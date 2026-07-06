"""Tree export format enumeration for /tree command."""

from __future__ import annotations

from enum import Enum

__all__ = ["TreeExportFormat"]


class TreeExportFormat(Enum):
    """Export format for the /tree command."""

    TEXTUAL = "textual"
    MARKDOWN = "markdown"
    HTML = "html"
