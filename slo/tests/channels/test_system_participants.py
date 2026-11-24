"""System participant registration (108.6 §3 Participants row; overview §2.3).

Level: application service → repository → real SQLite WAL file under
``tmp_path``. A system sender (one schedule on the ``scheduler`` channel) is
registered by ``ChannelGateway.register_system``; its identity is the
``UNIQUE(channel_id, external_ref)`` slot. No mocks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


async def _open_gateway(*, db_path: Path) -> ChannelGateway:
    """Open one gateway over the given database file.

    Args:
        db_path (Path): Test-owned ``channels.db`` path.

    Returns:
        ChannelGateway: Open gateway.
    """
    gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=db_path))
    await gateway.open()
    return gateway


class TestRegisterSystem:
    async def test_registers_one_open_system_participant_per_channel_slot(self, tmp_path: Path) -> None:
        """Repeated registration keeps one id, refreshes the name, and stays a system sender."""
        gateway: ChannelGateway = await _open_gateway(db_path=tmp_path / "channels.db")
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="scheduler", name="scheduler@host")
            first: ParticipantDAO = await gateway.register_system(
                channel_id=channel.id, name="scheduler Nightly", external_ref="sched-1"
            )
            again: ParticipantDAO = await gateway.register_system(
                channel_id=channel.id, name="scheduler Nightly (renamed)", external_ref="sched-1"
            )
            other: ParticipantDAO = await gateway.register_system(
                channel_id=channel.id, name="scheduler Weekly", external_ref="sched-2"
            )
            stored: Optional[ParticipantDAO] = await gateway.get_participant(participant_id=first.id)

            assert again.id == first.id
            assert other.id != first.id
            assert stored is not None
            assert (stored.kind, stored.status, stored.channel_id, stored.external_ref) == (
                "system",
                "open",
                channel.id,
                "sched-1",
            )
            assert stored.name == "scheduler Nightly (renamed)"
            assert stored.is_operator is False
            assert await gateway.count_participants() == 2
        finally:
            await gateway.close()

    async def test_an_existing_user_in_the_slot_converts_to_system_keeping_its_id_and_rows(
        self, tmp_path: Path
    ) -> None:
        """A pre-IR-1 scheduler sender (stored as a user) becomes a system sender in place.

        Its pending rows keep their sender id, and a closed interactive session
        (durable inbox) now admits the schedule's rows instead of refusing an operator.
        """
        gateway: ChannelGateway = await _open_gateway(db_path=tmp_path / "channels.db")
        try:
            session_id: UUID = uuid4()
            await gateway.register_agent(session_id=session_id, name="slo target", durable_inbox=True)
            channel: ChannelDAO = await gateway.register_channel(kind="scheduler", name="scheduler@host")
            legacy: ParticipantDAO = await gateway.register_user(
                channel_id=channel.id, name="scheduler Nightly", external_ref="sched-1"
            )
            earlier: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=legacy.id, recipient_id=session_id, message_contents="run 1")
            )

            converted: ParticipantDAO = await gateway.register_system(
                channel_id=channel.id, name="scheduler Nightly", external_ref="sched-1"
            )
            await gateway.close_agent(session_id=session_id, reason="session_closed")
            later: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=converted.id, recipient_id=session_id, message_contents="run 2")
            )
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=session_id)

            assert converted.id == legacy.id
            assert converted.kind == "system"
            assert await gateway.count_participants() == 2
            assert [row.id for row in pending] == [earlier.id, later.id]
            assert {row.sender_id for row in pending} == {legacy.id}
        finally:
            await gateway.close()

    async def test_concurrent_processes_agree_on_one_identity(self, tmp_path: Path) -> None:
        """Two gateways (two connections, as two scheduler processes) racing on one slot share one id."""
        db_path: Path = tmp_path / "channels.db"
        first_gateway: ChannelGateway = await _open_gateway(db_path=db_path)
        second_gateway: ChannelGateway = await _open_gateway(db_path=db_path)
        try:
            channel: ChannelDAO = await first_gateway.register_channel(
                kind="scheduler", name="scheduler@host"
            )
            registered: list[ParticipantDAO] = list(
                await asyncio.gather(
                    *(
                        gateway.register_system(
                            channel_id=channel.id, name="scheduler Nightly", external_ref="sched-1"
                        )
                        for gateway in (first_gateway, second_gateway) * 4
                    )
                )
            )

            assert len({participant.id for participant in registered}) == 1
            assert await first_gateway.count_participants() == 1
        finally:
            await first_gateway.close()
            await second_gateway.close()
