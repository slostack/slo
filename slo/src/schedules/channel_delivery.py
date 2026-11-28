"""Scheduler channel sender — how one invocation reaches an open TUI session (111.a.2).

Each schedule talks through the single ``scheduler`` channel as its own sender
participant (``external_ref = schedule_id``), so a newer pending fire with the
same coalescing key supersedes the older one and the transcript labels the run
``scheduler <schedule name>``.
"""

from __future__ import annotations

import socket
from typing import Optional
from uuid import NAMESPACE_URL, UUID, uuid5

from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.gateway import ChannelGateway
from src.schedules.dao import ScheduleDAO

__all__ = ["SCHEDULER_CHANNEL_ID", "ScheduleChannelSender"]

SCHEDULER_CHANNEL_ID: UUID = uuid5(NAMESPACE_URL, "slo:channels:scheduler")
"""Stable id of the one ``scheduler`` channel every scheduler process shares."""


class ScheduleChannelSender:
    """Sends one invocation's prompt to an agent session as the schedule's own sender.

    WHAT: Registers the shared ``scheduler`` channel and the schedule's sender
        participant (idempotent upserts), then sends one row to the target
        session's agent participant through the public gateway API.
    WHO: ``DeliverScheduleInvocationAppService`` for every invocation that must
        be delivered.
    WHEN: Once per invocation; the caller owns the gateway lifetime.
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
        schedule: ScheduleDAO,
        invocation_id: UUID,
        recipient_session_id: str,
    ) -> ChannelMessageDAO:
        """Send one invocation's prompt to the recipient session.

        Args:
            schedule (ScheduleDAO): The schedule whose sender participant sends
                the row; its coalescing rule applies.
            invocation_id (UUID): The invocation id; also the channel message id.
            recipient_session_id (str): The agent session that receives the row.

        Returns:
            ChannelMessageDAO: The stored channel row.

        Raises:
            UnknownParticipantError: The target session has never registered.
            RecipientClosedError: The target session does not admit this sender.
        """
        sender: ParticipantDAO = await self._register_schedule_sender(
            schedule_id=str(schedule.id), schedule_name=schedule.name
        )
        scheduled_prompt: NewMessageDAO = NewMessageDAO(
            id=invocation_id,
            sender_id=sender.id,
            recipient_id=channel_participant_id_for_session(session_id=recipient_session_id),
            message_contents=schedule.prompt,
            message_type="prompt",
            channel_id=SCHEDULER_CHANNEL_ID,
            coalesce_key=(schedule.coalescing_key if schedule.coalescing_mode == "latest_by_key" else None),
        )
        return await self._gateway.send(new=scheduled_prompt)

    async def stored_message(self, *, invocation_id: UUID) -> Optional[ChannelMessageDAO]:
        """Read the channel row whose id is the invocation id, without writing.

        Args:
            invocation_id (UUID): The invocation id to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored channel row, or None when the
                send never happened.
        """
        return await self._gateway.find_message(message_id=invocation_id)

    async def _register_schedule_sender(self, *, schedule_id: str, schedule_name: str) -> ParticipantDAO:
        """Register the shared scheduler channel and this schedule's sender participant.

        The participant is the ``system`` occupant of the ``(scheduler channel,
        schedule_id)`` slot, so every fire of one schedule — from any process —
        shares one sender, and a closed interactive session keeps its rows in
        the durable inbox instead of refusing them as an operator's.

        Args:
            schedule_id (str): Schedule identity stored as ``external_ref``.
            schedule_name (str): Human label; the sender is ``scheduler <name>``.

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
            external_ref=schedule_id,
            name=f"scheduler {schedule_name}",
        )
