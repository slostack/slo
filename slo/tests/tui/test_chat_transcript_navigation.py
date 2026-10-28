"""Native callback ordering against mounted production widgets (Feature 96)."""

import asyncio
from functools import partial
from textual import events
from pathlib import Path
from textual.theme import Theme

import pytest
from textual.message_pump import Callback
from textual.widgets import Static
from textual.scrollbar import ScrollUp, ScrollTo

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.components.chat_transcript.component import ChatTranscript, TranscriptScroll
from src.tui.theme import SLO_DEFAULT_THEME, SLO_DARK_THEME
from tests.tui.test_chat_transcript import TranscriptTestApp


class OrderedTranscript(ChatTranscript):
    """Hold selected real after-refresh calls; never replace layout or animation."""

    def __init__(self) -> None:
        """Create a local empty-reader surface and an initially transparent recorder."""
        super().__init__(history_reader=self.read_empty)
        self.hold: set[str] = set()
        self.calls: list[tuple[Callback, tuple[object, ...], dict[str, object]]] = []

    async def read_empty(self) -> list[TranscriptEntryDAO]:
        """Provide the unused replay boundary for native-only cases."""
        return []

    def call_after_refresh(self, callback: Callback, *args: object, **kwargs: object) -> bool:
        """Record only explicitly armed callbacks; otherwise preserve Textual scheduling."""
        target = callback.func if isinstance(callback, partial) else callback
        if getattr(target, "__name__", "") in self.hold:
            self.calls.append((callback, args, kwargs))
            return True
        return super().call_after_refresh(callback, *args, **kwargs)

    def release_at(self, *, index: int = 0, duplicate: bool = False) -> None:
        """Deliver a captured call through Textual, optionally twice for idempotence."""
        callback, args, kwargs = self.calls.pop(index)
        super().call_after_refresh(callback, *args, **kwargs)
        if duplicate:
            super().call_after_refresh(callback, *args, **kwargs)


def painted_rows(*, app: TranscriptTestApp) -> list[str]:
    """Read actual composed terminal cells after the caller settles layout."""
    return [strip.text for strip in app.screen._compositor.render_strips()]


def named_row(*, app: TranscriptTestApp, literal: str) -> int:
    """Require a unique painted row, allowing repeated labels across that row."""
    matches = [index for index, line in enumerate(painted_rows(app=app)) if literal in line]
    assert len(matches) == 1, (literal, painted_rows(app=app))
    return matches[0]


@pytest.mark.parametrize("theme", [SLO_DEFAULT_THEME, SLO_DARK_THEME])
@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("growth_above", [False, True])
@pytest.mark.parametrize("timing", ["before_start", "before_settlement"])
@pytest.mark.parametrize("trigger", ["pageup", "track"])
async def test_native_destination_survives_growth(
    theme: Theme, size: tuple[int, int], growth_above: bool, timing: str, trigger: str
) -> None:
    """Growth preserves the requested line, not the intermediate animated frame."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    app.register_theme(theme)
    app.theme = theme.name
    async with app.run_test(size=size) as pilot:
        upper = await transcript.mount_assistant_block()
        upper.set_answer(content="upper")
        body = Static("\n".join(f"DEST-{i:03}" for i in range(160)))
        body.styles.height = 160
        await transcript.mount_tree_output(widget=body)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        # Observe the exact requested destination before returning to the input origin.
        destination = 100 - scroll.scrollable_content_region.height
        scroll.scroll_to(y=destination, animate=False, immediate=True)
        await pilot.pause()
        expected = next(line.strip() for line in painted_rows(app=app) if "DEST-" in line)
        row = named_row(app=app, literal=expected)
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        transcript.hold = (
            {"_start_native_navigation"} if timing == "before_start" else {"_settle_native_navigation"}
        )
        scroll.focus()
        if trigger == "pageup":
            await pilot.press("pageup")
        else:
            scroll.post_message(ScrollUp())
            await pilot.pause()
        if timing == "before_settlement":
            await pilot.wait_for_scheduled_animations()
            await pilot.pause()
        assert transcript.calls
        if growth_above:
            upper.set_answer(content="\n\n".join(f"growth-{i}" for i in range(12)))
        else:
            transcript.write_transcript_line(content="END-MARKER", classes="tool-result")
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at()
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        assert named_row(app=app, literal=expected) == row
        assert transcript._native_navigation is None


@pytest.mark.parametrize("keys", [("pageup", "end"), ("end", "pageup")])
@pytest.mark.parametrize("reverse", [False, True])
async def test_delayed_starts_and_duplicate_completions_respect_latest_input(
    keys: tuple[str, str], reverse: bool
) -> None:
    """Old deferred starts cannot supersede the second input or final stream growth."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"ROW-{i:03}" for i in range(100)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        transcript.hold = {"_start_native_navigation", "_native_navigation_completed"}
        await pilot.press(*keys)
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        await pilot.pause()
        assert len(transcript.calls) == 2
        transcript.release_at(index=1 if reverse else 0, duplicate=True)
        transcript.release_at(duplicate=True)
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.pause()
        assert ("END-MARKER" in "\n".join(painted_rows(app=app))) == (keys[-1] == "end")
        before = painted_rows(app=app)
        block.set_answer(content=block.get_copyable_text() + "\n\nLAST-MARKER")
        for _ in range(4):
            await pilot.pause()
        if keys[-1] == "pageup":
            literal = next(line.strip() for line in before if "ROW-" in line)
            assert named_row(app=app, literal=literal) == next(
                index for index, line in enumerate(before) if literal in line
            )
        else:
            assert "LAST-MARKER" in "\n".join(painted_rows(app=app))
        assert transcript._native_navigation is None


@pytest.mark.parametrize("during_motion", [False, True])
@pytest.mark.parametrize("reset", ["hide", "clear"])
async def test_stale_two_axis_callbacks_after_visibility_or_reset(during_motion: bool, reset: str) -> None:
    """A stale pair of native callbacks cannot repaint hidden or replacement content."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        wide = Static("\n".join((f"WIDE-{i:03} " * 30) for i in range(100)))
        wide.styles.width = 300
        wide.styles.height = 100
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        transcript.hold = {"_settle_native_navigation"} if during_motion else {"_start_native_navigation"}
        scroll.post_message(ScrollTo(x=70, y=40, animate=True))
        await pilot.pause()
        if during_motion:
            await pilot.wait_for_scheduled_animations()
            await pilot.pause()
        assert transcript.calls
        if reset == "hide":
            transcript.set_visible(visible=False)
        else:
            await transcript.clear()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.pause()
        if reset == "hide":
            transcript.set_visible(visible=True)
        await transcript.echo_user(text="NEW-LIFETIME")
        await pilot.pause()
        transcript.scroll_to_bottom()
        await pilot.pause()
        before = painted_rows(app=app)
        await pilot.pause()
        assert painted_rows(app=app) == before
        assert transcript._native_navigation is None


@pytest.mark.parametrize("input_kind", ["right", "ctrl", "shift", "track"])
@pytest.mark.parametrize("reach", ["programmatic", "focus"])
@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("theme", [SLO_DEFAULT_THEME, SLO_DARK_THEME])
async def test_x_first_real_history_preserves_reading(
    tmp_path: Path, input_kind: str, reach: str, size: tuple[int, int], theme: Theme
) -> None:
    """X-first admission reconciles public reveal before upper and lower stream growth."""
    from textual import events
    from tests.tui.test_chat_transcript import seed_history

    entries = await seed_history(root=tmp_path, count=35)

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply actual replay results from the temporary store."""
        return entries

    transcript = OrderedTranscript()
    await transcript.bind_history(history_reader=reader)
    app = TranscriptTestApp(transcript=transcript)
    app.register_theme(theme)
    app.theme = theme.name
    async with app.run_test(size=size) as pilot:
        await transcript.hydrate()
        upper = await transcript.mount_assistant_block()
        upper.set_answer(content="upper")
        wide = Static("\n".join((f"READ-{i:03} " * 30) for i in range(100)))
        wide.can_focus = True
        wide.styles.width = 300
        wide.styles.height = 100
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        await pilot.pause()
        if reach == "focus":
            wide.focus()
        else:
            scroll.scroll_to(
                y=wide.region.y - scroll.scrollable_content_region.y + scroll.scroll_y + 10,
                animate=False,
                immediate=True,
            )
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        literal = next(line.split()[0] for line in painted_rows(app=app) if "READ-" in line)
        row = named_row(app=app, literal=literal)
        transcript.hold = {"_start_native_navigation", "_native_navigation_completed"}
        if input_kind == "right":
            scroll.focus()
            await pilot.press("right")
        elif input_kind == "track":
            bar = scroll.horizontal_scrollbar
            await pilot.click(widget=bar, offset=(bar.size.width - 2, 0))
        else:
            wide.post_message(
                events.MouseScrollDown(
                    widget=wide,
                    x=5,
                    y=3,
                    delta_x=0,
                    delta_y=1,
                    button=0,
                    shift=input_kind == "shift",
                    meta=False,
                    ctrl=input_kind == "ctrl",
                )
            )
            await pilot.pause()
        assert transcript.calls
        upper.set_answer(content="\n\n".join(f"upper-{i}" for i in range(15)))
        transcript.write_transcript_line(content="END-MARKER", classes="tool-result")
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert scroll.scroll_x > 0
        upper.set_answer(content=upper.get_copyable_text() + "\n\nmore upper growth")
        for _ in range(4):
            await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert "END-MARKER" not in "\n".join(painted_rows(app=app))
        assert transcript._native_navigation is None


@pytest.mark.parametrize("vertical", ["pageup", "end"])
@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("paired", [False, True])
async def test_horizontal_interruption_retains_vertical_destination(
    vertical: str, started: bool, paired: bool
) -> None:
    """Right retains a pending y destination before and after its native start."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        upper = await transcript.mount_assistant_block()
        upper.set_answer(content="upper")
        wide = Static("\n".join((f"TARGET-{i:03} " * 24) for i in range(100)))
        wide.styles.width = 300
        wide.styles.height = 100
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.scroll_to(y=60, animate=False, immediate=True)
        await pilot.pause()
        target = 60 - scroll.scrollable_content_region.height
        scroll.scroll_to(y=target, animate=False, immediate=True)
        await pilot.pause()
        literal = next(line.split()[0] for line in painted_rows(app=app)[2:] if "TARGET-" in line)
        row = named_row(app=app, literal=literal)
        scroll.scroll_to(y=60, animate=False, immediate=True)
        await pilot.pause()
        transcript.hold = {"_start_native_navigation"}
        scroll.focus()
        await pilot.press(vertical)
        if paired:
            await pilot.press("right")
        if started:
            origin = scroll.scroll_y
            while transcript.calls:
                transcript.release_at()
            async with asyncio.timeout(3):
                while scroll.scroll_y == origin:
                    await asyncio.sleep(0.001)
            operation = transcript._native_navigation
            assert operation is not None and operation.request.y is not None
            assert abs(scroll.scroll_y - operation.request.y) > 0.01
        await pilot.press("right")
        upper.set_answer(content="\n\n".join(f"upper-{i}" for i in range(12)))
        # Tree output is the final content; its last row is the bottom marker.
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        if vertical == "pageup":
            assert named_row(app=app, literal=literal) == row
        else:
            assert "TARGET-099" in "\n".join(painted_rows(app=app))
        assert scroll.scroll_x > 0
        assert transcript._native_navigation is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("pin_landed", [False, True])
@pytest.mark.parametrize("transition", ["right", "echo", "hide", "clear"])
async def test_x_only_pending_pin_survives_old_release(
    reverse: bool, pin_landed: bool, transition: str
) -> None:
    """A current bottom request survives x-only input and obsolete pin/release callbacks."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"ROW-{i}" for i in range(100)))
        block.styles.width = 300
        transcript.query_one("#transcript-content").styles.width = 300
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.focus()
        await pilot.press("pageup")
        await pilot.wait_for_scheduled_animations()
        transcript.hold = {"_release_follow_pin" if pin_landed else "_land_follow_pin"}
        transcript.scroll_to_bottom()
        await pilot.pause()
        assert transcript.calls
        if transition == "echo":
            await transcript.echo_user(text="NEW-USER")
        elif transition == "hide":
            transcript.set_visible(visible=False)
            transcript.set_visible(visible=True)
        elif transition == "clear":
            await transcript.clear()
            block = await transcript.mount_assistant_block()
        else:
            await pilot.press("right")
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(index=-1 if reverse else 0, duplicate=True)
        for _ in range(4):
            await pilot.pause()
        assert "END-MARKER" in "\n".join(painted_rows(app=app))
        if transition == "right":
            assert scroll.scroll_x > 0


async def test_removed_reading_candidate_uses_clamped_numeric_fallback() -> None:
    """Public removal during held x settlement falls back without acquiring bottom intent."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        for prefix in ("FIRST", "SECOND"):
            wide = Static("\n".join((f"{prefix}-{i:03} " * 25) for i in range(100)))
            wide.styles.width = 300
            wide.styles.height = 100
            await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.scroll_to(y=40, animate=False, immediate=True)
        await pilot.pause()
        saved_y = scroll.scroll_y
        first = scroll.children[1]
        transcript.hold = {"_settle_native_navigation"}
        scroll.focus()
        await pilot.press("right")
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        assert transcript.calls
        await first.remove()
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at()
        for _ in range(3):
            await pilot.pause()
        assert scroll.scroll_y == min(saved_y, scroll.max_scroll_y)
        assert "SECOND-099" not in "\n".join(painted_rows(app=app))
        assert transcript._native_navigation is None


@pytest.mark.parametrize("release_cover_first", [False, True])
@pytest.mark.parametrize("x_target", [0, 3, 180])
async def test_two_axis_completion_order_and_no_movement(release_cover_first: bool, x_target: int) -> None:
    """Unequal native distances and duplicate covering callbacks settle exactly once."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        wide = Static("\n".join((f"PAIR-{i:03} " * 24) for i in range(100)))
        wide.styles.width = 300
        wide.styles.height = 100
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.scroll_to(y=70, animate=False, immediate=True)
        await pilot.pause()
        transcript.hold = {"_native_navigation_completed"}
        scroll.post_message(ScrollTo(x=x_target, y=30, animate=True))
        await pilot.pause()
        assert transcript.calls
        if release_cover_first:
            transcript.release_at(duplicate=True)
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        for _ in range(3):
            await pilot.pause()
        assert "PAIR-033" in "\n".join(painted_rows(app=app))
        row = named_row(app=app, literal="PAIR-033")
        assert scroll.scroll_x == x_target
        assert transcript._native_navigation is None
        later = await transcript.mount_assistant_block()
        later.set_answer(content="late tail")
        for _ in range(3):
            await pilot.pause()
        assert named_row(app=app, literal="PAIR-033") == row, (
            transcript._reading,
            transcript._reading_anchor,
            scroll.scroll_y,
            wide.region,
        )


@pytest.mark.parametrize("first", ["pageup", "end"])
async def test_programmatic_reveal_interrupts_pending_native_operation(first: str) -> None:
    """Public focus reveal interrupts pending native work without stranding settlement."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"FOCUS-{i:03}" for i in range(100)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        transcript.hold = {"_start_native_navigation"}
        scroll.focus()
        await pilot.press(first)
        block.focus()
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(duplicate=True)
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        assert transcript._native_navigation is None
        literal = next(line.strip() for line in painted_rows(app=app) if "FOCUS-" in line)
        row = named_row(app=app, literal=literal)
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        for _ in range(4):
            await pilot.pause()
        if first == "pageup":
            assert named_row(app=app, literal=literal) == row
        else:
            assert "END-MARKER" in "\n".join(painted_rows(app=app))


async def test_synchronous_notice_above_tree_keeps_reading_line() -> None:
    """A queued notice mount must finish layout before consuming the reading anchor."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        wide = Static("\n".join(f"NOTICE-{i:03}" for i in range(100)))
        wide.styles.height = 100
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        await pilot.press("pageup")
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        literal = next(line.strip() for line in painted_rows(app=app) if "NOTICE-" in line)
        row = named_row(app=app, literal=literal)
        transcript.write_transcript_line(content="new notice", classes="tool-result")
        for _ in range(4):
            await pilot.pause()
        assert named_row(app=app, literal=literal) == row
