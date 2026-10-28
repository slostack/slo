"""Tests for sub-agent event routing and the workflow session list (28.t.1, 94 a.2).

The orchestrator transcript is always in the foreground; there are no
sub-agent panes and no pane-switching. These tests verify:
- Lifecycle events write notices to the main transcript.
- Lifecycle events refresh the session list from the workflow service snapshot;
  content events never touch the list, so task labels stay stable.
- The orchestrator projector never receives sub-agent events.
- Prompt-end cleanup keeps the service-owned rows; an emptied list returns focus.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from textual.pilot import Pilot
from textual.screen import ModalScreen

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, SubAgentStatusDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.sub_agent_fleet_panel import FleetSessionList
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.dao import WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_session() -> SloAgentSession:
    """Build a minimal faux-backed session.

    Returns:
        SloAgentSession: Session with no real LLM calls.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _spawned(*, task_id: str = "task-A", session_id: str = "s1") -> AgentStreamEventDAO:
    """Build a ``sub_agent_spawned`` event."""
    return AgentStreamEventDAO(
        kind="sub_agent_spawned",
        sub_agent_id=session_id,
        task_id=task_id,
    )


def _completed(*, task_id: str = "task-A", session_id: str = "s1") -> AgentStreamEventDAO:
    """Build a ``sub_agent_completed`` event."""
    return AgentStreamEventDAO(
        kind="sub_agent_completed",
        sub_agent_id=session_id,
        task_id=task_id,
    )


def _failed(*, task_id: str = "task-A", session_id: str = "s1") -> AgentStreamEventDAO:
    """Build a ``sub_agent_failed`` event."""
    return AgentStreamEventDAO(
        kind="sub_agent_failed",
        sub_agent_id=session_id,
        task_id=task_id,
    )


def _text_delta(
    *,
    task_id: str = "task-A",
    session_id: str = "s1",
    delta: str = "hello",
) -> AgentStreamEventDAO:
    """Build a ``text_delta`` event tagged as a sub-agent event."""
    return AgentStreamEventDAO(
        kind="text_delta",
        sub_agent_id=session_id,
        task_id=task_id,
        delta=delta,
    )


def _thinking_delta(
    *,
    task_id: str = "task-A",
    session_id: str = "s1",
    delta: str = "child reasoning",
) -> AgentStreamEventDAO:
    """Build a ``thinking_delta`` event tagged as a sub-agent event."""
    return AgentStreamEventDAO(
        kind="thinking_delta",
        sub_agent_id=session_id,
        task_id=task_id,
        delta=delta,
        block_id="thinking:0:0",
    )


def _tool_call_end(
    *,
    task_id: str = "task-A",
    session_id: str = "s1",
    tool_name: str = "bash",
    tool_input: Optional[dict] = None,
) -> AgentStreamEventDAO:
    """Build a ``tool_call_end`` event tagged as a sub-agent event."""
    return AgentStreamEventDAO(
        kind="tool_call_end",
        sub_agent_id=session_id,
        task_id=task_id,
        tool_name=tool_name,
        tool_call_id="tc1",
        tool_input=tool_input or {"command": "pytest -x"},
    )


def _tool_result(
    *,
    task_id: str = "task-A",
    session_id: str = "s1",
    tool_name: str = "bash",
) -> AgentStreamEventDAO:
    """Build a ``tool_result`` event tagged as a sub-agent event."""
    return AgentStreamEventDAO(
        kind="tool_result",
        sub_agent_id=session_id,
        task_id=task_id,
        tool_name=tool_name,
        tool_call_id="tc1",
        content="output text",
    )


def _orchestrator_text_delta(*, delta: str = "orchestrator output") -> AgentStreamEventDAO:
    """Build an orchestrator ``text_delta`` (no sub_agent_id)."""
    return AgentStreamEventDAO(kind="text_delta", delta=delta, iteration=0)


def _aborted(*, task_id: str = "task-A", session_id: str = "s1") -> AgentStreamEventDAO:
    """Build a ``sub_agent_aborted`` event."""
    return AgentStreamEventDAO(
        kind="sub_agent_aborted",
        sub_agent_id=session_id,
        task_id=task_id,
    )


_DISPATCH_ID: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
_EXECUTION_ID: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"


class _AttachedSupplier:
    """Mutable stand-in for ``session.attached_dispatch_snapshot``, counting reads."""

    def __init__(self) -> None:
        """Start with the explicit no-dispatch value."""
        self.snapshot: AttachedDispatchSnapshotDAO = AttachedDispatchSnapshotDAO.empty()
        self.calls: int = 0

    def publish(
        self, *, status: str = "running", session_id: str = "s1", preview: str = "Audit the parser"
    ) -> None:
        """Replace the current batch with one child entry.

        Args:
            status (str, optional): Child status. Defaults to ``"running"``.
            session_id (str, optional): Child session id. Defaults to ``"s1"``.
            preview (str, optional): Registry task preview. Defaults to ``"Audit the parser"``.
        """
        self.snapshot = AttachedDispatchSnapshotDAO(
            dispatch_id=_DISPATCH_ID,
            dispatch_sequence=1,
            entries=(
                SubAgentStatusDAO(
                    task_id="task-A",
                    session_id=session_id,
                    status=status,  # type: ignore[arg-type]
                    execution_id=_EXECUTION_ID,
                    prompt_preview=preview,
                ),
            ),
        )

    def __call__(self) -> AttachedDispatchSnapshotDAO:
        """Return the current batch and count the read.

        Returns:
            AttachedDispatchSnapshotDAO: Current attached projection.
        """
        self.calls += 1
        return self.snapshot


async def _install_service(*, app: SloTUI) -> _AttachedSupplier:
    """Rebind workflow observation to a test supplier for the current session.

    Shadows the session's attached supplier, then rebinds through the app's own
    owner-replacement path, so the real service, sink and coordinator read it.

    Args:
        app (SloTUI): Mounted app with a no-history session.

    Returns:
        _AttachedSupplier: The supplier the service reads on every snapshot.
    """
    supplier: _AttachedSupplier = _AttachedSupplier()
    app._session.attached_dispatch_snapshot = supplier  # type: ignore[method-assign]
    await app._bind_workflow_observation()
    return supplier


async def _settle(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Await the coordinator's in-flight refresh, then let Textual paint.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Active pilot.
    """
    coordinator: Optional[WorkflowProgressCoordinator] = app._workflow_progress_coordinator
    task: Optional[asyncio.Task[None]] = coordinator._task if coordinator is not None else None
    if task is not None:
        await task
    await pilot.pause()


async def _refresh(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Request one coordinator refresh and wait until it painted.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Active pilot.
    """
    assert app._workflow_progress_coordinator is not None
    app._workflow_progress_coordinator.request_refresh()
    await _settle(app=app, pilot=pilot)


def _painted_rows(*, app: SloTUI) -> dict[str, str]:
    """Return each mounted row's status by session id.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        dict[str, str]: Session id to displayed status.
    """
    assert app._fleet_panel is not None
    return {item.row.key.session_id: item.row.status for item in app._fleet_panel.query(SubAgentFleetRow)}


# ---------------------------------------------------------------------------
# TestSubAgentEventRouting
# ---------------------------------------------------------------------------


class TestSubAgentEventRouting:
    """``_route_sub_agent_event`` and content-isolation invariants."""

    @pytest.mark.asyncio
    async def test_spawned_writes_notice_to_main_transcript(self) -> None:
        """``sub_agent_spawned`` writes ``⊇ task-A: spawned`` to the adapter."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await _settle(app=app, pilot=pilot)

            assert app.query_one(ChatTranscript)._adapter is not None
            lines = [content for content, _ in app.query_one(ChatTranscript)._adapter.lines]
        assert any("task-A" in line and "spawned" in line for line in lines)
        assert any("⊇" in line for line in lines)

    @pytest.mark.asyncio
    async def test_spawned_does_not_reach_orchestrator_projector(self) -> None:
        """The orchestrator projector is NOT called for a sub-agent spawned event."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch.object(
                app.query_one(ChatTranscript)._projector, "project", new_callable=AsyncMock
            ) as mock_proj:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await _settle(app=app, pilot=pilot)

            mock_proj.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawned_refreshes_the_session_list(self) -> None:
        """``sub_agent_spawned`` shows the parent and child rows from the service snapshot."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            supplier.publish()
            assert app._fleet_panel is not None
            assert app._fleet_panel.display is False

            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await _settle(app=app, pilot=pilot)

            assert app._fleet_panel.display is True
            assert _painted_rows(app=app) == {app._session.session_id: "running", "s1": "running"}

    @pytest.mark.asyncio
    async def test_session_without_history_shows_attached_rows_after_spawn(self) -> None:
        """A no-history session observes its own attached batch through the mount-bound service."""
        session: SloAgentSession = _build_session()
        supplier: _AttachedSupplier = _AttachedSupplier()
        supplier.publish(session_id="child-1")

        with patch.object(session, "attached_dispatch_snapshot", new=supplier):
            app: SloTUI = SloTUI(session=session)
            async with app.run_test(size=(120, 40)) as pilot:
                await _settle(app=app, pilot=pilot)
                await app._render_event(_spawned(task_id="task-A", session_id="child-1"))
                await _settle(app=app, pilot=pilot)

                assert app._fleet_panel is not None
                assert app._fleet_panel.display is True
                assert _painted_rows(app=app) == {session.session_id: "running", "child-1": "running"}

    @pytest.mark.asyncio
    async def test_new_session_spawn_shows_only_rows_owned_by_the_new_session(self) -> None:
        """After ``/new`` the list drops the old rows and observes only the adopted session."""
        old_session: SloAgentSession = _build_session()
        new_session: SloAgentSession = _build_session()
        old_supplier: _AttachedSupplier = _AttachedSupplier()
        old_supplier.publish(session_id="old-child")
        new_supplier: _AttachedSupplier = _AttachedSupplier()
        new_supplier.publish(session_id="new-child")

        with (
            patch.object(old_session, "attached_dispatch_snapshot", new=old_supplier),
            patch.object(new_session, "attached_dispatch_snapshot", new=new_supplier),
        ):
            app: SloTUI = SloTUI(session=old_session)
            async with app.run_test(size=(120, 40)) as pilot:
                await _settle(app=app, pilot=pilot)
                await app._render_event(_spawned(task_id="task-A", session_id="old-child"))
                await _settle(app=app, pilot=pilot)
                assert "old-child" in _painted_rows(app=app)

                with patch("src.tui.app.SloAgentSession.build", return_value=new_session):
                    await app._start_new_session(requested_name=None)
                old_reads: int = old_supplier.calls
                await _settle(app=app, pilot=pilot)
                assert _painted_rows(app=app) == {new_session.session_id: "running", "new-child": "running"}

                await app._render_event(_spawned(task_id="task-A", session_id="new-child"))
                await _settle(app=app, pilot=pilot)

                assert _painted_rows(app=app) == {new_session.session_id: "running", "new-child": "running"}
                assert old_supplier.calls == old_reads

    @pytest.mark.asyncio
    async def test_text_delta_does_not_appear_in_main_transcript(self) -> None:
        """A sub-agent ``text_delta`` does NOT add any entry to the adapter."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            lines_before = (
                len(app.query_one(ChatTranscript)._adapter.lines)
                if app.query_one(ChatTranscript)._adapter
                else 0
            )
            await app._render_event(_text_delta(task_id="task-A", session_id="s1", delta="work"))
            await _settle(app=app, pilot=pilot)

            lines_after = (
                len(app.query_one(ChatTranscript)._adapter.lines)
                if app.query_one(ChatTranscript)._adapter
                else 0
            )
            assert lines_after == lines_before

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_event",
        [
            _text_delta(delta="analyzing files"),
            _thinking_delta(delta="child reasoning"),
            _tool_call_end(tool_input={"command": "pytest -x"}),
            _tool_result(),
        ],
        ids=["text_delta", "thinking_delta", "tool_call_end", "tool_result"],
    )
    async def test_content_events_never_touch_the_session_list(
        self, content_event: AgentStreamEventDAO
    ) -> None:
        """Child content neither reads the service nor changes a row's label or status."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            supplier.publish(preview="Audit the parser")
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await _settle(app=app, pilot=pilot)
            reads_after_spawn: int = supplier.calls
            supplier.publish(status="completed", preview="should not appear")

            await app._render_event(content_event)
            await _settle(app=app, pilot=pilot)

            assert supplier.calls == reads_after_spawn
            assert app._fleet_panel is not None
            [child] = [
                item for item in app._fleet_panel.query(SubAgentFleetRow) if item.row.key.session_id == "s1"
            ]
            assert (child.row.status, child.row.task_text) == ("running", "Audit the parser")
            assert list(app.query(selector=AssistantStreamThinkingBlock)) == []

    @pytest.mark.asyncio
    async def test_orchestrator_event_bypasses_session_list(self) -> None:
        """An event with ``sub_agent_id=None`` never reads the workflow service."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            await _settle(app=app, pilot=pilot)
            reads_after_bind: int = supplier.calls
            await app._render_event(_orchestrator_text_delta())
            await _settle(app=app, pilot=pilot)

            assert supplier.calls == reads_after_bind
            assert _painted_rows(app=app) == {}

    @pytest.mark.asyncio
    async def test_completed_writes_notice_to_main_transcript(self) -> None:
        """``sub_agent_completed`` writes ``⊇ task-A: completed`` to the adapter."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_completed(task_id="task-A", session_id="s1"))
            await _settle(app=app, pilot=pilot)

            assert app.query_one(ChatTranscript)._adapter is not None
            lines = [content for content, _ in app.query_one(ChatTranscript)._adapter.lines]
        assert any("task-A" in line and "completed" in line for line in lines)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("terminal_event", "status"),
        [(_completed(), "completed"), (_failed(), "failed"), (_aborted(), "aborted")],
        ids=["completed", "failed", "aborted"],
    )
    async def test_terminal_event_refreshes_row_status(
        self, terminal_event: AgentStreamEventDAO, status: str
    ) -> None:
        """Completed, failed and aborted events show the snapshot's terminal status."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            supplier.publish()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            supplier.publish(status=status)
            await app._render_event(terminal_event)
            await _settle(app=app, pilot=pilot)

            assert _painted_rows(app=app)["s1"] == status

    @pytest.mark.asyncio
    async def test_aborted_event_writes_no_new_transcript_notice(self) -> None:
        """``sub_agent_aborted`` refreshes the list without adding a transcript line."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            await _install_service(app=app)
            lines_before: int = (
                len(app.query_one(ChatTranscript)._adapter.lines)
                if app.query_one(ChatTranscript)._adapter
                else 0
            )
            await app._render_event(_aborted())
            await _settle(app=app, pilot=pilot)

            assert (
                len(app.query_one(ChatTranscript)._adapter.lines)
                if app.query_one(ChatTranscript)._adapter
                else 0
            ) == lines_before

    @pytest.mark.asyncio
    async def test_late_content_cannot_regress_terminal_row(self) -> None:
        """A late child delta after completion leaves the completed row unchanged."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            supplier.publish(status="completed")
            await app._render_event(_completed(task_id="task-A", session_id="s1"))
            await app._render_event(_text_delta(task_id="task-A", session_id="s1", delta="late"))
            await _settle(app=app, pilot=pilot)

            assert _painted_rows(app=app)["s1"] == "completed"

    @pytest.mark.asyncio
    async def test_no_pane_switching_controls(self) -> None:
        """No pane-switching infrastructure exists — orchestrator is always foreground."""
        app: SloTUI = SloTUI(session=_build_session())

        assert not hasattr(app, "_pane_manager")
        assert not hasattr(app, "_tab_strip")
        assert not hasattr(app, "_panes_container")
        assert not hasattr(app, "action_switch_pane")


# ---------------------------------------------------------------------------
# TestFleetPanelCleanup
# ---------------------------------------------------------------------------


class TestFleetPanelCleanup:
    """Fleet panel lifecycle on run completion."""

    @pytest.mark.asyncio
    async def test_prompt_end_cleanup_retains_rows(self) -> None:
        """``_cleanup_sub_agent_state`` keeps the service-owned rows on screen."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await _settle(app=app, pilot=pilot)

            assert app._fleet_panel is not None
            assert app._fleet_panel.display is True

            await app._cleanup_sub_agent_state()
            await pilot.pause()

            assert app._fleet_panel is not None
            assert app._fleet_panel.display is True
            assert _painted_rows(app=app) == {app._session.session_id: "running", "s1": "running"}

    @pytest.mark.asyncio
    async def test_cleanup_after_failed_list_application_completes(self) -> None:
        """A failed row mount is reported once, never wedges cleanup, and the next refresh repaints."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            await _settle(app=app, pilot=pilot)
            supplier.publish()
            assert app._fleet_panel is not None
            session_list: FleetSessionList = app._fleet_panel.query_one(FleetSessionList)
            failing_extend: AsyncMock = AsyncMock(side_effect=RuntimeError("mount failed once"))
            with (
                patch.object(session_list, "extend", new=failing_extend),
                patch.object(app, "notify") as notify,
            ):
                await _refresh(app=app, pilot=pilot)
            notify.assert_called_once()
            assert "retrying" in notify.call_args.kwargs["message"]
            app._visualizer_launched_for_run = True

            await app._cleanup_sub_agent_state()
            await _refresh(app=app, pilot=pilot)

            assert app._visualizer_launched_for_run is False
            assert _painted_rows(app=app) == {app._session.session_id: "running", "s1": "running"}

    @pytest.mark.asyncio
    async def test_cleanup_is_safe_with_no_sub_agents(self) -> None:
        """``_cleanup_sub_agent_state`` is a no-op when no sub-agents were spawned."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)

            await app._cleanup_sub_agent_state()
            await _settle(app=app, pilot=pilot)


class _BlockingModal(ModalScreen[None]):
    """Any modal above the base screen; focus must not move behind it."""


class TestSessionListFocusReturn:
    """An emptied list returns focus to the prompt only from the focused base list."""

    @pytest.mark.asyncio
    async def test_emptied_focused_list_returns_focus_to_prompt(self) -> None:
        """Hiding the focused list on the base screen focuses the prompt editor."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = await _install_service(app=app)
            supplier.publish()
            await _refresh(app=app, pilot=pilot)
            assert app._fleet_panel is not None
            app._fleet_panel.focus_sessions()
            await _settle(app=app, pilot=pilot)

            await app._apply_session_snapshot(snapshot=WorkflowSessionSnapshotDAO())
            await _settle(app=app, pilot=pilot)

            assert app.focused is app._input

    @pytest.mark.asyncio
    async def test_emptied_unfocused_list_leaves_focus_alone(self) -> None:
        """When the list did not hold focus, emptying it moves no focus."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await _refresh(app=app, pilot=pilot)
            app.set_focus(None)
            await _settle(app=app, pilot=pilot)

            await app._apply_session_snapshot(snapshot=WorkflowSessionSnapshotDAO())
            await _settle(app=app, pilot=pilot)

            assert app.focused is None

    @pytest.mark.asyncio
    async def test_emptied_list_behind_modal_does_not_take_focus(self) -> None:
        """With a modal open, emptying the focused base list leaves the prompt unfocused."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await _refresh(app=app, pilot=pilot)
            assert app._fleet_panel is not None
            app._fleet_panel.focus_sessions()
            await _settle(app=app, pilot=pilot)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await _settle(app=app, pilot=pilot)

            await app._apply_session_snapshot(snapshot=WorkflowSessionSnapshotDAO())
            await _settle(app=app, pilot=pilot)

            assert app.screen is modal
            assert app._input is not None
            assert not app._input.has_focus

    @pytest.mark.asyncio
    async def test_prompt_end_cleanup_keeps_focused_list(self) -> None:
        """Prompt-end cleanup leaves the focused base list visible and focused."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await _refresh(app=app, pilot=pilot)
            assert app._fleet_panel is not None
            app._fleet_panel.focus_sessions()
            await _settle(app=app, pilot=pilot)

            await app._cleanup_sub_agent_state()
            await _settle(app=app, pilot=pilot)

            assert app._fleet_panel.display is True
            assert app.focused is not None and app._fleet_panel in app.focused.ancestors_with_self

    @pytest.mark.asyncio
    async def test_prompt_end_cleanup_of_unfocused_list_leaves_focus_alone(self) -> None:
        """Prompt-end cleanup of a list that did not hold focus moves no focus."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await _refresh(app=app, pilot=pilot)
            app.set_focus(None)
            await _settle(app=app, pilot=pilot)

            await app._cleanup_sub_agent_state()
            await _settle(app=app, pilot=pilot)

            assert app.focused is None

    @pytest.mark.asyncio
    async def test_prompt_end_cleanup_behind_modal_does_not_take_focus(self) -> None:
        """With a modal open, prompt-end cleanup of the focused base list leaves the prompt unfocused."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            (await _install_service(app=app)).publish()
            await _refresh(app=app, pilot=pilot)
            assert app._fleet_panel is not None
            app._fleet_panel.focus_sessions()
            await _settle(app=app, pilot=pilot)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await _settle(app=app, pilot=pilot)

            await app._cleanup_sub_agent_state()
            await _settle(app=app, pilot=pilot)

            assert app.screen is modal
            assert app._input is not None
            assert not app._input.has_focus

    @pytest.mark.asyncio
    async def test_new_session_with_focused_list_returns_focus_to_prompt(self) -> None:
        """``/new`` hides the focused base list of the old owner and focuses the prompt editor."""
        old_session: SloAgentSession = _build_session()
        new_session: SloAgentSession = _build_session()
        supplier: _AttachedSupplier = _AttachedSupplier()
        supplier.publish(session_id="old-child")

        with patch.object(old_session, "attached_dispatch_snapshot", new=supplier):
            app: SloTUI = SloTUI(session=old_session)
            async with app.run_test(size=(120, 40)) as pilot:
                await _settle(app=app, pilot=pilot)
                await app._render_event(_spawned(task_id="task-A", session_id="old-child"))
                await _settle(app=app, pilot=pilot)
                assert app._fleet_panel is not None
                app._fleet_panel.focus_sessions()
                await _settle(app=app, pilot=pilot)

                with patch("src.tui.app.SloAgentSession.build", return_value=new_session):
                    await app._start_new_session(requested_name=None)
                await _settle(app=app, pilot=pilot)

                assert (app._fleet_panel.display, app.focused) == (False, app._input)


class TestHistoryGatedLaunchEffects:
    """Launch-result effects stay history-gated while the list observes every session (a.2)."""

    @pytest.mark.asyncio
    async def test_session_without_history_ignores_launch_result_but_lists_children(self) -> None:
        """A valid ``launch_workflow`` result opens nothing and seeds no exit hint without history."""
        session: SloAgentSession = _build_session()
        supplier: _AttachedSupplier = _AttachedSupplier()
        supplier.publish(session_id="child-1")
        launch_result: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1", "state": "launching"}',
        )
        hint_before: str = f"Resume this session: slo --resume {session.session_id}"

        with (
            patch.object(session, "attached_dispatch_snapshot", new=supplier),
            patch(
                "src.tui.workflows.renderer.DetachedWorkflowRenderer.handle_launch_result"
            ) as renderer_launch,
        ):
            app: SloTUI = SloTUI(session=session)
            async with app.run_test(size=(120, 40)) as pilot:
                await _settle(app=app, pilot=pilot)
                await app._render_event(launch_result)
                await app._render_event(_spawned(task_id="task-A", session_id="child-1"))
                await _settle(app=app, pilot=pilot)

                renderer_launch.assert_not_called()
                assert app._live_workflow_labels() == []
                assert app._resume_command_hint() == hint_before
                assert _painted_rows(app=app) == {session.session_id: "running", "child-1": "running"}

    @pytest.mark.asyncio
    async def test_session_without_history_hides_live_labels_from_exit_hint(self) -> None:
        """Even a seeded live-state cache never reaches the exit hint of a session without history."""
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            assert app._workflow_app_service is not None
            outcome: str = app._workflow_app_service.advance_from_launch_result(
                result_text='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1", "state": "running"}'
            )

            assert outcome != "ignored"
            assert app._live_workflow_labels() == []
            assert app._resume_command_hint() == f"Resume this session: slo --resume {session.session_id}"


# ---------------------------------------------------------------------------
# TestVisualizerAutoLaunch
# ---------------------------------------------------------------------------


class TestVisualizerAutoLaunch:
    """``_maybe_launch_visualizer`` opens the visualizer once per run."""

    @pytest.mark.asyncio
    async def test_first_spawn_launches_visualizer_once(self) -> None:
        """The visualizer launches on the first spawn only, not on the second."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await app._render_event(_spawned(task_id="task-B", session_id="s2"))
                await _settle(app=app, pilot=pilot)

            mock_launch.assert_called_once()
            assert app._visualizer_launched_for_run is True

    @pytest.mark.asyncio
    async def test_launch_passes_parent_session_id(self) -> None:
        """The launcher receives the orchestrator (parent) session id."""
        session = _build_session()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await _settle(app=app, pilot=pilot)

            _, kwargs = mock_launch.call_args
            assert kwargs["parent_session_id"] == session.session_id

    @pytest.mark.asyncio
    async def test_success_writes_open_notice(self) -> None:
        """A successful launch writes an 'Opened workflow visualizer' notice."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ):
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await _settle(app=app, pilot=pilot)

            assert app.query_one(ChatTranscript)._adapter is not None
            lines = [content for content, _ in app.query_one(ChatTranscript)._adapter.lines]
            assert any("Opened workflow visualizer" in line for line in lines)

    @pytest.mark.asyncio
    async def test_failure_writes_manual_hint(self) -> None:
        """A failed launch writes the manual ``slo visualize`` hint instead."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=False),
            ):
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await _settle(app=app, pilot=pilot)

            assert app.query_one(ChatTranscript)._adapter is not None
            lines = [content for content, _ in app.query_one(ChatTranscript)._adapter.lines]
            assert any("slo visualize --session" in line for line in lines)

    @pytest.mark.asyncio
    async def test_cleanup_resets_launch_guard(self) -> None:
        """After run cleanup the guard resets so the next run relaunches."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await _settle(app=app, pilot=pilot)
                assert app._visualizer_launched_for_run is True

                await app._cleanup_sub_agent_state()
                assert app._visualizer_launched_for_run is False

                await app._render_event(_spawned(task_id="task-B", session_id="s2"))
                await _settle(app=app, pilot=pilot)
                assert mock_launch.call_count == 2
