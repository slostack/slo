"""Schedule exceptions — typed failures for the schedule record lifecycle."""

from __future__ import annotations

from uuid import UUID

__all__ = [
    "InvocationNotPendingError",
    "InvocationNotRunningError",
    "ScheduleInvalidError",
    "ScheduleNameTakenError",
    "ScheduleNotFoundError",
    "ScheduleWorkerStartError",
]


class ScheduleNotFoundError(RuntimeError):
    """Raised when a schedule reference resolves to no active row."""

    def __init__(self, *, reference: str) -> None:
        """Record the unresolved reference.

        Args:
            reference (str): The schedule id or name the caller passed.
        """
        super().__init__(f"No active schedule matches reference: {reference}")
        self.reference: str = reference


class ScheduleNameTakenError(RuntimeError):
    """Raised when an active row already holds the normalised name key."""

    def __init__(self, *, name_key: str) -> None:
        """Record the conflicting name key.

        Args:
            name_key (str): The normalised schedule name that is already taken.
        """
        super().__init__(f"A schedule named {name_key!r} already exists")
        self.name_key: str = name_key


class InvocationNotPendingError(RuntimeError):
    """Raised when a guarded invocation update matched zero pending rows."""

    def __init__(self, *, invocation_id: UUID) -> None:
        """Record the invocation id whose status is no longer pending.

        Args:
            invocation_id (UUID): The invocation another writer already finalised.
        """
        super().__init__(f"Invocation {invocation_id} is no longer pending")
        self.invocation_id: UUID = invocation_id


class InvocationNotRunningError(RuntimeError):
    """Raised when a guarded invocation update matched zero running rows."""

    def __init__(self, *, invocation_id: UUID) -> None:
        """Record the invocation id whose status is not running.

        Args:
            invocation_id (UUID): The invocation whose run cannot be finalised.
        """
        super().__init__(f"Invocation {invocation_id} is not running")
        self.invocation_id: UUID = invocation_id


class ScheduleWorkerStartError(RuntimeError):
    """Raised when the schedule worker cannot start its engine."""

    def __init__(self, *, reason: str) -> None:
        """Record the startup failure.

        Args:
            reason (str): Human-readable reason the worker could not start.
        """
        super().__init__(f"Schedule worker failed to start: {reason}")
        self.reason: str = reason


class ScheduleInvalidError(RuntimeError):
    """Raised when a schedule definition or lifecycle transition is invalid."""

    def __init__(self, *, reason: str) -> None:
        """Record the rejection reason.

        Args:
            reason (str): Human-readable reason the schedule was rejected.
        """
        super().__init__(f"Invalid schedule: {reason}")
        self.reason: str = reason
