"""Daily purge job tests (111.a.5 A7; D25 dead-letter sweep; FIR111-07).

The registered job runs the schedule-row retention and sweeps the engine's
dead-letter rows, kept in the engine's own file, with the same 90-day cutoff;
the populated channel store is never touched.

The schedules database, the channels database and the honker engine are real.
Engine rows are seeded and backdated through a test-owned honker handle (the
same native library the engine uses) and read back only after the engine
closed; nothing replaces or reads the engine's private state.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import honker
from pydantic import BaseModel, ConfigDict, Field

from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.channel_delivery import ScheduleChannelSender
from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.workflows import PURGE_QUEUE, ScheduleEngine

_PURGE_TASK_NAME = "schedule-purge"
_PURGE_CRONTAB = "0 3 * * *"
_BOUND_SECONDS: float = 60.0
_RECIPIENT = UUID("01234567-89ab-cdef-0123-456789abcdef")


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


class PurgeStoresDAO(BaseModel):
    """The disposable stores one purge test seeds and reads back."""

    model_config = ConfigDict(frozen=True)

    schedules_db_path: Path = Field(description="The schedules database holding the schedule rows.")
    engine_db_path: Path = Field(
        description="The engine's own file holding its jobs, schedules and dead letters."
    )
    channel_db_path: Path = Field(description="The channels database the purge must never touch.")
    aged_invocation_id: UUID = Field(description="An invocation created 91 days ago; retention deletes it.")
    recent_invocation_id: UUID = Field(description="An invocation created now; retention keeps it.")


async def _seed_schedules(*, tmp_path: Path) -> PurgeStoresDAO:
    """Create one schedule with one aged and one recent invocation.

    Args:
        tmp_path (Path): The test directory.

    Returns:
        PurgeStoresDAO: The store paths and seeded invocation ids.
    """
    schedules_db_path = tmp_path / "schedules.db"
    database = ScheduleDatabase(db_path=schedules_db_path)
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    now = _utc_now()
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name="Purge target",
                prompt="purge target prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
            ),
            now=now - timedelta(days=92),
        )
        aged = await service.trigger_now(reference=str(created.id), now=now - timedelta(days=91))
        recent = await service.trigger_now(reference=str(created.id), now=now)
    finally:
        await service.close()
        await database.close()
    # The directory has been served by this build once, so its engine file
    # carries the admission record; seeded engine rows are then this build's
    # own, not an earlier layout's (OPS111-09).
    admitted = ScheduleEngine(db_path=schedules_db_path, channel_db_path=tmp_path / "channels.db")
    admitted.open()
    admitted.close()
    return PurgeStoresDAO(
        schedules_db_path=schedules_db_path,
        engine_db_path=admitted.engine_db_path,
        channel_db_path=tmp_path / "channels.db",
        aged_invocation_id=aged.id,
        recent_invocation_id=recent.id,
    )


async def _populate_channel(*, stores: PurgeStoresDAO) -> list[tuple[str, str]]:
    """Send one real scheduler message into channels.db and snapshot its rows.

    Args:
        stores (PurgeStoresDAO): The seeded stores.

    Returns:
        list[tuple[str, str]]: Every channel message id and content, sorted.
    """
    gateway = ChannelGateway(repository=ChannelRepository(db_path=stores.channel_db_path))
    await gateway.open()
    database = ScheduleDatabase(db_path=stores.schedules_db_path)
    try:
        await gateway.register_agent(session_id=_RECIPIENT, name="purge channel agent")
        async with database.transaction() as transaction:
            schedule = await ScheduleRepository().get_active_by_name_key(
                name_key=NewScheduleDAO.normalize_name_key(name="Purge target"),
                transaction=transaction,
            )
        assert schedule is not None
        await ScheduleChannelSender(gateway=gateway).send(
            schedule=schedule,
            invocation_id=stores.recent_invocation_id,
            recipient_session_id=str(_RECIPIENT),
        )
    finally:
        await database.close()
        await gateway.close()
    snapshot = _channel_messages(db_path=stores.channel_db_path)
    assert len(snapshot) == 1, "one populated channel row must exist"
    return snapshot


def _seed_dead_letters(*, db_path: Path, ages_in_days: dict[str, int]) -> dict[str, int]:
    """Dead-letter one engine job per queue and backdate its creation.

    Uses a test-owned honker handle that is closed before the engine opens.

    Args:
        db_path (Path): The engine's own database file.
        ages_in_days (dict[str, int]): Queue name to job age in days (0 keeps now).

    Returns:
        dict[str, int]: Queue name to dead-letter job id.
    """
    engine_store = honker.open(str(db_path))
    try:
        job_ids: dict[str, int] = {}
        for queue_name, age_days in ages_in_days.items():
            honker_queue = engine_store.queue(queue_name)
            job_id: int = honker_queue.enqueue({"probe": queue_name})
            job = honker_queue.claim_one(worker_id="purge-test-worker")
            assert job is not None and job.id == job_id
            assert job.fail(error="probe failure") is True
            created_at: int = int(time.time()) - int(timedelta(days=age_days).total_seconds())
            with engine_store.transaction() as transaction:
                transaction.query("UPDATE _honker_dead SET created_at = ? WHERE id = ?", [created_at, job_id])
            job_ids[queue_name] = job_id
    finally:
        engine_store.close()
    return job_ids


def _make_registered_purge_due(*, db_path: Path) -> None:
    """Move the registered purge job's next fire into the past.

    The scheduler then fires the real registration (queue and payload as the
    engine registered them) on its next tick, as it would at 03:00 UTC.
    """
    engine_store = honker.open(str(db_path))
    try:
        with engine_store.transaction() as transaction:
            transaction.query(
                "UPDATE _honker_scheduler_tasks SET next_fire_at = ? WHERE name = ?",
                [int(time.time()) - 1, _PURGE_TASK_NAME],
            )
    finally:
        engine_store.close()


def _read_rows(*, db_path: Path, sql: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Run one read-only query against a closed-store database file."""
    connection: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        return list(connection.execute(sql, parameters).fetchall())
    finally:
        connection.close()


def _dead_letter_ids(*, db_path: Path) -> set[int]:
    """Return every remaining engine dead-letter id."""
    return {int(str(row[0])) for row in _read_rows(db_path=db_path, sql="SELECT id FROM _honker_dead")}


def _invocation_ids(*, db_path: Path) -> set[str]:
    """Return every remaining invocation id."""
    return {str(row[0]) for row in _read_rows(db_path=db_path, sql="SELECT id FROM schedule_invocations")}


def _channel_messages(*, db_path: Path) -> list[tuple[str, str]]:
    """Return every channel message id and content, sorted."""
    rows = _read_rows(db_path=db_path, sql="SELECT id, message_contents FROM messages ORDER BY id")
    return [(str(row[0]), str(row[1])) for row in rows]


def _engine(*, stores: PurgeStoresDAO) -> ScheduleEngine:
    """Build the production engine over the seeded stores."""
    return ScheduleEngine(db_path=stores.schedules_db_path, channel_db_path=stores.channel_db_path)


async def test_daily_job_is_registered_at_the_retention_crontab(tmp_path: Path) -> None:
    """A7: the engine registers the daily purge job at 03:00 UTC on its purge queue."""
    stores = await _seed_schedules(tmp_path=tmp_path)
    engine = _engine(stores=stores)
    engine.open()
    engine.close()

    registrations = _read_rows(
        db_path=stores.engine_db_path,
        sql="SELECT queue, cron_expr FROM _honker_scheduler_tasks WHERE name = ?",
        parameters=(_PURGE_TASK_NAME,),
    )
    assert registrations == [(PURGE_QUEUE, _PURGE_CRONTAB)]


async def test_daily_purge_sweeps_dead_letters_older_than_retention(tmp_path: Path) -> None:
    """D25: one purge pass deletes dead-lettered engine jobs at or before the
    90-day cutoff and keeps recent ones; a second pass deletes nothing more;
    the populated channel row is untouched."""
    stores = await _seed_schedules(tmp_path=tmp_path)
    channel_before = await _populate_channel(stores=stores)
    dead_letters = _seed_dead_letters(
        db_path=stores.engine_db_path,
        ages_in_days={"purge-expired": 91, "purge-boundary": 90, "purge-recent": 0},
    )
    engine = _engine(stores=stores)
    engine.open()
    try:
        await engine.purge_once()
        await engine.purge_once()
    finally:
        engine.close()

    assert _dead_letter_ids(db_path=stores.engine_db_path) == {dead_letters["purge-recent"]}
    assert _invocation_ids(db_path=stores.schedules_db_path) == {str(stores.recent_invocation_id)}
    assert _channel_messages(db_path=stores.channel_db_path) == channel_before


async def test_registered_purge_job_fires_through_the_scheduler_and_worker_loop(tmp_path: Path) -> None:
    """A7: the engine's own scheduler fires the registered ``schedule-purge``
    job, the worker loop runs its handler, and the pass deletes the aged
    invocation and the aged dead letter while the populated channel row stays
    byte-for-byte unchanged (FIR111-07 reconciliation boundary)."""
    stores = await _seed_schedules(tmp_path=tmp_path)
    channel_before = await _populate_channel(stores=stores)
    dead_letters = _seed_dead_letters(
        db_path=stores.engine_db_path, ages_in_days={"purge-expired": 91, "purge-recent": 0}
    )
    engine = _engine(stores=stores)
    engine.open()
    try:
        _make_registered_purge_due(db_path=stores.engine_db_path)
        stop_event = asyncio.Event()
        engine_run: asyncio.Task[None] = asyncio.create_task(engine.run(stop_event=stop_event))
        try:
            for _ in range(int(_BOUND_SECONDS / 0.25)):
                if str(stores.aged_invocation_id) not in _invocation_ids(db_path=stores.schedules_db_path):
                    break
                await asyncio.sleep(0.25)
            assert str(stores.aged_invocation_id) not in _invocation_ids(
                db_path=stores.schedules_db_path
            ), "the registered purge job never ran within the wait bound"
        finally:
            stop_event.set()
            await asyncio.wait_for(engine_run, timeout=15)
    finally:
        engine.close()

    assert _invocation_ids(db_path=stores.schedules_db_path) == {str(stores.recent_invocation_id)}
    assert _dead_letter_ids(db_path=stores.engine_db_path) == {dead_letters["purge-recent"]}
    assert _channel_messages(db_path=stores.channel_db_path) == channel_before
    next_fire = _read_rows(
        db_path=stores.engine_db_path,
        sql="SELECT next_fire_at FROM _honker_scheduler_tasks WHERE name = ?",
        parameters=(_PURGE_TASK_NAME,),
    )
    assert int(str(next_fire[0][0])) > int(time.time()), "the scheduler advanced the fired registration"
