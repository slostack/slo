"""Tests for the mermaid chart card, its source surface, and its source screen (spec 77.a.2).

Interaction claims here are proven by driving the interaction: the selection
claim drags a real mouse through a pilot and the dismissal claim presses a real
key, because calling ``get_selection`` or an action method directly passes
whether or not the behaviour is reachable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.color import Color
from rich.console import Console, Group
from rich.rule import Rule
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text
from textual.selection import SELECT_ALL
from textual.style import Style as TextualStyle
from textual.widget import Widget
from textual.widgets import Static, TextArea

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.mermaid_chart_source_screen import MermaidChartSourceScreen
from src.tui.mermaid_lexer import MermaidLexer
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.mermaid_chart_block import MermaidChartBlock, MermaidChartSurface
from tests.tui._scroll_settle import pump_until

_SAMPLE_SOURCE: str = 'graph TD\n  A[Start] --> B{Decision}\n  B -->|yes| C["Do it"]'
"""A small flowchart exercising directives, edges, nodes, and a quoted label."""


def _build_session() -> SloAgentSession:
    """Build a faux-model session for the pilot tests in this module.

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

    Args:
        app (SloTUI): The running app.

    Returns:
        Color: The resolved selection background colour.
    """
    style: TextualStyle = TextualStyle.from_styles(app.screen.get_component_styles("screen--selection"))
    background: Optional[Color] = style.rich_style.bgcolor
    assert background is not None
    return background


def _distinct_foreground_colors(*, source: str) -> set[str]:
    """Render mermaid source through the in-repo lexer and collect its colours.

    Args:
        source (str): Mermaid source to highlight.

    Returns:
        set[str]: Distinct foreground colour names on non-blank segments.
    """
    console: Console = Console(width=80, color_system="truecolor")
    highlighted: Syntax = Syntax(code=source, lexer=MermaidLexer(), background_color="default")
    segments: list[Segment] = list(console.render(highlighted))
    return {
        str(segment.style.color)
        for segment in segments
        if segment.text.strip() and segment.style is not None and segment.style.color is not None
    }


class TestMermaidLexerHighlighting:
    """The in-repo grammar actually colours mermaid source."""

    def test_source_is_highlighted_by_the_in_repo_lexer(self) -> None:
        """``Syntax`` driven by ``MermaidLexer`` emits more than one foreground colour.

        Pygments ships no mermaid lexer, so a ``mermaid`` → ``text`` fallback
        chain highlights nothing in either arm; this assertion is the one such
        a fallback test could never make.
        """
        colors: set[str] = _distinct_foreground_colors(source=_SAMPLE_SOURCE)

        assert len(colors) > 1


def _fallback_syntax(*, body: MermaidChartSurface) -> Syntax:
    """Return the highlighted source an undrawn card shows beneath its note.

    Args:
        body (MermaidChartSurface): The card's body region.

    Returns:
        Syntax: The source renderable under the reason line.
    """
    content = body.content
    assert isinstance(content, Group), "an undrawn card shows a note above its source"
    syntax = content.renderables[-1]
    assert isinstance(syntax, Syntax)
    return syntax


def _compose_regions(*, block: MermaidChartBlock) -> list[Widget]:
    """Build the card's three regions without mounting it in an app.

    Args:
        block (MermaidChartBlock): The card whose ``compose`` to drain.

    Returns:
        list[Widget]: Header, source surface, and caption, in compose order.
    """
    return list(block.compose())


class TestMermaidChartBlockComposition:
    """Directive extraction, the drawn body, and the caption line."""

    def test_directive_line_is_first_non_blank_line(self) -> None:
        """The header names the first non-blank source line, stripped."""
        block: MermaidChartBlock = MermaidChartBlock(source="\n\n   graph TD\n  A --> B\n")

        header, body, caption = _compose_regions(block=block)

        assert isinstance(header, Static)
        assert isinstance(header.content, Rule)
        assert header.content.title == "📊 Mermaid chart — graph TD"
        assert isinstance(body, MermaidChartSurface)
        assert isinstance(caption, LiteralTextStatic)

    def test_directive_line_defaults_for_blank_source(self) -> None:
        """A blank fence body falls back to the ``chart`` directive."""
        block: MermaidChartBlock = MermaidChartBlock(source="\n   \n\t\n")

        header, _body, caption = _compose_regions(block=block)

        assert isinstance(header, Static)
        assert isinstance(header.content, Rule)
        assert header.content.title == "📊 Mermaid chart — chart"
        assert "mermaid · chart · " in str(caption.content)

    def test_caption_names_the_full_screen_chord(self) -> None:
        """The caption advertises ``ctrl+f`` and never the swallowed bare ``f``."""
        block: MermaidChartBlock = MermaidChartBlock(source=_SAMPLE_SOURCE)

        _header, _body, caption = _compose_regions(block=block)
        caption_text: str = str(caption.content)

        assert caption_text == "mermaid · graph TD · 3 lines · ctrl+f for full screen"
        assert "ctrl+f" in caption_text
        assert "press f" not in caption_text
        assert "mermaid-chart-caption" in caption.classes

    def test_a_drawable_flowchart_body_shows_the_drawing_not_the_source(self) -> None:
        """A ``graph TD`` card draws boxes and arrows instead of printing code."""
        block: MermaidChartBlock = MermaidChartBlock(source=_SAMPLE_SOURCE)

        _header, body, _caption = _compose_regions(block=block)
        shown: str = str(body.content)

        assert "┌" in shown and "▼" in shown
        assert "-->" not in shown, "the raw arrow syntax must not reach the drawn body"

    def test_an_undrawable_diagram_shows_a_reason_above_its_highlighted_source(self) -> None:
        """A sequence diagram cannot be drawn, so the card falls back to source."""
        source: str = "sequenceDiagram\n  A->>B: hi\n"
        block: MermaidChartBlock = MermaidChartBlock(source=source)

        _header, body, _caption = _compose_regions(block=block)
        note: str = str(body.content.renderables[0])

        assert "only graph and flowchart diagrams are drawn" in note
        assert "showing the source instead" in note
        assert _fallback_syntax(body=body).code == source

    def test_a_looping_diagram_names_the_loop_and_keeps_its_source(self) -> None:
        """A cyclic flowchart is declined with the reason, not drawn wrongly."""
        source: str = "graph TD\n A --> B\n B --> A\n"
        block: MermaidChartBlock = MermaidChartBlock(source=source)

        _header, body, _caption = _compose_regions(block=block)

        assert "loop" in str(body.content.renderables[0])
        assert _fallback_syntax(body=body).code == source

    def test_an_undrawable_card_still_carries_the_whole_source(self) -> None:
        """Declining to draw never costs the reader the source itself.

        The selection seam trims the fence body's trailing newline, which is
        why it is compared against ``rstrip``; the copy chord and the
        ``source`` property both still carry the bytes verbatim.
        """
        source: str = "sequenceDiagram\n  A->>B: hi\n"

        block: MermaidChartBlock = MermaidChartBlock(source=source)
        _header, body, _caption = _compose_regions(block=block)

        assert block.source == source
        assert block.get_copyable_text() == source
        assert body.get_selection(SELECT_ALL) == (source.rstrip("\n"), "\n")

    def test_an_undrawn_source_at_the_cap_is_shown_whole(self) -> None:
        """An undrawn fence at the line cap keeps every line, caption unqualified."""
        source: str = "\n".join(f"  A{index} --> B{index}" for index in range(150))

        block: MermaidChartBlock = MermaidChartBlock(source=source)
        _header, body, caption = _compose_regions(block=block)

        assert _fallback_syntax(body=body).code == source
        assert str(caption.content).endswith("150 lines · ctrl+f for full screen")
        assert "showing" not in str(caption.content)

    def test_an_undrawn_source_over_the_cap_is_previewed_and_the_caption_says_so(self) -> None:
        """An oversized undrawn fence previews 40 lines while ``source`` stays whole."""
        lines: list[str] = [f"  A{index} --> B{index}" for index in range(200)]
        source: str = "\n".join(lines)

        block: MermaidChartBlock = MermaidChartBlock(source=source)
        _header, body, caption = _compose_regions(block=block)

        assert _fallback_syntax(body=body).code == "\n".join(lines[:40])
        assert str(caption.content).endswith("showing 40 of 200 lines — ctrl+f for full source")
        assert block.source == source

    def test_a_drawn_card_never_shows_a_truncation_note(self) -> None:
        """A drawn diagram shows no source, so the caption never counts lines off.

        The source is padded past the preview cap with ``%%`` comment lines,
        which the parser drops — so the fence stays small enough to draw
        while its line count sits well over the cap.
        """
        source: str = "\n".join(
            ["graph TD", "  A[Start] --> B[End]"] + [f"  %% note {index}" for index in range(200)]
        )

        block: MermaidChartBlock = MermaidChartBlock(source=source)
        _header, body, caption = _compose_regions(block=block)

        assert isinstance(body.content, Text), "a drawable fence shows the drawing alone"
        assert "showing" not in str(caption.content)

    def test_the_caption_reports_source_lines_not_drawn_lines(self) -> None:
        """The caption counts the fence body, which is what ``ctrl+f`` reveals."""
        source: str = "\n".join(["graph TD"] + [f"  A{index} --> A{index + 1}" for index in range(9)])

        block: MermaidChartBlock = MermaidChartBlock(source=source)
        _header, _body, caption = _compose_regions(block=block)

        assert str(caption.content).endswith("10 lines · ctrl+f for full screen")
        assert "showing" not in str(caption.content)


class TestMermaidChartBlockCopyContract:
    """The focused-copy chord resolves to the card's verbatim source."""

    @pytest.mark.asyncio
    async def test_get_copyable_text_returns_verbatim_source(self) -> None:
        """The copy chord on a focused card lands the source, not the transcript."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app._write_adapter_line(content="unrelated transcript line", classes="tool-result")
            block: MermaidChartBlock = MermaidChartBlock(source=_SAMPLE_SOURCE)
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            await pilot.pause()
            block.focus()
            await pilot.pause()

            copied: list[str] = []
            app.copy_to_clipboard = lambda text: copied.append(text)  # type: ignore[method-assign, assignment]
            await app.action_copy_visible_text()

            assert app.focused is block
            assert copied == [_SAMPLE_SOURCE]
            assert block.get_copyable_text() == _SAMPLE_SOURCE


class TestMermaidChartSurfaceSelection:
    """A real mouse drag over the card extracts the verbatim source."""

    @pytest.mark.asyncio
    async def test_drag_over_card_extracts_verbatim_source(self) -> None:
        """The drag lands on the source surface, not the caption line."""
        source: str = "\n".join([_SAMPLE_SOURCE] + [f"  D{index} --> E{index}" for index in range(200)])
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            block: MermaidChartBlock = MermaidChartBlock(source=source)
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            await pilot.pause()
            block.scroll_visible(animate=False)
            await pilot.pause(delay=0.2)

            surface: MermaidChartSurface = block.query_one(MermaidChartSurface)
            region = surface.region
            base_background: Optional[Color] = app.screen.get_style_at(x=region.x, y=region.y).bgcolor
            await pilot.mouse_down(offset=(region.x, region.y))
            await pilot.hover(offset=(region.x + 8, region.y))
            await pilot.mouse_up(offset=(region.x + 8, region.y))
            await pilot.pause()

            assert surface in app.screen.selections
            selected: Optional[str] = app.screen.get_selected_text()
            assert selected is not None
            assert "graph TD" in selected
            assert "mermaid · graph TD" not in selected
            assert "D199 --> E199" in selected, "selection must serve the full, untruncated source"
            assert surface.get_selection(SELECT_ALL) == (source, "\n")

            selection_background: Color = _selection_background(app=app)
            assert app.screen.get_style_at(x=region.x, y=region.y).bgcolor == selection_background
            assert selection_background != base_background


class TestMermaidChartSourceScreen:
    """The full-screen source view shows everything and closes on Escape."""

    @pytest.mark.asyncio
    async def test_source_screen_text_area_is_read_only_with_full_source(self) -> None:
        """The screen hosts the full, untruncated source in a read-only area."""
        source: str = "\n".join([_SAMPLE_SOURCE] + [f"  D{index} --> E{index}" for index in range(200)])
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.push_screen(MermaidChartSourceScreen(source=source, directive="graph TD"))
            await pilot.pause()

            screen: MermaidChartSourceScreen = app.screen  # type: ignore[assignment]
            area: TextArea = screen.query_one("#mermaid-source-area", TextArea)
            title: LiteralTextStatic = screen.query_one(".mermaid-source-title", LiteralTextStatic)

            assert isinstance(screen, MermaidChartSourceScreen)
            assert area.read_only is True
            assert area.text == source
            assert str(title.content) == "📊 Mermaid chart — graph TD"

    @pytest.mark.asyncio
    async def test_escape_dismisses_the_source_screen(self) -> None:
        """Pressing Escape closes the modal and restores the previous screen."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            previous_screen = app.screen
            app.push_screen(MermaidChartSourceScreen(source=_SAMPLE_SOURCE, directive="graph TD"))
            await pilot.pause()
            assert isinstance(app.screen, MermaidChartSourceScreen)

            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()

            assert app.screen is previous_screen
            assert not any(isinstance(screen, MermaidChartSourceScreen) for screen in app.screen_stack)


class TestFullScreenChordWiring:
    """The ``ctrl+f`` chord on a focused card reaches the app's handler (spec 77.a.4)."""

    @pytest.mark.asyncio
    async def test_pressing_ctrl_f_on_focused_block_opens_source_screen(self) -> None:
        """A real keypress on a focused card opens the source screen, untouched prompt.

        The card is built the way production builds it — streamed into an
        ``AssistantStreamBlock``, so it sits two levels down inside that
        block's ``AssistantAnswerBody`` — because both claims here depend on
        that nesting: the ``FullScreenRequested`` message has to bubble
        through the two extra ancestors, and the card has to stay in the
        focus chain even though ``AssistantStreamBlock`` is itself
        ``can_focus = True``. Mounting a bare card on the transcript would
        prove neither.

        The chord is driven through the pilot rather than by calling
        ``action_mermaid_full_screen()`` directly: a direct call passes even when
        no key can reach the action. ``SloTUI.on_key`` swallows every printable
        keystroke, so a plain-letter binding would silently do nothing here and
        type into the prompt instead — which the second assertion pins.
        """
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            stream_block: AssistantStreamBlock = await app.mount_assistant_block()
            stream_block.finalize(final_text="Here is the flow:\n\n```mermaid\ngraph TD\n  A --> B\n```\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: len(stream_block.query(MermaidChartBlock)) == 1,
            )

            block: MermaidChartBlock = stream_block.query_one(MermaidChartBlock)
            assert block in app.screen.focus_chain, "the card must stay Tab-reachable inside the block"
            block.focus()
            await pilot.pause()

            await pilot.press("ctrl+f")
            await pilot.pause()

            assert isinstance(app.screen, MermaidChartSourceScreen)
            assert app._input is not None and app._input.text == ""

            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()

            assert not isinstance(app.screen, MermaidChartSourceScreen)
            assert not any(isinstance(screen, MermaidChartSourceScreen) for screen in app.screen_stack)
