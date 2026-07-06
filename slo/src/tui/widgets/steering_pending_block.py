"""SteeringPendingBlock — greyed-out pending steering message widget."""

from __future__ import annotations

from textual.widgets import Static

__all__ = ["SteeringPendingBlock"]


class SteeringPendingBlock(Static):
    """Widget showing a pending steering message in muted style."""

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
