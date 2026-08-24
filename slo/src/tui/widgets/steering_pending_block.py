"""SteeringPendingBlock — greyed-out pending steering message widget."""

from __future__ import annotations

from src.tui.widgets.literal_text_static import LiteralTextStatic

__all__ = ["SteeringPendingBlock"]


class SteeringPendingBlock(LiteralTextStatic):
    """Widget showing a pending steering message in muted style.

    Subclasses ``LiteralTextStatic`` (not ``Static``) so verbatim ``/steer`` text
    containing ``[...]`` — type hints like ``list[str]``, regex ``[a-z]+`` — renders
    literally instead of being parsed as console markup.
    """

    DEFAULT_CSS = """
    SteeringPendingBlock {
        color: $text-muted;
        text-style: italic;
        padding: 0 1;
        margin: 0;
    }
    """

    def __init__(self, *, message: str) -> None:
        """Construct the pending steering block.

        Args:
            message: The pending steering message text.
        """
        super().__init__()
        self._message: str = message
        self.update(f"⏳ Steering: {self._message}")
