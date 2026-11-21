"""``ChannelBoundaryInbox`` — the channel-queue adapter for ``BoundaryInbox`` (108.2).

The adapter is shared by the session's poller and its agent: the poller
refreshes the forced-row snapshot every tick (so the agent's synchronous
``has_forced`` stays fresh), and the agent takes pending forced prompt rows
at each safe boundary, then confirms them (accepts) after the history record
is written.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway

__all__ = ["ChannelBoundaryInbox"]


class ChannelBoundaryInbox:
    """Reads forced prompt rows for one agent participant from the shared queue.

    The snapshot is the set of pending forced prompt row ids; ``reserve``
    removes a row the poller is starting as a run from both the snapshot and
    ``take`` so the agent's boundary can never re-apply its own prompt.
    """

    def __init__(
        self,
        *,
        gateway: ChannelGateway,
        agent_id: UUID,
        operator_participant_id: Optional[UUID] = None,
    ) -> None:
        """Bind the adapter to the shared gateway and one agent participant.

        Args:
            gateway (ChannelGateway): The shared queue API.
            agent_id (UUID): The agent's participant id (its session id).
            operator_participant_id (Optional[UUID]): The operator's user
                participant id when the session knows it (the TUI registers
                its own user); rows from that participant take the transcript
                label ``you`` (108.2 §4), while every other sender keeps its
                recorded ``sender_name``.
        """
        self._gateway: ChannelGateway = gateway
        self._agent_id: UUID = agent_id
        self._operator_participant_id: Optional[UUID] = operator_participant_id
        self._forced_ids: set[UUID] = set()
        self._reserved_ids: set[UUID] = set()
        self._in_flight_ids: set[UUID] = set()

    async def refresh(self) -> None:
        """Re-read the queue and update the forced-row snapshot.

        The poller calls this every tick (including while a run is in
        flight) so a forced row sent mid-run becomes visible to the agent's
        stop decision within one poll interval.
        """
        rows: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._agent_id,
        )
        # Rows taken at a boundary but not yet confirmed stay pending in the
        # queue; excluding them here keeps a refresh between take and confirm
        # from reinserting them into the snapshot and reviving the run for a
        # delivery that is already being applied (108.2 B3).
        self._forced_ids = {
            row.id
            for row in rows
            if row.forced_at is not None and row.message_type == "prompt"
        } - self._in_flight_ids

    def reserve(self, *, message_id: UUID) -> None:
        """Exclude one row from the boundary while the poller runs it.

        Args:
            message_id (UUID): The row the poller started a run for.
        """
        self._reserved_ids.add(message_id)

    def release(self, *, message_id: UUID) -> None:
        """Stop excluding a reserved row once its run has ended.

        Args:
            message_id (UUID): The row whose run finished.
        """
        self._reserved_ids.discard(message_id)

    def has_forced(self) -> bool:
        """Return whether the snapshot holds an unreserved forced prompt row.

        Returns:
            bool: ``True`` when a forced row was pending at the latest refresh
                and is not the run the poller is currently starting.
        """
        return bool((self._forced_ids - self._in_flight_ids) - self._reserved_ids)

    async def take(self, *, iteration: int) -> list[BoundaryDeliveryDAO]:
        """Take pending notes first, then forced prompt rows, FIFO by message index.

        Notes join the current run's context at the boundary before forced
        prompts (108.3 §2). Rows the poller reserved for its own run, and rows
        taken here but not yet confirmed, are never taken again, so a take can
        never apply a delivery twice. Notices and normal prompts are never
        taken here (108.2 §5).

        Args:
            iteration (int): Agent loop iteration whose boundary takes them.

        Returns:
            list[BoundaryDeliveryDAO]: The taken rows in delivery order — notes
                before forced prompts.
        """
        rows: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._agent_id,
        )
        claimable: list[ChannelMessageDAO] = [
            row
            for row in rows
            if row.id not in self._reserved_ids and row.id not in self._in_flight_ids
        ]
        notes: list[ChannelMessageDAO] = [row for row in claimable if row.message_type == "note"]
        forced_rows: list[ChannelMessageDAO] = [
            row
            for row in claimable
            if row.forced_at is not None and row.message_type == "prompt"
        ]
        taken: list[ChannelMessageDAO] = notes + forced_rows
        # The fresh read is the truth: replace the snapshot with the ids the
        # queue still reports so a cached id the queue dropped (cancelled or
        # accepted since the last refresh) cannot revive the run for an empty
        # boundary, and reconcile the taken ids out of the snapshot.
        self._forced_ids = {row.id for row in forced_rows}
        # The taken rows are in flight until their confirm settles them, so a
        # refresh between take and confirm cannot reinsert them (108.2 B3).
        self._in_flight_ids |= {row.id for row in taken}
        return [
            BoundaryDeliveryDAO(
                message_id=row.id,
                text=row.message_contents,
                sender_name=self._sender_label(sender_id=row.sender_id, sender_name=row.sender_name),
                iteration=iteration,
            )
            for row in taken
        ]

    def _sender_label(self, *, sender_id: UUID, sender_name: str) -> str:
        """Return the transcript label for one taken row's sender.

        Rows the operator sent through the session's own channel take the
        ``you`` label (108.2 §4); every other sender keeps the recorded name
        so the transcript can credit external senders.
        """
        if self._operator_participant_id is not None and sender_id == self._operator_participant_id:
            return "you"
        return sender_name

    async def confirm(self, *, deliveries: list[BoundaryDeliveryDAO]) -> None:
        """Accept every taken row exactly once (spec: accept after the context write).

        Args:
            deliveries (list[BoundaryDeliveryDAO]): The taken deliveries.
        """
        for delivery in deliveries:
            await self._gateway.accept(message_id=delivery.message_id)
        self._in_flight_ids -= {delivery.message_id for delivery in deliveries}
