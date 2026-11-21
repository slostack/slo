"""ChannelGateway — the one API every channel caller uses (108.1).

Adapters, the TUI, headless orchestrators and (later) the CLI all talk to the
queue through this application service; only the repository below it knows SQL.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from config.cfg import cfg

from src.channels.dao import (
    ChannelDAO,
    ChannelKind,
    ChannelMessageDAO,
    NewMessageDAO,
    ParticipantDAO,
    utc_now,
)
from src.channels.repository import ChannelRepository

__all__ = ["ChannelGateway"]


class ChannelGateway:
    """Application service over the channel repository."""

    def __init__(self, *, repository: ChannelRepository) -> None:
        """Compose the gateway over one repository.

        Args:
            repository (ChannelRepository): Open (or to-be-opened) repository.
        """
        self._repository: ChannelRepository = repository
        self._wakes: dict[UUID, asyncio.Event] = {}

    @property
    def repository(self) -> ChannelRepository:
        """Return the repository (composition seam for adapters/tests).

        Returns:
            ChannelRepository: The repository this gateway wraps.
        """
        return self._repository

    @classmethod
    async def default(cls) -> "ChannelGateway":
        """Open the shared process gateway on ``$SLO_HOME/channels/channels.db``.

        Returns:
            ChannelGateway: A gateway whose repository is open on the shared
                database file for this user.
        """
        slo_home: Path = Path(str(cfg(key="SLO_HOME") or Path.home() / ".slo"))
        repository: ChannelRepository = ChannelRepository(db_path=slo_home / "channels" / "channels.db")
        await repository.open()
        return cls(repository=repository)

    async def close(self) -> None:
        """Close the underlying repository."""
        await self._repository.close()

    async def register_channel(
        self,
        *,
        kind: ChannelKind,
        name: str,
        channel_id: Optional[UUID] = None,
    ) -> ChannelDAO:
        """Register (idempotently) one platform channel.

        Args:
            kind (ChannelKind): Platform type, e.g. ``tui``.
            name (str): Human-readable label, e.g. ``tui@host``.
            channel_id (Optional[UUID]): Stable id when the adapter persists
                one (TUI stores it in ``channels/tui.json``); otherwise new.

        Returns:
            ChannelDAO: The stored channel.
        """
        now = utc_now()
        channel: ChannelDAO = ChannelDAO(
            id=channel_id or uuid4(),
            kind=kind,
            name=name,
            created_at=now,
            last_seen_at=now,
        )
        return await self._repository.upsert_channel(channel=channel)

    async def register_user(
        self,
        *,
        channel_id: UUID,
        name: str,
        external_ref: Optional[str] = None,
    ) -> ParticipantDAO:
        """Register (idempotently) the user talking through one channel.

        Reuses the existing occupant of the channel's ``external_ref`` slot
        (refreshing its name and heartbeat) so a restarted adapter keeps its
        identity; pending rows addressed to it survive the restart.

        Args:
            channel_id (UUID): Channel the user talks through.
            name (str): Display name, e.g. ``sid (tui)``.
            external_ref (Optional[str]): Platform-side identity.

        Returns:
            ParticipantDAO: The stored participant.
        """
        if external_ref is not None:
            existing: Optional[ParticipantDAO] = await self._repository.participant_by_external_ref(
                channel_id=channel_id,
                external_ref=external_ref,
            )
            if existing is not None:
                refreshed: ParticipantDAO = existing.model_copy(
                    update={"name": name, "status": "open", "last_seen_at": utc_now()}
                )
                return await self._repository.upsert_participant(participant=refreshed)
        now = utc_now()
        participant: ParticipantDAO = ParticipantDAO(
            id=uuid4(),
            kind="user",
            name=name,
            channel_id=channel_id,
            external_ref=external_ref,
            status="open",
            last_seen_at=now,
            created_at=now,
        )
        return await self._repository.upsert_participant(participant=participant)

    async def register_agent(self, *, session_id: UUID, name: str) -> ParticipantDAO:
        """Register (idempotently) one agent session participant.

        The agent's participant id IS its session id (overview §2.3).

        Args:
            session_id (UUID): Agent session id.
            name (str): Display name, e.g. ``slo <short id>``.

        Returns:
            ParticipantDAO: The stored participant.
        """
        now = utc_now()
        participant: ParticipantDAO = ParticipantDAO(
            id=session_id,
            kind="agent",
            name=name,
            channel_id=None,
            external_ref=None,
            status="open",
            last_seen_at=now,
            created_at=now,
        )
        return await self._repository.upsert_participant(participant=participant)

    async def close_agent(self, *, session_id: UUID, reason: str) -> int:
        """Close one agent participant and cancel its pending inbound rows.

        Args:
            session_id (UUID): Agent session to close.
            reason (str): Cancellation reason for pending rows, e.g.
                ``session_closed``.

        Returns:
            int: Number of pending inbound rows cancelled.
        """
        await self._repository.set_participant_status(participant_id=session_id, status="closed")
        return await self._repository.cancel_pending_inbound(recipient_id=session_id, reason=reason)

    async def send(self, *, new: NewMessageDAO) -> ChannelMessageDAO:
        """Insert one message and wake the in-process poller if there is one.

        Args:
            new (NewMessageDAO): Sender-supplied message data.

        Returns:
            ChannelMessageDAO: The stored row.
        """
        stored: ChannelMessageDAO = await self._repository.insert_message(new=new)
        wake: Optional[asyncio.Event] = self._wakes.get(stored.recipient_id)
        if wake is not None:
            wake.set()
        return stored

    async def cancel(self, *, message_id: UUID, by: Optional[UUID] = None, reason: str = "operator") -> bool:
        """Cancel a pending row on behalf of a participant or the recipient agent.

        When ``by`` is given, only the sender or the recipient may cancel, and
        only while the row is neither accepted nor cancelled. When ``by`` is
        ``None`` the call is an internal system cancellation (the recipient
        agent's poller, e.g. ``start_failed``); no actor check applies.

        Args:
            message_id (UUID): Row to cancel.
            by (Optional[UUID]): Participant requesting the cancellation.
            reason (str): Cancellation reason recorded on the row.

        Returns:
            bool: ``True`` when the row was cancelled by this call.
        """
        stored: Optional[ChannelMessageDAO] = await self._repository.get(message_id=message_id)
        if stored is None:
            return False
        if by is not None and by not in (stored.sender_id, stored.recipient_id):
            return False
        return await self._repository.cancel(message_id=message_id, reason=reason)

    async def force(self, *, message_id: UUID, by: UUID) -> bool:
        """Force a pending row into the current run at its next boundary (108.2).

        Only the sender or the recipient may force, and only while the row is
        neither accepted nor cancelled. Forcing an already-forced row is a
        no-op success. The recipient's in-process poller is woken so an idle
        agent starts the forced row at once (108.2 F3).

        Args:
            message_id (UUID): Row to force.
            by (UUID): Participant requesting the force.

        Returns:
            bool: ``True`` when the row is now forced; ``False`` when it was
                accepted, cancelled, unknown, or ``by`` is an outside actor.
        """
        stored: Optional[ChannelMessageDAO] = await self._repository.get(message_id=message_id)
        if stored is None:
            return False
        if by not in (stored.sender_id, stored.recipient_id):
            return False
        forced: bool = await self._repository.force(message_id=message_id)
        if forced:
            wake: Optional[asyncio.Event] = self._wakes.get(stored.recipient_id)
            if wake is not None:
                wake.set()
        return forced

    async def accept(self, *, message_id: UUID) -> bool:
        """Accept a row exactly once (see repository).

        Args:
            message_id (UUID): Row to accept.

        Returns:
            bool: Whether this call performed the acceptance.
        """
        return await self._repository.accept(message_id=message_id)

    async def get(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return one stored row.

        Args:
            message_id (UUID): Row to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored row, or ``None``.
        """
        return await self._repository.get(message_id=message_id)

    async def pending_inbound(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Return pending inbound rows for one recipient, FIFO.

        Args:
            recipient_id (UUID): Recipient to check.

        Returns:
            list[ChannelMessageDAO]: Pending rows in index order.
        """
        return await self._repository.pending_inbound(recipient_id=recipient_id)

    async def pending_outbound(self, *, recipient_ids: list[UUID]) -> list[ChannelMessageDAO]:
        """Return pending outbound rows addressed to any of the recipients.

        Args:
            recipient_ids (list[UUID]): Recipients to check.

        Returns:
            list[ChannelMessageDAO]: Pending outbound rows.
        """
        return await self._repository.pending_outbound(recipient_ids=recipient_ids)

    async def heartbeat(self, *, participant_id: UUID) -> None:
        """Refresh one participant's heartbeat.

        Args:
            participant_id (UUID): Participant to stamp.
        """
        await self._repository.heartbeat(participant_id=participant_id)

    def local_wake(self, *, recipient_id: UUID) -> asyncio.Event:
        """Return the shared wake event for one recipient's in-process poller.

        ``send()`` sets this event when the recipient matches, so a local
        send wakes the poller without waiting for the next poll tick.

        Args:
            recipient_id (UUID): Participant whose poller waits on the event.

        Returns:
            asyncio.Event: The shared wake event for that recipient.
        """
        wake: Optional[asyncio.Event] = self._wakes.get(recipient_id)
        if wake is None:
            wake = asyncio.Event()
            self._wakes[recipient_id] = wake
        return wake
