"""Channel domain errors (108.1)."""

from __future__ import annotations

from uuid import UUID

__all__ = [
    "AdapterConfigError",
    "AmbiguousAgentError",
    "ChannelError",
    "MessageCancelledError",
    "RecipientClosedError",
    "ReplyTimeoutError",
    "UnknownAgentError",
    "UnknownMessageError",
    "UnknownParticipantError",
]


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


class UnknownAgentError(ChannelError):
    """No agent participant matches an id prefix (108.5 ``resolve_agent``)."""

    def __init__(self, *, prefix: str) -> None:
        """Record the prefix that matched nothing.

        Args:
            prefix (str): The prefix as the caller supplied it.
        """
        self.prefix: str = prefix
        super().__init__(f"No agent matches {prefix!r}")


class AmbiguousAgentError(ChannelError):
    """Several agent participants match an id prefix (108.5 ``resolve_agent``)."""

    def __init__(self, *, prefix: str, match_count: int) -> None:
        """Record the prefix and how many agents it matched.

        Args:
            prefix (str): The prefix as the caller supplied it.
            match_count (int): Number of matching agents (at least two).
        """
        self.prefix: str = prefix
        self.match_count: int = match_count
        super().__init__(f"{match_count} agents match {prefix!r}; use more characters")


class UnknownMessageError(ChannelError):
    """A wait was requested for a message id that is not in the queue."""

    def __init__(self, *, message_id: UUID) -> None:
        """Record the missing message id.

        Args:
            message_id (UUID): The id that was not found.
        """
        self.message_id: UUID = message_id
        super().__init__(f"Unknown message: {message_id}")


class MessageCancelledError(ChannelError):
    """The awaited message was cancelled before it could be answered or accepted."""

    def __init__(self, *, message_id: UUID, reason: str) -> None:
        """Record the cancelled message and its cancel reason.

        Args:
            message_id (UUID): The cancelled message id.
            reason (str): The stored ``cancel_reason``, e.g. ``recipient_closed``.
        """
        self.message_id: UUID = message_id
        self.reason: str = reason
        super().__init__(f"Message {message_id} was cancelled ({reason})")


class ReplyTimeoutError(ChannelError):
    """No reply (or acceptance) arrived for a message within the wait timeout."""

    def __init__(self, *, message_id: UUID, timeout: float) -> None:
        """Record the awaited message and the elapsed timeout.

        Args:
            message_id (UUID): The awaited message id.
            timeout (float): The timeout in seconds that elapsed.
        """
        self.message_id: UUID = message_id
        self.timeout: float = timeout
        super().__init__(f"No answer for {message_id} within {timeout:g} s")


class AdapterConfigError(ChannelError):
    """An external channel adapter cannot be loaded or configured (exit code 1).

    Raised for a missing or invalid adapter config file, a missing bot token,
    an unloadable ``module:Class`` reference, or an adapter kind the queue does
    not know. The message is safe to print: it never contains a secret.
    """
