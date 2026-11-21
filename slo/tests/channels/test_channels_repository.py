"""Domain and repository behavior tests for ``src/channels/`` (108.1 M1).

Levels: domain-service / repository journey against a real SQLite WAL database
under tmp paths. No mocks for internal collaborators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


async def _open_repository(*, tmp_path: Path) -> ChannelRepository:
    """Open one real repository on a fresh temp database file."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return repository


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open a gateway over one real temp database."""
    return ChannelGateway(repository=await _open_repository(tmp_path=tmp_path))


class TestSchemaBootstrap:
    async def test_open_creates_the_three_tables_and_wal_mode(self, tmp_path: Path) -> None:
        repository: ChannelRepository = await _open_repository(tmp_path=tmp_path)
        try:
            tables: set[str] = await repository.table_names()
            assert {"channels", "participants", "messages"} <= tables
            assert await repository.user_version() == 1
            assert await repository.journal_mode() == "wal"
            db_file: Path = tmp_path / "channels.db"
            assert oct(db_file.stat().st_mode & 0o777) == "0o600"
        finally:
            await repository.close()


class TestRegisterParticipants:
    async def test_register_channel_user_and_agent_round_trip(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            session_id: UUID = uuid4()
            agent: ParticipantDAO = await gateway.register_agent(session_id=session_id, name="slo abc12345")
            assert channel.kind == "tui"
            assert user.kind == "user" and user.channel_id == channel.id
            assert agent.kind == "agent" and agent.id == session_id and agent.status == "open"
        finally:
            await gateway.close()


class TestInsertMessage:
    async def test_insert_assigns_gapless_index_and_resolves_names(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            first: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="run tests",
                    channel_id=channel.id,
                )
            )
            second: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="then lint",
                    channel_id=channel.id,
                )
            )
            assert first.message_index == 1 and second.message_index == 2
            assert first.agent_session_id == agent.id
            assert first.sender_name == "tester (tui)" and first.recipient_name == "slo abc12345"
            assert first.accepted_at is None and first.cancelled_at is None
        finally:
            await gateway.close()

    async def test_duplicate_id_returns_the_existing_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            message_id: UUID = uuid4()
            new_message = NewMessageDAO(
                id=message_id,
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents="run tests",
                channel_id=channel.id,
            )
            first: ChannelMessageDAO = await gateway.send(new=new_message)
            again: ChannelMessageDAO = await gateway.send(new=new_message)
            assert again.id == first.id and again.message_index == first.message_index
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert len(pending) == 1
        finally:
            await gateway.close()

    async def test_send_to_unknown_recipient_raises(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            with pytest.raises(UnknownParticipantError):
                await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id,
                        recipient_id=uuid4(),
                        message_contents="hello?",
                        channel_id=channel.id,
                    )
                )
        finally:
            await gateway.close()

    async def test_send_to_closed_agent_raises(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            cancelled: int = await gateway.close_agent(session_id=agent.id, reason="session_closed")
            assert cancelled == 0
            with pytest.raises(RecipientClosedError):
                await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id,
                        recipient_id=agent.id,
                        message_contents="too late",
                        channel_id=channel.id,
                    )
                )
        finally:
            await gateway.close()

    async def test_close_agent_cancels_pending_inbound(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="one", channel_id=channel.id
                )
            )
            cancelled: int = await gateway.close_agent(session_id=agent.id, reason="session_closed")
            assert cancelled == 1
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert pending == []
        finally:
            await gateway.close()


class TestAcceptAndCancel:
    async def test_accept_happens_once(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            message: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="hi", channel_id=channel.id
                )
            )
            assert await gateway.accept(message_id=message.id) is True
            assert await gateway.accept(message_id=message.id) is False
            stored: ChannelMessageDAO | None = await gateway.get(message_id=message.id)
            assert stored is not None and stored.accepted_at is not None
        finally:
            await gateway.close()

    async def test_cancel_pending_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            message: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="hi", channel_id=channel.id
                )
            )
            assert await gateway.cancel(message_id=message.id, by=user.id) is True
            stored: ChannelMessageDAO | None = await gateway.get(message_id=message.id)
            assert stored is not None
            assert stored.cancelled_at is not None and stored.cancel_reason == "operator"
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
        finally:
            await gateway.close()

    async def test_cancel_accepted_row_fails(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            message: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="hi", channel_id=channel.id
                )
            )
            await gateway.accept(message_id=message.id)
            assert await gateway.cancel(message_id=message.id, by=user.id) is False
        finally:
            await gateway.close()


class TestForcePendingRow:
    async def test_force_sets_forced_at_on_a_pending_row(self, tmp_path: Path) -> None:
        """``force`` stamps ``forced_at`` on a pending row exactly once (108.2 F7)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            row: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="use pytest -x",
                    channel_id=channel.id,
                )
            )
            forced: bool = await gateway.force(message_id=row.id, by=agent.id)
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
            assert forced is True
            assert stored is not None and stored.forced_at is not None
            assert stored.accepted_at is None and stored.cancelled_at is None

            forced_again: bool = await gateway.force(message_id=row.id, by=agent.id)
            assert forced_again is True
        finally:
            await gateway.close()

    async def test_force_refuses_accepted_cancelled_and_unknown_rows(self, tmp_path: Path) -> None:
        """Only a pending row can be forced; accepted rows report ``already running`` upstream."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            accepted: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="running",
                    channel_id=channel.id,
                )
            )
            cancelled: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="gone", channel_id=channel.id
                )
            )
            await gateway.accept(message_id=accepted.id)
            await gateway.cancel(message_id=cancelled.id, reason="operator")
            assert await gateway.force(message_id=accepted.id, by=user.id) is False
            assert await gateway.force(message_id=cancelled.id, by=user.id) is False
            assert await gateway.force(message_id=uuid4(), by=user.id) is False
        finally:
            await gateway.close()

    async def test_force_refuses_an_outside_actor(self, tmp_path: Path) -> None:
        """Only the sender or the recipient may force a row (mirrors ``cancel``)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            other: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo other")
            row: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="hi", channel_id=channel.id
                )
            )
            assert await gateway.force(message_id=row.id, by=other.id) is False
        finally:
            await gateway.close()


class TestForcedFirstOrdering:
    async def test_pending_inbound_orders_forced_rows_first_then_fifo(self, tmp_path: Path) -> None:
        """``pending_inbound`` sorts forced rows ahead of normal rows, FIFO within each class.

        Spec 108.2 §4: ``ORDER BY (forced_at IS NULL), message_index``.
        """
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            rows: list[ChannelMessageDAO] = []
            for text in ("normal one", "normal two", "late normal"):
                rows.append(
                    await gateway.send(
                        new=NewMessageDAO(
                            sender_id=user.id,
                            recipient_id=agent.id,
                            message_contents=text,
                            channel_id=channel.id,
                        )
                    )
                )
            forced_row: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="forced later",
                    channel_id=channel.id,
                    force=True,
                )
            )
            await gateway.force(message_id=rows[2].id, by=agent.id)
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert [row.message_contents for row in pending] == [
                "late normal",
                "forced later",
                "normal one",
                "normal two",
            ]
            assert pending[0].id == rows[2].id
            assert pending[0].forced_at is not None and pending[1].forced_at is not None
            assert forced_row.forced_at is not None
        finally:
            await gateway.close()


class TestPendingReads:
    async def test_pending_inbound_fifo_by_index(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            for text in ("one", "two", "three"):
                await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id, recipient_id=agent.id, message_contents=text, channel_id=channel.id
                    )
                )
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert [row.message_contents for row in pending] == ["one", "two", "three"]
        finally:
            await gateway.close()

    async def test_pending_outbound_finds_replies_for_a_channel_user(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="hi", channel_id=channel.id
                )
            )
            reply: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="answer",
                    message_type="reply",
                    in_reply_to_id=request.id,
                    channel_id=channel.id,
                )
            )
            outbound: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
            assert [row.id for row in outbound] == [reply.id]
            assert reply.agent_session_id == agent.id
        finally:
            await gateway.close()

    async def test_two_processes_share_one_database_without_index_gaps(self, tmp_path: Path) -> None:
        db_path: Path = tmp_path / "channels.db"
        first: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=db_path))
        await first.repository.open()
        channel: ChannelDAO = await first.register_channel(kind="tui", name="tui@testhost")
        user: ParticipantDAO = await first.register_user(channel_id=channel.id, name="tester (tui)")
        agent: ParticipantDAO = await first.register_agent(session_id=uuid4(), name="slo abc12345")
        try:
            second: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=db_path))
            await second.repository.open()
            try:
                left = await first.send(
                    new=NewMessageDAO(
                        sender_id=user.id, recipient_id=agent.id, message_contents="a", channel_id=channel.id
                    )
                )
                right = await second.send(
                    new=NewMessageDAO(
                        sender_id=user.id, recipient_id=agent.id, message_contents="b", channel_id=channel.id
                    )
                )
                assert {left.message_index, right.message_index} == {1, 2}
            finally:
                await second.close()
        finally:
            await first.close()
