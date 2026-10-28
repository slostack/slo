"""Final bounded callback and native-motion acceptance cases for Feature 96."""

import asyncio

import pytest

from src.tui.components.chat_transcript.component import TranscriptScroll
from tests.tui.test_chat_transcript import TranscriptTestApp
from tests.tui.test_chat_transcript_navigation import OrderedTranscript, named_row, painted_rows


@pytest.mark.parametrize("first,second", [("pageup", "end"), ("end", "pageup")])
async def test_native_supersession_during_observed_motion(first: str, second: str) -> None:
    """Deliver the second native key between observed start and destination arrival."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"MIDDLE-{i:03}" for i in range(150)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        for _ in range(4):
            await pilot.pause()
        scroll.scroll_to(y=100, animate=False, immediate=True)
        await pilot.pause()
        origin = scroll.scroll_y
        first_key = asyncio.create_task(pilot.press(first))
        async with asyncio.timeout(3):
            while scroll.scroll_y == origin:
                await asyncio.sleep(0.001)
        operation = transcript._native_navigation
        assert operation is not None and operation.request.y is not None
        assert abs(scroll.scroll_y - operation.request.y) > 0.01
        await pilot.press(second)
        await first_key
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        literal = next(line.strip() for line in painted_rows(app=app) if "MIDDLE-" in line)
        row = named_row(app=app, literal=literal)
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        for _ in range(4):
            await pilot.pause()
        if second == "end":
            assert "END-MARKER" in "\n".join(painted_rows(app=app))
        else:
            assert named_row(app=app, literal=literal) == row
            assert "END-MARKER" not in "\n".join(painted_rows(app=app))
        assert transcript._native_navigation is None


@pytest.mark.parametrize("reset", ["hide", "clear", "echo"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_old_show_callbacks_do_not_override_current_intent(reset: str, reverse: bool) -> None:
    """Hold show layout, supersede its lifetime/intent, and deliver duplicates in either order."""
    transcript = OrderedTranscript()
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.set_answer(content="\n\n".join(f"SHOW-{i:03}" for i in range(100)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        await pilot.press("pageup")
        await pilot.wait_for_scheduled_animations()
        for _ in range(4):
            await pilot.pause()
        literal = next(line.strip() for line in painted_rows(app=app) if "SHOW-" in line)
        row = named_row(app=app, literal=literal)
        transcript.hold = {"_resume_visible_layout"}
        transcript.set_visible(visible=False)
        transcript.set_visible(visible=True)
        assert transcript.calls
        if reset == "hide":
            transcript.set_visible(visible=False)
            transcript.set_visible(visible=True)
        elif reset == "clear":
            await transcript.clear()
            block = await transcript.mount_assistant_block()
        else:
            await transcript.echo_user(text="NEW-USER")
        block.set_answer(content=block.get_copyable_text() + "\n\nEND-MARKER")
        await pilot.pause()
        transcript.hold.clear()
        while transcript.calls:
            transcript.release_at(index=-1 if reverse else 0, duplicate=True)
        for _ in range(4):
            await pilot.pause()
        if reset == "hide":
            assert named_row(app=app, literal=literal) == row
        elif reset == "clear":
            assert "END-MARKER" in "\n".join(painted_rows(app=app))
            assert "SHOW-" not in "\n".join(painted_rows(app=app))
        else:
            assert "NEW-USER" in "\n".join(painted_rows(app=app))
