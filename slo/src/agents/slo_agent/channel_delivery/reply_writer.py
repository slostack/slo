"""ReplyWriter — answers each completed channel turn (108.1).

When a run ends, exactly one ``reply`` row goes back to the original sender
with ``in_reply_to_id`` pointing at the request row (108.1 §9 A8). The reply id
is derived from the request id, so a retried write after an uncertain failure
hits the duplicate-id rule instead of storing a second reply.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.gateway import ChannelGateway

__all__ = ["ReplyWriter"]

_MAX_REPLY_CHARS: int = 65_536


class ReplyWriter:
    """Writes the reply row for one finished channel turn."""

    def __init__(self, *, gateway: ChannelGateway) -> None:
        """Bind the writer to the shared gateway.

        Args:
            gateway (ChannelGateway): The gateway every row goes through.
        """
        self._gateway: ChannelGateway = gateway

    @classmethod
    def reply_id_for(cls, *, request_id: UUID) -> UUID:
        """Return the one stable reply id that answers a request row.

        Args:
            request_id (UUID): Id of the prompt row being answered.

        Returns:
            UUID: Deterministic ``uuid5`` id of its reply row.
        """
        return uuid5(NAMESPACE_URL, f"slo-channel-reply:{request_id}")

    async def write(self, *, request: ChannelMessageDAO, outcome: TurnOutcomeDAO) -> None:
        """Insert the reply row for one finished turn.

        Contents are the run's final text (trimmed to the 64 KiB column
        limit) or, when the turn failed, the short error line. Idempotent:
        every write for one request uses ``reply_id_for``, so repeating it
        stores no second reply.

        Args:
            request (ChannelMessageDAO): The accepted prompt row being answered.
            outcome (TurnOutcomeDAO): How the turn ended.
        """
        contents: str = (
            outcome.final_text
            if outcome.status in ("completed", "aborted")
            else (outcome.error or "(run failed)")
        )
        contents = contents[:_MAX_REPLY_CHARS] if contents else "(no response)"
        await self._gateway.send(
            new=NewMessageDAO(
                id=self.reply_id_for(request_id=request.id),
                sender_id=request.recipient_id,
                recipient_id=request.sender_id,
                message_contents=contents,
                message_type="reply",
                in_reply_to_id=request.id,
                channel_id=request.channel_id,
            )
        )
