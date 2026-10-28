"""Bounded remaining Feature 96 interaction proofs using existing Pilot facilities."""

import asyncio
from pathlib import Path

import pytest
from textual import events
from textual.widgets import Static
from textual.theme import Theme

from src.tui.theme import SLO_DEFAULT_THEME, SLO_DARK_THEME

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.components.chat_transcript.component import ChatTranscript, TranscriptScroll
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from tests.tui.test_chat_transcript import TranscriptTestApp, seed_history
from tests.tui.test_chat_transcript_navigation import OrderedTranscript, named_row, painted_rows


class HiddenPrependTranscript(ChatTranscript):
    """Hide at the actual first prepend mount and optionally fail the next mount."""

    prepend_mounts = 0
    fail_prepend = False

    async def mount_assistant_block(
        self, *, before: int | None = None, title_prefix: str | None = None
    ) -> AssistantStreamBlock:
        """Keep the published prefix and exercise the real partial-failure policy."""
        if before is not None:
            self.prepend_mounts += 1
            if self.fail_prepend and self.prepend_mounts == 2:
                raise RuntimeError("controlled projection failure")
        block = await super().mount_assistant_block(before=before, title_prefix=title_prefix)
        if before is not None and self.prepend_mounts == 1:
            self.set_visible(visible=False)
        return block


@pytest.mark.parametrize("theme", [SLO_DEFAULT_THEME, SLO_DARK_THEME])
@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
@pytest.mark.parametrize("prepend_mode", ["hidden", "first_mount", "partial"])
@pytest.mark.parametrize("growth_first", [False, True])
async def test_hidden_real_prepend_and_upper_growth(
    tmp_path: Path, growth_first: bool, prepend_mode: str, theme: Theme, size: tuple[int, int]
) -> None:
    """Both hidden mutation orders preserve a nonfirst line and canonical bytes."""
    entries = await seed_history(root=tmp_path, count=95)
    before = (tmp_path / "seed" / "events.jsonl").read_bytes()
    entered, release = asyncio.Event(), asyncio.Event()
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Gate older publication, keeping real-store canonical entries."""
        nonlocal reads
        reads += 1
        if reads > 1:
            entered.set()
            await release.wait()
        return entries

    transcript = HiddenPrependTranscript(history_reader=reader)
    transcript.fail_prepend = prepend_mode == "partial"
    app = TranscriptTestApp(transcript=transcript)
    app.register_theme(theme)
    app.theme = theme.name
    async with app.run_test(size=size) as pilot:
        await transcript.hydrate()
        transcript.begin_run()
        await transcript.present_event(
            event=AgentStreamEventDAO(kind="thinking_delta", block_id="upper", content="thought", iteration=1)
        )
        await transcript.present_event(
            event=AgentStreamEventDAO(kind="text_delta", content="answer", iteration=1)
        )
        await transcript.echo_user(text="\n\n".join(f"READ-LATER-{i:02}" for i in range(60)))
        scroll = transcript.query_one(TranscriptScroll)
        # Reading starts only after the real append/layout pin has settled.
        # A single pause can leave PageUp targeting the pre-append viewport.
        async with asyncio.timeout(5):
            while True:
                await pilot.pause()
                if (
                    transcript._active_pin is None
                    and scroll.scroll_y == scroll.max_scroll_y
                    and any("READ-LATER" in line for line in painted_rows(app=app))
                ):
                    break
        scroll.focus()
        await pilot.press("pageup")
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        literal = next(line.strip() for line in painted_rows(app=app) if "READ-LATER" in line)
        row = named_row(app=app, literal=literal)
        old_y = scroll.scroll_y
        older = asyncio.create_task(transcript.load_older())
        await asyncio.wait_for(entered.wait(), timeout=5)
        if prepend_mode == "hidden":
            transcript.set_visible(visible=False)

        async def grow() -> None:
            """Mutate both existing upper stream blocks through their real event route."""
            await transcript.present_event(
                event=AgentStreamEventDAO(
                    kind="thinking_delta",
                    block_id="upper",
                    content="\n\n".join(f"thought-{i}" for i in range(20)),
                    iteration=1,
                )
            )
            await transcript.present_event(
                event=AgentStreamEventDAO(
                    kind="text_delta", content="\n\n".join(f"answer-{i}" for i in range(20)), iteration=1
                )
            )
            await pilot.pause()

        if growth_first:
            await grow()
        release.set()
        await asyncio.wait_for(older, timeout=5)
        if not growth_first:
            await grow()
        transcript.set_visible(visible=True)
        for _ in range(3):
            await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert scroll.scroll_y != old_y
        assert reads == 2
        replay = [
            b.get_copyable_text()
            for b in transcript.query(AssistantStreamBlock)
            if b.get_copyable_text().startswith("entry-")
        ]
        expected = [35, *range(65, 95)] if prepend_mode == "partial" else range(35, 95)
        assert replay == [f"entry-{i:02}" for i in expected]
        if prepend_mode == "partial":
            await transcript.load_older()
            assert reads == 2
            assert "partially displayed" in str(transcript.query_one("#transcript-earlier-summary").render())
    assert (tmp_path / "seed" / "events.jsonl").read_bytes() == before


class EmptyPrependTranscript(ChatTranscript):
    """Observe the real sentinel and append a tail notice during the first mount."""

    saw_sentinel = False

    async def mount_assistant_block(
        self, *, before: int | None = None, title_prefix: str | None = None
    ) -> AssistantStreamBlock:
        """Use the existing host seam; preserve all production projection behavior."""
        block = await super().mount_assistant_block(before=before, title_prefix=title_prefix)
        if before is not None and not self.saw_sentinel:
            sentinel = self.query_one(".transcript-prepend-boundary")
            assert not sentinel.can_focus
            self.saw_sentinel = True
            self.workflow_notice.write(content="concurrent tail", classes="tool-result")
        return block


async def test_empty_content_prepend_removes_sentinel(tmp_path: Path) -> None:
    """Public removal of the tail leaves an empty-content older insertion boundary."""
    entries = await seed_history(root=tmp_path, count=35)

    async def reader() -> list[TranscriptEntryDAO]:
        """Return canonical replay entries without writing history."""
        return entries

    transcript = EmptyPrependTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        transcript.set_visible(visible=False)
        for child in tuple(transcript.query_one("#transcript-content").children):
            if child.id != "transcript-earlier-summary":
                await child.remove()
        transcript.set_visible(visible=True)
        await transcript.load_older()
        await pilot.pause()
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == [
            f"entry-{i:02}" for i in range(5)
        ]
        assert transcript.saw_sentinel
        assert not transcript.query(".transcript-prepend-boundary")
        assert transcript.logical_copy_text().count("concurrent tail") == 1
        assert "concurrent tail" in str(transcript.query_one("#transcript-content").children[-1].render())


class HeldRenderedTranscript(OrderedTranscript):
    """Hold one genuine widget notification at the existing message handler seam."""

    armed = False
    captured: AssistantStreamBlock.Rendered | None = None

    def on_assistant_stream_block_rendered(self, message: AssistantStreamBlock.Rendered) -> None:
        """Retain the actual source and snapshot, never manufacture either."""
        if self.armed and self.captured is None:
            message.stop()
            self.captured = message
            return
        super().on_assistant_stream_block_rendered(message)

    def release_rendered(self) -> None:
        """Deliver the original notification after intervening native input."""
        assert self.captured is not None
        super().on_assistant_stream_block_rendered(self.captured)
        self.captured = None
        self.armed = False


@pytest.mark.parametrize(
    "input_kind",
    [
        "wheel_up",
        "wheel_down",
        "up",
        "down",
        "pageup",
        "pagedown",
        "home",
        "end",
        "track_up",
        "track_down",
        "drag",
    ],
)
async def test_genuine_stale_rendered_after_native_wheel(input_kind: str) -> None:
    """A delayed following snapshot cannot undo real wheel input; echo can rearm."""
    transcript = HeldRenderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"RACE-{i:03}" for i in range(100)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        for _ in range(4):
            await pilot.pause()
        transcript.armed = True
        block.set_answer(content=block.get_copyable_text() + "\n\nTAIL")
        await pilot.pause()
        assert transcript.captured is not None and transcript.captured.snapshot.was_following
        if input_kind == "up":
            await pilot.press("pageup")
            await pilot.wait_for_scheduled_animations()
            for _ in range(4):
                await pilot.pause()
        if input_kind.startswith("wheel"):
            event_type = events.MouseScrollUp if input_kind == "wheel_up" else events.MouseScrollDown
            block.post_message(
                event_type(
                    widget=block,
                    x=3,
                    y=3,
                    delta_x=0,
                    delta_y=1,
                    button=0,
                    shift=False,
                    meta=False,
                    ctrl=False,
                )
            )
        elif input_kind.startswith("track"):
            bar = scroll.vertical_scrollbar
            await pilot.click(widget=bar, offset=(0, 1 if input_kind == "track_up" else bar.size.height - 2))
        elif input_kind == "drag":
            bar = scroll.vertical_scrollbar
            await pilot.mouse_down(widget=bar, offset=(0, bar.size.height - 2))
            await pilot.hover(widget=bar, offset=(0, bar.size.height // 2))
            await pilot.mouse_up(widget=bar, offset=(0, bar.size.height // 2))
        else:
            await pilot.press(input_kind)
        for _ in range(4):
            await pilot.pause()
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        literal = next(line.strip() for line in painted_rows(app=app) if "RACE-" in line)
        row = named_row(app=app, literal=literal)
        transcript.release_rendered()
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        for _ in range(4):
            await pilot.pause()
        if input_kind in {"wheel_down", "down", "pagedown", "end", "track_down"}:
            assert "END-MARKER" in "\n".join(painted_rows(app=app))
        else:
            assert named_row(app=app, literal=literal) == row
        await transcript.echo_user(text="NEW-USER")
        for _ in range(4):
            await pilot.pause()
        assert "NEW-USER" in "\n".join(painted_rows(app=app))


@pytest.mark.parametrize("interruption", ["right", "hide", "home"])
async def test_public_animation_interrupted_while_actually_moving(interruption: str) -> None:
    """Observe a genuine intermediate frame before x input, hide, or edge Home."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        wide = Static("\n".join(f"MOTION-{i:03} " * 24 for i in range(160)))
        wide.styles.width = 300
        wide.styles.height = 160
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.scroll_to(x=0, y=0, animate=False, immediate=True)
        await pilot.pause()
        scroll.focus()
        for _ in range(4):
            await pilot.pause()
        scroll.scroll_to(x=0, y=0, animate=False, immediate=True)
        await pilot.pause()
        # Public duration makes the intermediate state observable without replacing the animator.
        scroll.scroll_to(x=100, y=None if interruption == "home" else 100, duration=1.0, immediate=True)
        async with asyncio.timeout(3):
            while not 0 < scroll.scroll_x < 100:
                await asyncio.sleep(0.005)
        assert 0 < scroll.scroll_x < 100
        if interruption != "home":
            assert 0 < scroll.scroll_y < 100
        await pilot.pause()
        before = painted_rows(app=app)
        literal = next(
            word for line in before for word in line.split() if word.startswith("MOTION-") and len(word) == 10
        )
        row = named_row(app=app, literal=literal)
        if interruption == "hide":
            transcript.set_visible(visible=False)
            transcript.set_visible(visible=True)
        else:
            await pilot.press(interruption)
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        assert named_row(app=app, literal=literal) == row
        assert transcript._native_navigation is None
