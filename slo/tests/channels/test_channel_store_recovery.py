"""108.1 §6 / 1081-R06: a corrupt queue file is set aside and recreated; a locked queue is never quarantined.

Both cases use the real SQLite file under the per-test ``SLO_HOME`` that the
gateway resolves by default. A corrupt file is recovered (renamed to
``channels.db.corrupt-<stamp>`` with its bytes preserved, then a fresh queue is
created). A lock held by another connection is a transient failure: the send
fails visibly and the database file stays exactly where it was.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway

_GARBAGE_BYTES: bytes = b"this is not a sqlite database; it was truncated mid-write\n" * 64


async def _register_queue_members(*, gateway: ChannelGateway) -> tuple[ChannelDAO, ParticipantDAO, UUID]:
    """Register one channel, one user and one agent on an open gateway.

    Args:
        gateway (ChannelGateway): Open gateway over the queue under test.

    Returns:
        tuple[ChannelDAO, ParticipantDAO, UUID]: The channel, the user and the agent session id.
    """
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@recovery")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="recovery (tui)")
    session_id: UUID = uuid4()
    await gateway.register_agent(session_id=session_id, name="slo recovery")
    return channel, user, session_id


class TestCorruptQueueFileRecovery:
    """A file that is not a SQLite database is preserved aside and replaced by a working queue."""

    async def test_corrupt_channels_db_is_set_aside_and_a_fresh_queue_accepts_a_prompt(
        self, isolated_slo_home: Path
    ) -> None:
        """Opening a corrupt queue renames the file, keeps its bytes, and the new queue accepts sends.

        The recovery must not raise to the caller: the TUI opens the queue once at
        mount, and a corrupt file must end with a usable queue plus the set-aside copy.
        """
        channels_dir: Path = isolated_slo_home / "channels"
        channels_dir.mkdir(parents=True, exist_ok=True)
        queue_path: Path = channels_dir / "channels.db"
        queue_path.write_bytes(_GARBAGE_BYTES)

        gateway: ChannelGateway = ChannelGateway.at_default_path()
        await gateway.open()
        try:
            _channel, user, session_id = await _register_queue_members(gateway=gateway)
            sent: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=session_id, message_contents="after recovery"
                )
            )
            schema_version: int = await gateway.repository.user_version()
        finally:
            await gateway.close()

        set_aside: list[Path] = sorted(channels_dir.glob("channels.db.corrupt-*"))
        assert len(set_aside) == 1, [path.name for path in channels_dir.iterdir()]
        assert set_aside[0].read_bytes() == _GARBAGE_BYTES
        assert schema_version == 1
        assert (sent.message_index, sent.message_contents) == (1, "after recovery")

    async def test_corrupt_queue_is_still_readable_by_sqlite_after_recovery(self, isolated_slo_home: Path) -> None:
        """The recreated file is a valid SQLite database that a plain sqlite3 connection can read.

        Guards against recovery that renames the file but leaves an unopenable placeholder behind.
        """
        channels_dir: Path = isolated_slo_home / "channels"
        channels_dir.mkdir(parents=True, exist_ok=True)
        (channels_dir / "channels.db").write_bytes(_GARBAGE_BYTES)

        gateway: ChannelGateway = ChannelGateway.at_default_path()
        await gateway.open()
        await gateway.close()

        connection: sqlite3.Connection = sqlite3.connect(str(channels_dir / "channels.db"))
        try:
            tables: set[str] = {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            integrity: str = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()

        assert {"channels", "participants", "messages"} <= tables
        assert integrity == "ok"


class TestLockedQueueIsNotQuarantined:
    """A write lock held by another connection fails the send but never discards the queue."""

    async def test_send_while_another_connection_holds_the_write_lock_fails_and_keeps_the_database(
        self, isolated_slo_home: Path
    ) -> None:
        """The send fails with a lock error, nothing is set aside, and the queue works once the lock clears."""
        channels_dir: Path = isolated_slo_home / "channels"
        gateway: ChannelGateway = ChannelGateway.at_default_path()
        await gateway.open()
        _channel, user, session_id = await _register_queue_members(gateway=gateway)
        queue_path: Path = channels_dir / "channels.db"
        holder: sqlite3.Connection = sqlite3.connect(str(queue_path), isolation_level=None)
        try:
            holder.execute("BEGIN IMMEDIATE")
            failure: BaseException | None = None
            try:
                await gateway.send(
                    new=NewMessageDAO(sender_id=user.id, recipient_id=session_id, message_contents="blocked")
                )
            except Exception as error:  # noqa: BLE001 — the assertion below names the expected lock error
                failure = error
            holder.execute("ROLLBACK")
        finally:
            holder.close()

        try:
            assert isinstance(failure, sqlite3.OperationalError), repr(failure)
            assert "locked" in str(failure)
            assert sorted(channels_dir.glob("channels.db.corrupt-*")) == []
            assert await gateway.repository.count_participants() == 2
            retried: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=user.id, recipient_id=session_id, message_contents="retried")
            )
        finally:
            await gateway.close()

        assert (retried.message_index, retried.message_contents) == (1, "retried")
