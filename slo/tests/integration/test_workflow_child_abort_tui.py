"""Composed detached child abort: mounted TUI → service → temp store → controller → pool (feature 94 a.4).

Real ``SloTUI`` over a history-backed owner session, the real
``DetachedWorkflowAppService``, coordinator, sink, progress and confirmation
screens, a real ``WorkflowHandleStore`` handle for one detached orchestrator,
the real ``ChildAbortStore`` and ``ChildAbortController`` and a real
``SubAgentPool`` writing fleet, execution and capture files below ``tmp_path``.
The only replaced boundaries are the OS process (``FakeChildProcess`` from the
spawn seam), the ``FleetReaper`` identity/reap seams and the handle store's
liveness probe. ``os.kill`` is patched to fail the test if anything signals.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Optional, TypeVar
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.pilot import Pilot
from textual.widgets import Button, Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator import child_abort
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortController, ChildAbortStore
from src.agents.slo_agent.orchestrator.dao import (
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    OrchestratorResultDAO,
    SubAgentMode,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import SloTUI
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator
from src.tui.workflows.session_progress_screen import SessionProgressScreen
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess

_PARENT: str = "orch-1"
_TARGET: str = "child-1"
_SIBLING: str = "child-2"
_SPAWN_SEAM: str = "asyncio.create_subprocess_exec"
_IDENTITY_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome"
_REAP_SEAM: str = "src.agents.slo_agent.orchestrator.process.FleetReaper.reap"
_BOUNDED_SECONDS: float = 5.0
"""Deadline for awaited conditions so a regression fails instead of hanging; not a timing oracle."""

_T = TypeVar("_T")


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until ``predicate`` holds, bounded by a deadline.

    Args:
        predicate (Callable[[], bool]): Condition to wait for.
    """

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=_BOUNDED_SECONDS)


async def _bounded(awaitable: Awaitable[_T]) -> _T:
    """Await within the deadline.

    Args:
        awaitable (Awaitable[_T]): Operation.

    Returns:
        _T: Its result.
    """
    return await asyncio.wait_for(awaitable, timeout=_BOUNDED_SECONDS)


class _ChildFleet:
    """OS boundary: one ``FakeChildProcess`` per spawn that runs until reaped or exited."""

    def __init__(self) -> None:
        """Start with no children; reaping is open unless ``reap_gate`` is set."""
        self.children: dict[int, FakeChildProcess] = {}
        self.reaped_pids: list[int] = []
        self.reap_gate: Optional[asyncio.Event] = None

    async def spawn(self, *args: object, **kwargs: object) -> FakeChildProcess:
        """Return a running child that emits nothing until it exits.

        Args:
            *args (object): Ignored command line.
            **kwargs (object): Ignored spawn options.

        Returns:
            FakeChildProcess: Controlled child.
        """
        child = FakeChildProcess(lines=[], exit_code=0, pid=7000 + len(self.children))
        self.children[child.pid] = child
        return child

    async def reap(self, *, pid: int) -> str:
        """Record the reap of exactly this pid, optionally wait at the gate, then exit it.

        Args:
            pid (int): Child pid chosen by the wrapper.

        Returns:
            str: Graceful reap outcome.
        """
        self.reaped_pids.append(pid)
        if self.reap_gate is not None:
            await self.reap_gate.wait()
        self.children[pid].exit()
        return "graceful"

    def exit_all(self) -> None:
        """Let every remaining child exit naturally."""
        for child in self.children.values():
            child.exit()


class _DetachedWorld:
    """Owner TUI session plus one detached orchestrator's real pool and controller."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Create the temp root, owner session, handle store, pool and controller.

        Args:
            tmp_path (Path): Test-owned directory; every write stays below it.
        """
        self.root: Path = tmp_path / "history"
        self.root.mkdir()
        self.session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=FilesystemSessionHistoryStore(root=self.root),
            enable_history=True,
        )
        self.handles: WorkflowHandleStore = WorkflowHandleStore(
            history_root=self.root, pid_alive=lambda pid: True
        )
        self.fleet: _ChildFleet = _ChildFleet()
        self.pool: SubAgentPool = SubAgentPool(
            orchestrator_session_id=_PARENT,
            default_model=None,
            relay=self._relay,
            owner_session_id=self.session.session_id,
            run_id=str(uuid4()),
            history_root=self.root,
        )
        self.store: ChildAbortStore = ChildAbortStore(history_root=self.root, orchestrator_session_id=_PARENT)
        self.controller: ChildAbortController = ChildAbortController(
            pool=self.pool, store=self.store, capability=self.pool.child_control_capability()
        )

    @staticmethod
    async def _relay(event: AgentStreamEventDAO) -> None:
        """Discard child lifecycle events (no orchestrator transcript in this test).

        Args:
            event (AgentStreamEventDAO): Child event.
        """

    async def write_handle(self) -> None:
        """Persist the owner's running handle for the detached orchestrator."""
        await self.handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-1",
                owner_session_id=self.session.session_id,
                orchestrator_session_id=_PARENT,
                pid=4242,
                brief="Run the detached workflow",
                cwd=str(self.root),
                state="running",
            )
        )

    @contextmanager
    def boundaries(self) -> Iterator[list[tuple[int, int]]]:
        """Replace only the OS seams; record (and fail) any direct signal.

        Yields:
            list[tuple[int, int]]: ``os.kill`` calls (must stay empty).
        """
        signals: list[tuple[int, int]] = []

        def no_kill(pid: int, sig: int) -> None:
            signals.append((pid, sig))
            raise AssertionError("no process may be signalled in this test")

        with (
            patch(_SPAWN_SEAM, new=self.fleet.spawn),
            patch(_IDENTITY_SEAM, return_value="matching"),
            patch(_REAP_SEAM, new=self.fleet.reap),
            patch.object(child_abort, "POLL_INTERVAL_SECONDS", 0.01),
            patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=False),
            patch("os.kill", side_effect=no_kill),
        ):
            yield signals

    @asynccontextmanager
    async def running(self, *, mode: SubAgentMode) -> AsyncIterator[asyncio.Task[OrchestratorResultDAO]]:
        """Start the controller and dispatch target + sibling; always close and drain.

        Args:
            mode (SubAgentMode): ``parallel`` (sibling runs) or ``chain`` (sibling depends).

        Yields:
            asyncio.Task[OrchestratorResultDAO]: The dispatch task.
        """
        await _bounded(self.controller.start())
        tasks = [
            SubAgentTaskDAO(task_id=f"t-{sid}", prompt=f"task for {sid}", session_id=sid)
            for sid in (_TARGET, _SIBLING)
        ]
        dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
            self.pool.dispatch(mode=mode, tasks=tasks)
        )
        try:
            yield dispatch
        finally:
            if self.fleet.reap_gate is not None:
                self.fleet.reap_gate.set()
            self.fleet.exit_all()
            await _bounded(asyncio.gather(dispatch, return_exceptions=True))
            await _bounded(self.controller.close())

    def status(self, *, session_id: str) -> Optional[str]:
        """Return the registry status of one child.

        Args:
            session_id (str): Child session.

        Returns:
            Optional[str]: Status, or None when not registered.
        """
        entry = self.pool.registry.get(session_id=session_id)
        return entry.status if entry is not None else None

    def pid(self, *, session_id: str) -> int:
        """Return the registered pid of a running child.

        Args:
            session_id (str): Child session.

        Returns:
            int: Pid.
        """
        entry = self.pool.registry.get(session_id=session_id)
        assert entry is not None and entry.pid is not None
        return entry.pid

    async def receipt(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Wait for the controller's receipt of one request.

        Args:
            request (ChildAbortRequestDAO): Committed request.

        Returns:
            ChildAbortOutcomeDAO: Receipt.
        """
        while (receipt := await self.store.load_receipt(request=request)) is None:
            await asyncio.sleep(0.01)
        return receipt


@pytest.fixture(autouse=True)
def _no_auth_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a fake credential so the startup authentication modal stays closed.

    Args:
        monkeypatch (pytest.MonkeyPatch): Restores the resolver after the test.
    """

    def _fake(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(provider=provider, auth_type=AuthType.API_KEY, access_token="sk-fake-default")

    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", _fake)


async def _tick(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Request one observation refresh, await it and let paint settle.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.
    """
    coordinator: Optional[WorkflowProgressCoordinator] = app._workflow_progress_coordinator
    assert coordinator is not None
    coordinator.request_refresh()
    if coordinator._task is not None:
        await _bounded(coordinator._task)
    for _ in range(3):
        await pilot.pause()


def _rows(*, app: SloTUI) -> dict[str, str]:
    """Return painted list rows as ``session_id → status``.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        dict[str, str]: Row statuses.
    """
    assert app._fleet_panel is not None
    return {item.row.key.session_id: item.row.status for item in app._fleet_panel.query(SubAgentFleetRow)}


async def _open(*, app: SloTUI, pilot: Pilot[None], session_id: str) -> SessionProgressScreen:
    """Click one detached row and return its progress screen.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.
        session_id (str): Row to open.

    Returns:
        SessionProgressScreen: Opened screen.
    """
    assert app._fleet_panel is not None
    row = next(
        item for item in app._fleet_panel.query(SubAgentFleetRow) if item.row.key.session_id == session_id
    )
    await pilot.click(row)
    await _tick(app=app, pilot=pilot)
    [screen] = [screen for screen in app.screen_stack if isinstance(screen, SessionProgressScreen)]
    return screen


def _state(*, screen: SessionProgressScreen) -> str:
    """Return the progress screen's painted status line.

    Args:
        screen (SessionProgressScreen): Open screen.

    Returns:
        str: Status line text.
    """
    return str(screen.query_one("#session-state", Static).render())


async def _confirm(*, app: SloTUI, pilot: Pilot[None], screen: SessionProgressScreen) -> ChildAbortRequestDAO:
    """Confirm Abort child from the open view and return the service's tracked request.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.
        screen (SessionProgressScreen): Open view whose Abort is enabled.

    Returns:
        ChildAbortRequestDAO: Request the service allocated for the confirmed target.
    """
    assert screen.query_one("#abort-child", Button).disabled is False
    await pilot.click("#abort-child")
    await pilot.pause()
    assert isinstance(app.screen, AbortConfirmationScreen)
    texts: list[str] = [str(static.render()) for static in app.screen.query(Static)]
    assert _PARENT in texts and _TARGET in texts
    await pilot.click("#confirm-abort")
    await pilot.pause()
    service = app._workflow_app_service
    assert service is not None
    [submission] = service._abort_submissions.values()
    await _bounded(submission.join())
    return submission.request


class TestDetachedChildAbortFromModal:
    """The operator stops exactly one detached child through the orchestrator that owns it."""

    async def test_detached_child_abort_from_modal(self, tmp_path: Path) -> None:
        """Requested then terminal paint; sibling, parent and transcript untouched; no whole abort, no signal."""
        world = _DetachedWorld(tmp_path=tmp_path)
        world.fleet.reap_gate = asyncio.Event()
        await world.write_handle()
        app: SloTUI = SloTUI(session=world.session, workflow_handle_store=world.handles)

        with world.boundaries() as signals:
            async with app.run_test(size=(120, 40)) as pilot, world.running(mode="parallel") as dispatch:
                await _until(
                    lambda: world.status(session_id=_TARGET) == world.status(session_id=_SIBLING) == "running"
                )
                target_pid: int = world.pid(session_id=_TARGET)
                await _tick(app=app, pilot=pilot)
                assert app.query_one(ChatTranscript)._adapter is not None
                foreground: list[tuple[str, str]] = list(app.query_one(ChatTranscript)._adapter.lines)
                assert _rows(app=app) == {_PARENT: "running", _TARGET: "running", _SIBLING: "running"}

                with patch.object(world.session, "abort") as whole_abort:
                    screen = await _open(app=app, pilot=pilot, session_id=_TARGET)
                    request = await _confirm(app=app, pilot=pilot, screen=screen)
                    await _until(lambda: world.fleet.reaped_pids == [target_pid])
                    await _tick(app=app, pilot=pilot)
                    requested_state: str = _state(screen=screen)
                    abort_disabled: bool = screen.query_one("#abort-child", Button).disabled

                    world.fleet.reap_gate.set()
                    receipt = await _bounded(world.receipt(request=request))
                    await _until(lambda: world.status(session_id=_TARGET) == "aborted")
                    await _tick(app=app, pilot=pilot)
                    terminal_state: str = _state(screen=screen)
                    rows: dict[str, str] = _rows(app=app)

                foreground_after = list(app.query_one(ChatTranscript)._adapter.lines)
                assert not dispatch.done()  # the sibling still runs
                whole_abort.assert_not_called()

            assert "Abort requested" in requested_state
            assert "running" in requested_state and "Child aborted." not in requested_state
            assert abort_disabled is True
            assert "Child aborted." in terminal_state and "aborted" in terminal_state
            assert (receipt.outcome, receipt.terminal_status) == ("aborted", "aborted")
            assert rows == {_PARENT: "running", _TARGET: "aborted", _SIBLING: "running"}
            assert world.fleet.reaped_pids == [target_pid]
            assert (request.owner_session_id, request.orchestrator_session_id, request.session_id) == (
                world.session.session_id,
                _PARENT,
                _TARGET,
            )
            assert request.run_id == world.pool.run_id
            assert foreground_after == foreground
            assert not (world.root / _PARENT / "abort_request.json").exists()
            assert signals == []

    async def test_dependent_chain_step_never_runs(self, tmp_path: Path) -> None:
        """Aborting the running chain step stops the chain: the dependent step never spawns."""
        world = _DetachedWorld(tmp_path=tmp_path)
        await world.write_handle()
        app: SloTUI = SloTUI(session=world.session, workflow_handle_store=world.handles)

        with world.boundaries() as signals:
            async with app.run_test(size=(120, 40)) as pilot, world.running(mode="chain") as dispatch:
                await _until(lambda: world.status(session_id=_TARGET) == "running")
                await _tick(app=app, pilot=pilot)
                screen = await _open(app=app, pilot=pilot, session_id=_TARGET)
                request = await _confirm(app=app, pilot=pilot, screen=screen)
                await _bounded(world.receipt(request=request))
                result: OrchestratorResultDAO = await _bounded(dispatch)

            assert len(world.fleet.children) == 1
            assert world.status(session_id=_SIBLING) is None
            assert [entry.status for entry in result.results] == ["aborted"]
            assert signals == []

    async def test_minimize_does_not_cancel_request_or_execution(self, tmp_path: Path) -> None:
        """Escape after commit keeps the request; the reap completes; reopen paints the terminal truth."""
        world = _DetachedWorld(tmp_path=tmp_path)
        world.fleet.reap_gate = asyncio.Event()
        await world.write_handle()
        app: SloTUI = SloTUI(session=world.session, workflow_handle_store=world.handles)

        with world.boundaries() as signals:
            async with app.run_test(size=(120, 40)) as pilot, world.running(mode="parallel"):
                await _until(
                    lambda: world.status(session_id=_TARGET) == world.status(session_id=_SIBLING) == "running"
                )
                await _tick(app=app, pilot=pilot)
                screen = await _open(app=app, pilot=pilot, session_id=_TARGET)
                request = await _confirm(app=app, pilot=pilot, screen=screen)

                await pilot.press("escape")
                await _tick(app=app, pilot=pilot)
                assert [s for s in app.screen_stack if isinstance(s, SessionProgressScreen)] == []
                await _until(lambda: len(world.fleet.reaped_pids) == 1)
                await _tick(app=app, pilot=pilot)  # minimized refresh keeps polling the receipt
                assert world.fleet.reap_gate is not None
                world.fleet.reap_gate.set()
                receipt = await _bounded(world.receipt(request=request))
                await _until(lambda: world.status(session_id=_TARGET) == "aborted")
                await _tick(app=app, pilot=pilot)

                reopened = await _open(app=app, pilot=pilot, session_id=_TARGET)
                state: str = _state(screen=reopened)
                assert reopened.query_one("#abort-child", Button).disabled is True

            assert receipt.outcome == "aborted"
            assert "Child aborted." in state
            assert world.fleet.reaped_pids == [world.fleet.reaped_pids[0]]
            assert (
                len(
                    list(
                        (world.root / _PARENT / "child-control.v1" / request.run_id / "requests").glob(
                            "*.json"
                        )
                    )
                )
                == 1
            )
            assert signals == []
