"""Selection-highlight scroll tracking on the AI transcript surfaces (spec 72 follow-up).

Root cause established by investigation: Textual 8.2.8's
``RichVisual.render_strips`` silently drops the render-time selection option, so
the markdown-backed answer surface (``AssistantAnswerBody``) and thinking
surface (``AssistantThinkingBody``) never painted the mouse-selection highlight
into their strips, and the compositor cannot map pointer coordinates back to
content offsets on Rich-rendered strips (no offset meta), so a drag falls back
to a whole-widget ``SELECT_ALL`` entry. The app-side mitigation is
``SelectableRichVisual``: it re-applies the selection span to the rendered
strips in content coordinates, baking the highlight into the widget's own
strips so it tracks the selected content exactly across parent scrolls.

The compositor-level tests in this file fail on the pre-fix behavior (no
highlight painted anywhere on the two AI surfaces) and pin the approved UX:
a drag over an answer or thinking body highlights the whole body — the same
span that copy extracts — and the highlight follows the text when the
transcript scrolls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.color import Color
from rich.markdown import Markdown
from rich.padding import Padding
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual.strip import Strip
from textual.style import Style as TextualStyle
from textual.visual import Visual
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import (
    AssistantStreamThinkingBlock,
    AssistantThinkingBody,
)
from src.tui.widgets.selectable_rich_visual import SelectableRichVisual


def _build_session() -> SloAgentSession:
    """Build a faux-model session for the selection-highlight tests.

    Returns:
        SloAgentSession: Session driven by a faux assistant response.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _selection_background(*, app: SloTUI) -> Color:
    """Resolve the selection background through the same path the painter uses.

    ``Visual.to_strips`` derives the selection style via
    ``Style.from_styles(screen.get_component_styles("screen--selection"))``;
    mirroring that path keeps the assertion robust across themes.

    Args:
        app (SloTUI): The running app.

    Returns:
        Color: The resolved selection background color.
    """
    style: TextualStyle = TextualStyle.from_styles(app.screen.get_component_styles("screen--selection"))
    background: Optional[Color] = style.rich_style.bgcolor
    assert background is not None
    return background


def _selection_foreground(*, app: SloTUI) -> Color:
    """Resolve the selection foreground through the same painter path.

    Args:
        app (SloTUI): The running app.

    Returns:
        Color: The resolved selection foreground color.
    """
    style: TextualStyle = TextualStyle.from_styles(app.screen.get_component_styles("screen--selection"))
    foreground: Optional[Color] = style.rich_style.color
    assert foreground is not None, "selection foreground must be an explicit readable color"
    return foreground


def _rows_with_background(*, app: SloTUI, background: Color) -> list[int]:
    """Return the screen rows containing at least one cell with ``background``.

    Args:
        app (SloTUI): The running app.
        background (Color): The background color to scan for.

    Returns:
        list[int]: Sorted screen row indices carrying the background.
    """
    width, height = app.screen.size
    rows: list[int] = []
    for y in range(height):
        for x in range(width):
            if app.screen.get_style_at(x=x, y=y).bgcolor == background:
                rows.append(y)
                break
    return rows


def _strip_segments_with_background(*, strip: Strip, background: Color) -> str:
    """Concatenate the text of a strip's segments carrying ``background``.

    Args:
        strip (Strip): The strip to inspect.
        background (Color): The background color to match.

    Returns:
        str: The highlighted text within the strip.
    """
    return "".join(
        segment.text for segment in strip if segment.style is not None and segment.style.bgcolor == background
    )


class TestSelectableRichVisual:
    """Decision-path tests for the selection-paint visual wrapper."""

    @pytest.mark.asyncio
    async def test_render_without_selection_paints_nothing(self) -> None:
        """No selection targeting the widget leaves every strip unhighlighted."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            body: Static = Static()
            await app.mount(body)
            renderable = Padding(renderable=Markdown("alpha bravo"), pad=(1, 0, 1, 0))
            body.update(renderable)
            await pilot.pause()

            visual: Visual = SelectableRichVisual(widget=body, renderable=renderable)
            strips: list[Strip] = Visual.to_strips(
                widget=body,
                visual=visual,
                width=40,
                height=None,
                style=body.visual_style,
            )

            selection_bg: Color = _selection_background(app=app)
            assert strips
            for strip in strips:
                assert _strip_segments_with_background(strip=strip, background=selection_bg) == ""

    @pytest.mark.asyncio
    async def test_select_all_paints_text_lines_to_text_extent(self) -> None:
        """``SELECT_ALL`` highlights text lines exactly up to their text extent."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            body: Static = Static()
            await app.mount(body)
            renderable = Padding(renderable=Markdown("alpha bravo"), pad=(1, 0, 1, 0))
            body.update(renderable)
            app.screen.selections = {body: SELECT_ALL}
            await pilot.pause()

            visual: Visual = SelectableRichVisual(widget=body, renderable=renderable)
            strips: list[Strip] = Visual.to_strips(
                widget=body,
                visual=visual,
                width=40,
                height=None,
                style=body.visual_style,
            )

            selection_bg: Color = _selection_background(app=app)
            highlighted: dict[str, str] = {
                strip.text.rstrip(): _strip_segments_with_background(strip=strip, background=selection_bg)
                for strip in strips
            }
            assert highlighted.get("alpha bravo") == "alpha bravo"
            for text, painted in highlighted.items():
                if text != "alpha bravo":
                    assert painted == ""

    @pytest.mark.asyncio
    async def test_partial_selection_paints_only_spanned_lines_and_cells(self) -> None:
        """A ranged selection highlights only the spanned lines and cells."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            body: Static = Static()
            await app.mount(body)
            renderable = Padding(renderable=Markdown("alpha bravo\n\ncharlie delta"), pad=(1, 0, 1, 0))
            body.update(renderable)
            await pilot.pause()

            layout_visual: Visual = SelectableRichVisual(widget=body, renderable=renderable)
            layout_strips: list[Strip] = Visual.to_strips(
                widget=body,
                visual=layout_visual,
                width=40,
                height=None,
                style=body.visual_style,
            )
            first_text_line: int = next(
                index for index, strip in enumerate(layout_strips) if strip.text.strip()
            )
            app.screen.selections = {
                body: Selection(
                    start=Offset(x=0, y=first_text_line),
                    end=Offset(x=3, y=first_text_line + 2),
                )
            }
            await pilot.pause()

            visual: Visual = SelectableRichVisual(widget=body, renderable=renderable)
            strips: list[Strip] = Visual.to_strips(
                widget=body,
                visual=visual,
                width=40,
                height=None,
                style=body.visual_style,
            )

            selection_bg: Color = _selection_background(app=app)
            painted_by_text: dict[str, str] = {
                strip.text.rstrip(): _strip_segments_with_background(strip=strip, background=selection_bg)
                for strip in strips
            }
            assert painted_by_text.get("alpha bravo") == "alpha bravo"
            assert painted_by_text.get("charlie delta") == "cha"
            for text, painted in painted_by_text.items():
                if text not in {"alpha bravo", "charlie delta"}:
                    assert painted == ""

    @pytest.mark.asyncio
    async def test_empty_span_paints_nothing(self) -> None:
        """A zero-width selection span leaves the line unhighlighted."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            body: Static = Static()
            await app.mount(body)
            renderable = Padding(renderable=Markdown("alpha bravo"), pad=(1, 0, 1, 0))
            body.update(renderable)
            app.screen.selections = {body: Selection(start=Offset(x=2, y=1), end=Offset(x=2, y=1))}
            await pilot.pause()

            visual: Visual = SelectableRichVisual(widget=body, renderable=renderable)
            strips: list[Strip] = Visual.to_strips(
                widget=body,
                visual=visual,
                width=40,
                height=None,
                style=body.visual_style,
            )

            selection_bg: Color = _selection_background(app=app)
            for strip in strips:
                assert _strip_segments_with_background(strip=strip, background=selection_bg) == ""


class TestAssistantThinkingBodySelection:
    """``AssistantThinkingBody.get_selection`` extraction seam."""

    def test_get_selection_returns_none_without_text(self) -> None:
        """An empty thinking surface serves no selection text."""
        body: AssistantThinkingBody = AssistantThinkingBody()

        assert body.get_selection(SELECT_ALL) is None

    def test_get_selection_extracts_full_text_for_select_all(self) -> None:
        """``SELECT_ALL`` extracts the entire raw reasoning buffer."""
        body: AssistantThinkingBody = AssistantThinkingBody()
        body.set_source_text(text="ponder alpha beta")

        extracted: Optional[tuple[str, str]] = body.get_selection(SELECT_ALL)

        assert extracted == ("ponder alpha beta", "\n")

    def test_get_selection_extracts_partial_span(self) -> None:
        """A ranged selection extracts only the spanned reasoning slice."""
        body: AssistantThinkingBody = AssistantThinkingBody()
        body.set_source_text(text="ponder alpha beta")

        extracted: Optional[tuple[str, str]] = body.get_selection(
            Selection(start=Offset(x=0, y=0), end=Offset(x=6, y=0))
        )

        assert extracted == ("ponder", "\n")


class TestSelectionHighlightTracksScroll:
    """Compositor-level acceptance: highlight stays attached across scrolls."""

    @pytest.mark.asyncio
    async def test_answer_block_selection_highlight_tracks_scroll(self) -> None:
        """A drag over an answer body paints the highlight and scrolls it with the text.

        Fails on the pre-fix behavior, where the RichVisual-backed answer
        surface painted no selection highlight at all.
        """
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for index in range(30):
                app._write_adapter_line(content=f"filler line {index}", classes="tool-result")
            block: AssistantStreamBlock = await app.mount_assistant_block()
            block.finalize(final_text="alpha bravo charlie delta echo foxtrot")
            for index in range(30, 60):
                app._write_adapter_line(content=f"filler line {index}", classes="tool-result")
            await pilot.pause(delay=0.2)
            block.scroll_visible(animate=False)
            await pilot.pause(delay=0.2)

            region = block.region
            anchor: tuple[int, int] = (region.x + 5, region.y + 1)
            base_bg: Optional[Color] = app.screen.get_style_at(x=anchor[0], y=anchor[1]).bgcolor
            await pilot.mouse_down(offset=(region.x + 1, region.y + 1))
            await pilot.hover(offset=(region.x + 20, region.y + 1))
            await pilot.mouse_up(offset=(region.x + 20, region.y + 1))
            await pilot.pause()

            selection_bg: Color = _selection_background(app=app)
            selection_fg: Color = _selection_foreground(app=app)
            highlighted = app.screen.get_style_at(x=anchor[0], y=anchor[1])
            assert highlighted.bgcolor == selection_bg
            assert selection_bg != base_bg
            assert highlighted.color == selection_fg
            assert highlighted.color != highlighted.bgcolor
            selection: Optional[str] = app.screen.get_selected_text()
            assert selection is not None and "alpha bravo charlie" in selection
            rows_before: list[int] = _rows_with_background(app=app, background=selection_bg)
            assert rows_before, "selection highlight must be painted over the answer text"

            assert app._transcript_scroll is not None
            scroll_before: float = app._transcript_scroll.scroll_y
            app._transcript_scroll.scroll_to(y=scroll_before + 3, animate=False)
            await pilot.pause(delay=0.3)
            scroll_after: float = app._transcript_scroll.scroll_y

            rows_after: list[int] = _rows_with_background(app=app, background=selection_bg)
            scroll_delta: int = int(round(scroll_after - scroll_before))
            assert scroll_delta == 3
            assert rows_after == [row - scroll_delta for row in rows_before]
            assert rows_after == [block.region.y + 1]

    @pytest.mark.asyncio
    async def test_thinking_block_selection_highlight_tracks_scroll(self) -> None:
        """A drag over a thinking body paints the highlight and scrolls it with the text.

        Fails on the pre-fix behavior, where the RichVisual-backed thinking
        surface painted no selection highlight and extracted no text at all.
        """
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for index in range(30):
                app._write_adapter_line(content=f"filler line {index}", classes="tool-result")
            block: AssistantStreamThinkingBlock = await app.mount_thinking_block()
            block.set_thinking(content="ponder alpha beta gamma delta")
            block.seal()
            for index in range(30, 60):
                app._write_adapter_line(content=f"filler line {index}", classes="tool-result")
            await pilot.pause(delay=0.2)
            block.scroll_visible(animate=False)
            await pilot.pause(delay=0.2)

            body: AssistantThinkingBody = block._body
            region = body.region
            anchor: tuple[int, int] = (region.x + 5, region.y + 1)
            base_bg: Optional[Color] = app.screen.get_style_at(x=anchor[0], y=anchor[1]).bgcolor
            await pilot.mouse_down(offset=(region.x + 1, region.y + 1))
            await pilot.hover(offset=(region.x + 15, region.y + 1))
            await pilot.mouse_up(offset=(region.x + 15, region.y + 1))
            await pilot.pause()

            selection_bg: Color = _selection_background(app=app)
            assert app.screen.get_style_at(x=anchor[0], y=anchor[1]).bgcolor == selection_bg
            assert selection_bg != base_bg
            selection: Optional[str] = app.screen.get_selected_text()
            assert selection is not None and "ponder alpha beta" in selection
            rows_before: list[int] = _rows_with_background(app=app, background=selection_bg)
            assert rows_before, "selection highlight must be painted over the thinking text"

            assert app._transcript_scroll is not None
            scroll_before: float = app._transcript_scroll.scroll_y
            app._transcript_scroll.scroll_to(y=scroll_before - 3, animate=False)
            await pilot.pause(delay=0.3)
            scroll_after: float = app._transcript_scroll.scroll_y

            rows_after: list[int] = _rows_with_background(app=app, background=selection_bg)
            scroll_delta: int = int(round(scroll_after - scroll_before))
            assert scroll_delta == -3
            assert rows_after == [row - scroll_delta for row in rows_before]
            assert rows_after == [body.region.y + 1]
