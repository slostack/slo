"""Plain prompt text with LF-only structural lines and literal filename characters."""

from textual.document._document import Document, EditResult
from textual.document._document import Location


class PromptDocument(Document):
    """Keep CR and Unicode separators as text, not implicit editor line breaks.

    PromptInput uses this document for normal TextArea edits, including undo and
    redo. Only LF is structural, matching the completion controller's locations;
    no token encoding or shell interpretation belongs at this boundary.
    """

    def __init__(self, text: str) -> None:
        """Load literal prompt text with LF as the sole structural separator.

        Args:
            text: Initial prompt buffer.
        """
        super().__init__(text="")
        self.lines[:] = text.split("\n")

    def replace_range(self, start: Location, end: Location, text: str) -> EditResult:
        """Replace a span literally through TextArea's normal undoable edit path.

        Args:
            start: One end of the replacement range.
            end: Other end of the replacement range.
            text: Literal replacement; only LF creates a document row.

        Returns:
            Cursor destination and removed text for TextArea undo/redo.
        """
        top, bottom = sorted((start, end))
        top_row, top_column = top
        bottom_row, bottom_column = bottom
        replaced_text = self.get_text_range(start=top, end=bottom)
        before = self.lines[top_row][:top_column] if top_row < self.line_count else ""
        after = self.lines[bottom_row][bottom_column:] if bottom_row < self.line_count else ""
        inserted = text.split("\n")
        inserted[0] = before + inserted[0]
        destination = (top_row + len(inserted) - 1, len(inserted[-1]))
        inserted[-1] += after
        self.lines[top_row : bottom_row + 1] = inserted
        return EditResult(end_location=destination, replaced_text=replaced_text)
