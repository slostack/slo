"""Two bounded native-animation proofs using Textual's existing test hooks."""

import asyncio
from functools import partial

from textual._animator import SimpleAnimation
from textual.message_pump import Callback

import pytest
from textual.widgets import Static
from textual.events import Key

from src.tui.components.chat_transcript.component import TranscriptScrollComponent
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO
from tests.tui.test_chat_transcript import TranscriptTestApp
from tests.tui.test_chat_transcript_navigation import OrderedTranscript, named_row, painted_rows


class PaintObservedApp(TranscriptTestApp):
    """Observe composed frames synchronously at Textual's display boundary."""

    def __init__(self, *, transcript: OrderedTranscript) -> None:
        """Keep observation disabled until the test has finished setup."""
        super().__init__(transcript=transcript)
        self.observe = False
        self.frames: list[list[str]] = []
        self.interrupt_frame: list[str] | None = None

    def on_key(self, event: Key) -> None:
        """Paint the current animator offset at input dispatch before saving its reading row."""
        if self.observe and event.key == "right":
            # The scroll notification can still be queued behind this input event.
            self.screen._refresh_layout(scroll=True)
            self.interrupt_frame = painted_rows(app=self)

    def post_display_hook(self) -> None:
        """Capture each displayed compositor state without yielding or scheduling work."""
        if self.observe:
            self.frames.append(painted_rows(app=self))


async def mount_wide_rows(*, transcript: OrderedTranscript) -> Static:
    """Mount unique row labels repeated horizontally so panning retains the oracle."""
    wide = Static("\n".join((f"PRECISE-{i:03} " * 30) for i in range(160)))
    wide.styles.width = 360
    wide.styles.height = 160
    await transcript.mount_tree_output(widget=wide)
    return wide


@pytest.mark.parametrize("cover_first", [True, False])
async def test_unequal_axes_retire_with_cover_before_or_after_native(cover_first: bool) -> None:
    """Real one-cell x finishes before page-sized y in both covering-callback orders."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        await mount_wide_rows(transcript=transcript)
        scroll = transcript.query_one(TranscriptScrollComponent)
        scroll.styles.overflow_x = "scroll"
        scroll.focus()
        await pilot.pause()
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        target = 100 - scroll.scrollable_content_region.height
        scroll.scroll_to(y=target, animate=False, immediate=True)
        await pilot.pause()
        literal = next(line.split()[0] for line in painted_rows(app=app) if "PRECISE-" in line)
        row = named_row(app=app, literal=literal)
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        transcript.hold = {"_start_native_navigation", "_native_navigation_completed"}
        await pilot.press("pageup", "right")

        # Release both starts; the old revision must reject itself. The current
        # Right request merges pending y and uses native speed=50, not duration=.1.
        # Wall-clock polling can miss this entire short-lived frame when the
        # worker is descheduled. Pause only native ticks, not layout/callbacks,
        # then evaluate Textual's real animations at the unequal-axis boundary.
        def start_with_paused_ticks(
            *, callback: Callback, args: tuple[object, ...], kwargs: dict[str, object]
        ) -> None:
            """Run the captured native start and pause its timer before yielding."""
            callback(*args, **kwargs)
            app.animator._timer.pause()

        transcript.hold.remove("_start_native_navigation")
        for _ in range(2):
            callback, args, kwargs = transcript.calls.pop(0)
            transcript.call_after_refresh(
                partial(start_with_paused_ticks, callback=callback, args=args, kwargs=kwargs)
            )
        async with asyncio.timeout(3):
            while not all((id(scroll), f"scroll_{axis}") in app.animator._animations for axis in ("x", "y")):
                await asyncio.sleep(0.001)
        x_animation = app.animator._animations[(id(scroll), "scroll_x")]
        y_animation = app.animator._animations[(id(scroll), "scroll_y")]
        assert isinstance(x_animation, SimpleAnimation)
        assert isinstance(y_animation, SimpleAnimation)
        assert x_animation.duration < y_animation.duration
        animation_time = max(x_animation.start_time, y_animation.start_time) + x_animation.duration
        assert x_animation(time=animation_time, app_animation_level=app.animation_level)
        assert not y_animation(time=animation_time, app_animation_level=app.animation_level)
        assert x_animation.on_complete is not None
        x_animation.on_complete()
        async with asyncio.timeout(3):
            while not (
                scroll.scroll_x == 1
                and target < scroll.scroll_y < 100
                and transcript._native_navigation is not None
                and transcript._native_navigation.pending_axes == {"y"}
            ):
                await asyncio.sleep(0.001)
        operation = transcript._native_navigation
        assert operation is not None
        assert operation.pending_axes == {"y"}
        assert transcript.calls
        if cover_first:
            transcript.release_at(duplicate=True)
            # Observe the callback synchronously; Pilot.pause may consume the
            # remaining real animation and invalidate the intermediate oracle.
            assert transcript._native_navigation is operation
            assert target < scroll.scroll_y < 100
        app.animator._timer.resume()
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        if not cover_first:
            assert transcript._native_navigation is None
            transcript.release_at(duplicate=True)
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.pause()
        assert transcript._native_navigation is None
        assert named_row(app=app, literal=literal) == row
        await transcript.handle(command=TranscriptNoticeDAO(content="LATER-GROWTH", classes="tool-result"))
        await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert scroll.scroll_x == 1


async def test_every_compositor_frame_excludes_interrupted_public_y_endpoint() -> None:
    """Right interrupts public y motion without even one old-endpoint compositor frame."""
    transcript = OrderedTranscript()
    app = PaintObservedApp(transcript=transcript)
    async with app.run_test() as pilot:
        await mount_wide_rows(transcript=transcript)
        scroll = transcript.query_one(TranscriptScrollComponent)
        scroll.styles.overflow_x = "scroll"
        scroll.focus()
        await pilot.pause()
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        endpoint = next(line.split()[0] for line in painted_rows(app=app) if "PRECISE-" in line)
        scroll.scroll_to(y=30, animate=False, immediate=True)
        await pilot.pause()
        app.observe = True
        scroll.scroll_to(y=100, animate=True, duration=2, immediate=True)
        async with asyncio.timeout(3):
            while scroll.scroll_y < 35 or len({tuple(frame) for frame in app.frames}) < 2:
                await asyncio.sleep(0.001)
        assert 30 < scroll.scroll_y < 80
        assert transcript._native_navigation is None
        await pilot.press("right")
        assert app.interrupt_frame is not None
        before_literal = next(line.split()[0] for line in app.interrupt_frame if "PRECISE-" in line)
        before_row = next(index for index, line in enumerate(app.interrupt_frame) if before_literal in line)
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        settled = painted_rows(app=app)
        literal = next(line.split()[0] for line in settled if "PRECISE-" in line)
        row = named_row(app=app, literal=literal)
        await transcript.handle(command=TranscriptNoticeDAO(content="LATER-GROWTH", classes="tool-result"))
        await pilot.pause()
        app.observe = False
        assert len(app.frames) >= 3
        assert len({tuple(frame) for frame in app.frames}) >= 2
        assert all(endpoint not in "\n".join(frame) for frame in app.frames)
        assert named_row(app=app, literal=literal) == row
        assert named_row(app=app, literal=before_literal) == before_row
        assert scroll.scroll_x == 1
        assert transcript._native_navigation is None
