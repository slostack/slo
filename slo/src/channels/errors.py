"""Channel domain errors (108.1)."""

from __future__ import annotations

from uuid import UUID

__all__ = ["ChannelError", "RecipientClosedError", "UnknownParticipantError"]


class ChannelError(Exception):
    """Base error for the channels domain."""


class UnknownParticipantError(ChannelError):
    """A message was addressed to a participant id that does not exist."""

    def __init__(self, *, participant_id: UUID) -> None:
        """Record the missing participant id.

        Args:
            participant_id (UUID): The id that was not found.
        """
        self.participant_id: UUID = participant_id
        super().__init__(f"Unknown participant: {participant_id}")


class RecipientClosedError(ChannelError):
    """A message was addressed to an agent whose session is closed."""

    def __init__(self, *, participant_id: UUID) -> None:
        """Record the closed recipient id.

        Args:
            participant_id (UUID): The closed agent participant id.
        """
        self.participant_id: UUID = participant_id
        super().__init__(f"Recipient is closed: {participant_id}")
