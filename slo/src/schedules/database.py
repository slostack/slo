"""`schedules.db` — file, pragmas, schema creation and one-transaction discipline."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Protocol, TypeVar

from config.cfg import cfg as _cfg

__all__ = ["ScheduleDatabase", "ScheduleTransaction", "format_instant", "parse_instant"]

_FILE_MODE: int = 0o600
_DIR_MODE: int = 0o700
_BUSY_TIMEOUT_MS: int = 5000
_SCHEMA_VERSION: int = 3
_DATABASE_NAME: str = "schedules.db"

# Rebuild target (111.a.3 §4.3 M2; FIR111-06 reason rule): the current
# schedule_invocations definition under a staging name. M3 relaxes the
# failure_reason CHECK so a run_failed row may carry its recovery reason.
_INVOCATIONS_TABLE_DDL: str = """
        CREATE TABLE schedule_invocations_m3 (
          id                    TEXT PRIMARY KEY,
          schedule_id           TEXT NOT NULL REFERENCES schedules (id),
          due_at                TEXT NOT NULL,
          status                TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'skipped', 'failed', 'running', 'completed', 'run_failed')),
          skip_reason           TEXT CHECK (skip_reason IN ('schedule_disabled', 'schedule_deleted', 'misfire')),
          failure_reason        TEXT,
          recipient_session_id  TEXT,
          channel_message_id    TEXT,
          accepted_at           TEXT,
          cancelled_at          TEXT,
          cancel_reason         TEXT,
          reply_message_id      TEXT,
          outcome_reconciled_at TEXT,
          channel_row_gone_at   TEXT,
          run_exit_code         INTEGER,
          created_at            TEXT NOT NULL,
          delivered_at          TEXT,
          UNIQUE (schedule_id, due_at),
          CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)),
          CHECK (failure_reason IS NULL OR status IN ('failed', 'run_failed')),
          CHECK (status <> 'failed' OR failure_reason IS NOT NULL),
          CHECK (channel_message_id IS NULL OR channel_message_id = id),
          CHECK (status <> 'delivered' OR (channel_message_id IS NOT NULL AND delivered_at IS NOT NULL)),
          CHECK (status <> 'completed' OR (run_exit_code IS NOT NULL AND delivered_at IS NOT NULL))
        )
        """

_RESULT = TypeVar("_RESULT")
_RUN_RESULT = TypeVar("_RUN_RESULT")


class OffLoopRunner(Protocol):
    """Runs one blocking callable on the database's dedicated worker thread."""

    def __call__(self, operation: Callable[[], _RUN_RESULT]) -> Awaitable[_RUN_RESULT]:
        """Execute the operation off the event loop.

        Args:
            operation (Callable[[], _RUN_RESULT]): The blocking callable.

        Returns:
            Awaitable[_RUN_RESULT]: The awaited result.
        """
        ...


def format_instant(*, value: datetime) -> str:
    """Render one UTC instant in the fixed-width text form used by every timestamp column.

    Args:
        value (datetime): The instant to render; naive values are rejected.

    Returns:
        str: ``YYYY-MM-DDTHH:MM:SS.mmmZ`` in UTC, truncated to milliseconds.

    Raises:
        ValueError: When the value is naive.
    """
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_instant(*, text: str) -> datetime:
    """Parse one stored timestamp column back into an aware UTC datetime.

    Args:
        text (str): The fixed-width ``YYYY-MM-DDTHH:MM:SS.mmmZ`` text.

    Returns:
        datetime: The timezone-aware UTC instant.
    """
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def default_database_path() -> Path:
    """Resolve the default `schedules.db` path.

    Uses ``SLO_SCHEDULES_DIR`` when set, else ``$SLO_HOME/schedules``.

    Returns:
        Path: The database file path.
    """
    schedules_dir: str | None = _cfg("SLO_SCHEDULES_DIR")
    if schedules_dir:
        return Path(schedules_dir) / _DATABASE_NAME
    slo_home: str | None = _cfg("SLO_HOME")
    if slo_home:
        return Path(slo_home) / "schedules" / _DATABASE_NAME
    return Path.home() / ".slo" / "schedules" / _DATABASE_NAME


class ScheduleTransaction:
    """One open ``BEGIN IMMEDIATE`` transaction handed to repository methods.

    Every statement runs on the owning database's dedicated worker thread, so
    blocking SQLite work stays off the event loop for the whole transaction
    lifetime (111.a.1 §5.9).
    """

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        run_operation: OffLoopRunner,
    ) -> None:
        """Hold the open connection and the off-loop runner for the caller's command.

        Args:
            connection (sqlite3.Connection): The connection inside the transaction.
            run_operation (Callable[...]): The database's runner that executes one
                blocking callable on the dedicated worker thread.
        """
        self._connection: sqlite3.Connection = connection
        self._run_operation: OffLoopRunner = run_operation

    async def execute(
        self,
        *,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> sqlite3.Cursor:
        """Run one SQL statement inside the transaction.

        Args:
            sql (str): The SQL statement.
            parameters (tuple[object, ...]): Bound parameters.

        Returns:
            sqlite3.Cursor: The executed cursor.
        """
        statement: Callable[[], sqlite3.Cursor] = lambda: self._connection.execute(sql, parameters)
        return await self._run_operation(statement)

    async def fetch_one(
        self,
        *,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> Optional[sqlite3.Row]:
        """Run one statement and return its first row.

        Args:
            sql (str): The SQL statement.
            parameters (tuple[object, ...]): Bound parameters.

        Returns:
            Optional[sqlite3.Row]: The first row, or None when the result is empty.
        """
        statement: Callable[[], Optional[sqlite3.Row]] = lambda: self._connection.execute(
            sql, parameters
        ).fetchone()
        return await self._run_operation(statement)

    async def fetch_all(
        self,
        *,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> list[sqlite3.Row]:
        """Run one statement and return every row.

        Args:
            sql (str): The SQL statement.
            parameters (tuple[object, ...]): Bound parameters.

        Returns:
            list[sqlite3.Row]: The result rows in cursor order.
        """
        statement: Callable[[], list[sqlite3.Row]] = lambda: self._connection.execute(
            sql, parameters
        ).fetchall()
        return await self._run_operation(statement)

    async def commit(self) -> None:
        """Commit the transaction."""
        await self._run_operation(self._connection.commit)

    async def rollback(self) -> None:
        """Roll the transaction back."""
        await self._run_operation(self._connection.rollback)


class ScheduleDatabase:
    """Owns the process-local connection to `schedules.db` and its schema."""

    _DDL: tuple[str, ...] = (
        """
        CREATE TABLE IF NOT EXISTS schedules (
          id                    TEXT PRIMARY KEY,
          name                  TEXT NOT NULL CHECK (length(trim(name)) > 0),
          name_key              TEXT NOT NULL,
          prompt                TEXT NOT NULL CHECK (length(prompt) BETWEEN 1 AND 65536),
          trigger_kind          TEXT NOT NULL CHECK (trigger_kind IN ('one_shot', 'interval', 'cron')),
          run_at                TEXT,
          every_seconds         INTEGER CHECK (every_seconds IS NULL OR every_seconds >= 15),
          interval_anchor_at    TEXT,
          cron_expression       TEXT,
          timezone              TEXT,
          session_mode          TEXT NOT NULL CHECK (session_mode IN ('fresh', 'continuous')),
          session_reference     TEXT,
          coalescing_mode       TEXT NOT NULL DEFAULT 'none' CHECK (coalescing_mode IN ('none', 'latest_by_key')),
          coalescing_key        TEXT,
          misfire_grace_seconds INTEGER NOT NULL DEFAULT 300 CHECK (misfire_grace_seconds >= 0),
          cwd                   TEXT,
          model                 TEXT,
          enabled               INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
          next_due_at           TEXT,
          created_at            TEXT NOT NULL,
          updated_at            TEXT NOT NULL,
          deleted_at            TEXT,
          CHECK (
            (trigger_kind = 'one_shot' AND run_at IS NOT NULL AND every_seconds IS NULL
               AND cron_expression IS NULL AND timezone IS NULL AND interval_anchor_at IS NULL)
            OR (trigger_kind = 'interval' AND every_seconds IS NOT NULL AND run_at IS NULL
               AND cron_expression IS NULL AND timezone IS NULL)
            OR (trigger_kind = 'cron' AND cron_expression IS NOT NULL AND timezone IS NOT NULL
               AND run_at IS NULL AND every_seconds IS NULL AND interval_anchor_at IS NULL)
          ),
          CHECK (session_mode = 'continuous'
                 OR (session_reference IS NULL AND coalescing_mode = 'none' AND coalescing_key IS NULL)),
          CHECK ((coalescing_mode = 'none' AND coalescing_key IS NULL)
                 OR (coalescing_mode = 'latest_by_key' AND coalescing_key IS NOT NULL
                     AND length(coalescing_key) > 0))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schedule_invocations (
          id                    TEXT PRIMARY KEY,
          schedule_id           TEXT NOT NULL REFERENCES schedules (id),
          due_at                TEXT NOT NULL,
          status                TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'skipped', 'failed', 'running', 'completed', 'run_failed')),
          skip_reason           TEXT CHECK (skip_reason IN ('schedule_disabled', 'schedule_deleted', 'misfire')),
          failure_reason        TEXT,
          recipient_session_id  TEXT,
          channel_message_id    TEXT,
          accepted_at           TEXT,
          cancelled_at          TEXT,
          cancel_reason         TEXT,
          reply_message_id      TEXT,
          outcome_reconciled_at TEXT,
          channel_row_gone_at   TEXT,
          run_exit_code         INTEGER,
          created_at            TEXT NOT NULL,
          delivered_at          TEXT,
          UNIQUE (schedule_id, due_at),
          CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)),
          CHECK (failure_reason IS NULL OR status IN ('failed', 'run_failed')),
          CHECK (status <> 'failed' OR failure_reason IS NOT NULL),
          CHECK (channel_message_id IS NULL OR channel_message_id = id),
          CHECK (status <> 'delivered' OR (channel_message_id IS NOT NULL AND delivered_at IS NOT NULL)),
          CHECK (status <> 'completed' OR (run_exit_code IS NOT NULL AND delivered_at IS NOT NULL))
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS schedules_active_name ON schedules (name_key) WHERE deleted_at IS NULL",
        "CREATE INDEX IF NOT EXISTS schedules_due ON schedules (enabled, next_due_at) WHERE deleted_at IS NULL",
        "CREATE INDEX IF NOT EXISTS schedules_deleted ON schedules (deleted_at) WHERE deleted_at IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS schedule_invocations_status_created"
        " ON schedule_invocations (status, created_at)",
        "CREATE INDEX IF NOT EXISTS schedule_invocations_schedule_due"
        " ON schedule_invocations (schedule_id, due_at)",
        "CREATE INDEX IF NOT EXISTS schedule_invocations_created ON schedule_invocations (created_at)",
    )

    def __init__(self, *, db_path: Path) -> None:
        """Prepare (not open) a database bound to one file path.

        Args:
            db_path (Path): The SQLite file path; the parent directory is created
                mode 0700 and the file mode 0600 on first open.
        """
        self._db_path: Path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._connection_lock: threading.Lock = threading.Lock()
        self._transaction_gate: asyncio.Lock = asyncio.Lock()
        self._worker: Optional[ThreadPoolExecutor] = None

    @property
    def db_path(self) -> Path:
        """Return the bound database file path.

        Returns:
            Path: The path this database was constructed with.
        """
        return self._db_path

    async def _run(self, operation: Callable[[], _RESULT]) -> _RESULT:
        """Run one blocking operation on the dedicated worker thread.

        Args:
            operation (Callable[[], _RESULT]): The blocking callable.

        Returns:
            _RESULT: The operation's result.
        """
        if self._worker is None:
            self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="schedule-db")
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, operation)

    def _open_connection(self) -> sqlite3.Connection:
        """Create the file and open the connection with its pragmas and schema.

        Returns:
            sqlite3.Connection: The open connection.

        Raises:
            RuntimeError: When the database path is not a regular file.
            sqlite3.Error: When the pragmas, schema or migration fail; the
                half-opened connection is closed and the file keeps its
                pre-open state (the migration transaction rolled back).
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        if self._db_path.exists() and not stat.S_ISREG(self._db_path.lstat().st_mode):
            raise RuntimeError(f"Schedule database path is not a regular file: {self._db_path}")
        connection: sqlite3.Connection = sqlite3.connect(
            str(self._db_path),
            timeout=_BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            os.chmod(path=self._db_path, mode=_FILE_MODE)
            self._create_schema(connection=connection)
        except BaseException:
            connection.close()
            raise
        return connection

    def _create_schema(self, *, connection: sqlite3.Connection) -> None:
        """Create both tables and all indexes when the file is new.

        Args:
            connection (sqlite3.Connection): The connection whose schema to create.
        """
        version_row: sqlite3.Row = connection.execute("PRAGMA user_version").fetchone()
        if int(version_row["user_version"]) >= _SCHEMA_VERSION:
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            self._migrate(connection=connection)
            for statement in self._DDL:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    def _migrate(self, *, connection: sqlite3.Connection) -> None:
        """Apply in-place migration steps to bring the schema to the target version.

        Args:
            connection (sqlite3.Connection): The connection inside the open transaction.
        """
        version_row: sqlite3.Row = connection.execute("PRAGMA user_version").fetchone()
        if int(version_row["user_version"]) < _SCHEMA_VERSION:
            self._migrate_invocations_to_current(connection=connection)

    def _migrate_invocations_to_current(self, *, connection: sqlite3.Connection) -> None:
        """Rebuild schedule_invocations to the current definition.

        M2 (111.a.3 §4.3) added the run statuses and ``run_exit_code``; M3
        (FIR111-06) allows ``failure_reason`` on ``run_failed`` rows so restart
        recovery can record its reason. Expands only: every existing row keeps
        every column value (FRR111-01); a v1 source has no ``run_exit_code``
        and gets NULL. The rebuild runs inside the
        caller's transaction, so a failure rolls back cleanly.

        Args:
            connection (sqlite3.Connection): The connection inside the open transaction.
        """
        table_exists: bool = bool(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master" " WHERE type='table' AND name='schedule_invocations'"
            ).fetchone()[0]
        )
        if not table_exists:
            return
        # Version-aware copy: the source carries ``run_exit_code`` only from M2
        # (user_version 2) onward. A populated V2 database must keep every
        # existing column value, so the rebuild copies it when present; a V1
        # source has no such column and the rebuild supplies NULL.
        source_columns: set[str] = {
            row[1] for row in connection.execute("PRAGMA table_info(schedule_invocations)")
        }
        run_exit_code_column: str = "run_exit_code" if "run_exit_code" in source_columns else "NULL"
        connection.execute(_INVOCATIONS_TABLE_DDL)
        connection.execute(
            "INSERT INTO schedule_invocations_m3 ("
            "id, schedule_id, due_at, status, skip_reason, failure_reason, recipient_session_id,"
            " channel_message_id, accepted_at, cancelled_at, cancel_reason, reply_message_id,"
            " outcome_reconciled_at, channel_row_gone_at, run_exit_code, created_at, delivered_at)"
            " SELECT id, schedule_id, due_at, status, skip_reason, failure_reason,"
            " recipient_session_id, channel_message_id, accepted_at, cancelled_at,"
            " cancel_reason, reply_message_id, outcome_reconciled_at, channel_row_gone_at,"
            f" {run_exit_code_column}, created_at, delivered_at FROM schedule_invocations"
        )
        connection.execute("DROP TABLE schedule_invocations")
        connection.execute("ALTER TABLE schedule_invocations_m3 RENAME TO schedule_invocations")

    def _begin(self) -> ScheduleTransaction:
        """Open the connection if needed and begin one immediate transaction.

        Returns:
            ScheduleTransaction: The open transaction.

        Raises:
            RuntimeError: When the connection is already inside a transaction.
        """
        with self._connection_lock:
            if self._connection is None:
                self._connection = self._open_connection()
            if self._connection.in_transaction:
                raise RuntimeError("Schedule database is already inside a transaction")
            self._connection.execute("BEGIN IMMEDIATE")
            return ScheduleTransaction(connection=self._connection, run_operation=self._run)

    def _rollback_any_open_transaction(self) -> None:
        """Roll back a transaction the worker may have opened while its waiter was cancelled."""
        with self._connection_lock:
            if self._connection is not None and self._connection.in_transaction:
                self._connection.rollback()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ScheduleTransaction]:
        """Open one ``BEGIN IMMEDIATE`` transaction and commit or roll it back.

        Transaction lifetimes are serialised on an asyncio gate, so a second
        command waits for its turn instead of colliding on ``BEGIN IMMEDIATE``
        (EF111-02). A cancellation that lands while the worker is still opening
        the transaction rolls that transaction back before the gate is released.

        Yields:
            ScheduleTransaction: The open transaction for repository methods.
        """
        await self._transaction_gate.acquire()
        try:
            try:
                transaction: ScheduleTransaction = await self._run(self._begin)
            except BaseException:
                await self._run(self._rollback_any_open_transaction)
                raise
            try:
                yield transaction
            except BaseException:
                await transaction.rollback()
                raise
            else:
                await transaction.commit()
        finally:
            self._transaction_gate.release()

    async def close(self) -> None:
        """Close the connection and retire the worker thread."""
        if self._worker is not None:
            worker: ThreadPoolExecutor = self._worker
            self._worker = None
            worker.shutdown(wait=True)
        with self._connection_lock:
            if self._connection is not None:
                connection: sqlite3.Connection = self._connection
                self._connection = None
                connection.close()
