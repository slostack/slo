"""`InvocationOutcomeReconciler` — the only writer of the invocation outcome columns."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.schedules.dao import InvocationOutcomeDAO, ScheduleInvocationDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository

__all__ = ["InvocationOutcomeReconciler"]


class InvocationOutcomeReconciler:
    """Copies accepted / cancelled / reply facts from the channel row onto invocations."""

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        gateway: ChannelGateway,
        invocations: ScheduleInvocationRepository,
    ) -> None:
        """Bind the collaborators the reconciler owns.

        Args:
            database (ScheduleDatabase): The schedules database; opens one
                transaction per invocation it updates.
            gateway (ChannelGateway): The channel API; the source of the facts.
            invocations (ScheduleInvocationRepository): The invocation table SQL.
        """
        self._database: ScheduleDatabase = database
        self._gateway: ChannelGateway = gateway
        self._invocations: ScheduleInvocationRepository = invocations

    async def reconcile(self, *, now: datetime, limit: int) -> int:
        """Refresh the outcome snapshot of delivered invocations.

        Args:
            now (datetime): The boundary clock instant.
            limit (int): Maximum rows to refresh in this run.

        Returns:
            int: The number of rows whose outcome snapshot was set in this run.
        """
        async with self._database.transaction() as transaction:
            awaiting = await self._invocations.list_awaiting_outcome(limit=limit, transaction=transaction)
        reconciled: int = 0
        for invocation in awaiting:
            handled: bool = await self._reconcile_one(invocation=invocation, now=now)
            if handled:
                reconciled += 1
        return reconciled

    async def _reconcile_one(self, *, invocation: ScheduleInvocationDAO, now: datetime) -> bool:
        """Refresh one invocation's outcome snapshot from its channel message.

        Args:
            invocation (ScheduleInvocationDAO): The delivered invocation to refresh.
            now (datetime): The boundary clock instant.

        Returns:
            bool: True when the row's snapshot was set in this run.
        """
        channel_message_id: Optional[UUID] = invocation.channel_message_id
        if channel_message_id is None:
            return False
        channel_message: Optional[ChannelMessageDAO] = await self._gateway.find_message(
            message_id=channel_message_id
        )
        if channel_message is None:
            await self._mark_channel_row_gone(invocation_id=invocation.id, now=now)
            return True
        reply: Optional[ChannelMessageDAO] = await self._gateway.find_reply(message_id=channel_message_id)
        outcome: InvocationOutcomeDAO = InvocationOutcomeDAO(
            accepted_at=channel_message.accepted_at,
            cancelled_at=channel_message.cancelled_at,
            cancel_reason=channel_message.cancel_reason,
            reply_message_id=None if reply is None else reply.id,
        )
        await self._record_outcome(invocation_id=invocation.id, outcome=outcome, now=now)
        return True

    async def _mark_channel_row_gone(self, *, invocation_id: UUID, now: datetime) -> None:
        """Mark a delivered invocation whose channel row is gone.

        Args:
            invocation_id (UUID): The invocation to stop reading.
            now (datetime): The boundary clock instant.
        """
        async with self._database.transaction() as transaction:
            await self._invocations.mark_channel_row_gone(
                invocation_id=invocation_id,
                reconciled_at=now,
                transaction=transaction,
            )

    async def _record_outcome(
        self, *, invocation_id: UUID, outcome: InvocationOutcomeDAO, now: datetime
    ) -> None:
        """Copy one channel outcome snapshot onto a delivered invocation.

        Args:
            invocation_id (UUID): The invocation to update.
            outcome (InvocationOutcomeDAO): The channel facts to copy.
            now (datetime): The boundary clock instant.
        """
        async with self._database.transaction() as transaction:
            await self._invocations.record_outcome(
                invocation_id=invocation_id,
                outcome=outcome,
                reconciled_at=now,
                transaction=transaction,
            )
