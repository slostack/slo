"""Tests for conventional Markdown user-message body rendering and copy semantics."""

from __future__ import annotations

from typing import Optional

import pytest
from textual.app import App, ComposeResult
from textual.content import Content
from textual.containers import Vertical, VerticalScroll
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from textual.style import Style

from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.user_message_block import UserMessageBlock, UserMessageBody


class _Harness(App):
    """Mount one user block with both registered Slo themes."""

    def __init__(self, *, text: str) -> None:
        """Store exact raw message text for the body fixture."""
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self._text: str = text

    def compose(self) -> ComposeResult:
        """Compose the scrollable transcript fixture."""
        with VerticalScroll():
            with Vertical():
                yield UserMessageBlock(text=self._text)


class _LayoutHarness(App):
    """Mount comparable user and compact tool blocks under the active Slo theme."""

    def __init__(self, *, user_text: str) -> None:
        """Store the exact user source used by the compositor fixture."""
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name
        self._user_text: str = user_text

    def compose(self) -> ComposeResult:
        """Compose one full-width user band and one default compact tool card."""
        with VerticalScroll():
            with Vertical():
                yield UserMessageBlock(text=self._user_text)
                yield ToolExecutionBlock(tool_call_id="layout-tool", tool_name=None)


class TestUserMessageBlock:
    """Raw user ownership and compiler-visible body behavior."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme_name", [SLO_DEFAULT_THEME.name])
    async def test_mounted_body_resolves_semantic_roles_for_each_theme(self, theme_name: str) -> None:
        """Mounted content resolves compiler role strings through the active theme map."""
        app = _Harness(text="# hello **world**")
        app.theme = theme_name
        async with app.run_test() as pilot:
            await pilot.pause()
            block = app.query_one(UserMessageBlock)
            assert str(block._body.content) == "hello world"
            assert isinstance(block._body.content, Content)
            assert all(isinstance(span.style, Style) for span in block._body.content.spans)

    def test_preserves_exact_raw_user_source_while_rendering_visible_markdown(self) -> None:
        """User storage and raw copy keep source while Content hides Markdown chrome."""
        source: str = "  # heading\n- [link](https://example.test)\n```python\nvalue = 1\n```  "
        block = UserMessageBlock(text=source)
        assert block.text == source
        assert block.get_raw_markdown_for_copy() == source
        assert str(block._body.content) == "heading\n\n• link\n\nvalue = 1"

    def test_selection_extracts_bounded_visible_text(self) -> None:
        """Native selections index the compiler-emitted visible buffer only."""
        body = UserMessageBody(source_text="# alpha bravo")
        selected: Optional[tuple[str, str]] = body.get_selection(
            Selection(start=Offset(x=6, y=0), end=Offset(x=11, y=0))
        )
        assert selected == ("bravo", "\n")

    def test_whitespace_only_user_source_remains_visible(self) -> None:
        """Whitespace-only accepted prompts preserve current visible fallback parity."""
        block = UserMessageBlock(text="  \n ")
        assert str(block._body.content) == "  \n "
        assert block.get_copyable_text() == "  \n "

    def test_empty_body_has_no_selection_text(self) -> None:
        """An empty compiler buffer remains unselectable."""
        assert UserMessageBody(source_text="").get_selection(SELECT_ALL) is None

    def test_user_band_css_uses_neutral_body_with_a_dim_spine_and_speaker_label(self) -> None:
        """The band keeps its body normal-weight and labels the speaker in secondary color."""
        block = UserMessageBlock(text="# hello")
        block.set_expanded(expanded=False)
        css: str = UserMessageBlock.DEFAULT_CSS
        assert block._expanded is True
        assert "border-left: solid $text-dim;" in css
        assert "user-message-speaker" in css
        assert "color: $secondary;" in css
        assert "text-style: none;" in css
        assert "background: $user-msg-bg;" in css

    @pytest.mark.asyncio
    async def test_one_line_band_shows_speaker_above_body_and_fills_available_width(self) -> None:
        """The user band adds one speaker row and keeps the body inside the band."""
        app = _LayoutHarness(user_text="one line")

        async with app.run_test(size=(80, 16)) as pilot:
            await pilot.pause()
            user: UserMessageBlock = app.query_one(UserMessageBlock)
            tool: ToolExecutionBlock = app.query_one(ToolExecutionBlock)

            assert user.region.width == 80
            assert user.content_region.width == 77
            assert user.region.height == 5
            assert user._speaker.region.y == user.region.y + 1
            assert user._body.region.y == user._speaker.region.bottom
            assert user._body.region.x == user.region.x + 2
            assert user._body.region.width == user.content_region.width
            assert user._speaker.styles.color.hex == app.get_css_variables()["secondary"]
            assert user._body.styles.text_style.bold is not True
            assert user.styles.background == user._body.styles.background

    @pytest.mark.asyncio
    async def test_multiline_body_grows_without_clipping_and_keeps_native_visible_selection(self) -> None:
        """Natural multiline growth leaves every visible line selectable after the CSS-only layout change."""
        source: str = "first line\nsecond line\nthird line"
        app = _LayoutHarness(user_text=source)

        async with app.run_test(size=(40, 16)) as pilot:
            await pilot.pause()
            user: UserMessageBlock = app.query_one(UserMessageBlock)
            body: UserMessageBody = user._body

            assert user.region.height == 7
            assert body.region.height == 3
            assert body.region.y == user._speaker.region.bottom
            assert body.get_selection(SELECT_ALL) == (source, "\n")

    def test_focused_copy_is_visible_and_raw_copy_is_exact_source(self) -> None:
        """The two complete-copy paths deliberately return their separate buffers."""
        block = UserMessageBlock(text="# hello **world**")
        assert block.get_copyable_text() == "hello world"
        assert block.get_raw_markdown_for_copy() == "# hello **world**"
