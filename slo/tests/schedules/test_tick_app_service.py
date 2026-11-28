"""Tick tests (111.a.2 A1/A2/A3, T2.1) on real SQLite with a recording queue."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase, format_instant, parse_instant
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.database import ScheduleTransaction
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.tick_app_service import ScheduleTickAppService


def _utc(*, minute: int = 0) -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=12, minute=minute, tzinfo=timezone.utc)


def _interval_input(name: str = "Daily Summary") -> NewScheduleDAO:
    """Build a valid interval schedule input."""
    return NewScheduleDAO(
        name=name,
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
    )


def _one_shot_input(*, run_at: datetime) -> NewScheduleDAO:
    """Build a valid one-shot schedule input."""
    return NewScheduleDAO(
        name="One Shot",
        prompt="Summarise the repo",
        trigger=OneShotTriggerDAO(run_at=run_at),
    )


class RecordingInvocationQueue:
    """Test stub that records enqueue calls and accepts them all (spec §6.2)."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[UUID, UUID]] = []

    async def enqueue_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Record one enqueue call."""
        self.calls.append((invocation_id, schedule_id))


class StoppingScheduleRepository(ScheduleRepository):
    """Test double that stops the schedule when the tick tries to advance it."""

    def __init__(self) -> None:
        """Start with no target; the test sets one after creating the schedule."""
        super().__init__()
        self._schedule_id: Optional[UUID] = None

    def set_target(self, *, schedule_id: UUID) -> None:
        """Bind the schedule the stop will hit."""
        self._schedule_id = schedule_id

    async def set_next_due(
        self,
        *,
        schedule_id: UUID,
        expected_due_at: datetime,
        next_due_at: Optional[datetime],
        transaction: ScheduleTransaction,
    ) -> bool:
        """Stop the schedule first, then run the guarded update."""
        if schedule_id == self._schedule_id:  # type: ignore[comparison-overlap]
            await transaction.execute(
                sql="UPDATE schedules SET enabled = 0, next_due_at = NULL WHERE id = ?",
                parameters=(str(schedule_id),),
            )
        return await super().set_next_due(
            schedule_id=schedule_id,
            expected_due_at=expected_due_at,
            next_due_at=next_due_at,
            transaction=transaction,
        )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    """Build a real tick service on tmp_path databases with a recording queue."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    schedules = ScheduleRepository()
    invocations = ScheduleInvocationRepository()
    service = ScheduleService(
        database=database,
        schedules=schedules,
        invocations=invocations,
        session_history=None,
    )
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    reconciler = InvocationOutcomeReconciler(
        database=database,
        gateway=gateway,
        invocations=invocations,
    )
    queue = RecordingInvocationQueue()
    tick = ScheduleTickAppService(
        database=database,
        schedules=schedules,
        schedule_service=service,
        invocations=invocations,
        queue=queue,
        reconciler=reconciler,
    )
    built: dict[str, object] = {
        "database": database,
        "service": service,
        "invocations": invocations,
        "gateway": gateway,
        "queue": queue,
        "tick": tick,
    }
    yield built
    await gateway.close()
    await database.close()


async def test_tick_creates_one_pending_invocation_and_advances_next_due(
    harness: dict[str, object],
) -> None:
    """A1: one due schedule gets one pending row at its next_due_at; the schedule moves on."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    assert created.next_due_at == now + timedelta(seconds=60)

    result = await tick.invoke(now=now + timedelta(seconds=60), batch_limit=50)

    assert result.created_count == 1
    assert result.duplicate_count == 0
    assert result.enqueued_count == 1
    shown = await service.show(reference=str(created.id))
    assert shown.next_due_at == now + timedelta(seconds=120)
    async with database.transaction() as transaction:
        rows: list[ScheduleInvocationDAO] = await invocations.list_pending(limit=10, transaction=transaction)
    assert len(rows) == 1
    assert rows[0].schedule_id == created.id
    assert rows[0].due_at == now + timedelta(seconds=60)
    assert rows[0].status == "pending"


async def test_second_tick_at_the_same_instant_creates_no_duplicate(
    harness: dict[str, object],
) -> None:
    """A1: the second run sees next_due_at already advanced and creates nothing."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    due: datetime = now + timedelta(seconds=60)

    await tick.invoke(now=due, batch_limit=50)
    second = await tick.invoke(now=due, batch_limit=50)

    assert second.created_count == 0
    assert second.duplicate_count == 0
    shown = await service.show(reference=str(created.id))
    assert shown.next_due_at == now + timedelta(seconds=120)


async def test_duplicate_conflict_still_advances_next_due(
    harness: dict[str, object],
) -> None:
    """A2: a unique conflict on (schedule_id, due_at) counts a duplicate and still moves on."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    due: datetime = now + timedelta(seconds=60)
    # A pending row already covers the due time; the tick must still advance next_due_at.
    async with database.transaction() as transaction:
        await invocations.insert_pending(
            invocation=ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=created.id,
                due_at=due,
                status="pending",
                created_at=now,
            ),
            transaction=transaction,
        )

    result = await tick.invoke(now=due, batch_limit=50)

    assert result.duplicate_count == 1
    assert result.created_count == 0
    shown = await service.show(reference=str(created.id))
    assert shown.next_due_at == now + timedelta(seconds=120)


async def test_schedule_stopped_after_selection_creates_no_invocation(
    tmp_path: Path,
) -> None:
    """A3: a stop committed after selection rolls the tick's transaction back."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    schedules = StoppingScheduleRepository()
    invocations = ScheduleInvocationRepository()
    service = ScheduleService(
        database=database,
        schedules=schedules,
        invocations=invocations,
        session_history=None,
    )
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    reconciler = InvocationOutcomeReconciler(
        database=database,
        gateway=gateway,
        invocations=invocations,
    )
    queue = RecordingInvocationQueue()
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    due: datetime = now + timedelta(seconds=60)
    # The stop lands between the tick's read and its guarded advance: the spy
    # repository disables the row on the same transaction before the guard runs.
    schedules.set_target(schedule_id=created.id)
    tick = ScheduleTickAppService(
        database=database,
        schedules=schedules,
        schedule_service=service,
        invocations=invocations,
        queue=queue,
        reconciler=reconciler,
    )

    result = await tick.invoke(now=due, batch_limit=50)

    assert result.created_count == 0
    assert result.duplicate_count == 0
    assert result.enqueued_count == 0
    async with database.transaction() as transaction:
        rows: list[ScheduleInvocationDAO] = await invocations.list_pending(limit=10, transaction=transaction)
    assert len(rows) == 0
    await gateway.close()
    await database.close()


async def test_one_shot_tick_clears_next_due_and_stays_enabled(
    harness: dict[str, object],
) -> None:
    """A3: a one-shot's tick passes next_due_at=None; the row stays enabled until final."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    now: datetime = _utc()
    run_at: datetime = now + timedelta(seconds=60)
    created = await service.create(new_schedule=_one_shot_input(run_at=run_at), now=now)

    result = await tick.invoke(now=run_at, batch_limit=50)

    assert result.created_count == 1
    shown = await service.show(reference=str(created.id))
    assert shown.next_due_at is None
    assert shown.enabled is True


async def test_tick_enqueues_pending_rows_oldest_due_first(
    harness: dict[str, object],
) -> None:
    """A2: re-enqueue covers crashes; pending rows go to the queue oldest due first."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    queue: RecordingInvocationQueue = harness["queue"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    first = await service.create(new_schedule=_interval_input(name="First"), now=now)
    second = await service.create(new_schedule=_interval_input(name="Second"), now=now)
    due_first: datetime = now + timedelta(seconds=60)
    due_second: datetime = now + timedelta(seconds=90)
    for schedule_id, due in ((first.id, due_second), (second.id, due_first)):
        async with database.transaction() as transaction:
            await invocations.insert_pending(
                invocation=ScheduleInvocationDAO(
                    id=uuid4(),
                    schedule_id=schedule_id,
                    due_at=due,
                    status="pending",
                    created_at=now,
                ),
                transaction=transaction,
            )

    await tick.invoke(now=now + timedelta(seconds=120), batch_limit=50)

    assert len(queue.calls) == 3
    delivered_ats: list[datetime] = []
    for invocation_id, _schedule_id in queue.calls:
        async with database.transaction() as transaction:
            row = await invocations.get(invocation_id=invocation_id, transaction=transaction)
        assert row is not None
        delivered_ats.append(row.due_at)
    assert delivered_ats == sorted(delivered_ats)


async def test_late_due_time_records_misfire_and_advances_next_due(
    harness: dict[str, object],
) -> None:
    """A1 (tick-side): a due time past the grace is skipped/misfire; the next
    due advances past now on the same phase; the count increments."""
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    now = _utc(minute=30)
    created = await service.create(new_schedule=_interval_input(), now=_utc())
    missed_due = _utc(minute=20)
    async with database.transaction() as transaction:
        await transaction.execute(
            sql="UPDATE schedules SET next_due_at = ?, misfire_grace_seconds = 300 WHERE id = ?",
            parameters=(format_instant(value=missed_due), str(created.id)),
        )

    result = await tick.invoke(now=now, batch_limit=10)

    assert result.misfire_count == 1
    assert result.created_count == 0
    row = await service.show(reference=str(created.id))
    assert row.next_due_at is not None
    assert row.next_due_at > now
    async with database.transaction() as transaction:
        skipped = await transaction.fetch_all(
            sql="SELECT * FROM schedule_invocations WHERE schedule_id = ?",
            parameters=(str(created.id),),
        )
    assert len(skipped) == 1
    assert skipped[0]["status"] == "skipped"
    assert skipped[0]["skip_reason"] == "misfire"
    assert parse_instant(text=str(skipped[0]["due_at"])) == missed_due


async def test_late_one_shot_is_disabled_by_the_tick(
    harness: dict[str, object],
) -> None:
    """A5 (tick-side, one-shot): the tick finds the one-shot late; the skipped
    row and the disable commit together; next_due_at stays cleared."""
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    tick: ScheduleTickAppService = harness["tick"]  # type: ignore[assignment]
    now = _utc(minute=30)
    created = await service.create(new_schedule=_one_shot_input(run_at=_utc(minute=5)), now=_utc())
    async with database.transaction() as transaction:
        await transaction.execute(
            sql="UPDATE schedules SET misfire_grace_seconds = 300 WHERE id = ?",
            parameters=(str(created.id),),
        )

    result = await tick.invoke(now=now, batch_limit=10)

    assert result.misfire_count == 1
    row = await service.show(reference=str(created.id))
    assert row.enabled is False
    assert row.next_due_at is None
    async with database.transaction() as transaction:
        skipped = await transaction.fetch_all(
            sql="SELECT * FROM schedule_invocations WHERE schedule_id = ?",
            parameters=(str(created.id),),
        )
    assert len(skipped) == 1
    assert skipped[0]["status"] == "skipped"
    assert skipped[0]["skip_reason"] == "misfire"
