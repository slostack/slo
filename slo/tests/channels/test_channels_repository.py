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
            assert await repository.user_version() == 3
            assert await repository.journal_mode() == "wal"
            db_file: Path = tmp_path / "channels.db"
            assert oct(db_file.stat().st_mode & 0o777) == "0o600"
        finally:
            await repository.close()

    async def test_v1_database_is_upgraded_to_v2_with_the_coalesce_column(self, tmp_path: Path) -> None:
        """A database left at schema v1 gains the ``coalesce_key`` column and index (108.3 §4)."""
        import sqlite3

        from src.channels.schema import SCHEMA_V1

        db_file: Path = tmp_path / "channels.db"
        connection: sqlite3.Connection = sqlite3.connect(database=str(db_file))
        connection.executescript(SCHEMA_V1)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        connection.close()

        repository: ChannelRepository = await _open_repository(tmp_path=tmp_path)
        try:
            assert await repository.user_version() == 3
            participant_columns: list[tuple[str, str]] = await repository.column_names(table="participants")
            assert "durable_inbox" in {name for name, _kind in participant_columns}
            columns: list[tuple[str, str]] = await repository.column_names(table="messages")
            assert "coalesce_key" in {name for name, _kind in columns}
            indexes: set[str] = await repository.index_names()
            assert "coalesce_pending" in indexes
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


class TestCoalesceSupersede:
    """Coalesce keys: a newer pending notice replaces an older one (108.3 §4)."""

    async def test_newer_pending_notice_supersedes_an_older_pending_one(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            older: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="fleet snapshot 1",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key=f"wf:abcd:fleet",
                )
            )
            newer: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="fleet snapshot 2",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key=f"wf:abcd:fleet",
                )
            )
            pending: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
            assert [row.id for row in pending] == [newer.id]
            stored_older: Optional[ChannelMessageDAO] = await gateway.get(message_id=older.id)
            assert stored_older is not None
            assert stored_older.cancelled_at is not None
            assert stored_older.cancel_reason == "superseded"
            stored_newer: Optional[ChannelMessageDAO] = await gateway.get(message_id=newer.id)
            assert stored_newer is not None
            assert stored_newer.cancelled_at is None and stored_newer.accepted_at is None
            assert stored_newer.coalesce_key == "wf:abcd:fleet"
        finally:
            await gateway.close()

    async def test_supersede_never_touches_accepted_rows_or_other_keys(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            other_agent: ParticipantDAO = await gateway.register_agent(
                session_id=uuid4(), name="slo def67890"
            )
            accepted: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="delivered snapshot",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key="wf:abcd:fleet",
                )
            )
            await gateway.accept(message_id=accepted.id)
            different_key: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="other key",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key="wf:abcd:other",
                )
            )
            different_sender: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=other_agent.id,
                    recipient_id=user.id,
                    message_contents="other sender",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key="wf:abcd:fleet",
                )
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="fleet snapshot 2",
                    message_type="notice",
                    channel_id=channel.id,
                    coalesce_key="wf:abcd:fleet",
                )
            )
            stored_accepted: Optional[ChannelMessageDAO] = await gateway.get(message_id=accepted.id)
            assert stored_accepted is not None
            assert stored_accepted.cancelled_at is None and stored_accepted.accepted_at is not None
            for row in (different_key, different_sender):
                stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
                assert stored is not None and stored.cancelled_at is None
        finally:
            await gateway.close()

    async def test_duplicate_id_retry_returns_the_existing_row_without_superseding(
        self, tmp_path: Path
    ) -> None:
        """A crashed notifier retrying its fixed uuid5 id never creates a second row."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            message_id: UUID = uuid4()
            first: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    id=message_id,
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="phase 1 done",
                    message_type="note",
                    channel_id=channel.id,
                )
            )
            second: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    id=message_id,
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="phase 1 done",
                    message_type="note",
                    channel_id=channel.id,
                    coalesce_key="wf:abcd:fleet",
                )
            )
            assert first.id == second.id == message_id
            pending: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
            assert [row.id for row in pending] == [message_id]
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=message_id)
            assert stored is not None and stored.coalesce_key is None
        finally:
            await gateway.close()


class TestAtomicCloseAgent:
    """close_agent marks the participant closed and cancels pending rows atomically (108.3 §2)."""

    async def test_close_agent_cancels_pending_inbound_and_refuses_further_sends(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="late prompt",
                    channel_id=channel.id,
                )
            )
            cancelled: int = await gateway.close_agent(session_id=agent.id, reason="recipient_closed")
            assert cancelled == 1
            participant: Optional[ParticipantDAO] = await gateway.get_participant(participant_id=agent.id)
            assert participant is not None and participant.status == "closed"
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert pending == []
            conversation: list[ChannelMessageDAO] = await gateway.conversation(agent_session_id=agent.id)
            assert conversation[0].cancel_reason == "recipient_closed"
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


class TestSentMessagesAndReplies:
    """Composer source queries: rows you sent and their replies (108.3 §4)."""

    async def test_recent_sent_messages_lists_the_newest_rows_first(self, tmp_path: Path) -> None:
        from src.channels.dao import SentMessageRowDAO

        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            for text in ("first", "second", "third"):
                await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id,
                        recipient_id=agent.id,
                        message_contents=text,
                        channel_id=channel.id,
                    )
                )
            rows: list[ChannelMessageDAO] = await gateway.recent_sent_messages(
                sender_id=user.id, recipient_id=agent.id, limit=5
            )
            assert [row.message_contents for row in rows] == ["third", "second", "first"]
        finally:
            await gateway.close()

    async def test_recent_sent_messages_scopes_sender_recipient_and_type(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            other_agent: ParticipantDAO = await gateway.register_agent(
                session_id=uuid4(), name="slo def67890"
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="mine", channel_id=channel.id
                )
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=other_agent.id,
                    message_contents="other target",
                    channel_id=channel.id,
                )
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="inbound",
                    channel_id=channel.id,
                )
            )
            rows: list[ChannelMessageDAO] = await gateway.recent_sent_messages(
                sender_id=user.id, recipient_id=agent.id, limit=5
            )
            assert [row.message_contents for row in rows] == ["mine"]
        finally:
            await gateway.close()

    async def test_reply_for_returns_the_answer_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="run tests",
                    channel_id=channel.id,
                )
            )
            reply: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=user.id,
                    message_contents="all green",
                    message_type="reply",
                    in_reply_to_id=request.id,
                )
            )
            found: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
            assert found is not None and found.id == reply.id
            assert await gateway.reply_for(message_id=reply.id) is None
        finally:
            await gateway.close()

    async def test_sent_row_state_and_previews_derive_from_the_queue(self, tmp_path: Path) -> None:
        from src.channels.dao import SentMessageRowDAO

        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
            forced: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="x" * 100,
                    channel_id=channel.id,
                    force=True,
                )
            )
            queued: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="waiting",
                    channel_id=channel.id,
                )
            )
            cancelled: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="gone",
                    channel_id=channel.id,
                )
            )
            await gateway.cancel(message_id=cancelled.id, reason="recipient_closed")
            await gateway.accept(message_id=forced.id)
            sent: list[SentMessageRowDAO] = await gateway.sent_rows(
                sender_id=user.id, recipient_id=agent.id, limit=5
            )
            by_id: dict = {row.message_id: row for row in sent}
            assert by_id[forced.id].state == "accepted"
            assert by_id[forced.id].forced is True
            assert by_id[forced.id].preview == "x" * 80
            assert by_id[queued.id].state == "queued"
            assert by_id[cancelled.id].state == "cancelled"
        finally:
            await gateway.close()


class TestDurableSessionInbox:
    """A closed interactive session keeps its inbox for agents and systems; finished agents refuse (108.3 §6)."""

    async def test_closed_session_admits_agent_rows_and_keeps_them_pending(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            session: ParticipantDAO = await gateway.register_agent(
                session_id=uuid4(), name="slo session", durable_inbox=True
            )
            workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator")
            operator_prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=user.id, recipient_id=session.id, message_contents="queued")
            )
            early_note: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id,
                    recipient_id=session.id,
                    message_contents="early",
                    message_type="note",
                )
            )
            cancelled: int = await gateway.close_agent(session_id=session.id, reason="session_closed")
            assert cancelled == 1
            stored_prompt: Optional[ChannelMessageDAO] = await gateway.get(message_id=operator_prompt.id)
            assert stored_prompt is not None and stored_prompt.cancel_reason == "session_closed"
            stored_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=early_note.id)
            assert stored_note is not None and stored_note.cancelled_at is None
            late: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id, recipient_id=session.id, message_contents="W completed"
                )
            )
            pending_ids: list[UUID] = [
                row.id for row in await gateway.pending_inbound(recipient_id=session.id)
            ]
            assert pending_ids == [early_note.id, late.id]
            closed_session: Optional[ParticipantDAO] = await gateway.get_participant(
                participant_id=session.id
            )
            assert closed_session is not None and closed_session.status == "closed"
            assert closed_session.durable_inbox is True
        finally:
            await gateway.close()

    async def test_closed_finished_agent_still_refuses_sends(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator")
            await gateway.close_agent(session_id=workflow.id, reason="recipient_closed")
            with pytest.raises(RecipientClosedError):
                await gateway.send(
                    new=NewMessageDAO(sender_id=user.id, recipient_id=workflow.id, message_contents="late")
                )
        finally:
            await gateway.close()
