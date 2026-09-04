"""Unit tests for ``QueuedPromptBlock`` (spec 72.a.4)."""

from __future__ import annotations

from src.tui.widgets.queued_prompt_block import QueuedPromptBlock


class TestQueuedPromptBlock:
    """Presentation contract for the one visible held ordinary prompt."""

    def test_renders_queued_prompt_text(self) -> None:
        """Initial render contains the ``⏳ Queued:`` prefix and the held text."""
        block = QueuedPromptBlock(text="explain the failing test")

        assert block.queued_text == "explain the failing test"
        assert "⏳ Queued: explain the failing test" in str(block.render())

    def test_queued_prompt_block_renders_brackets_literally(self) -> None:
        """Bracketed queued text renders verbatim because the widget is literal.

        Proves the block subclasses ``LiteralTextStatic``: a queued prompt such
        as ``apply list[str] then [a-z]+`` keeps its brackets instead of being
        swallowed or raising a ``MarkupError`` after the Textual 8.x bump.
        """
        block = QueuedPromptBlock(text="apply list[str] then [a-z]+")

        rendered: str = str(block.render())
        assert "list[str]" in rendered
        assert "[a-z]+" in rendered

    def test_replace_text_updates_queued_text_and_rendered_content(self) -> None:
        """``replace_text`` updates ``queued_text`` and the render in place."""
        block = QueuedPromptBlock(text="first held prompt")

        block.replace_text(text="replacement held prompt")

        assert block.queued_text == "replacement held prompt"
        rendered: str = str(block.render())
        assert "⏳ Queued: replacement held prompt" in rendered
        assert "first held prompt" not in rendered

    def test_has_queued_prompt_css_selector(self) -> None:
        """Block DEFAULT_CSS includes the queued-prompt styling rule."""
        # CSS classes in Textual are defined by DEFAULT_CSS, not set directly.
        assert "QueuedPromptBlock" in QueuedPromptBlock.DEFAULT_CSS
