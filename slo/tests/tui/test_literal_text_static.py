"""Unit tests for ``LiteralTextStatic`` — the markup-safe transcript seam."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical

from src.tui.widgets.literal_text_static import LiteralTextStatic


class _LiteralHost(App[None]):
    """Minimal host app that mounts a ``LiteralTextStatic`` for render checks.

    Used only by the tests in this module: the CSS-selector test needs a real
    styled DOM, and the render tests need a mounted widget whose rendered lines
    can be read back.
    """

    CSS = """
    .tool-call-headline {
        color: red;
    }
    """

    def __init__(self, *, content: str) -> None:
        """Store the content the mounted widget should render.

        Args:
            content (str): Initial text for the ``LiteralTextStatic``.
        """
        super().__init__()
        self._content: str = content
        self.literal: LiteralTextStatic = LiteralTextStatic(self._content, classes="tool-call-headline")

    def compose(self) -> ComposeResult:
        """Mount the single ``LiteralTextStatic`` under a container.

        Yields:
            ComposeResult: A container holding the literal widget.
        """
        with Vertical():
            yield self.literal


def _rendered_text(*, widget: LiteralTextStatic) -> str:
    """Return the widget's rendered content as plain text.

    Reads the ``Content`` produced by ``Static.render`` and returns its plain
    form so bracket literals can be asserted. Called by the render tests.

    Args:
        widget (LiteralTextStatic): The mounted widget to read.

    Returns:
        str: The rendered plain text.
    """
    return str(widget.render())


class TestLiteralTextStatic:
    """Markup-safe rendering contract for ``LiteralTextStatic``."""

    @pytest.mark.asyncio
    async def test_literal_text_static_renders_brackets_literally(self) -> None:
        """Bracketed initial content renders verbatim with no markup parsing."""
        app: _LiteralHost = _LiteralHost(content="type: list[str] at [2026-08-24]")

        async with app.run_test():
            text: str = _rendered_text(widget=app.literal)

        assert "list[str]" in text
        assert "[2026-08-24]" in text

    @pytest.mark.asyncio
    async def test_literal_text_static_update_keeps_markup_disabled(self) -> None:
        """A later ``update`` also renders brackets literally (init flag governs it)."""
        app: _LiteralHost = _LiteralHost(content="")

        async with app.run_test():
            app.literal.update("regex /[a-z]+/")
            text: str = _rendered_text(widget=app.literal)

        assert "regex /[a-z]+/" in text

    @pytest.mark.asyncio
    async def test_literal_text_static_matches_class_selectors(self) -> None:
        """Subclassing keeps class-based CSS selectors matching the widget."""
        app: _LiteralHost = _LiteralHost(content="headline text")

        async with app.run_test():
            color: str = app.literal.styles.color.hex.lower()

        # The ``.tool-call-headline`` rule sets red; if the subclass broke CSS
        # matching the color would fall back to the default text color.
        assert color == "#ff0000"
