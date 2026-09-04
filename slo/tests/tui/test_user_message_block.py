"""Tests for the ``UserMessageBlock`` transcript widget (feature 15)."""

from __future__ import annotations

import pytest
from rich.markdown import Markdown
from rich.padding import Padding
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll

from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.user_message_block import UserMessageBlock


class _Harness(App):
    """Minimal app mirroring the real transcript layout for render tests.

    Registers both Slo themes so widget CSS that references the canonical
    ``$user-msg-bg`` semantic token resolves during compositing.
    """

    def __init__(self, *, text: str) -> None:
        """Store the user text to mount and activate the Slo default theme.

        Args:
            text (str): The user prompt text.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = SLO_DARK_THEME.name
        self._text: str = text

    def compose(self) -> ComposeResult:
        """Compose a scroll viewport holding one user block.

        Yields:
            ComposeResult: The transcript scaffold.
        """
        with VerticalScroll(id="transcript-scroll"):
            with Vertical(id="transcript-content"):
                yield UserMessageBlock(text=self._text)


class TestUserMessageBlock:
    """Rendering and content behavior of one user turn."""

    @pytest.mark.asyncio
    async def test_renders_without_compositor_error(self) -> None:
        """A markdown user prompt renders inside the real layout cleanly."""
        app = _Harness(text="hello **world**")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._exception is None
            block = app.query_one(UserMessageBlock)
            assert block.text == "hello **world**"

    @pytest.mark.asyncio
    async def test_whitespace_only_text_renders_nothing(self) -> None:
        """An empty/whitespace prompt produces no visible renderable."""
        app = _Harness(text="   ")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._exception is None
            block = app.query_one(UserMessageBlock)
            assert block.text == "   "

    def test_renderable_is_empty_for_blank_text(self) -> None:
        """The construction-time renderable is empty for blank text."""
        assert UserMessageBlock._renderable(text="   ") == ""

    def test_renderable_is_present_for_real_text(self) -> None:
        """Non-blank text yields a vertical-only padded renderable (spec 72.a.3)."""
        renderable = UserMessageBlock._renderable(text="hi")
        assert isinstance(renderable, Padding)
        assert renderable.top == 1
        assert renderable.right == 0
        assert renderable.bottom == 1
        assert renderable.left == 0

    def test_widget_css_uses_transcript_output_pad(self) -> None:
        """The widget declares the uniform ``TRANSCRIPT_OUTPUT_PAD`` convention."""
        block_rule: str = UserMessageBlock.DEFAULT_CSS.split("UserMessageBlock {")[1].split("}")[0]
        assert "padding: 0 1;" in block_rule

    def test_user_block_uses_canonical_user_band_fill(self) -> None:
        """The widget paints the quiet ``user-msg-bg`` band, not a panel card (spec 72.a.5)."""
        assert "background: $user-msg-bg;" in UserMessageBlock.DEFAULT_CSS
        assert "background: $panel;" not in UserMessageBlock.DEFAULT_CSS


class TestUserMessageBlockExpansion:
    """Global expand/collapse behaviour for ``UserMessageBlock``."""

    def test_user_block_always_starts_expanded(self) -> None:
        """User turns always start in the full-text state."""
        block: UserMessageBlock = UserMessageBlock(text="hello\nworld")

        assert block._expanded is True

    def test_user_block_multi_line_text_renders_full_at_construction(self) -> None:
        """Construction keeps the full multi-line renderable intact."""
        block: UserMessageBlock = UserMessageBlock(text="line one\nline two\nline three")

        assert block.text == "line one\nline two\nline three"
        # ``_body.content`` is the stored ``Padding(Markdown(...))`` renderable;
        # reaching into it for the markdown source is intentional for this assertion.
        padding: Padding = block._body.content  # type: ignore[assignment]
        markdown: Markdown = padding.renderable  # type: ignore[assignment]
        assert markdown.markup == "line one\nline two\nline three"

    def test_set_expanded_is_a_noop_for_user_blocks(self) -> None:
        """``set_expanded`` never changes the tracked user-block state."""
        block: UserMessageBlock = UserMessageBlock(text="hello\nworld")

        block.set_expanded(expanded=False)
        assert block._expanded is True

        block.set_expanded(expanded=True)
        assert block._expanded is True

    def test_set_expanded_to_true_is_also_noop(self) -> None:
        """The idempotent true-path also preserves the full-text state."""
        block: UserMessageBlock = UserMessageBlock(text="hello\nworld")

        block.set_expanded(expanded=True)

        assert block._expanded is True


class TestUserMessageBlockCopyableText:
    """``get_copyable_text`` protocol for clipboard copy (spec 56)."""

    def test_returns_raw_prompt_text(self) -> None:
        """``get_copyable_text`` returns the exact prompt text unmodified."""
        block = UserMessageBlock(text="hello\nworld")

        assert block.get_copyable_text() == "hello\nworld"

    def test_preserves_leading_and_trailing_whitespace(self) -> None:
        """``get_copyable_text`` does not strip or transform the raw text."""
        block = UserMessageBlock(text="  hello  ")

        assert block.get_copyable_text() == "  hello  "
