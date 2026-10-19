"""One literal row of the workflow session list (feature 94 a.2).

``SubAgentFleetRow`` is a native ``ListItem`` holding one ``Static`` label. The
stored ``WorkflowSessionRowDAO``, never the rendered text, supplies identity, so
visual clipping cannot change which session a selection opens. The row has no
execution logic and no authority: it only paints ``[status] session_id: task``.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import ListItem, Static

from src.agents.slo_agent.orchestrator.task_preview import TaskPreview
from src.tui.workflows.dao import WorkflowSessionRowDAO

__all__ = ["SubAgentFleetRow"]

ORCHESTRATOR_LABEL: str = "Orchestrator"
"""Exact label of the parent row; its task text is never shown in the list."""

TASK_FALLBACK_LABEL: str = "Task details unavailable"
"""Label for a child whose task text has nothing displayable after normalization."""


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
        self._label: Static = Static(markup=False)

    def compose(self) -> ComposeResult:
        """Yield the literal label during Textual composition."""
        yield self._label

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
        self._label.update(content=f"[{row.status}] {row.key.session_id}: {self._task_label(row=row)}")

    @staticmethod
    def _task_label(*, row: WorkflowSessionRowDAO) -> str:
        """Choose the parent label or the safe capped task preview.

        Args:
            row (WorkflowSessionRowDAO): Row being painted.

        Returns:
            str: ``Orchestrator`` for the parent, else the TaskPreview label or
                the fixed fallback when nothing displayable remains.
        """
        if row.role == "orchestrator":
            return ORCHESTRATOR_LABEL
        return TaskPreview.build(task_text=row.task_text) or TASK_FALLBACK_LABEL
