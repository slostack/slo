"""Schedule retention — the 90-day purge of invocation rows and soft-deleted schedules."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.schedules.dao import RetentionResultDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository

__all__ = ["ScheduleRetentionService", "RETENTION_DAYS"]

RETENTION_DAYS: int = 90
_BATCH_SIZE: int = 1000


class ScheduleRetentionService:
    """Deletes schedule data older than the retention window.

    The service owns the retention rule: invocation rows created at or before
    the cutoff are deleted first, then soft-deleted schedules with no rows
    left. It opens its own transactions and never touches the channel store.
    """

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleRepository,
        invocations: ScheduleInvocationRepository,
    ) -> None:
        """Store the collaborators the retention service needs.

        Args:
            database (ScheduleDatabase): The schedule database that owns
                transactions for the purge.
            schedules (ScheduleRepository): The repository for schedule rows.
            invocations (ScheduleInvocationRepository): The repository for
                invocation rows.
        """
        self._database: ScheduleDatabase = database
        self._schedules: ScheduleRepository = schedules
        self._invocations: ScheduleInvocationRepository = invocations

    async def purge(self, *, now: datetime) -> RetentionResultDAO:
        """Delete schedule data older than the retention window.

        Args:
            now (datetime): The boundary clock instant; the cutoff is
                ``now - RETENTION_DAYS``.

        Returns:
            RetentionResultDAO: The number of invocation rows and soft-deleted
                schedule rows removed.
        """
        cutoff: datetime = now - timedelta(days=RETENTION_DAYS)
        deleted_invocations: int = await self._purge_invocations(cutoff=cutoff)
        deleted_schedules: int = await self._purge_schedules(cutoff=cutoff)
        return RetentionResultDAO(
            deleted_invocations=deleted_invocations,
            deleted_schedules=deleted_schedules,
        )

    async def _purge_invocations(self, *, cutoff: datetime) -> int:
        """Delete invocation rows created at or before the cutoff, in batches.

        Args:
            cutoff (datetime): Rows created at or before this instant are deleted.

        Returns:
            int: The total number of invocation rows deleted.
        """
        deleted: int = 0
        while True:
            async with self._database.transaction() as transaction:
                batch: int = await self._invocations.purge_created_before(
                    cutoff=cutoff, batch_size=_BATCH_SIZE, transaction=transaction
                )
            if batch < _BATCH_SIZE:
                return deleted + batch
            deleted += batch

    async def _purge_schedules(self, *, cutoff: datetime) -> int:
        """Delete soft-deleted schedules with no rows left, in batches.

        Args:
            cutoff (datetime): Rows soft-deleted at or before this instant are
                candidates.

        Returns:
            int: The total number of soft-deleted schedule rows removed.
        """
        deleted: int = 0
        while True:
            async with self._database.transaction() as transaction:
                batch: int = await self._schedules.purge_deleted_before(
                    cutoff=cutoff, batch_size=_BATCH_SIZE, transaction=transaction
                )
            if batch < _BATCH_SIZE:
                return deleted + batch
            deleted += batch
