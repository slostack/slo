"""Scheduler channel sender — how a schedule fire reaches an open TUI session (108.6).

Each schedule talks through the single ``scheduler`` channel as its own sender
participant (``external_ref = schedule_id``), so a newer pending fire with the
same coalescing key supersedes the older one (108.3 §4) and the transcript
labels the run ``scheduler <schedule name>``.
"""

from __future__ import annotations

import socket
from typing import Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.dao import ChannelMessageDAO, MessageType, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway

__all__ = ["SCHEDULER_CHANNEL_ID", "ScheduleChannelSender", "ScheduledChannelDeliveryDAO"]

SCHEDULER_CHANNEL_ID: UUID = uuid5(NAMESPACE_URL, "slo:channels:scheduler")
"""Stable id of the one ``scheduler`` channel every scheduler process shares."""


class ScheduledChannelDeliveryDAO(BaseModel):
    """Result of sending one schedule message into a session's channel queue."""

    model_config = ConfigDict(frozen=True)

    message: ChannelMessageDAO = Field(description="The stored (or already-present) channel row.")
    superseded_older: bool = Field(
        description="True when an older pending row with the same sender and coalescing key was replaced."
    )


class ScheduleChannelSender:
    """Sends schedule messages to agent sessions as the schedule's own sender.

    WHAT: Registers the shared ``scheduler`` channel and the schedule's sender
        participant (idempotent upserts), then sends one row to the target
        session's agent participant through the public gateway API.
    WHO: ``ScheduleExecutor._queue_for_active_session`` for every fire that
        targets a session with an active TUI lease, and the one-time
        ``InboxImporter`` for legacy scheduler inbox items.
    WHEN: Once per fire / imported item; the caller owns the gateway lifetime.
    """

    def __init__(self, *, gateway: ChannelGateway) -> None:
        """Bind the sender to the caller-owned gateway.

        Args:
            gateway (ChannelGateway): The shared channel queue API; opened and
                closed by the caller.
        """
        self._gateway: ChannelGateway = gateway

    async def send(
        self,
        *,
        schedule_id: str,
        schedule_name: str,
        target_session_id: str,
        contents: str,
        message_type: MessageType = "prompt",
        coalesce_key: Optional[str] = None,
        message_id: Optional[UUID] = None,
    ) -> ScheduledChannelDeliveryDAO:
        """Send one schedule message to the target session's agent.

        Args:
            schedule_id (str): Schedule whose sender participant sends it.
            schedule_name (str): Human label; the sender is ``scheduler <name>``.
            target_session_id (str): Session whose agent receives the row.
            contents (str): Message text (the prompt for ``prompt`` rows).
            message_type (MessageType, optional): Row type. Defaults to ``"prompt"``.
            coalesce_key (Optional[str], optional): Key under which this row
                replaces an older pending one from the same schedule. Defaults to None.
            message_id (Optional[UUID], optional): Fixed id for idempotent
                retries (the importer keeps inbox ids). Defaults to a new id.

        Returns:
            ScheduledChannelDeliveryDAO: The stored row and whether it
                superseded an older pending one.

        Raises:
            UnknownParticipantError: The target session has never registered.
            RecipientClosedError: The target session does not admit this sender.
        """
        sender: ParticipantDAO = await self._register_schedule_sender(
            schedule_id=schedule_id, schedule_name=schedule_name
        )
        recipient_id: UUID = channel_participant_id_for_session(session_id=target_session_id)
        new: NewMessageDAO = NewMessageDAO(
            id=message_id or uuid4(),
            sender_id=sender.id,
            recipient_id=recipient_id,
            message_contents=contents,
            message_type=message_type,
            channel_id=SCHEDULER_CHANNEL_ID,
            coalesce_key=coalesce_key,
        )
        older_pending: bool = await self._has_older_pending(new=new)
        stored: ChannelMessageDAO = await self._gateway.send(new=new)
        return ScheduledChannelDeliveryDAO(message=stored, superseded_older=older_pending)

    async def _register_schedule_sender(self, *, schedule_id: str, schedule_name: str) -> ParticipantDAO:
        """Register the shared scheduler channel and this schedule's sender participant.

        The participant is the ``system`` occupant of the ``(scheduler channel,
        schedule_id)`` slot, so every fire of one schedule — from any process —
        uses the same sender, and a closed interactive session keeps its rows
        in the durable inbox instead of refusing them as an operator's.

        Args:
            schedule_id (str): Schedule identity stored as ``external_ref``.
            schedule_name (str): Human label used for the sender name.

        Returns:
            ParticipantDAO: The schedule's sender participant.
        """
        await self._gateway.register_channel(
            kind="scheduler",
            name=f"scheduler@{socket.gethostname()}",
            channel_id=SCHEDULER_CHANNEL_ID,
        )
        return await self._gateway.register_system(
            channel_id=SCHEDULER_CHANNEL_ID,
            name=f"scheduler {schedule_name}",
            external_ref=schedule_id,
        )

    async def _has_older_pending(self, *, new: NewMessageDAO) -> bool:
        """Return whether ``new`` will supersede an older pending row.

        Supersede itself happens inside the gateway's insert transaction; this
        read only reports it. The per-schedule fire lock serializes fires of
        one schedule, and only that schedule's sender can own such a row.

        Args:
            new (NewMessageDAO): The row about to be sent.

        Returns:
            bool: True when a different pending row from the same sender
                carries the same coalescing key.
        """
        if new.coalesce_key is None:
            return False
        pending: list[ChannelMessageDAO] = await self._gateway.list_pending_inbound_messages(
            recipient_id=new.recipient_id
        )
        return any(
            row.sender_id == new.sender_id and row.coalesce_key == new.coalesce_key and row.id != new.id
            for row in pending
        )
