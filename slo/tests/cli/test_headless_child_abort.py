"""Runner-owned child-control consumption (feature 94.a.4, T10).

``ChildAbortController`` tests run against the real ``ChildAbortStore`` on a
``tmp_path`` history root, a recording pool gateway at the consumer boundary and
a manual poll clock, so every tick is driven explicitly: no sleeps, no signals.
Runner tests compose the real ``HeadlessRunner`` with a real ``SubAgentPool``
whose only replaced boundary is the OS process (``FakeChildProcess``) and the
``FleetReaper`` identity/reap seams.
"""

from __future__ import annotations

import asyncio
import gc
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional, TypeVar
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator import child_abort
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortController, ChildAbortStore
from src.agents.slo_agent.orchestrator.dao import (
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.cli.headless import HeadlessRunner
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess, terminal_line

_PARENT: str = "orch-1"
_OWNER: str = "owner-1"
_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_RESTARTED_RUN_ID: str = "11111111-2222-4333-8444-555555555555"
_EXECUTION_ID: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"
_SECRET_SENTINEL: str = "SECRET-SENTINEL-prompt-text-9f3"
_BOUNDED_SECONDS: float = 2.0
"""Deadline for operations that must not block; never a timing oracle."""

_T = TypeVar("_T")


async def _bounded(awaitable: Awaitable[_T]) -> _T:
    """Await within the deadline so a regression fails instead of hanging."""
    return await asyncio.wait_for(awaitable, timeout=_BOUNDED_SECONDS)


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until ``predicate`` holds, bounded by a deadline."""

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=_BOUNDED_SECONDS)


@pytest.fixture(autouse=True)
async def _every_task_exception_retrieved() -> AsyncIterator[None]:
    """Fail any test that leaves a task exception unretrieved (a.4 decision-path closure).

    The loop's exception handler receives "Task exception was never retrieved"
    when an abandoned failed task is finalized; ``gc.collect`` forces those
    finalizers to run before this test's loop closes, so the report lands here.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    saved: Optional[Callable[[asyncio.AbstractEventLoop, dict[str, Any]], object]] = (
        loop.get_exception_handler()
    )
    unretrieved: list[str] = []
    loop.set_exception_handler(lambda _loop, context: unretrieved.append(str(context.get("message"))))
    try:
        yield
        gc.collect()
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(saved)
    assert unretrieved == []


class _ManualClock:
    """Poll clock whose ticks the test releases one at a time.

    ``waits`` counts entries into ``wait_next_tick``: an increment means the
    controller finished one complete tick and is idle until released or stopped.
    """

    def __init__(self) -> None:
        self.waits: int = 0
        self._release: Optional[asyncio.Future[None]] = None

    async def wait_next_tick(self, *, stop: asyncio.Event) -> None:
        release: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._release = release
        self.waits += 1
        stopped: asyncio.Future[None] = asyncio.ensure_future(self._stopped(stop=stop))
        try:
            await asyncio.wait({release, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopped.cancel()

    @staticmethod
    async def _stopped(*, stop: asyncio.Event) -> None:
        await stop.wait()

    async def tick(self) -> None:
        """Release one idle wait and return once the next full tick has run."""
        waits_before: int = self.waits
        assert self._release is not None
        self._release.set_result(None)
        await _until(lambda: self.waits > waits_before)


class _RecordingGateway:
    """Recording stand-in for ``SubAgentPool.abort_child`` at the consumer boundary."""

    def __init__(self) -> None:
        self.calls: list[ChildAbortRequestDAO] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.error: Optional[Exception] = None

    async def abort_child(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        self.calls.append(request)
        gate: Optional[asyncio.Event] = self.gates.get(request.session_id)
        if gate is not None:
            await gate.wait()
        if self.error is not None:
            raise self.error
        return ChildAbortOutcomeDAO.for_request(request=request, outcome="aborted", terminal_status="aborted")


def _capability(*, run_id: str = _RUN_ID) -> ChildControlCapabilityDAO:
    return ChildControlCapabilityDAO(
        run_id=run_id, owner_session_id=_OWNER, orchestrator_session_id=_PARENT, accepting=True
    )


def _request(*, run_id: str = _RUN_ID, session_id: str = "child-1", **overrides: str) -> ChildAbortRequestDAO:
    fields: dict[str, str] = {
        "request_id": str(uuid4()),
        "owner_session_id": _OWNER,
        "orchestrator_session_id": _PARENT,
        "session_id": session_id,
        "run_id": run_id,
        "execution_id": _EXECUTION_ID,
    }
    return ChildAbortRequestDAO.model_validate({**fields, **overrides})


class _Harness:
    """Real temp store + recording gateway + manual clock around one controller."""

    def __init__(self, *, root: Path, run_id: str = _RUN_ID) -> None:
        self.root: Path = root
        self.store: ChildAbortStore = ChildAbortStore(history_root=root, orchestrator_session_id=_PARENT)
        self.gateway: _RecordingGateway = _RecordingGateway()
        self.clock: _ManualClock = _ManualClock()
        self.controller: ChildAbortController = ChildAbortController(
            pool=self.gateway, store=self.store, capability=_capability(run_id=run_id), clock=self.clock
        )

    async def started(self) -> "_Harness":
        await _bounded(self.controller.start())
        await _until(lambda: self.clock.waits == 1)
        return self

    async def submit(self, *, request: ChildAbortRequestDAO) -> None:
        assert (await self.store.submit(request=request)).outcome == "requested"

    async def receipt(self, *, request: ChildAbortRequestDAO) -> Optional[ChildAbortOutcomeDAO]:
        return await self.store.load_receipt(request=request)

    async def capability(self) -> Optional[ChildControlCapabilityDAO]:
        return await self.store.load_capability()

    async def withdrawn(self) -> None:
        """Return once the on-disk capability reports ``accepting=False``."""
        while (capability := await self.capability()) is None or capability.accepting:
            await asyncio.sleep(0)


class TestControllerLifecycle:
    """Start/close ownership: capability first, one poller, one shutdown."""

    async def test_start_publishes_capability_before_admission(self, tmp_path: Path) -> None:
        """No request is consumed before the accepting capability is on disk."""
        harness = _Harness(root=tmp_path)
        order: list[str] = []
        real_write = harness.store.write_capability
        real_read = harness.store.read_pending

        async def write_capability(*, capability: ChildControlCapabilityDAO) -> None:
            order.append(f"capability:{capability.accepting}")
            await real_write(capability=capability)

        async def read_pending(*, run_id: str) -> list[ChildAbortRequestDAO]:
            order.append("read")
            return await real_read(run_id=run_id)

        with (
            patch.object(harness.store, "write_capability", side_effect=write_capability),
            patch.object(harness.store, "read_pending", side_effect=read_pending),
        ):
            await harness.started()
            await _bounded(harness.controller.close())

        assert order[:2] == ["capability:True", "read"]
        assert order[-1] == "capability:False"

    async def test_start_twice_and_start_after_close(self, tmp_path: Path) -> None:
        """A second start is a no-op; a start after close publishes nothing and polls nothing."""
        harness = await _Harness(root=tmp_path).started()
        await _bounded(harness.controller.start())
        assert harness.clock.waits == 1
        await _bounded(harness.controller.close())
        withdrawn = await harness.capability()

        await _bounded(harness.controller.start())

        assert withdrawn is not None and withdrawn.accepting is False
        assert await harness.capability() == withdrawn
        assert harness.clock.waits == 1

    async def test_capability_start_failure_creates_no_poller(self, tmp_path: Path) -> None:
        """A failed capability publication raises and starts no polling task or admission."""
        harness = _Harness(root=tmp_path)

        with patch.object(harness.store, "write_capability", side_effect=OSError("read-only")):
            with pytest.raises(OSError):
                await _bounded(harness.controller.start())

        assert harness.clock.waits == 0
        assert harness.gateway.calls == []
        await _bounded(harness.controller.close())  # closing a never-started controller is safe

    async def test_repeated_close_joins_one_shutdown(self, tmp_path: Path) -> None:
        """Concurrent and repeated closes share one shutdown that withdraws exactly once."""
        harness = await _Harness(root=tmp_path).started()
        withdrawals: list[bool] = []
        real_write = harness.store.write_capability

        async def write_capability(*, capability: ChildControlCapabilityDAO) -> None:
            withdrawals.append(capability.accepting)
            await real_write(capability=capability)

        with patch.object(harness.store, "write_capability", side_effect=write_capability):
            await _bounded(asyncio.gather(harness.controller.close(), harness.controller.close()))
            await _bounded(harness.controller.close())

        assert withdrawals == [False]

    async def test_caller_cancelled_during_close_keeps_cleanup_ownership(self, tmp_path: Path) -> None:
        """Cancelling the waiter does not cancel shutdown: the operation is joined and its receipt written."""
        harness = await _Harness(root=tmp_path).started()
        gate = harness.gateway.gates["child-1"] = asyncio.Event()
        request = _request()
        await harness.submit(request=request)
        await harness.clock.tick()
        await _until(lambda: len(harness.gateway.calls) == 1)

        waiter = asyncio.create_task(harness.controller.close())
        await _until(lambda: harness.controller._closing is not None)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        gate.set()
        await _bounded(harness.controller.close())

        receipt = await harness.receipt(request=request)
        assert receipt is not None and receipt.outcome == "aborted"

    async def test_close_joins_accepted_operation_and_flushes_receipt(self, tmp_path: Path) -> None:
        """Shutdown withdraws first, then waits for the accepted reap, then writes its receipt."""
        harness = await _Harness(root=tmp_path).started()
        gate = harness.gateway.gates["child-1"] = asyncio.Event()
        request = _request()
        await harness.submit(request=request)
        await harness.clock.tick()
        await _until(lambda: len(harness.gateway.calls) == 1)

        closing = asyncio.create_task(harness.controller.close())
        await _bounded(harness.withdrawn())
        assert not closing.done()
        gate.set()
        await _bounded(closing)

        receipt = await harness.receipt(request=request)
        assert receipt == ChildAbortOutcomeDAO.for_request(
            request=request, outcome="aborted", terminal_status="aborted"
        )

    async def test_capability_close_failure_still_joins_operations(self, tmp_path: Path) -> None:
        """A failed withdrawal is diagnosed with a fixed reason and never skips joins or receipts."""
        harness = await _Harness(root=tmp_path).started()
        gate = harness.gateway.gates["child-1"] = asyncio.Event()
        request = _request()
        await harness.submit(request=request)
        await harness.clock.tick()
        await _until(lambda: len(harness.gateway.calls) == 1)

        with (
            patch.object(harness.store, "write_capability", side_effect=OSError("gone")),
            patch.object(child_abort, "log_warning") as warn,
        ):
            closing = asyncio.create_task(harness.controller.close())
            await _until(lambda: warn.call_count >= 1)
            gate.set()
            await _bounded(closing)

        warn.assert_any_call(msg="child_control_capability_close_failed")
        receipt = await harness.receipt(request=request)
        assert receipt is not None and receipt.outcome == "aborted"


class TestControllerAdmission:
    """Every poll decision: reads, receipts, duplicates, failures and retries."""

    async def test_request_is_executed_once_and_receipted(self, tmp_path: Path) -> None:
        """A committed request reaches the pool once; its settled outcome becomes its receipt."""
        harness = await _Harness(root=tmp_path).started()
        request = _request()
        await harness.submit(request=request)

        await harness.clock.tick()
        await harness.clock.tick()

        assert harness.gateway.calls == [request]
        assert await harness.receipt(request=request) == ChildAbortOutcomeDAO.for_request(
            request=request, outcome="aborted", terminal_status="aborted"
        )
        await _bounded(harness.controller.close())
        assert harness.gateway.calls == [request]

    async def test_poll_read_failure_retries_next_tick(self, tmp_path: Path) -> None:
        """A failed scan is diagnosed and contained; the next tick reads again and admits."""
        harness = await _Harness(root=tmp_path).started()
        request = _request()
        await harness.submit(request=request)
        real_read = harness.store.read_pending
        attempts: list[int] = []

        async def flaky_read(*, run_id: str) -> list[ChildAbortRequestDAO]:
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("transient")
            return await real_read(run_id=run_id)

        with (
            patch.object(harness.store, "read_pending", side_effect=flaky_read),
            patch.object(child_abort, "log_warning") as warn,
        ):
            await harness.clock.tick()
            assert harness.gateway.calls == []
            await harness.clock.tick()

        warn.assert_any_call(msg="child_control_read_failed")
        await _until(lambda: harness.gateway.calls == [request])
        await _bounded(harness.controller.close())

    async def test_stop_during_receipt_read_admits_nothing(self, tmp_path: Path) -> None:
        """A request whose receipt read is in flight when close begins is never executed."""
        harness = await _Harness(root=tmp_path).started()
        request = _request()
        await harness.submit(request=request)
        reading = asyncio.Event()
        release = asyncio.Event()
        real_load = harness.store.load_receipt

        async def blocked_load(*, request: ChildAbortRequestDAO) -> Optional[ChildAbortOutcomeDAO]:
            reading.set()
            await release.wait()
            return await real_load(request=request)

        with patch.object(harness.store, "load_receipt", side_effect=blocked_load):
            harness.clock._release.set_result(None)  # type: ignore[union-attr]
            await _bounded(reading.wait())
            closing = asyncio.create_task(harness.controller.close())
            await _until(lambda: harness.controller._closing is not None)
            release.set()
            await _bounded(closing)

        assert harness.gateway.calls == []
        assert await harness.receipt(request=request) is None
        assert (
            tmp_path / _PARENT / "child-control.v1" / _RUN_ID / "requests" / f"{request.request_id}.json"
        ).exists()

    async def test_existing_receipt_skips_execution(self, tmp_path: Path) -> None:
        """A request already settled on disk is never handed to the pool again."""
        harness = await _Harness(root=tmp_path).started()
        request = _request()
        await harness.submit(request=request)
        settled = ChildAbortOutcomeDAO.for_request(request=request, outcome="already_terminal")
        await harness.store.write_receipt(request=request, outcome=settled)

        await harness.clock.tick()
        await _bounded(harness.controller.close())

        assert harness.gateway.calls == []
        assert await harness.receipt(request=request) == settled

    async def test_duplicate_request_joins_without_second_operation(self, tmp_path: Path) -> None:
        """A request still in flight on the next tick is not admitted twice."""
        harness = await _Harness(root=tmp_path).started()
        gate = harness.gateway.gates["child-1"] = asyncio.Event()
        request = _request()
        await harness.submit(request=request)

        await harness.clock.tick()
        await harness.clock.tick()
        await harness.clock.tick()
        gate.set()
        await _bounded(harness.controller.close())

        assert harness.gateway.calls == [request]

    async def test_two_ids_for_same_child_each_get_own_receipt(self, tmp_path: Path) -> None:
        """Different request IDs for one child both reach the pool (which joins) and each settles."""
        harness = await _Harness(root=tmp_path).started()
        first, second = _request(), _request()
        await harness.submit(request=first)
        await harness.submit(request=second)

        await harness.clock.tick()
        await _bounded(harness.controller.close())

        assert {r.request_id for r in harness.gateway.calls} == {first.request_id, second.request_id}
        for request in (first, second):
            receipt = await harness.receipt(request=request)
            assert receipt is not None and receipt.request_id == request.request_id

    async def test_blocked_reap_does_not_delay_another_childs_admission(self, tmp_path: Path) -> None:
        """Polling admits a second child's request while the first child's reap is still pending."""
        harness = await _Harness(root=tmp_path).started()
        gate = harness.gateway.gates["child-1"] = asyncio.Event()
        first = _request(session_id="child-1")
        await harness.submit(request=first)
        await harness.clock.tick()
        second = _request(session_id="child-2")
        await harness.submit(request=second)

        await harness.clock.tick()
        await _until(lambda: len(harness.gateway.calls) == 2)
        await harness.clock.tick()

        assert await harness.receipt(request=second) is not None
        assert await harness.receipt(request=first) is None
        gate.set()
        await _bounded(harness.controller.close())
        assert await harness.receipt(request=first) is not None

    async def test_operation_exception_is_unresolved(self, tmp_path: Path) -> None:
        """An unexpected pool failure settles as unresolved with fixed text; no exception text leaks."""
        harness = await _Harness(root=tmp_path).started()
        harness.gateway.error = RuntimeError(_SECRET_SENTINEL)
        request = _request()
        await harness.submit(request=request)

        with patch.object(child_abort, "log_warning") as warn:
            await harness.clock.tick()
            await _bounded(harness.controller.close())

        receipt = await harness.receipt(request=request)
        assert receipt == ChildAbortOutcomeDAO.for_request(request=request, outcome="unresolved")
        warn.assert_any_call(msg="child_control_operation_unresolved")
        assert _SECRET_SENTINEL not in repr(warn.call_args_list)
        assert len(harness.gateway.calls) == 1

    async def test_receipt_failure_retries_write_only(self, tmp_path: Path) -> None:
        """A failed receipt write is retried on later ticks without repeating cancellation."""
        harness = await _Harness(root=tmp_path).started()
        request = _request()
        await harness.submit(request=request)
        real_write = harness.store.write_receipt
        writes: list[int] = []

        async def flaky_write(*, request: ChildAbortRequestDAO, outcome: ChildAbortOutcomeDAO) -> None:
            writes.append(1)
            if len(writes) == 1:
                raise OSError("disk full")
            await real_write(request=request, outcome=outcome)

        with (
            patch.object(harness.store, "write_receipt", side_effect=flaky_write),
            patch.object(child_abort, "log_warning") as warn,
        ):
            await harness.clock.tick()
            await _until(lambda: len(harness.gateway.calls) == 1)
            await harness.clock.tick()
            assert await harness.receipt(request=request) is None
            await harness.clock.tick()

        warn.assert_any_call(msg="child_control_receipt_write_failed")
        assert len(harness.gateway.calls) == 1
        assert len(writes) == 2
        receipt = await harness.receipt(request=request)
        assert receipt is not None and receipt.outcome == "aborted"
        await _bounded(harness.controller.close())

    async def test_stale_run_request_is_refused_and_never_executed(self, tmp_path: Path) -> None:
        """A request in this run's directory naming another run gets unavailable, never execution."""
        harness = await _Harness(root=tmp_path).started()
        stale = _request(run_id=_RESTARTED_RUN_ID)
        requests_dir = OrchestrationLayout.child_abort_requests_dir(
            history_root=tmp_path, orchestrator_session_id=_PARENT, run_id=_RUN_ID
        )
        requests_dir.mkdir(parents=True)
        (requests_dir / f"{stale.request_id}.json").write_text(stale.model_dump_json(), encoding="utf-8")

        await harness.clock.tick()
        await _bounded(harness.controller.close())

        assert harness.gateway.calls == []
        receipt_path = OrchestrationLayout.child_abort_receipt_path(
            history_root=tmp_path,
            orchestrator_session_id=_PARENT,
            run_id=_RUN_ID,
            request_id=stale.request_id,
        )
        assert ChildAbortOutcomeDAO.model_validate_json(receipt_path.read_bytes()).outcome == "unavailable"

    async def test_restarted_runner_never_executes_old_run_requests(self, tmp_path: Path) -> None:
        """A resumed runner has a fresh run_id: requests committed for the old run stay unexecuted."""
        old = await _Harness(root=tmp_path).started()
        old_request = _request()
        await old.submit(request=old_request)
        await _bounded(old.controller.close())  # closed before its next tick: request never admitted
        assert old.gateway.calls == []

        restarted = await _Harness(root=tmp_path, run_id=_RESTARTED_RUN_ID).started()
        await restarted.clock.tick()
        with pytest.raises(ValueError):
            await restarted.store.submit(request=_request())  # old-run submission refused
        await _bounded(restarted.controller.close())

        assert restarted.gateway.calls == []
        assert await restarted.receipt(request=old_request) is None
        assert (
            tmp_path / _PARENT / "child-control.v1" / _RUN_ID / "requests" / f"{old_request.request_id}.json"
        ).exists()


# ── HeadlessRunner composition ───────────────────────────────────────────────

_TUI_OWNER: str = "tui-owner"
_SPAWN_SEAM: str = "asyncio.create_subprocess_exec"
_IDENTITY_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome"
_REAP_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.reap"


class _ChildFleet:
    """Controlled OS boundary: one ``FakeChildProcess`` per spawn; reap may be gated."""

    def __init__(self) -> None:
        self.children: list[FakeChildProcess] = []
        self.reaped_pids: list[int] = []
        self.reap_gate: Optional[asyncio.Event] = None

    async def spawn(self, *args: object, **kwargs: object) -> FakeChildProcess:
        child = FakeChildProcess(
            lines=[terminal_line(content="natural")], exit_code=0, pid=7000 + len(self.children)
        )
        self.children.append(child)
        return child

    async def reap(self, *, pid: int) -> str:
        self.reaped_pids.append(pid)
        if self.reap_gate is not None:
            await self.reap_gate.wait()
        next(child for child in self.children if child.pid == pid).exit()
        return "graceful"

    def exit_all(self) -> None:
        for child in self.children:
            child.exit()


class _DispatchingSession:
    """Session double whose stream blocks inside a real pool dispatch, like a provider tool call."""

    def __init__(self, *, root: Path, session_ids: list[str]) -> None:
        self.session_id: str = _PARENT
        self.history_root: Optional[Path] = None
        self.abort: MagicMock = MagicMock()
        self._subscribers: list[Callable[[AgentStreamEventDAO], Awaitable[None]]] = []
        self._session_ids: list[str] = session_ids
        self._sub_agent_pool: SubAgentPool = SubAgentPool(
            orchestrator_session_id=_PARENT,
            default_model=None,
            relay=self._relay,
            owner_session_id=_TUI_OWNER,
            run_id=str(uuid4()),
            history_root=root,
        )

    @property
    def pool(self) -> SubAgentPool:
        return self._sub_agent_pool

    def subscribe(self, *, handler: Callable[[AgentStreamEventDAO], Awaitable[None]]) -> None:
        self._subscribers.append(handler)

    async def _relay(self, event: AgentStreamEventDAO) -> None:
        for subscriber in self._subscribers:
            await subscriber(event)

    async def invoke(self, *, text: str):  # type: ignore[no-untyped-def]
        tasks = [
            SubAgentTaskDAO(
                task_summary="Observe the child cancellation boundary",
                task_id=f"t-{sid}",
                prompt=text,
                session_id=sid,
            )
            for sid in self._session_ids
        ]
        if tasks:
            await self._sub_agent_pool.dispatch(mode="parallel", tasks=tasks)
        terminal = AgentStreamEventDAO(kind="run_completed", content="done")
        await self._relay(terminal)
        yield terminal


class _RecordingWatchdog:
    """Watchdog double: records its whole-abort path and starts no thread."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs: dict[str, object] = kwargs

    def start(self) -> None:
        """Provide the start seam."""

    def stop(self) -> None:
        """Provide the stop seam."""


class _RunnerHarness:
    """Real HeadlessRunner + real pool under a temp history root; only OS seams replaced."""

    def __init__(
        self, *, root: Path, session_ids: list[str], notify_session_id: Optional[str] = _TUI_OWNER
    ) -> None:
        self.root: Path = root
        self.session: _DispatchingSession = _DispatchingSession(root=root, session_ids=session_ids)
        self.fleet: _ChildFleet = _ChildFleet()
        self.tui_store: ChildAbortStore = ChildAbortStore(history_root=root, orchestrator_session_id=_PARENT)
        self.runner: HeadlessRunner = HeadlessRunner(
            config=SessionConfigDAO(workdir=root, model_name="faux", enable_history=False),
            orchestrator_mode=True,
            notify_session_id=notify_session_id,
            notifier=AsyncMock(),
        )

    @contextmanager
    def boundaries(self) -> Iterator[None]:
        with (
            patch("src.cli.headless.SloAgentSession.build", return_value=self.session),
            patch("src.cli.headless.default_history_root", return_value=self.root),
            patch("src.cli.headless.HeadlessWatchdog", side_effect=_RecordingWatchdog),
            patch(_SPAWN_SEAM, new=self.fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=self.fleet.reap),
            patch.object(child_abort, "POLL_INTERVAL_SECONDS", 0.01),
        ):
            yield

    def running(self, *session_ids: str) -> Callable[[], bool]:
        def all_running() -> bool:
            entries = [self.session.pool.registry.get(session_id=sid) for sid in session_ids]
            return all(entry is not None and entry.status == "running" for entry in entries)

        return all_running

    async def accepting_capability(self) -> ChildControlCapabilityDAO:
        while (capability := await self.tui_store.load_capability()) is None or not capability.accepting:
            await asyncio.sleep(0)
        return capability

    def request_for(self, *, capability: ChildControlCapabilityDAO, session_id: str) -> ChildAbortRequestDAO:
        entry = self.session.pool.registry.get(session_id=session_id)
        assert entry is not None
        return ChildAbortRequestDAO(
            request_id=str(uuid4()),
            owner_session_id=_TUI_OWNER,
            orchestrator_session_id=_PARENT,
            session_id=session_id,
            run_id=capability.run_id,
            execution_id=entry.execution_id,
        )

    async def receipt(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        while (receipt := await self.tui_store.load_receipt(request=request)) is None:
            await asyncio.sleep(0)
        return receipt

    async def withdrawn(self) -> None:
        while (capability := await self.tui_store.load_capability()) is None or capability.accepting:
            await asyncio.sleep(0)

    def pid_of(self, *, session_id: str) -> int:
        entry = self.session.pool.registry.get(session_id=session_id)
        assert entry is not None and entry.pid is not None
        return entry.pid

    def control_files(self) -> list[Path]:
        control_dir = OrchestrationLayout.child_control_dir(
            history_root=self.root, orchestrator_session_id=_PARENT
        )
        return (
            sorted(path for path in control_dir.rglob("*") if path.is_file()) if control_dir.exists() else []
        )


class TestHeadlessRunnerChildControl:
    """The runner publishes, consumes and withdraws child control around a blocked dispatch."""

    async def test_consumer_runs_during_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A request is executed while the stream awaits dispatch; only the target is reaped."""
        monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-1")
        harness = _RunnerHarness(root=tmp_path, session_ids=["child-1", "child-2"])
        drained_with_capability: list[Optional[ChildControlCapabilityDAO]] = []
        real_drain = harness.runner._drain_fleet

        async def recording_drain() -> bool:
            drained_with_capability.append(await harness.tui_store.load_capability())
            return await real_drain()

        with harness.boundaries(), patch.object(harness.runner, "_drain_fleet", side_effect=recording_drain):
            run = asyncio.create_task(harness.runner.invoke(prompt=_SECRET_SENTINEL))
            await _until(harness.running("child-1", "child-2"))
            capability = await _bounded(harness.accepting_capability())
            request = harness.request_for(capability=capability, session_id="child-1")
            target_pid, sibling_pid = harness.pid_of(session_id="child-1"), harness.pid_of(
                session_id="child-2"
            )

            assert (await harness.tui_store.submit(request=request)).outcome == "requested"
            receipt = await _bounded(harness.receipt(request=request))

            assert not run.done()  # dispatch is still blocked on the sibling
            assert harness.running("child-2")()
            next(child for child in harness.fleet.children if child.pid == sibling_pid).exit()
            exit_code = await _bounded(run)

        assert exit_code == 0
        assert (receipt.outcome, receipt.terminal_status) == ("aborted", "aborted")
        assert harness.fleet.reaped_pids == [target_pid]
        assert capability.run_id == harness.session.pool.run_id
        assert capability.owner_session_id == _TUI_OWNER
        assert drained_with_capability and drained_with_capability[0] is not None
        assert drained_with_capability[0].accepting is False  # closed before the final fleet drain
        assert not (tmp_path / _PARENT / "abort_request.json").exists()
        for path in harness.control_files():
            assert _SECRET_SENTINEL not in path.read_text(encoding="utf-8")

    async def test_run_without_owner_context_publishes_no_capability(self, tmp_path: Path) -> None:
        """A headless run with no explicit launch owner exposes no child control at all."""
        harness = _RunnerHarness(root=tmp_path, session_ids=[], notify_session_id=None)

        with harness.boundaries():
            exit_code = await _bounded(harness.runner.invoke(prompt="hi"))

        assert exit_code == 0
        assert not OrchestrationLayout.child_control_dir(
            history_root=tmp_path, orchestrator_session_id=_PARENT
        ).exists()

    async def test_plain_headless_run_publishes_no_capability(self, tmp_path: Path) -> None:
        """Without orchestrator mode there is no pool, so no controller starts."""
        harness = _RunnerHarness(root=tmp_path, session_ids=[])
        harness.runner._orchestrator_mode = False
        harness.session._sub_agent_pool = None  # type: ignore[assignment]

        with harness.boundaries():
            exit_code = await _bounded(harness.runner.invoke(prompt="hi"))

        assert exit_code == 0
        assert harness.control_files() == []

    async def test_start_failure_leaves_execution_usable(self, tmp_path: Path) -> None:
        """A capability publication failure is a fixed diagnostic; the workflow still runs to completion."""
        harness = _RunnerHarness(root=tmp_path, session_ids=["child-1"])

        with (
            harness.boundaries(),
            patch.object(ChildAbortStore, "write_capability", side_effect=OSError(_SECRET_SENTINEL)),
            patch("src.cli.headless.log_warning") as warn,
        ):
            run = asyncio.create_task(harness.runner.invoke(prompt="hi"))
            await _until(harness.running("child-1"))
            harness.fleet.exit_all()
            exit_code = await _bounded(run)

        assert exit_code == 0
        warn.assert_any_call(msg="child_control_unavailable")
        assert _SECRET_SENTINEL not in repr(warn.call_args_list)
        assert harness.control_files() == []

    async def test_composition_failure_leaves_execution_usable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An owner that fails identity validation leaves child control unavailable, not the run failed."""
        invalid_owner: str = "owner with space"
        harness = _RunnerHarness(root=tmp_path, session_ids=["child-1"], notify_session_id=invalid_owner)
        harness.session._sub_agent_pool = SubAgentPool(
            orchestrator_session_id=_PARENT,
            default_model=None,
            relay=harness.session._relay,
            owner_session_id=invalid_owner,
            run_id=str(uuid4()),
            history_root=tmp_path,
        )

        with harness.boundaries(), patch("src.cli.headless.log_warning") as warn:
            run = asyncio.create_task(harness.runner.invoke(prompt="hi"))
            try:
                await _until(harness.running("child-1"))
            finally:
                harness.fleet.exit_all()
            exit_code = await _bounded(run)

        stdout: str = capsys.readouterr().out
        assert exit_code == 0
        assert len(harness.fleet.children) == 1
        warn.assert_any_call(msg="child_control_unavailable")
        assert "validation error" not in repr(warn.call_args_list)
        assert "run_failed" not in stdout
        assert "validation error" not in stdout
        assert harness.control_files() == []

    async def test_runner_cancellation_still_joins_close(self, tmp_path: Path) -> None:
        """Cancelling the runner (even twice) during close does not abandon the accepted reap or receipt."""
        harness = _RunnerHarness(root=tmp_path, session_ids=["child-1", "child-2"])
        harness.fleet.reap_gate = asyncio.Event()

        with harness.boundaries():
            run = asyncio.create_task(harness.runner.invoke(prompt="hi"))
            await _until(harness.running("child-1", "child-2"))
            capability = await _bounded(harness.accepting_capability())
            request = harness.request_for(capability=capability, session_id="child-1")
            await harness.tui_store.submit(request=request)
            await _until(lambda: len(harness.fleet.reaped_pids) == 1)

            run.cancel()
            await _bounded(harness.withdrawn())
            run.cancel()
            await asyncio.sleep(0)
            assert not run.done()  # close still joining the accepted reap
            harness.fleet.reap_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await _bounded(run)
            receipt = await _bounded(harness.receipt(request=request))
            harness.fleet.exit_all()
            await _until(lambda: not harness.session.pool._active_by_session_id)

        assert receipt.outcome == "aborted"

    async def test_restarted_runner_refuses_old_run_request(self, tmp_path: Path) -> None:
        """A committed-but-unadmitted request from a previous run is never executed by the next run."""
        first = _RunnerHarness(root=tmp_path, session_ids=[])
        with first.boundaries(), patch.object(ChildAbortController, "start", new=AsyncMock()):
            assert await _bounded(first.runner.invoke(prompt="hi")) == 0
        old_request = _request(run_id=first.session.pool.run_id, session_id="child-1")
        old_requests_dir = OrchestrationLayout.child_abort_requests_dir(
            history_root=tmp_path, orchestrator_session_id=_PARENT, run_id=old_request.run_id
        )
        old_requests_dir.mkdir(parents=True)
        (old_requests_dir / f"{old_request.request_id}.json").write_text(
            old_request.model_dump_json(), encoding="utf-8"
        )

        second = _RunnerHarness(root=tmp_path, session_ids=["child-1"])
        with second.boundaries():
            run = asyncio.create_task(second.runner.invoke(prompt="hi"))
            await _until(second.running("child-1"))
            capability = await _bounded(second.accepting_capability())
            stale = old_request.model_copy(update={"owner_session_id": _TUI_OWNER})
            with pytest.raises(ValueError):
                await second.tui_store.submit(request=stale)
            second.fleet.exit_all()
            assert await _bounded(run) == 0

        assert capability.run_id != old_request.run_id
        assert second.fleet.reaped_pids == []
        assert await second.tui_store.load_receipt(request=old_request) is None
        results = second.session.pool.registry.get(session_id="child-1")
        assert results is not None and results.status == "completed"
