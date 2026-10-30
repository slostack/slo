"""Navigable workflow session list below the Slo prompt (feature 94 a.2).

``SubAgentFleetPanel`` keeps its historical location and class identity: SloTUI
mounts exactly one below ``PromptInput`` and above ``UsageStatusBar``. It is a
presentation-only consumer of ``WorkflowSessionSnapshotDAO``: a heading and one
stable native ``ListView`` of ``SubAgentFleetRow`` items keyed by the composite
``(orchestrator_session_id, session_id)``. It never reads files, owns execution
status or runs a timer; the application supplies snapshots and receives the
``SessionSelected`` key on Enter or click.

Layout (heading plus at most five rows, 25% of the screen, one row on short
screens, a resize notice below 60x20) lives in ``src/tui/app.tcss``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import ListView, Static

from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.dao import (
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
)

__all__ = ["FleetSessionList", "SubAgentFleetPanel"]

_LOGGER = logging.getLogger(__name__)

SESSION_LIST_HEADING: str = "Ongoing workflow tasks"
"""Fixed heading painted above the rows."""

RESIZE_NOTICE: str = "Enlarge the terminal to 60x20 to browse workflow tasks"
"""Compact notice shown instead of the rows below the minimum interactive size."""


class FleetSessionList(ListView):
    """Expose user navigation generation without changing native list actions.

    Private to ``SubAgentFleetPanel``. Every local key, click and wheel event
    advances ``navigation_revision`` synchronously before native delegation, so a
    restoration queued by a structural refresh can tell that the user moved since.
    """

    def __init__(self) -> None:
        """Initialize the generation before the panel mounts the list."""
        super().__init__()
        self.navigation_revision: int = 0

    async def _on_key(self, event: events.Key) -> None:
        """Invalidate queued restoration before native keyboard navigation.

        Args:
            event (events.Key): Local key event from Textual.
        """
        self.navigation_revision += 1
        await super()._on_key(event)

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        """Invalidate restoration before native click selection.

        Args:
            event (events.MouseDown): Local mouse event.
        """
        self.navigation_revision += 1
        await super()._on_mouse_down(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Let native upward scrolling supersede a queued restoration.

        Args:
            event (events.MouseScrollUp): Native wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_up(event)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Let native downward scrolling supersede a queued restoration.

        Args:
            event (events.MouseScrollDown): Native wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_down(event)


class SubAgentFleetPanel(Vertical):
    """Display owner-scoped rows and emit selection; never read execution files.

    Invariants: the ``FleetSessionList`` stays mounted for the panel's lifetime;
    ``_rows`` mirrors the mounted items in display order with unique keys, even
    after a failed mount; at most one row application runs at a time, and a
    cancelled caller never interrupts it (shielded). A failure reaches only the
    caller that started it, so a later ``apply_snapshot`` or ``reset`` still runs
    and ``reset`` ends with the panel empty.
    """

    class SessionSelected(Message):
        """Request inspection of one exact composite key."""

        def __init__(self, *, key: WorkflowSessionKeyDAO) -> None:
            """Capture the row identity on native activation.

            Args:
                key (WorkflowSessionKeyDAO): Unclipped identity to inspect.
            """
            super().__init__()
            self.key: WorkflowSessionKeyDAO = key

    def __init__(self) -> None:
        """Create presentation state when SloTUI composes its single panel."""
        super().__init__()
        self._heading: Static = Static(
            content=SESSION_LIST_HEADING,
            markup=False,
            classes="workflow-sessions-heading",
        )
        self._resize_notice: Static = Static(
            content=RESIZE_NOTICE,
            markup=False,
            classes="workflow-sessions-resize-notice",
        )
        self._list: FleetSessionList = FleetSessionList()
        self._rows: list[SubAgentFleetRow] = []
        self._apply_lock: asyncio.Lock = asyncio.Lock()
        self._apply_task: Optional[asyncio.Task[None]] = None
        # Latest highlighted row, kept so user navigation during a structural
        # mount can be clamped onto the new rows.
        self._navigation_key: Optional[WorkflowSessionKeyDAO] = None
        self._navigation_index: int = 0
        self.display = False

    def compose(self) -> ComposeResult:
        """Yield the heading, the resize notice and the native focusable list."""
        yield self._heading
        yield self._resize_notice
        yield self._list

    async def apply_snapshot(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Apply one service result without stealing editor or modal focus.

        WHAT: Updates labels in place when the key order is unchanged; otherwise
            rebuilds the items and restores the selection by key. Hides the panel
            when the snapshot is empty. Never focuses anything.
        WHO: SloTUI whenever it holds a fresh session snapshot.
        WHEN: Serialized under the panel lock; an unfinished application left by
            a cancelled caller is joined first without inheriting its outcome.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Ordered authoritative view rows.
        """
        async with self._apply_lock:
            await self._join_unfinished_application()
            self._apply_task = asyncio.create_task(
                self._apply_rows(rows=self._unique_rows(snapshot=snapshot))
            )
            self._apply_task.add_done_callback(self._log_application_failure)
            await asyncio.shield(self._apply_task)

    async def _join_unfinished_application(self) -> None:
        """Wait for an application whose cancelled caller released the lock early.

        ``asyncio.wait`` neither cancels nor re-raises: a failure belongs to the
        caller that started that application, or to the failure log when that
        caller was cancelled, so a later caller never inherits a stale error.
        """
        if self._apply_task is not None and not self._apply_task.done():
            await asyncio.wait({self._apply_task})

    @staticmethod
    def _log_application_failure(task: asyncio.Task[None]) -> None:
        """Record a failed application, including one whose caller was cancelled.

        A cancelled shielded caller detaches from its task, so without this
        observer an orphaned failure would surface only as asyncio's "Task
        exception was never retrieved". The starting caller, when still
        waiting, also receives the exception through its own shielded await.

        Args:
            task (asyncio.Task[None]): Finished row application.
        """
        if task.cancelled() or task.exception() is None:
            return
        _LOGGER.warning("workflow_session_list_apply_failed", exc_info=task.exception())

    async def reset(self) -> None:
        """Discard presentation on owner replacement.

        WHO: SloTUI's workflow observation teardown (``/new`` adoption and
            unmount), never prompt completion.
        WHEN: After the old owner's coordinator, service and sink are closed; it
            joins any in-flight application through the lock.
        """
        await self.apply_snapshot(snapshot=WorkflowSessionSnapshotDAO())

    def focus_sessions(self) -> None:
        """Focus available rows only when the app explicitly requests navigation."""
        if self._rows:
            self._list.focus()

    @staticmethod
    def _unique_rows(*, snapshot: WorkflowSessionSnapshotDAO) -> tuple[WorkflowSessionRowDAO, ...]:
        """Keep the first row per key as a defense against a duplicating service.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Service result.

        Returns:
            tuple[WorkflowSessionRowDAO, ...]: Rows in order with unique keys.
        """
        rows_by_key: dict[WorkflowSessionKeyDAO, WorkflowSessionRowDAO] = {}
        for row in snapshot.rows:
            rows_by_key.setdefault(row.key, row)
        return tuple(rows_by_key.values())

    async def _apply_rows(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> None:
        """Keep widgets for an unchanged key order; called under the application lock.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): New unique rows in order.
        """
        if [row.key for row in rows] == [item.row.key for item in self._rows]:
            for item, row in zip(self._rows, rows):
                item.apply_row(row=row)
            return
        await self._replace_rows(rows=rows)

    async def _replace_rows(self, *, rows: tuple[WorkflowSessionRowDAO, ...]) -> None:
        """Rebuild the items and restore selection after a structural change.

        Args:
            rows (tuple[WorkflowSessionRowDAO, ...]): New unique rows, possibly empty.
        """
        old_index: int = min(self._list.index or 0, max(0, len(self._rows) - 1))
        old_key: Optional[WorkflowSessionKeyDAO] = self._rows[old_index].row.key if self._rows else None
        old_y: float = self._list.scroll_y
        revision: int = self._list.navigation_revision
        try:
            await self._list.clear()
            self._rows = [SubAgentFleetRow(row=row) for row in rows]
            await self._list.extend(self._rows)
        finally:
            self._adopt_mounted_rows()
        self._list.index = self._restored_index(revision=revision, key=old_key, index=old_index)
        self._list.call_after_refresh(self._queue_position_restore, revision=revision, y=old_y)

    def _adopt_mounted_rows(self) -> None:
        """Mirror the rows actually mounted, so a failed mount cannot leave drift.

        A partial ``clear``/``extend`` failure leaves an unknown subset mounted;
        the next application then compares keys against what is on screen and
        rebuilds instead of updating rows that never mounted.
        """
        self._rows = [item for item in self._list.children if isinstance(item, SubAgentFleetRow)]
        self.display = bool(self._rows)

    def _restored_index(
        self,
        *,
        revision: int,
        key: Optional[WorkflowSessionKeyDAO],
        index: int,
    ) -> Optional[int]:
        """Choose the highlighted index for the rebuilt rows.

        Args:
            revision (int): Navigation revision captured before the rebuild.
            key (Optional[WorkflowSessionKeyDAO]): Key highlighted before the rebuild.
            index (int): Index highlighted before the rebuild.

        Returns:
            Optional[int]: The old key's new index, else the clamped old index.
                When the user navigated during the rebuild, the latest highlighted
                key (or its clamped index) wins instead. None when empty.
        """
        if not self._rows:
            return None
        if revision != self._list.navigation_revision:
            return self._index_of(key=self._navigation_key, fallback=self._navigation_index)
        return self._index_of(key=key, fallback=index)

    def _index_of(self, *, key: Optional[WorkflowSessionKeyDAO], fallback: int) -> int:
        """Locate a key among the current rows, or clamp a fallback index.

        Args:
            key (Optional[WorkflowSessionKeyDAO]): Key to find.
            fallback (int): Index used when the key is gone.

        Returns:
            int: A valid index into the current (nonempty) rows.
        """
        keys: list[WorkflowSessionKeyDAO] = [item.row.key for item in self._rows]
        if key in keys:
            return keys.index(key)
        return min(fallback, len(keys) - 1)

    def _queue_position_restore(self, *, revision: int, y: float) -> None:
        """Queue offset restoration behind the native highlight scroll.

        Setting the index made the native ``watch_index`` queue
        ``scroll_to_widget`` on the list's refresh queue ahead of this callback;
        that scroll defers its own ``_scroll_to`` by one more hop on the same
        queue. Restoring one hop later lets the saved offset win, so a
        wheel-scrolled list does not jump back to the highlighted row.

        Args:
            revision (int): Navigation revision captured before mounting rows.
            y (float): Previous list scroll offset.
        """
        self._list.call_after_refresh(self._restore_position, revision=revision, y=y)

    def _restore_position(self, *, revision: int, y: float) -> None:
        """Restore the scroll offset after layout unless navigation superseded it.

        The previous offset is clamped to the new range; the highlighted row
        is not scrolled into view, so a wheel-scrolled list stays where it was.

        Args:
            revision (int): Navigation revision captured before mounting rows.
            y (float): Previous list scroll offset.
        """
        if not self.is_mounted or revision != self._list.navigation_revision:
            return
        self._list.scroll_to(y=min(y, self._list.max_scroll_y), animate=False, immediate=True)

    @on(ListView.Highlighted)
    def _remember_selection(self, event: ListView.Highlighted) -> None:
        """Retain the latest valid selection while structural updates await mount.

        Args:
            event (ListView.Highlighted): Native or programmatic highlight update.
        """
        if isinstance(event.item, SubAgentFleetRow) and event.item in self._rows:
            self._navigation_key = event.item.row.key
            self._navigation_index = self._rows.index(event.item)

    @on(ListView.Selected)
    def _selected(self, event: ListView.Selected) -> None:
        """Forward native click/Enter identity to the application.

        Args:
            event (ListView.Selected): Activation from this panel's ListView.
        """
        event.stop()
        if isinstance(event.item, SubAgentFleetRow):
            self.post_message(self.SessionSelected(key=event.item.row.key))
