"""In-process prompt-history recall helpers for the Slo TUI."""

from __future__ import annotations

from typing import Optional

__all__ = ["PromptHistoryNavigator"]


class PromptHistoryNavigator:
    """Manage in-process recall of submitted user prompts."""

    def __init__(self) -> None:
        """Seed empty history and inactive navigation state."""
        self._entries: list[str] = []
        self._cursor: Optional[int] = None
        self._draft: str = ""

    @property
    def is_navigating(self) -> bool:
        """Return whether history-navigation mode is currently active.

        Returns:
            bool: True when the navigator is browsing prior prompts.
        """
        return self._cursor is not None

    def record(self, *, text: str) -> None:
        """Record one submitted non-slash user prompt.

        Args:
            text (str): Submitted non-slash user prompt text.
        """
        if not text.strip():
            return
        self._entries.append(text)
        self.clear_navigation()

    def older(self, *, current_buffer: str) -> Optional[str]:
        """Return the next older prompt, if any.

        Args:
            current_buffer (str): Current editor buffer before recall begins.

        Returns:
            Optional[str]: Older prompt text, or ``None`` when unavailable.
        """
        if not self._entries:
            return None
        if self._cursor is None:
            self._draft = current_buffer
            self._cursor = len(self._entries) - 1
            return self._entries[self._cursor]
        if self._cursor == 0:
            return self._entries[0]
        self._cursor -= 1
        return self._entries[self._cursor]

    def newer(self) -> Optional[str]:
        """Return the next newer prompt, or the preserved draft.

        Returns:
            Optional[str]: Newer prompt text, the preserved draft, or ``None``.
        """
        if self._cursor is None:
            return None
        if self._cursor >= len(self._entries) - 1:
            draft: str = self._draft
            self.clear_navigation()
            return draft
        self._cursor += 1
        return self._entries[self._cursor]

    def clear_navigation(self) -> None:
        """Exit history-navigation mode and forget the preserved draft."""
        self._cursor = None
        self._draft = ""
