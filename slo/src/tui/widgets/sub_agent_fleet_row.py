"""One literal row of the workflow session list (feature 94 a.2).

``SubAgentFleetRow`` is a native ``ListItem`` holding separate status glyph,
status word, session, and task cells. The status word (``running``,
``completed``…) is always shown so lifecycle never depends on colour alone. The stored ``WorkflowSessionRowDAO``, never the rendered text,
supplies identity, so visual clipping cannot change the selected session. The
row has no execution authority; it restyles the existing session/task data only.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import ListItem, Static

from src.agents.slo_agent.orchestrator.task_preview import TASK_SUMMARY_FALLBACK
from src.tui.workflows.dao import WorkflowSessionRowDAO

__all__ = ["SubAgentFleetRow"]

ORCHESTRATOR_LABEL: str = "Orchestrator"
"""Exact label of the parent row; its task text is never shown in the list."""


class SubAgentFleetRow(ListItem):
    """Present one immutable workflow row without interpreting its authority."""

    def __init__(self, *, row: WorkflowSessionRowDAO) -> None:
        """Bind a snapshot row when the panel creates a list item.

        WHO: ``SubAgentFleetPanel`` when a snapshot changes the row keys.
        WHEN: Before the row is mounted; ``on_mount`` paints it.

        Args:
            row (WorkflowSessionRowDAO): Display-only identity and task data.
        """
        super().__init__()
        self.row: WorkflowSessionRowDAO = row
        self._status_glyph: Static = Static(markup=False, classes="fleet-row-status")
        self._status_word: Static = Static(markup=False, classes="fleet-row-status-word")
        self._session_id: Static = Static(markup=False, classes="fleet-row-session fleet-row-meta")
        self._task_label: Static = Static(markup=False, classes="fleet-row-task fleet-row-label")
        self._row_content: Horizontal = Horizontal(
            self._status_glyph,
            self._status_word,
            self._session_id,
            self._task_label,
            classes="fleet-row-content",
        )

    def compose(self) -> ComposeResult:
        """Yield the row's status, identity and task cells in one line."""
        yield self._row_content

    def on_mount(self) -> None:
        """Paint the initial row after its label is mounted."""
        self.apply_row(row=self.row)

    def apply_row(self, *, row: WorkflowSessionRowDAO) -> None:
        """Update label data during a panel refresh without replacing the widget.

        WHO: ``SubAgentFleetPanel`` for a same-key snapshot, and ``on_mount``.
        WHEN: On every snapshot whose key order is unchanged.

        Args:
            row (WorkflowSessionRowDAO): Same-key replacement snapshot row.
        """
        self.row = row
        self._status_glyph.update(content=self._status_glyph_for_row(row=row))
        self._status_word.update(content=row.status)
        self._session_id.update(content=row.key.session_id + ": ")
        self._task_label.update(content=self._task_label_for_row(row=row))
        self._apply_status_color(row=row)

    @staticmethod
    def _task_label_for_row(*, row: WorkflowSessionRowDAO) -> str:
        """Choose the parent label or the safe capped task preview.

        Args:
            row (WorkflowSessionRowDAO): Row being painted.

        Returns:
            str: ``Orchestrator`` for the parent, else the TaskPreview label or
                the fixed fallback when nothing displayable remains.
        """
        if row.role == "orchestrator":
            return ORCHESTRATOR_LABEL + (" [retained batch]" if row.retained_batch else "")
        return row.task_summary or TASK_SUMMARY_FALLBACK

    @staticmethod
    def _status_glyph_for_row(*, row: WorkflowSessionRowDAO) -> str:
        """Return the mock's compact glyph without changing lifecycle data."""
        if row.status == "running":
            return "◍"
        if row.status == "completed":
            return "●"
        if row.status in {"failed", "aborted"}:
            return "✕"
        return "·"

    def _apply_status_color(self, *, row: WorkflowSessionRowDAO) -> None:
        """Select a CSS status class; only the glyph receives its semantic color."""
        for status_class in ("-running", "-completed", "-failed", "-aborted", "-idle"):
            self.remove_class(status_class)
        status_class: str = {
            "running": "-running",
            "completed": "-completed",
            "failed": "-failed",
            "aborted": "-aborted",
        }.get(row.status, "-idle")
        self.add_class(status_class)
