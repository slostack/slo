"""`ScheduleTickAppService` — one pass over due schedules; one transaction per schedule."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from src.schedules.dao import (
    ScheduleDAO,
    ScheduleInvocationDAO,
    ScheduleTickResultDAO,
    TriggerDAO,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.timing import ScheduleTiming

__all__ = ["ScheduleInvocationQueue", "ScheduleTickAppService"]


class ScheduleInvocationQueue(Protocol):
    """Enqueue seam; the engine implementation lives in `workflows.py`."""

    async def enqueue_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Enqueue one delivery job for the invocation.

        Args:
            invocation_id (UUID): The invocation to deliver.
            schedule_id (UUID): The owning schedule; also the partition key.
        """
        ...


class ScheduleTickAppService:
    """Creates pending invocations for due schedules; re-enqueues pending ones."""

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleRepository,
        schedule_service: ScheduleService,
        invocations: ScheduleInvocationRepository,
        queue: ScheduleInvocationQueue,
        reconciler: InvocationOutcomeReconciler,
    ) -> None:
        """Bind the collaborators the tick owns.

        Args:
            database (ScheduleDatabase): The schedules database; opens one
                transaction per due schedule.
            schedules (ScheduleRepository): Read-only list_due over ``schedules``.
            schedule_service (ScheduleService): The only writer of ``next_due_at``.
            invocations (ScheduleInvocationRepository): The invocation table SQL.
            queue (ScheduleInvocationQueue): The delivery enqueue seam.
            reconciler (InvocationOutcomeReconciler): The outcome copy collaborator.
        """
        self._database: ScheduleDatabase = database
        self._schedules: ScheduleRepository = schedules
        self._schedule_service: ScheduleService = schedule_service
        self._invocations: ScheduleInvocationRepository = invocations
        self._queue: ScheduleInvocationQueue = queue
        self._reconciler: InvocationOutcomeReconciler = reconciler

    async def invoke(self, *, now: datetime, batch_limit: int) -> ScheduleTickResultDAO:
        """Run one tick pass over due schedules.

        Args:
            now (datetime): The boundary clock instant.
            batch_limit (int): Maximum due schedules and re-enqueued rows.

        Returns:
            ScheduleTickResultDAO: The counts from this run.
        """
        created_count: int = 0
        duplicate_count: int = 0
        misfire_count: int = 0
        async with self._database.transaction() as transaction:
            due_schedules = await self._schedules.list_due(
                now=now, limit=batch_limit, transaction=transaction
            )
        for schedule in due_schedules:
            outcome: Literal["created", "duplicate", "misfire", "rolled_back"] = await self._handle_one(
                schedule=schedule, now=now
            )
            if outcome == "created":
                created_count += 1
            elif outcome == "duplicate":
                duplicate_count += 1
            elif outcome == "misfire":
                misfire_count += 1
        enqueued_count: int = await self._enqueue_pending(limit=batch_limit)
        reconciled_count: int = await self._reconciler.reconcile(now=now, limit=batch_limit)
        return ScheduleTickResultDAO(
            created_count=created_count,
            duplicate_count=duplicate_count,
            misfire_count=misfire_count,
            enqueued_count=enqueued_count,
            reconciled_count=reconciled_count,
        )

    async def _handle_one(
        self, *, schedule: ScheduleDAO, now: datetime
    ) -> Literal["created", "duplicate", "misfire", "rolled_back"]:
        """Create one pending invocation and advance the schedule's next due.

        A due time later than the misfire grace is recorded as a misfire instead
        (111.a.4 §5.2); the skipped row and the schedule writes commit together.

        Args:
            schedule (ScheduleDAO): The due schedule row selected by the tick.
            now (datetime): The boundary clock instant.

        Returns:
            Literal["created", "duplicate", "misfire", "rolled_back"]: ``created``
                when the pending row was inserted; ``duplicate`` when the due
                time was already covered; ``misfire`` when the missed due time
                was recorded; ``rolled_back`` when the schedule changed since
                selection (stopped, edited or deleted) and no row was written.
        """
        due: datetime = _due_instant(schedule=schedule)
        trigger: TriggerDAO = schedule.trigger
        lateness: timedelta = now - due
        if lateness > timedelta(seconds=schedule.misfire_grace_seconds):
            return await self._handle_misfire(schedule=schedule, due=due, now=now)
        next_due: datetime | None = ScheduleTiming.next_due_after(trigger=trigger, after=due)
        async with self._database.transaction() as transaction:
            invocation: ScheduleInvocationDAO = ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=schedule.id,
                due_at=due,
                status="pending",
                created_at=now,
            )
            inserted: bool = await self._invocations.insert_pending(
                invocation=invocation, transaction=transaction
            )
            advanced: bool = await self._schedule_service.advance_next_due(
                schedule_id=schedule.id,
                expected_due_at=due,
                next_due_at=next_due,
                transaction=transaction,
            )
            if not advanced:
                await transaction.rollback()
                return "rolled_back"
        return "created" if inserted else "duplicate"

    async def _handle_misfire(
        self, *, schedule: ScheduleDAO, due: datetime, now: datetime
    ) -> Literal["misfire", "duplicate", "rolled_back"]:
        """Record one skipped/misfire row and advance the schedule's next due.

        The skipped row, the next-due advance and the one-shot end commit
        together (111.a.4 §5.2). A duplicate ``(schedule_id, due)`` inserts
        nothing and counts nothing; the advance still runs.

        Args:
            schedule (ScheduleDAO): The due schedule row selected by the tick.
            due (datetime): The missed due instant.
            now (datetime): The boundary clock instant.

        Returns:
            Literal["misfire", "duplicate", "rolled_back"]: ``misfire`` when the
                skipped row was inserted; ``duplicate`` when the missed time was
                already recorded; ``rolled_back`` when the schedule changed since
                selection.
        """
        trigger: TriggerDAO = schedule.trigger
        next_due: datetime | None = ScheduleTiming.catch_up_to(trigger=trigger, missed_due_at=due, now=now)
        async with self._database.transaction() as transaction:
            invocation: ScheduleInvocationDAO = ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=schedule.id,
                due_at=due,
                status="skipped",
                skip_reason="misfire",
                created_at=now,
            )
            inserted: bool = await self._invocations.insert_misfire(
                invocation=invocation, transaction=transaction
            )
            advanced: bool = await self._schedule_service.advance_next_due(
                schedule_id=schedule.id,
                expected_due_at=due,
                next_due_at=next_due,
                transaction=transaction,
            )
            if not advanced:
                await transaction.rollback()
                return "rolled_back"
            await self._schedule_service.complete_occurrence(
                schedule_id=schedule.id,
                now=now,
                transaction=transaction,
            )
        return "misfire" if inserted else "duplicate"

    async def _enqueue_pending(self, *, limit: int) -> int:
        """Re-enqueue every pending invocation, oldest due first.

        Args:
            limit (int): Maximum rows to re-enqueue.

        Returns:
            int: The number of rows handed to the queue.
        """
        async with self._database.transaction() as transaction:
            pending = await self._invocations.list_pending(limit=limit, transaction=transaction)
        for invocation in pending:
            await self._queue.enqueue_delivery(
                invocation_id=invocation.id, schedule_id=invocation.schedule_id
            )
        return len(pending)


def _due_instant(*, schedule: ScheduleDAO) -> datetime:
    """Return the due time the tick handled for one schedule.

    Args:
        schedule (ScheduleDAO): The due schedule row.

    Returns:
        datetime: The schedule's next_due_at.

    Raises:
        ValueError: When the row has no next_due_at (not selected by list_due).
    """
    if schedule.next_due_at is None:
        raise ValueError(f"Schedule {schedule.id} has no next_due_at")
    return schedule.next_due_at
