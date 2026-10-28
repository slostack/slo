"""WorkflowProgressCoordinator — the sole TUI observation refresh owner (feature 94 a.3).

One instance per owning session schedules every workflow observation read: the
session-list snapshot and, when a session is selected, that session's bounded
progress. It owns one five-second timer, at most one in-flight read task, the
observation generation and the selected key. It never owns, cancels or signals
agent execution; closing it stops observation only.

Presentation is behind the consumer-owned ``WorkflowProgressSink`` protocol,
implemented by ``WorkflowProgressUpdatesAdapter`` in
``src/tui/components/chat_transcript/adapters/workflow_progress.py`` and a recording fake in tests.
Reads go through ``WorkflowProgressSource`` (``DetachedWorkflowAppService`` in
production). The adapter owns screen references and saved viewports; this
coordinator owns scheduling and selected identity only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Optional, Protocol

from textual.timer import Timer

from config.logger import log_error
from src.tui.workflows.dao import (
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)

__all__ = ["WorkflowProgressCoordinator", "WorkflowProgressSink", "WorkflowProgressSource"]

REFRESH_INTERVAL_SECONDS: float = 5.0
"""Fixed UI observation cadence; deliberately not configurable (a.3 refresh contract)."""

_MAX_READS_PER_DRAIN: int = 2
"""Initial refresh plus at most one coalesced refresh before waiting for the next tick."""


class WorkflowProgressSource(Protocol):
    """Owner-scoped, read-only observation reads the coordinator schedules."""

    async def load_session_snapshot(self) -> WorkflowSessionSnapshotDAO:
        """Return current or explicitly stale retained session-list rows."""
        ...

    async def load_session_progress(self, *, key: WorkflowSessionKeyDAO) -> SessionProgressSnapshotDAO:
        """Return one member's bounded progress, a safe notice or a removal."""
        ...


class WorkflowProgressSink(Protocol):
    """Presentation boundary for the list and the selected progress view.

    apply_sessions may raise presentation errors; the coordinator/app owns fixed
    feedback and retry. The app routes lifecycle intents back to the coordinator.
    """

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Open (or keep) the view for ``key``; False refuses the selection."""
        ...

    def minimize_progress(self) -> None:
        """Save the viewport and dismiss the owned progress view, if any."""
        ...

    async def apply_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Paint list rows without stealing focus."""
        ...

    def apply_progress(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Paint progress on the still-selected mounted view only."""
        ...

    def membership_removed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Forget a removed selection and show a fixed notice."""
        ...

    def observation_failed(self) -> None:
        """Keep the last good paint and show a fixed retry notice."""
        ...


class WorkflowProgressCoordinator:
    """Coalesce owner-scoped observation; never cancel agent execution.

    Invariants: at most one timer (registered by ``start``) and at most one drain
    task exist; every result is applied only if the generation and selected key
    captured before its read are still current; once closed, no method starts work.
    """

    def __init__(
        self,
        *,
        service: WorkflowProgressSource,
        sink: WorkflowProgressSink,
        schedule: Callable[[float, Callable[[], None]], Timer],
    ) -> None:
        """Bind one owner and its mounted presentation boundary without starting work.

        WHAT: Stores collaborators and empty scheduling state; no timer or task.
        WHO: SloTUI when it binds workflow observation to the current session.
        WHEN: Once per owning session (mount and each ``/new`` adoption).

        Args:
            service (WorkflowProgressSource): Current owner-scoped service.
            sink (WorkflowProgressSink): App adapter for panel/modal presentation.
            schedule (Callable[[float, Callable[[], None]], Timer]): Textual interval
                timer factory, invoked positionally as ``schedule(seconds, callback)``.
        """
        self._service: WorkflowProgressSource = service
        self._sink: WorkflowProgressSink = sink
        self._schedule: Callable[[float, Callable[[], None]], Timer] = schedule
        self._timer: Optional[Timer] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._selected: Optional[WorkflowSessionKeyDAO] = None
        # Bumped on every select/minimize/close; a read applies only if unchanged.
        self._generation: int = 0
        self._presentation_revision: int = 0
        self._presentation_lock: asyncio.Lock = asyncio.Lock()
        self._paint_task: Optional[asyncio.Task[None]] = None
        self._close_task: Optional[asyncio.Task[None]] = None
        # True while a refresh was requested but not yet started by the drain.
        self._pending: bool = False
        self._closed: bool = False
        # (key, execution_id or dispatch_id) whose terminal source was fully read.
        self._terminal_read: Optional[tuple[WorkflowSessionKeyDAO, str]] = None

    def start(self) -> None:
        """Register the sole five-second timer and request an immediate read, once.

        WHO: SloTUI after mount, right after constructing the coordinator.
        WHEN: Once per coordinator; later calls and calls after close are no-ops.
        """
        if self._closed or self._timer is not None:
            return
        self._timer = self._schedule(REFRESH_INTERVAL_SECONDS, self.request_refresh)
        self.request_refresh()

    def select(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Replace observation after the app accepts a list activation.

        WHAT: Asks the sink to open the view; on acceptance invalidates in-flight
            results, adopts ``key``, clears terminal suppression (reopen always
            reads afresh) and requests an immediate read.
        WHO: SloTUI's ``SessionSelected`` handler.
        WHEN: On each Enter or click on a list row.

        Args:
            key (WorkflowSessionKeyDAO): Exact owner-scoped selected key.
        """
        if self._closed or not self._sink.open_progress(key=key):
            return
        self._generation += 1
        self._selected = key
        self._terminal_read = None
        self.request_refresh()

    def minimize(self) -> None:
        """Invalidate any in-flight paint, drop the selection and let the sink dismiss.

        WHO: SloTUI for Escape/Minimize and for a same-key incarnation change; the
            coordinator itself when the selected member is removed.
        WHEN: Before the sink dismisses the view, so no late result can paint it.
        """
        if self._closed:
            return
        self._generation += 1
        self._selected = None
        self._sink.minimize_progress()

    def request_refresh(self) -> None:
        """Coalesce timer, lifecycle and open requests while one bounded read runs.

        WHO: The five-second timer, ``select``, ``start`` and SloTUI lifecycle
            events (child lifecycle, dispatch start, typed dismiss/resume).
        WHEN: Any time before close; at most one drain task exists.
        """
        if self._closed:
            return
        self._pending = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())

    async def close(self) -> None:
        """Stop and join observation before the app replaces or unmounts its session.

        WHAT: Marks closed and invalidates the generation before stopping the
            timer, then cancels and awaits the drain task. A cancelled off-loop
            leaf read may finish in its thread; its result is discarded.
        WHO: SloTUI teardown, before ``service.close`` and ``sink.dispose``.
        WHEN: On ``/new`` adoption and on unmount; idempotent.
        """
        if self._close_task is None:
            self._closed = True
            self._generation += 1
            self._presentation_revision += 1
            self._selected = None
            self._pending = False
            self._close_task = asyncio.create_task(self._close_observation())
        await self._join_paint(task=self._close_task)

    async def _close_observation(self) -> None:
        """Stop the timer, join the drain, then cross the final paint barrier."""
        self._stop_timer()
        task: Optional[asyncio.Task[None]] = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self._presentation_lock:
            pass

    def _stop_timer(self) -> None:
        """Stop and forget the interval timer, if one was registered."""
        if self._timer is None:
            return
        self._timer.stop()
        self._timer = None

    async def _drain(self) -> None:
        """Run requested refreshes serially: the initial one plus at most one coalesced one.

        WHAT: Requests arriving during a read set ``_pending``; after two reads any
            remaining request is dropped until the next scheduled tick, so slow
            reads never become a busy loop. Unexpected errors are reported once per
            refresh through the sink; cancellation propagates to ``close``.
        """
        for _ in range(_MAX_READS_PER_DRAIN):
            if not self._pending or self._closed:
                return
            self._pending = False
            await self._refresh_reporting_failure()
        self._pending = False

    async def _refresh_reporting_failure(self) -> None:
        """Run one refresh; translate an unexpected error into the fixed sink notice."""
        try:
            await self._refresh_current_view()
        except Exception:  # noqa: BLE001 - top-level boundary of one observation refresh
            log_error(msg="workflow_observation_refresh_failed")
            self._sink.observation_failed()

    async def apply_local_snapshot(self, *, snapshot: WorkflowSessionSnapshotDAO) -> bool:
        """Paint committed local visibility without waiting for observation reads.

        Args:
            snapshot: Current service projection.
        Returns:
            bool: Whether this presentation revision painted successfully.
        """
        if self._closed:
            return False
        self._generation += 1
        self._presentation_revision += 1
        return await self._paint_sessions(snapshot=snapshot, generation=self._presentation_revision)

    async def _paint_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO, generation: int) -> bool:
        """Serialize list paint and join shielded panel work before releasing ownership."""
        async with self._presentation_lock:
            if self._closed or generation != self._presentation_revision:
                return False
            self._paint_task = asyncio.create_task(self._sink.apply_sessions(snapshot=snapshot))
            try:
                await self._join_paint(task=self._paint_task)
            finally:
                self._paint_task = None
            if self._closed or generation != self._presentation_revision:
                return False
            key = self._selected
            if key is not None and not any(row.key == key for row in snapshot.rows):
                self._close_removed(key=key)
            return True

    @staticmethod
    async def _join_paint(*, task: asyncio.Task[None]) -> None:
        """Join a started sink operation even across repeated caller cancellation."""
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError()
        task.result()

    async def _refresh_current_view(self) -> None:
        """Read the list, paint it, then refresh the selection captured before the read."""
        generation: int = self._generation
        presentation_revision: int = self._presentation_revision
        key: Optional[WorkflowSessionKeyDAO] = self._selected
        sessions: WorkflowSessionSnapshotDAO = await self._service.load_session_snapshot()
        if self._closed or presentation_revision != self._presentation_revision:
            return
        painted = await self._paint_sessions(snapshot=sessions, generation=presentation_revision)
        if not painted or key is None or generation != self._generation:
            return
        await self._refresh_member(key=key, generation=generation, sessions=sessions)

    async def _refresh_member(
        self,
        *,
        key: WorkflowSessionKeyDAO,
        generation: int,
        sessions: WorkflowSessionSnapshotDAO,
    ) -> None:
        """Close a removed selection, skip a fully read terminal one, otherwise read it.

        Args:
            key (WorkflowSessionKeyDAO): Selection captured before the list read.
            generation (int): Generation captured before the list read.
            sessions (WorkflowSessionSnapshotDAO): Service's retained or fresh rows.
        """
        row = next((row for row in sessions.rows if row.key == key), None)
        if row is None:
            self._close_removed(key=key)
            return
        identity: tuple[WorkflowSessionKeyDAO, str] = (key, row.execution_id or row.dispatch_id)
        if self._terminal_read == identity and row.availability == "available":
            return
        await self._refresh_selected(key=key, generation=generation)

    async def _refresh_selected(self, *, key: WorkflowSessionKeyDAO, generation: int) -> None:
        """Apply progress only to the selection that initiated the read.

        Args:
            key (WorkflowSessionKeyDAO): Captured row identity.
            generation (int): Captured open/minimize generation.
        """
        snapshot: SessionProgressSnapshotDAO = await self._service.load_session_progress(key=key)
        if self._closed or generation != self._generation or key != self._selected:
            return
        if snapshot.membership_removed:
            self._close_removed(key=key)
            return
        self._sink.apply_progress(snapshot=snapshot)
        self._remember_final_read(key=key, snapshot=snapshot)

    def _close_removed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Minimize first (invalidating paint), then let the sink forget the key.

        Args:
            key (WorkflowSessionKeyDAO): Selection no longer in the owner's list.
        """
        self.minimize()
        self._sink.membership_removed(key=key)

    def _remember_final_read(
        self, *, key: WorkflowSessionKeyDAO, snapshot: SessionProgressSnapshotDAO
    ) -> None:
        """Suppress further transcript reads after a complete final read of a known execution.

        A legacy result without execution or dispatch identity is never
        suppressed, because an empty identity cannot tell executions apart.

        Args:
            key (WorkflowSessionKeyDAO): Selected key.
            snapshot (SessionProgressSnapshotDAO): Result just painted.
        """
        identity: str = snapshot.execution_id or snapshot.dispatch_id
        if snapshot.final_read_complete and identity:
            self._terminal_read = (key, identity)
