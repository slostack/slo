"""SessionProgressScreen — read one workflow session without losing your place (feature 94 a.3).

A native Textual ``ModalScreen`` that paints one selected session's bounded
public progress. It owns display state only: the reader's viewport, the last
painted snapshot and semantic messages. It never reads files, never owns or
cancels execution, and never decides scrolling from execution state. The app's
progress sink pushes it, delivers coordinator-validated snapshots and dismisses
it; ``Minimized`` and ``AbortRequested`` are intents the app routes.

``ProgressLog`` is private to this screen: a non-wrapping, manually followed
``RichLog`` that counts user navigation so a delayed post-layout restoration can
tell that the reader moved since the paint that scheduled it.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Optional

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.screen import ModalScreen
from textual.scrollbar import ScrollDown, ScrollLeft, ScrollRight, ScrollTo, ScrollUp
from textual.widgets import Button, RichLog, Static

from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    ProgressViewportDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
)
from src.tui.workflows.transcript_renderer import WorkflowTranscriptRenderer

__all__ = ["PROGRESS_RESET_VIEW_NOTICE", "ProgressLog", "SessionProgressScreen"]

PROGRESS_RESET_VIEW_NOTICE: str = "Progress view reset; earlier position unavailable"
"""Shown after a non-append repaint until the reader next navigates."""

NAVIGATION_HINT: str = "↑↓ scroll · ←→ pan · PgUp/PgDn · End latest · Esc minimize"
"""Fixed keyboard hint painted under the log."""

_READABLE_AVAILABILITY: frozenset[str] = frozenset({"available", "empty"})
"""Snapshot availabilities whose entries are authoritative content to paint."""


class ProgressLog(RichLog):
    """Track user navigation before native RichLog scrolling.

    ``navigation_revision`` increments synchronously before native handling of
    every local key, mouse-down, wheel and scrollbar message, so it advances even
    when the resulting offset is unchanged. Programmatic scrolling never touches
    it. It is a non-refreshing reactive so the screen can watch it.
    """

    navigation_revision: var[int] = var(0, init=False)

    class LayoutChanged(Message):
        """The log was resized, so a restore clamped by earlier layout may now land."""

    def __init__(self) -> None:
        """Build the screen's non-wrapping, manually followed log."""
        # Markdown must fit narrow modals rather than RichLog's default 78-cell floor.
        # Plain tool output remains unwrapped and horizontally scrollable.
        super().__init__(min_width=1, wrap=False, markup=False, auto_scroll=False, id="session-log")

    def on_resize(self, event: events.Resize) -> None:
        """Render deferred lines natively, then report the new layout to the screen.

        Args:
            event (events.Resize): Native resize event.
        """
        super().on_resize(event)
        self.post_message(self.LayoutChanged())

    async def _on_key(self, event: events.Key) -> None:
        """Invalidate restoration before Textual handles a local key.

        Args:
            event (events.Key): Native local key event.
        """
        self.navigation_revision += 1
        await super()._on_key(event)

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        """Invalidate restoration before native mouse navigation.

        Args:
            event (events.MouseDown): Native mouse event.
        """
        self.navigation_revision += 1
        await super()._on_mouse_down(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Preserve user upward navigation across pending layout work.

        Args:
            event (events.MouseScrollUp): Native wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_up(event)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Preserve user downward navigation across pending layout work.

        Args:
            event (events.MouseScrollDown): Native wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_down(event)

    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        """Preserve user leftward wheel panning across pending layout work.

        Args:
            event (events.MouseScrollLeft): Native horizontal wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_left(event)

    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        """Preserve user rightward wheel panning across pending layout work.

        Args:
            event (events.MouseScrollRight): Native horizontal wheel event.
        """
        self.navigation_revision += 1
        super()._on_mouse_scroll_right(event)

    # Scrollbars stop their own mouse-down, then post these messages to this log
    # for every click and drag step; only user scrollbar input produces them.

    def _on_scroll_to(self, message: ScrollTo) -> None:
        """Count a scrollbar drag step before it moves the log.

        Args:
            message (ScrollTo): Scrollbar drag message.
        """
        self.navigation_revision += 1
        super()._on_scroll_to(message)

    def _on_scroll_up(self, event: ScrollUp) -> None:
        """Count a scrollbar page-up click before it moves the log.

        Args:
            event (ScrollUp): Scrollbar message.
        """
        self.navigation_revision += 1
        super()._on_scroll_up(event)

    def _on_scroll_down(self, event: ScrollDown) -> None:
        """Count a scrollbar page-down click before it moves the log.

        Args:
            event (ScrollDown): Scrollbar message.
        """
        self.navigation_revision += 1
        super()._on_scroll_down(event)

    def _on_scroll_left(self, event: ScrollLeft) -> None:
        """Count a horizontal scrollbar click before it moves the log.

        Args:
            event (ScrollLeft): Scrollbar message.
        """
        self.navigation_revision += 1
        super()._on_scroll_left(event)

    def _on_scroll_right(self, event: ScrollRight) -> None:
        """Count a horizontal scrollbar click before it moves the log.

        Args:
            event (ScrollRight): Scrollbar message.
        """
        self.navigation_revision += 1
        super()._on_scroll_right(event)


class SessionProgressScreen(ModalScreen[None]):
    """Present one selected session; emit intent without owning execution.

    Invariants: content is painted only from readable snapshots; a repaint keeps
    existing lines only for an exact same-source entry prefix; a scheduled
    restoration applies only if no newer paint and no user navigation happened.
    """

    CSS_PATH = "session_progress_screen.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(key="escape", action="minimize", description="Minimize", priority=True)
    ]
    # Below 80 columns the action buttons stack (see the adjacent TCSS).
    HORIZONTAL_BREAKPOINTS = [
        (0, "-progress-narrow"),
        (80, "-progress-wide"),
    ]

    class Minimized(Message):
        """Tell the app to close observation without stopping execution."""

    class AbortRequested(Message):
        """Carry the immutable confirmation target to the app-owned sink."""

        def __init__(self, *, target: ChildAbortTargetDAO) -> None:
            """Capture identity when the operator chooses Abort.

            Args:
                target (ChildAbortTargetDAO): Exact current run/incarnation.
            """
            super().__init__()
            self.target: ChildAbortTargetDAO = target

    def __init__(self, *, key: WorkflowSessionKeyDAO, viewport: ProgressViewportDAO) -> None:
        """Bind observation identity and saved position; the sink owns lifetime.

        Args:
            key (WorkflowSessionKeyDAO): Session selected from the owner list.
            viewport (ProgressViewportDAO): Saved position or initial tail intent.
        """
        super().__init__()
        self.key: WorkflowSessionKeyDAO = key
        # Used for the first paint that has content; later paints capture live.
        self._initial_viewport: Optional[ProgressViewportDAO] = viewport
        self._log: ProgressLog = ProgressLog()
        self._state: Static = Static(markup=False, id="session-state")
        self._task_text: Static = Static(markup=False, id="task-description")
        self._abort: Button = Button(label="Abort child…", id="abort-child", variant="error", disabled=True)
        self._snapshot: Optional[SessionProgressSnapshotDAO] = None
        self._last_readable: Optional[SessionProgressSnapshotDAO] = None
        self._paint_revision: int = 0
        # A restore that layout clamped (for example, before wide lines were laid
        # out), kept until it lands, the reader navigates, or it is superseded.
        self._pending_restore: Optional[ProgressViewportDAO] = None
        self._pending_navigation: int = 0
        # Navigation revision at which the reset notice appeared; None when hidden.
        self._reset_notice_navigation: Optional[int] = None
        # True from retirement until the view pops itself; it pops only while on top.
        self._close_pending: bool = False

    def compose(self) -> ComposeResult:
        """Build the native modal once when the sink pushes it."""
        with Vertical(id="progress-box"):
            yield Static(
                content=f"Session progress · {self.key.session_id}",
                markup=False,
                id="progress-heading",
                classes="heading",
            )
            with VerticalScroll(id="task-scroll"):
                yield self._task_text
            yield self._state
            yield self._log
            yield Static(content=NAVIGATION_HINT, markup=False, classes="hint")
            with Horizontal(classes="actions"):
                yield Button(label="Minimize", id="minimize")
                yield self._abort

    def on_mount(self) -> None:
        """Focus the log for keyboard reading and watch for user navigation."""
        self._log.focus()
        self.watch(self._log, "navigation_revision", self._hide_reset_notice, init=False)
        self.watch(self._log, "virtual_size", self._retry_pending_restore, init=False)

    def on_progress_log_layout_changed(self, _message: ProgressLog.LayoutChanged) -> None:
        """Retry a clamped restore once the log has been laid out again.

        Args:
            _message (ProgressLog.LayoutChanged): Resize notification from the log.
        """
        self._retry_pending_restore()

    def apply_snapshot(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Paint safe status and changed content after coordinator freshness checks.

        WHAT: Always refreshes task text, status line and Abort eligibility; paints
            content only for readable (available/empty) snapshots, so stale or
            unavailable results keep the last good content and position.
        WHO: The app's progress sink, for the screen object it still owns.
        WHEN: On every validated progress delivery while the screen is mounted.

        Args:
            snapshot (SessionProgressSnapshotDAO): Bounded public progress result.
        """
        self._task_text.update(content=snapshot.task_text)
        self._abort.disabled = snapshot.abort_target is None
        self._snapshot = snapshot
        if snapshot.availability in _READABLE_AVAILABILITY:
            self._apply_content(snapshot=snapshot)
        self._render_state()

    @property
    def is_live(self) -> bool:
        """Return whether the screen is mounted and still attached to the app.

        Textual 8 keeps ``is_mounted`` True after a dismissed screen is removed,
        so delayed callbacks also require ``is_attached``.
        """
        return self.is_mounted and self.is_attached

    def capture_viewport(self) -> ProgressViewportDAO:
        """Return reader state to the sink on refresh/minimize.

        Returns:
            ProgressViewportDAO: Current offsets independent of execution.
        """
        return ProgressViewportDAO.capture(log=self._log)

    def retire(self) -> None:
        """Close this view now when it is active, otherwise as soon as it is active again.

        WHAT: Textual's ``dismiss`` pops whatever screen is on top, so a view
            covered by an unrelated modal never dismisses itself under it; it
            waits for that modal to close and then leaves the stack on resume.
        WHO: The app's progress sink when it minimizes, replaces or disposes it.
        WHEN: After the sink stopped owning the view; repeated calls close it once.
        """
        self._close_pending = True
        self._close_if_on_top()

    def on_screen_resume(self) -> None:
        """Finish a retirement deferred while an unrelated modal covered this view."""
        self._close_if_on_top()

    def _close_if_on_top(self) -> None:
        """Pop this view once, and only while it is the active screen.

        WHAT: ``ScreenResume`` is queued, so it can reach this view after it
            already left the stack or after another screen was pushed above
            it; ``dismiss`` would then pop that other screen or an empty stack.
        WHO: ``retire`` and ``on_screen_resume``.
        WHEN: Whenever a pending close may now be possible.
        """
        if not (self._close_pending and self.is_active):
            return
        self._close_pending = False
        self.dismiss()

    def action_minimize(self) -> None:
        """Ask the app to minimize; never cancel a session or accepted request."""
        self.post_message(self.Minimized())

    @on(Button.Pressed, "#minimize")
    def _minimize_pressed(self) -> None:
        """Map mouse activation to the Escape semantic message."""
        self.action_minimize()

    @on(Button.Pressed, "#abort-child")
    def _abort_pressed(self) -> None:
        """Emit the currently displayed eligible identity for confirmation."""
        target: Optional[ChildAbortTargetDAO] = self._snapshot.abort_target if self._snapshot else None
        if target is not None:
            self.post_message(self.AbortRequested(target=target))

    def _apply_content(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Append or rebuild only when the loader revision changes at delivery.

        Args:
            snapshot (SessionProgressSnapshotDAO): Readable current observation.
        """
        previous: Optional[SessionProgressSnapshotDAO] = self._last_readable
        self._last_readable = snapshot
        if previous is not None and previous.revision == snapshot.revision:
            return
        viewport: ProgressViewportDAO = self._delivery_viewport()
        self._paint_entries(previous=previous, snapshot=snapshot)
        self._schedule_restore(viewport=viewport)

    def _delivery_viewport(self) -> ProgressViewportDAO:
        """Choose the position to restore: saved intent until content first lands, else live.

        Returns:
            ProgressViewportDAO: Saved viewport while the log is still empty, else the
                reader's position captured right now.
        """
        if self._initial_viewport is not None and not self._log.lines:
            return self._initial_viewport
        if self._pending_restore is not None and self._pending_navigation == self._log.navigation_revision:
            # The live offsets are only a clamp of the saved position, not the reader's.
            return self._pending_restore
        return self.capture_viewport()

    def _paint_entries(
        self,
        *,
        previous: Optional[SessionProgressSnapshotDAO],
        snapshot: SessionProgressSnapshotDAO,
    ) -> None:
        """Preserve existing lines only for an exact same-source entry prefix.

        WHAT: An exact prefix appends only the new entries. A growing last entry
            (live streaming text) rewrites the log silently: earlier lines are
            identical, so the restored offset still shows the same content. Any
            other change (new source, edited or evicted earlier entries) rebuilds
            and shows the fixed reset notice.

        Args:
            previous (Optional[SessionProgressSnapshotDAO]): Last painted content.
            snapshot (SessionProgressSnapshotDAO): New bounded entries.
        """
        kept: int = len(previous.entries) if previous is not None else 0
        if previous is not None and not self._extends(previous=previous, snapshot=snapshot):
            self._log.clear()
            self._show_reset_notice(previous=previous, snapshot=snapshot)
            kept = 0
        for entry in snapshot.entries[kept:]:
            WorkflowTranscriptRenderer.write_entry(log=self._log, entry=entry)
        if snapshot.entries:
            self._initial_viewport = None

    @staticmethod
    def _extends(*, previous: SessionProgressSnapshotDAO, snapshot: SessionProgressSnapshotDAO) -> bool:
        """Return whether ``snapshot`` keeps every painted entry of the same source.

        Args:
            previous (SessionProgressSnapshotDAO): Last painted content.
            snapshot (SessionProgressSnapshotDAO): New bounded entries.

        Returns:
            bool: True for an exact same-source prefix (append only).
        """
        count: int = len(previous.entries)
        same_source: bool = previous.source_generation == snapshot.source_generation
        return same_source and snapshot.entries[:count] == previous.entries

    def _show_reset_notice(
        self,
        *,
        previous: SessionProgressSnapshotDAO,
        snapshot: SessionProgressSnapshotDAO,
    ) -> None:
        """Show the fixed reset notice unless the rebuild only grew the last entry.

        Args:
            previous (SessionProgressSnapshotDAO): Content before the rebuild.
            snapshot (SessionProgressSnapshotDAO): Content being painted.
        """
        if not previous.entries or self._grows_last_entry(previous=previous, snapshot=snapshot):
            return
        self._reset_notice_navigation = self._log.navigation_revision

    @staticmethod
    def _grows_last_entry(
        *, previous: SessionProgressSnapshotDAO, snapshot: SessionProgressSnapshotDAO
    ) -> bool:
        """Return whether only the last painted entry changed, within the same source.

        Args:
            previous (SessionProgressSnapshotDAO): Nonempty last painted content.
            snapshot (SessionProgressSnapshotDAO): Content being painted.

        Returns:
            bool: True when every earlier entry is unchanged and the last still exists.
        """
        stable: int = len(previous.entries) - 1
        same_source: bool = previous.source_generation == snapshot.source_generation
        return (
            same_source
            and len(snapshot.entries) > stable
            and snapshot.entries[:stable] == previous.entries[:stable]
        )

    def _hide_reset_notice(self, revision: int) -> None:
        """Drop the reset notice once the reader navigates after it appeared.

        Args:
            revision (int): New navigation revision.
        """
        if self._reset_notice_navigation is None or revision == self._reset_notice_navigation:
            return
        self._reset_notice_navigation = None
        self._render_state()

    def _render_state(self) -> None:
        """Paint the status line: notices, last readable status and its observation time."""
        parts: list[str] = []
        if self._reset_notice_navigation is not None:
            parts.append(PROGRESS_RESET_VIEW_NOTICE)
        if self._snapshot is not None and self._snapshot.notice:
            parts.append(self._snapshot.notice)
        parts.extend(self._status_parts())
        self._state.update(content=" · ".join(parts))

    def _status_parts(self) -> list[str]:
        """Return the last readable status and update time, or a waiting placeholder.

        Returns:
            list[str]: Status, refresh cadence and update time; a single loading
                notice before any readable snapshot.
        """
        readable: Optional[SessionProgressSnapshotDAO] = self._last_readable
        if readable is None:
            return ["Loading progress…"]
        updated: str = datetime.fromisoformat(readable.observed_at).strftime("%H:%M:%S")
        return [readable.status, "Refresh every 5s", f"Updated {updated}"]

    def _schedule_restore(self, *, viewport: ProgressViewportDAO) -> None:
        """Queue one layout-aware restoration for the current paint/navigation.

        Args:
            viewport (ProgressViewportDAO): Position captured immediately before paint.
        """
        self._paint_revision += 1
        self._pending_restore = None
        self.call_after_refresh(
            self._restore_if_current,
            revision=self._paint_revision,
            navigation=self._log.navigation_revision,
            viewport=viewport,
        )

    def _restore_if_current(self, *, revision: int, navigation: int, viewport: ProgressViewportDAO) -> None:
        """Let user navigation and newer paints win over delayed layout callbacks.

        A restore clamped by layout that has not settled yet stays pending; the
        log's next resize or content-size change retries it.

        Args:
            revision (int): Paint generation that scheduled restoration.
            navigation (int): User-navigation generation captured at paint.
            viewport (ProgressViewportDAO): Old offsets and tail-follow intent.
        """
        if not self.is_live or revision != self._paint_revision:
            return
        if navigation != self._log.navigation_revision:
            return
        if not viewport.restore(log=self._log):
            self._pending_restore = viewport
            self._pending_navigation = navigation

    def _retry_pending_restore(self) -> None:
        """Land a pending restore after layout changed, unless the reader navigated."""
        viewport: Optional[ProgressViewportDAO] = self._pending_restore
        if viewport is None or not self.is_live:
            return
        if self._pending_navigation != self._log.navigation_revision:
            self._pending_restore = None
            return
        if viewport.restore(log=self._log):
            self._pending_restore = None
