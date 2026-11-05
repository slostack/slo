"""Durable session messaging storage (feature 96, sub-spec A.1).

``MessageStore`` is the only SQLite owner for session messaging state:
messages, identities, receipts, application evidence and recovery
records. It is not a broker and not a history replacement.

Storage rules from the A.1 contract:

- Database path: ``<resolved_history_root>/<session_id>/messaging.v1.sqlite3``;
  WAL/SHM siblings stay private.
- No-follow ancestry and regular-file ownership validated before opening;
  directory 0700, files 0600, no network filesystem support.
- ``journal_mode=WAL``, ``synchronous=FULL``, ``foreign_keys=ON``,
  ``busy_timeout=1000``.
- Startup creates the schema when ``PRAGMA user_version=0`` then sets 1;
  any other non-1 value fails closed without migration. Later slices
  upgrade this released schema explicitly.
- One dedicated single-worker executor per store owns connection
  create/use/close, keeping blocking database work off the UI loop. That
  worker is not the session scheduler.
- No Alembic/SQLAlchemy dependency; Python sqlite3 only.
- All timestamps are canonical UTC ISO8601; JSON columns contain
  validated canonical DAO JSON.
- Admission refuses ``storage_unavailable`` at a 256 MiB messaging
  database budget (including WAL); identity tombstones are never deleted
  to reclaim capacity.

Public store operations are internal queue collaborators; no UI or
client code calls them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Protocol, TypeVar
from uuid import UUID, uuid5

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessageDeliveryDAO,
    MessageEnvelopeDAO,
    MessageIdentityDAO,
    MessageApplicationMetadataDAO,
    canonical_submission_bytes,
    CompactionLedgerDAO,
    InternalObservationDAO,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageStoreError,
    MessageSubmissionDAO,
    MessagingLimitsDAO,
    QueueStateDAO,
    QueueSummaryDAO,
    RecoveryOutcomeDAO,
    RecoveryTransferDAO,
    utcnow,
)

__all__ = ["MessageStore"]

_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 1000
_STORAGE_BUDGET_BYTES = 256 * 1024 * 1024
_SEQUENCE_MAX = 2**63 - 1
_UNSETTLED_APPLICATION_LIMIT = 512
_LIFECYCLE_KEY = "lifecycle"
_NEXT_SEQUENCE_KEY = "next_sequence"
_GENERATION_KEY = "generation"
_LIFECYCLE_ACCEPTING = "accepting"
_LIFECYCLE_SEALED = "sealed"
_T = TypeVar("_T")

_SCHEMA_DDL = """
CREATE TABLE meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE identity(
    message_id TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_json TEXT NOT NULL,
    original_target_json TEXT NOT NULL,
    sequence INTEGER NOT NULL UNIQUE CHECK(sequence > 0),
    admitted_at TEXT NOT NULL,
    applied_at TEXT,
    run_id TEXT,
    durable INTEGER NOT NULL CHECK(durable IN (0,1)),
    state TEXT NOT NULL CHECK(state IN ('accepted','applying','applied','cancelled')),
    terminal_at TEXT,
    source_event_id TEXT,
    kind TEXT NOT NULL,
    history_event_id TEXT,
    event_sha256 TEXT,
    execution_generation TEXT NOT NULL
);

CREATE UNIQUE INDEX source_identity
    ON identity(source_event_id) WHERE source_event_id IS NOT NULL;

CREATE TABLE messages(
    message_id TEXT PRIMARY KEY REFERENCES identity(message_id),
    submission_json TEXT NOT NULL,
    sequence INTEGER NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('agent_input','context_note','ui_notice','transcript_note')),
    priority TEXT NOT NULL CHECK(priority IN ('normal','urgent')),
    state TEXT NOT NULL CHECK(state IN ('accepted','applying','applied','cancelled')),
    execution_generation TEXT NOT NULL,
    retained INTEGER NOT NULL DEFAULT 0 CHECK(retained IN (0,1)),
    run_id TEXT,
    boundary_index INTEGER CHECK(boundary_index >= 0),
    history_event_id TEXT,
    CHECK(priority='normal' OR kind='agent_input')
);

CREATE INDEX pending_selection
    ON messages(retained, state, kind, priority, sequence);

CREATE UNIQUE INDEX instruction_boundary
    ON messages(run_id, boundary_index)
    WHERE kind='agent_input' AND run_id IS NOT NULL;

CREATE UNIQUE INDEX note_boundary
    ON messages(run_id, boundary_index)
    WHERE kind IN ('context_note','transcript_note') AND run_id IS NOT NULL;

CREATE TABLE applications(
    message_id TEXT PRIMARY KEY REFERENCES identity(message_id),
    event_json TEXT NOT NULL,
    history_committed INTEGER NOT NULL DEFAULT 0 CHECK(history_committed IN (0,1)),
    context_committed INTEGER NOT NULL DEFAULT 0 CHECK(context_committed IN (0,1)),
    workflow_effect_json TEXT,
    workflow_effect_committed INTEGER NOT NULL DEFAULT 0 CHECK(workflow_effect_committed IN (0,1))
);

CREATE TABLE recovery_transfers(
    transfer_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES identity(message_id),
    original_digest TEXT NOT NULL,
    from_generation TEXT NOT NULL,
    to_generation TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    transfer_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    UNIQUE(message_id, to_generation)
);

CREATE TABLE compactions(
    compaction_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('prepared','committed','rolled_back')),
    summary_event_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE compacted_applications(
    compaction_id TEXT NOT NULL REFERENCES compactions(compaction_id),
    message_id TEXT NOT NULL REFERENCES identity(message_id),
    PRIMARY KEY(compaction_id, message_id)
);

CREATE TABLE internal_observations(
    observation_id TEXT PRIMARY KEY,
    history_event_id TEXT NOT NULL UNIQUE,
    event_sha256 TEXT NOT NULL,
    event_json TEXT,
    state TEXT NOT NULL CHECK(state IN ('prepared','applied'))
);

CREATE TABLE compacted_observations(
    compaction_id TEXT NOT NULL REFERENCES compactions(compaction_id),
    observation_id TEXT NOT NULL REFERENCES internal_observations(observation_id),
    PRIMARY KEY(compaction_id, observation_id)
);

CREATE TABLE migration_items(
    source_path TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    legacy_id TEXT NOT NULL,
    transfer_id TEXT UNIQUE,
    message_id TEXT,
    disposition TEXT NOT NULL CHECK(disposition IN ('retained','applied','done','ambiguous','invalid'))
);
"""


class SQLiteConnectionFactory(Protocol):
    """Construct a real SQLite connection on its store-owned worker."""

    def __call__(self, *, database: str, uri: bool) -> sqlite3.Connection:
        """Transfer connection lifetime to MessageStore, including failed startup."""
        ...


class _SQLiteFiles:
    """Hold no-follow private SQLite inodes and their complete directory lineage.

    This Linux-only stdlib VFS boundary deliberately has no pathname fallback.
    The session ownership lease remains a caller precondition. Held descriptors
    and identity checks detect namespace replacement; they are not a sandbox
    against another process with the same UID actively racing SQLite's VFS.
    """

    def __init__(self, *, path: Path) -> None:
        """Acquire nothing until the worker calls acquire()."""
        self.path = path
        self._resources = ExitStack()
        self._directories: list[tuple[int, str, int]] = []
        self._files: dict[str, int] = {}
        self._parent = -1

    def acquire(self) -> None:
        """Acquire a no-follow lineage and private single-link files on the worker.

        Raises:
            MessageStoreError: The platform or any existing inode is unsafe.
        """
        if not hasattr(os, "O_NOFOLLOW") or not Path("/proc/self/fd").is_dir():
            raise MessageStoreError()
        if not self.path.is_absolute() or ".." in self.path.parts:
            raise MessageStoreError()
        try:
            self._acquire_directories()
            for suffix in ("", "-wal", "-shm"):
                self._acquire_file(name=self.path.name + suffix)
            self.validate()
        except BaseException:
            self.close()
            raise

    def _hold(self, descriptor: int) -> int:
        """Retain one descriptor until connection shutdown or acquisition rollback."""
        self._resources.callback(os.close, descriptor)
        return descriptor

    def _acquire_directories(self) -> None:
        """Walk from root with directory-relative no-follow opens, never chmod paths."""
        parent = self._hold(os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for name in self.path.parent.parts[1:]:
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                os.mkdir(name, mode=0o700, dir_fd=parent)
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            child = self._hold(child)
            self._directories.append((parent, name, child))
            parent = child
        self._parent = parent
        info = os.fstat(parent)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise MessageStoreError()

    def _acquire_file(self, *, name: str) -> None:
        """Refuse linked, non-private or foreign SQLite files before VFS access."""
        descriptor = self._hold(
            os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                mode=0o600,
                dir_fd=self._parent,
            )
        )
        self._require_private_file(descriptor=descriptor)
        self._files[name] = descriptor

    @staticmethod
    def _require_private_file(*, descriptor: int) -> None:
        """Require a current-owner private regular inode with exactly one link."""
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise MessageStoreError()

    @staticmethod
    def _require_identity(*, parent: int, name: str, descriptor: int) -> None:
        """Refuse a renamed/unlinked or substituted inode without following links."""
        actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
        held = os.fstat(descriptor)
        if (actual.st_dev, actual.st_ino) != (held.st_dev, held.st_ino):
            raise MessageStoreError()

    def validate(self) -> None:
        """Recheck containment and inode identity before publishing or using storage."""
        for parent, name, descriptor in self._directories:
            self._require_identity(parent=parent, name=name, descriptor=descriptor)
        parent_info = os.fstat(self._parent)
        if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) != 0o700:
            raise MessageStoreError()
        for name, descriptor in self._files.items():
            self._require_private_file(descriptor=descriptor)
            self._require_identity(parent=self._parent, name=name, descriptor=descriptor)

    def connect_path(self) -> str:
        """Return the pinned database inode path; SQLite still owns its native VFS."""
        return f"file:/proc/self/fd/{self._files[self.path.name]}?mode=rw"

    def close(self) -> None:
        """Release held inodes only after the worker has closed its connection."""
        self._resources.close()


def _submission_digest(*, submission: MessageSubmissionDAO, principal: MessagePrincipalDAO) -> str:
    """Bind the canonical submission bytes to the complete verified principal.

    The digest covers the original sender identity plus the canonical
    submission, so a retry carrying the same bytes under another principal
    is ``unauthorized`` rather than an existence oracle.

    Args:
        submission (MessageSubmissionDAO): The immutable sender intent.
        principal (MessagePrincipalDAO): The recipient-authenticated sender.

    Returns:
        str: 64-character lowercase hex SHA-256 digest.
    """
    canonical = json.dumps(
        {
            "principal": json.loads(principal.model_dump_json()),
            "submission": json.loads(submission.model_dump_json()),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MessageStore:
    """Serialize queue transactions on a session-owned worker, never the UI loop.

    Own session messaging transactions without owning agent execution.
    All connection create/use/close happens on this store's single-worker
    executor; every public coroutine shields and joins its worker future
    so cancellation of a waiter never abandons an in-progress transaction.
    """

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        executor: ThreadPoolExecutor,
        path: Optional[Path],
        durable: bool,
        limits: MessagingLimitsDAO,
        target: MessageAddressDAO,
        files: Optional[_SQLiteFiles] = None,
    ) -> None:
        """Bind one validated connection/worker pair; construction starts no tasks.

        Args:
            connection (sqlite3.Connection): Worker-owned open connection.
            executor (ThreadPoolExecutor): Single-worker executor owning the connection.
            path (Optional[Path]): Database path, or None for explicit ephemeral mode.
            durable (bool): Whether receipts of this store report durability.
            limits (MessagingLimitsDAO): Construction-time capacity and size bounds.
            target (MessageAddressDAO): Exact session incarnation owning this store.
        """
        self._files = files
        self._connection = connection
        self._executor = executor
        self._path = path
        self._durable = durable
        self._limits = limits
        self._target = target
        self._closed = False
        self._close_task: Optional[asyncio.Task[None]] = None

    @classmethod
    async def open(
        cls,
        *,
        path: Optional[Path],
        limits: MessagingLimitsDAO,
        target: MessageAddressDAO,
        executor_factory: Optional[Callable[[], ThreadPoolExecutor]] = None,
        connection_factory: Optional[SQLiteConnectionFactory] = None,
    ) -> "MessageStore":
        """Acquire one worker/connection while startup is sealed.

        WHAT: Return a validated schema-1 store, or fail without partial
            ownership.
        WHO: ``SloAgentSession.start_messaging`` calls this after acquiring
            execution ownership.
        WHEN: Once at startup, while admission is sealed.
        DATA FLOW: Admitted records persist in this session's SQLite
            database; ``path=None`` is permitted only for explicitly
            ephemeral local sessions (``:memory:``, receipts durable=False).
        LIFETIME: The session owns the worker/connection and joins it
            during close.

        Args:
            path (Optional[Path]): Database path; None requires explicit
                ephemeral mode. Persistent failure never silently falls
                back to memory.
            limits (MessagingLimitsDAO): Construction-time capacity and
                size bounds.
            target (MessageAddressDAO): Exact session incarnation owning
                this store.
            executor_factory: Optional single-worker factory; store owns shutdown.
            connection_factory: Optional real SQLite construction seam, called only
                on that worker; store owns returned connection cleanup.

        Returns:
            MessageStore: Ready storage; no scheduler or endpoint started.

        Raises:
            MessageStoreError: Storage cannot open or validate; partial
                resources are released.
        """
        operation = asyncio.create_task(
            cls._open_owned(
                path=path,
                limits=limits,
                target=target,
                executor_factory=executor_factory,
                connection_factory=connection_factory,
            )
        )
        store, cancelled = await cls._settle(future=operation)
        if cancelled:
            await store.close()
            raise asyncio.CancelledError()
        return store

    @classmethod
    async def _open_owned(
        cls,
        *,
        path: Optional[Path],
        limits: MessagingLimitsDAO,
        target: MessageAddressDAO,
        executor_factory: Optional[Callable[[], ThreadPoolExecutor]],
        connection_factory: Optional[SQLiteConnectionFactory],
    ) -> "MessageStore":
        """Keep startup alive until every created connection is adopted or closed."""
        executor = (
            executor_factory()
            if executor_factory is not None
            else ThreadPoolExecutor(max_workers=1, thread_name_prefix="slo-msg-store")
        )
        files = _SQLiteFiles(path=path) if path is not None else None
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = await cls._run_on(
                executor=executor,
                operation=lambda: cls._connect(
                    path=path, files=files, connection_factory=connection_factory, target=target
                ),
            )
            await cls._run_on(
                executor=executor,
                operation=lambda: cls._initialize(
                    connection=connection, durable=path is not None, target=target
                ),
            )
            if files is not None:
                await cls._run_on(executor=executor, operation=files.validate)
        except BaseException:
            try:
                if connection is not None:
                    await cls._run_on(executor=executor, operation=connection.close)
            finally:
                if files is not None:
                    await cls._run_on(executor=executor, operation=files.close)
                executor.shutdown(wait=True)
            raise
        return cls(
            connection=connection,
            executor=executor,
            path=path,
            durable=path is not None,
            limits=limits,
            target=target,
            files=files,
        )

    @classmethod
    def _connect(
        cls,
        *,
        path: Optional[Path],
        files: Optional[_SQLiteFiles],
        connection_factory: Optional[SQLiteConnectionFactory],
        target: MessageAddressDAO,
    ) -> sqlite3.Connection:
        """Open and configure SQLite on its worker, unwinding every partial resource.

        Args:
            path (Optional[Path]): Exact durable path, or explicit in-memory mode.
            files (Optional[_SQLiteFiles]): Worker-owned durable inode lifetime.
            connection_factory: Optional real-engine factory for explicit composition.
            target: Exact owning session address, validated before filesystem access.

        Returns:
            sqlite3.Connection: Configured connection with verified pragmas.

        Raises:
            MessageStoreError: Filesystem, SQLite or pragma validation failure.
        """
        connection: Optional[sqlite3.Connection] = None
        try:
            cls._require_owner_path(path=path, target=target)
            if files is not None:
                files.acquire()
            database = files.connect_path() if files is not None else ":memory:"
            factory = connection_factory if connection_factory is not None else sqlite3.connect
            connection = factory(database=database, uri=True)
            cls._configure_connection(connection=connection, durable=path is not None)
            if files is not None:
                files.validate()
            return connection
        except BaseException as error:
            try:
                if connection is not None:
                    connection.close()
            finally:
                if files is not None:
                    files.close()
            if isinstance(error, (OSError, sqlite3.Error, ValueError)):
                raise MessageStoreError() from None
            raise

    @staticmethod
    def _require_owner_path(*, path: Optional[Path], target: MessageAddressDAO) -> None:
        """Refuse noncanonical owner/path combinations before any filesystem effect."""
        target = MessageAddressDAO.model_validate_json(target.model_dump_json())
        if target.kind != "agent_session":
            raise MessageStoreError()
        if path is None:
            return
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.name != "messaging.v1.sqlite3"
            or path.parent.name != target.session_id
        ):
            raise MessageStoreError()

    @staticmethod
    def _configure_connection(*, connection: sqlite3.Connection, durable: bool) -> None:
        """Set and read back the actual connection-local durability contract."""
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys=ON")
        if durable:
            if connection.execute("PRAGMA journal_mode=WAL").fetchone() != ("wal",):
                raise MessageStoreError()
            connection.execute("PRAGMA synchronous=FULL")
        expected = {"busy_timeout": _BUSY_TIMEOUT_MS, "foreign_keys": 1}
        if durable:
            expected["synchronous"] = 2
        for pragma, value in expected.items():
            if connection.execute(f"PRAGMA {pragma}").fetchone() != (value,):
                raise MessageStoreError()

    @classmethod
    def _initialize(
        cls,
        *,
        connection: sqlite3.Connection,
        durable: bool,
        target: MessageAddressDAO,
    ) -> None:
        """Validate or create schema version 1 and seed sealed meta rows.

        Args:
            connection (sqlite3.Connection): Worker-owned open connection.
            durable (bool): Whether this store persists across restarts.
            target (MessageAddressDAO): Owning session incarnation; its
                generation seeds a fresh database.

        Raises:
            MessageStoreError: Any non-1 user_version or schema failure;
                the store fails closed without migration.
        """
        try:
            row = connection.execute("PRAGMA user_version").fetchone()
            version = int(row[0])
            if version == _SCHEMA_VERSION:
                connection.execute("BEGIN IMMEDIATE")
                cls._validate_schema(connection=connection)
                cls._validate_meta(connection=connection)
                cls._validate_records(connection=connection, durable=durable, target=target)
                cls._reseal(connection=connection, target=target)
                return
            if version != 0:
                raise MessageStoreError()
            # executescript commits a preceding transaction implicitly. Start the
            # transaction inside its script so DDL, version and meta share rollback.
            connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA_DDL)
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
            connection.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?), (?, ?), (?, ?)",
                (
                    _NEXT_SEQUENCE_KEY,
                    "1",
                    _LIFECYCLE_KEY,
                    _LIFECYCLE_SEALED,
                    _GENERATION_KEY,
                    target.generation,
                ),
            )
            connection.commit()
        except MessageStoreError:
            connection.rollback()
            raise
        except (sqlite3.Error, ValueError):
            connection.rollback()
            raise MessageStoreError() from None

    @staticmethod
    def _schema_shape(*, connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
        """Read normalized schema definitions including constraints and index predicates."""
        rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        ).fetchall()
        return [(kind, name, table, " ".join(sql.split()).lower()) for kind, name, table, sql in rows]

    @classmethod
    def _validate_schema(cls, *, connection: sqlite3.Connection) -> None:
        """Validate the complete compatible core schema against its single DDL owner."""
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(_SCHEMA_DDL)
            if cls._schema_shape(connection=connection) != cls._schema_shape(connection=reference):
                raise MessageStoreError()
        finally:
            reference.close()
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise MessageStoreError()
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MessageStoreError()

    @staticmethod
    def _validate_meta(*, connection: sqlite3.Connection) -> None:
        """Refuse missing, noncanonical or regressed metadata before any startup write."""
        meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
        if set(meta) != {_NEXT_SEQUENCE_KEY, _LIFECYCLE_KEY, _GENERATION_KEY}:
            raise MessageStoreError()
        if meta[_LIFECYCLE_KEY] not in {_LIFECYCLE_ACCEPTING, _LIFECYCLE_SEALED}:
            raise MessageStoreError()
        generation = meta[_GENERATION_KEY]
        if str(UUID(generation)) != generation:
            raise MessageStoreError()
        sequence = meta[_NEXT_SEQUENCE_KEY]
        if not sequence.isascii() or not sequence.isdecimal() or str(int(sequence)) != sequence:
            raise MessageStoreError()
        maximum = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM identity").fetchone()[0]
        if not maximum < int(sequence) <= _SEQUENCE_MAX:
            raise MessageStoreError()

    @classmethod
    def _validate_records(
        cls,
        *,
        connection: sqlite3.Connection,
        durable: bool,
        target: MessageAddressDAO,
    ) -> None:
        """Validate authoritative identities and their remaining immutable bodies."""
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row
        for identity in cursor.execute("SELECT * FROM identity"):
            cls._validate_identity(connection=connection, identity=identity, durable=durable, target=target)
        for transfer in cursor.execute("SELECT * FROM recovery_transfers"):
            cls._validate_transfer(connection=connection, row=transfer, target=target)
        for observation in cursor.execute("SELECT * FROM internal_observations"):
            cls._observation_record(row=observation)
        prepared = 0
        for row in cursor.execute("SELECT * FROM compactions"):
            CompactionLedgerDAO(
                compaction_id=row["compaction_id"],
                state=row["state"],
                summary_event_id=row["summary_event_id"],
                message_ids=(),
                observation_ids=(),
            )
            timestamp = datetime.fromisoformat(row["created_at"])
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise MessageStoreError()
            prepared += row["state"] == "prepared"
        if prepared > 1 or connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MessageStoreError()
        if (
            connection.execute(
                "SELECT 1 FROM compacted_applications ca JOIN identity i USING(message_id) WHERE i.state!='applied' LIMIT 1"
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM compacted_observations co JOIN internal_observations o USING(observation_id) WHERE o.state!='applied' LIMIT 1"
            ).fetchone()
        ):
            raise MessageStoreError()

    @classmethod
    def _validate_transfer(
        cls, *, connection: sqlite3.Connection, row: sqlite3.Row, target: MessageAddressDAO
    ) -> None:
        """Verify persisted transfer and original outcome against lifetime recipient proof."""
        transfer = RecoveryTransferDAO.model_validate_json(row["transfer_json"])
        outcome = RecoveryOutcomeDAO.model_validate_json(row["outcome_json"])
        confirmer = MessagePrincipalDAO.model_validate_json(row["confirmed_by"])
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row
        identity = cursor.execute(
            "SELECT * FROM identity WHERE message_id=?", (row["message_id"],)
        ).fetchone()
        if identity is None or confirmer.kind != "human":
            raise MessageStoreError()
        if str(UUID(row["from_generation"])) != row["from_generation"]:
            raise MessageStoreError()
        timestamp = datetime.fromisoformat(row["confirmed_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise MessageStoreError()
        if (
            transfer.transfer_id != row["transfer_id"]
            or transfer.original.message_id != row["message_id"]
            or transfer.original_digest != row["original_digest"]
            or transfer.original_digest != identity["digest"]
            or _submission_digest(submission=transfer.original, principal=transfer.original_sender)
            != identity["digest"]
            or transfer.original_sender != MessagePrincipalDAO.model_validate_json(identity["principal_json"])
            or transfer.original.target
            != MessageAddressDAO.model_validate_json(identity["original_target_json"])
            or transfer.destination.generation != row["to_generation"]
            or transfer.destination.session_id != target.session_id
            or outcome.transfer_id != transfer.transfer_id
            or outcome.execution_generation != row["to_generation"]
            or outcome.receipt.message_id != row["message_id"]
            or outcome.receipt.sequence != identity["sequence"]
            or outcome.receipt.target != transfer.original.target
            or outcome.receipt.admitted_at != datetime.fromisoformat(identity["admitted_at"])
            or outcome.receipt.durable != bool(identity["durable"])
        ):
            raise MessageStoreError()

    @classmethod
    def _observation_record(cls, *, row: sqlite3.Row) -> InternalObservationDAO:
        """Decode one observation and verify body hash when its body remains."""
        record = InternalObservationDAO(
            observation_id=row["observation_id"],
            history_event_id=row["history_event_id"],
            event_sha256=row["event_sha256"],
            state=row["state"],
            event=(
                SessionHistoryEventDAO.model_validate_json(row["event_json"])
                if row["event_json"] is not None
                else None
            ),
        )
        if record.event is not None and (
            record.event.event_id != record.history_event_id
            or cls._event_digest(event=record.event) != record.event_sha256
        ):
            raise MessageStoreError()
        return record

    @classmethod
    def _validate_identity(
        cls,
        *,
        connection: sqlite3.Connection,
        identity: sqlite3.Row,
        durable: bool,
        target: MessageAddressDAO,
    ) -> None:
        """Validate one receipt/principal/evidence tombstone before trusting its body."""
        original_target = MessageAddressDAO.model_validate_json(identity["original_target_json"])
        principal = MessagePrincipalDAO.model_validate_json(identity["principal_json"])
        receipt = MessageReceiptDAO(
            message_id=identity["message_id"],
            target=original_target,
            state=identity["state"],
            sequence=identity["sequence"],
            durable=bool(identity["durable"]),
            admitted_at=datetime.fromisoformat(identity["admitted_at"]),
            applied_at=datetime.fromisoformat(identity["applied_at"]) if identity["applied_at"] else None,
            run_id=identity["run_id"],
        )
        MessageIdentityDAO(
            receipt=receipt,
            sender=principal,
            digest=identity["digest"],
            kind=identity["kind"],
            history_event_id=identity["history_event_id"],
            event_sha256=identity["event_sha256"],
            execution_generation=identity["execution_generation"],
        )
        if (
            principal.principal_id != identity["principal_id"]
            or receipt.durable != durable
            or original_target.kind != "agent_session"
            or original_target.session_id != target.session_id
        ):
            raise MessageStoreError()
        cls._validate_identity_state(identity=identity)
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row
        body = cursor.execute(
            "SELECT * FROM messages WHERE message_id=?", (identity["message_id"],)
        ).fetchone()
        if body is None:
            if (
                receipt.state not in {"applied", "cancelled"}
                or connection.execute(
                    "SELECT 1 FROM applications WHERE message_id=?", (identity["message_id"],)
                ).fetchone()
            ):
                raise MessageStoreError()
            return
        cls._validate_body(identity=identity, body=body, principal=principal, original_target=original_target)
        cls._validate_application(connection=connection, identity=identity, body=body, principal=principal)

    @classmethod
    def _validate_application(
        cls,
        *,
        connection: sqlite3.Connection,
        identity: sqlite3.Row,
        body: sqlite3.Row,
        principal: MessagePrincipalDAO,
    ) -> None:
        """Check journal, claim and lifetime evidence together before trusting acknowledgement."""
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row
        journal = cursor.execute(
            "SELECT * FROM applications WHERE message_id=?", (identity["message_id"],)
        ).fetchone()
        if journal is None:
            if identity["history_event_id"] is not None:
                raise MessageStoreError()
            return
        if body["state"] not in {"applying", "applied"}:
            raise MessageStoreError()
        event = SessionHistoryEventDAO.model_validate_json(journal["event_json"])
        delivery = MessageDeliveryDAO(
            envelope=MessageEnvelopeDAO(
                submission=MessageSubmissionDAO.model_validate_json(body["submission_json"]),
                sender=principal,
                sequence=identity["sequence"],
                admitted_at=datetime.fromisoformat(identity["admitted_at"]),
            ),
            boundary=BoundaryDAO(run_id=body["run_id"], boundary_index=body["boundary_index"]),
            history_event_id=body["history_event_id"],
        )
        cls._require_application_event(
            delivery=delivery, event=event, generation=identity["execution_generation"]
        )
        if (identity["history_event_id"], identity["event_sha256"]) != (
            event.event_id,
            cls._event_digest(event=event),
        ):
            raise MessageStoreError()
        if journal["context_committed"] != (body["state"] == "applied"):
            raise MessageStoreError()
        if journal["context_committed"] and not journal["history_committed"]:
            raise MessageStoreError()

    @staticmethod
    def _validate_identity_state(*, identity: sqlite3.Row) -> None:
        """Refuse impossible state/timestamp/run combinations, including tombstones."""
        state = identity["state"]
        if (state in {"applied", "cancelled"}) != (identity["terminal_at"] is not None):
            raise MessageStoreError()
        if (state == "applied") != (identity["applied_at"] is not None):
            raise MessageStoreError()
        if state in {"applying", "applied"} and identity["run_id"] is None:
            raise MessageStoreError()
        if state == "accepted" and identity["run_id"] is not None:
            raise MessageStoreError()
        for field in ("admitted_at", "applied_at", "terminal_at"):
            if identity[field] is None:
                continue
            timestamp = datetime.fromisoformat(identity[field])
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise MessageStoreError()

    @staticmethod
    def _validate_body(
        *,
        identity: sqlite3.Row,
        body: sqlite3.Row,
        principal: MessagePrincipalDAO,
        original_target: MessageAddressDAO,
    ) -> None:
        """Compare decoded intent and every mirrored identity/claim column exactly."""
        submission = MessageSubmissionDAO.model_validate_json(body["submission_json"])
        try:
            MessageStore._require_source_author(submission=submission, principal=principal)
        except MessageAdmissionError:
            raise MessageStoreError() from None
        mirrored = ("message_id", "sequence", "state", "kind", "execution_generation", "run_id")
        if any(identity[name] != body[name] for name in mirrored):
            raise MessageStoreError()
        if (
            submission.message_id != identity["message_id"]
            or submission.target != original_target
            or submission.kind != body["kind"]
            or submission.priority != body["priority"]
            or submission.source_event_id != identity["source_event_id"]
            or _submission_digest(submission=submission, principal=principal) != identity["digest"]
        ):
            raise MessageStoreError()
        claimed = body["state"] in {"applying", "applied"}
        if claimed != (body["boundary_index"] is not None and body["history_event_id"] is not None):
            raise MessageStoreError()
        if (
            identity["history_event_id"] is not None
            and identity["history_event_id"] != body["history_event_id"]
        ):
            raise MessageStoreError()
        if claimed:
            BoundaryDAO(run_id=body["run_id"], boundary_index=body["boundary_index"])
            canonical_id = str(
                uuid5(namespace=UUID(original_target.session_id), name="message:" + submission.message_id)
            )
            if body["history_event_id"] != canonical_id:
                raise MessageStoreError()

    @staticmethod
    def _reseal(*, connection: sqlite3.Connection, target: MessageAddressDAO) -> None:
        """Adopt the owner generation without making old accepted input executable.

        This local storage seal does not perform session history reconciliation.
        Applying records keep their claim/journal and become retained for that later
        explicit reconciliation; neither sealed startup nor enablement replays them.
        """
        try:
            connection.execute("UPDATE meta SET value=? WHERE key=?", (_LIFECYCLE_SEALED, _LIFECYCLE_KEY))
            connection.execute("UPDATE meta SET value=? WHERE key=?", (target.generation, _GENERATION_KEY))
            connection.execute("UPDATE messages SET retained=1 WHERE state IN ('accepted','applying')")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @classmethod
    async def _run_on(
        cls,
        *,
        executor: ThreadPoolExecutor,
        operation: Callable[[], _T],
    ) -> _T:
        """Run one blocking operation on the worker, shielded and joined.

        A cancelled waiter never abandons the started worker operation:
        the shielded future is awaited to completion before the
        cancellation propagates.

        Args:
            executor (ThreadPoolExecutor): The store's single-worker executor.
            operation (Callable[[], _T]): Blocking work to run on the worker.

        Returns:
            _T: The operation result.
        """
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(executor, operation)
        result, cancelled = await cls._settle(future=future)
        if cancelled:
            raise asyncio.CancelledError()
        return result

    @staticmethod
    async def _settle(future: asyncio.Future[_T]) -> tuple[_T, bool]:
        """Join repeated cancellation without cancelling the started worker future."""
        cancelled = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled and not future.cancelled() and future.exception() is not None:
            raise asyncio.CancelledError() from None
        return future.result(), cancelled

    async def _run(self, operation: Callable[[], _T]) -> _T:
        """Run one blocking operation on this store's worker, joined on cancel.

        This is the single error-translation chokepoint: any raw SQLite,
        filesystem or decoding failure is suppressed and re-raised as the
        fixed safe ``MessageStoreError``. Caller-decided errors
        (``MessageAdmissionError``, ``MessageStoreError``) pass through.

        Args:
            operation (Callable[[], _T]): Blocking work to run on the worker.

        Returns:
            _T: The operation result.

        Raises:
            MessageStoreError: Any translated storage failure.
        """
        try:
            return await self._run_on(
                executor=self._executor, operation=lambda: self._run_validated(operation=operation)
            )
        except (MessageAdmissionError, MessageStoreError):
            raise
        except (sqlite3.Error, OSError, ValueError):
            raise MessageStoreError() from None

    def _run_validated(self, *, operation: Callable[[], _T]) -> _T:
        """Keep every filesystem recheck and operation on the owning worker."""
        if self._files is not None:
            self._files.validate()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            self._validate_meta(connection=connection)
            cursor = connection.cursor()
            cursor.row_factory = sqlite3.Row
            active = cursor.execute(
                "SELECT i.* FROM identity i JOIN messages m USING(message_id)"
                " WHERE m.retained=0 AND m.state IN ('accepted','applying') LIMIT 513"
            ).fetchall()
            if len(active) > 512:
                raise MessageStoreError()
            for identity in active:
                self._validate_identity(
                    connection=connection, identity=identity, durable=self._durable, target=self._target
                )
            result = operation()
            if self._files is not None:
                self._files.validate()
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise

    async def close(self) -> None:
        """Join all submitted worker operations, then close connection and worker.

        Idempotent: a repeated call does nothing. A cancellation of the
        waiter still joins the worker close before propagating.
        """
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_owned())
        _, cancelled = await self._settle(future=self._close_task)
        if cancelled:
            raise asyncio.CancelledError()

    async def _close_owned(self) -> None:
        """Close behind queued work and join the dedicated worker exactly once."""
        try:
            await self._run_on(executor=self._executor, operation=self._connection.close)
        finally:
            if self._files is not None:
                await self._run_on(executor=self._executor, operation=self._files.close)
            self._executor.shutdown(wait=True)

    async def admit(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
    ) -> MessageReceiptDAO:
        """Commit one authorized submission and return its canonical receipt.

        Counter allocation and identity/body insertion occur in one
        ``BEGIN IMMEDIATE`` transaction; the sequence increments only on
        new admission. An identical retry returns the original outcome; a
        changed payload conflicts. Rollback happens on any BaseException —
        a partly updated identity/body state is never committed. Acceptance
        is returned only after the commit is confirmed.

        Args:
            submission (MessageSubmissionDAO): Immutable input and retry identity.
            principal (MessagePrincipalDAO): Recipient-authenticated sender.

        Returns:
            MessageReceiptDAO: Original duplicate receipt or new durable receipt.

        Raises:
            MessageAdmissionError: Capacity, conflict, sealed lifecycle or
                foreign-principal retry.
            MessageStoreError: The durable commit cannot be confirmed.
        """
        if self._closed:
            raise MessageStoreError()
        return await self._run(lambda: self._admit_tx(submission=submission, principal=principal))

    def _admit_tx(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
    ) -> MessageReceiptDAO:
        """Run the complete admission transaction on the store worker."""
        connection = self._connection
        connection.execute("SAVEPOINT operation")
        try:
            receipt = self._admit_in_transaction(submission=submission, principal=principal)
            connection.execute("RELEASE operation")
            return receipt
        except BaseException:
            connection.execute("ROLLBACK TO operation")
            connection.execute("RELEASE operation")
            raise

    def _admit_in_transaction(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
    ) -> MessageReceiptDAO:
        """Decide duplicate/conflict/new admission inside the open transaction."""
        self._require_live_target(submission=submission)
        self._require_source_author(submission=submission, principal=principal)
        digest = _submission_digest(submission=submission, principal=principal)
        identity_row = self._connection.execute(
            "SELECT digest, principal_json FROM identity WHERE message_id = ?",
            (submission.message_id,),
        ).fetchone()
        if identity_row is not None:
            return self._duplicate_outcome(
                submission=submission,
                principal=principal,
                identity_row=identity_row,
            )
        if (
            submission.source_event_id is not None
            and self._connection.execute(
                "SELECT 1 FROM identity WHERE source_event_id=?", (submission.source_event_id,)
            ).fetchone()
        ):
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="conflict", message_id=submission.message_id)
            )
        self._require_accepting()
        self._require_capacity(submission=submission, principal=principal)
        return self._insert_new_admission(
            submission=submission,
            principal=principal,
            digest=digest,
        )

    @staticmethod
    def _require_source_author(*, submission: MessageSubmissionDAO, principal: MessagePrincipalDAO) -> None:
        """Validate source shape/correlation, without granting session authority."""
        if submission.payload.type == "workflow":
            workflow = submission.payload.workflow
            if (principal.kind, principal.session_id, principal.generation) != (
                "workflow",
                workflow.orchestrator_session_id,
                workflow.orchestrator_generation,
            ) or submission.target.session_id != workflow.owner_session_id:
                raise MessageAdmissionError(
                    error=MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
                )
            return
        if submission.source_event_id is None:
            return
        parts = submission.source_event_id.split(":")
        valid = principal.kind == "scheduler" and len(parts) == 3 and parts[0] == "schedule"
        if valid:
            try:
                valid = all(str(UUID(part)) == part for part in parts[1:])
            except ValueError:
                valid = False
        if not valid:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
            )

    def _require_live_target(self, *, submission: MessageSubmissionDAO) -> None:
        """Require the exact current logical target, including for duplicate admission."""
        if (submission.target.kind, submission.target.session_id, submission.target.channel_id) != (
            self._target.kind,
            self._target.session_id,
            self._target.channel_id,
        ):
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
            )
        if submission.target.generation != self._target.generation:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="stale_generation", message_id=submission.message_id)
            )

    def _duplicate_outcome(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
        identity_row: tuple,
    ) -> MessageReceiptDAO:
        """Return the original outcome for an identical retry, or refuse.

        Raises:
            MessageAdmissionError: ``unauthorized`` for a foreign principal,
                ``conflict`` for changed payload bytes under the same ID.
        """
        stored_digest, stored_principal_json = identity_row
        if MessagePrincipalDAO.model_validate_json(stored_principal_json) != principal:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="unauthorized", message_id=submission.message_id)
            )
        candidate_digest = _submission_digest(submission=submission, principal=principal)
        if candidate_digest != stored_digest:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="conflict", message_id=submission.message_id)
            )
        return self._receipt_for(message_id=submission.message_id)

    def _require_accepting(self) -> None:
        """Refuse new admission while the store lifecycle is sealed.

        Raises:
            MessageAdmissionError: ``completing`` when admission is sealed.
        """
        row = self._connection.execute("SELECT value FROM meta WHERE key = ?", (_LIFECYCLE_KEY,)).fetchone()
        if row is None or row[0] != _LIFECYCLE_ACCEPTING:
            raise MessageAdmissionError(error=MessageErrorDAO(code="completing"))

    def _require_capacity(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
    ) -> None:
        """Refuse new IDs beyond payload, storage, queue and sender budgets.

        Applying records count toward every capacity limit; duplicate
        lookup precedes these checks, so a full queue still resolves
        identical retries.

        Raises:
            MessageAdmissionError: ``queue_full`` or ``sender_limit``.
            MessageStoreError: The 256 MiB storage budget is reached.
        """
        payload_size = len(canonical_submission_bytes(submission=submission))
        if payload_size > self._limits.payload_bytes:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
            )
        if self._storage_bytes() + payload_size > _STORAGE_BUDGET_BYTES:
            raise MessageStoreError()
        lane = "agent_input" if submission.kind == "agent_input" else "note"
        limit = self._limits.pending_inputs if lane == "agent_input" else self._limits.pending_notes
        lane_count = self._pending_lane_count(kind=submission.kind)
        if lane_count >= limit:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="queue_full", message_id=submission.message_id)
            )
        sender_count = self._pending_sender_count(principal_id=principal.principal_id)
        if sender_count >= self._limits.pending_per_sender:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="sender_limit", message_id=submission.message_id)
            )
        if submission.priority == "urgent":
            urgent_count = self._pending_urgent_sender_count(principal_id=principal.principal_id)
            if urgent_count >= self._limits.urgent_per_sender:
                raise MessageAdmissionError(
                    error=MessageErrorDAO(code="sender_limit", message_id=submission.message_id)
                )

    def _pending_lane_count(self, *, kind: str) -> int:
        """Count pending (accepted or applying) records in one admission lane."""
        if kind == "agent_input":
            row = self._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE state IN ('accepted','applying') AND retained=0"
                " AND kind = 'agent_input'"
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE state IN ('accepted','applying') AND retained=0"
                " AND kind != 'agent_input'"
            ).fetchone()
        return int(row[0])

    def _pending_sender_count(self, *, principal_id: str) -> int:
        """Count one sender's pending records across all kinds."""
        row = self._connection.execute(
            "SELECT COUNT(*) FROM messages m JOIN identity i USING(message_id)"
            " WHERE m.state IN ('accepted','applying') AND m.retained=0 AND i.principal_id = ?",
            (principal_id,),
        ).fetchone()
        return int(row[0])

    def _pending_urgent_sender_count(self, *, principal_id: str) -> int:
        """Count one sender's pending urgent records."""
        row = self._connection.execute(
            "SELECT COUNT(*) FROM messages m JOIN identity i USING(message_id)"
            " WHERE m.state IN ('accepted','applying') AND m.retained=0 AND m.priority = 'urgent'"
            " AND i.principal_id = ?",
            (principal_id,),
        ).fetchone()
        return int(row[0])

    def _storage_bytes(self) -> int:
        """Measure the messaging database budget consumption including WAL."""
        if self._path is None:
            row = self._connection.execute("PRAGMA page_count").fetchone()
            size_row = self._connection.execute("PRAGMA page_size").fetchone()
            return int(row[0]) * int(size_row[0])
        total = 0
        for suffix in ("", "-wal", "-shm"):
            sibling = Path(str(self._path) + suffix)
            try:
                if sibling.exists():
                    total += sibling.stat().st_size
            except OSError:
                raise MessageStoreError() from None
        return total

    def _insert_new_admission(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
        digest: str,
    ) -> MessageReceiptDAO:
        """Allocate the sequence and insert identity/body in the open transaction.

        Raises:
            MessageStoreError: The sequence counter is exhausted.
        """
        row = self._connection.execute(
            "SELECT value FROM meta WHERE key = ?", (_NEXT_SEQUENCE_KEY,)
        ).fetchone()
        sequence = int(row[0])
        if sequence >= _SEQUENCE_MAX:
            raise MessageStoreError()
        admitted_at = utcnow()
        generation = self._meta_value(key=_GENERATION_KEY)
        self._connection.execute(
            "UPDATE meta SET value = ? WHERE key = ?",
            (str(sequence + 1), _NEXT_SEQUENCE_KEY),
        )
        self._connection.execute(
            "INSERT INTO identity("
            " message_id, digest, principal_id, principal_json, original_target_json,"
            " sequence, admitted_at, durable, state, kind, source_event_id,"
            " execution_generation)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                submission.message_id,
                digest,
                principal.principal_id,
                principal.model_dump_json(),
                submission.target.model_dump_json(),
                sequence,
                admitted_at.isoformat(),
                1 if self._durable else 0,
                "accepted",
                submission.kind,
                submission.source_event_id,
                generation,
            ),
        )
        self._connection.execute(
            "INSERT INTO messages("
            " message_id, submission_json, sequence, kind, priority, state,"
            " execution_generation)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                submission.message_id,
                submission.model_dump_json(),
                sequence,
                submission.kind,
                submission.priority,
                "accepted",
                generation,
            ),
        )
        return MessageReceiptDAO(
            message_id=submission.message_id,
            target=submission.target,
            state="accepted",
            sequence=sequence,
            durable=self._durable,
            admitted_at=admitted_at,
        )

    def _meta_value(self, *, key: str) -> str:
        """Return one required meta value, or fail closed as corruption."""
        row = self._connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise MessageStoreError()
        return str(row[0])

    def _receipt_for(self, *, message_id: str) -> MessageReceiptDAO:
        """Reconstruct the canonical receipt from retained identity metadata.

        Identity tombstones retain target, admitted_at, applied_at, durable
        and run_id, so a lookup after terminal payload pruning still
        reconstructs a minimal terminal receipt.
        """
        self._require_stored_identity(message_id=message_id)
        row = self._connection.execute(
            "SELECT original_target_json, state, sequence, durable, admitted_at,"
            " applied_at, run_id FROM identity WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise MessageStoreError()
        (
            target_json,
            state,
            sequence,
            durable,
            admitted_at,
            applied_at,
            run_id,
        ) = row
        retained = self._connection.execute(
            "SELECT retained FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return MessageReceiptDAO(
            message_id=message_id,
            target=MessageAddressDAO.model_validate_json(target_json),
            state=state,
            sequence=int(sequence),
            durable=bool(durable),
            admitted_at=datetime.fromisoformat(admitted_at),
            applied_at=datetime.fromisoformat(applied_at) if applied_at is not None else None,
            run_id=run_id,
            retained_for_recovery=bool(retained[0]) if retained is not None else False,
        )

    def _require_stored_identity(self, *, message_id: str) -> None:
        """Validate one addressed identity and its body/journal in the operation snapshot."""
        cursor = self._connection.cursor()
        cursor.row_factory = sqlite3.Row
        row = cursor.execute("SELECT * FROM identity WHERE message_id=?", (message_id,)).fetchone()
        if row is None:
            raise MessageStoreError()
        self._validate_identity(
            connection=self._connection, identity=row, durable=self._durable, target=self._target
        )

    async def claim_one(self, *, boundary: BoundaryDAO) -> Optional[MessageDeliveryDAO]:
        """Claim at most one instruction for one boundary, recoverably.

        A claim conditionally moves state columns to applying and installs
        run/boundary/event identity. A second claim for the same
        ``(run_id, boundary_index)`` is refused by the unique boundary
        index; repeat reads return the already-claimed delivery, including
        after preparation. Selection is urgent before normal, FIFO by
        sequence within each class, over current-generation, non-retained,
        accepted agent_input records.

        Args:
            boundary (BoundaryDAO): Stable logical run ID and boundary index.

        Returns:
            Optional[MessageDeliveryDAO]: The claimed or replayed delivery,
                or None when this boundary cannot claim.
        """
        if self._closed:
            raise MessageStoreError()
        return await self._run(lambda: self._claim_tx(boundary=boundary))

    async def claim_note(self, *, boundary: BoundaryDAO) -> Optional[MessageDeliveryDAO]:
        """Claim one FIFO context/transcript note in its independent boundary slot."""
        if self._closed:
            raise MessageStoreError()
        return await self._run(lambda: self._claim_tx(boundary=boundary, note=True))

    def _claim_tx(self, *, boundary: BoundaryDAO, note: bool = False) -> Optional[MessageDeliveryDAO]:
        """Run the complete claim transaction on the store worker."""
        connection = self._connection
        connection.execute("SAVEPOINT operation")
        try:
            delivery = self._claim_in_transaction(boundary=boundary, note=note)
            connection.execute("RELEASE operation")
            return delivery
        except BaseException:
            connection.execute("ROLLBACK TO operation")
            connection.execute("RELEASE operation")
            raise

    def _claim_in_transaction(
        self, *, boundary: BoundaryDAO, note: bool = False
    ) -> Optional[MessageDeliveryDAO]:
        """Replay an existing boundary claim or claim the next eligible input."""
        if self._meta_value(key=_LIFECYCLE_KEY) != _LIFECYCLE_ACCEPTING:
            return None
        lane = "kind IN ('context_note','transcript_note')" if note else "kind = 'agent_input'"
        existing = self._connection.execute(
            "SELECT m.message_id, m.history_event_id, m.state FROM messages m"
            f" WHERE m.run_id = ? AND m.boundary_index = ? AND {lane}"
            " AND m.retained = 0 AND m.execution_generation = ?",
            (boundary.run_id, boundary.boundary_index, self._target.generation),
        ).fetchone()
        if existing is not None:
            message_id, history_event_id, state = existing
            if state != "applying":
                return None
            return self._delivery_for(message_id=message_id, history_event_id=history_event_id)
        candidate = self._connection.execute(
            "SELECT message_id FROM messages"
            f" WHERE state = 'accepted' AND retained = 0 AND {lane}"
            " AND execution_generation = ?"
            " ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, sequence"
            " LIMIT 1",
            (self._meta_value(key=_GENERATION_KEY),),
        ).fetchone()
        if candidate is None:
            return None
        message_id = candidate[0]
        history_event_id = str(uuid5(namespace=UUID(self._target.session_id), name="message:" + message_id))
        self._connection.execute(
            "UPDATE messages SET state = 'applying', run_id = ?, boundary_index = ?,"
            " history_event_id = ? WHERE message_id = ?",
            (boundary.run_id, boundary.boundary_index, history_event_id, message_id),
        )
        self._connection.execute(
            "UPDATE identity SET state = 'applying', run_id = ? WHERE message_id = ?",
            (boundary.run_id, message_id),
        )
        return self._delivery_for(message_id=message_id, history_event_id=history_event_id)

    def _delivery_for(
        self,
        *,
        message_id: str,
        history_event_id: Optional[str] = None,
        event: Optional[SessionHistoryEventDAO] = None,
    ) -> MessageDeliveryDAO:
        """Reconstruct one recoverable delivery from identity/body rows."""
        self._require_stored_identity(message_id=message_id)
        row = self._connection.execute(
            "SELECT m.submission_json, m.sequence, m.run_id, m.boundary_index,"
            " m.history_event_id, i.principal_json, i.admitted_at"
            " FROM messages m JOIN identity i USING(message_id)"
            " WHERE m.message_id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            raise MessageStoreError()
        (
            submission_json,
            sequence,
            run_id,
            boundary_index,
            stored_event_id,
            principal_json,
            admitted_at,
        ) = row
        if run_id is None or boundary_index is None:
            raise MessageStoreError()
        installed = history_event_id or stored_event_id
        if installed is None:
            raise MessageStoreError()
        envelope = MessageEnvelopeDAO(
            submission=MessageSubmissionDAO.model_validate_json(submission_json),
            sender=MessagePrincipalDAO.model_validate_json(principal_json),
            sequence=int(sequence),
            admitted_at=datetime.fromisoformat(admitted_at),
        )
        return MessageDeliveryDAO(
            envelope=envelope,
            boundary=BoundaryDAO(run_id=run_id, boundary_index=int(boundary_index)),
            history_event_id=installed,
            event=event,
        )

    async def prepare_application(
        self,
        *,
        delivery: MessageDeliveryDAO,
        event: SessionHistoryEventDAO,
    ) -> None:
        """Journal the exact application event before history append.

        An identical retry is idempotent; an unequal duplicate is
        corruption and fails closed.

        Raises:
            MessageStoreError: Missing claim or mismatched journaled event.
        """
        if self._closed:
            raise MessageStoreError()
        # Serialize on entry: caller-owned history DAOs remain mutable, whereas the
        # worker must validate precisely the bytes it will persist.
        message_id = delivery.envelope.submission.message_id
        delivery = MessageDeliveryDAO.model_validate_json(delivery.model_dump_json())
        event_json = event.model_dump_json()
        event = SessionHistoryEventDAO.model_validate_json(event_json)

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                row = connection.execute(
                    "SELECT event_json FROM applications WHERE message_id = ?", (message_id,)
                ).fetchone()
                stored = self._delivery_for(message_id=message_id)
                if delivery.model_copy(update={"event": None}) != stored:
                    raise MessageStoreError()
                generation = connection.execute(
                    "SELECT execution_generation FROM identity WHERE message_id=?", (message_id,)
                ).fetchone()[0]
                self._require_application_event(delivery=stored, event=event, generation=generation)
                digest = self._event_digest(event=event)
                if (
                    row is not None
                    and self._event_digest(event=SessionHistoryEventDAO.model_validate_json(row[0])) != digest
                ):
                    raise MessageStoreError()
                if row is None:
                    claim = connection.execute(
                        "SELECT 1 FROM messages WHERE message_id = ? AND state = 'applying'",
                        (message_id,),
                    ).fetchone()
                    if claim is None:
                        raise MessageStoreError()
                    connection.execute(
                        "INSERT INTO applications(message_id, event_json) VALUES (?, ?)",
                        (message_id, event_json),
                    )
                    connection.execute(
                        "UPDATE identity SET history_event_id=?, event_sha256=? WHERE message_id=?",
                        (event.event_id, digest, message_id),
                    )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def load_application_event(self, *, message_id: str) -> SessionHistoryEventDAO:
        """Return the journaled application event for reconciliation.

        Raises:
            MessageStoreError: No journaled event exists for this message.
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> SessionHistoryEventDAO:
            self._require_stored_identity(message_id=message_id)
            row = self._connection.execute(
                "SELECT event_json FROM applications WHERE message_id = ?", (message_id,)
            ).fetchone()
            if row is None:
                raise MessageStoreError()
            return SessionHistoryEventDAO.model_validate_json(row[0])

        return await self._run(_read)

    async def load_unsettled_applications(self) -> list[MessageDeliveryDAO]:
        """Return claimed-but-unapplied deliveries for startup reconciliation.

        Only prepared applying rows are returned, in sequence order,
        bounded at 512; unprepared rows belong to ``reset_unprepared_claims``.
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> list[MessageDeliveryDAO]:
            rows = self._connection.execute(
                "SELECT m.message_id, a.event_json FROM messages m"
                " JOIN applications a USING(message_id)"
                " WHERE m.state = 'applying' ORDER BY m.sequence LIMIT ?",
                (_UNSETTLED_APPLICATION_LIMIT,),
            ).fetchall()
            return [
                self._delivery_for(
                    message_id=message_id,
                    event=SessionHistoryEventDAO.model_validate_json(event_json),
                )
                for message_id, event_json in rows
            ]

        return await self._run(_read)

    async def reset_unprepared_claims(self) -> None:
        """Return unprepared claims to retained state during sealed startup.

        Claims without an application journal lose their run/boundary/event
        identity and become retained accepted; explicit recovery is required.
        The original input is never deleted or automatically reexecuted.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                connection.execute(
                    "UPDATE messages SET state = 'accepted', run_id = NULL,"
                    " boundary_index = NULL, history_event_id = NULL, retained = 1"
                    " WHERE state = 'applying' AND message_id NOT IN"
                    " (SELECT message_id FROM applications)"
                )
                connection.execute(
                    "UPDATE identity SET state = 'accepted', run_id = NULL"
                    " WHERE state = 'applying' AND message_id NOT IN"
                    " (SELECT message_id FROM applications)"
                )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def mark_history_committed(self, *, message_id: str) -> None:
        """Record that the journaled event reached canonical history.

        A repeated mark is idempotent; marking without a journal fails closed.

        Raises:
            MessageStoreError: No application journal exists for this message.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                cursor = connection.execute(
                    "UPDATE applications SET history_committed = 1 WHERE message_id = ?",
                    (message_id,),
                )
                if cursor.rowcount == 0:
                    raise MessageStoreError()
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def mark_applied(self, *, message_id: str) -> MessageReceiptDAO:
        """Mark delivery applied only after all required evidence is valid.

        History commitment is required; a workflow payload additionally
        requires its committed workflow effect. Message, identity and
        application flags settle atomically.

        Returns:
            MessageReceiptDAO: The terminal applied receipt.

        Raises:
            MessageStoreError: Required evidence is uncommitted.
        """
        if self._closed:
            raise MessageStoreError()
        return await self._run(lambda: self._mark_applied_tx(message_id=message_id))

    def _mark_applied_tx(self, *, message_id: str) -> MessageReceiptDAO:
        """Run the terminal application transaction on the store worker."""
        connection = self._connection
        connection.execute("SAVEPOINT operation")
        try:
            receipt = self._mark_applied_in_transaction(message_id=message_id)
            connection.execute("RELEASE operation")
            return receipt
        except BaseException:
            connection.execute("ROLLBACK TO operation")
            connection.execute("RELEASE operation")
            raise

    def _mark_applied_in_transaction(self, *, message_id: str) -> MessageReceiptDAO:
        """Settle the terminal applied state inside the open transaction."""
        receipt = self._receipt_for(message_id=message_id)
        if receipt.state == "applied":
            return receipt
        journal = self._connection.execute(
            "SELECT history_committed, workflow_effect_committed FROM applications" " WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if journal is None or int(journal[0]) != 1:
            raise MessageStoreError()
        message = self._connection.execute(
            "SELECT submission_json FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        if message is None:
            raise MessageStoreError()
        submission = MessageSubmissionDAO.model_validate_json(message[0])
        if submission.payload.type == "workflow" and int(journal[1]) != 1:
            raise MessageStoreError()
        applied_at = utcnow().isoformat()
        self._connection.execute(
            "UPDATE applications SET context_committed = 1 WHERE message_id = ?",
            (message_id,),
        )
        self._connection.execute(
            "UPDATE messages SET state = 'applied', retained = 0 WHERE message_id = ?", (message_id,)
        )
        self._connection.execute(
            "UPDATE identity SET state = 'applied', applied_at = ?, terminal_at = ?,"
            " history_event_id = (SELECT history_event_id FROM messages WHERE message_id = ?),"
            " event_sha256 = ? WHERE message_id = ?",
            (
                applied_at,
                applied_at,
                message_id,
                self._application_event_digest(message_id=message_id),
                message_id,
            ),
        )
        return self._receipt_for(message_id=message_id)

    def _application_event_digest(self, *, message_id: str) -> str:
        """Digest the journaled application event for identity evidence."""
        row = self._connection.execute(
            "SELECT event_json FROM applications WHERE message_id = ?", (message_id,)
        ).fetchone()
        if row is None:
            raise MessageStoreError()
        return self._event_digest(event=SessionHistoryEventDAO.model_validate_json(row[0]))

    @staticmethod
    def _event_digest(*, event: SessionHistoryEventDAO) -> str:
        """Hash canonical event JSON, excluding only history-assigned fields."""
        data = event.model_dump(mode="json")
        data.pop("sequence")
        data["payload"].pop("token_usage")
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _require_application_event(
        cls, *, delivery: MessageDeliveryDAO, event: SessionHistoryEventDAO, generation: str
    ) -> None:
        """Compare all supplied fields to the deterministic event of the stored claim."""
        envelope = delivery.envelope
        submission = envelope.submission
        metadata = MessageApplicationMetadataDAO(
            message_id=submission.message_id,
            kind=submission.kind,
            sender=envelope.sender,
            sequence=envelope.sequence,
            run_id=delivery.boundary.run_id,
            execution_generation=generation,
        )
        expected = SessionHistoryEventDAO(
            event_id=delivery.history_event_id,
            session_id=submission.target.session_id,
            kind="workflow_update",
            turn_id=delivery.boundary.run_id,
            recorded_at=envelope.admitted_at,
            payload=SessionHistoryEventPayloadDAO(
                content=submission.text, metadata={"messaging_v1": metadata.model_dump(mode="json")}
            ),
        )
        if cls._event_digest(event=expected) != cls._event_digest(event=event):
            raise MessageStoreError()

    async def read_identities(
        self, *, after_sequence: int = 0, limit: int = 256
    ) -> tuple[MessageIdentityDAO, ...]:
        """Read one ordered lifetime identity page on the store worker, limit 1..256."""
        if type(after_sequence) is not int or not 0 <= after_sequence <= _SEQUENCE_MAX:
            raise MessageAdmissionError(error=MessageErrorDAO(code="invalid_message"))
        if type(limit) is not int or not 1 <= limit <= 256:
            raise MessageAdmissionError(error=MessageErrorDAO(code="invalid_message"))
        if self._closed:
            raise MessageStoreError()

        def _read() -> tuple[MessageIdentityDAO, ...]:
            cursor = self._connection.cursor()
            cursor.row_factory = sqlite3.Row
            rows = cursor.execute(
                "SELECT * FROM identity WHERE sequence>? ORDER BY sequence LIMIT ?", (after_sequence, limit)
            ).fetchall()
            return tuple(
                MessageIdentityDAO(
                    receipt=self._receipt_for(message_id=row["message_id"]),
                    sender=MessagePrincipalDAO.model_validate_json(row["principal_json"]),
                    digest=row["digest"],
                    kind=row["kind"],
                    history_event_id=row["history_event_id"],
                    event_sha256=row["event_sha256"],
                    execution_generation=row["execution_generation"],
                )
                for row in rows
            )

        return await self._run(_read)

    @staticmethod
    def _require_page(*, after_id: Optional[str], limit: int) -> None:
        """Validate lexical UUID cursors and strict bounded page sizes."""
        if type(limit) is not int or not 1 <= limit <= 256:
            raise MessageAdmissionError(error=MessageErrorDAO(code="invalid_message"))
        if after_id is not None:
            try:
                if str(UUID(after_id)) != after_id:
                    raise ValueError()
            except (ValueError, AttributeError, TypeError):
                raise MessageAdmissionError(error=MessageErrorDAO(code="invalid_message")) from None

    def _compaction_for(self, *, compaction_id: str) -> CompactionLedgerDAO:
        """Decode exact ledger membership from the same SQLite snapshot."""
        row = self._connection.execute(
            "SELECT state, summary_event_id FROM compactions WHERE compaction_id=?", (compaction_id,)
        ).fetchone()
        if row is None:
            raise MessageStoreError()
        messages = self._connection.execute(
            "SELECT message_id FROM compacted_applications WHERE compaction_id=? ORDER BY message_id",
            (compaction_id,),
        )
        message_ids = tuple(item[0] for item in messages)
        observations = self._connection.execute(
            "SELECT observation_id FROM compacted_observations WHERE compaction_id=? ORDER BY observation_id",
            (compaction_id,),
        )
        return CompactionLedgerDAO(
            compaction_id=compaction_id,
            state=row[0],
            summary_event_id=row[1],
            message_ids=message_ids,
            observation_ids=tuple(item[0] for item in observations),
        )

    async def read_retained(
        self, *, after_sequence: int = 0, limit: int = 256
    ) -> tuple[MessageEnvelopeDAO, ...]:
        """Read retained accepted local sources by sequence, preserving original authorship.

        This trusted session-only read creates no preview, transfer or acceptance.
        The session owns source registration and human confirmation.
        """
        if type(after_sequence) is not int or not 0 <= after_sequence <= _SEQUENCE_MAX:
            raise MessageAdmissionError(error=MessageErrorDAO(code="invalid_message"))
        self._require_page(after_id=None, limit=limit)
        if self._closed:
            raise MessageStoreError()

        def _read() -> tuple[MessageEnvelopeDAO, ...]:
            rows = self._connection.execute(
                "SELECT m.message_id, m.submission_json, i.principal_json, i.sequence, i.admitted_at"
                " FROM messages m JOIN identity i USING(message_id)"
                " WHERE m.retained=1 AND m.state='accepted' AND m.sequence>? ORDER BY m.sequence LIMIT ?",
                (after_sequence, limit),
            ).fetchall()
            result = []
            for message_id, submission, principal, sequence, admitted_at in rows:
                self._require_stored_identity(message_id=message_id)
                result.append(
                    MessageEnvelopeDAO(
                        submission=MessageSubmissionDAO.model_validate_json(submission),
                        sender=MessagePrincipalDAO.model_validate_json(principal),
                        sequence=sequence,
                        admitted_at=datetime.fromisoformat(admitted_at),
                    )
                )
            return tuple(result)

        return await self._run(_read)

    async def read_compactions(
        self, *, after_id: Optional[str] = None, limit: int = 256
    ) -> tuple[CompactionLedgerDAO, ...]:
        """Page all compaction states lexically by canonical UUID on the worker."""
        self._require_page(after_id=after_id, limit=limit)
        if self._closed:
            raise MessageStoreError()

        def _read() -> tuple[CompactionLedgerDAO, ...]:
            rows = self._connection.execute(
                "SELECT compaction_id FROM compactions WHERE compaction_id>? ORDER BY compaction_id LIMIT ?",
                (after_id or "", limit),
            ).fetchall()
            return tuple(self._compaction_for(compaction_id=row[0]) for row in rows)

        return await self._run(_read)

    async def read_observations(
        self, *, after_id: Optional[str] = None, limit: int = 256
    ) -> tuple[InternalObservationDAO, ...]:
        """Page prepared/applied observation proof, including pruned tombstones."""
        self._require_page(after_id=after_id, limit=limit)
        if self._closed:
            raise MessageStoreError()

        def _read() -> tuple[InternalObservationDAO, ...]:
            rows = self._connection.execute(
                "SELECT observation_id, history_event_id, event_sha256, state, event_json"
                " FROM internal_observations WHERE observation_id>? ORDER BY observation_id LIMIT ?",
                (after_id or "", limit),
            ).fetchall()
            records = tuple(
                InternalObservationDAO(
                    observation_id=row[0],
                    history_event_id=row[1],
                    event_sha256=row[2],
                    state=row[3],
                    event=SessionHistoryEventDAO.model_validate_json(row[4]) if row[4] is not None else None,
                )
                for row in rows
            )
            for record in records:
                if record.event is not None and (
                    record.event.event_id != record.history_event_id
                    or self._event_digest(event=record.event) != record.event_sha256
                ):
                    raise MessageStoreError()
            return records

        return await self._run(_read)

    async def get_receipt(
        self,
        *,
        message_id: str,
        principal: MessagePrincipalDAO,
    ) -> Optional[MessageReceiptDAO]:
        """Return the receipt for the authorized principal, or None when absent.

        Receipt payloads expire seven days after terminal state; a lookup
        after pruning reconstructs a minimal terminal receipt from retained
        identity metadata. A foreign principal is refused without payload.

        Raises:
            MessageAdmissionError: ``unauthorized`` for a foreign principal.
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> Optional[MessageReceiptDAO]:
            row = self._connection.execute(
                "SELECT principal_json FROM identity WHERE message_id = ?", (message_id,)
            ).fetchone()
            if row is None:
                return None
            if MessagePrincipalDAO.model_validate_json(row[0]) != principal:
                raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized", message_id=message_id))
            return self._receipt_for(message_id=message_id)

        return await self._run(_read)

    async def retain_pending(self) -> None:
        """Retain unapplied accepted input across shutdown or /new.

        Accepted bodies are marked retained without changing their original
        identity; applying and terminal records are untouched.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                connection.execute("UPDATE messages SET retained = 1 WHERE state = 'accepted'")
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def cancel_retained(self, *, message_ids: tuple[str, ...]) -> None:
        """Cancel only the exact confirmed retained selection.

        Every selected ID must still be a retained accepted record; any
        changed selection refuses the whole operation atomically.

        Raises:
            MessageAdmissionError: ``recovery_required`` when any selected ID
                is absent or no longer retained-accepted.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                for message_id in message_ids:
                    exists = connection.execute(
                        "SELECT 1 FROM identity WHERE message_id=?", (message_id,)
                    ).fetchone()
                    if exists is not None:
                        self._require_stored_identity(message_id=message_id)
                    row = connection.execute(
                        "SELECT retained FROM messages WHERE message_id = ? AND state = 'accepted'",
                        (message_id,),
                    ).fetchone()
                    if row is None or int(row[0]) != 1:
                        raise MessageAdmissionError(
                            error=MessageErrorDAO(code="recovery_required", message_id=message_id)
                        )
                terminal_at = utcnow().isoformat()
                for message_id in message_ids:
                    connection.execute(
                        "UPDATE messages SET state = 'cancelled', retained = 0" " WHERE message_id = ?",
                        (message_id,),
                    )
                    connection.execute(
                        "UPDATE identity SET state = 'cancelled', terminal_at = ?" " WHERE message_id = ?",
                        (terminal_at, message_id),
                    )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def read_queue_state(self) -> QueueStateDAO:
        """Read eligibility counts atomically, including applying capacity.

        Counts cover current-generation, non-retained, accepted records;
        applying records count toward capacity limits, not eligibility, and
        retained work is excluded. The urgent high-water is the highest
        eligible urgent sequence, or zero.
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> QueueStateDAO:
            if self._meta_value(key=_LIFECYCLE_KEY) != _LIFECYCLE_ACCEPTING:
                return QueueStateDAO(eligible_inputs=0, eligible_notes=0, urgent_high_water=0)
            generation = self._meta_value(key=_GENERATION_KEY)
            inputs = self._connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(CASE priority WHEN 'urgent' THEN sequence END), 0)"
                " FROM messages WHERE state = 'accepted' AND retained = 0"
                " AND kind = 'agent_input' AND execution_generation = ?",
                (generation,),
            ).fetchone()
            notes = self._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE state = 'accepted' AND retained = 0"
                " AND kind IN ('context_note','transcript_note') AND execution_generation = ?",
                (generation,),
            ).fetchone()
            return QueueStateDAO(
                eligible_inputs=int(inputs[0]),
                eligible_notes=int(notes[0]),
                urgent_high_water=int(inputs[1]),
            )

        return await self._run(_read)

    async def read_summary(self, *, principal: MessagePrincipalDAO) -> QueueSummaryDAO:
        """Build the bounded presentation projection for the TUI queue band.

        Reports the total pending input count and only this principal's
        next local text; foreign text is never revealed.
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> QueueSummaryDAO:
            pending = self._connection.execute(
                "SELECT COUNT(*) FROM messages"
                " WHERE state IN ('accepted','applying') AND kind = 'agent_input'"
            ).fetchone()
            row = self._connection.execute(
                "SELECT m.message_id, m.submission_json FROM messages m"
                " JOIN identity i USING(message_id)"
                " WHERE m.state = 'accepted' AND m.retained = 0"
                " AND m.kind = 'agent_input' AND i.principal_json = ? AND m.execution_generation = ?"
                " ORDER BY CASE m.priority WHEN 'urgent' THEN 0 ELSE 1 END, m.sequence"
                " LIMIT 1",
                (principal.model_dump_json(), self._target.generation),
            ).fetchone()
            if row is None:
                return QueueSummaryDAO(pending_count=int(pending[0]))
            submission = MessageSubmissionDAO.model_validate_json(row[1])
            return QueueSummaryDAO(
                pending_count=int(pending[0]),
                next_local_message_id=row[0],
                next_local_text=submission.text,
            )

        return await self._run(_read)

    async def prepare_compaction(
        self,
        *,
        compaction_id: str,
        message_ids: tuple[str, ...],
        observation_ids: tuple[str, ...],
    ) -> None:
        """Record exact compaction membership; preparation is not coverage.

        Unsettled (accepted/applying) members are refused before any
        preparation row is written.

        Raises:
            MessageStoreError: An unknown or unsettled member, or a
                conflicting compaction ID.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                proposed = CompactionLedgerDAO(
                    compaction_id=compaction_id,
                    state="prepared",
                    message_ids=message_ids,
                    observation_ids=observation_ids,
                )
                existing = connection.execute(
                    "SELECT 1 FROM compactions WHERE compaction_id=?", (compaction_id,)
                ).fetchone()
                if existing is not None:
                    stored = self._compaction_for(compaction_id=compaction_id)
                    if set(stored.message_ids) != set(proposed.message_ids) or set(
                        stored.observation_ids
                    ) != set(proposed.observation_ids):
                        raise MessageStoreError()
                    connection.execute("RELEASE operation")
                    return
                if connection.execute("SELECT 1 FROM compactions WHERE state='prepared' LIMIT 1").fetchone():
                    raise MessageStoreError()
                if connection.execute("SELECT 1 FROM messages WHERE state='applying' LIMIT 1").fetchone():
                    raise MessageStoreError()
                if connection.execute(
                    "SELECT 1 FROM internal_observations WHERE state='prepared' LIMIT 1"
                ).fetchone():
                    raise MessageStoreError()
                for message_id in message_ids:
                    row = connection.execute(
                        "SELECT state FROM identity WHERE message_id = ?", (message_id,)
                    ).fetchone()
                    if row is None or row[0] != "applied":
                        raise MessageStoreError()
                for observation_id in observation_ids:
                    row = connection.execute(
                        "SELECT state FROM internal_observations WHERE observation_id = ?",
                        (observation_id,),
                    ).fetchone()
                    if row is None or row[0] != "applied":
                        raise MessageStoreError()
                connection.execute(
                    "INSERT INTO compactions(compaction_id, state, created_at)" " VALUES (?, 'prepared', ?)",
                    (compaction_id, utcnow().isoformat()),
                )
                for message_id in message_ids:
                    connection.execute(
                        "INSERT INTO compacted_applications(compaction_id, message_id)" " VALUES (?, ?)",
                        (compaction_id, message_id),
                    )
                for observation_id in observation_ids:
                    connection.execute(
                        "INSERT INTO compacted_observations(compaction_id, observation_id)" " VALUES (?, ?)",
                        (compaction_id, observation_id),
                    )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def finish_compaction(
        self,
        *,
        compaction_id: str,
        summary_event_id: Optional[str],
    ) -> None:
        """Commit or roll back one compaction ledger entry.

        A non-None summary event commits proven coverage; None records a
        proven rollback, not a failure. A repeated identical finish is
        idempotent; a conflicting finish fails closed.

        Raises:
            MessageStoreError: Unknown, finalized or conflicting compaction.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                row = connection.execute(
                    "SELECT state, summary_event_id FROM compactions WHERE compaction_id = ?",
                    (compaction_id,),
                ).fetchone()
                if row is None:
                    raise MessageStoreError()
                state, stored_summary = row
                if state == "prepared":
                    next_state = "committed" if summary_event_id is not None else "rolled_back"
                    connection.execute(
                        "UPDATE compactions SET state = ?, summary_event_id = ?" " WHERE compaction_id = ?",
                        (next_state, summary_event_id, compaction_id),
                    )
                else:
                    expected = stored_summary if state == "committed" else None
                    if expected != summary_event_id:
                        raise MessageStoreError()
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def prepare_observation(
        self,
        *,
        observation_id: str,
        event: SessionHistoryEventDAO,
    ) -> None:
        """Journal one internal observation before history append.

        An identical retry is idempotent; an unequal retry fails closed.

        Raises:
            MessageStoreError: Conflicting observation identity or event.
        """
        if self._closed:
            raise MessageStoreError()
        event_json = event.model_dump_json()
        digest = self._event_digest(event=event)

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                row = connection.execute(
                    "SELECT event_json, history_event_id FROM internal_observations"
                    " WHERE observation_id = ?",
                    (observation_id,),
                ).fetchone()
                if row is not None:
                    if (
                        row[0] is None
                        or self._event_digest(event=SessionHistoryEventDAO.model_validate_json(row[0]))
                        != digest
                        or row[1] != event.event_id
                    ):
                        raise MessageStoreError()
                else:
                    connection.execute(
                        "INSERT INTO internal_observations("
                        " observation_id, history_event_id, event_sha256, event_json, state)"
                        " VALUES (?, ?, ?, ?, 'prepared')",
                        (observation_id, event.event_id, digest, event_json),
                    )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def mark_observation_applied(self, *, observation_id: str) -> None:
        """Mark one internal observation applied after verification.

        A duplicate mark is harmless; a missing row is corruption.

        Raises:
            MessageStoreError: No prepared observation with this identity.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            connection.execute("SAVEPOINT operation")
            try:
                reader = connection.cursor()
                reader.row_factory = sqlite3.Row
                row = reader.execute(
                    "SELECT * FROM internal_observations WHERE observation_id=?", (observation_id,)
                ).fetchone()
                if row is None:
                    raise MessageStoreError()
                self._observation_record(row=row)
                cursor = connection.execute(
                    "UPDATE internal_observations SET state = 'applied'" " WHERE observation_id = ?",
                    (observation_id,),
                )
                if cursor.rowcount == 0:
                    raise MessageStoreError()
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)

    async def load_workflow_effect(self, *, message_id: str) -> Optional[str]:
        """Load a pending workflow effect outcome for reconciliation.

        Returns:
            Optional[str]: The committed outcome JSON, or None before any
                effect commit (including unknown messages).
        """
        if self._closed:
            raise MessageStoreError()

        def _read() -> Optional[str]:
            row = self._connection.execute(
                "SELECT workflow_effect_json FROM applications WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            return row[0]

        return await self._run(_read)

    async def commit_workflow_effect(self, *, message_id: str, outcome_json: str) -> None:
        """Refuse unavailable B.2 effect validation; opaque persistence is not advancement.

        A later version must inject the canonical B.2 outcome validator and enable
        its complete admission route together. A.1 has no such collaborator and
        never silently certifies caller JSON as a successful workflow effect.
        """
        if self._closed:
            raise MessageStoreError()
        raise MessageAdmissionError(error=MessageErrorDAO(code="unsupported", message_id=message_id))

    async def maintain(self, *, now: datetime) -> None:
        """Checkpoint WAL and prune terminal payloads outside execution.

        Runs serially on the store worker. Terminal message bodies and
        application journals expire ``limits.receipt_days`` after their
        terminal timestamp; identity tombstones and recovery_transfers are
        never pruned, and no accepted or applying body expires.

        Args:
            now (datetime): The caller's current canonical UTC timestamp.
        """
        if self._closed:
            raise MessageStoreError()

        def _write() -> None:
            connection = self._connection
            cutoff = now - timedelta(days=self._limits.receipt_days)
            for query in (
                "SELECT 1 FROM messages WHERE state='applying' LIMIT 1",
                "SELECT 1 FROM compactions WHERE state='prepared' LIMIT 1",
                "SELECT 1 FROM internal_observations WHERE state='prepared' LIMIT 1",
            ):
                if connection.execute(query).fetchone():
                    raise MessageStoreError()
            connection.execute("SAVEPOINT operation")
            try:
                expired = connection.execute(
                    "SELECT message_id FROM identity"
                    " WHERE state IN ('applied','cancelled')"
                    " AND terminal_at IS NOT NULL AND terminal_at < ?",
                    (cutoff.isoformat(),),
                )
                for (message_id,) in expired:
                    self._require_stored_identity(message_id=message_id)
                    connection.execute("DELETE FROM applications WHERE message_id = ?", (message_id,))
                    connection.execute("DELETE FROM messages WHERE message_id = ?", (message_id,))
                connection.execute(
                    "UPDATE internal_observations SET event_json=NULL WHERE state='applied'"
                    " AND observation_id IN (SELECT co.observation_id FROM compacted_observations co"
                    " JOIN compactions c USING(compaction_id) WHERE c.state='committed')"
                )
                connection.execute("RELEASE operation")
            except BaseException:
                connection.execute("ROLLBACK TO operation")
                connection.execute("RELEASE operation")
                raise

        await self._run(_write)
        await self._run_on(
            executor=self._executor,
            operation=lambda: self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(),
        )

    async def recover(
        self,
        *,
        transfer: RecoveryTransferDAO,
        principal: MessagePrincipalDAO,
    ) -> RecoveryOutcomeDAO:
        """Commit one owner-confirmed recovery transfer once.

        Generation recovery never edits submission_json,
        original_target_json, digest, message_id or the original sender. A
        completed transfer_id returns its original outcome; a changed
        transfer conflicts. Only one transfer per message/destination
        generation is admitted. A matching applying record must be
        reconciled at startup first; a matching applied/cancelled record
        returns its terminal receipt without re-execution; a matching
        retained pending record is re-activated under the current
        generation with its original identity untouched.

        Raises:
            MessageAdmissionError: Conflict, foreign principal, changed
                transfer or unreconciled applying state.
            MessageStoreError: The transfer commit cannot be confirmed.
        """
        if self._closed:
            raise MessageStoreError()
        return await self._run(lambda: self._recover_tx(transfer=transfer, principal=principal))

    def _recover_tx(
        self,
        *,
        transfer: RecoveryTransferDAO,
        principal: MessagePrincipalDAO,
    ) -> RecoveryOutcomeDAO:
        """Run the complete recovery transfer transaction on the store worker."""
        connection = self._connection
        connection.execute("SAVEPOINT operation")
        try:
            outcome = self._recover_in_transaction(transfer=transfer, principal=principal)
            connection.execute("RELEASE operation")
            return outcome
        except BaseException:
            connection.execute("ROLLBACK TO operation")
            connection.execute("RELEASE operation")
            raise

    def _recover_in_transaction(
        self,
        *,
        transfer: RecoveryTransferDAO,
        principal: MessagePrincipalDAO,
    ) -> RecoveryOutcomeDAO:
        """Decide replay/conflict/new transfer inside the open transaction."""
        if not self._durable:
            raise MessageAdmissionError(error=MessageErrorDAO(code="unsupported"))
        if principal.kind != "human":
            raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized"))
        existing = self._connection.execute(
            "SELECT outcome_json, transfer_json, confirmed_by FROM recovery_transfers WHERE transfer_id = ?",
            (transfer.transfer_id,),
        ).fetchone()
        if existing is not None:
            if existing[2] != principal.model_dump_json():
                raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized"))
            if existing[1] != transfer.model_dump_json():
                raise MessageAdmissionError(
                    error=MessageErrorDAO(code="conflict", message_id=transfer.original.message_id)
                )
            return RecoveryOutcomeDAO.model_validate_json(existing[0])
        return self._commit_new_transfer(transfer=transfer, principal=principal)

    def _commit_new_transfer(
        self,
        *,
        transfer: RecoveryTransferDAO,
        principal: MessagePrincipalDAO,
    ) -> RecoveryOutcomeDAO:
        """Validate and commit one new transfer inside the open transaction."""
        message_id = transfer.original.message_id
        exists = self._connection.execute(
            "SELECT 1 FROM identity WHERE message_id=?", (message_id,)
        ).fetchone()
        if exists is not None:
            self._require_stored_identity(message_id=message_id)
        identity_row = self._connection.execute(
            "SELECT principal_json, state, execution_generation, digest, original_target_json"
            " FROM identity WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if identity_row is None:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="recovery_required", message_id=message_id)
            )
        principal_json, state, from_generation, stored_digest, target_json = identity_row
        if MessagePrincipalDAO.model_validate_json(principal_json) != transfer.original_sender:
            raise MessageAdmissionError(error=MessageErrorDAO(code="unauthorized", message_id=message_id))
        digest = _submission_digest(submission=transfer.original, principal=transfer.original_sender)
        if (
            digest != transfer.original_digest
            or digest != stored_digest
            or transfer.original.target != MessageAddressDAO.model_validate_json(target_json)
        ):
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="recovery_required", message_id=message_id)
            )
        if state == "applying":
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="recovery_required", message_id=message_id)
            )
        generation = self._meta_value(key=_GENERATION_KEY)
        if transfer.destination != self._target:
            raise MessageAdmissionError(error=MessageErrorDAO(code="stale_generation", message_id=message_id))
        if (
            transfer.original.target.kind,
            transfer.original.target.session_id,
            transfer.original.target.channel_id,
        ) != (self._target.kind, self._target.session_id, self._target.channel_id):
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="recovery_required", message_id=message_id)
            )
        prior = self._connection.execute(
            "SELECT 1 FROM recovery_transfers WHERE message_id = ? AND to_generation = ?",
            (message_id, generation),
        ).fetchone()
        if prior is not None:
            raise MessageAdmissionError(error=MessageErrorDAO(code="conflict", message_id=message_id))
        if state == "accepted":
            self._require_capacity(submission=transfer.original, principal=transfer.original_sender)
            row = self._connection.execute(
                "UPDATE messages SET retained = 0, execution_generation = ?"
                " WHERE message_id = ? AND state = 'accepted' AND retained = 1",
                (generation, message_id),
            )
            if row.rowcount == 0:
                raise MessageAdmissionError(
                    error=MessageErrorDAO(code="recovery_required", message_id=message_id)
                )
            self._connection.execute(
                "UPDATE identity SET execution_generation = ? WHERE message_id = ?",
                (generation, message_id),
            )
        outcome = RecoveryOutcomeDAO(
            transfer_id=transfer.transfer_id,
            execution_generation=generation,
            receipt=self._receipt_for(message_id=message_id),
        )
        self._connection.execute(
            "INSERT INTO recovery_transfers("
            " transfer_id, message_id, original_digest, from_generation, to_generation,"
            " confirmed_by, confirmed_at, transfer_json, outcome_json)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                transfer.transfer_id,
                message_id,
                transfer.original_digest,
                from_generation,
                generation,
                principal.model_dump_json(),
                utcnow().isoformat(),
                transfer.model_dump_json(),
                outcome.model_dump_json(),
            ),
        )
        return outcome

    async def set_lifecycle(self, *, accepting: bool) -> None:
        """Persist the accepting/sealed lifecycle flag.

        Args:
            accepting (bool): True opens admission; False seals it.
        """
        if self._closed:
            raise MessageStoreError()
        value = _LIFECYCLE_ACCEPTING if accepting else _LIFECYCLE_SEALED

        def _write() -> None:
            try:
                self._connection.execute("SAVEPOINT operation")
                self._connection.execute("UPDATE meta SET value = ? WHERE key = ?", (value, _LIFECYCLE_KEY))
                self._connection.execute("RELEASE operation")
            except sqlite3.Error:
                self._connection.execute("ROLLBACK TO operation")
                self._connection.execute("RELEASE operation")
                raise MessageStoreError() from None

        await self._run(_write)
