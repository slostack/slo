"""Report service — one schedule's window counts and newest rows, read-only."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from src.schedules.dao import (
    NewScheduleDAO,
    ScheduleDAO,
    ScheduleInvocationDAO,
    ScheduleReportCountsDAO,
    ScheduleReportDAO,
)
from src.schedules.database import ScheduleDatabase, ScheduleTransaction
from src.schedules.exceptions import ScheduleNotFoundError
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository

__all__ = ["ScheduleReportService", "RECENT_ROW_LIMIT"]

RECENT_ROW_LIMIT: int = 20


class ScheduleReportService:
    """Builds one schedule's report; the report never writes."""

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleRepository,
        invocations: ScheduleInvocationRepository,
    ) -> None:
        """Store the read-only collaborators.

        Args:
            database (ScheduleDatabase): The schedules database to read.
            schedules (ScheduleRepository): The schedule row reads.
            invocations (ScheduleInvocationRepository): The invocation reads.
        """
        self._database: ScheduleDatabase = database
        self._schedules: ScheduleRepository = schedules
        self._invocations: ScheduleInvocationRepository = invocations

    async def build(
        self,
        *,
        reference: str,
        window_start: datetime,
        window_end: datetime,
    ) -> ScheduleReportDAO:
        """Build one schedule's report for a due-time window.

        Args:
            reference (str): A schedule id or name. An id matches any row,
                including deleted; a name matches active rows only.
            window_start (datetime): Window start; a row matches when
                ``due_at >= window_start``.
            window_end (datetime): Window end; a row matches when
                ``due_at <= window_end``.

        Returns:
            ScheduleReportDAO: The counts for the window and the newest rows.

        Raises:
            ScheduleNotFoundError: When no schedule matches the reference.
        """
        async with self._database.transaction() as transaction:
            schedule: ScheduleDAO | None = await self._resolve(reference=reference, transaction=transaction)
            if schedule is None:
                raise ScheduleNotFoundError(reference=reference)
            counts: ScheduleReportCountsDAO = await self._invocations.count_for_window(
                schedule_id=schedule.id,
                since=window_start,
                until=window_end,
                transaction=transaction,
            )
            recent: list[ScheduleInvocationDAO] = await self._invocations.list_for_schedule(
                schedule_id=schedule.id,
                since=window_start,
                until=window_end,
                limit=RECENT_ROW_LIMIT,
                transaction=transaction,
            )
        return ScheduleReportDAO(
            schedule_id=schedule.id,
            name=schedule.name,
            window_start=window_start,
            window_end=window_end,
            counts=counts,
            recent_invocations=recent,
        )

    async def _resolve(self, *, reference: str, transaction: ScheduleTransaction) -> ScheduleDAO | None:
        """Resolve one report reference to a schedule row.

        An id matches any row, including deleted; a name matches active rows
        only, normalised exactly as every other reference lookup (FIR111-05:
        the repository owns name-key normalisation). A syntactically UUID-shaped
        reference resolves by id first and falls back to the active-name lookup
        when no id matches (FRR111-04), so UUID-shaped names stay reportable.

        Args:
            reference (str): A schedule id or name.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            ScheduleDAO | None: The row, or None when nothing matches.
        """
        schedule_id: UUID | None
        try:
            schedule_id = UUID(reference)
        except ValueError:
            schedule_id = None
        if schedule_id is not None:
            by_id: ScheduleDAO | None = await self._schedules.get_by_id(
                schedule_id=schedule_id, include_deleted=True, transaction=transaction
            )
            if by_id is not None:
                return by_id
        return await self._schedules.get_active_by_name_key(
            name_key=NewScheduleDAO.normalize_name_key(name=reference),
            transaction=transaction,
        )
