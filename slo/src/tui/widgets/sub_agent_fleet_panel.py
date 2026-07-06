"""Concurrent sub-agent fleet-status panel for the Slo TUI.

Mounted below ``PromptInput`` and above ``UsageStatusBar`` for the duration
of any run that spawns sub-agents. Shows one compact, live-updating row per
active sub-agent. Rows are read-only status displays — there is no pane
switching; the orchestrator transcript is always in the foreground.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from textual.containers import Vertical
from textual.widgets import Static

from src.agents.slo_agent.orchestrator.dao import SubAgentStatus

__all__ = ["SubAgentFleetRowDAO", "SubAgentFleetRow", "SubAgentFleetPanel"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_ICONS: dict[str, str] = {
    "pending": "○",
    "running": "⏳",
    "completed": "✓",
    "failed": "✗",
    "aborted": "✗",
}

_GLYPH: str = "⊇"
"""U+2287 — sub-agent marker, consistent with transcript notices."""

_LAST_TEXT_MAX_CHARS: int = 72
"""Maximum visible characters of the live-activity field per row."""


# ---------------------------------------------------------------------------
# DAO
# ---------------------------------------------------------------------------


class SubAgentFleetRowDAO(BaseModel):
    """Transient render state for one sub-agent row in the fleet panel.

    Owned exclusively by ``SubAgentFleetPanel``. Not persisted to disk.

    Attributes:
        task_id (str): Human-readable task label shown on the row.
        session_id (str): Child session UUID; the internal row key.
        status (SubAgentStatus): Current lifecycle state.
        last_text (Optional[str]): Most recent visible activity from the child.
            Updated on ``text_delta``, ``thinking_delta``, ``tool_call_end``,
            and ``tool_result`` events so the row always reflects the latest
            thing the sub-agent is doing.
        started_at (float): ``time.monotonic()`` at registration; drives the
            elapsed-seconds column.
        prompt_preview (str): First 40 chars of the task prompt; shown as
            fallback activity text before the first content event arrives.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    status: SubAgentStatus = "running"
    last_text: Optional[str] = None
    started_at: float = Field(default_factory=time.monotonic)
    prompt_preview: str = ""


# ---------------------------------------------------------------------------
# SubAgentFleetRow — one status row widget
# ---------------------------------------------------------------------------


class SubAgentFleetRow(Static):
    """One read-only status row in the fleet panel representing one sub-agent.

    Renders live markup via ``_format()`` and refreshes on every DAO change
    or timer tick. There is no click handler — the orchestrator transcript is
    always the foreground; this row is informational only.
    """

    DEFAULT_CSS = """
    SubAgentFleetRow {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, *, dao: SubAgentFleetRowDAO) -> None:
        """Bind the row to its DAO and render the initial markup.

        ``Static.update()`` is safe in ``__init__``; deferring to ``on_mount``
        causes a one-frame blank flash on first paint.

        Args:
            dao (SubAgentFleetRowDAO): Initial row state.
        """
        super().__init__()
        self._dao: SubAgentFleetRowDAO = dao
        self.update(self._format(dao=self._dao))

    def refresh_from_dao(self, *, dao: SubAgentFleetRowDAO) -> None:
        """Recompute and apply the row markup from updated DAO state.

        Called by ``SubAgentFleetPanel._refresh_row`` whenever the DAO changes
        and by ``_refresh_all_rows`` on the per-second timer tick.

        Args:
            dao (SubAgentFleetRowDAO): Updated row state.
        """
        self._dao = dao
        self.update(self._format(dao=dao))

    @staticmethod
    def _format(*, dao: SubAgentFleetRowDAO) -> str:
        """Render the Rich markup string for this row.

        Row format::

            ⊇ [bold]task-deps[/bold]  ⏳  4s   bash: find . -name "*.py"…

        Running rows show the task label in bold; terminal rows dim it so
        the user can tell at a glance which agents are still active.

        Args:
            dao (SubAgentFleetRowDAO): Current row state.

        Returns:
            str: Rich markup string for one row.
        """
        icon: str = _STATUS_ICONS.get(dao.status, "○")
        elapsed: int = int(time.monotonic() - dao.started_at)
        activity: str = dao.last_text or dao.prompt_preview or "…"
        if len(activity) > _LAST_TEXT_MAX_CHARS:
            activity = f"{activity[:_LAST_TEXT_MAX_CHARS]}…"
        label: str = (
            f"[bold]{dao.task_id}[/bold]"
            if dao.status in ("pending", "running")
            else f"[dim]{dao.task_id}[/dim]"
        )
        return f"{_GLYPH} {label}  {icon}  [dim]{elapsed}s[/dim]   {activity}"


# ---------------------------------------------------------------------------
# SubAgentFleetPanel — the fleet container
# ---------------------------------------------------------------------------


class SubAgentFleetPanel(Vertical):
    """Live fleet-status panel mounted below PromptInput while sub-agents run.

    Displays one ``SubAgentFleetRow`` per active sub-agent. The panel is
    yielded in ``SloTUI.compose()`` with ``display = False`` and becomes
    visible on the first ``register_row`` call. Rows update in place from
    a per-second timer and from streaming content events, so the user always
    sees what each sub-agent is currently doing.

    The panel is purely informational — there is no pane-switching; the
    orchestrator transcript stays in the foreground at all times.
    """

    DEFAULT_CSS = """
    SubAgentFleetPanel {
        height: auto;
        max-height: 10;
        border-top: solid $surface;
        padding: 0 0;
    }
    """

    def __init__(self) -> None:
        """Construct an empty fleet panel, initially hidden."""
        super().__init__()
        self._rows: dict[str, SubAgentFleetRowDAO] = {}
        self._row_widgets: dict[str, SubAgentFleetRow] = {}
        self.display = False

    def on_mount(self) -> None:
        """Start the per-second timer that advances elapsed-time counters.

        Textual's ``invoke()`` handles both sync and async callbacks; a sync
        callback returning ``None`` is invoked directly without blocking the
        event loop.
        """
        self.set_interval(interval=1.0, callback=self._refresh_all_rows)

    async def register_row(
        self,
        *,
        session_id: str,
        task_id: str,
        prompt_preview: str,
    ) -> None:
        """Add a new sub-agent row and make the panel visible.

        Called by ``SloTUI._route_sub_agent_event`` on ``sub_agent_spawned``.
        Idempotent: a no-op when ``session_id`` is already registered.

        Args:
            session_id (str): Child session UUID; internal row key.
            task_id (str): Human-readable label shown on the row.
            prompt_preview (str): First 40 chars of the task prompt; used as
                fallback activity text until the first content event arrives.
        """
        if session_id in self._rows:
            return
        dao: SubAgentFleetRowDAO = SubAgentFleetRowDAO(
            task_id=task_id,
            session_id=session_id,
            status="running",
            prompt_preview=prompt_preview[:40],
        )
        self._rows[session_id] = dao
        row_widget: SubAgentFleetRow = SubAgentFleetRow(dao=dao)
        self._row_widgets[session_id] = row_widget
        await self.mount(row_widget)
        self.display = True

    def update_last_text(self, *, session_id: str, text: str) -> None:
        """Update the live-activity field for a running row.

        Called on ``text_delta``, ``thinking_delta``, ``tool_call_end``, and
        ``tool_result`` events so the row reflects the latest work the child
        agent is performing. A no-op when the session is not registered or the
        row has already reached a terminal status.

        Args:
            session_id (str): Child session to update.
            text (str): Latest activity string for the row.
        """
        dao: Optional[SubAgentFleetRowDAO] = self._rows.get(session_id)
        if dao is None or dao.status not in ("pending", "running"):
            return
        updated: SubAgentFleetRowDAO = dao.model_copy(update={"last_text": text})
        self._rows[session_id] = updated
        self._refresh_row(session_id=session_id, dao=updated)

    def mark_terminal(self, *, session_id: str, status: SubAgentStatus) -> None:
        """Transition a row to a terminal status.

        Called by ``SloTUI._route_sub_agent_event`` on ``sub_agent_completed``
        or ``sub_agent_failed``. Terminal rows remain visible in the panel
        until the whole panel is reset at run end.

        Args:
            session_id (str): Child session to transition.
            status (SubAgentStatus): Terminal status value.
        """
        dao: Optional[SubAgentFleetRowDAO] = self._rows.get(session_id)
        if dao is None:
            return
        updated: SubAgentFleetRowDAO = dao.model_copy(update={"status": status})
        self._rows[session_id] = updated
        self._refresh_row(session_id=session_id, dao=updated)

    async def reset(self) -> None:
        """Clear all rows and hide the panel for the next run.

        Called by ``SloTUI._cleanup_sub_agent_state`` at run end. Uses
        ``asyncio.gather`` to remove all row widgets concurrently rather than
        serially — row removals are independent of each other.
        """
        if self._row_widgets:
            await asyncio.gather(*(w.remove() for w in self._row_widgets.values()))
        self._rows.clear()
        self._row_widgets.clear()
        self.display = False

    def _refresh_row(self, *, session_id: str, dao: SubAgentFleetRowDAO) -> None:
        """Re-render one row widget from its current DAO state.

        Args:
            session_id (str): Row key.
            dao (SubAgentFleetRowDAO): Current DAO state for this row.
        """
        widget: Optional[SubAgentFleetRow] = self._row_widgets.get(session_id)
        if widget is None:
            return
        widget.refresh_from_dao(dao=dao)

    def _refresh_all_rows(self) -> None:
        """Advance elapsed-time counters on every row.

        Called by the per-second timer. Only updates rendered text content —
        no CSS class mutations — so each tick is O(N) string formatting
        operations only, with no layout invalidation.
        """
        for session_id, dao in self._rows.items():
            widget: Optional[SubAgentFleetRow] = self._row_widgets.get(session_id)
            if widget is not None:
                widget.update(SubAgentFleetRow._format(dao=dao))
