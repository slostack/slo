"""Tests for the TUI detached-workflow receive path (spec 57.a.4 / 57.a.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.app import SloTUI


def _mock_session(*, history_root: Path) -> MagicMock:
    """Build the standard mocked ``SloAgentSession`` for TUI receive-path tests.

    Args:
        history_root (Path): History root exposed by the mock session.

    Returns:
        MagicMock: Session mock matching the ``SloAgentSession`` surface.
    """
    session: MagicMock = MagicMock(spec=SloAgentSession)
    session.workdir = Path(".").resolve()
    session.session_id = "session-1234"
    session.session_name = None
    session.active_model_name = "claude-sonnet-4-6"
    session.routed_model_name = "claude-sonnet-4-6"
    session.active_reasoning_level = "high"
    session.history_enabled = True
    session.history_root = history_root
    session.subscribe = MagicMock()
    session.unsubscribe = MagicMock()
    session.hydrate_transcript_entries = AsyncMock(return_value=[])
    session.should_show_startup_notice = AsyncMock(return_value=False)
    session.usage_snapshot = MagicMock(return_value=MagicMock())
    session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
    session.record_workflow_update = AsyncMock(return_value=True)
    return session


def _build_store(*, history_root: Path, pid_alive: bool = True) -> WorkflowHandleStore:
    """Build a workflow handle store with an injected liveness probe.

    Args:
        history_root (Path): Store root directory.
        pid_alive (bool): Fixed probe answer for every pid.

    Returns:
        WorkflowHandleStore: Store rooted at ``history_root``.
    """
    return WorkflowHandleStore(
        history_root=history_root,
        pid_alive=lambda pid: pid_alive,
    )


async def _write_handle(
    *,
    store: WorkflowHandleStore,
    workflow_id: str = "wf-1",
    state: WorkflowState = "launching",
) -> WorkflowHandleDAO:
    """Persist one handle owned by the test session.

    Args:
        store (WorkflowHandleStore): Target store.
        workflow_id (str): Handle workflow id.
        state (WorkflowState): Initial handle state.

    Returns:
        WorkflowHandleDAO: The persisted handle.
    """
    handle: WorkflowHandleDAO = WorkflowHandleDAO(
        workflow_id=workflow_id,
        owner_session_id="session-1234",
        orchestrator_session_id="orch-1",
        pid=4242,
        brief="run the workflow",
        cwd="/tmp",
        state=state,
    )
    await store.write(handle=handle)
    return handle


def _workflow_message(
    *,
    kind: str,
    delivery_mode: str = "context_note",
    message_id: str = "message-1",
    workflow_id: str = "wf-1",
    orchestrator_session_id: str = "orch-1",
) -> SessionInboxMessageDAO:
    """Build one workflow lifecycle inbox message.

    Args:
        kind (str): Workflow lifecycle message kind.
        delivery_mode (str): Inbox delivery mode.
        message_id (str): Stable message id.
        workflow_id (str): Owning workflow id.
        orchestrator_session_id (str): Detached orchestrator session id.

    Returns:
        SessionInboxMessageDAO: The built message.
    """
    return SessionInboxMessageDAO(
        message_id=message_id,
        session_id="session-1234",
        schedule_id=f"workflow:{workflow_id}",
        run_id="run-1",
        kind=kind,  # type: ignore[arg-type]
        delivery_mode=delivery_mode,  # type: ignore[arg-type]
        title=f"{workflow_id} update",
        text=f"[workflow {workflow_id}] lifecycle note",
        payload={
            "workflow_id": workflow_id,
            "orchestrator_session_id": orchestrator_session_id,
        },
    )


class TestContextNoteDelivery:
    """The ``context_note`` inbox branch (spec 57.a.4)."""

    @pytest.mark.asyncio
    async def test_context_note_renders_line_and_persists_event(self, tmp_path: Path) -> None:
        """A claimed context_note writes the ``⊛`` line AND records the event."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        message: SessionInboxMessageDAO = _workflow_message(kind="workflow_phase_update")

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._handle_inbox_message(message=message)

            assert app._adapter is not None
            assert any(
                content == "⊛ wf-1 update: [workflow wf-1] lifecycle note"
                and classes == "sub-agent-notice"
                for content, classes in app._adapter.lines
            )
            session.record_workflow_update.assert_awaited_once_with(
                text="[workflow wf-1] lifecycle note",
                message_id="message-1",
                workflow_id="wf-1",
            )

    @pytest.mark.asyncio
    async def test_context_note_missing_payload_defaults_workflow_unknown(
        self, tmp_path: Path
    ) -> None:
        """A context_note without workflow payload records ``wf-unknown``."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            message_id="message-1",
            session_id="session-1234",
            schedule_id="workflow:wf-1",
            run_id="run-1",
            kind="workflow_phase_update",
            delivery_mode="context_note",
            text="phase note",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._handle_inbox_message(message=message)

            session.record_workflow_update.assert_awaited_once_with(
                text="phase note",
                message_id="message-1",
                workflow_id="wf-unknown",
            )


class TestVisualizerRetarget:
    """The visualizer launches against the orchestrator session id (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_launch_result_triggers_visualizer_with_orch_sid(self, tmp_path: Path) -> None:
        """The launch_workflow tool result opens the visualizer on the orch session."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"}',
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._render_event(event)

            mock_launch.assert_called_once_with(parent_session_id="orch-1")
            assert app._adapter is not None
            assert any(
                "Opened workflow visualizer in a new window (session orch-1)." in content
                for content, _classes in app._adapter.lines
            )

    @pytest.mark.asyncio
    async def test_launch_result_error_json_does_not_trigger(self, tmp_path: Path) -> None:
        """A launch_workflow error JSON (no orchestrator id) never launches."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content='{"error": "workflow cap reached"}',
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._render_event(event)

            mock_launch.assert_not_called()
            assert app._visualizer_launched_for == set()

    @pytest.mark.asyncio
    async def test_duplicate_launch_result_launches_once(self, tmp_path: Path) -> None:
        """Redelivered launch results are guarded by the launched set."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )

            mock_launch.assert_called_once_with(parent_session_id="orch-1")

    @pytest.mark.asyncio
    async def test_launch_failure_writes_manual_command_hint(self, tmp_path: Path) -> None:
        """A failed window spawn writes the manual visualize command instead."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=False,
            ):
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )

            assert app._adapter is not None
            assert any(
                content == "⊇ Watch the workflow live: slo visualize --session orch-1 --follow"
                for content, _classes in app._adapter.lines
            )

    @pytest.mark.asyncio
    async def test_workflow_started_note_triggers_fallback_launch(self, tmp_path: Path) -> None:
        """The resume case: a claimed workflow_started note opens the visualizer."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="launching")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_started"),
                )

            mock_launch.assert_called_once_with(parent_session_id="orch-1")


class TestWorkflowHandleStateAdvance:
    """Claimed lifecycle notes advance the durable handle (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_started_note_advances_handle_to_running(self, tmp_path: Path) -> None:
        """``workflow_started`` maps to state ``running`` on disk."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="launching")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=True):
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_started"),
                )

            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "running"
            assert app._workflow_states["wf-1"] == "running"

    @pytest.mark.asyncio
    async def test_terminal_notes_advance_and_clear_launched_set(self, tmp_path: Path) -> None:
        """Terminal notes reach terminal states and free the visualizer guard."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="running")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._visualizer_launched_for.add("orch-1")
            with patch.object(app, "_start_inbox_chat_turn", new=AsyncMock()):
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_completed", delivery_mode="chat_turn"),
                )

            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "completed"
            assert "orch-1" not in app._visualizer_launched_for

    @pytest.mark.asyncio
    async def test_unknown_workflow_id_is_logged_not_raised(self, tmp_path: Path) -> None:
        """A missing handle file never fails inbox delivery."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=True):
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_started", workflow_id="wf-missing"),
                )

            assert "wf-missing" not in app._workflow_states

    @pytest.mark.asyncio
    async def test_illegal_transition_is_swallowed(self, tmp_path: Path) -> None:
        """An illegal transition (e.g. late failure on aborted) never raises."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="aborted")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "_start_inbox_chat_turn", new=AsyncMock()):
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_failed", delivery_mode="chat_turn"),
                )

            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "aborted"

    @pytest.mark.asyncio
    async def test_mount_reconciles_handles(self, tmp_path: Path) -> None:
        """A resumed TUI shows accurate states before any note arrives."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root, pid_alive=False)
        await _write_handle(store=store, state="running")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert app._workflow_states == {"wf-1": "stalled"}


class TestAbortSeparationAndExit:
    """Abort separation and the live-workflow exit hint (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_session_abort_leaves_detached_handles_untouched(self, tmp_path: Path) -> None:
        """``^C`` during a prompt aborts only the prompt — no handle writes."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="running")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._in_flight_task = asyncio.create_task(asyncio.sleep(60))
            with patch.object(
                store, "update_state", wraps=store.update_state
            ) as update_state_spy:
                await app.action_interrupt()

            session.abort.assert_called_once_with()
            update_state_spy.assert_not_called()
            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "running"
            app._in_flight_task.cancel()
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_detached_lifecycle_never_touches_fleet_panel(self, tmp_path: Path) -> None:
        """A full detached lifecycle keeps the fleet panel idle (v1 decision)."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="launching")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            fleet_panel_spy: MagicMock = MagicMock()
            app._fleet_panel = fleet_panel_spy
            with (
                patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=True),
                patch.object(app, "_start_inbox_chat_turn", new=AsyncMock()),
            ):
                await app._handle_inbox_message(
                    message=_workflow_message(kind="workflow_started"),
                )
                await app._handle_inbox_message(
                    message=_workflow_message(
                        kind="workflow_phase_update", message_id="message-2"
                    ),
                )
                await app._handle_inbox_message(
                    message=_workflow_message(
                        kind="workflow_completed",
                        delivery_mode="chat_turn",
                        message_id="message-3",
                    ),
                )

            fleet_panel_spy.register_row.assert_not_called()
            fleet_panel_spy.mark_terminal.assert_not_called()

    @pytest.mark.asyncio
    async def test_exit_hint_lists_live_workflows(self, tmp_path: Path) -> None:
        """Live workflows appear next to the resume command on exit."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        app._workflow_states = {"wf-1": "running", "wf-2": "completed"}

        hint: str = app._resume_command_hint()

        assert hint == (
            "Resume this session: slo --resume session-1234\n"
            "Live workflows: wf-1 (running). "
            "They keep running — list with /workflows after resume."
        )

    @pytest.mark.asyncio
    async def test_exit_hint_without_workflows_is_unchanged(self, tmp_path: Path) -> None:
        """Sessions without workflows print today's hint byte-identically."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        assert app._resume_command_hint() == "Resume this session: slo --resume session-1234"


class TestLaunchResultSeedsExitHint:
    """The launch turn itself makes the new workflow visible to the exit hint."""

    @pytest.mark.asyncio
    async def test_launch_result_seeds_state_cache_and_exit_hint(self, tmp_path: Path) -> None:
        """A workflow launched this session is listed before any note is claimed."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content=(
                '{"workflow_id": "wf-9a1b", "orchestrator_session_id": "orch-1", '
                '"state": "launching"}'
            ),
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ):
                await app._render_event(event)

            assert app._workflow_states == {"wf-9a1b": "launching"}
            assert app._resume_command_hint() == (
                "Resume this session: slo --resume session-1234\n"
                "Live workflows: wf-9a1b (launching). "
                "They keep running — list with /workflows after resume."
            )
