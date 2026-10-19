"""Composed list → progress → refresh flow through the real TUI stack (feature 94 a.3).

Real ``SloTUI``, real history-backed ``SloAgentSession`` over a temp-owned
``FilesystemSessionHistoryStore``, the real ``DetachedWorkflowAppService``,
``WorkflowVisualizerLoader``, coordinator, sink and progress screen. The only
declared fakes are the attached registry supplier (the pool boundary) and the
faux chat model; child output is written to real capture files under
``tmp_path`` exactly where the wrapper would write it. Ticks are requested
explicitly instead of waiting five real seconds. No provider, process, signal,
terminal or user history is touched; visualizer launch stays disabled.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Optional
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.await_complete import AwaitComplete
from textual.pilot import Pilot
from textual.widgets import Button, Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
    ChildControlCapabilityDAO,
    ChildExecutionEvidenceDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.task_preview import TASK_PREVIEW_MAX_CODE_POINTS
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import SloTUI
from src.tui.widgets.sub_agent_fleet_panel import FleetSessionList, SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.widgets.usage_status_bar import UsageStatusBar
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.dao import (
    ProgressViewportDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator
from src.tui.workflows.session_progress_screen import ProgressLog, SessionProgressScreen

_RUN_ID: str = "7a0e6a54-2f43-4d5c-9b1e-0c6f4a3d2e10"
_DISPATCH_ID: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
_EXECUTION_A: str = "11111111-1111-4111-8111-111111111111"
_EXECUTION_B: str = "22222222-2222-4222-8222-222222222222"
_CHILD: str = "child-a"
_PRIVATE_PROMPT: str = "SYSTEM-PRIVATE-PROMPT"


class _AttachedSupplier:
    """The pool boundary: the attached registry batch the session would report."""

    def __init__(self) -> None:
        """Start with no admitted dispatch."""
        self.snapshot: AttachedDispatchSnapshotDAO = AttachedDispatchSnapshotDAO.empty()

    def publish(self, *, status: str, execution_id: str = _EXECUTION_A) -> None:
        """Report one child of the current dispatch.

        Args:
            status (str): Registry status.
            execution_id (str, optional): Incarnation. Defaults to the first one.
        """
        self.snapshot = AttachedDispatchSnapshotDAO(
            dispatch_id=_DISPATCH_ID,
            dispatch_sequence=1,
            entries=(
                SubAgentStatusDAO(
                    task_id="task-a",
                    session_id=_CHILD,
                    status=status,  # type: ignore[arg-type]
                    execution_id=execution_id,
                    prompt_preview="Audit the parser",
                ),
            ),
        )

    def __call__(self) -> AttachedDispatchSnapshotDAO:
        """Return the current batch.

        Returns:
            AttachedDispatchSnapshotDAO: Current batch.
        """
        return self.snapshot


class _PoolSeam:
    """Recording attached child-abort seam; ``gate`` holds the pool's answer until set."""

    def __init__(self) -> None:
        """Start open, with no requests."""
        self.calls: list[ChildAbortRequestDAO] = []
        self.gate: asyncio.Event = asyncio.Event()
        self.gate.set()

    async def __call__(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Record the request, wait at the gate, then report the child aborted.

        Args:
            request (ChildAbortRequestDAO): Submitted request.

        Returns:
            ChildAbortOutcomeDAO: Aborted outcome for the request.
        """
        self.calls.append(request)
        await self.gate.wait()
        return ChildAbortOutcomeDAO.for_request(request=request, outcome="aborted", terminal_status="aborted")


class _World:
    """A history-backed owner session plus the child files its wrapper would write."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Create the temp history root, the session and the attached supplier.

        Args:
            tmp_path (Path): Test-owned directory; every write stays below it.
        """
        self.root: Path = tmp_path / "history"
        self.root.mkdir()
        self.supplier: _AttachedSupplier = _AttachedSupplier()
        self.session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=FilesystemSessionHistoryStore(root=self.root),
            enable_history=True,
        )
        self.session.attached_dispatch_snapshot = self.supplier  # type: ignore[method-assign]
        self.evidence: Optional[ChildExecutionEvidenceDAO] = None

    @property
    def capture_dir(self) -> Path:
        """Return (and create) the child's capture directory."""
        path: Path = OrchestrationLayout.child_capture_dir(
            history_root=self.root, parent_session_id=self.session.session_id, child_session_id=_CHILD
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def start_child(self, *, lines: int, execution_id: str = _EXECUTION_A) -> None:
        """Write spawn context, an initial capture, running evidence and the fleet.

        Args:
            lines (int): Number of separate public output entries to capture.
            execution_id (str, optional): Incarnation. Defaults to the first one.
        """
        context: bytes = dump_json_bytes(
            SpawnContextDAO.build(
                task_id="task-a",
                prompt="Audit the parser thoroughly",
                system_prompt=_PRIVATE_PROMPT,
                inactivity_timeout_seconds=1.0,
                model=None,
                reasoning_level=None,
                cwd=None,
                execution_id=execution_id,
            )
        )
        (self.capture_dir / "spawn_context.json").write_bytes(context)
        capture: Path = self.capture_dir / "stdout.jsonl"
        capture.write_text("", encoding="utf-8")
        self.append(start=0, lines=lines)
        status = os.stat(capture)
        self.evidence = ChildExecutionEvidenceDAO.pending(
            session_id=_CHILD, execution_id=execution_id, dispatch_id=_DISPATCH_ID
        ).running(
            stdout_identity=StdoutCaptureIdentityDAO(device=status.st_dev, inode=status.st_ino),
            spawn_context_sha256=hashlib.sha256(context).hexdigest(),
        )
        self._store().publish_execution(evidence=self.evidence)
        self._store().persist(
            entries=[
                SubAgentStatusDAO(
                    task_id="task-a", session_id=_CHILD, status="running", execution_id=execution_id
                )
            ]
        )
        self.supplier.publish(status="running", execution_id=execution_id)

    def append(self, *, start: int, lines: int, terminal: bool = False) -> None:
        """Append separate public entries (and optionally the run terminal event).

        Args:
            start (int): First line number.
            lines (int): Number of entries.
            terminal (bool, optional): Append ``run_completed``. Defaults to False.
        """
        events: list[dict[str, object]] = []
        for index in range(start, start + lines):
            events.append({"kind": "text_delta", "delta": f"child line {index:03d}"})
            events.append({"kind": "text_end"})
        if terminal:
            events.append({"kind": "run_completed"})
        with (self.capture_dir / "stdout.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(event) + "\n" for event in events))

    def finish(self, *, status: str = "completed") -> None:
        """Publish the child's terminal status and evidence; the registry reports it too.

        Args:
            status (str, optional): Terminal status. Defaults to ``"completed"``.
        """
        assert self.evidence is not None
        data: bytes = (
            SubAgentResultDAO(
                task_id="task-a",
                session_id=_CHILD,
                status=status,  # type: ignore[arg-type]
                exit_code=0 if status == "completed" else 2,
            )
            .model_dump_json()
            .encode()
        )
        (self.capture_dir / "status.json").write_bytes(data)
        self._store().publish_execution(
            evidence=self.evidence.terminal(
                status=status, status_sha256=hashlib.sha256(data).hexdigest()  # type: ignore[arg-type]
            )
        )
        self.supplier.publish(status=status)

    def enable_attached_control(self) -> "_PoolSeam":
        """Give the session an accepting attached pool seam that records every request.

        The recording seam stands in for ``SloAgentSession.abort_child`` (the pool
        boundary); no process is signalled. Must run before the app mounts.

        Returns:
            _PoolSeam: The recording seam.
        """
        seam: _PoolSeam = _PoolSeam()
        owner: str = self.session.session_id
        self.session.abort_child = seam  # type: ignore[method-assign]
        self.session.child_control_capability = lambda: ChildControlCapabilityDAO(  # type: ignore[method-assign]
            run_id=_RUN_ID, owner_session_id=owner, orchestrator_session_id=owner, accepting=True
        )
        return seam

    def _store(self) -> FleetStore:
        """Return the run-bound fleet store of the owner session."""
        return FleetStore(
            history_root=self.root, orchestrator_session_id=self.session.session_id, run_id=_RUN_ID
        )


@pytest.fixture(autouse=True)
def _no_visualizer_window() -> Iterator[None]:
    """Keep the external visualizer launcher from opening any terminal."""
    with patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _no_auth_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a fake credential so the startup authentication modal stays closed.

    Args:
        monkeypatch (pytest.MonkeyPatch): Restores the resolver after the test.
    """

    def _fake(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(provider=provider, auth_type=AuthType.API_KEY, access_token="sk-fake-default")

    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", _fake)


def _coordinator(*, app: SloTUI) -> WorkflowProgressCoordinator:
    """Return the bound coordinator.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        WorkflowProgressCoordinator: Coordinator.
    """
    assert app._workflow_progress_coordinator is not None
    return app._workflow_progress_coordinator


async def _tick(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Fire one observation tick and wait for it to paint.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.
    """
    _coordinator(app=app).request_refresh()
    await _settle(app=app, pilot=pilot)


async def _settle(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Await the in-flight refresh, then let layout and restoration run.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.
    """
    coordinator: Optional[WorkflowProgressCoordinator] = app._workflow_progress_coordinator
    task: Optional[asyncio.Task[None]] = coordinator._task if coordinator is not None else None
    if task is not None:
        await task
    for _ in range(3):
        await pilot.pause()


def _screen(*, app: SloTUI) -> SessionProgressScreen:
    """Return the single open progress screen.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        SessionProgressScreen: Screen.
    """
    [screen] = [screen for screen in app.screen_stack if isinstance(screen, SessionProgressScreen)]
    return screen


def _painted_log_text(*, screen: SessionProgressScreen) -> str:
    """Return the progress log's painted text.

    Args:
        screen (SessionProgressScreen): Open screen.

    Returns:
        str: All log lines joined.
    """
    return "\n".join(strip.text for strip in screen.query_one(ProgressLog).lines)


async def _until_live(*, pilot: Pilot[None], screen: SessionProgressScreen) -> None:
    """Pause until a pushed screen is mounted and attached (bounded).

    Args:
        pilot (Pilot[None]): Pilot.
        screen (SessionProgressScreen): Pushed screen.
    """
    for _ in range(20):
        if screen.is_live:
            return
        await pilot.pause()
    raise AssertionError("progress screen never mounted")


async def _open_child(*, app: SloTUI, pilot: Pilot[None]) -> SessionProgressScreen:
    """Click the child row and return the opened screen.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Pilot.

    Returns:
        SessionProgressScreen: Opened screen.
    """
    assert app._fleet_panel is not None
    row: SubAgentFleetRow = next(
        item for item in app._fleet_panel.query(SubAgentFleetRow) if item.row.key.session_id == _CHILD
    )
    await pilot.click(row)
    await _settle(app=app, pilot=pilot)
    return _screen(app=app)


async def _open_confirmation(*, app: SloTUI, pilot: Pilot[None]) -> AbortConfirmationScreen:
    """Click the progress view's Abort child button and return the confirmation.

    Args:
        app (SloTUI): Mounted app with an open, abort-eligible progress view.
        pilot (Pilot[None]): Pilot.

    Returns:
        AbortConfirmationScreen: Confirmation on top of the progress view.
    """
    await pilot.click("#abort-child")
    for _ in range(3):
        await pilot.pause()
    assert isinstance(app.screen, AbortConfirmationScreen)
    return app.screen


class TestOwnedWorkflowListToProgress:
    """The full journey keeps the reader's place and never touches execution."""

    async def test_owned_workflow_list_to_progress(self, tmp_path: Path) -> None:
        """Spawn → row → click → append on tick → scroll → minimize → reopen → terminal."""
        world: _World = _World(tmp_path=tmp_path)
        world.start_child(lines=30)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            assert app._adapter is not None
            foreground: list[tuple[str, str]] = list(app._adapter.lines)
            with patch.object(world.session, "abort") as abort:
                screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
                log: ProgressLog = screen.query_one(ProgressLog)
                assert "child line 029" in _painted_log_text(screen=screen)
                assert log.scroll_y == log.max_scroll_y

                world.append(start=30, lines=10)
                await _tick(app=app, pilot=pilot)
                assert "child line 039" in _painted_log_text(screen=screen)
                assert log.scroll_y == log.max_scroll_y

                log.scroll_to(x=0, y=20, animate=False, immediate=True)
                await pilot.pause()
                world.append(start=40, lines=10)
                await _tick(app=app, pilot=pilot)
                assert "child line 049" in _painted_log_text(screen=screen)
                assert log.scroll_y == 20.0

                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)
                assert [s for s in app.screen_stack if isinstance(s, SessionProgressScreen)] == []
                world.append(start=50, lines=5)
                await _tick(app=app, pilot=pilot)

                reopened: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
                assert reopened is not screen
                reopened_log: ProgressLog = reopened.query_one(ProgressLog)
                assert "child line 054" in _painted_log_text(screen=reopened)
                assert reopened_log.scroll_y == 20.0

                world.append(start=55, lines=2, terminal=True)
                world.finish()
                await _tick(app=app, pilot=pilot)
                assert "child line 056" in _painted_log_text(screen=reopened)
                assert "completed" in str(reopened.query_one("#session-state", Static).render())
                service = app._workflow_app_service
                assert service is not None
                with patch.object(
                    service, "load_session_progress", wraps=service.load_session_progress
                ) as reads:
                    await _tick(app=app, pilot=pilot)
                reads.assert_not_called()

            abort.assert_not_called()
            assert list(app._adapter.lines) == foreground
            painted: str = _painted_log_text(screen=reopened)
            assert _PRIVATE_PROMPT not in painted

    async def test_incarnation_change_routes_through_app(self, tmp_path: Path) -> None:
        """A same-key new execution closes the open view through the app handler exactly once."""
        world: _World = _World(tmp_path=tmp_path)
        world.start_child(lines=30)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            key: WorkflowSessionKeyDAO = screen.key
            screen.query_one(ProgressLog).scroll_to(x=0, y=5, animate=False, immediate=True)
            await pilot.pause()
            coordinator: WorkflowProgressCoordinator = _coordinator(app=app)
            order: list[str] = []
            real_minimize = coordinator.minimize
            real_dismiss = screen.dismiss

            def minimize() -> None:
                order.append(f"minimize:{coordinator._generation}")
                real_minimize()
                order.append(f"generation:{coordinator._generation}")

            def dismiss(result: None = None) -> AwaitComplete:
                order.append(f"dismiss:{coordinator._generation}")
                return real_dismiss(result)

            coordinator.minimize = minimize  # type: ignore[method-assign]
            screen.dismiss = dismiss  # type: ignore[method-assign]
            world.start_child(lines=3, execution_id=_EXECUTION_B)
            with (
                patch.object(
                    app, "_on_progress_incarnation_changed", wraps=app._on_progress_incarnation_changed
                ) as handler,
                patch.object(world.session, "abort") as abort,
                patch.object(screen, "apply_snapshot") as late_paint,
            ):
                await _tick(app=app, pilot=pilot)

            handler.assert_called_once_with(key=key)
            generation: int = int(order[0].split(":")[1])
            assert order == [
                f"minimize:{generation}",
                f"dismiss:{generation + 1}",
                f"generation:{generation + 1}",
            ]
            assert [s for s in app.screen_stack if isinstance(s, SessionProgressScreen)] == []
            assert key not in sink._viewports
            late_paint.assert_not_called()
            abort.assert_not_called()

    async def test_incarnation_change_with_confirmation_open(self, tmp_path: Path) -> None:
        """Same-key reuse while confirming withdraws the confirmation (False) before the view; no abort."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=30)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            key: WorkflowSessionKeyDAO = screen.key
            confirmation: AbortConfirmationScreen = await _open_confirmation(app=app, pilot=pilot)
            coordinator: WorkflowProgressCoordinator = _coordinator(app=app)
            order: list[str] = []
            results: list[Optional[bool]] = []
            real_minimize = coordinator.minimize
            real_withdraw = confirmation.withdraw
            real_dismiss = confirmation.dismiss

            def minimize() -> None:
                order.append(f"minimize:{coordinator._generation}")
                real_minimize()

            def withdraw() -> None:
                order.append(f"withdraw:{coordinator._generation}")
                real_withdraw()

            def dismiss(result: Optional[bool] = None) -> AwaitComplete:
                results.append(result)
                return real_dismiss(result)

            coordinator.minimize = minimize  # type: ignore[method-assign]
            confirmation.withdraw = withdraw  # type: ignore[method-assign]
            confirmation.dismiss = dismiss  # type: ignore[method-assign]
            world.start_child(lines=3, execution_id=_EXECUTION_B)
            with (
                patch.object(
                    app, "_on_progress_incarnation_changed", wraps=app._on_progress_incarnation_changed
                ) as handler,
                patch.object(world.session, "abort") as abort,
                patch.object(screen, "apply_snapshot") as late_paint,
            ):
                await _tick(app=app, pilot=pilot)
                await _settle(app=app, pilot=pilot)

            handler.assert_called_once_with(key=key)
            generation: int = int(order[0].split(":")[1])
            assert order == [f"minimize:{generation}", f"withdraw:{generation + 1}"]
            assert results == [False]
            assert [
                s for s in app.screen_stack if isinstance(s, (SessionProgressScreen, AbortConfirmationScreen))
            ] == []
            assert key not in sink._viewports
            late_paint.assert_not_called()
            abort.assert_not_called()
            assert seam.calls == []
            assert app._workflow_app_service is not None
            assert app._workflow_app_service._abort_submissions == {}

    async def test_removal_with_confirmation_open(self, tmp_path: Path) -> None:
        """Group removal while confirming withdraws the confirmation (False) before the view; no abort."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=5)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            key: WorkflowSessionKeyDAO = screen.key
            confirmation: AbortConfirmationScreen = await _open_confirmation(app=app, pilot=pilot)
            coordinator: WorkflowProgressCoordinator = _coordinator(app=app)
            order: list[str] = []
            results: list[Optional[bool]] = []
            real_minimize = coordinator.minimize
            real_withdraw = confirmation.withdraw
            real_dismiss = confirmation.dismiss
            real_retire = screen.retire

            def minimize() -> None:
                order.append("minimize")
                real_minimize()

            def withdraw() -> None:
                order.append("withdraw")
                real_withdraw()

            def dismiss(result: Optional[bool] = None) -> AwaitComplete:
                results.append(result)
                return real_dismiss(result)

            def retire() -> None:
                order.append("retire")
                real_retire()

            coordinator.minimize = minimize  # type: ignore[method-assign]
            confirmation.withdraw = withdraw  # type: ignore[method-assign]
            confirmation.dismiss = dismiss  # type: ignore[method-assign]
            screen.retire = retire  # type: ignore[method-assign]
            world.supplier.snapshot = AttachedDispatchSnapshotDAO.empty()
            with (
                patch.object(world.session, "abort") as abort,
                patch.object(screen, "apply_snapshot") as late_paint,
            ):
                await _tick(app=app, pilot=pilot)
                await _settle(app=app, pilot=pilot)

            assert order == ["minimize", "withdraw", "retire"]
            assert results == [False]
            assert [
                s for s in app.screen_stack if isinstance(s, (SessionProgressScreen, AbortConfirmationScreen))
            ] == []
            assert key not in sink._viewports
            late_paint.assert_not_called()
            abort.assert_not_called()
            assert seam.calls == []
            assert app._workflow_app_service is not None
            assert app._workflow_app_service._abort_submissions == {}

    async def test_dispose_with_confirmation_open(self, tmp_path: Path) -> None:
        """Observation teardown while confirming withdraws the confirmation (False) before the view."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=5)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            service = app._workflow_app_service
            assert service is not None
            confirmation: AbortConfirmationScreen = await _open_confirmation(app=app, pilot=pilot)
            order: list[str] = []
            results: list[Optional[bool]] = []
            real_minimize = sink.minimize_progress
            real_withdraw = confirmation.withdraw
            real_dismiss = confirmation.dismiss
            real_retire = screen.retire

            def minimize() -> None:
                order.append("minimize")
                real_minimize()

            def withdraw() -> None:
                order.append("withdraw")
                real_withdraw()

            def dismiss(result: Optional[bool] = None) -> AwaitComplete:
                results.append(result)
                return real_dismiss(result)

            def retire() -> None:
                order.append("retire")
                real_retire()

            sink.minimize_progress = minimize  # type: ignore[method-assign]
            confirmation.withdraw = withdraw  # type: ignore[method-assign]
            confirmation.dismiss = dismiss  # type: ignore[method-assign]
            screen.retire = retire  # type: ignore[method-assign]
            with (
                patch.object(world.session, "abort") as abort,
                patch.object(screen, "apply_snapshot") as late_paint,
            ):
                await app._close_workflow_observation()
                for _ in range(3):
                    await pilot.pause()

            assert order == ["minimize", "withdraw", "retire"]
            assert results == [False]
            assert [
                s for s in app.screen_stack if isinstance(s, (SessionProgressScreen, AbortConfirmationScreen))
            ] == []
            assert sink._viewports == {}
            late_paint.assert_not_called()
            abort.assert_not_called()
            assert seam.calls == []
            assert service._abort_submissions == {}

    async def test_confirmation_choices_and_double_activation(self, tmp_path: Path) -> None:
        """Escape and Keep running submit nothing; a double click opens one confirmation; True submits once."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=5)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)

            await _open_confirmation(app=app, pilot=pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            await _open_confirmation(app=app, pilot=pilot)
            await pilot.click("#keep-running")
            await pilot.pause()
            assert app.screen is screen
            assert seam.calls == []

            screen.query_one("#abort-child").press()  # type: ignore[attr-defined]
            screen.query_one("#abort-child").press()  # type: ignore[attr-defined]
            for _ in range(3):
                await pilot.pause()
            assert len([s for s in app.screen_stack if isinstance(s, AbortConfirmationScreen)]) == 1
            await pilot.click("#confirm-abort")
            await _settle(app=app, pilot=pilot)
            assert app._workflow_app_service is not None
            for submission in tuple(app._workflow_app_service._abort_submissions.values()):
                await submission.join()

            [request] = seam.calls
            assert (
                request.orchestrator_session_id,
                request.session_id,
                request.execution_id,
                request.run_id,
            ) == (
                world.session.session_id,
                _CHILD,
                _EXECUTION_A,
                _RUN_ID,
            )
            assert app.screen is screen

    async def test_confirmation_closed_without_result_submits_nothing(self, tmp_path: Path) -> None:
        """A confirmation dismissed with no result (None) is forgotten and never submits."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=5)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            service = app._workflow_app_service
            assert sink is not None and service is not None
            confirmation: AbortConfirmationScreen = await _open_confirmation(app=app, pilot=pilot)
            assert sink._confirmation is confirmation
            with (
                patch.object(service, "begin_child_abort", wraps=service.begin_child_abort) as begin,
                patch.object(world.session, "abort") as whole_abort,
            ):
                await confirmation.dismiss()
                await _settle(app=app, pilot=pilot)

            assert app.screen is screen
            assert sink._confirmation is None
            begin.assert_not_called()
            whole_abort.assert_not_called()
            assert seam.calls == []
            assert service._abort_submissions == {}

    async def test_minimize_during_attached_abort_keeps_request(self, tmp_path: Path) -> None:
        """Escape while the pool works neither cancels nor repeats the request; reopen shows the outcome."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        seam.gate.clear()
        world.start_child(lines=5)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            assert app._adapter is not None
            foreground: list[tuple[str, str]] = list(app._adapter.lines)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            await _open_confirmation(app=app, pilot=pilot)
            with patch.object(world.session, "abort") as whole_abort:
                await pilot.click("#confirm-abort")
                await _settle(app=app, pilot=pilot)
                state: str = str(screen.query_one("#session-state", Static).render())
                assert "Abort requested" in state
                assert screen.query_one("#abort-child").disabled  # type: ignore[attr-defined]

                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)
                assert [s for s in app.screen_stack if isinstance(s, SessionProgressScreen)] == []
                assert app._workflow_app_service is not None
                [submission] = app._workflow_app_service._abort_submissions.values()
                assert submission.blocks_new_request
                seam.gate.set()
                await submission.join()
                world.finish(status="aborted")
                await _tick(app=app, pilot=pilot)

                reopened: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
                reopened_state: str = str(reopened.query_one("#session-state", Static).render())

            assert "Child aborted." in reopened_state
            assert "aborted" in reopened_state
            assert len(seam.calls) == 1
            whole_abort.assert_not_called()
            assert list(app._adapter.lines) == foreground

    async def test_matching_incarnation_invokes_no_handler(self, tmp_path: Path) -> None:
        """A tick with the same execution leaves the view open and calls no handler."""
        world: _World = _World(tmp_path=tmp_path)
        world.start_child(lines=3)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            screen: SessionProgressScreen = await _open_child(app=app, pilot=pilot)
            with patch.object(app, "_on_progress_incarnation_changed") as handler:
                await _tick(app=app, pilot=pilot)

            handler.assert_not_called()
            assert _screen(app=app) is screen

    async def test_viewport_cache_evicts_the_oldest_beyond_64(self, tmp_path: Path) -> None:
        """Sixty-five visited keys keep the 64 most recent viewports."""
        world: _World = _World(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            owner: str = world.session.session_id
            keys: list[WorkflowSessionKeyDAO] = [
                WorkflowSessionKeyDAO(orchestrator_session_id=owner, session_id=f"child-{index:02d}")
                for index in range(65)
            ]
            rows = tuple(
                WorkflowSessionRowDAO(
                    key=key, role="child", status="running", task_text="t", task_text_complete=False
                )
                for key in keys
            )
            await _coordinator(app=app).close()
            await sink.apply_sessions(snapshot=WorkflowSessionSnapshotDAO(rows=rows))
            for key in keys:
                assert sink.open_progress(key=key) is True
                await _until_live(pilot=pilot, screen=_screen(app=app))
            assert len(sink._viewports) == 64
            sink.minimize_progress()
            await pilot.pause()

            assert len(sink._viewports) == 64
            assert keys[0] not in sink._viewports
            assert list(sink._viewports)[-1] == keys[64]
            assert sink._viewports[keys[1]] == ProgressViewportDAO()

    async def test_owner_replacement_during_apply_sessions(self, tmp_path: Path) -> None:
        """``/new`` while a row application is in flight joins it; nothing old repaints."""
        world: _World = _World(tmp_path=tmp_path)
        world.start_child(lines=3)
        replacement: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
            workdir=tmp_path,
            session_id=str(uuid4()),
        )
        replacement.attached_dispatch_snapshot = AttachedDispatchSnapshotDAO.empty  # type: ignore[method-assign]
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            panel: Optional[SubAgentFleetPanel] = app._fleet_panel
            assert panel is not None
            gate: asyncio.Event = asyncio.Event()
            entered: asyncio.Event = asyncio.Event()
            real_apply_rows = panel._apply_rows

            async def gated_apply_rows(*, rows: tuple[WorkflowSessionRowDAO, ...]) -> None:
                if rows:
                    entered.set()
                    await gate.wait()
                await real_apply_rows(rows=rows)

            panel._apply_rows = gated_apply_rows  # type: ignore[method-assign]
            world.append(start=3, lines=1)
            world.supplier.publish(status="running")
            _coordinator(app=app).request_refresh()
            await entered.wait()
            with patch("src.tui.app.SloAgentSession.build", return_value=replacement):
                replacing: asyncio.Task[None] = asyncio.create_task(
                    app._start_new_session(requested_name=None)
                )
                await asyncio.sleep(0)
                assert not replacing.done()
                gate.set()
                await replacing
            await _settle(app=app, pilot=pilot)

            assert list(panel.query(SubAgentFleetRow)) == []
            assert panel.display is False
            assert app._session is replacement


class TestAttachedAndDetachedListInRealApp:
    """One list shows the attached batch first, then the owner's detached groups."""

    async def test_attached_and_detached_list_in_real_app(self, tmp_path: Path) -> None:
        """Real handle, fleet and capture files produce ordered attached and detached rows."""
        world: _World = _World(tmp_path=tmp_path)
        world.start_child(lines=2)
        handles: WorkflowHandleStore = WorkflowHandleStore(
            history_root=world.root, pid_alive=lambda pid: True
        )
        await handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-a",
                owner_session_id=world.session.session_id,
                orchestrator_session_id="orch-a",
                pid=4242,
                brief="Refactor the [b]loader[/b]",
                cwd=str(tmp_path),
                state="running",
            )
        )
        await handles.write(
            handle=WorkflowHandleDAO(
                workflow_id="wf-other",
                owner_session_id="someone-else",
                orchestrator_session_id="orch-x",
                pid=4243,
                brief="not ours",
                cwd=str(tmp_path),
                state="running",
            )
        )
        FleetStore(history_root=world.root, orchestrator_session_id="orch-a", run_id=None).persist(
            entries=[
                SubAgentStatusDAO(
                    task_id="task-legacy",
                    session_id="child-legacy",
                    status="completed",
                    prompt_preview="legacy task",
                )
            ]
        )
        app: SloTUI = SloTUI(session=world.session, workflow_handle_store=handles)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)

            assert app._fleet_panel is not None
            rows: list[WorkflowSessionRowDAO] = [
                item.row for item in app._fleet_panel.query(SubAgentFleetRow)
            ]
            assert [(row.key.orchestrator_session_id, row.key.session_id) for row in rows] == [
                (world.session.session_id, world.session.session_id),
                (world.session.session_id, _CHILD),
                ("orch-a", "orch-a"),
                ("orch-a", "child-legacy"),
            ]
            assert [row.status for row in rows] == ["running", "running", "running", "completed"]
            assert rows[1].task_text == "Audit the parser thoroughly"
            assert rows[2].task_text == "Refactor the [b]loader[/b]"
            assert len(app.query(SubAgentFleetPanel)) == 1


def _tree_state(*, root: Path) -> dict[str, tuple[bytes, int]]:
    """Snapshot every regular file's bytes and nanosecond mtime below ``root``.

    Args:
        root (Path): Directory to snapshot.

    Returns:
        dict[str, tuple[bytes, int]]: Relative path to (bytes, ``st_mtime_ns``).
    """
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


async def _write_detached(
    *, world: _World, handles: WorkflowHandleStore, workflow_id: str, orchestrator: str, state: str, hour: int
) -> None:
    """Persist one owned detached handle and its legacy fleet with one child of the same status.

    Args:
        world (_World): Owner world.
        handles (WorkflowHandleStore): Real handle store over the world's root.
        workflow_id (str): Workflow id.
        orchestrator (str): Detached orchestrator session id.
        state (str): Handle state, also used as the child's status.
        hour (int): Launch hour for list order.
    """
    await handles.write(
        handle=WorkflowHandleDAO(
            workflow_id=workflow_id,
            owner_session_id=world.session.session_id,
            orchestrator_session_id=orchestrator,
            pid=4242,
            brief=f"brief {workflow_id}",
            cwd=str(world.root),
            state=state,  # type: ignore[arg-type]
            started_at=datetime(2026, 10, 18, hour, tzinfo=timezone.utc),
        )
    )
    FleetStore(history_root=world.root, orchestrator_session_id=orchestrator, run_id=None).persist(
        entries=[
            SubAgentStatusDAO(
                task_id=f"task-{workflow_id}",
                session_id=f"child-{workflow_id}",
                status=state,  # type: ignore[arg-type]
                prompt_preview=f"task {workflow_id}",
            )
        ]
    )


class TestClearFinishedGroupsInRealApp:
    """``/workflows tui dismiss`` through the real stack (94.a.5 acceptance 1, 2 and 5)."""

    async def test_clear_finished_groups_end_to_end(self, tmp_path: Path) -> None:
        """Finished attached and detached groups go, the running one stays, nothing is written."""
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=1)
        world.finish(status="completed")
        handles: WorkflowHandleStore = WorkflowHandleStore(
            history_root=world.root, pid_alive=lambda pid: True
        )
        await _write_detached(
            world=world,
            handles=handles,
            workflow_id="wf-done",
            orchestrator="orch-done",
            state="completed",
            hour=9,
        )
        await _write_detached(
            world=world,
            handles=handles,
            workflow_id="wf-live",
            orchestrator="orch-live",
            state="running",
            hour=10,
        )
        app: SloTUI = SloTUI(session=world.session, workflow_handle_store=handles)
        owner: str = world.session.session_id

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            assert app._fleet_panel is not None and app._input is not None and app._adapter is not None
            assert [
                item.row.key.orchestrator_session_id for item in app._fleet_panel.query(SubAgentFleetRow)
            ] == [
                owner,
                owner,
                "orch-done",
                "orch-done",
                "orch-live",
                "orch-live",
            ]
            before: dict[str, tuple[bytes, int]] = _tree_state(root=world.root)

            app._input.load_text("/workflows tui dismiss")
            await pilot.press("enter")
            await _settle(app=app, pilot=pilot)
            await _tick(app=app, pilot=pilot)

            visible = [item.row.key for item in app._fleet_panel.query(SubAgentFleetRow)]
            assert [(key.orchestrator_session_id, key.session_id) for key in visible] == [
                ("orch-live", "orch-live"),
                ("orch-live", "child-wf-live"),
            ]
            assert (
                "cleared 2 finished workflow group(s) from the list; 1 still running",
                "tool-result",
            ) in app._adapter.lines
            assert _tree_state(root=world.root) == before
            assert seam.calls == []
            assert {handle.state for handle in await handles.list_observation(owner_session_id=owner)} == {
                "completed",
                "running",
            }


_SIBLINGS: int = 19
_LONG_TASK: str = "Verify the redesigned workflow list keeps long task text readable " * 4
_LONG_LINE: str = "wide-tool-output-" + "x" * 300
_MULTILINE_DRAFT: str = "First draft line\nSecond draft line\nThird draft line"
_THEMES: tuple[str, ...] = ("slo-dark", "slo-default")


def _publish_fleet(*, world: _World, target_status: str) -> None:
    """Report the target child plus nineteen long-task siblings as one attached batch.

    Args:
        world (_World): World whose ``start_child`` already wrote the target's files.
        target_status (str): Registry status of the target child; siblings stay running.
    """
    siblings: tuple[SubAgentStatusDAO, ...] = tuple(
        SubAgentStatusDAO(
            task_id=f"task-{index:02d}",
            session_id=f"sibling-{index:02d}",
            status="running",
            prompt_preview=f"{index:02d} {_LONG_TASK}",
        )
        for index in range(_SIBLINGS)
    )
    world.supplier.snapshot = AttachedDispatchSnapshotDAO(
        dispatch_id=_DISPATCH_ID,
        dispatch_sequence=1,
        entries=(
            SubAgentStatusDAO(
                task_id="task-a",
                session_id=_CHILD,
                status=target_status,  # type: ignore[arg-type]
                execution_id=_EXECUTION_A,
                prompt_preview="Audit the parser",
            ),
            *siblings,
        ),
    )


def _append_long_line(*, world: _World) -> None:
    """Append one tool result whose output line is wider than every tested terminal.

    Tool output paints unwrapped, so it exercises horizontal panning; answers wrap.

    Args:
        world (_World): World with a started child capture.
    """
    events: list[dict[str, str]] = [
        {"kind": "tool_call_start", "block_id": "call-wide", "tool_name": "bash"},
        {"kind": "tool_call_end", "block_id": "call-wide"},
        {"kind": "tool_result", "tool_call_id": "call-wide", "content": _LONG_LINE},
    ]
    with (world.capture_dir / "stdout.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(event) + "\n" for event in events))


def _capture(*, app: SloTUI, views: Path, name: str) -> None:
    """Write the current screen as SVG for human visual review, only below ``views``.

    Args:
        app (SloTUI): Running app.
        views (Path): Test-owned capture directory (under ``tmp_path``).
        name (str): File stem.
    """
    target: Path = (views / f"{name}.svg").resolve()
    assert target.is_relative_to(views.resolve())
    target.write_text(app.export_screenshot(), encoding="utf-8")


def _row_statuses(*, app: SloTUI) -> dict[str, str]:
    """Return each painted row's status by session id.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        dict[str, str]: Session id to status.
    """
    assert app._fleet_panel is not None
    return {item.row.key.session_id: item.row.status for item in app._fleet_panel.query(SubAgentFleetRow)}


def _session_state(*, screen: SessionProgressScreen) -> list[str]:
    """Return the painted session-state line split into its ``" · "`` fields.

    The first field is the abort/notice message (when present) and the second is
    the loader's header status, so a test can tell "Abort requested" apart from
    terminal evidence.

    Args:
        screen (SessionProgressScreen): Open progress screen.

    Returns:
        list[str]: Painted fields in order.
    """
    return str(screen.query_one("#session-state", Static).render()).split(" · ")


class TestTwentyChildFleetJourney:
    """T12 composed release journey over a synthetic 20-child fleet in both themes and three sizes."""

    @pytest.mark.parametrize("theme", _THEMES)
    @pytest.mark.parametrize(
        ("width", "height"), [(60, 20), (80, 24), (120, 40)], ids=["60x20", "80x24", "120x40"]
    )
    async def test_twenty_child_fleet_journey(
        self, tmp_path: Path, theme: str, width: int, height: int
    ) -> None:
        """List → keyboard select → read history across updates → minimize/reopen → cancel → abort one child.

        The abort leg holds the pool seam so "Abort requested" paints with the header
        still ``running``; only after the seam answers and the child's terminal
        ``status.json`` plus execution evidence exist does the header read ``aborted``.
        The supplier is test-controlled, so the sibling statuses only show the list
        repaints; the target-only proof is the single recorded seam request (and the
        real-pool test in ``test_workflow_child_abort_tui.py``).
        """
        world: _World = _World(tmp_path=tmp_path)
        seam: _PoolSeam = world.enable_attached_control()
        world.start_child(lines=40)
        _append_long_line(world=world)
        _publish_fleet(world=world, target_status="running")
        views: Path = tmp_path / "views"
        views.mkdir()
        stem: str = f"{theme}-{width}x{height}"
        app: SloTUI = SloTUI(session=world.session)

        async with app.run_test(size=(width, height)) as pilot:
            app.theme = theme
            await _settle(app=app, pilot=pilot)
            assert app._input is not None and app._fleet_panel is not None and app._adapter is not None
            foreground: list[tuple[str, str]] = list(app._adapter.lines)
            app._input.load_text(_MULTILINE_DRAFT)
            await _settle(app=app, pilot=pilot)

            panel: SubAgentFleetPanel = app._fleet_panel
            usage: UsageStatusBar = app.query_one(UsageStatusBar)
            assert len(app.query(SubAgentFleetPanel)) == 1
            assert len(list(panel.query(SubAgentFleetRow))) == 1 + 1 + _SIBLINGS
            assert app._input.region.height >= 3
            assert panel.region.y >= app._input.region.bottom
            assert usage.region.y >= panel.region.bottom and usage.region.bottom <= height
            sibling: SubAgentFleetRow = next(
                item for item in panel.query(SubAgentFleetRow) if item.row.key.session_id == "sibling-00"
            )
            capped: str = f"00 {_LONG_TASK}"[: TASK_PREVIEW_MAX_CODE_POINTS - 1] + "…"
            assert str(sibling.query_one(Static).render()) == f"[running] sibling-00: {capped}"
            assert sibling.region.height <= 1
            _capture(app=app, views=views, name=f"{stem}-1-list-multiline")

            session_list: FleetSessionList = panel.query_one(FleetSessionList)
            panel.focus_sessions()
            await pilot.press(*(["down"] * (1 + _SIBLINGS)))
            await _settle(app=app, pilot=pilot)
            last: SubAgentFleetRow = list(panel.query(SubAgentFleetRow))[-1]
            assert last.row.key.session_id == f"sibling-{_SIBLINGS - 1:02d}"
            assert session_list.region.contains_region(last.region)
            assert app._input.text == _MULTILINE_DRAFT
            await pilot.press(*(["up"] * _SIBLINGS), "enter")
            await _settle(app=app, pilot=pilot)

            with patch.object(world.session, "abort") as whole_abort:
                screen: SessionProgressScreen = _screen(app=app)
                assert screen.key.session_id == _CHILD
                for button in screen.query(Button):
                    assert button.region.right <= width and button.region.bottom <= height
                log: ProgressLog = screen.query_one(ProgressLog)
                assert "wide-tool-output-xxxx" in _painted_log_text(screen=screen)
                assert log.max_scroll_x > 0
                log.scroll_to(x=4, y=5, animate=False, immediate=True)
                await pilot.pause()
                for start in (100, 110):
                    world.append(start=start, lines=10)
                    await _tick(app=app, pilot=pilot)
                assert "child line 119" in _painted_log_text(screen=screen)
                assert (log.scroll_x, log.scroll_y) == (4.0, 5.0)
                _capture(app=app, views=views, name=f"{stem}-2-progress-reading-history")

                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)
                assert [s for s in app.screen_stack if isinstance(s, SessionProgressScreen)] == []
                assert app.focused is not None and panel in app.focused.ancestors_with_self
                await pilot.press("enter")
                await _settle(app=app, pilot=pilot)
                reopened: SessionProgressScreen = _screen(app=app)
                reopened_log: ProgressLog = reopened.query_one(ProgressLog)
                assert (reopened_log.scroll_x, reopened_log.scroll_y) == (4.0, 5.0), (
                    f"max_scroll=({reopened_log.max_scroll_x}, {reopened_log.max_scroll_y}) "
                    f"size={reopened_log.size} virtual_size={reopened_log.virtual_size} "
                    f"lines={len(reopened_log.lines)}"
                )

                await _open_confirmation(app=app, pilot=pilot)
                _capture(app=app, views=views, name=f"{stem}-3-abort-confirmation")
                await pilot.press("escape")
                await pilot.pause()
                assert app.screen is reopened and seam.calls == []

                seam.gate.clear()
                await _open_confirmation(app=app, pilot=pilot)
                await pilot.click("#confirm-abort")
                await _settle(app=app, pilot=pilot)
                await _tick(app=app, pilot=pilot)
                pending: list[str] = _session_state(screen=reopened)
                assert pending[0].startswith("Abort requested") and pending[1] == "running"
                assert reopened.query_one("#abort-child", Button).disabled
                _capture(app=app, views=views, name=f"{stem}-4-abort-requested")

                seam.gate.set()
                assert app._workflow_app_service is not None
                for submission in tuple(app._workflow_app_service._abort_submissions.values()):
                    await submission.join()
                world.finish(status="aborted")
                _publish_fleet(world=world, target_status="aborted")
                await _tick(app=app, pilot=pilot)
                settled: list[str] = _session_state(screen=reopened)
                assert settled[:2] == ["Child aborted.", "aborted"]
                assert reopened.query_one("#abort-child", Button).disabled
                _capture(app=app, views=views, name=f"{stem}-5-child-aborted")
                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)
                _capture(app=app, views=views, name=f"{stem}-6-list-after-abort")

            [request] = seam.calls
            assert (request.session_id, request.execution_id) == (_CHILD, _EXECUTION_A)
            whole_abort.assert_not_called()
            statuses: dict[str, str] = _row_statuses(app=app)
            assert statuses.pop(_CHILD) == "aborted"
            assert set(statuses.values()) == {"running"} and len(statuses) == 1 + _SIBLINGS
            assert app._input.text == _MULTILINE_DRAFT
            assert list(app._adapter.lines) == foreground
            assert sorted(path.name for path in views.iterdir()) == [
                f"{stem}-1-list-multiline.svg",
                f"{stem}-2-progress-reading-history.svg",
                f"{stem}-3-abort-confirmation.svg",
                f"{stem}-4-abort-requested.svg",
                f"{stem}-5-child-aborted.svg",
                f"{stem}-6-list-after-abort.svg",
            ]
