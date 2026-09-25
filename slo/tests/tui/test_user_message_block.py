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

from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.user_message_block import UserMessageBlock, UserMessageBody


class _Harness(App):
    """Mount one user block with both registered Slo themes."""

    def __init__(self, *, text: str) -> None:
        """Store exact raw message text for the body fixture."""
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self._text: str = text

    def compose(self) -> ComposeResult:
        """Compose the scrollable transcript fixture."""
        with VerticalScroll():
            with Vertical():
                yield UserMessageBlock(text=self._text)


class TestUserMessageBlock:
    """Raw user ownership and compiler-visible body behavior."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme_name", [SLO_DEFAULT_THEME.name, SLO_DARK_THEME.name])
    async def test_mounted_body_resolves_semantic_roles_for_each_theme(self, theme_name: str) -> None:
        """Mounted content resolves compiler role strings through the active theme map."""
        app = _Harness(text="# hello **world**")
        app.theme = theme_name
        async with app.run_test() as pilot:
            await pilot.pause()
            block = app.query_one(UserMessageBlock)
            assert str(block._body.content) == "hello world"
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

    def test_user_band_padding_and_no_collapse_are_preserved(self) -> None:
        """The compiler rewire leaves established user transcript ownership intact."""
        block = UserMessageBlock(text="# hello")
        block.set_expanded(expanded=False)
        assert block._expanded is True
        assert "padding: 0 1;" in UserMessageBlock.DEFAULT_CSS
        assert "background: $user-msg-bg;" in UserMessageBlock.DEFAULT_CSS

    def test_focused_copy_is_visible_and_raw_copy_is_exact_source(self) -> None:
        """The two complete-copy paths deliberately return their separate buffers."""
        block = UserMessageBlock(text="# hello **world**")
        assert block.get_copyable_text() == "hello world"
        assert block.get_raw_markdown_for_copy() == "# hello **world**"
