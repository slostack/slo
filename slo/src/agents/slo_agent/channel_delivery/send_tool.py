"""SendMessageTool — the ``send_message`` agent tool (108.4 §4-§6).

It follows the same factory shape as ``SpawnSubAgentsTool``: a ``*SchemaDAO``
args model, a ``build(...)`` classmethod that returns a bound ``BaseTool``, and
results and validation errors returned as JSON strings.

The sender identity comes from the binding (``self_id``), never from the tool
arguments. ``MessagingPolicy`` decides the allowed edges and the delivery
defaults. The tool owns the per-sender note rate limit and maps the gateway's
domain errors onto ``SendMessageResultDAO.status``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, Optional
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.channel_delivery.policy import (
    MessageAddressDAO,
    MessageKind,
    MessagingPolicy,
)
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO, utc_now
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.channels.gateway import ChannelGateway

__all__ = [
    "NOTE_RATE_LIMIT_INTERVAL",
    "NoteRateLimit",
    "NotAllowedReason",
    "SendMessageResultDAO",
    "SendMessageSchemaDAO",
    "SendMessageStatus",
    "SendMessageTool",
]

NOTE_RATE_LIMIT_INTERVAL: timedelta = timedelta(seconds=5)
"""Minimum spacing between two notes from one sender (108.4 §6)."""

SEND_MESSAGE_VALIDATION_ERROR: str = (
    '{"error": "invalid send_message arguments; use to, text (1-16384 characters), '
    "optional force, kind ('prompt' or 'note') and in_reply_to_id\"}"
)
"""JSON returned to the model when the arguments fail schema validation."""

SendMessageStatus = Literal["sent", "recipient_closed", "not_allowed", "unknown_recipient"]
"""Result of one send attempt (108.4 §4)."""

NotAllowedReason = Literal["recipient_not_permitted", "rate_limited", "unknown_in_reply_to"]
"""Why a ``not_allowed`` send was refused."""


class SendMessageSchemaDAO(BaseModel):
    """Arguments the model passes to ``send_message`` (108.4 §4)."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    to: str = Field(description="'parent', a child task_id, or an agent session id.")
    text: str = Field(min_length=1, max_length=16_384, description="Message text, at most 16 KiB.")
    force: Optional[bool] = Field(
        default=None,
        description="Force into the recipient's current run; None means True for children, False otherwise.",
    )
    kind: Optional[MessageKind] = Field(
        default=None,
        description=(
            "'prompt' asks for work; 'note' only adds context. None means 'note' when a child "
            "messages its parent and 'prompt' otherwise."
        ),
    )
    in_reply_to_id: Optional[UUID] = Field(
        default=None, description="Id of the message this one answers, if any."
    )


class SendMessageResultDAO(BaseModel):
    """Tool output, serialised to a JSON string for the model (108.4 §4)."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    status: SendMessageStatus = Field(description="Result of the send attempt.")
    message_id: Optional[UUID] = Field(default=None, description="Id of the stored message when sent.")
    recipient_name: Optional[str] = Field(default=None, description="Resolved recipient display name.")
    reason: Optional[NotAllowedReason] = Field(
        default=None,
        description="Why the send was refused when status is 'not_allowed'; None otherwise.",
    )


class NoteRateLimit:
    """Allows one note per interval for one sender; prompts are never limited.

    The check and the reservation happen together, with no ``await`` in
    between, so two parallel tool calls cannot both pass. A reservation for a
    note that was not delivered is given back.
    """

    def __init__(self, *, interval: timedelta, clock: Callable[[], datetime]) -> None:
        """Configure the spacing and the clock.

        Args:
            interval (timedelta): Minimum spacing between two notes.
            clock (Callable[[], datetime]): Source of the current UTC time.
        """
        self._interval: timedelta = interval
        self._clock: Callable[[], datetime] = clock
        self._last_note_at: Optional[datetime] = None
        self._previous_note_at: Optional[datetime] = None

    def reserve(self, *, message_type: MessageKind) -> bool:
        """Reserve the sender's note slot, or report that it is still taken.

        Args:
            message_type (MessageKind): Type of the message about to be sent.

        Returns:
            bool: ``True`` when the message may be sent now.
        """
        if message_type != "note":
            return True
        now: datetime = self._clock()
        if self._last_note_at is not None and now - self._last_note_at < self._interval:
            return False
        self._previous_note_at, self._last_note_at = self._last_note_at, now
        return True

    def release(self, *, message_type: MessageKind) -> None:
        """Give back the slot reserved for a note that was not delivered.

        Args:
            message_type (MessageKind): Type of the message that was not sent.
        """
        if message_type == "note":
            self._last_note_at = self._previous_note_at


class SendMessageTool:
    """Sends one agent's messages to its parent, children or launched workflows."""

    def __init__(
        self,
        *,
        gateway: ChannelGateway,
        policy: MessagingPolicy,
        self_id: UUID,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Bind the tool to the queue, the sender's policy and its identity.

        Args:
            gateway (ChannelGateway): The shared queue API.
            policy (MessagingPolicy): Edges and defaults for this sender.
            self_id (UUID): Participant id of the sending session.
            clock (Callable[[], datetime]): Source of UTC time for ``sent_at``
                and the note rate limit.

        Raises:
            ValueError: ``self_id`` is not the identity ``policy`` was built for.
        """
        policy.ensure_sender(sender_id=self_id)
        self._gateway: ChannelGateway = gateway
        self._policy: MessagingPolicy = policy
        self._self_id: UUID = self_id
        self._clock: Callable[[], datetime] = clock
        self._note_rate_limit: NoteRateLimit = NoteRateLimit(interval=NOTE_RATE_LIMIT_INTERVAL, clock=clock)

    @classmethod
    def build(
        cls,
        *,
        gateway: ChannelGateway,
        policy: MessagingPolicy,
        self_id: UUID,
        clock: Callable[[], datetime] = utc_now,
    ) -> BaseTool:
        """Build a ``send_message`` tool bound to one sender.

        Called once per session during session construction, for
        orchestrator sessions (TUI or headless) and for children. The result
        is passed to ``SessionConfigDAO.extra_tools``.

        Args:
            gateway (ChannelGateway): The shared queue API.
            policy (MessagingPolicy): Edges and defaults for this sender.
            self_id (UUID): Participant id of the sending session.
            clock (Callable[[], datetime]): Source of UTC time (tests inject one).

        Returns:
            BaseTool: A bound LangChain tool the LLM can call.

        Raises:
            ValueError: ``self_id`` is not the identity ``policy`` was built for.
        """
        owner: SendMessageTool = cls(gateway=gateway, policy=policy, self_id=self_id, clock=clock)

        @tool(args_schema=SendMessageSchemaDAO)
        async def send_message(
            to: str,
            text: str,
            force: Optional[bool] = None,
            kind: Optional[MessageKind] = None,
            in_reply_to_id: Optional[UUID] = None,
        ) -> str:
            """Send a message to your parent orchestrator, one of your children, or a workflow you launched.

            Use ``to="parent"`` to reach the orchestrator that spawned you, a child's
            ``task_id`` (or its session id) to reach a running child, or the session id
            of a workflow you launched. Any other recipient is refused with
            ``not_allowed``. A ``prompt`` asks for work and a ``note`` only adds
            context. Messages to children are forced into their current run by default.
            Messages from a child to its parent default to ``note``, and only one note
            per 5 seconds is accepted.

            Args:
                to (str): ``"parent"``, a child task_id, or an agent session id.
                text (str): Message text, 1-16384 characters.
                force (Optional[bool]): Force into the recipient's current run.
                kind (Optional[MessageKind]): ``"prompt"`` or ``"note"``.
                in_reply_to_id (Optional[UUID]): Id of the message this one answers.

            Returns:
                str: JSON ``{"status": "sent" | "recipient_closed" | "not_allowed" |
                    "unknown_recipient", "message_id"?, "recipient_name"?, "reason"?}``.
            """
            request: SendMessageSchemaDAO = SendMessageSchemaDAO(
                to=to,
                text=text,
                force=force,
                kind=kind,
                in_reply_to_id=in_reply_to_id,
            )
            result: SendMessageResultDAO = await owner.invoke(request=request)
            return result.model_dump_json(exclude_none=True)

        send_message.handle_validation_error = SEND_MESSAGE_VALIDATION_ERROR
        return send_message

    async def invoke(self, *, request: SendMessageSchemaDAO) -> SendMessageResultDAO:
        """Address, check and send one message as the bound sender.

        Args:
            request (SendMessageSchemaDAO): Validated tool arguments.

        Returns:
            SendMessageResultDAO: ``sent`` with the stored id, or the reason
                nothing was stored.

        Raises:
            UnknownParticipantError: The bound sender itself is not registered
                (a wiring defect, not a model error).
        """
        address: MessageAddressDAO = self._policy.address(
            to=request.to, kind=request.kind, force=request.force
        )
        if address.recipient_id is None:
            return SendMessageResultDAO(status="not_allowed", reason="recipient_not_permitted")
        if address.status == "recipient_closed":
            return await self._recipient_closed(recipient_id=address.recipient_id)
        if not await self._is_known_reply_target(in_reply_to_id=request.in_reply_to_id):
            return SendMessageResultDAO(status="not_allowed", reason="unknown_in_reply_to")
        if not self._note_rate_limit.reserve(message_type=address.message_type):
            return SendMessageResultDAO(status="not_allowed", reason="rate_limited")
        return await self._deliver(request=request, address=address, recipient_id=address.recipient_id)

    async def _deliver(
        self,
        *,
        request: SendMessageSchemaDAO,
        address: MessageAddressDAO,
        recipient_id: UUID,
    ) -> SendMessageResultDAO:
        """Insert the row and map recipient errors onto the result.

        The queue re-checks the recipient inside its insert transaction, so a
        child that closes after the policy check is still reported as
        ``recipient_closed``. A note that was not stored gives back its rate
        limit slot.

        Args:
            request (SendMessageSchemaDAO): Validated tool arguments.
            address (MessageAddressDAO): The policy's allowed decision.
            recipient_id (UUID): The resolved recipient.

        Returns:
            SendMessageResultDAO: ``sent``, ``recipient_closed`` or
                ``unknown_recipient``.

        Raises:
            UnknownParticipantError: The bound sender is not registered.
        """
        new: NewMessageDAO = NewMessageDAO(
            sender_id=self._self_id,
            recipient_id=recipient_id,
            message_contents=request.text,
            message_type=address.message_type,
            in_reply_to_id=request.in_reply_to_id,
            force=address.force,
            sent_at=self._clock(),
        )
        try:
            stored: ChannelMessageDAO = await self._gateway.send(new=new)
        except RecipientClosedError:
            self._note_rate_limit.release(message_type=address.message_type)
            return await self._recipient_closed(recipient_id=recipient_id)
        except UnknownParticipantError as error:
            if error.participant_id != recipient_id:
                raise
            self._note_rate_limit.release(message_type=address.message_type)
            return SendMessageResultDAO(status="unknown_recipient")
        return SendMessageResultDAO(status="sent", message_id=stored.id, recipient_name=stored.recipient_name)

    async def _recipient_closed(self, *, recipient_id: UUID) -> SendMessageResultDAO:
        """Build a ``recipient_closed`` result that names the recipient when it is known.

        Args:
            recipient_id (UUID): The closed or finished recipient.

        Returns:
            SendMessageResultDAO: ``recipient_closed`` with the display name.
        """
        participant: Optional[ParticipantDAO] = await self._gateway.get_participant(
            participant_id=recipient_id
        )
        return SendMessageResultDAO(
            status="recipient_closed",
            recipient_name=participant.name if participant is not None else None,
        )

    async def _is_known_reply_target(self, *, in_reply_to_id: Optional[UUID]) -> bool:
        """Return whether ``in_reply_to_id`` is absent or names a stored message.

        Args:
            in_reply_to_id (Optional[UUID]): Requested reply link.

        Returns:
            bool: ``True`` when there is no link or the linked row exists.
        """
        if in_reply_to_id is None:
            return True
        return await self._gateway.get(message_id=in_reply_to_id) is not None
