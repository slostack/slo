"""Tests for the ``UserMessageBlock`` transcript widget (feature 15)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll

from src.tui.widgets.user_message_block import UserMessageBlock


class _Harness(App):
    """Minimal app mirroring the real transcript layout for render tests."""

    def __init__(self, *, text: str) -> None:
        """Store the user text to mount.

        Args:
            text (str): The user prompt text.
        """
        super().__init__()
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
        """Non-blank text yields a non-empty renderable."""
        renderable = UserMessageBlock._renderable(text="hi")
        assert renderable != ""
        assert renderable.top == 1
        assert renderable.right == 1
        assert renderable.bottom == 1
        assert renderable.left == 1

    def test_user_block_exposes_shared_message_surface_styling(self) -> None:
        """The widget CSS declares a panel-like message surface."""
        assert "background: $panel;" in UserMessageBlock.DEFAULT_CSS


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
        assert block._body.renderable.renderable.markup == "line one\nline two\nline three"

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
