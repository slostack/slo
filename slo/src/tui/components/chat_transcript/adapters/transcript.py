"""Incomplete append-order logical record and plain-notice display."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Self

if TYPE_CHECKING:
    from src.tui.components.chat_transcript.component import ChatTranscript


class TranscriptNoticeDisplayAdapter:
    """Record logical lines separately from the component's rendered widget tree."""

    TURN_SEPARATOR: str = "─" * 18

    def __init__(self, *, tui: ChatTranscript) -> None:
        """Borrow one component for its mounted lifetime; never own persistence."""
        self._tui = tui
        self.lines: list[tuple[str, str]] = []

    @classmethod
    def register(cls, *, tui: ChatTranscript) -> Self:
        """Return a fresh component-local record, without global registration."""
        return cls(tui=tui)

    def write(self, *, content: str, classes: str = "", before: Optional[int] = None) -> None:
        """Append an admitted notice; insertion affects display, not logical order."""
        self._append_line(content=content, classes=classes, before=before)

    def _append_line(self, *, content: str, classes: str, before: Optional[int]) -> None:
        """Keep the local recording/display leaf chain synchronous."""
        self.lines.append((content, classes))
        self._tui._transcript_write(line=content, style_class=classes, before=before)

    def record(self, *, content: str, classes: str) -> None:
        """Retain already-rendered text without mounting a duplicate widget."""
        self.lines.append((content, classes))

    def has_prior_turn_content(self) -> bool:
        """Exclude separator-only records when deciding whether to separate turns."""
        return any(classes != "turn-separator" for _content, classes in self.lines)
