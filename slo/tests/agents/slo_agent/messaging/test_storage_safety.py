"""Public storage safety regressions over disposable real SQLite files."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageStoreError,
    MessagingLimitsDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore


def _target() -> MessageAddressDAO:
    """Name one disposable session owner."""
    return MessageAddressDAO(kind="agent_session", session_id=str(uuid4()), generation=str(uuid4()))


def _snapshot(path: Path) -> tuple[bytes, int, int]:
    """Record bytes, mode and inode of a disposable destination."""
    info = path.stat()
    return path.read_bytes(), stat.S_IMODE(info.st_mode), info.st_ino


class TestUnsafeSQLiteDestinations:
    @pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
    @pytest.mark.parametrize("hazard", ["hardlink", "symlink", "public", "foreign", "directory"])
    async def test_open_refuses_unsafe_inode_without_changing_destination(
        self, tmp_path: Path, suffix: str, hazard: str
    ) -> None:
        """Unsafe database and sidecar paths never become writable store resources."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        path.parent.mkdir(mode=0o700)
        destination = tmp_path / "destination"
        destination.write_bytes(b"private sentinel bytes")
        destination.chmod(mode=0o600)
        candidate = Path(str(path) + suffix)
        if hazard == "hardlink":
            os.link(src=destination, dst=candidate)
        elif hazard == "symlink":
            candidate.symlink_to(destination)
        elif hazard == "directory":
            candidate.mkdir(mode=0o700)
        else:
            candidate.write_bytes(b"")
            candidate.chmod(mode=0o644 if hazard == "public" else 0o600)
            if hazard == "foreign":
                os.chown(path=candidate, uid=os.getuid() + 1, gid=-1)
        before = _snapshot(destination)
        candidate_before = candidate.lstat()
        opened: MessageStore | None = None
        try:
            with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                opened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        finally:
            if opened is not None:
                await opened.close()
        assert _snapshot(destination) == before
        after = candidate.lstat()
        assert (after.st_ino, after.st_mode, after.st_uid) == (
            candidate_before.st_ino,
            candidate_before.st_mode,
            candidate_before.st_uid,
        )

    async def test_unsafe_ancestor_does_not_change_target_directory_mode(self, tmp_path: Path) -> None:
        """No chmod follows a linked ancestor into another directory."""
        target = _target()
        destination = tmp_path / "destination"
        destination.mkdir(mode=0o755)
        alias = tmp_path / "alias"
        alias.symlink_to(destination, target_is_directory=True)
        before = destination.stat().st_mode
        with pytest.raises(MessageStoreError):
            await MessageStore.open(
                path=alias / target.session_id / "messaging.v1.sqlite3",
                limits=MessagingLimitsDAO(),
                target=target,
            )
        assert destination.stat().st_mode == before
        assert list(destination.iterdir()) == []

    async def test_open_failure_closes_worker_and_database_descriptor(self, tmp_path: Path) -> None:
        """An invalid real database must not leave its acquisition descriptor behind."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b"not a sqlite database" * 32)
        path.chmod(mode=0o600)
        worker = ThreadPoolExecutor(max_workers=1)
        before = {entry.name for entry in Path("/proc/self/fd").iterdir()}
        try:
            with pytest.raises(MessageStoreError):
                await MessageStore.open(
                    path=path,
                    limits=MessagingLimitsDAO(),
                    target=target,
                    executor_factory=lambda: worker,
                )
            with pytest.raises(RuntimeError):
                worker.submit(lambda: None)
            after = {entry.name for entry in Path("/proc/self/fd").iterdir()}
            assert after == before
        finally:
            worker.shutdown(wait=True)

    async def test_real_wal_database_and_sidecars_are_private_and_reopenable(self, tmp_path: Path) -> None:
        """Actual SQLite bytes, not a durability flag, survive worker close and reopen."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        try:
            for suffix in ("", "-wal", "-shm"):
                info = Path(str(path) + suffix).stat()
                assert stat.S_ISREG(info.st_mode)
                assert stat.S_IMODE(info.st_mode) == 0o600
                assert info.st_uid == os.getuid() and info.st_nlink == 1
            connection = sqlite3.connect(database=path)
            try:
                assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
                assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert connection.execute("PRAGMA user_version").fetchone() == (1,)
            finally:
                connection.close()
        finally:
            await store.close()
        reopened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await reopened.close()


class InspectingSQLiteFactory:
    """Open the real engine; observe worker pragmas or deny one real pragma."""

    def __init__(self, *, deny_pragma: bool = False, replace_parent: bool = False) -> None:
        """Retain only observations and deliberate real-boundary failure controls."""
        self.deny_pragma = deny_pragma
        self.replace_parent = replace_parent
        self.connections: list[sqlite3.Connection] = []
        self.observed: dict[str, object] = {}
        self.worker_thread = 0

    def __call__(self, *, database: str, uri: bool) -> sqlite3.Connection:
        """Return real SQLite and install its documented authorizer/trace hooks."""
        self.worker_thread = get_ident()
        # Test-only cross-thread readback after shutdown distinguishes closed from
        # merely thread-affine; every actual store operation still runs on worker.
        connection = sqlite3.connect(database=database, uri=uri, check_same_thread=False)
        self.connections.append(connection)

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database_name: str | None,
            trigger_name: str | None,
        ) -> int:
            """Cause a real SQLite pragma failure, not fake persistence."""
            if self.deny_pragma and action == sqlite3.SQLITE_PRAGMA and arg1 == "journal_mode":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def trace(statement: str) -> None:
            """Observe connection-local pragmas immediately before schema creation."""
            if statement == "PRAGMA user_version":
                for name in ("busy_timeout", "foreign_keys", "synchronous", "journal_mode"):
                    self.observed[name] = connection.execute(f"PRAGMA {name}").fetchone()[0]
            if self.replace_parent and statement == "PRAGMA synchronous=FULL":
                self.replace_parent = False
                database_path = Path(connection.execute("PRAGMA database_list").fetchone()[2])
                original = database_path.parent
                original.rename(original.with_name(original.name + "-held"))
                original.mkdir(mode=0o700)

        connection.set_authorizer(authorize)
        connection.set_trace_callback(trace)
        return connection


class TestSQLitePartialStartup:
    async def test_real_connection_pragmas_are_verified_on_worker(self, tmp_path: Path) -> None:
        """All connection-local settings are effective on the actual store connection."""
        target = _target()
        factory = InspectingSQLiteFactory()
        store = await MessageStore.open(
            path=tmp_path / target.session_id / "messaging.v1.sqlite3",
            limits=MessagingLimitsDAO(),
            target=target,
            connection_factory=factory,
        )
        try:
            assert factory.worker_thread != get_ident()
            assert factory.observed == {
                "busy_timeout": 1000,
                "foreign_keys": 1,
                "synchronous": 2,
                "journal_mode": "wal",
            }
        finally:
            await store.close()

    @pytest.mark.parametrize("cancelled", [False, True])
    async def test_pragma_failure_closes_real_connection_descriptors_and_worker(
        self, tmp_path: Path, cancelled: bool
    ) -> None:
        """Repeated cancellation cannot abandon a startup ending in real engine failure."""
        target = _target()
        factory = InspectingSQLiteFactory(deny_pragma=True)
        worker = ThreadPoolExecutor(max_workers=1)
        gate = Event()
        blocker = worker.submit(gate.wait, timeout=10)
        before = {entry.name for entry in Path("/proc/self/fd").iterdir()}
        task = asyncio.create_task(
            MessageStore.open(
                path=tmp_path / target.session_id / "messaging.v1.sqlite3",
                limits=MessagingLimitsDAO(),
                target=target,
                connection_factory=factory,
                executor_factory=lambda: worker,
            )
        )
        try:
            for _ in range(10):
                await asyncio.sleep(0)
            if cancelled:
                task.cancel()
                for _ in range(10):
                    await asyncio.sleep(0)
                task.cancel()
                for _ in range(10):
                    await asyncio.sleep(0)
                assert not task.done()
            gate.set()
            expected = asyncio.CancelledError if cancelled else MessageStoreError
            with pytest.raises(expected):
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            assert len(factory.connections) == 1
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                factory.connections[0].execute("SELECT 1")
            with pytest.raises(RuntimeError):
                worker.submit(lambda: None)
            assert {entry.name for entry in Path("/proc/self/fd").iterdir()} == before
        finally:
            gate.set()
            blocker.result(timeout=5)
            await asyncio.gather(task, return_exceptions=True)
            worker.shutdown(wait=True)

    async def test_parent_replacement_cannot_publish_store_or_modify_replacement(
        self, tmp_path: Path
    ) -> None:
        """A real VFS startup callback swaps the parent; publication must fail closed."""
        target = _target()
        factory = InspectingSQLiteFactory(replace_parent=True)
        parent = tmp_path / target.session_id
        opened: MessageStore | None = None
        try:
            with pytest.raises(MessageStoreError):
                opened = await MessageStore.open(
                    path=parent / "messaging.v1.sqlite3",
                    limits=MessagingLimitsDAO(),
                    target=target,
                    connection_factory=factory,
                )
        finally:
            if opened is not None:
                await opened.close()
        assert list(parent.iterdir()) == []
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700


class TestSealedValidatedStartup:
    @pytest.mark.parametrize("new_generation", [False, True])
    async def test_reopen_is_sealed_and_old_input_is_not_executable(
        self, tmp_path: Path, new_generation: bool
    ) -> None:
        """Reopening storage never substitutes for explicit history reconciliation."""
        from src.agents.slo_agent.messaging.dao import (
            BoundaryDAO,
            MessageAdmissionError,
            MessagePrincipalDAO,
            MessageSubmissionDAO,
        )

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="old retained input"
        )
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await first.set_lifecycle(accepting=True)
        original = await first.admit(submission=submission, principal=principal)
        await first.close()
        current = target.model_copy(update={"generation": str(uuid4())}) if new_generation else target
        second = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=current)
        try:
            fresh = MessageSubmissionDAO(
                message_id=str(uuid4()), target=current, kind="agent_input", text="new input"
            )
            with pytest.raises(MessageAdmissionError) as refused:
                await second.admit(submission=fresh, principal=principal)
            assert refused.value.error.code == "completing"
            receipt = await second.get_receipt(message_id=submission.message_id, principal=principal)
            assert receipt is not None and receipt.retained_for_recovery
            assert receipt.target == original.target and receipt.sequence == original.sequence
            assert await second.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)) is None
            await second.set_lifecycle(accepting=True)
            assert await second.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)) is None
            admitted = await second.admit(submission=fresh, principal=principal)
            assert admitted.sequence == 2 and admitted.target == current
            if new_generation:
                with pytest.raises(MessageAdmissionError) as stale:
                    await second.admit(submission=submission, principal=principal)
                assert stale.value.error.code == "stale_generation"
            else:
                assert await second.admit(submission=submission, principal=principal) == receipt
        finally:
            await second.close()
        connection = sqlite3.connect(database=path)
        try:
            assert connection.execute("SELECT value FROM meta WHERE key='generation'").fetchone() == (
                current.generation,
            )
        finally:
            connection.close()

    @pytest.mark.parametrize(
        "change",
        [
            "DROP TABLE applications",
            "DROP INDEX instruction_boundary",
            "UPDATE meta SET value='not-a-uuid' WHERE key='generation'",
            "UPDATE meta SET value='bogus' WHERE key='lifecycle'",
            "UPDATE meta SET value='0' WHERE key='next_sequence'",
            "DELETE FROM meta WHERE key='next_sequence'",
            "ALTER TABLE messages ADD COLUMN surprise TEXT",
            "CREATE TRIGGER surprise AFTER INSERT ON identity BEGIN DELETE FROM messages; END",
        ],
    )
    async def test_schema_one_corruption_refuses_without_partial_meta_publication(
        self, tmp_path: Path, change: str
    ) -> None:
        """Version 1 alone cannot bless incompatible shape, metadata or triggers."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await first.close()
        connection = sqlite3.connect(database=path)
        connection.execute(change)
        connection.commit()
        before = connection.execute("SELECT * FROM meta ORDER BY key").fetchall()
        connection.close()
        before_bytes = path.read_bytes()
        opened: MessageStore | None = None
        try:
            with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                opened = await MessageStore.open(
                    path=path,
                    limits=MessagingLimitsDAO(),
                    target=target.model_copy(update={"generation": str(uuid4())}),
                )
        finally:
            if opened is not None:
                await opened.close()
        assert path.read_bytes() == before_bytes
        connection = sqlite3.connect(database=path)
        try:
            assert connection.execute("SELECT * FROM meta ORDER BY key").fetchall() == before
        finally:
            connection.close()

    @pytest.mark.parametrize("variant", ["wrong_session", "wrong_name", "relative", "channel"])
    async def test_owner_target_and_path_must_be_canonical(self, tmp_path: Path, variant: str) -> None:
        """A store cannot open another session's database or a noncanonical alias."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        if variant == "wrong_session":
            path = tmp_path / str(uuid4()) / path.name
        elif variant == "wrong_name":
            path = path.with_name("alternate.sqlite3")
        elif variant == "relative":
            path = Path("relative") / target.session_id / path.name
        else:
            target = MessageAddressDAO(
                kind="ui_channel",
                session_id=target.session_id,
                generation=target.generation,
                channel_id=str(uuid4()),
            )
        opened: MessageStore | None = None
        try:
            with pytest.raises(MessageStoreError):
                opened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        finally:
            if opened is not None:
                await opened.close()
        assert not path.exists()


class TestStoredRecordTrust:
    @pytest.mark.parametrize("field", ["kind", "session_id", "generation"])
    async def test_full_principal_mismatch_is_unauthorized_for_duplicate_and_receipt(
        self, field: str
    ) -> None:
        """The same principal_id cannot substitute another complete principal."""
        from src.agents.slo_agent.messaging.dao import (
            MessageAdmissionError,
            MessagePrincipalDAO,
            MessageSubmissionDAO,
        )

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        changed = principal.model_copy(update={field: "agent" if field == "kind" else str(uuid4())})
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="secret"
        )
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        try:
            await store.set_lifecycle(accepting=True)
            original = await store.admit(submission=submission, principal=principal)
            for operation in (
                lambda: store.admit(submission=submission, principal=changed),
                lambda: store.get_receipt(message_id=submission.message_id, principal=changed),
            ):
                with pytest.raises(MessageAdmissionError) as refused:
                    await operation()
                assert refused.value.error.code == "unauthorized"
            assert await store.get_receipt(message_id=submission.message_id, principal=principal) == original
        finally:
            await store.close()

    @pytest.mark.parametrize(
        "change",
        [
            "UPDATE messages SET sequence=sequence+5",
            "UPDATE messages SET state='cancelled'",
            "UPDATE messages SET kind='context_note'",
            "UPDATE messages SET priority='urgent'",
            "UPDATE identity SET digest='" + "0" * 64 + "'",
            "UPDATE identity SET principal_id='impostor'",
            "UPDATE identity SET kind='context_note'",
            "UPDATE identity SET durable=0",
            "UPDATE identity SET admitted_at='yesterday'",
            "UPDATE identity SET original_target_json='{}'",
            "UPDATE identity SET execution_generation='invalid'",
            "DELETE FROM messages",
            "UPDATE meta SET value='1' WHERE key='next_sequence'",
        ],
    )
    async def test_corrupt_records_refuse_public_read_admit_and_reopen_without_writes(
        self, tmp_path: Path, change: str
    ) -> None:
        """Individually decodable rows cannot hide identity/body disagreement."""
        from src.agents.slo_agent.messaging.dao import MessagePrincipalDAO, MessageSubmissionDAO

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="unaltered"
        )
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await store.set_lifecycle(accepting=True)
        await store.admit(submission=submission, principal=principal)
        connection = sqlite3.connect(database=path)
        try:
            connection.execute(change)
            connection.commit()
            before = tuple(connection.iterdump())
            for operation in (
                lambda: store.get_receipt(message_id=submission.message_id, principal=principal),
                lambda: store.admit(submission=submission, principal=principal),
            ):
                with pytest.raises(MessageStoreError, match="^storage_unavailable$"):
                    await operation()
                assert tuple(connection.iterdump()) == before
        finally:
            connection.close()
            await store.close()
        opened: MessageStore | None = None
        try:
            with pytest.raises(MessageStoreError):
                opened = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        finally:
            if opened is not None:
                await opened.close()


class TestStartupClaimIsolation:
    @pytest.mark.parametrize("new_generation", [False, True])
    async def test_reopened_unprepared_claim_never_executes_as_live_boundary(
        self, tmp_path: Path, new_generation: bool
    ) -> None:
        """A previously claimed boundary is recovery state, not automatic retry authority."""
        from src.agents.slo_agent.messaging.dao import (
            BoundaryDAO,
            MessagePrincipalDAO,
            MessageSubmissionDAO,
        )

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="claimed before crash"
        )
        boundary = BoundaryDAO(run_id=str(uuid4()), boundary_index=0)
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        await first.set_lifecycle(accepting=True)
        await first.admit(submission=submission, principal=principal)
        assert await first.claim_one(boundary=boundary) is not None
        await first.close()
        current = target.model_copy(update={"generation": str(uuid4())}) if new_generation else target
        second = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=current)
        try:
            assert await second.claim_one(boundary=boundary) is None
            await second.set_lifecycle(accepting=True)
            assert await second.claim_one(boundary=boundary) is None
            assert await second.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)) is None
            receipt = await second.get_receipt(message_id=submission.message_id, principal=principal)
            assert receipt is not None and receipt.state == "applying" and receipt.retained_for_recovery
        finally:
            await second.close()

    async def test_sealed_fresh_store_cannot_claim_newly_accepted_input(self) -> None:
        """Sealing stops selection as well as admission; no application may start."""
        from src.agents.slo_agent.messaging.dao import (
            BoundaryDAO,
            MessagePrincipalDAO,
            MessageSubmissionDAO,
        )

        target = _target()
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()), target=target, kind="agent_input", text="pending"
                ),
                principal=MessagePrincipalDAO(principal_id="owner", kind="human"),
            )
            await store.set_lifecycle(accepting=False)
            assert await store.claim_one(boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0)) is None
        finally:
            await store.close()


class TestLiveReadTrust:
    async def test_summary_does_not_disclose_text_to_same_id_different_principal(self) -> None:
        """Summary projection uses the same full-principal trust as receipt lookup."""
        from src.agents.slo_agent.messaging.dao import MessagePrincipalDAO, MessageSubmissionDAO

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        store = await MessageStore.open(path=None, limits=MessagingLimitsDAO(), target=target)
        try:
            await store.set_lifecycle(accepting=True)
            await store.admit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()), target=target, kind="agent_input", text="private draft"
                ),
                principal=principal,
            )
            for field, value in (
                ("kind", "agent"),
                ("session_id", str(uuid4())),
                ("generation", str(uuid4())),
            ):
                summary = await store.read_summary(principal=principal.model_copy(update={field: value}))
                assert summary.next_local_text is None and summary.next_local_message_id is None
            assert (await store.read_summary(principal=principal)).next_local_text == "private draft"
        finally:
            await store.close()

    @pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
    async def test_live_inode_substitution_refuses_before_touching_destination(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """A store may not keep publishing valid-looking reads after a pathname swap."""
        target = _target()
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        store = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        destination = tmp_path / "destination"
        destination.write_bytes(b"untouched destination")
        destination.chmod(mode=0o600)
        candidate = Path(str(path) + suffix)
        held = candidate.with_name(candidate.name + ".held")
        candidate.rename(held)
        candidate.symlink_to(destination)
        before = _snapshot(destination)
        try:
            with pytest.raises(MessageStoreError):
                await store.read_queue_state()
            assert _snapshot(destination) == before
        finally:
            # Restore the original namespace before SQLite's native close cleanup.
            candidate.unlink()
            held.rename(candidate)
            await store.close()


class TestStableTerminalReopen:
    async def test_cancelled_tombstone_duplicate_survives_prune_and_sealed_reopen(
        self, tmp_path: Path
    ) -> None:
        """Terminal identity and sequence remain stable without a retained body."""
        from datetime import timedelta
        from src.agents.slo_agent.messaging.dao import MessagePrincipalDAO, MessageSubmissionDAO, utcnow

        target = _target()
        principal = MessagePrincipalDAO(principal_id="owner", kind="human")
        submission = MessageSubmissionDAO(
            message_id=str(uuid4()), target=target, kind="agent_input", text="cancel explicitly"
        )
        path = tmp_path / target.session_id / "messaging.v1.sqlite3"
        first = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        try:
            await first.set_lifecycle(accepting=True)
            await first.admit(submission=submission, principal=principal)
            await first.retain_pending()
            await first.cancel_retained(message_ids=(submission.message_id,))
            terminal = await first.get_receipt(message_id=submission.message_id, principal=principal)
            assert terminal is not None and terminal.state == "cancelled"
            await first.maintain(now=utcnow() + timedelta(days=8))
        finally:
            await first.close()
        second = await MessageStore.open(path=path, limits=MessagingLimitsDAO(), target=target)
        try:
            assert await second.get_receipt(message_id=submission.message_id, principal=principal) == terminal
            assert await second.admit(submission=submission, principal=principal) == terminal
        finally:
            await second.close()
