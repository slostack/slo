"""`ScheduleService` — one owner of definition, enabled flag and soft deletion."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

import re

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.schedules.dao import (
    DeliveryDecisionDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleDAO,
    ScheduleInvocationDAO,
    ScheduleStateFilter,
    ScheduleSummaryDAO,
)
from src.schedules.database import ScheduleDatabase, ScheduleTransaction, default_database_path
from src.schedules.exceptions import ScheduleInvalidError, ScheduleNotFoundError, ScheduleNameTakenError
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.timing import ScheduleTiming

__all__ = ["ScheduleService"]

_SESSION_ID_SLUG_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")
"""A reference that can be passed through as a session id when it resolves to nothing."""


class ScheduleService:
    """Owns the schedules table lifecycle; one write transaction per command."""

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleRepository,
        invocations: ScheduleInvocationRepository,
        session_history: Optional[SessionHistoryStoreProtocol],
    ) -> None:
        """Bind the collaborators this service owns.

        Args:
            database (ScheduleDatabase): The schedules database; opens one
                transaction per command.
            schedules (ScheduleRepository): The row-level SQL for ``schedules``.
            invocations (ScheduleInvocationRepository): Read-only invocation
                queries for list summaries.
            session_history (Optional[SessionHistoryStoreProtocol]): Reference
                resolution collaborator; used only by decide_delivery.
        """
        self._database: ScheduleDatabase = database
        self._schedules: ScheduleRepository = schedules
        self._invocations: ScheduleInvocationRepository = invocations
        self._session_history: Optional[SessionHistoryStoreProtocol] = session_history

    @classmethod
    def at_default_path(cls) -> "ScheduleService":
        """Build a service on ``SLO_SCHEDULES_DIR`` or ``$SLO_HOME/schedules``.

        Returns:
            ScheduleService: A service wired to the default database path.
        """
        return cls(
            database=ScheduleDatabase(db_path=default_database_path()),
            schedules=ScheduleRepository(),
            invocations=ScheduleInvocationRepository(),
            session_history=FilesystemSessionHistoryStore(),
        )

    async def close(self) -> None:
        """Release the database worker and connection."""
        await self._database.close()

    async def create(self, *, new_schedule: NewScheduleDAO, now: datetime) -> ScheduleDAO:
        """Insert one enabled schedule with its first due time.

        Args:
            new_schedule (NewScheduleDAO): The validated definition to persist.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleDAO: The stored row.

        Raises:
            ScheduleInvalidError: The trigger cannot fire from ``now``.
            ScheduleNameTakenError: An active row already holds the name key.
        """
        ScheduleTiming.validate(trigger=new_schedule.trigger, now=now)
        first_due = ScheduleTiming.first_due_at(trigger=new_schedule.trigger, created_at=now)
        created_schedule: ScheduleDAO = ScheduleDAO(
            id=uuid4(),
            name=new_schedule.name,
            name_key=new_schedule.name_key,
            prompt=new_schedule.prompt,
            trigger=new_schedule.trigger,
            session_mode=new_schedule.session_mode,
            session_reference=new_schedule.session_reference,
            coalescing_mode=new_schedule.coalescing_mode,
            coalescing_key=new_schedule.coalescing_key,
            misfire_grace_seconds=new_schedule.misfire_grace_seconds,
            cwd=new_schedule.cwd,
            model=new_schedule.model,
            enabled=True,
            next_due_at=first_due,
            created_at=now,
            updated_at=now,
            deleted_at=None,
        )
        async with self._database.transaction() as transaction:
            name_holder = await self._schedules.get_active_by_name_key(
                name_key=created_schedule.name_key,
                transaction=transaction,
            )
            if name_holder is not None:
                raise ScheduleNameTakenError(name_key=created_schedule.name_key)
            await self._schedules.insert(schedule=created_schedule, transaction=transaction)
        return created_schedule

    async def edit(self, *, reference: str, changes: NewScheduleDAO, now: datetime) -> ScheduleDAO:
        """Replace one active schedule's definition.

        Args:
            reference (str): The schedule id or name.
            changes (NewScheduleDAO): The replacement definition.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleDAO: The updated row.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
            ScheduleInvalidError: The trigger cannot fire from ``now``.
            ScheduleNameTakenError: Another active row holds the new name key.
        """
        ScheduleTiming.validate(trigger=changes.trigger, now=now)
        async with self._database.transaction() as transaction:
            stored_schedule = await self._schedules.get_by_reference(
                reference=reference, transaction=transaction
            )
            if stored_schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            name_key = changes.name_key
            name_holder = await self._schedules.get_active_by_name_key(
                name_key=name_key,
                transaction=transaction,
            )
            if name_holder is not None and name_holder.id != stored_schedule.id:
                raise ScheduleNameTakenError(name_key=name_key)
            first_due = ScheduleTiming.first_due_at(trigger=changes.trigger, created_at=now)
            edited_schedule = ScheduleDAO(
                id=stored_schedule.id,
                name=changes.name,
                name_key=name_key,
                prompt=changes.prompt,
                trigger=changes.trigger,
                session_mode=changes.session_mode,
                session_reference=changes.session_reference,
                coalescing_mode=changes.coalescing_mode,
                coalescing_key=changes.coalescing_key,
                misfire_grace_seconds=changes.misfire_grace_seconds,
                cwd=changes.cwd,
                model=changes.model,
                enabled=stored_schedule.enabled,
                next_due_at=first_due if stored_schedule.enabled else None,
                created_at=stored_schedule.created_at,
                updated_at=now,
                deleted_at=None,
            )
            await self._schedules.update(schedule=edited_schedule, transaction=transaction)
        return edited_schedule

    async def show(self, *, reference: str) -> ScheduleDAO:
        """Load one active schedule.

        Args:
            reference (str): The schedule id or name.

        Returns:
            ScheduleDAO: The stored row.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
        """
        async with self._database.transaction() as transaction:
            stored_schedule = await self._schedules.get_by_reference(
                reference=reference, transaction=transaction
            )
        if stored_schedule is None:
            raise ScheduleNotFoundError(reference=reference)
        return stored_schedule

    async def list_by_state(self, *, state: ScheduleStateFilter) -> list[ScheduleSummaryDAO]:
        """List schedules in the requested state with their newest invocation status.

        Args:
            state (ScheduleStateFilter): ``active`` or ``disabled``.

        Returns:
            list[ScheduleSummaryDAO]: Deterministic rows ordered by name key.
        """
        async with self._database.transaction() as transaction:
            listed_schedules = await self._schedules.list_by_state(state=state, transaction=transaction)
            statuses = await self._invocations.latest_status_by_schedule(
                schedule_ids=[listed.id for listed in listed_schedules],
                transaction=transaction,
            )
        return [
            ScheduleSummaryDAO(schedule=listed, last_invocation_status=statuses.get(listed.id))
            for listed in listed_schedules
        ]

    async def start(self, *, reference: str, now: datetime) -> ScheduleDAO:
        """Enable one disabled schedule; the next due recomputes from ``now``.

        Args:
            reference (str): The schedule id or name.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleDAO: The stored row.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
            ScheduleInvalidError: A one-shot trigger can no longer fire.
        """
        async with self._database.transaction() as transaction:
            stored_schedule = await self._schedules.get_by_reference(
                reference=reference, transaction=transaction
            )
            if stored_schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            if stored_schedule.enabled:
                return stored_schedule
            ScheduleTiming.validate(trigger=stored_schedule.trigger, now=now)
            first_due = ScheduleTiming.first_due_at(trigger=stored_schedule.trigger, created_at=now)
            started_schedule = ScheduleDAO(
                **{
                    **stored_schedule.model_dump(),
                    "enabled": True,
                    "next_due_at": first_due,
                    "updated_at": now,
                }
            )
            await self._schedules.update(schedule=started_schedule, transaction=transaction)
        return started_schedule

    async def stop(self, *, reference: str, now: datetime) -> ScheduleDAO:
        """Disable one enabled schedule and clear its next due.

        Args:
            reference (str): The schedule id or name.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleDAO: The stored row.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
        """
        async with self._database.transaction() as transaction:
            stored_schedule = await self._schedules.get_by_reference(
                reference=reference, transaction=transaction
            )
            if stored_schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            if not stored_schedule.enabled:
                return stored_schedule
            stopped_schedule = ScheduleDAO(
                **{
                    **stored_schedule.model_dump(),
                    "enabled": False,
                    "next_due_at": None,
                    "updated_at": now,
                }
            )
            await self._schedules.update(schedule=stopped_schedule, transaction=transaction)
        return stopped_schedule

    async def trigger_now(self, *, reference: str, now: datetime) -> ScheduleInvocationDAO:
        """Insert one pending invocation for a manual fire, due now.

        Args:
            reference (str): The schedule id or name.
            now (datetime): The boundary clock instant, truncated to the millisecond.

        Returns:
            ScheduleInvocationDAO: The pending row; an existing row for the same
                millisecond is returned instead of a second one.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
            ScheduleInvalidError: The schedule is disabled.
        """
        async with self._database.transaction() as transaction:
            schedule = await self._schedules.get_by_reference(reference=reference, transaction=transaction)
            if schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            if not schedule.enabled:
                raise ScheduleInvalidError(reason="schedule_disabled")
            invocation: ScheduleInvocationDAO = ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=schedule.id,
                due_at=now,
                status="pending",
                created_at=now,
            )
            inserted: bool = await self._invocations.insert_pending(
                invocation=invocation, transaction=transaction
            )
            if not inserted:
                existing = await self._invocations.get_by_schedule_and_due(
                    schedule_id=schedule.id,
                    due_at=now,
                    transaction=transaction,
                )
                if existing is not None:
                    return existing
        return invocation

    async def decide_delivery(
        self, *, invocation: ScheduleInvocationDAO, now: datetime
    ) -> DeliveryDecisionDAO:
        """Decide what deliver must do with one pending invocation.

        The checks run in this order (111.a.2 §5.4 step 3); the first match
        decides and later checks do not run:

        1. Schedule deleted → skip, schedule_deleted.
        2. Schedule disabled → skip, schedule_disabled.
        3. Late (now − due_at > misfire_grace_seconds) → skip, misfire.
        4. ``session_mode = fresh`` → run (111.a.3 §6.2).
        5. Continuous, no ``session_reference`` → run, treated as fresh (D5 part 3).
        6. Continuous, reference is neither a session id nor a name and not a
           slug → fail, unknown_session_reference.
        7. Continuous, reference resolves → deliver, recipient = resolved id.

        Args:
            invocation (ScheduleInvocationDAO): The pending invocation to decide.
            now (datetime): The boundary clock instant supplied by the caller.

        Returns:
            DeliveryDecisionDAO: The decision, carrying the loaded schedule row.
        """
        async with self._database.transaction() as transaction:
            schedule = await self._schedules.get_by_id(
                schedule_id=invocation.schedule_id,
                include_deleted=True,
                transaction=transaction,
            )
        if schedule is None:
            return _skip_decision(skip_reason="schedule_deleted", schedule=None)
        if schedule.deleted_at is not None:
            return _skip_decision(skip_reason="schedule_deleted", schedule=schedule)
        if not schedule.enabled:
            return _skip_decision(skip_reason="schedule_disabled", schedule=schedule)
        if now - invocation.due_at > timedelta(seconds=schedule.misfire_grace_seconds):
            return _skip_decision(skip_reason="misfire", schedule=schedule)
        if schedule.session_mode == "fresh":
            return _run_decision(schedule=schedule)
        reference = schedule.session_reference
        if reference is None:
            return _run_decision(schedule=schedule)
        if self._session_history is not None:
            resolved: Optional[str]
            try:
                resolved = await self._session_history.resolve_session_reference(reference=reference)
            except ValueError:
                resolved = None
            if resolved is not None:
                return _deliver_decision(schedule=schedule, recipient_session_id=resolved)
        if _SESSION_ID_SLUG_RE.match(reference):
            return _deliver_decision(schedule=schedule, recipient_session_id=reference)
        return _fail_decision(failure_reason="unknown_session_reference", schedule=schedule)

    async def advance_next_due(
        self,
        *,
        schedule_id: UUID,
        expected_due_at: datetime,
        next_due_at: Optional[datetime],
        transaction: ScheduleTransaction,
    ) -> bool:
        """Advance one enabled schedule's next due time on the caller's transaction.

        Args:
            schedule_id (UUID): The schedule to advance.
            expected_due_at (datetime): The due time the tick handled.
            next_due_at (Optional[datetime]): The new due time, or None to clear it
                (a one-shot stays enabled until its invocation is final).
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            bool: True when the update matched; False when the schedule was stopped,
                edited or deleted since selection.
        """
        return await self._schedules.set_next_due(
            schedule_id=schedule_id,
            expected_due_at=expected_due_at,
            next_due_at=next_due_at,
            transaction=transaction,
        )

    async def complete_occurrence(
        self,
        *,
        schedule_id: UUID,
        now: datetime,
        transaction: ScheduleTransaction,
    ) -> None:
        """Disable a one-shot schedule whose only invocation is final (111.a.4 §5.4).

        Non-one-shot triggers and already-disabled or deleted schedules cause no
        write. The caller's transaction is used, so the schedule write commits
        together with the invocation write.

        Args:
            schedule_id (UUID): The schedule that owned the final invocation.
            now (datetime): The boundary clock instant supplied by the caller.
            transaction (ScheduleTransaction): The caller's open transaction.
        """
        schedule = await self._schedules.get_by_id(
            schedule_id=schedule_id,
            include_deleted=True,
            transaction=transaction,
        )
        if schedule is None or schedule.deleted_at is not None or not schedule.enabled:
            return
        if not isinstance(schedule.trigger, OneShotTriggerDAO):
            return
        await self._schedules.update(
            schedule=schedule.model_copy(
                update={"enabled": False, "next_due_at": None, "updated_at": now},
            ),
            transaction=transaction,
        )

    async def delete(self, *, reference: str, now: datetime) -> ScheduleDAO:
        """Soft-delete one active schedule.

        Args:
            reference (str): The schedule id or name.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleDAO: The stored row.

        Raises:
            ScheduleNotFoundError: No active row matches the reference.
        """
        async with self._database.transaction() as transaction:
            stored_schedule = await self._schedules.get_by_reference(
                reference=reference, transaction=transaction
            )
            if stored_schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            deleted_schedule = ScheduleDAO(
                **{
                    **stored_schedule.model_dump(),
                    "enabled": False,
                    "next_due_at": None,
                    "deleted_at": now,
                    "updated_at": now,
                }
            )
            await self._schedules.update(schedule=deleted_schedule, transaction=transaction)
        return deleted_schedule


def _skip_decision(*, skip_reason: str, schedule: Optional[ScheduleDAO]) -> DeliveryDecisionDAO:
    """Build a skip decision.

    Args:
        skip_reason (str): Why the invocation was skipped.
        schedule (Optional[ScheduleDAO]): The loaded schedule row, or None when
            no row matched (treated as deleted).

    Returns:
        DeliveryDecisionDAO: The skip decision.
    """
    if schedule is None:
        raise ValueError("skip decision requires a schedule row")
    return DeliveryDecisionDAO(
        outcome="skip",
        skip_reason=skip_reason,  # type: ignore[arg-type]
        schedule=schedule,
    )


def _run_decision(*, schedule: ScheduleDAO) -> DeliveryDecisionDAO:
    """Build a run decision: one fresh headless run for this invocation.

    Args:
        schedule (ScheduleDAO): The loaded schedule row.

    Returns:
        DeliveryDecisionDAO: The run decision, carrying the schedule row so
            deliver can read the prompt, cwd and model without loading it again.
    """
    return DeliveryDecisionDAO(
        outcome="run",
        schedule=schedule,
    )


def _fail_decision(*, failure_reason: str, schedule: ScheduleDAO) -> DeliveryDecisionDAO:
    """Build a fail decision.

    Args:
        failure_reason (str): Why the invocation failed.
        schedule (ScheduleDAO): The loaded schedule row.

    Returns:
        DeliveryDecisionDAO: The fail decision.
    """
    return DeliveryDecisionDAO(
        outcome="fail",
        failure_reason=failure_reason,
        schedule=schedule,
    )


def _deliver_decision(*, schedule: ScheduleDAO, recipient_session_id: str) -> DeliveryDecisionDAO:
    """Build a deliver decision.

    Args:
        schedule (ScheduleDAO): The loaded schedule row.
        recipient_session_id (str): The resolved session id to send to.

    Returns:
        DeliveryDecisionDAO: The deliver decision.
    """
    return DeliveryDecisionDAO(
        outcome="deliver",
        recipient_session_id=recipient_session_id,
        schedule=schedule,
    )
