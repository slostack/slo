"""108.1 §6 / 1081-R06: a corrupt queue file is set aside and recreated; a locked queue is never quarantined.

Both cases use the real SQLite file under the per-test ``SLO_HOME`` that the
gateway resolves by default. A corrupt file is recovered (renamed to
``channels.db.corrupt-<stamp>`` with its bytes preserved, then a fresh queue is
created). A lock held by another connection is a transient failure: the send
fails visibly and the database file stays exactly where it was.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sqlite3
import threading
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.channels.schema import SCHEMA_VERSION

_RECOVERY_LOCK_TIMEOUT_SECONDS: float = 6.0

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
        os.chmod(path=queue_path, mode=0o640)
        previous_backup: Path = channels_dir / "channels.db.corrupt-previous"
        previous_backup.write_bytes(b"older preserved recovery")
        sidecar_bytes: dict[str, bytes] = {
            "channels.db-wal": b"uncheckpointed queue writes",
            "channels.db-shm": b"shared memory metadata",
            "channels.db-journal": b"rollback journal bytes",
        }
        for sidecar_name, contents in sidecar_bytes.items():
            sidecar_path: Path = channels_dir / sidecar_name
            sidecar_path.write_bytes(contents)
            os.chmod(path=sidecar_path, mode=0o640)

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

        set_aside: list[Path] = sorted(
            path
            for path in channels_dir.glob("channels.db.corrupt-*")
            if path != previous_backup and not path.name.endswith(("-wal", "-shm", "-journal"))
        )
        assert len(set_aside) == 1, [path.name for path in channels_dir.iterdir()]
        assert set_aside[0].read_bytes() == _GARBAGE_BYTES
        for sidecar_name, contents in sidecar_bytes.items():
            sidecar_backup: Path = set_aside[0].with_name(
                f"{set_aside[0].name}{sidecar_name.removeprefix('channels.db')}"
            )
            assert sidecar_backup.read_bytes() == contents
            assert sidecar_backup.stat().st_mode & 0o777 == 0o640
        assert set_aside[0].stat().st_mode & 0o777 == 0o640
        assert previous_backup.read_bytes() == b"older preserved recovery"
        assert queue_path.stat().st_mode & 0o777 == 0o600
        for sidecar_name in sidecar_bytes:
            current_sidecar: Path = channels_dir / sidecar_name
            assert not current_sidecar.exists() or current_sidecar.read_bytes() != sidecar_bytes[sidecar_name]
        assert schema_version == SCHEMA_VERSION
        assert gateway.recovery_path == set_aside[0]
        assert (sent.message_index, sent.message_contents) == (1, "after recovery")

    async def test_open_without_database_recovery_exposes_no_recovery_path(self, tmp_path: Path) -> None:
        """A normal successful open exposes no corrupt-database recovery path."""
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )

        await gateway.open()
        try:
            assert gateway.recovery_path is None
        finally:
            await gateway.close()

    async def test_corrupt_sqlite_page_is_preserved_before_fresh_database_creation(
        self, tmp_path: Path
    ) -> None:
        """Integrity-check corruption is set aside with the original SQLite bytes intact."""
        queue_path: Path = tmp_path / "channels.db"
        connection: sqlite3.Connection = sqlite3.connect(str(queue_path))
        connection.execute("CREATE TABLE damaged (value TEXT NOT NULL)")
        connection.executemany("INSERT INTO damaged(value) VALUES (?)", [("x" * 1000,) for _ in range(20)])
        connection.commit()
        connection.close()
        damaged_bytes: bytearray = bytearray(queue_path.read_bytes())
        damaged_bytes[4096] = 0xFF
        queue_path.write_bytes(damaged_bytes)

        gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=queue_path))
        await gateway.open()
        await gateway.close()

        set_aside: list[Path] = sorted(
            path
            for path in tmp_path.glob("channels.db.corrupt-*")
            if not path.name.endswith(("-wal", "-shm", "-journal"))
        )
        assert len(set_aside) == 1
        assert set_aside[0].read_bytes() == damaged_bytes
        verification_repository: ChannelRepository = ChannelRepository(db_path=queue_path)
        await verification_repository.open()
        try:
            assert await verification_repository.user_version() == SCHEMA_VERSION
        finally:
            await verification_repository.close()

    async def test_corrupt_queue_is_still_readable_by_sqlite_after_recovery(
        self, isolated_slo_home: Path
    ) -> None:
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

    async def test_concurrent_openers_recover_corrupt_queue_once(self, tmp_path: Path) -> None:
        """Serialize repository startup so concurrent openers share the fresh queue."""
        queue_path: Path = tmp_path / "channels.db"
        queue_path.write_bytes(_GARBAGE_BYTES)
        gateways: list[ChannelGateway] = [
            ChannelGateway(repository=ChannelRepository(db_path=queue_path)) for _ in range(2)
        ]

        await asyncio.gather(*(gateway.open() for gateway in gateways))
        try:
            schema_versions: list[int] = await asyncio.gather(
                *(gateway.repository.user_version() for gateway in gateways)
            )
            participant_counts: list[int] = await asyncio.gather(
                *(gateway.repository.count_participants() for gateway in gateways)
            )
        finally:
            await asyncio.gather(*(gateway.close() for gateway in gateways))

        set_aside: list[Path] = sorted(
            path
            for path in tmp_path.glob("channels.db.corrupt-*")
            if not path.name.endswith(("-wal", "-shm", "-journal"))
        )
        assert schema_versions == [SCHEMA_VERSION, SCHEMA_VERSION]
        assert participant_counts == [0, 0]
        assert len(set_aside) == 1
        assert set_aside[0].read_bytes() == _GARBAGE_BYTES


class TestLockedQueueIsNotQuarantined:
    """Transient SQLite errors and invalid paths never discard queue data."""

    async def test_open_while_another_connection_holds_the_write_lock_keeps_the_database(
        self, tmp_path: Path
    ) -> None:
        """A lock failure while opening propagates without moving the valid queue aside."""
        queue_path: Path = tmp_path / "channels.db"
        setup_connection: sqlite3.Connection = sqlite3.connect(str(queue_path))
        setup_connection.execute("PRAGMA journal_mode=WAL")
        setup_connection.execute("CREATE TABLE preserved (value TEXT NOT NULL)")
        setup_connection.execute("INSERT INTO preserved(value) VALUES ('still here')")
        setup_connection.commit()
        setup_connection.close()
        original_bytes: bytes = queue_path.read_bytes()
        original_mode: int = queue_path.stat().st_mode & 0o777
        holder: sqlite3.Connection = sqlite3.connect(str(queue_path), isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                await repository.open()
        finally:
            holder.execute("ROLLBACK")
            holder.close()
            await repository.close()

        assert queue_path.read_bytes() == original_bytes
        assert queue_path.stat().st_mode & 0o777 == original_mode
        assert sorted(tmp_path.glob("channels.db.corrupt-*")) == []
        verify_connection: sqlite3.Connection = sqlite3.connect(str(queue_path))
        try:
            preserved_values: list[tuple[str]] = verify_connection.execute(
                "SELECT value FROM preserved"
            ).fetchall()
        finally:
            verify_connection.close()
        assert preserved_values == [("still here",)]

    async def test_symlinked_sidecar_is_not_moved_or_replaced(self, tmp_path: Path) -> None:
        """A symlink in the queue files refuses recovery without touching its target."""
        queue_path: Path = tmp_path / "channels.db"
        queue_path.write_bytes(_GARBAGE_BYTES)
        sidecar_path: Path = tmp_path / "channels.db-wal"
        sidecar_target: Path = tmp_path / "sidecar-target"
        sidecar_target.write_bytes(b"preserve target")
        sidecar_path.symlink_to(sidecar_target)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError, match="not a regular file"):
            await repository.open()
        await repository.close()

        assert queue_path.read_bytes() == _GARBAGE_BYTES
        assert sidecar_path.is_symlink()
        assert sidecar_target.read_bytes() == b"preserve target"
        assert sorted(tmp_path.glob("channels.db.corrupt-*")) == []

    async def test_database_symlink_does_not_modify_its_realpath_target(self, tmp_path: Path) -> None:
        """Opening a symlinked database refuses it without changing its realpath target."""
        queue_path: Path = tmp_path / "database" / "channels.db"
        unrelated_target: Path = tmp_path / "unrelated" / "target.db"
        queue_path.parent.mkdir()
        unrelated_target.parent.mkdir()
        unrelated_target.write_bytes(b"unrelated database target")
        queue_path.symlink_to(unrelated_target)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError):
            await repository.open()
        await repository.close()

        assert queue_path.is_symlink()
        assert queue_path.resolve(strict=True) == unrelated_target.resolve(strict=True)
        assert unrelated_target.read_bytes() == b"unrelated database target"

    async def test_dangling_database_symlink_target_is_not_created(self, tmp_path: Path) -> None:
        """Opening refuses a dangling database symlink without creating its target."""
        queue_path: Path = tmp_path / "database" / "channels.db"
        unrelated_target: Path = tmp_path / "unrelated" / "target.db"
        queue_path.parent.mkdir()
        unrelated_target.parent.mkdir()
        queue_path.symlink_to(unrelated_target)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError):
            await repository.open()
        await repository.close()

        assert queue_path.is_symlink()
        assert queue_path.resolve(strict=False) == unrelated_target.resolve(strict=False)
        assert not unrelated_target.exists()

    async def test_dangling_recovery_lock_symlink_target_is_not_created(self, tmp_path: Path) -> None:
        """Opening refuses a dangling lock symlink without creating its target."""
        queue_path: Path = tmp_path / "database" / "channels.db"
        lock_path: Path = queue_path.with_name(f"{queue_path.name}.recovery.lock")
        unrelated_target: Path = tmp_path / "unrelated" / "target.lock"
        queue_path.parent.mkdir()
        unrelated_target.parent.mkdir()
        lock_path.symlink_to(unrelated_target)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError):
            await repository.open()
        await repository.close()

        assert lock_path.is_symlink()
        assert lock_path.resolve(strict=False) == unrelated_target.resolve(strict=False)
        assert not unrelated_target.exists()
        assert not queue_path.exists()

    async def test_recovery_lock_symlink_does_not_modify_its_realpath_target(self, tmp_path: Path) -> None:
        """Opening refuses a symlinked recovery lock without changing its realpath target."""
        queue_path: Path = tmp_path / "database" / "channels.db"
        lock_path: Path = queue_path.with_name(f"{queue_path.name}.recovery.lock")
        unrelated_target: Path = tmp_path / "unrelated" / "target.lock"
        queue_path.parent.mkdir()
        unrelated_target.parent.mkdir()
        unrelated_target.write_bytes(b"unrelated lock target")
        lock_path.symlink_to(unrelated_target)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError):
            await repository.open()
        await repository.close()

        assert lock_path.is_symlink()
        assert lock_path.resolve(strict=True) == unrelated_target.resolve(strict=True)
        assert unrelated_target.read_bytes() == b"unrelated lock target"
        assert not queue_path.exists()

    async def test_valid_database_migration_error_does_not_quarantine_database(self, tmp_path: Path) -> None:
        """A valid SQLite database with incompatible schema remains in place after migration failure."""
        queue_path: Path = tmp_path / "channels.db"
        setup_connection: sqlite3.Connection = sqlite3.connect(str(queue_path))
        setup_connection.execute("CREATE TABLE channels(id TEXT PRIMARY KEY)")
        setup_connection.commit()
        setup_connection.close()
        os.chmod(path=queue_path, mode=0o640)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(sqlite3.OperationalError, match="already exists"):
            await repository.open()
        await repository.close()

        assert queue_path.is_file()
        assert queue_path.stat().st_mode & 0o777 == 0o640
        assert sorted(tmp_path.glob("channels.db.corrupt-*")) == []
        verify_connection: sqlite3.Connection = sqlite3.connect(str(queue_path))
        try:
            channel_columns: list[tuple[object, ...]] = verify_connection.execute(
                "PRAGMA table_info(channels)"
            ).fetchall()
        finally:
            verify_connection.close()
        assert [column[1] for column in channel_columns] == ["id"]

    async def test_non_database_path_is_not_moved_or_replaced(self, tmp_path: Path) -> None:
        """A directory at the queue path is an operational error, not SQLite corruption."""
        queue_path: Path = tmp_path / "channels.db"
        queue_path.mkdir()
        marker: Path = queue_path / "preserve"
        marker.write_text("keep")
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)

        with pytest.raises(OSError, match="not a regular file"):
            await repository.open()
        await repository.close()

        assert marker.read_text() == "keep"
        assert sorted(tmp_path.glob("channels.db.corrupt-*")) == []

    async def test_recovery_lock_wait_is_bounded_and_keeps_the_event_loop_responsive(
        self, tmp_path: Path
    ) -> None:
        """A held recovery lock times out with OperationalError while async tasks keep running."""
        queue_path: Path = tmp_path / "channels.db"
        lock_path: Path = queue_path.with_name(f"{queue_path.name}.recovery.lock")
        holder_descriptor: int = os.open(path=lock_path, flags=os.O_CREAT | os.O_RDWR, mode=0o600)
        fcntl.flock(holder_descriptor, fcntl.LOCK_EX)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)
        heartbeat_count: int = 0
        heartbeat_stopped: asyncio.Event = asyncio.Event()

        async def record_heartbeats() -> None:
            """Count event-loop turns while the repository worker waits for flock."""
            nonlocal heartbeat_count
            while not heartbeat_stopped.is_set():
                heartbeat_count += 1
                await asyncio.sleep(0.01)

        heartbeat_task: asyncio.Task[None] = asyncio.create_task(record_heartbeats())
        started_at: float = asyncio.get_running_loop().time()
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                async with asyncio.timeout(_RECOVERY_LOCK_TIMEOUT_SECONDS):
                    await repository.open()
        finally:
            heartbeat_stopped.set()
            await heartbeat_task
            fcntl.flock(holder_descriptor, fcntl.LOCK_UN)
            os.close(holder_descriptor)
            await repository.close()

        elapsed_seconds: float = asyncio.get_running_loop().time() - started_at
        assert 4.5 <= elapsed_seconds <= _RECOVERY_LOCK_TIMEOUT_SECONDS
        assert heartbeat_count >= 10
        assert not queue_path.exists()
        assert not [thread for thread in threading.enumerate() if thread.name == "channel-repository_0"]
        await repository.open()
        try:
            assert await repository.user_version() == SCHEMA_VERSION
        finally:
            await repository.close()

    async def test_cancelled_open_joins_worker_and_can_be_retried(self, tmp_path: Path) -> None:
        """Cancellation joins flock acquisition, closes any opened DB and permits a later open."""
        queue_path: Path = tmp_path / "channels.db"
        lock_path: Path = queue_path.with_name(f"{queue_path.name}.recovery.lock")
        holder_descriptor: int = os.open(path=lock_path, flags=os.O_CREAT | os.O_RDWR, mode=0o600)
        fcntl.flock(holder_descriptor, fcntl.LOCK_EX)
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)
        heartbeat_count: int = 0
        heartbeat_stopped: asyncio.Event = asyncio.Event()

        async def record_heartbeats() -> None:
            """Keep the event loop observable while repository opening is cancelled."""
            nonlocal heartbeat_count
            while not heartbeat_stopped.is_set():
                heartbeat_count += 1
                await asyncio.sleep(0.01)

        def release_recovery_lock() -> None:
            """Release the held file descriptor after cancellation has reached cleanup."""
            fcntl.flock(holder_descriptor, fcntl.LOCK_UN)
            os.close(holder_descriptor)

        heartbeat_task: asyncio.Task[None] = asyncio.create_task(record_heartbeats())
        open_task: asyncio.Task[None] = asyncio.create_task(repository.open())
        lock_released: bool = False

        def release_recovery_lock_once() -> None:
            """Release the test-owned flock descriptor once."""
            nonlocal lock_released
            if lock_released:
                return
            release_recovery_lock()
            lock_released = True

        try:
            async with asyncio.timeout(1.0):
                while not any(thread.name == "channel-repository_0" for thread in threading.enumerate()):
                    await asyncio.sleep(0.01)
            open_task.cancel()
            asyncio.get_running_loop().call_later(0.05, release_recovery_lock_once)
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(1.0):
                    await open_task
        finally:
            heartbeat_stopped.set()
            await heartbeat_task
            release_recovery_lock_once()

        assert heartbeat_count >= 5
        assert not [thread for thread in threading.enumerate() if thread.name == "channel-repository_0"]
        open_database_descriptors: list[str] = []
        for descriptor_path in Path("/proc/self/fd").iterdir():
            try:
                if Path(os.readlink(descriptor_path)).resolve() == queue_path.resolve():
                    open_database_descriptors.append(str(descriptor_path))
            except FileNotFoundError:
                continue
        assert open_database_descriptors == []
        await repository.open()
        try:
            assert await repository.user_version() == SCHEMA_VERSION
        finally:
            await repository.close()

    async def test_cancel_during_prune_closes_opened_database_connection(self, tmp_path: Path) -> None:
        """Cancellation after SQLite opens joins prune, closes its connection and allows reopen."""
        queue_path: Path = tmp_path / "channels.db"
        initial_repository: ChannelRepository = ChannelRepository(db_path=queue_path)
        await initial_repository.open()
        await initial_repository.close()
        holder: sqlite3.Connection = sqlite3.connect(str(queue_path), isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        repository: ChannelRepository = ChannelRepository(db_path=queue_path)
        open_task: asyncio.Task[None] = asyncio.create_task(repository.open())
        try:
            async with asyncio.timeout(1.0):
                while not any(thread.name == "channel-repository_0" for thread in threading.enumerate()):
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            open_task.cancel()
            asyncio.get_running_loop().call_later(0.05, holder.execute, "ROLLBACK")
            with pytest.raises(asyncio.CancelledError):
                async with asyncio.timeout(1.0):
                    await open_task
        finally:
            if holder.in_transaction:
                holder.execute("ROLLBACK")
            holder.close()

        assert not [thread for thread in threading.enumerate() if thread.name == "channel-repository_0"]
        open_database_descriptors: list[str] = []
        for descriptor_path in Path("/proc/self/fd").iterdir():
            try:
                if Path(os.readlink(descriptor_path)).resolve() == queue_path.resolve():
                    open_database_descriptors.append(str(descriptor_path))
            except FileNotFoundError:
                continue
        assert open_database_descriptors == []

        await repository.open()
        try:
            assert await repository.user_version() == SCHEMA_VERSION
        finally:
            await repository.close()

    async def test_send_while_another_connection_holds_the_write_lock_fails_and_keeps_the_database(
        self, isolated_slo_home: Path
    ) -> None:
        """The send fails with a lock error, nothing is set aside, and the queue works once the lock clears."""
        channels_dir: Path = isolated_slo_home / "channels"
        gateway: ChannelGateway = ChannelGateway.at_default_path()
        await gateway.open()
        assert gateway.recovery_path is None
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
