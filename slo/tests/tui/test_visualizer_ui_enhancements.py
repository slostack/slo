"""Tests for HeadlessWorkflowVisualizer UI enhancements.

Covers keyboard-resizable panes, the workflow-summary tally, coloured
sub-agent labels, and the markdown-aware rich transcript writer.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.markdown import Markdown

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.headless_workflow_visualizer import (
    HeadlessWorkflowVisualizer,
    _CHILD_PANEL_WIDTH_MAX,
    _CHILD_PANEL_WIDTH_MIN,
    _DIAG_HEIGHT_MAX,
    _DIAG_HEIGHT_MIN,
)
from src.tui.workflows.dao import SessionProgressSnapshotDAO, WorkflowSessionRowDAO
from src.tui.workflows.transcript_renderer import WorkflowTranscriptRenderer
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    HeadlessWorkflowVisualizerConfigDAO,
    WorkflowDataDAO,
)


def _config() -> HeadlessWorkflowVisualizerConfigDAO:
    """Build a non-following visualizer config for tests.

    Returns:
        HeadlessWorkflowVisualizerConfigDAO: Config with follow disabled.
    """
    return HeadlessWorkflowVisualizerConfigDAO(session_reference="x", follow=False)


async def _empty_progress(*, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
    """Return an empty progress snapshot for any requested row."""
    return SessionProgressSnapshotDAO(
        key=row.key,
        execution_id=row.execution_id,
        revision="",
        source_generation="",
        availability="empty",
        observed_at="2026-10-18T00:00:00+00:00",
        task_text=row.task_text,
        task_text_complete=row.task_text_complete,
        status=row.status,
    )


def _loader_for(*, data: WorkflowDataDAO) -> MagicMock:
    """Build a mock loader returning ``data`` from ``load()``.

    Args:
        data (WorkflowDataDAO): Workflow data to return.

    Returns:
        MagicMock: Configured mock loader.
    """
    loader = MagicMock()
    loader.load = AsyncMock(return_value=data)
    loader.load_orchestrator_context = MagicMock(return_value=None)
    loader.load_session_progress = AsyncMock(side_effect=_empty_progress)
    loader.load_child_stderr_lines = MagicMock(return_value=[])
    loader.load_spawn_context = MagicMock(return_value=None)
    return loader


class _FakeLog:
    """Minimal RichLog stand-in that records everything written to it."""

    def __init__(self) -> None:
        """Initialise the capture buffer."""
        self.writes: list[Any] = []

    def write(self, renderable: Any, *, scroll_end: Optional[bool] = None) -> None:  # noqa: ANN401
        """Record a written renderable.

        Args:
            renderable (Any): The value written.
            scroll_end (Optional[bool], optional): RichLog scroll flag. Defaults to None.
        """
        self.writes.append(renderable)


# ---------------------------------------------------------------------------
# _status_counts
# ---------------------------------------------------------------------------


class TestStatusCounts:
    """The summary tally counts children by status."""

    def test_counts_each_status(self) -> None:
        """Mixed statuses are tallied into their buckets."""
        data = WorkflowDataDAO(
            parent_session_id="p",
            children=[
                ChildSessionSummaryDAO(session_id="a", status="running"),
                ChildSessionSummaryDAO(session_id="b", status="completed"),
                ChildSessionSummaryDAO(session_id="c", status="completed"),
                ChildSessionSummaryDAO(session_id="d", status="failed"),
                ChildSessionSummaryDAO(session_id="e", status="aborted"),
            ],
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=_loader_for(data=data))
        app._workflow_data = data

        counts = app._status_counts()

        assert counts["running"] == 1
        assert counts["completed"] == 2
        assert counts["failed"] == 1
        assert counts["aborted"] == 1

    def test_all_keys_present_when_no_data(self) -> None:
        """Every status bucket is present (zero) when no data is loaded."""
        app = HeadlessWorkflowVisualizer(
            config=_config(), loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p"))
        )

        counts = app._status_counts()

        assert counts == {
            "running": 0,
            "completed": 0,
            "failed": 0,
            "aborted": 0,
            "pending": 0,
        }


# ---------------------------------------------------------------------------
# _child_label colouring
# ---------------------------------------------------------------------------


class TestChildLabelColour:
    """Sub-agent labels are coloured by status."""

    def test_completed_label_is_green(self) -> None:
        """A completed child renders with the green status style."""
        summary = ChildSessionSummaryDAO(session_id="abc12345", status="completed")
        label = HeadlessWorkflowVisualizer._child_label(child=summary)
        assert label.style == "green"

    def test_failed_label_is_red(self) -> None:
        """A failed child renders with the red status style."""
        summary = ChildSessionSummaryDAO(session_id="abc12345", status="failed")
        label = HeadlessWorkflowVisualizer._child_label(child=summary)
        assert label.style == "red"


# ---------------------------------------------------------------------------
# WorkflowTranscriptRenderer.write_entry (shared since 94.a.3)
# ---------------------------------------------------------------------------


class TestWriteEntryRich:
    """The rich transcript writer renders answers as markdown."""

    def test_assistant_answer_rendered_as_markdown(self) -> None:
        """An assistant answer is written through rich.markdown.Markdown."""
        log = _FakeLog()
        entry = TranscriptEntryDAO(kind="assistant", answer="# Heading\n\nbody")

        WorkflowTranscriptRenderer.write_entry(log=log, entry=entry)  # type: ignore[arg-type]

        assert any(isinstance(w, Markdown) for w in log.writes)

    def test_user_message_rendered_as_markdown(self) -> None:
        """A user message body is written through Markdown."""
        log = _FakeLog()
        entry = TranscriptEntryDAO(kind="user", content="do **this**")

        WorkflowTranscriptRenderer.write_entry(log=log, entry=entry)  # type: ignore[arg-type]

        assert any(isinstance(w, Markdown) for w in log.writes)

    def test_thinking_entry_uses_shared_markdown(self) -> None:
        """Thinking uses the same source-preserving Markdown renderer as the modal."""
        log = _FakeLog()
        entry = TranscriptEntryDAO(kind="thinking", content="pondering")

        WorkflowTranscriptRenderer.write_entry(log=log, entry=entry)  # type: ignore[arg-type]

        bodies = [w for w in log.writes if isinstance(w, Markdown)]
        assert len(bodies) == 1
        assert bodies[0].markup == "pondering"


# ---------------------------------------------------------------------------
# Resize actions
# ---------------------------------------------------------------------------


class TestResizeActions:
    """Keyboard resize actions mutate and clamp the pane sizes."""

    @pytest.mark.asyncio
    async def test_widen_then_clamp_child_panel(self) -> None:
        """Widening repeatedly clamps at the max width."""
        app = HeadlessWorkflowVisualizer(
            config=_config(),
            loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p")),
        )
        async with app.run_test():
            for _ in range(40):
                app.action_widen_child_panel()
            assert app._child_panel_width == _CHILD_PANEL_WIDTH_MAX

    @pytest.mark.asyncio
    async def test_narrow_then_clamp_child_panel(self) -> None:
        """Narrowing repeatedly clamps at the min width."""
        app = HeadlessWorkflowVisualizer(
            config=_config(),
            loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p")),
        )
        async with app.run_test():
            for _ in range(40):
                app.action_narrow_child_panel()
            assert app._child_panel_width == _CHILD_PANEL_WIDTH_MIN

    @pytest.mark.asyncio
    async def test_grow_then_clamp_diagnostics(self) -> None:
        """Growing the diagnostics pane clamps at the max height."""
        app = HeadlessWorkflowVisualizer(
            config=_config(),
            loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p")),
        )
        async with app.run_test():
            for _ in range(40):
                app.action_grow_diagnostics()
            assert app._diag_height == _DIAG_HEIGHT_MAX

    @pytest.mark.asyncio
    async def test_shrink_then_clamp_diagnostics(self) -> None:
        """Shrinking the diagnostics pane clamps at the min height."""
        app = HeadlessWorkflowVisualizer(
            config=_config(),
            loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p")),
        )
        async with app.run_test():
            for _ in range(40):
                app.action_shrink_diagnostics()
            assert app._diag_height == _DIAG_HEIGHT_MIN

    @pytest.mark.asyncio
    async def test_resize_via_keybinding(self) -> None:
        """Pressing ctrl+right widens the panel above its default."""
        app = HeadlessWorkflowVisualizer(
            config=_config(),
            loader=_loader_for(data=WorkflowDataDAO(parent_session_id="p")),
        )
        async with app.run_test() as pilot:
            before = app._child_panel_width
            await pilot.press("ctrl+right")
            assert app._child_panel_width > before


# ---------------------------------------------------------------------------
# Summary bar
# ---------------------------------------------------------------------------


class TestSummaryBar:
    """The workflow-summary bar reflects the loaded data."""

    @pytest.mark.asyncio
    async def test_summary_shows_child_total(self) -> None:
        """The summary bar reports the number of sub-agents."""
        from textual.widgets import Label

        data = WorkflowDataDAO(
            parent_session_id="p",
            children=[
                ChildSessionSummaryDAO(session_id="a", status="running"),
                ChildSessionSummaryDAO(session_id="b", status="completed"),
            ],
            is_complete=False,
        )
        app = HeadlessWorkflowVisualizer(config=_config(), loader=_loader_for(data=data))
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.query_one("#workflow-summary", Label)
            rendered = str(summary.render())
            assert "2 sub-agents" in rendered
