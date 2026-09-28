"""Native visible-buffer selection, paint, and scrolling evidence for transcript bodies."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.widget import Widget
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.color import Color
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual.style import Style as TextualStyle

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantAnswerBody, AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import (
    AssistantStreamThinkingBlock,
    AssistantThinkingBody,
)
from src.tui.widgets.user_message_block import UserMessageBlock


def _build_session() -> SloAgentSession:
    """Build a deterministic session for Textual Pilot tests."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _selection_background(*, app: SloTUI) -> Color:
    """Resolve native selection background color from the active screen component."""
    style = TextualStyle.from_styles(app.screen.get_component_styles("screen--selection"))
    assert style.rich_style.bgcolor is not None
    return style.rich_style.bgcolor


def _location_for_offset(*, app: SloTUI, body: Widget, target: Offset) -> tuple[int, int]:
    """Find a post-layout screen coordinate for one native Content offset."""
    region = body.region
    for y in range(region.y, region.bottom):
        for x in range(region.x, region.right):
            widget, offset = app.screen.get_widget_and_offset_at(x=x, y=y)
            if widget is body and offset == target:
                return x, y
    raise AssertionError(f"offset {target} was not visible")


class TestVisibleBufferSelection:
    """Body extraction indexes visible compiled text instead of raw Markdown."""

    def test_answer_and_thinking_extract_visible_ranges(self) -> None:
        """Both AI body classes use their visible compiler buffers for native extraction."""
        answer = AssistantAnswerBody()
        answer.show_answer(text="# alpha bravo")
        thinking = AssistantThinkingBody()
        thinking.set_source_text(text="**alpha bravo**")
        selection = Selection(start=Offset(x=6, y=0), end=Offset(x=11, y=0))
        assert answer.get_selection(selection) == ("bravo", "\n")
        assert thinking.get_selection(Selection(start=Offset(x=0, y=0), end=Offset(x=5, y=0))) == (
            "alpha",
            "\n",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["# heading", "- item", "`code`", "```python\nvalue = 1\n```"])
    async def test_compositor_offsets_belong_to_visible_text(self, raw: str) -> None:
        """Every rendered body offset, including a valid line endpoint, indexes visible text."""
        app = SloTUI(session=_build_session())
        async with app.run_test(size=(80, 24)) as pilot:
            body = AssistantAnswerBody()
            await app.mount(body)
            body.show_answer(text=raw)
            await pilot.pause()
            visible = body._visible_text
            start = _location_for_offset(app=app, body=body, target=Offset(x=0, y=0))
            end = _location_for_offset(app=app, body=body, target=Offset(x=len(visible.splitlines()[0]), y=0))
            assert start != end
            assert visible not in {"# heading", "- item", "`code`", "```python\nvalue = 1\n```"}


class TestPilotVisibleSelection:
    """Actual mouse drags select, paint, and scroll compiler visible strings."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["answer", "thinking", "user"])
    async def test_drag_copies_exact_visible_substring(self, kind: str) -> None:
        """A Pilot drag selects a bounded visible substring for every textual body kind."""
        app = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            if kind == "answer":
                answer_block: AssistantStreamBlock = await app.mount_assistant_block()
                answer_block.finalize(final_text="# alpha bravo charlie")
                body: Widget = answer_block._answer_body
            elif kind == "thinking":
                thinking_block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
                thinking_block.set_thinking(content="# alpha bravo charlie")
                body = thinking_block._body
            else:
                user_block: UserMessageBlock = await app.mount_user_message_block(
                    text="# alpha bravo charlie"
                )
                body = user_block._body
            await pilot.pause(delay=0.1)
            start = _location_for_offset(app=app, body=body, target=Offset(x=6, y=0))
            end = _location_for_offset(app=app, body=body, target=Offset(x=10, y=0))
            await pilot.mouse_down(offset=start)
            await pilot.hover(offset=end)
            await pilot.mouse_up(offset=end)
            await pilot.pause()
            assert app.screen.get_selected_text() == "bravo"
            assert app._clipboard == "bravo"
            assert app.screen.selections[body] != SELECT_ALL

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["answer", "thinking", "user"])
    @pytest.mark.parametrize("theme_name", ["slo-default", "slo-dark"])
    async def test_selection_paint_and_scroll_remain_native_for_every_visible_body_and_theme(
        self, kind: str, theme_name: str
    ) -> None:
        """Native selection paint and range state remain scroll-attached in both Slo themes."""
        app = SloTUI(session=_build_session())
        async with app.run_test(size=(80, 24)) as pilot:
            app.theme = theme_name
            for index in range(20):
                app._write_adapter_line(content=f"filler {index}", classes="tool-result")
            if kind == "answer":
                answer_block: AssistantStreamBlock = await app.mount_assistant_block()
                answer_block.finalize(final_text="# alpha bravo charlie")
                block: Widget = answer_block
                body: Widget = answer_block._answer_body
            elif kind == "thinking":
                thinking_block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
                thinking_block.set_thinking(content="# alpha bravo charlie")
                block = thinking_block
                body = thinking_block._body
            else:
                user_block: UserMessageBlock = await app.mount_user_message_block(
                    text="# alpha bravo charlie"
                )
                block = user_block
                body = user_block._body
            for index in range(20, 40):
                app._write_adapter_line(content=f"filler {index}", classes="tool-result")
            await pilot.pause(delay=0.1)
            block.scroll_visible(animate=False)
            await pilot.pause(delay=0.1)
            if kind == "user":
                block.scroll_visible(top=True, animate=False)
                await pilot.pause(delay=0.1)
            start = _location_for_offset(app=app, body=body, target=Offset(x=6, y=0))
            end = _location_for_offset(app=app, body=body, target=Offset(x=10, y=0))
            await pilot.mouse_down(offset=start)
            await pilot.hover(offset=end)
            await pilot.mouse_up(offset=end)
            await pilot.pause()
            background = _selection_background(app=app)
            assert app.screen.get_style_at(x=start[0], y=start[1]).bgcolor == background
            assert app._transcript_scroll is not None
            before = app._transcript_scroll.scroll_y
            app._transcript_scroll.scroll_to(y=before - 2, animate=False)
            await pilot.pause(delay=0.2)
            assert app.screen.get_selected_text() == "bravo"
