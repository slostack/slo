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
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildExecutionEvidenceDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO, WorkflowHandleStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import SloTUI
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
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

    def finish(self) -> None:
        """Publish the child's terminal status and evidence; the registry reports completed."""
        assert self.evidence is not None
        data: bytes = (
            SubAgentResultDAO(task_id="task-a", session_id=_CHILD, status="completed", exit_code=0)
            .model_dump_json()
            .encode()
        )
        (self.capture_dir / "status.json").write_bytes(data)
        self._store().publish_execution(
            evidence=self.evidence.terminal(
                status="completed", status_sha256=hashlib.sha256(data).hexdigest()
            )
        )
        self.supplier.publish(status="completed")

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
