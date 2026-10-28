"""Two bounded native-animation proofs using Textual's existing test hooks."""

import asyncio

import pytest
from textual.widgets import Static
from textual.events import Key

from src.tui.components.chat_transcript.component import TranscriptScroll
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
        """Capture the painted reading row at actual input dispatch, not before queueing."""
        if self.observe and event.key == "right":
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
        scroll = transcript.query_one(TranscriptScroll)
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
        transcript.hold.remove("_start_native_navigation")
        transcript.release_at()
        transcript.release_at()
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
            await pilot.pause()
            assert transcript._native_navigation is operation
            assert target < scroll.scroll_y < 100
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
        transcript.write_transcript_line(content="LATER-GROWTH", classes="tool-result")
        await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert scroll.scroll_x == 1


async def test_every_compositor_frame_excludes_interrupted_public_y_endpoint() -> None:
    """Right interrupts public y motion without even one old-endpoint compositor frame."""
    transcript = OrderedTranscript()
    app = PaintObservedApp(transcript=transcript)
    async with app.run_test() as pilot:
        await mount_wide_rows(transcript=transcript)
        scroll = transcript.query_one(TranscriptScroll)
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
        transcript.write_transcript_line(content="LATER-GROWTH", classes="tool-result")
        await pilot.pause()
        app.observe = False
        assert len(app.frames) >= 3
        assert len({tuple(frame) for frame in app.frames}) >= 2
        assert all(endpoint not in "\n".join(frame) for frame in app.frames)
        assert named_row(app=app, literal=literal) == row
        assert named_row(app=app, literal=before_literal) == before_row
        assert scroll.scroll_x == 1
        assert transcript._native_navigation is None
