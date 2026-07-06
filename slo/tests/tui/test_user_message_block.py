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
    """Global expand/collapse behaviour for ``UserMessageBlock`` (sub-spec 42.a.12)."""

    def test_natural_default_is_expanded(self) -> None:
        """No force_expanded keeps the natural full-text state."""
        block = UserMessageBlock(text="hello\nworld")

        assert block._expanded is True

    def test_force_expanded_false_starts_collapsed(self) -> None:
        """Mounting under collapse-all starts in the collapsed state."""
        block = UserMessageBlock(text="hello\nworld", force_expanded=False)

        assert block._expanded is False

    def test_force_expanded_true_starts_expanded(self) -> None:
        """Mounting under expand-all starts in the expanded state."""
        block = UserMessageBlock(text="hello\nworld", force_expanded=True)

        assert block._expanded is True

    def test_collapsed_renderable_truncates_long_first_line(self) -> None:
        """A long first line collapses to <=80 chars with an ellipsis."""
        renderable = UserMessageBlock._collapsed_renderable(text="a" * 200)

        assert len(renderable.renderable) <= 80
        assert renderable.renderable.endswith("...")

    def test_collapsed_renderable_marks_multiline_text(self) -> None:
        """A multi-line message shows only the first line with a more-marker."""
        renderable = UserMessageBlock._collapsed_renderable(text="first line\nsecond line")

        assert "first line" in renderable.renderable
        assert "second line" not in renderable.renderable
        assert "…" in renderable.renderable

    def test_collapsed_renderable_blank_text_is_empty(self) -> None:
        """Whitespace-only text collapses to an empty string."""
        renderable = UserMessageBlock._collapsed_renderable(text="   \n  ")

        assert renderable == ""

    def test_set_expanded_toggles_state(self) -> None:
        """``set_expanded`` flips the tracked expansion state."""
        block = UserMessageBlock(text="hello\nworld")

        block.set_expanded(expanded=False)
        assert block._expanded is False

        block.set_expanded(expanded=True)
        assert block._expanded is True
