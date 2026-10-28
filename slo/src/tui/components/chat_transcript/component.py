"""Mounted conversation presentation, independent of session execution.

Own replay publication, lifecycle admission, viewport intent and bounded mounted
content. The application retains session execution, subscription and focus policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from importlib.resources import files
from dataclasses import dataclass, replace
from functools import partial

from textual._animator import EasingFunction
from textual._types import AnimationLevel
from textual.messages import CallbackType

from textual import events
from textual.actions import SkipAction
from textual.scrollbar import ScrollUp, ScrollDown, ScrollLeft, ScrollRight, ScrollTo
from typing import ClassVar, Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static
from textual.widget import Widget
from textual.message import Message

from config.logger import log_warning

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter
from src.tui.transcript_projector import TranscriptProjectionAdapter
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock, FollowSnapshotDAO
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.user_message_block import UserMessageBlock
from src.tui.widgets.steering_pending_block import SteeringPendingBlock

HistoryReader = Callable[[], Awaitable[list[TranscriptEntryDAO]]]
TRANSCRIPT_HYDRATION_ENTRY_LIMIT: int = 30
LOAD_OLDER_BATCH_SIZE: int = 30
TRANSCRIPT_WINDOW_SIZE: int = 500
TRANSCRIPT_PROTECTED_TAIL_SIZE: int = 10


@dataclass(frozen=True)
class _LoadOlderAnchorDAO:
    """Retain a message border in common scroll-content coordinates."""

    widget: Optional[Widget]
    offset_before: float
    scroll_y_before: float
    generation: int
    viewport_revision: int


@dataclass(frozen=True)
class _ViewportTokenDAO:
    """Identify deferred work in one content and viewport lifetime."""

    generation: int
    revision: int


@dataclass(frozen=True)
class _NativeScrollRequestDAO:
    """Describe one native input; None means that axis was not requested."""

    x: Optional[float] = None
    y: Optional[float] = None
    animate: bool = True
    duration: Optional[float] = None
    immediate: bool = False
    bottom: bool = False
    release_anchor: bool = True


@dataclass
class _NativeNavigationDAO:
    """Retain requested destinations and completion only for requested axes."""

    token: _ViewportTokenDAO
    request: _NativeScrollRequestDAO
    anchor: Optional[_LoadOlderAnchorDAO]
    follows_bottom: bool
    pending_axes: set[str]
    started: bool = False
    settlement_queued: bool = False


# component.py — TranscriptScroll implementation (one constructor).
# Imports: textual._animator.EasingFunction; textual._types.AnimationLevel;
# textual.messages.CallbackType; textual.events; textual.actions.SkipAction;
# textual.scrollbar.ScrollUp/ScrollDown/ScrollLeft/ScrollRight/ScrollTo.
class TranscriptScroll(VerticalScroll):
    """Translate inputs and guard deferred native calls; keep policy in ChatTranscript."""

    def __init__(
        self, *, navigate: Callable[[_NativeScrollRequestDAO], bool], interrupt: Callable[[], None], id: str
    ) -> None:
        """Borrow owner callbacks; initialize transport guards without starting work."""
        super().__init__(id=id)
        self._navigate = navigate
        self._interrupt = interrupt
        self._owner_scroll: bool = False
        self._scroll_epoch: int = 0

    class ReachedTop(Message):
        """Report a crossing into the top band, not every geometry update."""

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Preserve native watching before reporting the top crossing."""
        super().watch_scroll_y(old_value=old_value, new_value=new_value)
        if new_value <= 2 < old_value:
            self.post_message(self.ReachedTop())

    def invalidate_deferred_scrolls(self) -> None:
        """Revoke old public deferred starts before native force-stop callbacks."""
        self._scroll_epoch += 1

    def _scroll_to(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        *,
        animate: bool = True,
        speed: Optional[float] = None,
        duration: Optional[float] = None,
        easing: Optional[EasingFunction | str] = None,
        force: bool = False,
        on_complete: Optional[CallbackType] = None,
        level: AnimationLevel = "basic",
        release_anchor: bool = True,
    ) -> bool:
        """Guard direct framework execution before its unconditional two-axis stop."""
        if not self.is_attached or any(not node.display for node in (self, *self.ancestors)):
            return False
        if not self._owner_scroll:
            self._interrupt()
        return super()._scroll_to(
            x=x,
            y=y,
            animate=animate,
            speed=speed,
            duration=duration,
            easing=easing,
            force=force,
            on_complete=on_complete,
            level=level,
            release_anchor=release_anchor,
        )

    def scroll_to(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        *,
        animate: bool = True,
        speed: Optional[float] = None,
        duration: Optional[float] = None,
        easing: Optional[EasingFunction | str] = None,
        force: bool = False,
        on_complete: Optional[CallbackType] = None,
        level: AnimationLevel = "basic",
        immediate: bool = False,
        release_anchor: bool = True,
    ) -> None:
        """Preserve native scheduling and defaults; reject starts superseded by user intent."""
        if not self.is_attached or any(not node.display for node in (self, *self.ancestors)):
            return
        if not self._owner_scroll:
            self._interrupt()
        epoch = self._scroll_epoch
        if release_anchor:
            self.release_anchor()
        if x is not None:
            self.app.animator.force_stop_animation(obj=self, attribute="scroll_x")
        if y is not None:
            self.app.animator.force_stop_animation(obj=self, attribute="scroll_y")

        def start() -> None:
            """Mirror native public delegation only while this scheduled call is current."""
            if epoch != self._scroll_epoch or not self.is_attached or not self.display:
                return
            # Native scroll_to omits release_anchor in its private delegation.
            self._scroll_to(
                x=x,
                y=y,
                animate=animate,
                speed=speed,
                duration=duration,
                easing=easing,
                force=force,
                on_complete=on_complete,
                level=level,
            )

        if immediate:
            start()
        else:
            self.call_after_refresh(start)

    def _wheel(self, *, event: events.MouseEvent, axis: str, direction: int, animate: bool) -> None:
        """Translate only allowed pointer movement; retain edge bubbling."""
        event.prevent_default()
        allowed = self.allow_vertical_scroll if axis == "y" else self.allow_horizontal_scroll
        if not allowed:
            return
        request = (
            _NativeScrollRequestDAO(
                y=self.scroll_target_y + direction * self.app.scroll_sensitivity_y,
                animate=animate,
                immediate=True,
                release_anchor=direction < 0,
            )
            if axis == "y"
            else _NativeScrollRequestDAO(
                x=self.scroll_target_x + direction * self.app.scroll_sensitivity_x,
                animate=animate,
                immediate=True,
            )
        )
        if self._navigate(request):
            event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        """Translate up or modified horizontal wheel using native sensitivity."""
        self._wheel(event=event, axis="x" if event.ctrl or event.shift else "y", direction=-1, animate=False)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Translate down without releasing the native vertical anchor."""
        self._wheel(event=event, axis="x" if event.ctrl or event.shift else "y", direction=1, animate=False)

    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        """Retain dedicated horizontal wheel animation."""
        self._wheel(event=event, axis="x", direction=-1, animate=True)

    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        """Retain dedicated horizontal wheel animation."""
        self._wheel(event=event, axis="x", direction=1, animate=True)

    def _step(self, *, axis: str, direction: int, page: bool) -> None:
        """Translate an allowed arrow/page action; disabled actions bubble via SkipAction."""
        allowed = self.allow_vertical_scroll if axis == "y" else self.allow_horizontal_scroll
        if not allowed:
            raise SkipAction()
        if axis == "y":
            y = (
                self.scroll_y + direction * self.scrollable_content_region.height
                if page
                else self.scroll_target_y + direction
            )
            self._navigate(_NativeScrollRequestDAO(y=y))
            return
        x = (
            self.scroll_x + direction * self.scrollable_content_region.width
            if page
            else self.scroll_target_x + direction
        )
        self._navigate(_NativeScrollRequestDAO(x=x, duration=0.3 if page else None))

    def _on_scroll_up(self, event: ScrollUp) -> None:
        """Translate an allowed vertical track click once."""
        event.prevent_default()
        if self.allow_vertical_scroll:
            self._step(axis="y", direction=-1, page=True)
            event.stop()

    def _on_scroll_down(self, event: ScrollDown) -> None:
        """Translate an allowed vertical track click once."""
        event.prevent_default()
        if self.allow_vertical_scroll:
            self._step(axis="y", direction=1, page=True)
            event.stop()

    def _on_scroll_left(self, event: ScrollLeft) -> None:
        """Translate an allowed horizontal track click once."""
        event.prevent_default()
        if self.allow_horizontal_scroll:
            self._step(axis="x", direction=-1, page=True)
            event.stop()

    def _on_scroll_right(self, event: ScrollRight) -> None:
        """Translate an allowed horizontal track click once."""
        event.prevent_default()
        if self.allow_horizontal_scroll:
            self._step(axis="x", direction=1, page=True)
            event.stop()

    def _on_scroll_to(self, message: ScrollTo) -> None:
        """Translate scrollbar drag coordinates; y=None remains horizontal-only."""
        message.prevent_default()
        if self._allow_scroll:
            self._navigate(
                _NativeScrollRequestDAO(x=message.x, y=message.y, animate=message.animate, duration=0.1)
            )
            message.stop()

    def action_scroll_up(self) -> None:
        """Request one row upward."""
        self._step(axis="y", direction=-1, page=False)

    def action_scroll_down(self) -> None:
        """Request one row downward."""
        self._step(axis="y", direction=1, page=False)

    def action_page_up(self) -> None:
        """Request one viewport upward."""
        self._step(axis="y", direction=-1, page=True)

    def action_page_down(self) -> None:
        """Request one viewport downward."""
        self._step(axis="y", direction=1, page=True)

    def action_scroll_left(self) -> None:
        """Request one column left."""
        self._step(axis="x", direction=-1, page=False)

    def action_scroll_right(self) -> None:
        """Request one column right."""
        self._step(axis="x", direction=1, page=False)

    def action_page_left(self) -> None:
        """Request one viewport left."""
        self._step(axis="x", direction=-1, page=True)

    def action_page_right(self) -> None:
        """Request one viewport right."""
        self._step(axis="x", direction=1, page=True)

    def action_scroll_home(self) -> None:
        """Preserve native Home's conditional horizontal reset."""
        if not self._allow_scroll:
            raise SkipAction()
        self._navigate(_NativeScrollRequestDAO(x=0.0 if self.scroll_y == 0 else None, y=0.0, duration=1.0))

    def action_scroll_end(self) -> None:
        """Preserve native End's x=0 guard and anchor handling; resolve y after layout."""
        if not self._allow_scroll:
            raise SkipAction()
        if self._anchored and self._anchor_released:
            self._anchor_released = False
        self._navigate(
            _NativeScrollRequestDAO(
                x=0.0 if self.scroll_y == self.is_vertical_scroll_end else None,
                y=self.max_scroll_y,
                bottom=True,
                duration=1.0,
                release_anchor=False,
            )
        )


class ChatTranscript(Vertical):
    """Own replay presentation and mounted messages; borrow only the history reader."""

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.chat_transcript").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    def __init__(self, *, history_reader: HistoryReader) -> None:
        """Build an inactive surface without reading history or subscribing to events.

        Args:
            history_reader: Borrowed canonical replay operation; never closed here.
        """
        super().__init__(id="chat-transcript")
        self._history_reader = history_reader
        self._transcript_scroll = TranscriptScroll(
            navigate=self._navigate_native,
            interrupt=self._before_programmatic_scroll,
            id="transcript-scroll",
        )
        self._transcript_content = Vertical(id="transcript-content")
        self._adapter = TranscriptNoticeDisplayAdapter.register(tui=self)
        self.workflow_notice = WorkflowNoticeAdapter.register(tui=self)
        self._projector = TranscriptProjectionAdapter(host=self)
        self._load_older_cursor: int = 0
        self._hydrated: bool = False
        self._generation: int = 0
        self._viewport_revision: int = 0
        self._visible = True
        self._hidden_following = True
        self._geometry_ready = False
        self._reading = False
        self._reading_anchor: Optional[_LoadOlderAnchorDAO] = None
        self._native_navigation: Optional[_NativeNavigationDAO] = None
        self._force_following_until_layout = False
        self._follow_pin_dirty = False
        self._pin_sequence = 0
        self._active_pin: Optional[tuple[int, int, int]] = None
        self._hydration_lock = asyncio.Lock()
        self._presentation_closed: bool = False
        self._mutation_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task[list[TranscriptEntryDAO]]] = None
        self._older_task: Optional[asyncio.Task[None]] = None
        self._older_projection_failed = False
        self._back_scroll_mode = False
        self._hidden_block_count = 0
        self._earlier_summary: Optional[LiteralTextStatic] = None
        self._window_task: Optional[asyncio.Task[None]] = None
        self._window_enforcement_rerun = False
        self._pending_steer_blocks: list[SteeringPendingBlock] = []
        self._global_expand_all: Optional[bool] = None
        self._active_expandable_tool_block: Optional[ToolExecutionBlock] = None

    def compose(self) -> ComposeResult:
        """Mount the retained scroll/content pair once for this widget lifetime."""
        with self._transcript_scroll:
            yield self._transcript_content

    def on_mount(self) -> None:
        """Wait for visible layout before using geometry."""
        self.call_after_refresh(
            self._resume_visible_layout, token=(self._generation, self._viewport_revision)
        )

    def on_resize(self, event: events.Resize) -> None:
        """Preserve following when app startup or resize changes available height."""
        if self._visible and not self._reading:
            self.call_after_refresh(
                self._resume_visible_layout, token=(self._generation, self._viewport_revision)
            )

    def _resume_visible_layout(self, *, token: tuple[int, int]) -> None:
        """Restore retained intent only on the attached visible surface."""
        if (
            token[0] != self._generation
            or not self._visible
            or self._presentation_closed
            or not self.is_attached
        ):
            return
        self._geometry_ready = self._transcript_scroll.scrollable_content_region.height > 0
        if self._reading_anchor is not None:
            self._restore_reading_anchor(anchor=self._reading_anchor)
        elif self._hidden_following:
            self._queue_follow_pin()

    def _anchor_candidates(self) -> list[Widget]:
        """Use message roots and tree siblings, never nested bodies or markers."""
        return self._ordinary_children() + [
            child for child in self._transcript_scroll.children if child is not self._transcript_content
        ]

    def _scroll_content_y(self, *, widget: Widget) -> float:
        """Convert a border origin into common scroll-content cell coordinates."""
        scroll = self._transcript_scroll
        return float(widget.region.y - scroll.content_region.y + scroll.scroll_offset.y)

    def _capture_reading_anchor(self, *, target_y: Optional[float] = None) -> Optional[_LoadOlderAnchorDAO]:
        """Capture the current or requested reading destination after visible layout."""
        if not self._has_visible_geometry():
            return None
        scroll = self._transcript_scroll
        target = float(scroll.scroll_offset.y) if target_y is None else target_y
        height = scroll.scrollable_content_region.height
        candidates = sorted(
            (
                child
                for child in self._anchor_candidates()
                if child.is_attached and child.display and child.region.height > 0
            ),
            key=lambda child: child.region.y,
        )
        anchor = next(
            (
                child
                for child in candidates
                if self._scroll_content_y(widget=child) + child.region.height > target
                and self._scroll_content_y(widget=child) < target + height
            ),
            None,
        )
        return _LoadOlderAnchorDAO(
            widget=anchor,
            offset_before=0.0 if anchor is None else self._scroll_content_y(widget=anchor),
            scroll_y_before=target,
            generation=self._generation,
            viewport_revision=self._viewport_revision,
        )

    def _retain_reading_anchor(self) -> None:
        """Retain one pre-mutation reading point, never an intermediate native frame."""
        if self._native_navigation is None and self._reading_anchor is None and self._reading:
            self._reading_anchor = self._capture_reading_anchor()

    def _restore_reading_anchor(self, *, anchor: _LoadOlderAnchorDAO) -> None:
        """Restore only the exact current reading snapshot after layout."""
        if (
            self._native_navigation is not None
            or not self._visible
            or not self._geometry_ready
            or not self.is_attached
            or self._presentation_closed
            or self._reading_anchor is not anchor
            or anchor.generation != self._generation
            or anchor.viewport_revision != self._viewport_revision
        ):
            return
        target = anchor.scroll_y_before
        widget = anchor.widget
        if (
            widget is not None
            and widget.is_attached
            and widget.display
            and widget in self._anchor_candidates()
        ):
            target += self._scroll_content_y(widget=widget) - anchor.offset_before
        self._transcript_scroll.scroll_to(
            y=max(0.0, min(target, self._transcript_scroll.max_scroll_y)), animate=False, immediate=True
        )
        self._reading_anchor = None

    # component.py — methods on ChatTranscript; imports: replace, partial.
    def _invalidate_navigation(self) -> None:
        """Revoke all callbacks before either native axis can run a stop callback."""
        self._native_navigation = None
        self._active_pin = None
        self._follow_pin_dirty = False
        self._force_following_until_layout = False
        scroll = self._transcript_scroll
        scroll.invalidate_deferred_scrolls()
        if scroll.is_attached:
            scroll.app.animator.force_stop_animation(obj=scroll, attribute="scroll_x")
            scroll.app.animator.force_stop_animation(obj=scroll, attribute="scroll_y")

    def _navigation_is_current(self, *, token: _ViewportTokenDAO) -> bool:
        """Accept only the visible operation in the current content lifetime."""
        operation = self._native_navigation
        return (
            operation is not None
            and operation.token == token
            and token == _ViewportTokenDAO(generation=self._generation, revision=self._viewport_revision)
            and self._has_visible_geometry()
        )

    def _destination_anchor(self, *, target_y: float) -> _LoadOlderAnchorDAO:
        """Capture the destination border before a stop can move the input frame."""
        scroll = self._transcript_scroll
        candidates = sorted(
            (
                item
                for item in self._anchor_candidates()
                if item.is_attached and item.display and item.region.height > 0
            ),
            key=lambda item: self._scroll_content_y(widget=item),
        )
        widget = next(
            (
                item
                for item in candidates
                if self._scroll_content_y(widget=item) + item.region.height > target_y
                and self._scroll_content_y(widget=item) < target_y + scroll.scrollable_content_region.height
            ),
            None,
        )
        return _LoadOlderAnchorDAO(
            widget=widget,
            offset_before=0.0 if widget is None else self._scroll_content_y(widget=widget),
            scroll_y_before=target_y,
            generation=self._generation,
            viewport_revision=self._viewport_revision,
        )

    def _anchor_target(self, *, anchor: _LoadOlderAnchorDAO) -> float:
        """Resolve retained border displacement, falling back to saved numerical y."""
        target = anchor.scroll_y_before
        widget = anchor.widget
        if (
            widget is not None
            and widget.is_attached
            and widget.display
            and widget in self._anchor_candidates()
        ):
            target += self._scroll_content_y(widget=widget) - anchor.offset_before
        return max(0.0, min(target, self._transcript_scroll.max_scroll_y))

    def _reconcile_visible_viewport(self) -> None:
        """Adopt pre-stop vertical reality before horizontal input or hiding.

        Called synchronously by input admission before invalidation. A current bottom
        latch preserves an accepted pin intent; otherwise geometry cannot re-arm an
        already-reading viewport. Capture before either native axis can be stopped.
        """
        scroll = self._transcript_scroll
        pending_bottom = not self._reading and self._force_following_until_layout
        at_bottom = scroll.max_scroll_y - scroll.scroll_y <= 1.0
        follows = pending_bottom or (not self._reading and at_bottom)
        self._reading = not follows
        self._back_scroll_mode = not follows
        self._hidden_following = follows
        if follows:
            self._reading_anchor = None
            return
        # A retained snapshot predates an unfinished layout mutation; do not replace it.
        self._retain_reading_anchor()
        if self._reading_anchor is None:
            self._reading_anchor = self._destination_anchor(target_y=float(scroll.scroll_offset.y))

    def _hold_horizontal_viewport(self, *, target_y: float) -> None:
        """Undo both-axis force-stop displacement before x-only admission can paint.

        Args:
            target_y: Reading y resolved before force-stop, in painted terminal cells.
        """
        scroll = self._transcript_scroll
        scroll._owner_scroll = True
        try:
            scroll._scroll_to(y=max(0.0, min(target_y, scroll.max_scroll_y)), animate=False)
        finally:
            scroll._owner_scroll = False

    def _has_visible_geometry(self) -> bool:
        """Admit geometry work only while this surface and its ancestors are displayed."""
        return (
            self._visible
            and self._geometry_ready
            and self.is_attached
            and not self._presentation_closed
            and all(node.display for node in (self, *self.ancestors))
        )

    def _navigate_native(self, request: _NativeScrollRequestDAO) -> bool:
        """Admit input synchronously; return whether its requested axis can move."""
        if not self._has_visible_geometry():
            return False
        scroll = self._transcript_scroll
        old = self._native_navigation
        if request.y is None and old is None:
            self._reconcile_visible_viewport()
        moved = (
            request.y is not None and max(0.0, min(request.y, scroll.max_scroll_y)) != scroll.scroll_y
        ) or (request.x is not None and max(0.0, min(request.x, scroll.max_scroll_x)) != scroll.scroll_x)
        anchor = old.anchor if old is not None else self._reading_anchor
        follows = old.follows_bottom if old is not None else not self._reading
        if request.y is not None:
            target = max(0.0, min(request.y, scroll.max_scroll_y))
            follows = request.bottom or scroll.max_scroll_y - target <= 1.0
            anchor = None if follows else self._destination_anchor(target_y=target)
            self._reading = not follows
            self._back_scroll_mode = not follows
        elif old is not None and old.request.y is not None:
            request = replace(request, y=old.request.y, bottom=old.follows_bottom)
        hold_y = self._anchor_target(anchor=anchor) if request.y is None and anchor is not None else None
        self._viewport_revision += 1
        self._invalidate_navigation()
        self._reading_anchor = None
        if anchor is not None:
            anchor = replace(anchor, viewport_revision=self._viewport_revision)
        token = _ViewportTokenDAO(generation=self._generation, revision=self._viewport_revision)
        self._native_navigation = _NativeNavigationDAO(
            token=token, request=request, anchor=anchor, follows_bottom=follows, pending_axes=set()
        )
        if hold_y is not None:
            self._hold_horizontal_viewport(target_y=hold_y)
        if request.immediate:
            self._start_native_navigation(token=token)
        else:
            self.call_after_refresh(self._start_native_navigation, token=token)
        return moved

    def _start_native_navigation(self, *, token: _ViewportTokenDAO) -> None:
        """Start both requested axes together with Textual's single native animator."""
        if not self._navigation_is_current(token=token):
            return
        operation = self._native_navigation
        assert operation is not None
        request = operation.request
        scroll = self._transcript_scroll
        x = None if request.x is None else max(0.0, min(request.x, scroll.max_scroll_x))
        y = request.y
        if y is not None:
            y = (
                scroll.max_scroll_y
                if operation.follows_bottom
                else (
                    self._anchor_target(anchor=operation.anchor)
                    if operation.anchor is not None
                    else max(0.0, min(y, scroll.max_scroll_y))
                )
            )
        # Textual rounds animation targets to cells; a mid-motion page request
        # can be fractional. Completion must compare against the target it runs.
        if request.animate:
            x = round(x) if x is not None else None
            y = round(y) if y is not None else None
        operation.request = replace(request, x=x, y=y)
        operation.started = True
        operation.pending_axes = {
            axis
            for axis, target, current in (("x", x, scroll.scroll_x), ("y", y, scroll.scroll_y))
            if target is not None and target != current
        }
        scroll._owner_scroll = True
        try:
            scroll._scroll_to(
                x=x,
                y=y,
                animate=request.animate,
                duration=request.duration,
                release_anchor=request.release_anchor,
                on_complete=partial(self._native_navigation_completed, token=token),
            )
        finally:
            scroll._owner_scroll = False
        # Covers nonanimated, denied and no-movement requests; actual movement waits for callbacks.
        self.call_after_refresh(self._native_navigation_completed, token=token)

    def _native_navigation_completed(self, *, token: _ViewportTokenDAO) -> None:
        """Retire reached axes only; duplicate and old native callbacks are harmless."""
        if not self._navigation_is_current(token=token):
            return
        operation = self._native_navigation
        assert operation is not None
        scroll = self._transcript_scroll
        for axis, target, current, maximum, allowed in (
            ("x", operation.request.x, scroll.scroll_x, scroll.max_scroll_x, scroll.allow_horizontal_scroll),
            ("y", operation.request.y, scroll.scroll_y, scroll.max_scroll_y, scroll.allow_vertical_scroll),
        ):
            if target is not None and (not allowed or abs(current - max(0.0, min(target, maximum))) <= 0.01):
                operation.pending_axes.discard(axis)
        if operation.pending_axes or operation.settlement_queued:
            return
        operation.settlement_queued = True
        self.call_after_refresh(self._settle_native_navigation, token=token)

    def _settle_native_navigation(self, *, token: _ViewportTokenDAO) -> None:
        """After final layout preserve destination displacement or the newest bottom."""
        if not self._navigation_is_current(token=token):
            return
        operation = self._native_navigation
        assert operation is not None
        self._native_navigation = None
        self._reading_anchor = operation.anchor
        if operation.follows_bottom:
            self._queue_follow_pin()
        elif operation.anchor is not None:
            self._restore_reading_anchor(anchor=operation.anchor)
        self._enforce_window_soon()

    def _before_programmatic_scroll(self) -> None:
        """Revoke native completion before focus/layout scroll can force-stop it."""
        operation = self._native_navigation
        if operation is None:
            return
        self._reading_anchor = operation.anchor
        self._reading = not operation.follows_bottom
        self._hidden_following = operation.follows_bottom
        self._invalidate_navigation()
        token = _ViewportTokenDAO(generation=self._generation, revision=self._viewport_revision)
        self.call_after_refresh(self._queue_programmatic_settlement, token=token)

    def _queue_programmatic_settlement(self, *, token: _ViewportTokenDAO) -> None:
        """Wait another layout boundary so a deferred focus-scroll has executed first."""
        self.call_after_refresh(self._settle_programmatic_scroll, token=token)

    def _settle_programmatic_scroll(self, *, token: _ViewportTokenDAO) -> None:
        """Settle interrupted intent after layout unless a newer input/hide/reset won."""
        if (
            token != _ViewportTokenDAO(generation=self._generation, revision=self._viewport_revision)
            or not self._visible
            or not self._geometry_ready
            or self._presentation_closed
            or not self.is_attached
            or self._native_navigation is not None
        ):
            return
        if self._reading_anchor is not None:
            self._restore_reading_anchor(anchor=self._reading_anchor)
        elif not self._reading:
            self._queue_follow_pin()

    def _capture_follow_snapshot(self) -> FollowSnapshotDAO:
        """Capture intent once before mutation, retaining reading geometry when available."""
        if self._presentation_closed or not self.is_attached:
            return FollowSnapshotDAO()
        if self._native_navigation is not None:
            following = self._native_navigation.follows_bottom
        else:
            self._retain_reading_anchor()
            following = not self._reading and (
                self._hidden_following
                if not self._visible or not self._geometry_ready
                else self._force_following_until_layout
                or self._transcript_scroll.max_scroll_y - self._transcript_scroll.scroll_y <= 1.0
            )
        return FollowSnapshotDAO(
            was_following=following,
            presentation_generation=self._generation,
            viewport_revision=self._viewport_revision,
        )

    def _widget_follow_reader(self) -> Callable[[], FollowSnapshotDAO]:
        """Bind a widget's construction generation without exposing owner state."""
        generation = self._generation

        def capture() -> FollowSnapshotDAO:
            """Reject an old timer even before queued removal completes."""
            return self._capture_follow_snapshot() if generation == self._generation else FollowSnapshotDAO()

        return capture

    def _finish_viewport_mutation(self, *, snapshot: FollowSnapshotDAO) -> None:
        """Apply only current intent; native navigation retains exclusive movement authority."""
        if (
            snapshot.presentation_generation != self._generation
            or snapshot.viewport_revision != self._viewport_revision
            or self._presentation_closed
            or not self.is_attached
            or not self._visible
            or self._native_navigation is not None
        ):
            return
        if snapshot.was_following and not self._reading:
            self._queue_follow_pin()
        elif self._reading_anchor is not None:
            self.call_after_refresh(self._restore_reading_anchor, anchor=self._reading_anchor)

    def on_assistant_stream_block_rendered(self, message: AssistantStreamBlock.Rendered) -> None:
        """Consume exact child intent, refusing detached or foreign sources."""
        message.stop()
        if message.source.is_attached and self in message.source.ancestors:
            self._finish_viewport_mutation(snapshot=message.snapshot)

    def _queue_follow_pin(self) -> None:
        """Coalesce a bottom correction after a current following mutation."""
        if self._presentation_closed or self._reading or self._native_navigation is not None:
            return
        self._hidden_following = True
        self._force_following_until_layout = True
        if not self._visible or not self._geometry_ready:
            return
        if self._active_pin is not None:
            self._follow_pin_dirty = True
            return
        self._pin_sequence += 1
        token = (self._generation, self._viewport_revision, self._pin_sequence)
        self._active_pin = token
        self._follow_pin_dirty = False
        self.call_after_refresh(self._land_follow_pin, token=token)

    def _pin_is_current(self, *, token: tuple[int, int, int]) -> bool:
        """Reject callbacks after reading, hide, reset, teardown or replacement."""
        return (
            self._active_pin == token
            and token[:2] == (self._generation, self._viewport_revision)
            and self._visible
            and self._geometry_ready
            and self.is_attached
            and not self._presentation_closed
            and not self._reading
            and self._native_navigation is None
        )

    def _land_follow_pin(self, *, token: tuple[int, int, int]) -> None:
        """Land only this pin after layout; release on a later layout boundary."""
        if not self._pin_is_current(token=token):
            return
        self._follow_pin_dirty = False
        self._transcript_scroll.scroll_to(
            y=self._transcript_scroll.max_scroll_y, animate=False, immediate=True
        )
        self.call_after_refresh(self._release_follow_pin, token=token)

    def _release_follow_pin(self, *, token: tuple[int, int, int]) -> None:
        """Release the exact pin, or reland once more if a real mutation intervened."""
        if not self._pin_is_current(token=token):
            return
        if self._follow_pin_dirty:
            self.call_after_refresh(self._land_follow_pin, token=token)
            return
        self._active_pin = None
        self._force_following_until_layout = False

    def scroll_to_bottom(self) -> None:
        """Honor explicit user intent, including while hidden."""
        self._viewport_revision += 1
        self._invalidate_navigation()
        self._reading_anchor = None
        self._reading = False
        self._back_scroll_mode = False
        self._hidden_following = True
        self._queue_follow_pin()
        self._enforce_window_soon()

    async def hydrate(self) -> None:
        """Read the newest history once before subscription, without durable writes.

        Read errors leave boot usable. Projection errors propagate to the caller;
        cancellation joins the borrowed read operation before propagating.
        """
        async with self._hydration_lock:
            if self._hydrated or self._presentation_closed or not self.is_attached:
                return
            generation = self._generation
            entries = await self._read_history()
            if entries is None:
                return
            async with self._mutation_lock:
                if generation != self._generation or self._presentation_closed or not self.is_attached:
                    return
                await self._present_history_tail(entries=entries)

    async def _invoke_history_reader(self) -> list[TranscriptEntryDAO]:
        """Adapt the borrowed Awaitable contract to a tracked coroutine task."""
        return await self._history_reader()

    async def _read_history(self) -> Optional[list[TranscriptEntryDAO]]:
        """Track and join the initial reader, treating only read failure as empty boot."""
        task: asyncio.Task[list[TranscriptEntryDAO]] = asyncio.create_task(self._invoke_history_reader())
        self._read_task = task
        try:
            return await task
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        except Exception:
            return None
        finally:
            if self._read_task is task:
                self._read_task = None

    async def _present_history_tail(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Publish the bounded canonical tail; cursor counts entries, never widgets."""
        snapshot = self._capture_follow_snapshot()
        # A partial publication is retained. Only clear/bind may admit replay again;
        # retrying this tail in-place would duplicate the already mounted prefix.
        self._hydrated = True
        tail = entries[-TRANSCRIPT_HYDRATION_ENTRY_LIMIT:]
        for entry in tail:
            await self._projector.project_replay_entry(entry=entry)
        self._load_older_cursor = len(entries) - len(tail)
        self._hydrated = True
        await self._update_earlier_summary()
        self._finish_viewport_mutation(snapshot=snapshot)

    async def load_older(self) -> None:
        """Join one older read/publication; failures preserve the current mounted prefix.

        Concurrent requests join the same task. Read failures remain retryable;
        partial projection failures require clear or resume, never automatic replay.
        """
        if self._presentation_closed or not self.is_attached or not self._visible:
            return
        if self._older_task is None and self._load_older_cursor > 0 and not self._older_projection_failed:
            self._older_task = asyncio.create_task(self._load_older(generation=self._generation))
        task = self._older_task
        if task is not None:
            await asyncio.shield(task)

    def on_transcript_scroll_reached_top(self, event: TranscriptScroll.ReachedTop) -> None:
        """Start one retained UI task from a native top crossing."""
        event.stop()
        if self._older_task is not None or self._load_older_cursor <= 0 or self._older_projection_failed:
            return
        if self._presentation_closed or not self.is_attached or not self._visible:
            return
        self._older_task = asyncio.create_task(self._load_older(generation=self._generation))

    async def _load_older(self, *, generation: int) -> None:
        """Serialize readers, then validate their captured cursor before publication."""
        try:
            async with self._hydration_lock:
                cursor = self._load_older_cursor
                entries = await self._read_history()
                if not entries:
                    return
                batch = entries[max(0, cursor - LOAD_OLDER_BATCH_SIZE) : cursor]
                async with self._mutation_lock:
                    if generation != self._generation or cursor != self._load_older_cursor:
                        return
                    if self._presentation_closed or not self.is_attached or not batch:
                        return
                    await self._publish_older(entries=batch)
        finally:
            if self._older_task is asyncio.current_task():
                self._older_task = None

    async def _publish_older(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Retain partial output on projection failure; commit cursor only on success."""
        self._back_scroll_mode = True
        self._reading = True
        snapshot = self._capture_follow_snapshot()
        try:
            await self._prepend_older_entries(entries=entries)
        except Exception as error:
            self._older_projection_failed = True
            log_warning("transcript_older_projection_failed", error_class=type(error).__name__)
            self.write_transcript_line(
                content="Earlier messages could not be displayed; resume this session to reload history.",
                classes="tool-result",
            )
        else:
            self._load_older_cursor -= len(entries)
        await self._update_earlier_summary()
        self._finish_viewport_mutation(snapshot=snapshot)

    async def _prepend_older_entries(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Insert before one stable child, unaffected by synchronous tail notices."""
        children = self._ordinary_children()
        boundary = children[0] if children else Static("", classes="transcript-prepend-boundary")
        temporary = not children
        if temporary:
            await self._transcript_content.mount(boundary)
        try:
            for entry in entries:
                before = list(self._transcript_content.children).index(boundary)
                await self._projector.project_replay_entry(entry=entry, before=before)
        finally:
            if temporary:
                await boundary.remove()

    def _ordinary_children(self) -> list[Widget]:
        """Exclude presentation markers and exceptional scroll siblings from accounting."""
        return [
            child
            for child in self._transcript_content.children
            if child is not self._earlier_summary and not child.has_class("transcript-prepend-boundary")
        ]

    async def _update_earlier_summary(self) -> None:
        """Show reachable logical entries, never infer a cursor from evicted widgets."""
        if (
            not self._older_projection_failed
            and not self._load_older_cursor
            and (not self._hidden_block_count or self._back_scroll_mode)
        ):
            summary, self._earlier_summary = self._earlier_summary, None
            if summary is not None:
                await summary.remove()
            return
        text = self._earlier_summary_text()
        if self._earlier_summary is None:
            self._earlier_summary = LiteralTextStatic(text, id="transcript-earlier-summary")
            await self._transcript_content.mount(self._earlier_summary, before=0)
        else:
            self._earlier_summary.update(text)

    def _earlier_summary_text(self) -> str:
        """Give partial projection precedence over the otherwise reachable cursor."""
        if self._older_projection_failed:
            return "▲ earlier messages partially displayed — resume this session to reload history"
        if self._load_older_cursor:
            return (
                f"▲ {self._load_older_cursor} earlier messages hidden "
                "— scroll to the top to load older messages"
            )
        return "▲ earlier messages collapsed — resume this session to recover them"

    def begin_run(self) -> None:
        """Reset projector identity maps after the caller has serialized prompt admission."""
        self._projector.reset_for_new_run()

    async def echo_user(self, *, text: str) -> None:
        """Display accepted input without submitting or persisting it.

        Args:
            text: Already accepted prompt text owned by the caller.
        """
        async with self._lifecycle_lock:
            if self._presentation_closed or not self.is_attached:
                return
            async with self._mutation_lock:
                self.scroll_to_bottom()
                snapshot = self._capture_follow_snapshot()
                await self._projector.project_user_turn(text=text)
                self._finish_viewport_mutation(snapshot=snapshot)

    async def present_event(self, *, event: AgentStreamEventDAO) -> None:
        """Project an app-routed parent event; projection failures propagate.

        Args:
            event: Normalized parent event; callers retain child/status routing.
        """
        async with self._lifecycle_lock:
            if self._presentation_closed or not self.is_attached:
                return
            async with self._mutation_lock:
                snapshot = self._capture_follow_snapshot()
                await self._project_parent_event(event=event)
                self._finish_viewport_mutation(snapshot=snapshot)
                self._enforce_window_soon()

    async def _project_parent_event(self, *, event: AgentStreamEventDAO) -> None:
        """Consume pending steering FIFO; retain the existing parent projector otherwise."""
        if event.kind != "steering_applied":
            await self._projector.project(event=event)
            return
        if self._pending_steer_blocks:
            await self._pending_steer_blocks.pop(0).remove()
        await self._projector.project_user_turn(text=event.content or "")

    async def show_pending_steering(self, *, message: str) -> None:
        """Display accepted steering without owning its execution queue."""
        async with self._lifecycle_lock:
            if self._presentation_closed or not self.is_attached:
                return
            async with self._mutation_lock:
                snapshot = self._capture_follow_snapshot()
                block = SteeringPendingBlock(message=message)
                await self._transcript_content.mount(block)
                self._pending_steer_blocks.append(block)
                self._finish_viewport_mutation(snapshot=snapshot)
                self._enforce_window_soon()

    async def mount_tree_output(self, *, widget: Widget) -> None:
        """Mount already-exported tree output outside ordinary transcript accounting."""
        async with self._lifecycle_lock:
            if self._presentation_closed or not self.is_attached:
                return
            async with self._mutation_lock:
                snapshot = self._capture_follow_snapshot()
                await self._transcript_scroll.mount(widget)
                self._finish_viewport_mutation(snapshot=snapshot)

    def set_visible(self, *, visible: bool) -> None:
        """Retain the mounted surface and output without deciding app focus or execution.

        Retain reading coordinates across hidden mutations and restore only after
        visible layout; this boundary never reads hidden geometry.
        """
        if self._presentation_closed or self._visible == visible:
            return
        if not visible:
            if self._native_navigation is None and self._has_visible_geometry():
                self._reconcile_visible_viewport()
            snapshot = self._capture_follow_snapshot()
            self._hidden_following = snapshot.was_following
            if self._native_navigation is not None:
                self._reading_anchor = self._native_navigation.anchor
            self._invalidate_navigation()
        self._viewport_revision += 1
        self._active_pin = None
        self._force_following_until_layout = False
        if self._reading_anchor is not None:
            self._reading_anchor = replace(self._reading_anchor, viewport_revision=self._viewport_revision)
        self._geometry_ready = False
        self._visible = visible
        self.display = visible
        if visible:
            self.call_after_refresh(
                self._resume_visible_layout, token=(self._generation, self._viewport_revision)
            )
            self._enforce_window_soon()

    def toggle_expandable_details(self) -> None:
        """Cycle natural to expanded/collapsed without touching exceptional siblings."""
        snapshot = self._capture_follow_snapshot()
        self._global_expand_all = not bool(self._global_expand_all)
        for child in self._ordinary_children():
            if isinstance(child, (UserMessageBlock, ToolExecutionBlock, AssistantStreamThinkingBlock)):
                child.set_expanded(expanded=self._global_expand_all)
        self._finish_viewport_mutation(snapshot=snapshot)

    def _enforce_window_soon(self) -> None:
        """Coalesce mounts into one retained task; never await it under mutation lock."""
        if self._presentation_closed or not self.is_attached:
            return
        if len(self._ordinary_children()) <= TRANSCRIPT_WINDOW_SIZE:
            return
        self._window_enforcement_rerun = True
        if self._window_task is None:
            self._window_task = asyncio.create_task(
                self._run_window_enforcement_pass(generation=self._generation)
            )

    async def _run_window_enforcement_pass(self, *, generation: int) -> None:
        """Repeat only for new mutation requests, not for protected saturation."""
        try:
            while self._window_enforcement_rerun:
                self._window_enforcement_rerun = False
                async with self._mutation_lock:
                    if generation != self._generation or self._presentation_closed or not self.is_attached:
                        return
                    await self._evict_settled_prefix()
        except Exception as error:
            log_warning("transcript_window_failed", error_class=type(error).__name__)
        finally:
            if self._window_task is asyncio.current_task():
                self._window_task = None

    async def _evict_settled_prefix(self) -> None:
        """Protect the newest ten and all live blocks; cursor never grows on eviction."""
        if self._back_scroll_mode or not self._visible or self._reading_anchor is not None or self._reading:
            return
        children = self._ordinary_children()
        overflow = len(children) - TRANSCRIPT_WINDOW_SIZE
        for child in children[:-TRANSCRIPT_PROTECTED_TAIL_SIZE]:
            if overflow <= 0:
                break
            if self._is_block_live(child=child):
                continue
            self._hidden_block_count += 1
            overflow -= 1
            await child.remove()
        await self._update_earlier_summary()

    def _is_block_live(self, *, child: Widget) -> bool:
        """Keep answer, thinking, pending-tool and pending-steer lifecycle truth intact."""
        if isinstance(child, (AssistantStreamBlock, AssistantStreamThinkingBlock)):
            return not child.finalized
        if isinstance(child, ToolExecutionBlock):
            return child.result_output is None and not child.is_incomplete
        return child in self._pending_steer_blocks

    async def clear(self) -> None:
        """Join old presentation work and clear content without cancelling execution."""
        task = asyncio.create_task(self._reset_presentation(history_reader=None, close=False))
        await self._join_cleanup(task=task)

    async def bind_history(self, *, history_reader: HistoryReader) -> None:
        """Clear the old lifetime before adopting the caller's replacement reader.

        Args:
            history_reader: Borrowed canonical replay operation for the new session.
        """
        task = asyncio.create_task(self._reset_presentation(history_reader=history_reader, close=False))
        await self._join_cleanup(task=task)

    async def close(self) -> None:
        """Seal UI admission and join cleanup, including across caller cancellation."""
        task = asyncio.create_task(self._reset_presentation(history_reader=None, close=True))
        await self._join_cleanup(task=task)

    async def _reset_presentation(self, *, history_reader: Optional[HistoryReader], close: bool) -> None:
        """Serialize invalidation, reader settlement and removal at the lifecycle boundary."""
        async with self._lifecycle_lock:
            if self._presentation_closed:
                return
            self._generation += 1
            self._viewport_revision += 1
            self._presentation_closed = close
            self._invalidate_navigation()
            self._reading_anchor = None
            self._active_pin = None
            self._force_following_until_layout = False
            self._reading = False
            self._hidden_following = True
            tasks = [
                task for task in (self._older_task, self._read_task, self._window_task) if task is not None
            ]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            async with self._mutation_lock:
                old_children = tuple(self._transcript_content.children)
                self._adapter.lines.clear()
                self._projector.reset_for_new_run()
                self._load_older_cursor = 0
                self._hydrated = False
                self._older_projection_failed = False
                self._earlier_summary = None
                self._hidden_block_count = 0
                self._back_scroll_mode = False
                self._pending_steer_blocks.clear()
                self._active_expandable_tool_block = None
                for child in old_children:
                    await child.remove()
                if history_reader is not None:
                    self._history_reader = history_reader

    async def _join_cleanup(self, *, task: asyncio.Task[None]) -> None:
        """Propagate caller cancellation only after the retained cleanup has settled."""
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def on_unmount(self) -> None:
        """Join owned read work when Textual finally removes this component."""
        await self.close()

    def logical_copy_text(self) -> str:
        """Return incomplete logical append-order text, excluding turn separators."""
        return "\n".join(text for text, classes in self._adapter.lines if classes != "turn-separator")

    async def mount_user_message_block(self, *, text: str, before: Optional[int] = None) -> UserMessageBlock:
        """Mount accepted or replayed user text for the existing projector."""
        block = UserMessageBlock(text=text)
        await self._mount_transcript_widget(block=block, before=before)
        return block

    def mount_turn_separator_if_needed(self, *, before: Optional[int] = None) -> bool:
        """Separate turns only when non-separator logical content already exists."""
        if not self._adapter.has_prior_turn_content():
            return False
        self.write_transcript_line(
            content=TranscriptNoticeDisplayAdapter.TURN_SEPARATOR, classes="turn-separator", before=before
        )
        return True

    async def mount_assistant_block(
        self, *, title_prefix: Optional[str] = None, before: Optional[int] = None
    ) -> AssistantStreamBlock:
        """Mount an answer block for live or canonical replay projection."""
        block = AssistantStreamBlock(title_prefix=title_prefix, follow_snapshot=self._widget_follow_reader())
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def mount_thinking_block(self, *, before: Optional[int] = None) -> AssistantStreamThinkingBlock:
        """Mount a separate reasoning segment, retaining projector-owned identity."""
        block = AssistantStreamThinkingBlock(
            force_expanded=self._global_expand_all, follow_snapshot=self._widget_follow_reader()
        )
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def mount_tool_execution_block(
        self, *, tool_call_id: str, tool_name: Optional[str], before: Optional[int] = None
    ) -> ToolExecutionBlock:
        """Mount one tool call/result surface at the projector's insertion position."""
        block = ToolExecutionBlock(
            tool_call_id=tool_call_id, tool_name=tool_name, force_expanded=self._global_expand_all
        )
        if before is None:
            if self._active_expandable_tool_block is not None:
                self._active_expandable_tool_block.set_active(active=False)
            self._active_expandable_tool_block = block
            block.set_active(active=True)
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def _mount_transcript_widget(self, *, block: Widget, before: Optional[int] = None) -> None:
        """Mount under the caller's mutation admission, then request non-reentrant eviction."""
        snapshot = self._capture_follow_snapshot()
        await self._transcript_content.mount(block, before=before)
        self._finish_viewport_mutation(snapshot=snapshot)
        self._enforce_window_soon()

    def write_transcript_line(self, *, content: str, classes: str, before: Optional[int] = None) -> None:
        """Admit synchronous notices only while the destination remains attached."""
        if self._presentation_closed or not self.is_attached:
            return
        self._adapter.write(content=content, classes=classes, before=before)

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        """Record already-rendered text without duplicating its visible widget."""
        if self._presentation_closed or not self.is_attached:
            return
        self._adapter.record(content=content, classes=classes)

    def _transcript_write(self, *, line: str, style_class: str, before: Optional[int] = None) -> None:
        """Schedule one admitted plain notice; adapter owns its logical record."""
        widget = (
            Static(Markdown(line), classes=style_class)
            if style_class == "assistant-final"
            else LiteralTextStatic(line, classes=style_class)
        )
        snapshot = self._capture_follow_snapshot()
        self._transcript_content.mount(widget, before=before)
        # Queue on the new widget: the owner's refresh may precede this pending
        # mount and consume a reading anchor against pre-mount geometry.
        widget.call_after_refresh(self._finish_viewport_mutation, snapshot=snapshot)
        self._enforce_window_soon()
