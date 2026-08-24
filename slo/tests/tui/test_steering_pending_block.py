"""Unit tests for ``SteeringPendingBlock`` (sub-spec 42.a.7)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tui.widgets.steering_pending_block import SteeringPendingBlock


class TestSteeringPendingBlock:
    """Tests for ``SteeringPendingBlock`` widget."""

    def test_renders_pending_message(self) -> None:
        """Block stores the message text for rendering."""
        block = SteeringPendingBlock(message="fix typo")

        assert block._message == "fix typo"
        assert "⏳ Steering: fix typo" in str(block.render())

    def test_has_steering_pending_css_class(self) -> None:
        """Block DEFAULT_CSS includes steering-pending styling."""
        # CSS classes in Textual are defined by DEFAULT_CSS, not set directly
        assert "SteeringPendingBlock" in SteeringPendingBlock.DEFAULT_CSS

    def test_message_property(self) -> None:
        """The message is stored and accessible."""
        block = SteeringPendingBlock(message="fix typo")

        assert block._message == "fix typo"

    def test_steering_pending_block_renders_brackets_literally(self) -> None:
        """Verbatim ``/steer`` text with ``[...]`` renders literally, not as markup.

        Proves the block subclasses ``LiteralTextStatic``: a steer such as
        ``apply list[str] then [a-z]+`` keeps its brackets instead of being
        swallowed or raising a ``MarkupError`` after the 8.x bump.
        """
        block = SteeringPendingBlock(message="apply list[str] then [a-z]+")

        rendered: str = str(block.render())
        assert "list[str]" in rendered
        assert "[a-z]+" in rendered
