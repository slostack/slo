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
from src.tui.components.chat_transcript.commands import (
    EchoUserDAO,
    ProjectUserTurnDAO,
    ProjectReplayEntryDAO,
    PresentMessageApplicationDAO,
    RetireHistoryBindingDAO,
    TranscriptCommand,
    PresentAgentEventDAO,
    HydrateTranscriptDAO,
    BindHistoryDAO,
    ClearTranscriptDAO,
    BeginTranscriptRunDAO,
    LoadOlderHistoryDAO,
    ShowPendingSteeringDAO,
    MountTreeOutputDAO,
    SetTranscriptVisibilityDAO,
    ScrollTranscriptBottomDAO,
    ToggleTranscriptDetailsDAO,
    ScrollCommand,
    SetScrollPositionDAO,
    TranscriptNoticeDAO,
)
from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
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
    transcript_version: int
    viewport_revision: int


@dataclass(frozen=True)
class _ViewportTokenDAO:
    """Identify deferred work in one content and viewport lifetime."""

    transcript_version: int
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


# component.py — TranscriptScrollComponent implementation (one constructor).
# Imports: textual._animator.EasingFunction; textual._types.AnimationLevel;
# textual.messages.CallbackType; textual.events; textual.actions.SkipAction;
# textual.scrollbar.ScrollUp/ScrollDown/ScrollLeft/ScrollRight/ScrollTo.
class TranscriptScrollComponent(VerticalScroll):
    """Handle scrolling inside the chat transcript.

    Turn mouse and keyboard input into scroll movements, and ignore delayed
    scroll requests that are no longer valid. ChatTranscriptComponent decides
    when to follow new messages or keep the reader's current position."""

    def __init__(
        self, *, navigate: Callable[[_NativeScrollRequestDAO], bool], interrupt: Callable[[], None], id: str
    ) -> None:
        """Save the parent callbacks and prepare scrolling without starting any work."""
        super().__init__(id=id)
        self._navigate = navigate
        self._interrupt = interrupt
        self._owner_scroll: bool = False
        self._scroll_epoch: int = 0
        self._delivery_closed = False

    async def handle(self, *, command: ScrollCommand) -> None:
        """Apply a scroll command on the UI loop. Reject unknown commands and calls after close."""
        self._ensure_scroll_open()
        self._ensure_scroll_attached()
        self._ensure_scroll_ui_loop()
        if not isinstance(command, SetScrollPositionDAO):
            raise TypeError(f"Unsupported scroll command: {type(command).__name__}")
        self.scroll_to(x=command.x, y=command.y, animate=False, immediate=True)

    def _ensure_scroll_open(self) -> None:
        """Reject closed scroll delivery before native attachment or loop checks."""
        if self._delivery_closed:
            raise RuntimeError("Transcript scroll is closed")

    def _ensure_scroll_attached(self) -> None:
        """Require native attachment before accessing the scroll's application."""
        if not self.is_attached:
            raise RuntimeError("Scroll delivery requires the mounted UI loop")

    def _ensure_scroll_ui_loop(self) -> None:
        """Raise RuntimeError unless mutation runs on the mounted owner's loop."""
        if asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("Scroll delivery requires the mounted UI loop")

    async def reset(self) -> None:
        """Cancel pending scroll requests and stop movement, keeping the parent callbacks."""
        self._ensure_scroll_open()
        self._ensure_scroll_attached()
        self._ensure_scroll_ui_loop()
        self._retire_scroll()

    def _retire_scroll(self) -> None:
        """Cancel pending scroll starts before stopping the current animation."""
        self.invalidate_deferred_scrolls()
        if self.is_attached:
            self.app.animator.force_stop_animation(obj=self, attribute="scroll_x")
            self.app.animator.force_stop_animation(obj=self, attribute="scroll_y")

    async def close(self) -> None:
        """Stop scrolling without closing anything owned by the parent; repeated calls are safe."""
        self._delivery_closed = True
        self._retire_scroll()

    async def on_unmount(self) -> None:
        """Run the same cleanup as close when Textual removes this widget."""
        await self.close()

    class ReachedTop(Message):
        """Report a crossing into the top band, not every geometry update."""

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Run Textual’s scroll handling, then report when scrolling reaches the top."""
        super().watch_scroll_y(old_value=old_value, new_value=new_value)
        if not self._delivery_closed and new_value <= 2 < old_value:
            self.post_message(self.ReachedTop())

    def invalidate_deferred_scrolls(self) -> None:
        """Make earlier scheduled scroll requests invalid before stopping movement."""
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
        """Ignore outdated scroll requests before Textual stops movement on both axes."""
        if (
            self._delivery_closed
            or not self.is_attached
            or any(not node.display for node in (self, *self.ancestors))
        ):
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
        """Use Textual’s normal scrolling unless newer user input has replaced this request."""
        if (
            self._delivery_closed
            or not self.is_attached
            or any(not node.display for node in (self, *self.ancestors))
        ):
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
            # Textual does not pass release_anchor to its internal scroll method.
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
        """Handle allowed mouse-wheel movement and let the parent handle movement at an edge."""
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
        """Scroll up, or sideways when a modifier requests it, using Textual’s wheel speed."""
        self._wheel(event=event, axis="x" if event.ctrl or event.shift else "y", direction=-1, animate=False)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        """Scroll down without changing Textual’s vertical anchor."""
        self._wheel(event=event, axis="x" if event.ctrl or event.shift else "y", direction=1, animate=False)

    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        """Scroll left using Textual’s horizontal animation."""
        self._wheel(event=event, axis="x", direction=-1, animate=True)

    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        """Scroll right using Textual’s horizontal animation."""
        self._wheel(event=event, axis="x", direction=1, animate=True)

    def _step(self, *, axis: str, direction: int, page: bool) -> None:
        """Move by a row or page. Let the parent handle actions disabled here."""
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
        """Handle one upward click on the scrollbar track."""
        event.prevent_default()
        if self.allow_vertical_scroll:
            self._step(axis="y", direction=-1, page=True)
            event.stop()

    def _on_scroll_down(self, event: ScrollDown) -> None:
        """Handle one downward click on the scrollbar track."""
        event.prevent_default()
        if self.allow_vertical_scroll:
            self._step(axis="y", direction=1, page=True)
            event.stop()

    def _on_scroll_left(self, event: ScrollLeft) -> None:
        """Handle one leftward click on the scrollbar track."""
        event.prevent_default()
        if self.allow_horizontal_scroll:
            self._step(axis="x", direction=-1, page=True)
            event.stop()

    def _on_scroll_right(self, event: ScrollRight) -> None:
        """Handle one rightward click on the scrollbar track."""
        event.prevent_default()
        if self.allow_horizontal_scroll:
            self._step(axis="x", direction=1, page=True)
            event.stop()

    def _on_scroll_to(self, message: ScrollTo) -> None:
        """Scroll to the dragged scrollbar position. Leave vertical position alone when y is None."""
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
        """Scroll to the start, keeping Textual’s rules for resetting horizontal position."""
        if not self._allow_scroll:
            raise SkipAction()
        self._navigate(_NativeScrollRequestDAO(x=0.0 if self.scroll_y == 0 else None, y=0.0, duration=1.0))

    def action_scroll_end(self) -> None:
        """Scroll to the end after layout, keeping Textual’s horizontal and anchor rules."""
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


class ChatTranscriptComponent(Vertical):
    """Display chat history and live messages in the conversation area.

    Load older messages when needed, keep messages in order, and manage the
    visible message widgets and scroll position. Read saved history through
    the supplied reader without owning or deleting that saved history."""

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.chat_transcript").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    def __init__(self, *, history_reader: HistoryReader) -> None:
        """Prepare the transcript without reading history or listening for events."""
        super().__init__(id="chat-transcript")
        self._history_reader = history_reader
        self._transcript_scroll = TranscriptScrollComponent(
            navigate=self._navigate_native,
            interrupt=self._before_programmatic_scroll,
            id="transcript-scroll",
        )
        self._transcript_content = Vertical(id="transcript-content")
        self._adapter = TranscriptNoticeDisplayAdapter.register(tui=self)
        self.workflow_notice = WorkflowNoticeAdapter.register(tui=self)
        self._projector = TranscriptProjectionAdapter.register(host=self)
        self._load_older_cursor: int = 0
        self._hydrated: bool = False
        self._transcript_version: int = 0
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
        # Stored locks are synchronization resources, not ownership predicates.
        # Native async-with acquisition/release preserves cancellation semantics.
        self._hydration_lock = asyncio.Lock()
        self._presentation_closed: bool = False
        self._cleanup_complete = False
        self._delivery_closing = False
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

    async def handle(self, *, command: TranscriptCommand) -> None:
        """Apply a supported command on the mounted UI loop and report any display failure."""
        self._ensure_transcript_open()
        self._ensure_transcript_attached()
        self._ensure_transcript_ui_loop()
        transcript_version = self._get_transcript_version()
        match command:
            case TranscriptNoticeDAO():
                async with self._lifecycle_lock:
                    self._ensure_current_transcript_version(expected_version=transcript_version)
                    async with self._mutation_lock:
                        await self._adapter.handle(event=command)
            case PresentMessageApplicationDAO():
                await self.present_message_application(entry=command.entry)
            case EchoUserDAO():
                await self.echo_user(text=command.text)
            case PresentAgentEventDAO():
                await self.present_event(event=command.event)
            case HydrateTranscriptDAO():
                await self.hydrate(is_current=command.is_current)
            case BindHistoryDAO():
                await self.bind_history(history_reader=command.history_reader)
            case ClearTranscriptDAO():
                await self.reset()
            case (
                BeginTranscriptRunDAO()
                | SetTranscriptVisibilityDAO()
                | ScrollTranscriptBottomDAO()
                | ToggleTranscriptDetailsDAO()
            ):
                async with self._lifecycle_lock:
                    self._ensure_current_transcript_version(expected_version=transcript_version)
                    async with self._mutation_lock:
                        await self._present_control(command=command)
            case LoadOlderHistoryDAO():
                await self.load_older()
            case ShowPendingSteeringDAO():
                await self.show_pending_steering(message=command.message)
            case MountTreeOutputDAO():
                await self.mount_tree_output(widget=command.widget)
            case _:
                raise TypeError(f"Unsupported transcript command: {type(command).__name__}")

    async def _present_control(
        self,
        *,
        command: (
            BeginTranscriptRunDAO
            | SetTranscriptVisibilityDAO
            | ScrollTranscriptBottomDAO
            | ToggleTranscriptDetailsDAO
        ),
    ) -> None:
        """Apply a display command while holding permission to change the transcript."""
        match command:
            case BeginTranscriptRunDAO():
                await self._projector.reset()
            case SetTranscriptVisibilityDAO():
                self.set_visible(visible=command.visible)
            case ScrollTranscriptBottomDAO():
                self.scroll_to_bottom()
            case ToggleTranscriptDetailsDAO():
                self.toggle_expandable_details()

    def _ensure_transcript_open(self) -> None:
        """Reject closed transcript delivery before native attachment or loop checks."""
        if self._presentation_closed or self._delivery_closing:
            raise RuntimeError("Transcript is closed")

    def _ensure_transcript_attached(self) -> None:
        """Require native attachment before accessing the transcript's application."""
        if not self.is_attached:
            raise RuntimeError("Transcript delivery requires the mounted UI loop")

    def _ensure_transcript_ui_loop(self) -> None:
        """Raise RuntimeError unless mutation runs on the mounted owner's loop."""
        if asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("Transcript delivery requires the mounted UI loop")

    def _get_transcript_version(self) -> int:
        """Return the presentation lifetime captured by callbacks and admitted commands."""
        return self._transcript_version

    def _update_transcript_version(self) -> None:
        """Retire saved transcript work before reset/rebinding clears presentation state."""
        self._transcript_version += 1

    def _is_transcript_version(self, *, expected_version: int) -> bool:
        """Compare a saved lifetime without changing state or checking mount/loop admission."""
        return expected_version == self._transcript_version

    def _ensure_current_transcript_version(self, *, expected_version: int) -> None:
        """Require an admitted command's transcript lifetime after an awaited lock.

        Args:
            expected_version: Version captured before waiting, not an LLM iteration.

        Raises:
            RuntimeError: Closed delivery first, then attachment/loop mismatch,
                then a retired transcript version. This precedence is intentional.
        """
        self._ensure_transcript_open()
        self._ensure_transcript_attached()
        self._ensure_transcript_ui_loop()
        if not self._is_transcript_version(expected_version=expected_version):
            raise RuntimeError("Transcript delivery belongs to a retired presentation")

    async def reset(self) -> None:
        """Wait for old display work to finish, then clear the view while keeping the history reader."""
        self._ensure_transcript_open()
        self._ensure_transcript_attached()
        self._ensure_transcript_ui_loop()
        await self.clear()

    def compose(self) -> ComposeResult:
        """Add the scroll area and message container once for this component."""
        with self._transcript_scroll:
            yield self._transcript_content

    def on_mount(self) -> None:
        """Wait until the component is visible and laid out before measuring it."""
        self.call_after_refresh(
            self._resume_visible_layout, token=(self._get_transcript_version(), self._viewport_revision)
        )

    def on_resize(self, event: events.Resize) -> None:
        """Keep following new messages when startup or resizing changes the available height."""
        if self._visible and not self._reading:
            self.call_after_refresh(
                self._resume_visible_layout, token=(self._get_transcript_version(), self._viewport_revision)
            )

    def _resume_visible_layout(self, *, token: tuple[int, int]) -> None:
        """Restore the saved scroll behavior only when the component is mounted and visible."""
        if (
            token[0] != self._get_transcript_version()
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

    def _get_anchor_candidates(self) -> list[Widget]:
        """Choose whole message blocks and tree output as scroll anchors, not their inner widgets."""
        return self._get_ordinary_children() + [
            child for child in self._transcript_scroll.children if child is not self._transcript_content
        ]

    def _get_scroll_content_y(self, *, widget: Widget) -> float:
        """Find a widget’s vertical position using measurements from the same rendered frame.

        The scroll offset can change before screen coordinates are refreshed. Mixing
        old coordinates with the new offset would save the wrong reading position.
        """
        if widget.parent is self._transcript_scroll:
            return float(widget.virtual_region.y)
        content = self._transcript_content
        return float(widget.region.y - content.region.y + content.virtual_region.y)

    def _build_reading_anchor(self, *, target_y: Optional[float] = None) -> Optional[_LoadOlderAnchorDAO]:
        """Save the current or requested reading position once layout is visible."""
        if not self._is_transcript_geometry_visible():
            return None
        scroll = self._transcript_scroll
        target = float(scroll.scroll_offset.y) if target_y is None else target_y
        height = scroll.scrollable_content_region.height
        candidates = sorted(
            (
                child
                for child in self._get_anchor_candidates()
                if child.is_attached and child.display and child.region.height > 0
            ),
            key=lambda child: child.region.y,
        )
        anchor = next(
            (
                child
                for child in candidates
                if self._get_scroll_content_y(widget=child) + child.region.height > target
                and self._get_scroll_content_y(widget=child) < target + height
            ),
            None,
        )
        return _LoadOlderAnchorDAO(
            widget=anchor,
            offset_before=0.0 if anchor is None else self._get_scroll_content_y(widget=anchor),
            scroll_y_before=target,
            transcript_version=self._get_transcript_version(),
            viewport_revision=self._viewport_revision,
        )

    def _update_reading_anchor(self) -> None:
        """Keep the reading position from before a content change, not a temporary animation position."""
        if self._native_navigation is None and self._reading_anchor is None and self._reading:
            self._reading_anchor = self._build_reading_anchor()

    def _restore_reading_anchor(self, *, anchor: _LoadOlderAnchorDAO) -> None:
        """Restore the saved reading position after layout, but only if it is still current."""
        if (
            self._native_navigation is not None
            or not self._visible
            or not self._geometry_ready
            or not self.is_attached
            or self._presentation_closed
            or self._reading_anchor is not anchor
            or anchor.transcript_version != self._get_transcript_version()
            or anchor.viewport_revision != self._viewport_revision
        ):
            return
        target = anchor.scroll_y_before
        widget = anchor.widget
        if (
            widget is not None
            and widget.is_attached
            and widget.display
            and widget in self._get_anchor_candidates()
        ):
            target += self._get_scroll_content_y(widget=widget) - anchor.offset_before
        self._transcript_scroll.scroll_to(
            y=max(0.0, min(target, self._transcript_scroll.max_scroll_y)), animate=False, immediate=True
        )
        self._reading_anchor = None

    # component.py — methods on ChatTranscriptComponent; imports: replace, partial.
    def _invalidate_navigation(self) -> None:
        """Invalidate old callbacks before stopping horizontal or vertical movement."""
        self._native_navigation = None
        self._active_pin = None
        self._follow_pin_dirty = False
        self._force_following_until_layout = False
        scroll = self._transcript_scroll
        scroll.invalidate_deferred_scrolls()
        if scroll.is_attached:
            scroll.app.animator.force_stop_animation(obj=scroll, attribute="scroll_x")
            scroll.app.animator.force_stop_animation(obj=scroll, attribute="scroll_y")

    def _is_navigation_current(self, *, token: _ViewportTokenDAO) -> bool:
        """Check that this scroll operation still belongs to the visible, current transcript."""
        operation = self._native_navigation
        return (
            operation is not None
            and operation.token == token
            and token
            == _ViewportTokenDAO(
                transcript_version=self._get_transcript_version(), revision=self._viewport_revision
            )
            and self._is_transcript_geometry_visible()
        )

    def _build_destination_anchor(self, *, target_y: float) -> _LoadOlderAnchorDAO:
        """Save the destination position before stopping an animation can change the measurements."""
        scroll = self._transcript_scroll
        candidates = sorted(
            (
                item
                for item in self._get_anchor_candidates()
                if item.is_attached and item.display and item.region.height > 0
            ),
            key=lambda item: self._get_scroll_content_y(widget=item),
        )
        widget = next(
            (
                item
                for item in candidates
                if self._get_scroll_content_y(widget=item) + item.region.height > target_y
                and self._get_scroll_content_y(widget=item)
                < target_y + scroll.scrollable_content_region.height
            ),
            None,
        )
        return _LoadOlderAnchorDAO(
            widget=widget,
            offset_before=0.0 if widget is None else self._get_scroll_content_y(widget=widget),
            scroll_y_before=target_y,
            transcript_version=self._get_transcript_version(),
            viewport_revision=self._viewport_revision,
        )

    def _calculate_anchor_target(self, *, anchor: _LoadOlderAnchorDAO) -> float:
        """Find the saved anchor’s position, or use the saved scroll offset if it is unavailable."""
        target = anchor.scroll_y_before
        widget = anchor.widget
        if (
            widget is not None
            and widget.is_attached
            and widget.display
            and widget in self._get_anchor_candidates()
        ):
            target += self._get_scroll_content_y(widget=widget) - anchor.offset_before
        return max(0.0, min(target, self._transcript_scroll.max_scroll_y))

    def _reconcile_visible_viewport(self) -> None:
        """Save the actual vertical reading position before horizontal input or hiding the view.

        Keep an existing request to follow the bottom. Do not start following merely
        because a reader’s current position happens to be near the bottom.
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
        # Keep the position saved before the pending layout change.
        self._update_reading_anchor()
        if self._reading_anchor is None:
            self._reading_anchor = self._build_destination_anchor(target_y=float(scroll.scroll_offset.y))

    def _hold_horizontal_viewport(self, *, target_y: float) -> None:
        """Restore the vertical position after stopping both axes for a horizontal-only scroll."""
        scroll = self._transcript_scroll
        scroll._owner_scroll = True
        try:
            scroll._scroll_to(y=max(0.0, min(target_y, scroll.max_scroll_y)), animate=False)
        finally:
            scroll._owner_scroll = False

    def _is_transcript_geometry_visible(self) -> bool:
        """Check that this widget and its parents are visible before using their sizes and positions."""
        return (
            self._visible
            and self._geometry_ready
            and self.is_attached
            and not self._presentation_closed
            and all(node.display for node in (self, *self.ancestors))
        )

    def _navigate_native(self, request: _NativeScrollRequestDAO) -> bool:
        """Handle scroll input immediately and report whether the requested direction can move."""
        if not self._is_transcript_geometry_visible():
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
            anchor = None if follows else self._build_destination_anchor(target_y=target)
            self._reading = not follows
            self._back_scroll_mode = not follows
        elif old is not None and old.request.y is not None:
            request = replace(request, y=old.request.y, bottom=old.follows_bottom)
        hold_y = (
            self._calculate_anchor_target(anchor=anchor) if request.y is None and anchor is not None else None
        )
        self._viewport_revision += 1
        self._invalidate_navigation()
        self._reading_anchor = None
        if anchor is not None:
            anchor = replace(anchor, viewport_revision=self._viewport_revision)
        token = _ViewportTokenDAO(
            transcript_version=self._get_transcript_version(), revision=self._viewport_revision
        )
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
        """Start horizontal and vertical movement together using Textual’s animator."""
        if not self._is_navigation_current(token=token):
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
                    self._calculate_anchor_target(anchor=operation.anchor)
                    if operation.anchor is not None
                    else max(0.0, min(y, scroll.max_scroll_y))
                )
            )
        # Textual rounds scroll targets to whole cells. A page request during animation
        # may use a fraction, so compare completion with the rounded target.
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
        # Finish requests with no animation or movement here; animated moves finish in callbacks.
        self.call_after_refresh(self._native_navigation_completed, token=token)

    def _native_navigation_completed(self, *, token: _ViewportTokenDAO) -> None:
        """Finish axes that reached their targets, ignoring old or repeated callbacks."""
        if not self._is_navigation_current(token=token):
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
        """After layout, keep the requested reading position or follow the latest bottom."""
        if not self._is_navigation_current(token=token):
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
        """Invalidate animation callbacks before focus or layout changes force scrolling to stop."""
        operation = self._native_navigation
        if operation is None:
            return
        self._reading_anchor = operation.anchor
        self._reading = not operation.follows_bottom
        self._hidden_following = operation.follows_bottom
        self._invalidate_navigation()
        token = _ViewportTokenDAO(
            transcript_version=self._get_transcript_version(), revision=self._viewport_revision
        )
        self.call_after_refresh(self._queue_programmatic_settlement, token=token)

    def _queue_programmatic_settlement(self, *, token: _ViewportTokenDAO) -> None:
        """Wait for layout so a scheduled focus-related scroll can finish first."""
        self.call_after_refresh(self._settle_programmatic_scroll, token=token)

    def _settle_programmatic_scroll(self, *, token: _ViewportTokenDAO) -> None:
        """Restore interrupted scrolling after layout unless newer input, hiding, or reset replaced it."""
        if (
            token
            != _ViewportTokenDAO(
                transcript_version=self._get_transcript_version(), revision=self._viewport_revision
            )
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

    def _update_reading_anchor_and_build_follow_snapshot(self) -> FollowSnapshotDAO:
        """Retain the reading anchor and build a transient snapshot before content changes.

        Mutation paths and child-widget callbacks call this before changing content.
        Reuse a saved anchor; native navigation keeps ownership of its destination.

        Returns:
            FollowSnapshotDAO: Current follow/version state, or an empty snapshot
                when presentation is closed or detached.
        """
        if self._presentation_closed or not self.is_attached:
            return FollowSnapshotDAO()
        if self._native_navigation is not None:
            following = self._native_navigation.follows_bottom
        else:
            self._update_reading_anchor()
            following = not self._reading and (
                self._hidden_following
                if not self._visible or not self._geometry_ready
                else self._force_following_until_layout
                or self._transcript_scroll.max_scroll_y - self._transcript_scroll.scroll_y <= 1.0
            )
        return FollowSnapshotDAO(
            was_following=following,
            transcript_version=self._get_transcript_version(),
            viewport_revision=self._viewport_revision,
        )

    def _widget_follow_reader(self) -> Callable[[], FollowSnapshotDAO]:
        """Give a child a pre-mutation anchor/snapshot callback limited to its transcript version."""
        transcript_version = self._get_transcript_version()

        def capture() -> FollowSnapshotDAO:
            """Reject an old timer even before queued removal completes."""
            return (
                self._update_reading_anchor_and_build_follow_snapshot()
                if transcript_version == self._get_transcript_version()
                else FollowSnapshotDAO()
            )

        return capture

    def _finish_viewport_mutation(self, *, snapshot: FollowSnapshotDAO) -> None:
        """Restore the current scroll behavior after a content change without interrupting user navigation."""
        if (
            snapshot.transcript_version != self._get_transcript_version()
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
        """Handle a render notice only from a child that still belongs to this transcript."""
        message.stop()
        if message.source.is_attached and self in message.source.ancestors:
            self._finish_viewport_mutation(snapshot=message.snapshot)

    def _queue_follow_pin(self) -> None:
        """Schedule one move to the bottom after new content arrives while following."""
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
        token = (self._get_transcript_version(), self._viewport_revision, self._pin_sequence)
        self._active_pin = token
        self._follow_pin_dirty = False
        self.call_after_refresh(self._land_follow_pin, token=token)

    def _is_follow_pin_current(self, *, token: tuple[int, int, int]) -> bool:
        """Check that a scheduled move to the bottom has not been replaced or cancelled."""
        return (
            self._active_pin == token
            and token[:2] == (self._get_transcript_version(), self._viewport_revision)
            and self._visible
            and self._geometry_ready
            and self.is_attached
            and not self._presentation_closed
            and not self._reading
            and self._native_navigation is None
        )

    async def _land_follow_pin(self, *, token: tuple[int, int, int]) -> None:
        """Move to the bottom after layout and check again after the next layout."""
        if not self._is_follow_pin_current(token=token):
            return
        self._follow_pin_dirty = False
        await self._transcript_scroll.handle(
            command=SetScrollPositionDAO(y=self._transcript_scroll.max_scroll_y)
        )
        self.call_after_refresh(self._release_follow_pin, token=token)

    def _release_follow_pin(self, *, token: tuple[int, int, int]) -> None:
        """Finish this move to the bottom, or repeat it if content changed in the meantime."""
        if not self._is_follow_pin_current(token=token):
            return
        if self._follow_pin_dirty:
            self.call_after_refresh(self._land_follow_pin, token=token)
            return
        self._active_pin = None
        self._force_following_until_layout = False

    def scroll_to_bottom(self) -> None:
        """Follow the bottom when explicitly requested, even if the transcript is hidden."""
        self._viewport_revision += 1
        self._invalidate_navigation()
        self._reading_anchor = None
        self._reading = False
        self._back_scroll_mode = False
        self._hidden_following = True
        self._queue_follow_pin()
        self._enforce_window_soon()

    async def hydrate(self, *, is_current: Optional[Callable[[], bool]] = None) -> None:
        """Load recent saved history once without changing it.

        A read failure leaves the app usable; a display failure is reported to the
        caller. If cancelled, wait for the pending read before reporting cancellation.
        """
        transcript_version = self._get_transcript_version()
        async with self._hydration_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            if self._hydrated or self._presentation_closed or not self.is_attached:
                return
            transcript_version = self._get_transcript_version()
            entries = await self._read_history()
            if entries is None:
                return
            async with self._mutation_lock:
                if (
                    transcript_version != self._get_transcript_version()
                    or self._presentation_closed
                    or not self.is_attached
                ):
                    return
                if is_current is not None and not is_current():
                    return
                await self._present_history_tail(entries=entries, is_current=is_current)

    async def _invoke_history_reader(self) -> list[TranscriptEntryDAO]:
        """Call the supplied history reader from a task whose completion can be tracked."""
        return await self._history_reader()

    async def _read_history(self) -> Optional[list[TranscriptEntryDAO]]:
        """Read saved history for initial display or paging; leave the view unchanged if reading fails."""
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

    async def _present_history_tail(
        self, *, entries: list[TranscriptEntryDAO], is_current: Optional[Callable[[], bool]] = None
    ) -> None:
        """Display the recent history entries and count entries, not widgets, for paging."""
        snapshot = self._update_reading_anchor_and_build_follow_snapshot()
        # Keep messages already displayed after a partial failure. Clear or rebind before retrying;
        # retrying immediately would add the same messages twice.
        self._hydrated = True
        tail = entries[-TRANSCRIPT_HYDRATION_ENTRY_LIMIT:]
        for entry in tail:
            await self._projector.handle(event=ProjectReplayEntryDAO(entry=entry))
            if is_current is not None and not is_current():
                return
        self._load_older_cursor = len(entries) - len(tail)
        self._hydrated = True
        await self._update_earlier_summary()
        if is_current is None or is_current():
            self._finish_viewport_mutation(snapshot=snapshot)

    async def load_older(self) -> None:
        """Load and display one older page, sharing the same task with concurrent requests.

        Read failures can be retried. If display fails partway through, keep what was
        shown and require clearing or rebinding before replaying it to avoid duplicates.
        """
        if self._presentation_closed or not self.is_attached or not self._visible:
            return
        if self._older_task is None and self._load_older_cursor > 0 and not self._older_projection_failed:
            self._older_task = asyncio.create_task(
                self._load_older(transcript_version=self._get_transcript_version())
            )
        task = self._older_task
        if task is not None:
            await asyncio.shield(task)

    async def on_transcript_scroll_component_reached_top(
        self, event: TranscriptScrollComponent.ReachedTop
    ) -> None:
        """Start a tracked task to load older history when scrolling reaches the top."""
        event.stop()
        if self._older_task is not None or self._load_older_cursor <= 0 or self._older_projection_failed:
            return
        if self._presentation_closed or self._delivery_closing or not self.is_attached or not self._visible:
            return
        await self.handle(command=LoadOlderHistoryDAO())

    async def _load_older(self, *, transcript_version: int) -> None:
        """Read one history page at a time and check that its saved page position is still current."""
        try:
            async with self._hydration_lock:
                cursor = self._load_older_cursor
                entries = await self._read_history()
                if not entries:
                    return
                batch = entries[max(0, cursor - LOAD_OLDER_BATCH_SIZE) : cursor]
                async with self._mutation_lock:
                    if (
                        transcript_version != self._get_transcript_version()
                        or cursor != self._load_older_cursor
                    ):
                        return
                    if self._presentation_closed or not self.is_attached or not batch:
                        return
                    await self._publish_older(entries=batch)
        finally:
            if self._older_task is asyncio.current_task():
                self._older_task = None

    async def _publish_older(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Keep any messages already shown if display fails; advance the page position only on success."""
        self._back_scroll_mode = True
        self._reading = True
        snapshot = self._update_reading_anchor_and_build_follow_snapshot()
        try:
            await self._prepend_older_entries(entries=entries)
        except Exception as error:
            self._older_projection_failed = True
            log_warning("transcript_older_projection_failed", error_class=type(error).__name__)
            await self.mount_transcript_line(
                content="Earlier messages could not be displayed; resume this session to reload history.",
                classes="tool-result",
            )
        else:
            self._load_older_cursor -= len(entries)
        await self._update_earlier_summary()
        self._finish_viewport_mutation(snapshot=snapshot)

    async def _prepend_older_entries(self, *, entries: list[TranscriptEntryDAO]) -> None:
        """Insert older messages before a fixed child so new notices do not change their insertion point."""
        children = self._get_ordinary_children()
        boundary = children[0] if children else Static("", classes="transcript-prepend-boundary")
        temporary = not children
        if temporary:
            await self._transcript_content.mount(boundary)
        try:
            for entry in entries:
                before = list(self._transcript_content.children).index(boundary)
                await self._projector.handle(event=ProjectReplayEntryDAO(entry=entry, before=before))
        finally:
            if temporary:
                await boundary.remove()

    def _get_ordinary_children(self) -> list[Widget]:
        """Return message widgets without summary markers or separate scroll-area widgets."""
        return [
            child
            for child in self._transcript_content.children
            if child is not self._earlier_summary and not child.has_class("transcript-prepend-boundary")
        ]

    async def _update_earlier_summary(self) -> None:
        """Show how many older entries can be loaded, without counting removed widgets as history."""
        if (
            not self._older_projection_failed
            and not self._load_older_cursor
            and (not self._hidden_block_count or self._back_scroll_mode)
        ):
            summary, self._earlier_summary = self._earlier_summary, None
            if summary is not None:
                await summary.remove()
            return
        text = self._build_earlier_summary_text()
        if self._earlier_summary is None:
            self._earlier_summary = LiteralTextStatic(text, id="transcript-earlier-summary")
            await self._transcript_content.mount(self._earlier_summary, before=0)
        else:
            self._earlier_summary.update(text)

    def _build_earlier_summary_text(self) -> str:
        """Show a partial-display error before the normal older-history summary when needed."""
        if self._older_projection_failed:
            return "▲ earlier messages partially displayed — resume this session to reload history"
        if self._load_older_cursor:
            return (
                f"▲ {self._load_older_cursor} earlier messages hidden "
                "— scroll to the top to load older messages"
            )
        return "▲ earlier messages collapsed — resume this session to recover them"

    async def present_message_application(self, *, entry: TranscriptEntryDAO) -> None:
        """Route canonical live applications through binding-lifetime replay identity."""
        transcript_version = self._get_transcript_version()
        async with self._lifecycle_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            async with self._mutation_lock:
                snapshot = self._update_reading_anchor_and_build_follow_snapshot()
                await self._projector.handle(event=ProjectReplayEntryDAO(entry=entry))
                self._finish_viewport_mutation(snapshot=snapshot)
                self._enforce_window_soon()

    async def echo_user(self, *, text: str) -> None:
        """Display an accepted prompt without submitting it or saving it to history."""
        transcript_version = self._get_transcript_version()
        async with self._lifecycle_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            async with self._mutation_lock:
                self.scroll_to_bottom()
                snapshot = self._update_reading_anchor_and_build_follow_snapshot()
                await self._projector.handle(event=ProjectUserTurnDAO(text=text))
                self._finish_viewport_mutation(snapshot=snapshot)

    async def present_event(self, *, event: AgentStreamEventDAO) -> None:
        """Display an event routed here by the app and report display failures to the caller."""
        transcript_version = self._get_transcript_version()
        async with self._lifecycle_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            async with self._mutation_lock:
                snapshot = self._update_reading_anchor_and_build_follow_snapshot()
                await self._project_parent_event(event=event)
                self._finish_viewport_mutation(snapshot=snapshot)
                self._enforce_window_soon()

    async def _project_parent_event(self, *, event: AgentStreamEventDAO) -> None:
        """Match pending steering messages in arrival order, otherwise use the normal event adapter."""
        if event.kind != "steering_applied":
            await self._projector.handle(event=event)
            return
        if self._pending_steer_blocks:
            await self._pending_steer_blocks.pop(0).remove()
        await self._projector.handle(event=ProjectUserTurnDAO(text=event.content or ""))

    async def show_pending_steering(self, *, message: str) -> None:
        """Display an accepted steering message without managing its execution queue."""
        transcript_version = self._get_transcript_version()
        async with self._lifecycle_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            async with self._mutation_lock:
                snapshot = self._update_reading_anchor_and_build_follow_snapshot()
                block = SteeringPendingBlock(message=message)
                await self._transcript_content.mount(block)
                self._pending_steer_blocks.append(block)
                self._finish_viewport_mutation(snapshot=snapshot)
                self._enforce_window_soon()

    async def mount_tree_output(self, *, widget: Widget) -> None:
        """Add exported tree output separately from the normal chat-message count."""
        transcript_version = self._get_transcript_version()
        async with self._lifecycle_lock:
            self._ensure_current_transcript_version(expected_version=transcript_version)
            async with self._mutation_lock:
                snapshot = self._update_reading_anchor_and_build_follow_snapshot()
                await self._transcript_scroll.mount(widget)
                self._finish_viewport_mutation(snapshot=snapshot)

    def set_visible(self, *, visible: bool) -> None:
        """Show or hide the transcript without changing app focus or agent execution.

        Keep the reading position while hidden and restore it after visible layout.
        Do not measure widget positions while the transcript is hidden.
        """
        if self._presentation_closed or self._visible == visible:
            return
        if not visible:
            if self._native_navigation is None and self._is_transcript_geometry_visible():
                self._reconcile_visible_viewport()
            snapshot = self._update_reading_anchor_and_build_follow_snapshot()
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
                self._resume_visible_layout, token=(self._get_transcript_version(), self._viewport_revision)
            )
            self._enforce_window_soon()

    def toggle_expandable_details(self) -> None:
        """Expand all message details on the first call, then alternate between collapsed and expanded."""
        snapshot = self._update_reading_anchor_and_build_follow_snapshot()
        self._global_expand_all = not bool(self._global_expand_all)
        for child in self._get_ordinary_children():
            if isinstance(child, (UserMessageBlock, ToolExecutionBlock, AssistantStreamThinkingBlock)):
                child.set_expanded(expanded=self._global_expand_all)
        self._finish_viewport_mutation(snapshot=snapshot)

    def _enforce_window_soon(self) -> None:
        """Schedule one message-limit cleanup task without waiting while holding the update lock."""
        if self._presentation_closed or not self.is_attached:
            return
        if len(self._get_ordinary_children()) <= TRANSCRIPT_WINDOW_SIZE:
            return
        self._window_enforcement_rerun = True
        if self._window_task is None:
            self._window_task = asyncio.create_task(
                self._run_window_enforcement_pass(transcript_version=self._get_transcript_version())
            )

    async def _run_window_enforcement_pass(self, *, transcript_version: int) -> None:
        """Repeat cleanup only when more content changed, not when all remaining blocks must stay."""
        try:
            while self._window_enforcement_rerun:
                self._window_enforcement_rerun = False
                async with self._mutation_lock:
                    if (
                        transcript_version != self._get_transcript_version()
                        or self._presentation_closed
                        or not self.is_attached
                    ):
                        return
                    await self._evict_settled_prefix()
        except Exception as error:
            log_warning("transcript_window_failed", error_class=type(error).__name__)
        finally:
            if self._window_task is asyncio.current_task():
                self._window_task = None

    async def _evict_settled_prefix(self) -> None:
        """Remove old finished blocks, keeping the protected recent blocks and all active blocks.

        Leave the saved-history page position unchanged.
        """
        if self._back_scroll_mode or not self._visible or self._reading_anchor is not None or self._reading:
            return
        children = self._get_ordinary_children()
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
        """Check whether an answer, thinking block, tool call, or steering message is still active."""
        if isinstance(child, (AssistantStreamBlock, AssistantStreamThinkingBlock)):
            return not child.finalized
        if isinstance(child, ToolExecutionBlock):
            return child.result_output is None and not child.is_incomplete
        return child in self._pending_steer_blocks

    async def clear(self) -> None:
        """Wait for old display work and clear messages without cancelling agent execution."""
        self._ensure_transcript_open()
        self._ensure_transcript_attached()
        self._ensure_transcript_ui_loop()
        task = asyncio.create_task(self._reset_with_notice_retirement(history_reader=None))
        await self._join_cleanup(task=task)

    async def bind_history(self, *, history_reader: HistoryReader) -> None:
        """Clear the old transcript state before using the new session’s history reader."""
        if self._presentation_closed or self._delivery_closing:
            raise RuntimeError("Transcript is closed")
        task = asyncio.create_task(self._reset_with_notice_retirement(history_reader=history_reader))
        await self._join_cleanup(task=task)

    async def _reset_with_notice_retirement(self, *, history_reader: Optional[HistoryReader]) -> None:
        """Wait for notice delivery to finish without holding the lock that delivery needs."""
        await self.workflow_notice.reset()
        await self._reset_presentation(history_reader=history_reader, close=False)

    async def close(self) -> None:
        """Stop accepting updates and finish cleanup even if the caller is cancelled."""
        self._delivery_closing = True
        task = asyncio.create_task(self._reset_presentation(history_reader=None, close=True))
        await self._join_cleanup(task=task)

    async def _reset_presentation(self, *, history_reader: Optional[HistoryReader], close: bool) -> None:
        """Invalidate old updates, wait for reads, and remove widgets in order."""
        # Workflow notices need this lock. Release it before waiting for the notice
        # adapter to finish, otherwise both sides could wait forever.
        async with self._lifecycle_lock:
            if self._presentation_closed and not close:
                raise RuntimeError("Transcript is closed")
            if self._cleanup_complete:
                return
            self._update_transcript_version()
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
                old_children = tuple(self._transcript_content.children) + tuple(
                    child
                    for child in self._transcript_scroll.children
                    if child is not self._transcript_content
                )
                self._load_older_cursor = 0
                self._hydrated = False
                self._older_projection_failed = False
                self._earlier_summary = None
                self._hidden_block_count = 0
                self._back_scroll_mode = False
                self._pending_steer_blocks.clear()
                self._active_expandable_tool_block = None
                self._global_expand_all = None
                for child in old_children:
                    await child.remove()
                if history_reader is not None:
                    self._history_reader = history_reader
                if close:
                    await self._adapter.close()
                    await self._projector.close()
                    await self._transcript_scroll.close()
                else:
                    await self._adapter.reset()
                    await self._projector.reset()
                    if history_reader is not None:
                        await self._projector.handle(event=RetireHistoryBindingDAO())
                    if self.is_attached:
                        await self._transcript_scroll.reset()
        if close:
            await self.workflow_notice.close()
            self._cleanup_complete = True

    async def _join_cleanup(self, *, task: asyncio.Task[None]) -> None:
        """Wait for cleanup to finish before reporting that the caller was cancelled."""
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
        """Wait for outstanding reads and cleanup when Textual removes the component."""
        await self.close()

    def logical_copy_text(self) -> str:
        """Return collected text in append order without turn separators.

        This is not a complete history export.
        """
        return "\n".join(text for text, classes in self._adapter.lines if classes != "turn-separator")

    async def mount_user_message_block(self, *, text: str, before: Optional[int] = None) -> UserMessageBlock:
        """Add a user message for live output or replayed history."""
        block = UserMessageBlock(text=text)
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def mount_turn_separator_if_needed(self, *, before: Optional[int] = None) -> bool:
        """Add a turn separator only when actual message text already exists."""
        if not self._adapter.is_prior_turn_content_present():
            return False
        await self.mount_transcript_line(
            content=TranscriptNoticeDisplayAdapter.TURN_SEPARATOR, classes="turn-separator", before=before
        )
        return True

    async def mount_assistant_block(
        self, *, title_prefix: Optional[str] = None, before: Optional[int] = None
    ) -> AssistantStreamBlock:
        """Add an assistant answer block for live output or replayed history."""
        block = AssistantStreamBlock(title_prefix=title_prefix, follow_snapshot=self._widget_follow_reader())
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def mount_thinking_block(self, *, before: Optional[int] = None) -> AssistantStreamThinkingBlock:
        """Add a thinking block whose identity is managed by the event adapter."""
        block = AssistantStreamThinkingBlock(
            force_expanded=self._global_expand_all, follow_snapshot=self._widget_follow_reader()
        )
        await self._mount_transcript_widget(block=block, before=before)
        return block

    async def mount_tool_execution_block(
        self, *, tool_call_id: str, tool_name: Optional[str], before: Optional[int] = None
    ) -> ToolExecutionBlock:
        """Add a tool call and result block at the position requested by the adapter."""
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
        """Add a message during an allowed update, then schedule removal of excess old messages."""
        snapshot = self._update_reading_anchor_and_build_follow_snapshot()
        await self._transcript_content.mount(block, before=before)
        self._finish_viewport_mutation(snapshot=snapshot)
        self._enforce_window_soon()

    async def mount_transcript_line(
        self, *, content: str, classes: str, before: Optional[int] = None
    ) -> None:
        """Add an adapter notice during an existing update without acquiring the same locks again."""
        await self._adapter.handle(event=TranscriptNoticeDAO(content=content, classes=classes, before=before))

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        """Save text that is already displayed without adding a second visible message."""
        if self._presentation_closed or not self.is_attached:
            return
        self._adapter.record(content=content, classes=classes)

    async def mount_transcript_notice(self, *, notice: TranscriptNoticeDAO) -> None:
        """Add an accepted adapter notice without acquiring the public update locks again."""
        widget = (
            Static(Markdown(notice.content), classes=notice.classes)
            if notice.classes == "assistant-final"
            else LiteralTextStatic(notice.content, classes=notice.classes)
        )
        await self._mount_transcript_widget(block=widget, before=notice.before)
