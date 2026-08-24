"""Markup-safe plain-text transcript surface for the Slo TUI."""

from __future__ import annotations

from typing import Optional

from textual.visual import VisualType
from textual.widgets import Static

__all__ = ["LiteralTextStatic"]


class LiteralTextStatic(Static):
    """A ``Static`` that renders its text literally, never as console markup.

    Slo streams arbitrary model and tool text into the transcript — Python type
    hints (``list[str]``), timestamps (``[2026-08-24]``), JSON arrays, regex
    character classes (``[a-z]+``), and the ``[scheduled notice]`` inbox lines.
    Textual's ``Static`` treats ``[...]`` in a string as content markup, which
    after the 8.x bump can drop or corrupt those spans. This subclass forces
    ``markup=False`` so both the initial content and every later ``update`` render
    the string verbatim. It is the single canonical seam for plain transcript text;
    every plain-string transcript render site uses it instead of a bare ``Static``.

    Who uses it: ``SloTUI._transcript_write``, the tree-viewer mounts,
    ``AssistantStreamBlock`` (label + terminal note), ``ToolExecutionBlock``
    (headline/hint/body/result), and ``SteeringPendingBlock`` (verbatim ``/steer``
    text).
    """

    def __init__(
        self,
        content: VisualType = "",
        *,
        classes: Optional[str] = None,
        id: Optional[str] = None,
    ) -> None:
        """Construct a markup-disabled ``Static``.

        Args:
            content (VisualType): Initial content. Strings render literally.
            classes (Optional[str]): Space-separated CSS classes.
            id (Optional[str]): Optional widget id.
        """
        super().__init__(content, classes=classes, id=id, markup=False)
