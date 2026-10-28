"""Borrow the transcript destination without owning workflow decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from src.tui.components.chat_transcript.component import ChatTranscript


class WorkflowNoticeAdapter:
    """Forward renderer-owned notice text and classes unchanged."""

    def __init__(self, *, tui: ChatTranscript) -> None:
        """Borrow only the component destination for this sink's lifetime."""
        self._tui = tui

    @classmethod
    def register(cls, *, tui: ChatTranscript) -> Self:
        """Return a fresh sink for the component's workflow renderer consumers."""
        return cls(tui=tui)

    def write(self, *, content: str, classes: str = "") -> None:
        """Submit one notice through public component write admission."""
        self._tui.write_transcript_line(content=content, classes=classes)
