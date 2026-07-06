"""Scheduling exceptions — typed failures for store and trigger parsing."""

from __future__ import annotations

from pathlib import Path

__all__ = ["ScheduleNotFoundError", "ScheduleStoreCorruptError", "TriggerParseError"]


class ScheduleStoreCorruptError(RuntimeError):
    """Raised when a ``schedule.md`` or ``state.json`` file cannot be parsed."""

    def __init__(self, *, path: Path) -> None:
        """Record the offending path.

        Args:
            path (Path): The unreadable or unparseable file.
        """
        super().__init__(f"Corrupt schedule file: {path}")
        self.path: Path = path


class ScheduleNotFoundError(RuntimeError):
    """Raised when a schedule reference resolves to no schedule."""

    def __init__(self, *, reference: str) -> None:
        """Record the unresolved reference.

        Args:
            reference (str): The schedule_id or name the caller passed.
        """
        super().__init__(f"No schedule matches reference: {reference}")
        self.reference: str = reference


class TriggerParseError(RuntimeError):
    """Raised when a trigger cannot be constructed from CLI or frontmatter input."""

    def __init__(self, *, reason: str) -> None:
        """Record why the trigger was rejected.

        Args:
            reason (str): Human-readable rejection reason.
        """
        super().__init__(f"Invalid trigger: {reason}")
        self.reason: str = reason
