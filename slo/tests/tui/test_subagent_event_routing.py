"""Tests for sub-agent event routing and fleet panel (28.t.1, simplified design).

The orchestrator transcript is always in the foreground; there are no
sub-agent panes and no pane-switching. These tests verify:
- Lifecycle events write notices to the main transcript.
- Content events update the fleet panel's live-activity field only.
- The orchestrator projector never receives sub-agent events.
- The fleet panel resets cleanly at run end.
- Tool-call activity text is formatted and shown in the fleet row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock

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
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await pilot.pause()

        assert app._adapter is not None
        lines = [content for content, _ in app._adapter.lines]
        assert any("task-A" in line and "spawned" in line for line in lines)
        assert any("⊇" in line for line in lines)

    @pytest.mark.asyncio
    async def test_spawned_does_not_reach_orchestrator_projector(self) -> None:
        """The orchestrator projector is NOT called for a sub-agent spawned event."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch.object(app._projector, "project", new_callable=AsyncMock) as mock_proj:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await pilot.pause()

            mock_proj.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawned_makes_fleet_panel_visible(self) -> None:
        """After ``sub_agent_spawned``, fleet panel is visible."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app._fleet_panel is not None
            assert app._fleet_panel.display is False

            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await pilot.pause()

            assert app._fleet_panel.display is True

    @pytest.mark.asyncio
    async def test_spawned_registers_fleet_row(self) -> None:
        """After ``sub_agent_spawned``, the fleet panel has a row for the task."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-B", session_id="s2"))
            await pilot.pause()

            assert app._fleet_panel is not None
            assert "s2" in app._fleet_panel._rows

    @pytest.mark.asyncio
    async def test_text_delta_does_not_appear_in_main_transcript(self) -> None:
        """A sub-agent ``text_delta`` does NOT add any entry to the adapter."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            lines_before = len(app._adapter.lines) if app._adapter else 0
            await app._render_event(_text_delta(task_id="task-A", session_id="s1", delta="work"))
            await pilot.pause()

            lines_after = len(app._adapter.lines) if app._adapter else 0
            assert lines_after == lines_before

    @pytest.mark.asyncio
    async def test_text_delta_updates_fleet_panel_last_text(self) -> None:
        """A sub-agent ``text_delta`` updates the fleet panel's last_text."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_text_delta(task_id="task-A", session_id="s1", delta="analyzing files"))
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.last_text == "analyzing files"

    @pytest.mark.asyncio
    async def test_child_thinking_delta_updates_fleet_activity_and_never_mounts_a_foreground_thinking_block(
        self,
    ) -> None:
        """A child ``thinking_delta`` is fleet activity only — no foreground thinking widget."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(
                _thinking_delta(task_id="task-A", session_id="s1", delta="child reasoning")
            )
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.last_text == "child reasoning"
            assert list(app.query(selector=AssistantStreamThinkingBlock)) == []

    @pytest.mark.asyncio
    async def test_tool_call_end_updates_fleet_last_text(self) -> None:
        """A sub-agent ``tool_call_end`` updates the fleet panel's last_text."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(
                _tool_call_end(
                    task_id="task-A",
                    session_id="s1",
                    tool_name="bash",
                    tool_input={"command": "pytest -x"},
                )
            )
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.last_text is not None
            assert "bash" in row.last_text
            assert "pytest" in row.last_text

    @pytest.mark.asyncio
    async def test_tool_result_updates_fleet_last_text(self) -> None:
        """A sub-agent ``tool_result`` updates the fleet panel's last_text."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_tool_result(task_id="task-A", session_id="s1"))
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.last_text is not None
            assert "bash" in row.last_text

    @pytest.mark.asyncio
    async def test_orchestrator_event_bypasses_fleet_panel(self) -> None:
        """An event with ``sub_agent_id=None`` does not touch the fleet panel."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            rows_before: int = len(app._fleet_panel._rows) if app._fleet_panel else 0
            await app._render_event(_orchestrator_text_delta())
            await pilot.pause()

            rows_after: int = len(app._fleet_panel._rows) if app._fleet_panel else 0
            assert rows_after == rows_before

    @pytest.mark.asyncio
    async def test_completed_writes_notice_to_main_transcript(self) -> None:
        """``sub_agent_completed`` writes ``⊇ task-A: completed`` to the adapter."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_completed(task_id="task-A", session_id="s1"))
            await pilot.pause()

        assert app._adapter is not None
        lines = [content for content, _ in app._adapter.lines]
        assert any("task-A" in line and "completed" in line for line in lines)

    @pytest.mark.asyncio
    async def test_completed_marks_fleet_row_terminal(self) -> None:
        """``sub_agent_completed`` transitions the fleet row to ``completed``."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_completed(task_id="task-A", session_id="s1"))
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.status == "completed"

    @pytest.mark.asyncio
    async def test_failed_marks_fleet_row_terminal(self) -> None:
        """``sub_agent_failed`` transitions the fleet row to ``failed``."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await app._render_event(_failed(task_id="task-A", session_id="s1"))
            await pilot.pause()

            assert app._fleet_panel is not None
            row = app._fleet_panel._rows.get("s1")
            assert row is not None
            assert row.status == "failed"

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
    async def test_fleet_panel_reset_on_run_end(self) -> None:
        """``_cleanup_sub_agent_state`` hides and clears the fleet panel."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app._render_event(_spawned(task_id="task-A", session_id="s1"))
            await pilot.pause()

            assert app._fleet_panel is not None
            assert app._fleet_panel.display is True

            await app._cleanup_sub_agent_state()
            await pilot.pause()

            assert app._fleet_panel is not None
            assert app._fleet_panel.display is False
            assert len(app._fleet_panel._rows) == 0

    @pytest.mark.asyncio
    async def test_cleanup_is_safe_with_no_sub_agents(self) -> None:
        """``_cleanup_sub_agent_state`` is a no-op when no sub-agents were spawned."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            await app._cleanup_sub_agent_state()
            await pilot.pause()


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
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await app._render_event(_spawned(task_id="task-B", session_id="s2"))
                await pilot.pause()

            mock_launch.assert_called_once()
            assert app._visualizer_launched_for_run is True

    @pytest.mark.asyncio
    async def test_launch_passes_parent_session_id(self) -> None:
        """The launcher receives the orchestrator (parent) session id."""
        session = _build_session()
        app: SloTUI = SloTUI(session=session)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await pilot.pause()

            _, kwargs = mock_launch.call_args
            assert kwargs["parent_session_id"] == session.session_id

    @pytest.mark.asyncio
    async def test_success_writes_open_notice(self) -> None:
        """A successful launch writes an 'Opened workflow visualizer' notice."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ):
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await pilot.pause()

            assert app._adapter is not None
            lines = [content for content, _ in app._adapter.lines]
            assert any("Opened workflow visualizer" in line for line in lines)

    @pytest.mark.asyncio
    async def test_failure_writes_manual_hint(self) -> None:
        """A failed launch writes the manual ``slo visualize`` hint instead."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=False),
            ):
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await pilot.pause()

            assert app._adapter is not None
            lines = [content for content, _ in app._adapter.lines]
            assert any("slo visualize --session" in line for line in lines)

    @pytest.mark.asyncio
    async def test_cleanup_resets_launch_guard(self) -> None:
        """After run cleanup the guard resets so the next run relaunches."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                new=MagicMock(return_value=True),
            ) as mock_launch:
                await app._render_event(_spawned(task_id="task-A", session_id="s1"))
                await pilot.pause()
                assert app._visualizer_launched_for_run is True

                await app._cleanup_sub_agent_state()
                assert app._visualizer_launched_for_run is False

                await app._render_event(_spawned(task_id="task-B", session_id="s2"))
                await pilot.pause()
                assert mock_launch.call_count == 2


# ---------------------------------------------------------------------------
# TestSubAgentActivityText
# ---------------------------------------------------------------------------


class TestSubAgentActivityText:
    """``SloTUI._sub_agent_activity_text`` formats content events for fleet rows."""

    def test_text_delta_returns_delta(self) -> None:
        """``text_delta`` returns the delta string."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="text_delta",
            sub_agent_id="s1",
            task_id="t1",
            delta="thinking about it",
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result == "thinking about it"

    def test_thinking_delta_returns_delta(self) -> None:
        """``thinking_delta`` returns the delta string."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="thinking_delta",
            sub_agent_id="s1",
            task_id="t1",
            delta="reasoning step",
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result == "reasoning step"

    def test_tool_call_end_includes_tool_name_and_arg(self) -> None:
        """``tool_call_end`` formats as ``tool_name: first_arg``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_call_end",
            sub_agent_id="s1",
            task_id="t1",
            tool_name="bash",
            tool_call_id="tc1",
            tool_input={"command": "pytest -x"},
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result is not None
        assert "bash" in result
        assert "pytest" in result

    def test_tool_call_end_no_input_returns_tool_name(self) -> None:
        """``tool_call_end`` with no input returns just the tool name."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_call_end",
            sub_agent_id="s1",
            task_id="t1",
            tool_name="now",
            tool_call_id="tc1",
            tool_input=None,
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result == "now"

    def test_tool_result_includes_checkmark_and_tool_name(self) -> None:
        """``tool_result`` returns ``✓ tool_name``."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            sub_agent_id="s1",
            task_id="t1",
            tool_name="read",
            tool_call_id="tc1",
            content="file contents",
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result is not None
        assert "✓" in result
        assert "read" in result

    def test_lifecycle_event_returns_none(self) -> None:
        """Lifecycle event kinds return ``None`` (no activity text)."""
        for kind in ("sub_agent_spawned", "sub_agent_completed", "sub_agent_failed"):
            event: AgentStreamEventDAO = AgentStreamEventDAO(
                kind=kind,  # type: ignore[arg-type]
                sub_agent_id="s1",
                task_id="t1",
            )
            result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
            assert result is None, f"expected None for {kind}, got {result!r}"

    def test_run_completed_returns_none(self) -> None:
        """``run_completed`` returns ``None`` — not a fleet-row activity event."""
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="run_completed",
            sub_agent_id="s1",
            task_id="t1",
            content="final answer",
        )
        result: Optional[str] = SloTUI._sub_agent_activity_text(event=event)
        assert result is None
