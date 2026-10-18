"""Child-only pool cancellation and exact slot/pending/spawn races (feature 94.a.4, T09).

Orchestration tests over a real ``SubAgentPool`` whose registry is bound to a real
temp-owned ``FleetStore``. Only the OS boundary is replaced: a controlled
``FakeChildProcess`` stands in for ``asyncio.create_subprocess_exec`` and the
``FleetReaper`` identity/reap seams are injected. No subprocess, signal, provider
or user history is touched; every write resolves below ``tmp_path``. Ordering is
controlled with Events/Futures; bounded waits are deadlines, never oracles.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional, TypeVar
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import (
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ExecutionIndexDAO,
    OrchestratorResultDAO,
    SubAgentResultDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess, terminal_line
from tests.agents.slo_agent.orchestrator.released_schemas import (
    ReleasedFleetSnapshotDAO,
    ReleasedSubAgentResultDAO,
)

_PARENT: str = "orch-1"
_OWNER: str = "owner-1"
_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_BOUNDED_SECONDS: float = 2.0
"""Deadline for operations that must not block; never a timing oracle."""

_T = TypeVar("_T")

_TERMINAL_KINDS: frozenset[str] = frozenset({"sub_agent_completed", "sub_agent_failed", "sub_agent_aborted"})

_RELEASED_STATUS_FIELDS: frozenset[str] = frozenset(ReleasedSubAgentResultDAO.model_fields)
"""Every field a released status.json reader accepts; the winner must match on all of them."""


class _PoolHarness:
    """One pool composed with temp-owned identity, recording relayed events and wrappers.

    ``wrappers`` keeps every incarnation's ``SubAgentProcess`` keyed by
    ``(session_id, execution_id)``. It is captured on the spawned event, when the
    pool has already installed the wrapper, so the wrapper's cached terminal
    winner stays readable after the pool's teardown forgets it.
    """

    def __init__(
        self, *, tmp_path: Path, relay_hook: Optional[Callable[[AgentStreamEventDAO], Awaitable[None]]] = None
    ) -> None:
        self.root: Path = tmp_path
        self.events: list[AgentStreamEventDAO] = []
        self.wrappers: dict[tuple[str, str], SubAgentProcess] = {}
        self._relay_hook: Optional[Callable[[AgentStreamEventDAO], Awaitable[None]]] = relay_hook
        self.pool: SubAgentPool = SubAgentPool(
            orchestrator_session_id=_PARENT,
            default_model=None,
            relay=self._relay,
            owner_session_id=_OWNER,
            run_id=_RUN_ID,
            history_root=tmp_path,
        )

    async def _relay(self, event: AgentStreamEventDAO) -> None:
        self.events.append(event)
        if event.kind == "sub_agent_spawned":
            self._remember_wrapper(session_id=str(event.sub_agent_id))
        if self._relay_hook is not None:
            await self._relay_hook(event)

    def _remember_wrapper(self, *, session_id: str) -> None:
        process: SubAgentProcess = self.pool._active_by_session_id[session_id]
        self.wrappers[(session_id, process.execution_id)] = process

    def wrapper_for(self, *, session_id: str, execution_id: str) -> SubAgentProcess:
        """Return the exact incarnation's wrapper captured at its spawned event."""
        return self.wrappers[(session_id, execution_id)]

    def terminal_kinds(self, *, session_id: str) -> list[str]:
        return [e.kind for e in self.events if e.kind in _TERMINAL_KINDS and e.sub_agent_id == session_id]

    def execution_id(self, *, session_id: str) -> str:
        entry = self.pool.registry.get(session_id=session_id)
        assert entry is not None
        return entry.execution_id

    def dispatch(
        self, *, session_ids: list[str], mode: str = "parallel"
    ) -> asyncio.Task[OrchestratorResultDAO]:
        tasks = [SubAgentTaskDAO(task_id=f"t-{sid}", prompt="work", session_id=sid) for sid in session_ids]
        return asyncio.create_task(self.pool.dispatch(mode=mode, tasks=tasks))  # type: ignore[arg-type]


async def _bounded(awaitable: Awaitable[_T]) -> _T:
    """Await within the deadline so a regression fails instead of hanging."""
    return await asyncio.wait_for(awaitable, timeout=_BOUNDED_SECONDS)


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until a state predicate holds, bounded by a deadline."""

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=_BOUNDED_SECONDS)


class TestIncarnationSynchronization:
    """Wrapper, abort event and completion future are installed per incarnation."""

    async def test_synchronization_installed_before_spawned_event(self, tmp_path: Path) -> None:
        """A spawned-event observer finds wrapper, event and unsettled future; no orphan interval."""
        observed: list[tuple[bool, bool, bool]] = []
        harness: _PoolHarness

        async def on_event(event: AgentStreamEventDAO) -> None:
            if event.kind != "sub_agent_spawned":
                return
            session_id: str = str(event.sub_agent_id)
            identity = (session_id, str(event.metadata["execution_id"]))
            pool = harness.pool
            observed.append(
                (
                    pool._active_by_session_id[session_id].execution_id == identity[1],
                    not pool._child_abort_events[identity].is_set(),
                    not pool._child_completion[identity].done(),
                )
            )

        harness = _PoolHarness(tmp_path=tmp_path, relay_hook=on_event)
        child = FakeChildProcess(lines=[terminal_line(content="done")], exit_code=0)
        child.exit()

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)):
            result = await harness.dispatch(session_ids=["child-1"])

        execution_id = harness.execution_id(session_id="child-1")
        completion = harness.pool._child_completion[("child-1", execution_id)]
        assert observed == [(True, True, True)]
        assert completion.done() and completion.result() == result.results[0]
        assert harness.pool._active_by_session_id == {}

    async def test_completion_future_settles_once_when_runner_errors(self, tmp_path: Path) -> None:
        """An unexpected runner error still settles the exact future, with the error retrieved."""
        harness = _PoolHarness(tmp_path=tmp_path)

        with patch.object(SubAgentProcess, "run", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError, match="boom"):
                await harness.dispatch(session_ids=["child-1"])

        execution_id = harness.execution_id(session_id="child-1")
        completion = harness.pool._child_completion[("child-1", execution_id)]
        assert completion.done() and isinstance(completion.exception(), RuntimeError)
        assert harness.pool._active_by_session_id == {}

    async def test_reused_session_prunes_old_incarnation_synchronization(self, tmp_path: Path) -> None:
        """A new incarnation drops the old entries; the old future is never settled again."""
        harness = _PoolHarness(tmp_path=tmp_path)

        def finished_child() -> FakeChildProcess:
            child = FakeChildProcess(lines=[terminal_line()], exit_code=0)
            child.exit()
            return child

        with patch(
            "asyncio.create_subprocess_exec", new=AsyncMock(side_effect=lambda *a, **k: finished_child())
        ):
            await harness.dispatch(session_ids=["child-1"])
            old_identity = ("child-1", harness.execution_id(session_id="child-1"))
            old_future = harness.pool._child_completion[old_identity]
            await harness.dispatch(session_ids=["child-1"])

        new_identity = ("child-1", harness.execution_id(session_id="child-1"))
        assert new_identity != old_identity
        assert set(harness.pool._child_completion) == {new_identity}
        assert set(harness.pool._child_abort_events) == {new_identity}
        assert old_future.done() and old_future.result().execution_id == old_identity[1]


class _GatedSemaphore(asyncio.Semaphore):
    """Semaphore whose acquisition waits a test gate and can run a hook on success.

    ``acquire_count`` and ``release_count`` are white-box accounting oracles;
    production never reads them. ``acquire_count`` counts entered acquisitions,
    so a waiter task that ran and was joined before the caller returned is
    still visible after ``asyncio.all_tasks()`` has forgotten it.
    """

    def __init__(self, *, value: int) -> None:
        super().__init__(value)
        self.gate: asyncio.Event = asyncio.Event()
        self.gate.set()
        self.on_acquired: Optional[Callable[[], object]] = None
        self.acquire_count: int = 0
        self.release_count: int = 0

    async def acquire(self) -> bool:  # type: ignore[override]
        self.acquire_count += 1
        await self.gate.wait()
        acquired: bool = await super().acquire()
        if self.on_acquired is not None:
            self.on_acquired()
        return acquired

    def release(self) -> None:
        self.release_count += 1
        super().release()


class _SlowCancelEvent(asyncio.Event):
    """Abort event whose waiter settles cancellation only when the test allows it."""

    def __init__(self) -> None:
        super().__init__()
        self.cleanup_started: bool = False
        self.release_cleanup: asyncio.Event = asyncio.Event()

    async def wait(self) -> bool:  # type: ignore[override]
        try:
            return await super().wait()
        except asyncio.CancelledError:
            self.cleanup_started = True
            await self.release_cleanup.wait()
            raise


_SID: str = "child-1"
_EID: str = "0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40"


def _slot_pool(
    *, tmp_path: Path, semaphore: asyncio.Semaphore, event: Optional[asyncio.Event] = None
) -> tuple[SubAgentPool, asyncio.Event]:
    """Pool with an injected semaphore and one incarnation's abort event installed."""
    harness = _PoolHarness(tmp_path=tmp_path)
    harness.pool._semaphore = semaphore
    abort_event: asyncio.Event = event if event is not None else asyncio.Event()
    harness.pool._child_abort_events[(_SID, _EID)] = abort_event
    return harness.pool, abort_event


def _other_tasks() -> set[asyncio.Task[object]]:
    """Return every live task except the running test's own task."""
    return {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}


class TestAcquireChildSlot:
    """Exact slot transfer/rollback matrix (CRITICAL-2)."""

    @pytest.mark.parametrize("free_permits", [1, 0])
    async def test_slot_event_preset(self, tmp_path: Path, free_permits: int) -> None:
        """A preset event refuses at once: no acquire attempted, no rollback, permits unchanged."""
        semaphore = _GatedSemaphore(value=free_permits)
        pool, event = _slot_pool(tmp_path=tmp_path, semaphore=semaphore)
        event.set()
        tasks_before = _other_tasks()

        transferred = await pool._acquire_child_slot(session_id=_SID, execution_id=_EID)

        assert transferred is False
        assert (semaphore.acquire_count, semaphore.release_count) == (0, 0)
        assert _other_tasks() == tasks_before
        assert semaphore._value == free_permits

    async def test_slot_normal_and_waiting_abort(self, tmp_path: Path) -> None:
        """Normal acquire transfers one permit; a waiting abort holds none; a sibling acquires after."""
        semaphore = _GatedSemaphore(value=1)
        pool, event = _slot_pool(tmp_path=tmp_path, semaphore=semaphore)

        assert await pool._acquire_child_slot(session_id=_SID, execution_id=_EID) is True
        assert semaphore._value == 0

        waiting = asyncio.create_task(pool._acquire_child_slot(session_id=_SID, execution_id=_EID))
        await _until(lambda: bool(semaphore._waiters))
        event.set()
        assert await asyncio.wait_for(waiting, timeout=_BOUNDED_SECONDS) is False
        assert (semaphore._value, semaphore.release_count) == (0, 0)

        semaphore.release()  # the caller of the transferred permit releases it once
        sibling = asyncio.create_task(semaphore.acquire())
        assert await asyncio.wait_for(sibling, timeout=_BOUNDED_SECONDS) is True
        assert semaphore._value == 0
        assert _other_tasks() == set()

    async def test_slot_abort_during_waiter_join(self, tmp_path: Path) -> None:
        """Abort admitted while cleanup joins after a successful acquire: rollback, False."""
        semaphore = _GatedSemaphore(value=1)
        event = _SlowCancelEvent()
        pool, _ = _slot_pool(tmp_path=tmp_path, semaphore=semaphore, event=event)

        helper = asyncio.create_task(pool._acquire_child_slot(session_id=_SID, execution_id=_EID))
        await _until(lambda: event.cleanup_started)
        event.set()  # admission lands while the abort waiter is still settling
        event.release_cleanup.set()

        assert await asyncio.wait_for(helper, timeout=_BOUNDED_SECONDS) is False
        assert (semaphore._value, semaphore.release_count) == (1, 1)
        assert _other_tasks() == set()

    async def test_slot_runner_cancel_after_acquire(self, tmp_path: Path) -> None:
        """Runner cancelled after acquire succeeds, before wait resumes: join, rollback, raise."""
        semaphore = _GatedSemaphore(value=1)
        pool, _ = _slot_pool(tmp_path=tmp_path, semaphore=semaphore)
        helper: asyncio.Task[bool] = asyncio.create_task(
            pool._acquire_child_slot(session_id=_SID, execution_id=_EID)
        )
        semaphore.on_acquired = helper.cancel

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(helper), timeout=_BOUNDED_SECONDS)

        assert helper.cancelled()
        assert (semaphore._value, semaphore.release_count) == (1, 1)
        assert _other_tasks() == set()

    async def test_slot_runner_cancel_during_join(self, tmp_path: Path) -> None:
        """Repeated runner cancellation during waiter cleanup still joins and rolls back once."""
        semaphore = _GatedSemaphore(value=1)
        event = _SlowCancelEvent()
        pool, _ = _slot_pool(tmp_path=tmp_path, semaphore=semaphore, event=event)

        helper = asyncio.create_task(pool._acquire_child_slot(session_id=_SID, execution_id=_EID))
        await _until(lambda: event.cleanup_started)
        helper.cancel()
        await asyncio.sleep(0)
        helper.cancel()
        await asyncio.sleep(0)
        assert not helper.done()
        event.release_cleanup.set()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(helper), timeout=_BOUNDED_SECONDS)
        assert (semaphore._value, semaphore.release_count) == (1, 1)
        assert _other_tasks() == set()


# ── abort_child gateway ──────────────────────────────────────────────────────

_IDENTITY_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome"
_REAP_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.reap"


def _request(*, harness: _PoolHarness, session_id: str = "child-1", **overrides: str) -> ChildAbortRequestDAO:
    """Build an exact current-run request for the session's current incarnation."""
    fields: dict[str, str] = {
        "request_id": str(uuid4()),
        "owner_session_id": _OWNER,
        "orchestrator_session_id": _PARENT,
        "session_id": session_id,
        "run_id": _RUN_ID,
        "execution_id": overrides.pop("execution_id", "") or harness.execution_id(session_id=session_id),
    }
    return ChildAbortRequestDAO.model_validate({**fields, **overrides})


class _ChildFleet:
    """Controlled OS boundary: one ``FakeChildProcess`` per spawn, in spawn order."""

    def __init__(self) -> None:
        self.children: list[FakeChildProcess] = []
        self.reaped_pids: list[int] = []
        self.exit_on_spawn: bool = False

    async def spawn(self, *args: object, **kwargs: object) -> FakeChildProcess:
        child = FakeChildProcess(
            lines=[terminal_line(content="natural")], exit_code=0, pid=5000 + len(self.children)
        )
        self.children.append(child)
        if self.exit_on_spawn:
            child.exit()
        return child

    async def reap(self, *, pid: int) -> str:
        """Confirm graceful termination of exactly the identified child."""
        self.reaped_pids.append(pid)
        next(child for child in self.children if child.pid == pid).exit()
        return "graceful"

    def child_for(self, *, harness: _PoolHarness, session_id: str) -> FakeChildProcess:
        entry = harness.pool.registry.get(session_id=session_id)
        assert entry is not None and entry.pid is not None
        return next(child for child in self.children if child.pid == entry.pid)


def _running(*, harness: _PoolHarness, session_id: str) -> Callable[[], bool]:
    return (
        lambda: (e := harness.pool.registry.get(session_id=session_id)) is not None and e.status == "running"
    )


def _assert_projections_agree(*, harness: _PoolHarness, winner: SubAgentResultDAO) -> None:
    """Result, registry, wrapper cache, status.json, fleet.json and versioned evidence agree.

    status.json is compared on every released field and its exact bytes are bound
    to the verified terminal evidence digest.
    """
    session_id = winner.session_id
    entry = harness.pool.registry.get(session_id=session_id)
    assert entry is not None
    assert (entry.status, entry.exit_code, entry.last_text, entry.execution_id) == (
        winner.status,
        winner.exit_code,
        winner.answer,
        winner.execution_id,
    )
    assert (
        harness.pool.registry.terminal_result(session_id=session_id, execution_id=winner.execution_id)
        == winner
    )
    wrapper: SubAgentProcess = harness.wrapper_for(session_id=session_id, execution_id=winner.execution_id)
    assert wrapper._terminal_result_built == winner
    status_bytes: bytes = (harness.root / _PARENT / "children" / session_id / "status.json").read_bytes()
    status = ReleasedSubAgentResultDAO.model_validate_json(status_bytes)
    assert status.model_dump() == winner.model_dump(include=set(_RELEASED_STATUS_FIELDS))
    fleet = ReleasedFleetSnapshotDAO.model_validate_json((harness.root / _PARENT / "fleet.json").read_bytes())
    fleet_entry = next(e for e in fleet.entries if e.session_id == session_id)
    assert (fleet_entry.status, fleet_entry.exit_code) == (winner.status, winner.exit_code)
    index = ExecutionIndexDAO.model_validate_json(
        (harness.root / _PARENT / "execution-index.v1.json").read_bytes()
    )
    assert index.executions[session_id] == winner.execution_id
    evidence = FleetStore.load_verified_execution(
        history_root=harness.root, orchestrator_session_id=_PARENT, child_session_id=session_id
    )
    assert evidence is not None
    assert (evidence.phase, evidence.status, evidence.execution_id, evidence.status_sha256) == (
        "terminal",
        winner.status,
        winner.execution_id,
        hashlib.sha256(status_bytes).hexdigest(),
    )


class TestAbortChildRefusals:
    """Independent owner/parent/run/execution validation before any cancellation."""

    @pytest.mark.parametrize(
        "override",
        [
            {"owner_session_id": "intruder"},
            {"orchestrator_session_id": "other-orch"},
            {"run_id": "11111111-2222-4333-8444-555555555555"},
            {"execution_id": "22222222-3333-4444-8555-666666666666"},
        ],
    )
    async def test_mismatched_identity_is_not_owned_and_cancels_nothing(
        self, tmp_path: Path, override: dict[str, str]
    ) -> None:
        """Any identity mismatch refuses not_owned; the child keeps running untouched."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            request = _request(harness=harness, **override)

            outcome = await _bounded(harness.pool.abort_child(request=request))

            assert (outcome.outcome, outcome.request_id) == ("not_owned", request.request_id)
            assert harness.pool._child_abort_tasks == {}
            assert fleet.reaped_pids == []
            fleet.children[0].exit()
            assert (await _bounded(dispatch)).results[0].status == "completed"

    async def test_unknown_session_is_not_owned(self, tmp_path: Path) -> None:
        """A session with no registry membership cannot be manufactured into a target."""
        harness = _PoolHarness(tmp_path=tmp_path)

        outcome = await _bounded(
            harness.pool.abort_child(
                request=_request(
                    harness=harness, session_id="ghost", execution_id="22222222-3333-4444-8555-666666666666"
                )
            )
        )

        assert outcome.outcome == "not_owned"

    async def test_natural_terminal_is_already_terminal_without_signal(self, tmp_path: Path) -> None:
        """A completed child refuses already_terminal with its status; no reap, winner kept."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            fleet.children[0].exit()
            winner = (await _bounded(dispatch)).results[0]

            outcome = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))

        assert (outcome.outcome, outcome.terminal_status) == ("already_terminal", "completed")
        assert fleet.reaped_pids == []
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_closing_pool_without_accepted_task_is_unavailable(self, tmp_path: Path) -> None:
        """A sealed (closing) pool refuses new targeted work with unavailable."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            harness.pool._sealed = True

            outcome = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))

            assert outcome.outcome == "unavailable"
            assert fleet.reaped_pids == []
            fleet.children[0].exit()
            await _bounded(dispatch)

    def test_capability_reports_identity_and_accepting_until_sealed(self, tmp_path: Path) -> None:
        """The typed capability accessor carries composed identity; sealing withdraws it."""
        harness = _PoolHarness(tmp_path=tmp_path)

        capability = harness.pool.child_control_capability()
        assert (capability.run_id, capability.owner_session_id, capability.orchestrator_session_id) == (
            _RUN_ID,
            _OWNER,
            _PARENT,
        )
        assert capability.accepting is True
        harness.pool._sealed = True
        assert harness.pool.child_control_capability().accepting is False


class TestAbortChildExecution:
    """Pending and running targets stop alone; the pool stays unsealed and dispatchable."""

    async def test_pending_child_never_spawns(self, tmp_path: Path) -> None:
        """A child waiting for capacity aborts with no spawn; slot accounting intact; sibling proceeds."""
        harness = _PoolHarness(tmp_path=tmp_path)
        harness.pool._semaphore = asyncio.Semaphore(1)
        fleet = _ChildFleet()
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            blocker = harness.dispatch(session_ids=["blocker"])
            await _until(_running(harness=harness, session_id="blocker"))
            queued = harness.dispatch(session_ids=["child-1"])
            await _until(lambda: "child-1" in harness.pool._active_by_session_id)

            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            pending_winner = (await asyncio.wait_for(queued, timeout=_BOUNDED_SECONDS)).results[0]

            assert (outcome.outcome, outcome.terminal_status) == ("aborted", "aborted")
            assert len(fleet.children) == 1  # only the blocker ever spawned
            assert harness.pool._semaphore._value == 0  # still held by the blocker only
            fleet.children[0].exit()
            assert (await _bounded(blocker)).results[0].status == "completed"
            assert harness.pool._semaphore._value == 1
            fleet.exit_on_spawn = True
            sibling = await asyncio.wait_for(
                harness.dispatch(session_ids=["child-2"]), timeout=_BOUNDED_SECONDS
            )

        assert (pending_winner.status, pending_winner.exit_code) == ("aborted", 2)
        _assert_projections_agree(harness=harness, winner=pending_winner)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]
        assert fleet.reaped_pids == []
        assert sibling.results[0].status == "completed"
        assert harness.pool._sealed is False

    async def test_running_child_only(self, tmp_path: Path) -> None:
        """Exactly the target is reaped once; the sibling completes; pool stays dispatchable."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=fleet.reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1", "child-2"])
            await _until(
                lambda: _running(harness=harness, session_id="child-1")()
                and _running(harness=harness, session_id="child-2")()
            )
            target = fleet.child_for(harness=harness, session_id="child-1")
            sibling = fleet.child_for(harness=harness, session_id="child-2")

            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )

            sibling_entry = harness.pool.registry.get(session_id="child-2")
            assert sibling_entry is not None and sibling_entry.status == "running"
            sibling.exit()
            results = {r.session_id: r for r in (await _bounded(dispatch)).results}
            fleet.exit_on_spawn = True
            later = await asyncio.wait_for(
                harness.dispatch(session_ids=["child-3"]), timeout=_BOUNDED_SECONDS
            )

        assert (outcome.outcome, outcome.terminal_status) == ("aborted", "aborted")
        assert fleet.reaped_pids == [target.pid]
        assert (results["child-1"].status, results["child-1"].exit_code) == ("aborted", 2)
        assert results["child-2"].status == "completed"
        _assert_projections_agree(harness=harness, winner=results["child-1"])
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]
        assert harness.pool._sealed is False
        assert later.results[0].status == "completed"

    async def test_waiting_caller_cancellation_keeps_owned_cancellation(self, tmp_path: Path) -> None:
        """Cancelling the waiting caller does not abandon the pool-owned cancellation."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        release = asyncio.Event()

        async def gated_reap(*, pid: int) -> str:
            await release.wait()
            return await fleet.reap(pid=pid)

        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=gated_reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            request = _request(harness=harness)
            caller = asyncio.create_task(harness.pool.abort_child(request=request))
            await _until(lambda: bool(harness.pool._child_abort_tasks))
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            release.set()
            winner = (await asyncio.wait_for(dispatch, timeout=_BOUNDED_SECONDS)).results[0]
            retained = await _bounded(harness.pool.abort_child(request=request))

        assert winner.status == "aborted"
        assert (retained.outcome, retained.request_id) == ("aborted", request.request_id)
        assert len(fleet.reaped_pids) == 1


class TestAbortChildRaces:
    """One controlled barrier per race boundary; canonical evidence decides the outcome."""

    @pytest.mark.parametrize("acquire_first", [True, False])
    async def test_slot_abort_during_wait_wakeup(self, tmp_path: Path, acquire_first: bool) -> None:
        """Acquire and admission become ready together, in either order: no spawn, permit restored."""
        harness = _PoolHarness(tmp_path=tmp_path)
        semaphore = _GatedSemaphore(value=1)
        semaphore.gate.clear()
        harness.pool._semaphore = semaphore
        accepted: list[asyncio.Task[ChildAbortOutcomeDAO]] = []

        def admit() -> None:
            accepted.append(harness.pool._join_or_start_child_abort(request=_request(harness=harness)))

        spawn = AsyncMock(side_effect=AssertionError("spawn must not be reached"))
        with patch("asyncio.create_subprocess_exec", new=spawn), patch(_REAP_SEAM, new=AsyncMock()) as reap:
            queued = harness.dispatch(session_ids=["child-1"])
            await _until(lambda: bool(semaphore.gate._waiters))  # helper parked in asyncio.wait
            if acquire_first:
                semaphore.on_acquired = admit
                semaphore.gate.set()
            else:
                admit()
                semaphore.gate.set()
            winner = (await asyncio.wait_for(queued, timeout=_BOUNDED_SECONDS)).results[0]
            outcome = await asyncio.wait_for(accepted[0], timeout=_BOUNDED_SECONDS)

        spawn.assert_not_awaited()
        reap.assert_not_awaited()
        assert semaphore._value == 1 and semaphore.release_count <= 1
        assert (outcome.outcome, winner.status, winner.exit_code) == ("aborted", "aborted", 2)
        _assert_projections_agree(harness=harness, winner=winner)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]

    async def test_event_callback_requests_abort(self, tmp_path: Path) -> None:
        """Abort admitted from the spawned-event callback finds wrapper/future; no spawn."""
        harness: _PoolHarness
        accepted: list[asyncio.Task[ChildAbortOutcomeDAO]] = []

        async def on_event(event: AgentStreamEventDAO) -> None:
            if event.kind != "sub_agent_spawned":
                return
            accepted.append(
                asyncio.ensure_future(harness.pool.abort_child(request=_request(harness=harness)))
            )
            await asyncio.sleep(0)  # the abort's synchronous admission runs inside the callback

        harness = _PoolHarness(tmp_path=tmp_path, relay_hook=on_event)
        spawn = AsyncMock(side_effect=AssertionError("spawn must not be reached"))
        with patch("asyncio.create_subprocess_exec", new=spawn):
            winner = (
                await asyncio.wait_for(harness.dispatch(session_ids=["child-1"]), timeout=_BOUNDED_SECONDS)
            ).results[0]
            outcome = await asyncio.wait_for(accepted[0], timeout=_BOUNDED_SECONDS)

        spawn.assert_not_awaited()
        assert (outcome.outcome, winner.status) == ("aborted", "aborted")
        _assert_projections_agree(harness=harness, winner=winner)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]

    async def test_slot_transfer_then_abort(self, tmp_path: Path) -> None:
        """Admission after spawn entry joins spawn_ready and reaps; never pending publication."""
        harness = _PoolHarness(tmp_path=tmp_path)
        semaphore = _GatedSemaphore(value=1)
        harness.pool._semaphore = semaphore
        fleet = _ChildFleet()
        spawn_gate = asyncio.Event()

        async def gated_spawn(*args: object, **kwargs: object) -> FakeChildProcess:
            await spawn_gate.wait()
            return await fleet.spawn()

        with (
            patch("asyncio.create_subprocess_exec", new=gated_spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=fleet.reap),
            patch.object(SubAgentProcess, "finish_without_spawn", new=AsyncMock()) as pending_publication,
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(
                lambda: (p := harness.pool._active_by_session_id.get("child-1")) is not None
                and p._spawn_in_progress
            )
            abort = asyncio.create_task(harness.pool.abort_child(request=_request(harness=harness)))
            await _until(lambda: bool(harness.pool._child_abort_tasks))
            for _ in range(3):
                await asyncio.sleep(0)
            assert fleet.reaped_pids == [] and not abort.done()
            spawn_gate.set()
            outcome = await asyncio.wait_for(abort, timeout=_BOUNDED_SECONDS)
            winner = (await asyncio.wait_for(dispatch, timeout=_BOUNDED_SECONDS)).results[0]

        pending_publication.assert_not_awaited()
        assert fleet.reaped_pids == [fleet.children[0].pid]
        assert (outcome.outcome, winner.status, winner.exit_code) == ("aborted", "aborted", 2)
        assert (semaphore._value, semaphore.release_count) == (1, 1)
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_spawn_race_and_natural_terminal(self, tmp_path: Path) -> None:
        """An OS exit observed before the cancel worker keeps the natural winner; no signal."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=fleet.reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            fleet.children[0].exit()
            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            winner = (await _bounded(dispatch)).results[0]

        assert fleet.reaped_pids == []
        assert (outcome.outcome, outcome.terminal_status) == ("already_terminal", "completed")
        assert (winner.status, winner.answer) == ("completed", "natural")
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_natural_winner_committed_before_pool_resumes(self, tmp_path: Path) -> None:
        """A committed natural winner is returned while the runner is still emitting lifecycle."""
        release_emit = asyncio.Event()

        async def hold_terminal(event: AgentStreamEventDAO) -> None:
            if event.kind == "sub_agent_completed":
                await release_emit.wait()

        harness = _PoolHarness(tmp_path=tmp_path, relay_hook=hold_terminal)
        fleet = _ChildFleet()
        fleet.exit_on_spawn = True
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(lambda: any(e.kind == "sub_agent_completed" for e in harness.events))
            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            release_emit.set()
            winner = (await _bounded(dispatch)).results[0]

        assert (outcome.outcome, outcome.terminal_status) == ("already_terminal", "completed")
        assert fleet.reaped_pids == []
        _assert_projections_agree(harness=harness, winner=winner)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_completed"]

    async def test_duplicate_and_whole_abort_join(self, tmp_path: Path) -> None:
        """Two confirmations and a whole abort share one reap and one lifecycle; seal preserved."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        release = asyncio.Event()

        async def gated_reap(*, pid: int) -> str:
            await release.wait()
            return await fleet.reap(pid=pid)

        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=gated_reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            first, second = _request(harness=harness), _request(harness=harness)
            first_caller = asyncio.create_task(harness.pool.abort_child(request=first))
            second_caller = asyncio.create_task(harness.pool.abort_child(request=second))
            whole_abort = asyncio.create_task(harness.pool.abort_and_drain())
            await _until(lambda: len(harness.pool._child_abort_tasks) == 1)
            for _ in range(3):
                await asyncio.sleep(0)
            release.set()
            await _bounded(asyncio.gather(first_caller, second_caller, whole_abort))
            first_outcome: ChildAbortOutcomeDAO = first_caller.result()
            second_outcome: ChildAbortOutcomeDAO = second_caller.result()
            winner = (await _bounded(dispatch)).results[0]

        assert len(fleet.reaped_pids) == 1
        assert (first_outcome.outcome, first_outcome.request_id) == ("aborted", first.request_id)
        assert (second_outcome.outcome, second_outcome.request_id) == ("aborted", second.request_id)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]
        assert harness.pool._sealed is True
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_sealed_pool_joins_accepted_task_and_refuses_unaccepted(self, tmp_path: Path) -> None:
        """After a whole abort seals the pool, a new request joins the accepted task; others are unavailable."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        release = asyncio.Event()

        async def gated_reap(*, pid: int) -> str:
            await release.wait()
            return await fleet.reap(pid=pid)

        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=gated_reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1", "child-2"])
            await _until(
                lambda: _running(harness=harness, session_id="child-1")()
                and _running(harness=harness, session_id="child-2")()
            )
            target = fleet.child_for(harness=harness, session_id="child-1")
            first = _request(harness=harness)
            first_caller = asyncio.create_task(harness.pool.abort_child(request=first))
            await _until(lambda: len(harness.pool._child_abort_tasks) == 1)
            accepted_task = next(iter(harness.pool._child_abort_tasks.values()))
            whole_abort = asyncio.create_task(harness.pool.abort_and_drain())
            await _until(lambda: harness.pool._sealed)

            second = _request(harness=harness)
            second_caller = asyncio.create_task(harness.pool.abort_child(request=second))
            unaccepted = await _bounded(
                harness.pool.abort_child(request=_request(harness=harness, session_id="child-2"))
            )
            assert list(harness.pool._child_abort_tasks.values()) == [accepted_task]
            release.set()
            await _bounded(asyncio.gather(first_caller, second_caller, whole_abort))
            results = {r.session_id: r for r in (await _bounded(dispatch)).results}

        first_outcome: ChildAbortOutcomeDAO = first_caller.result()
        second_outcome: ChildAbortOutcomeDAO = second_caller.result()
        assert fleet.reaped_pids.count(target.pid) == 1
        assert (unaccepted.outcome, unaccepted.terminal_status) == ("unavailable", None)
        assert (first_outcome.outcome, first_outcome.request_id) == ("aborted", first.request_id)
        assert (second_outcome.outcome, second_outcome.request_id) == ("aborted", second.request_id)
        assert harness.terminal_kinds(session_id="child-1") == ["sub_agent_aborted"]
        _assert_projections_agree(harness=harness, winner=results["child-1"])

    async def test_runner_cancelled_after_winner_commit_settles_registry_winner(self, tmp_path: Path) -> None:
        """A runner cancelled after the reaper committed abort still settles that winner; abort is aborted."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        runner: list[asyncio.Task[OrchestratorResultDAO]] = []
        commit_terminal = ProcessRegistry.commit_terminal

        def commit_then_cancel_runner(registry: ProcessRegistry, **kwargs: object) -> SubAgentResultDAO:
            winner: SubAgentResultDAO = commit_terminal(registry, **kwargs)  # type: ignore[arg-type]
            runner[0].cancel()  # no await separates the commit from the runner's cancellation
            return winner

        async def reap_once_run_waits_for_settlement(*, pid: int) -> str:
            fleet.children[0].exit()
            process = harness.pool._active_by_session_id["child-1"]
            await _until(lambda: bool(process._cancel_settled._waiters))
            return await fleet.reap(pid=pid)

        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=reap_once_run_waits_for_settlement),
            patch.object(ProcessRegistry, "commit_terminal", new=commit_then_cancel_runner),
        ):
            runner.append(harness.dispatch(session_ids=["child-1"]))
            await _until(lambda: _running(harness=harness, session_id="child-1")())
            identity = ("child-1", harness.execution_id(session_id="child-1"))
            outcome = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))
            with pytest.raises(asyncio.CancelledError):
                await _bounded(runner[0])

        committed = harness.pool.registry.terminal_result(session_id=identity[0], execution_id=identity[1])
        completion = harness.pool._child_completion[identity]
        assert committed is not None and committed.status == "aborted"
        assert completion.done() and completion.result() == committed
        assert (outcome.outcome, outcome.terminal_status) == ("aborted", "aborted")
        assert harness.pool._active_by_session_id == {}

    @pytest.mark.parametrize(
        ("identity", "reap_outcome", "expected_reaps"),
        [("unreadable", "graceful", 0), ("recycled_pid", "graceful", 0), ("matching", "unresolved", 1)],
    )
    async def test_unresolved_identity_never_claims_abort(
        self, tmp_path: Path, identity: str, reap_outcome: str, expected_reaps: int
    ) -> None:
        """Unresolved/recycled never commits abort; retained result, no repeat reap; natural exit wins."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        reap = AsyncMock(return_value=reap_outcome)
        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value=identity) as identity_check,
            patch(_REAP_SEAM, new=reap),
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            first = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            entry = harness.pool.registry.get(session_id="child-1")
            assert entry is not None and entry.status == "running"
            retained_task = harness.pool._child_abort_tasks[
                ("child-1", harness.execution_id(session_id="child-1"))
            ]
            repeated = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))
            assert list(harness.pool._child_abort_tasks.values()) == [retained_task]
            identity_checks = identity_check.call_count
            fleet.children[0].exit()
            winner = (await asyncio.wait_for(dispatch, timeout=_BOUNDED_SECONDS)).results[0]
            after_exit = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))

        assert (first.outcome, repeated.outcome) == ("unresolved", "unresolved")
        assert (identity_checks, reap.await_count) == (1, expected_reaps)
        assert winner.status == "completed"
        assert (after_exit.outcome, after_exit.terminal_status) == ("already_terminal", "completed")
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_operation_exception_is_unresolved_with_fixed_message(self, tmp_path: Path) -> None:
        """A wrapper failure becomes unresolved with fixed text; no exception text escapes."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch.object(
                SubAgentProcess, "cancel", new=AsyncMock(side_effect=RuntimeError("SECRET-SENTINEL"))
            ),
            patch("src.agents.slo_agent.orchestrator.pool.log_warning") as warn,
        ):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(_running(harness=harness, session_id="child-1"))
            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            entry = harness.pool.registry.get(session_id="child-1")
            fleet.children[0].exit()
            await _bounded(dispatch)

        assert outcome.outcome == "unresolved"
        assert "SECRET-SENTINEL" not in outcome.model_dump_json()
        assert "SECRET-SENTINEL" not in repr(warn.call_args_list)
        assert entry is not None and entry.status == "running"

    async def test_chain_stops_on_aborted_step_without_retry(self, tmp_path: Path) -> None:
        """An aborted chain step stops the chain; later steps never register or spawn."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with (
            patch("asyncio.create_subprocess_exec", new=fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=fleet.reap),
        ):
            chain = harness.dispatch(session_ids=["child-1", "child-2"], mode="chain")
            await _until(_running(harness=harness, session_id="child-1"))
            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            result = await asyncio.wait_for(chain, timeout=_BOUNDED_SECONDS)

        assert outcome.outcome == "aborted"
        assert [(r.session_id, r.status) for r in result.results] == [("child-1", "aborted")]
        assert result.all_completed is False
        assert harness.pool.registry.get(session_id="child-2") is None
        assert len(fleet.children) == 1

    async def test_reused_incarnation_refuses_old_request(self, tmp_path: Path) -> None:
        """A request for a superseded incarnation is not_owned; the new incarnation is untouched."""
        harness = _PoolHarness(tmp_path=tmp_path)
        fleet = _ChildFleet()
        with patch("asyncio.create_subprocess_exec", new=fleet.spawn), patch(_REAP_SEAM, new=fleet.reap):
            fleet.exit_on_spawn = True
            await asyncio.wait_for(harness.dispatch(session_ids=["child-1"]), timeout=_BOUNDED_SECONDS)
            stale = _request(harness=harness)
            fleet.exit_on_spawn = False
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _until(
                lambda: _running(harness=harness, session_id="child-1")()
                and harness.execution_id(session_id="child-1") != stale.execution_id
            )

            outcome = await _bounded(harness.pool.abort_child(request=stale))

            assert outcome.outcome == "not_owned"
            assert fleet.reaped_pids == []
            fleet.children[-1].exit()
            assert (await _bounded(dispatch)).results[0].status == "completed"

    async def test_status_write_failure_retains_aborted_winner(self, tmp_path: Path) -> None:
        """A failed status projection keeps the canonical aborted winner and outcome."""
        harness = _PoolHarness(tmp_path=tmp_path)
        harness.pool._semaphore = asyncio.Semaphore(0)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("no spawn"))),
            patch(
                "src.agents.slo_agent.orchestrator.process.AtomicFileWriter.write_text",
                side_effect=OSError("disk full"),
            ),
        ):
            queued = harness.dispatch(session_ids=["child-1"])
            await _until(lambda: "child-1" in harness.pool._active_by_session_id)
            outcome = await asyncio.wait_for(
                harness.pool.abort_child(request=_request(harness=harness)), timeout=_BOUNDED_SECONDS
            )
            winner = (await asyncio.wait_for(queued, timeout=_BOUNDED_SECONDS)).results[0]

        entry = harness.pool.registry.get(session_id="child-1")
        assert outcome.outcome == "aborted" and winner.status == "aborted"
        assert entry is not None and (entry.status, entry.execution_id) == ("aborted", winner.execution_id)
        assert not (tmp_path / _PARENT / "children" / "child-1" / "status.json").exists()

    async def test_failure_winner_is_already_terminal_and_preserved(self, tmp_path: Path) -> None:
        """A failed winner (spawn failure) stays authoritative; abort reports already_terminal."""
        harness = _PoolHarness(tmp_path=tmp_path)
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=OSError("spawn failed"))):
            winner = (await _bounded(harness.dispatch(session_ids=["child-1"]))).results[0]
            outcome = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))

        assert (winner.status, winner.exit_code) == ("failed", 1)
        assert (outcome.outcome, outcome.terminal_status) == ("already_terminal", "failed")
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_provider_failure_envelope_winner_is_preserved_everywhere(self, tmp_path: Path) -> None:
        """A provider-failure winner keeps its full envelope; a later abort is already_terminal."""
        harness = _PoolHarness(tmp_path=tmp_path)
        failure_line: bytes = (
            AgentStreamEventDAO(
                kind="run_failed",
                content="partial",
                metadata={
                    "failure_code": "provider_stream_interrupted",
                    "partial_output_committed": True,
                    "attempts": 2,
                },
            ).model_dump_json()
            + "\n"
        ).encode("utf-8")
        child = FakeChildProcess(lines=[failure_line], exit_code=1)
        child.exit()
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)):
            winner = (await _bounded(harness.dispatch(session_ids=["child-1"]))).results[0]
            outcome = await _bounded(harness.pool.abort_child(request=_request(harness=harness)))

        assert (winner.status, winner.exit_code, winner.answer) == ("failed", 1, "partial")
        assert (winner.failure_code, winner.partial_output_committed, winner.attempts) == (
            "provider_stream_interrupted",
            True,
            2,
        )
        assert winner.safe_message is not None
        assert (outcome.outcome, outcome.terminal_status) == ("already_terminal", "failed")
        _assert_projections_agree(harness=harness, winner=winner)

    async def test_runner_error_while_abort_waits_is_unresolved(self, tmp_path: Path) -> None:
        """A runner that dies without a winner yields unresolved, never aborted fiction."""
        harness = _PoolHarness(tmp_path=tmp_path)
        crash = asyncio.Event()
        entered = asyncio.Event()

        async def crashing_run(process: SubAgentProcess) -> SubAgentResultDAO:
            entered.set()
            await crash.wait()
            raise RuntimeError("runner crashed")

        with patch.object(SubAgentProcess, "run", new=crashing_run):
            dispatch = harness.dispatch(session_ids=["child-1"])
            await _bounded(entered.wait())
            abort = asyncio.create_task(harness.pool.abort_child(request=_request(harness=harness)))
            await _until(lambda: bool(harness.pool._child_abort_tasks))
            crash.set()
            outcome = await _bounded(abort)
            with pytest.raises(RuntimeError, match="runner crashed"):
                await _bounded(dispatch)

        assert outcome.outcome == "unresolved"
        entry = harness.pool.registry.get(session_id="child-1")
        assert entry is not None and entry.status != "aborted"
