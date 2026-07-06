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
        assert "⏳ Steering: fix typo" in block.renderable

    def test_has_steering_pending_css_class(self) -> None:
        """Block DEFAULT_CSS includes steering-pending styling."""
        # CSS classes in Textual are defined by DEFAULT_CSS, not set directly
        assert "SteeringPendingBlock" in SteeringPendingBlock.DEFAULT_CSS

    def test_message_property(self) -> None:
        """The message is stored and accessible."""
        block = SteeringPendingBlock(message="fix typo")

        assert block._message == "fix typo"
