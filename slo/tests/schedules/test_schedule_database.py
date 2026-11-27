"""Schema acceptance tests for the schedule database (111.a.1 A8)."""

import asyncio
from collections.abc import Callable
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from src.schedules.database import ScheduleDatabase, default_database_path


def _insert_row(connection: sqlite3.Connection, **overrides: object) -> None:
    """Insert one schedule row with the given column overrides.

    Args:
        connection (sqlite3.Connection): Open schema-bearing connection.
        **overrides (object): Column values replacing the valid defaults.
    """
    columns: dict[str, object] = {
        "id": "d0b0e5c8-0000-4000-8000-000000000001",
        "name": "Daily",
        "name_key": "daily",
        "prompt": "Summarise the repo",
        "trigger_kind": "interval",
        "run_at": None,
        "every_seconds": 60,
        "interval_anchor_at": None,
        "cron_expression": None,
        "timezone": None,
        "session_mode": "fresh",
        "session_reference": None,
        "coalescing_mode": "none",
        "coalescing_key": None,
        "misfire_grace_seconds": 300,
        "cwd": None,
        "model": None,
        "enabled": 1,
        "next_due_at": "2026-11-26T12:01:00.000Z",
        "created_at": "2026-11-26T12:00:00.000Z",
        "updated_at": "2026-11-26T12:00:00.000Z",
        "deleted_at": None,
    }
    columns.update(overrides)
    column_names: str = ", ".join(columns)
    placeholders: str = ", ".join(["?"] * len(columns))
    connection.execute(
        f"INSERT INTO schedules ({column_names}) VALUES ({placeholders})",
        tuple(columns.values()),
    )


def _open_raw_connection(*, db_path: Path) -> sqlite3.Connection:
    """Open a raw read connection for schema inspection.

    Args:
        db_path (Path): Path of the created schedules database.

    Returns:
        sqlite3.Connection: Connection with row access by name.
    """
    connection: sqlite3.Connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


async def test_fresh_database_has_schema_and_constraints(tmp_path: Path) -> None:
    """A fresh database creates both tables, six indexes, CHECK guards and user_version 3."""
    db_path: Path = tmp_path / "schedules" / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    async with database.transaction():
        pass
    await database.close()

    assert db_path.exists()
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(db_path.parent.stat().st_mode) == 0o700

    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        table_names: set[str] = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"schedules", "schedule_invocations"} <= table_names
        index_names: set[str] = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL"
            )
        }
        assert {
            "schedules_active_name",
            "schedules_due",
            "schedules_deleted",
            "schedule_invocations_status_created",
            "schedule_invocations_schedule_due",
            "schedule_invocations_created",
        } <= index_names
        user_version_row: sqlite3.Row = connection.execute("PRAGMA user_version").fetchone()
        assert int(user_version_row[0]) == 3
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("overrides", "forbidden_fragment"),
    [
        ({"enabled": 2}, "enabled"),
        ({"trigger_kind": "hourly"}, "trigger_kind"),
        ({"coalescing_key": "repo-watch"}, "coalescing"),
        ({"coalescing_mode": "latest_by_key"}, "coalescing"),
        ({"session_mode": "fresh", "session_reference": "release-prep"}, "session_mode"),
        ({"every_seconds": 14}, "every_seconds"),
        ({"trigger_kind": "interval", "every_seconds": None}, "trigger_kind"),
        ({"trigger_kind": "one_shot", "run_at": None}, "trigger_kind"),
        ({"trigger_kind": "cron", "cron_expression": "0 9 * * *"}, "trigger_kind"),
    ],
)
async def test_check_constraints_reject_invalid_rows(
    tmp_path: Path,
    overrides: dict[str, object],
    forbidden_fragment: str,
) -> None:
    """CHECK constraints reject writes that bypass the DAO validators."""
    db_path: Path = tmp_path / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    async with database.transaction():
        pass
    await database.close()

    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError) as rejected:
            _insert_row(connection, **overrides)
        assert forbidden_fragment in str(rejected.value)
    finally:
        connection.close()


def test_default_database_path_falls_back_to_the_owned_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EF111-06: with SLO_SCHEDULES_DIR unset the default path stays inside the test-owned SLO_HOME."""
    monkeypatch.delenv(name="SLO_SCHEDULES_DIR", raising=False)
    owned_home: Path = Path(os.environ["SLO_HOME"])

    resolved: Path = default_database_path()

    assert resolved.name == "schedules.db"
    assert resolved.is_relative_to(owned_home)


async def test_concurrent_commands_serialize_on_one_database(tmp_path: Path) -> None:
    """EF111-02: two concurrent commands on one database both commit instead of colliding."""
    database: ScheduleDatabase = ScheduleDatabase(db_path=tmp_path / "schedules.db")

    async def _create(*, name: str) -> None:
        async with database.transaction() as transaction:
            await transaction.execute(
                sql=(
                    "INSERT INTO schedules (id, name, name_key, prompt, trigger_kind, every_seconds,"
                    " session_mode, coalescing_mode, misfire_grace_seconds, enabled, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, 'interval', 60, 'fresh', 'none', 300, 1, ?, ?)"
                ),
                parameters=(
                    f"d0b0e5c8-0000-4000-8000-00000000000{len(name)}",
                    name,
                    name.lower(),
                    "Summarise the repo",
                    "2026-11-26T12:00:00.000Z",
                    "2026-11-26T12:00:00.000Z",
                ),
            )

    await asyncio.gather(_create(name="Alpha"), _create(name="Beta"))
    await database.close()

    connection: sqlite3.Connection = _open_raw_connection(db_path=tmp_path / "schedules.db")
    try:
        row_count: int = int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
        assert row_count == 2
    finally:
        connection.close()


async def test_cancellation_while_waiting_leaves_no_open_transaction(tmp_path: Path) -> None:
    """EF111-02: cancelling a command queued behind an open transaction leaves the database usable."""
    database: ScheduleDatabase = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    holder_started: asyncio.Event = asyncio.Event()
    release_holder: asyncio.Event = asyncio.Event()

    async def _hold() -> None:
        async with database.transaction() as transaction:
            await transaction.execute(
                sql=(
                    "INSERT INTO schedules (id, name, name_key, prompt, trigger_kind, every_seconds,"
                    " session_mode, coalescing_mode, misfire_grace_seconds, enabled, created_at, updated_at)"
                    " VALUES ('d0b0e5c8-0000-4000-8000-000000000001', 'Holder', 'holder', 'Summarise the repo',"
                    " 'interval', 60, 'fresh', 'none', 300, 1, '2026-11-26T12:00:00.000Z',"
                    " '2026-11-26T12:00:00.000Z')"
                ),
            )
            holder_started.set()
            await release_holder.wait()

    holder_task: asyncio.Task[None] = asyncio.create_task(_hold())
    await holder_started.wait()

    waiter_task: asyncio.Task[None] = asyncio.create_task(_create_named(database=database, name="Waiter"))
    await asyncio.sleep(0.05)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    release_holder.set()
    await holder_task

    # A fresh command must succeed and see only the committed holder row.
    await _create_named(database=database, name="After")
    await database.close()
    connection: sqlite3.Connection = _open_raw_connection(db_path=tmp_path / "schedules.db")
    try:
        names: list[str] = [str(row[0]) for row in connection.execute("SELECT name FROM schedules")]
        assert names == ["Holder", "After"]
    finally:
        connection.close()


async def test_cancellation_inside_a_transaction_rolls_back(tmp_path: Path) -> None:
    """EF111-02: cancelling the command inside its transaction rolls the write back."""
    database: ScheduleDatabase = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    wrote_row: asyncio.Event = asyncio.Event()

    async def _cancelled_writer() -> None:
        async with database.transaction() as transaction:
            await transaction.execute(
                sql=(
                    "INSERT INTO schedules (id, name, name_key, prompt, trigger_kind, every_seconds,"
                    " session_mode, coalescing_mode, misfire_grace_seconds, enabled, created_at, updated_at)"
                    " VALUES ('d0b0e5c8-0000-4000-8000-000000000001', 'Doomed', 'doomed', 'Summarise the repo',"
                    " 'interval', 60, 'fresh', 'none', 300, 1, '2026-11-26T12:00:00.000Z',"
                    " '2026-11-26T12:00:00.000Z')"
                ),
            )
            wrote_row.set()
            await asyncio.sleep(3600)

    writer_task: asyncio.Task[None] = asyncio.create_task(_cancelled_writer())
    await wrote_row.wait()
    writer_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer_task

    connection: sqlite3.Connection = _open_raw_connection(db_path=tmp_path / "schedules.db")
    try:
        row_count: int = int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
        assert row_count == 0
    finally:
        connection.close()
    await database.close()


async def _create_named(*, database: ScheduleDatabase, name: str) -> None:
    """Insert one valid schedule row through the caller's transaction."""
    async with database.transaction() as transaction:
        await transaction.execute(
            sql=(
                "INSERT INTO schedules (id, name, name_key, prompt, trigger_kind, every_seconds,"
                " session_mode, coalescing_mode, misfire_grace_seconds, enabled, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'interval', 60, 'fresh', 'none', 300, 1, ?, ?)"
            ),
            parameters=(
                f"d0b0e5c8-0000-4000-8000-{abs(hash(name)) % 10**12:012d}",
                name,
                name.lower(),
                "Summarise the repo",
                "2026-11-26T12:00:00.000Z",
                "2026-11-26T12:00:00.000Z",
            ),
        )


async def test_body_exception_rolls_back_and_reads_back(tmp_path: Path) -> None:
    """EF111-02: an exception inside the transaction rolls back; a later read sees no row."""
    db_path: Path = tmp_path / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)

    with pytest.raises(RuntimeError, match="planned failure"):
        async with database.transaction() as transaction:
            await transaction.execute(
                sql=(
                    "INSERT INTO schedules (id, name, name_key, prompt, trigger_kind, every_seconds,"
                    " session_mode, coalescing_mode, misfire_grace_seconds, enabled, created_at, updated_at)"
                    " VALUES ('d0b0e5c8-0000-4000-8000-000000000009', 'Doomed', 'doomed', 'Summarise the repo',"
                    " 'interval', 60, 'fresh', 'none', 300, 1, '2026-11-26T12:00:00.000Z',"
                    " '2026-11-26T12:00:00.000Z')"
                ),
            )
            raise RuntimeError("planned failure")

    await database.close()
    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        row_count: int = int(connection.execute("SELECT count(*) FROM schedules").fetchone()[0])
        assert row_count == 0
    finally:
        connection.close()


async def test_partial_index_predicates_match_the_contract(tmp_path: Path) -> None:
    """EF111-05: schedules_deleted indexes deleted rows only; schedules_due indexes active rows only."""
    db_path: Path = tmp_path / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    async with database.transaction():
        pass
    await database.close()

    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        definitions: dict[str, str] = {
            str(row["name"]): str(row["sql"])
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
        assert "WHERE deleted_at IS NOT NULL" in definitions["schedules_deleted"]
        assert "WHERE deleted_at IS NULL" in definitions["schedules_due"]
        assert "WHERE deleted_at IS NULL" in definitions["schedules_active_name"]
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("key_override", "rejected"),
    [
        ({"coalescing_key": None}, True),
        ({"coalescing_key": ""}, True),
        ({"coalescing_key": "repo-watch"}, False),
    ],
)
async def test_latest_by_key_rejects_missing_and_empty_keys(
    tmp_path: Path, key_override: dict[str, object], rejected: bool
) -> None:
    """EF111-05: a NULL or empty coalescing key is rejected for latest_by_key, even with SQL NULL logic."""
    db_path: Path = tmp_path / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    async with database.transaction():
        pass
    await database.close()

    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        overrides: dict[str, object] = {
            "session_mode": "continuous",
            "session_reference": "release-prep",
            "coalescing_mode": "latest_by_key",
        }
        overrides.update(key_override)
        if rejected:
            with pytest.raises(sqlite3.IntegrityError):
                _insert_row(connection, **overrides)
        else:
            _insert_row(connection, **overrides)
    finally:
        connection.close()


async def test_valid_row_persists_and_name_index_rejects_duplicate(tmp_path: Path) -> None:
    """A valid row persists and the unique active-name index rejects a second row."""
    db_path: Path = tmp_path / "schedules.db"
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    async with database.transaction():
        pass
    await database.close()

    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        _insert_row(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_row(connection, id="d0b0e5c8-0000-4000-8000-000000000002")
    finally:
        connection.close()


_V1_INVOCATIONS_DDL: str = """
        CREATE TABLE schedule_invocations (
          id                    TEXT PRIMARY KEY,
          schedule_id           TEXT NOT NULL REFERENCES schedules (id),
          due_at                TEXT NOT NULL,
          status                TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'skipped', 'failed')),
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
          created_at            TEXT NOT NULL,
          delivered_at          TEXT,
          UNIQUE (schedule_id, due_at),
          CHECK ((status = 'skipped') = (skip_reason IS NOT NULL)),
          CHECK ((status = 'failed') = (failure_reason IS NOT NULL)),
          CHECK (channel_message_id IS NULL OR channel_message_id = id),
          CHECK (status <> 'delivered' OR (channel_message_id IS NOT NULL AND delivered_at IS NOT NULL))
        )
        """


_V2_INVOCATIONS_DDL: str = """
        CREATE TABLE schedule_invocations (
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
          CHECK ((status = 'failed') = (failure_reason IS NOT NULL)),
          CHECK (channel_message_id IS NULL OR channel_message_id = id),
          CHECK (status <> 'delivered' OR (channel_message_id IS NOT NULL AND delivered_at IS NOT NULL)),
          CHECK (status <> 'completed' OR (run_exit_code IS NOT NULL AND delivered_at IS NOT NULL))
        )
        """


_SCHEDULE_ID: str = "d0b0e5c8-0000-4000-8000-000000000001"
_RECIPIENT: str = "01234567-89ab-cdef-0123-456789abcdef"

# Invocation states every pre-M3 database can hold (111.a.2 channel states).
_CHANNEL_STATE_ROWS: tuple[dict[str, object], ...] = (
    {
        "id": "inv-pending",
        "due_at": "2026-11-26T12:01:00.000Z",
        "status": "pending",
    },
    {
        "id": "inv-delivered",
        "due_at": "2026-11-26T12:02:00.000Z",
        "status": "delivered",
        "recipient_session_id": _RECIPIENT,
        "channel_message_id": "inv-delivered",
        "accepted_at": "2026-11-26T12:02:30.000Z",
        "reply_message_id": "msg-reply-1",
        "outcome_reconciled_at": "2026-11-26T12:03:00.000Z",
        "delivered_at": "2026-11-26T12:02:10.000Z",
    },
    {
        "id": "inv-superseded",
        "due_at": "2026-11-26T12:04:00.000Z",
        "status": "delivered",
        "recipient_session_id": _RECIPIENT,
        "channel_message_id": "inv-superseded",
        "cancelled_at": "2026-11-26T12:04:40.000Z",
        "cancel_reason": "superseded",
        "outcome_reconciled_at": "2026-11-26T12:05:00.000Z",
        "channel_row_gone_at": "2026-11-26T12:06:00.000Z",
        "delivered_at": "2026-11-26T12:04:10.000Z",
    },
    {
        "id": "inv-skipped",
        "due_at": "2026-11-26T12:07:00.000Z",
        "status": "skipped",
        "skip_reason": "misfire",
    },
    {
        "id": "inv-failed",
        "due_at": "2026-11-26T12:08:00.000Z",
        "status": "failed",
        "failure_reason": "recipient_closed",
        "recipient_session_id": _RECIPIENT,
    },
)

# Run states only a v2 (M2) database can hold.
_RUN_STATE_ROWS: tuple[dict[str, object], ...] = (
    {
        "id": "inv-completed",
        "due_at": "2026-11-26T12:09:00.000Z",
        "status": "completed",
        "recipient_session_id": "aaaaaaaa-0000-4000-8000-000000000001",
        "run_exit_code": 0,
        "delivered_at": "2026-11-26T12:10:00.000Z",
    },
    {
        "id": "inv-run-failed",
        "due_at": "2026-11-26T12:11:00.000Z",
        "status": "run_failed",
        "recipient_session_id": "aaaaaaaa-0000-4000-8000-000000000002",
        "run_exit_code": 2,
        "delivered_at": "2026-11-26T12:12:00.000Z",
    },
    {
        "id": "inv-running",
        "due_at": "2026-11-26T12:13:00.000Z",
        "status": "running",
        "recipient_session_id": "aaaaaaaa-0000-4000-8000-000000000003",
    },
)


def _insert_invocations(*, connection: sqlite3.Connection, rows: tuple[dict[str, object], ...]) -> None:
    """Insert invocation rows for the seeded schedule, one statement per row.

    Args:
        connection (sqlite3.Connection): Open connection on a pre-M3 schema.
        rows (tuple[dict[str, object], ...]): Column values per row; schedule id
            and created_at are supplied here.
    """
    for row in rows:
        columns: dict[str, object] = {
            "schedule_id": _SCHEDULE_ID,
            "created_at": "2026-11-26T12:00:00.000Z",
            **row,
        }
        connection.execute(
            f"INSERT INTO schedule_invocations ({', '.join(columns)})"
            f" VALUES ({', '.join(['?'] * len(columns))})",
            tuple(columns.values()),
        )


def _create_legacy_database(
    *, db_path: Path, user_version: int, invocations_ddl: str, rows: tuple[dict[str, object], ...]
) -> None:
    """Create a pre-M3 database with one schedule and the given invocation rows.

    Args:
        db_path (Path): Path of the database file to create.
        user_version (int): The legacy schema version to stamp.
        invocations_ddl (str): That version's schedule_invocations definition.
        rows (tuple[dict[str, object], ...]): The invocation rows to seed.
    """
    connection: sqlite3.Connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(f"PRAGMA user_version={user_version}")
        connection.execute(ScheduleDatabase._DDL[0])
        connection.execute(invocations_ddl)
        for statement in ScheduleDatabase._DDL[2:]:
            connection.execute(statement)
        _insert_row(connection)
        _insert_invocations(connection=connection, rows=rows)
        connection.commit()
    finally:
        connection.close()


def _create_v1_database(*, db_path: Path) -> None:
    """Create a v1 (pre-M2) database holding every channel state.

    Args:
        db_path (Path): Path of the database file to create.
    """
    _create_legacy_database(
        db_path=db_path, user_version=1, invocations_ddl=_V1_INVOCATIONS_DDL, rows=_CHANNEL_STATE_ROWS
    )


def _create_v2_database(*, db_path: Path) -> None:
    """Create a v2 (M2) database holding every channel and run state.

    Args:
        db_path (Path): Path of the database file to create.
    """
    _create_legacy_database(
        db_path=db_path,
        user_version=2,
        invocations_ddl=_V2_INVOCATIONS_DDL,
        rows=_CHANNEL_STATE_ROWS + _RUN_STATE_ROWS,
    )


def _invocation_snapshot(*, db_path: Path) -> dict[str, dict[str, object]]:
    """Read every invocation row, every column, keyed by invocation id.

    Args:
        db_path (Path): The database file to read.

    Returns:
        dict[str, dict[str, object]]: Column values per invocation id.
    """
    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        rows: list[sqlite3.Row] = connection.execute("SELECT * FROM schedule_invocations").fetchall()
    finally:
        connection.close()
    return {str(row["id"]): dict(row) for row in rows}


def _schema_facts(*, db_path: Path) -> tuple[int, set[str]]:
    """Read the schema version and the named index set of one database file.

    Args:
        db_path (Path): The database file to read.

    Returns:
        tuple[int, set[str]]: ``user_version`` and every explicitly named index.
    """
    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        version: int = int(connection.execute("PRAGMA user_version").fetchone()[0])
        indexes: set[str] = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
    finally:
        connection.close()
    return version, indexes


async def _open_and_close(*, db_path: Path) -> None:
    """Open one ScheduleDatabase transaction (running any migration) and close it.

    Args:
        db_path (Path): The database file to open.
    """
    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    try:
        async with database.transaction():
            pass
    finally:
        await database.close()


async def _current_index_names(*, tmp_path: Path) -> set[str]:
    """Create a fresh current-schema database and return its named indexes.

    Args:
        tmp_path (Path): The test's temporary directory.

    Returns:
        set[str]: The index names the current schema owns.
    """
    fresh_path: Path = tmp_path / "fresh" / "schedules.db"
    await _open_and_close(db_path=fresh_path)
    return _schema_facts(db_path=fresh_path)[1]


def _assert_run_failed_reason_allowed(*, db_path: Path) -> None:
    """M3: a run_failed row may carry its recovery reason; a delivered row may not.

    Args:
        db_path (Path): The migrated database file.
    """
    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    try:
        connection.execute(
            "INSERT INTO schedule_invocations (id, schedule_id, due_at, status,"
            " failure_reason, created_at, delivered_at)"
            f" VALUES ('inv-new', '{_SCHEDULE_ID}', '2026-11-26T13:00:00.000Z', 'run_failed',"
            " 'run_timeout', '2026-11-26T12:00:00.000Z', '2026-11-26T13:00:00.000Z')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO schedule_invocations (id, schedule_id, due_at, status,"
                " failure_reason, channel_message_id, created_at, delivered_at)"
                f" VALUES ('inv-bad', '{_SCHEDULE_ID}', '2026-11-26T13:01:00.000Z', 'delivered',"
                " 'not-allowed', 'inv-bad', '2026-11-26T12:00:00.000Z', '2026-11-26T13:01:00.000Z')"
            )
    finally:
        connection.rollback()
        connection.close()


async def test_m2_m3_migration_rebuilds_invocations_to_the_current_shape(
    tmp_path: Path,
) -> None:
    """M2+M3 (FRR111-01): a populated v1 database keeps every row and column
    value in every channel state; run_exit_code is NULL; the current indexes
    and schema version are in place."""
    db_path: Path = tmp_path / "schedules.db"
    _create_v1_database(db_path=db_path)
    before: dict[str, dict[str, object]] = _invocation_snapshot(db_path=db_path)

    await _open_and_close(db_path=db_path)

    after: dict[str, dict[str, object]] = _invocation_snapshot(db_path=db_path)
    assert set(after) == set(before) == {str(row["id"]) for row in _CHANNEL_STATE_ROWS}
    for invocation_id, old_row in before.items():
        assert after[invocation_id] == {**old_row, "run_exit_code": None}, invocation_id
    version, indexes = _schema_facts(db_path=db_path)
    assert version == 3
    assert indexes == await _current_index_names(tmp_path=tmp_path)
    _assert_run_failed_reason_allowed(db_path=db_path)


async def test_m2_m3_migration_preserves_populated_v2_rows(tmp_path: Path) -> None:
    """FRR111-01: a populated v2 (M2) database migrates with every column
    value intact in completed, run_failed, running and every channel state —
    ids, reasons, exit codes, timestamps — plus indexes and schema version."""
    db_path: Path = tmp_path / "schedules.db"
    _create_v2_database(db_path=db_path)
    before: dict[str, dict[str, object]] = _invocation_snapshot(db_path=db_path)

    await _open_and_close(db_path=db_path)

    after: dict[str, dict[str, object]] = _invocation_snapshot(db_path=db_path)
    assert after == before
    assert after["inv-completed"]["run_exit_code"] == 0
    assert after["inv-run-failed"]["run_exit_code"] == 2
    assert after["inv-failed"]["failure_reason"] == "recipient_closed"
    assert after["inv-superseded"]["cancel_reason"] == "superseded"
    version, indexes = _schema_facts(db_path=db_path)
    assert version == 3
    assert indexes == await _current_index_names(tmp_path=tmp_path)
    _assert_run_failed_reason_allowed(db_path=db_path)


def _obstruct_before_copy(*, connection: sqlite3.Connection) -> None:
    """A stale staging table from an interrupted attempt fails the rebuild's first step.

    Args:
        connection (sqlite3.Connection): Raw connection on the legacy database.
    """
    connection.execute("CREATE TABLE schedule_invocations_m3 (id TEXT PRIMARY KEY)")


def _obstruct_after_drop(*, connection: sqlite3.Connection) -> None:
    """A view over the old table fails the rename after the old table is dropped.

    Args:
        connection (sqlite3.Connection): Raw connection on the legacy database.
    """
    connection.execute("CREATE VIEW invocation_ids AS SELECT id FROM schedule_invocations")


@pytest.mark.parametrize(
    "obstruct",
    [_obstruct_before_copy, _obstruct_after_drop],
    ids=["fails-before-copy", "fails-after-drop"],
)
async def test_failed_migration_leaves_the_original_database_usable(
    tmp_path: Path, obstruct: Callable[..., None]
) -> None:
    """FRR111-01: a migration failure — before the copy or after the destructive
    drop — rolls back: every v2 row, the indexes and user_version 2 survive, and
    the same ScheduleDatabase opens cleanly once the obstruction is gone."""
    db_path: Path = tmp_path / "schedules.db"
    _create_v2_database(db_path=db_path)
    connection: sqlite3.Connection = _open_raw_connection(db_path=db_path)
    obstruct(connection=connection)
    connection.commit()
    connection.close()
    before: dict[str, dict[str, object]] = _invocation_snapshot(db_path=db_path)
    facts_before: tuple[int, set[str]] = _schema_facts(db_path=db_path)

    database: ScheduleDatabase = ScheduleDatabase(db_path=db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            async with database.transaction():
                pass

        assert _invocation_snapshot(db_path=db_path) == before
        assert _schema_facts(db_path=db_path) == facts_before
        assert facts_before[0] == 2

        connection = _open_raw_connection(db_path=db_path)
        connection.execute("DROP TABLE IF EXISTS schedule_invocations_m3")
        connection.execute("DROP VIEW IF EXISTS invocation_ids")
        connection.commit()
        connection.close()
        async with database.transaction() as transaction:
            migrated: list[sqlite3.Row] = await transaction.fetch_all(
                sql="SELECT id, run_exit_code FROM schedule_invocations WHERE id = 'inv-completed'"
            )
    finally:
        await database.close()

    assert [tuple(row) for row in migrated] == [("inv-completed", 0)]
    assert _invocation_snapshot(db_path=db_path) == before
    assert _schema_facts(db_path=db_path)[0] == 3
