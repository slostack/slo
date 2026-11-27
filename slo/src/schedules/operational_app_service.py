"""Operational schedule workflows (OPS111-01, OPS111-06, OPS111-07).

Creating or enabling a schedule is one user action with two durable effects
in a fixed order: the schedule definition is committed first, then the shared
worker is started or reused and proved healthy. A failed second step never
rolls the first back — the saved schedule is reported with its id so the user
retries activation with ``slo schedule start``, never a second create.
Status is the read-only counterpart: it observes, it never starts anything.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schedules.dao import NewScheduleDAO, ScheduleDAO
from src.schedules.exceptions import ScheduleNotFoundError
from src.schedules.service import ScheduleService
from src.schedules.worker_runtime import (
    ScheduleWorkerHealthDAO,
    ScheduleWorkerRuntime,
    ScheduleWorkerUnavailableError,
)

__all__ = [
    "CreateOperationalScheduleAppService",
    "OperationalScheduleDAO",
    "ScheduleNotOperationalError",
    "ScheduleStatusAppService",
    "ScheduleStatusDAO",
    "StartOperationalScheduleAppService",
]

NOT_OPERATIONAL_PREFIX: str = "schedule saved, but not operational"


class OperationalScheduleDAO(BaseModel):
    """A saved schedule together with the healthy worker that will fire it."""

    model_config = ConfigDict(frozen=True)

    schedule: ScheduleDAO = Field(description="The committed schedule row.")
    worker: ScheduleWorkerHealthDAO = Field(description="The healthy shared worker observation.")


class ScheduleStatusDAO(BaseModel):
    """Read-only operational status: worker health and the next due time."""

    model_config = ConfigDict(frozen=True)

    worker: ScheduleWorkerHealthDAO = Field(description="One bounded observation of the shared worker.")
    schedule: Optional[ScheduleDAO] = Field(
        default=None, description="The selected schedule when a reference was given."
    )
    next_due_at: Optional[datetime] = Field(
        default=None,
        description="The selected schedule's next due, or the earliest next due of all enabled schedules.",
    )


class ScheduleNotOperationalError(RuntimeError):
    """The schedule is saved, but no healthy worker will fire it yet."""

    def __init__(self, *, schedule: ScheduleDAO, health: ScheduleWorkerHealthDAO) -> None:
        """Record the saved schedule and the worker observation that explains why.

        Args:
            schedule (ScheduleDAO): The committed schedule; its id stays valid.
            health (ScheduleWorkerHealthDAO): The final worker observation.
        """
        super().__init__(
            f"{NOT_OPERATIONAL_PREFIX}: {health.reason or 'the schedule worker is ' + health.state}"
        )
        self.schedule: ScheduleDAO = schedule
        self.health: ScheduleWorkerHealthDAO = health


async def _activate(*, runtime: ScheduleWorkerRuntime, schedule: ScheduleDAO) -> OperationalScheduleDAO:
    """Start or reuse the shared worker for an already committed schedule.

    Args:
        runtime (ScheduleWorkerRuntime): The shared worker runtime.
        schedule (ScheduleDAO): The committed schedule.

    Returns:
        OperationalScheduleDAO: The schedule with its healthy worker.

    Raises:
        ScheduleNotOperationalError: When no healthy worker could be had.
    """
    try:
        health: ScheduleWorkerHealthDAO = await runtime.start_or_reuse()
    except ScheduleWorkerUnavailableError as error:
        raise ScheduleNotOperationalError(schedule=schedule, health=error.health) from error
    return OperationalScheduleDAO(schedule=schedule, worker=health)


class CreateOperationalScheduleAppService:
    """Create one schedule and make scheduling operational."""

    def __init__(
        self,
        *,
        schedules: ScheduleService,
        runtime: ScheduleWorkerRuntime,
        new_schedule: NewScheduleDAO,
        now: datetime,
    ) -> None:
        """Bind the collaborators and the validated definition.

        Args:
            schedules (ScheduleService): The schedule domain service.
            runtime (ScheduleWorkerRuntime): The shared worker runtime.
            new_schedule (NewScheduleDAO): The definition to create.
            now (datetime): The boundary clock instant.
        """
        self._schedules: ScheduleService = schedules
        self._runtime: ScheduleWorkerRuntime = runtime
        self._new_schedule: NewScheduleDAO = new_schedule
        self._now: datetime = now

    async def invoke(self) -> OperationalScheduleDAO:
        """Commit the schedule, then start or reuse the healthy worker.

        Returns:
            OperationalScheduleDAO: The saved schedule with its healthy worker.

        Raises:
            ScheduleInvalidError: The definition was rejected; nothing saved.
            ScheduleNameTakenError: The name is taken; nothing saved.
            ScheduleNotOperationalError: Saved, but no healthy worker.
        """
        created: ScheduleDAO = await self._schedules.create(new_schedule=self._new_schedule, now=self._now)
        return await _activate(runtime=self._runtime, schedule=created)


class StartOperationalScheduleAppService:
    """Enable one schedule (idempotently) and make scheduling operational."""

    def __init__(
        self, *, schedules: ScheduleService, runtime: ScheduleWorkerRuntime, reference: str, now: datetime
    ) -> None:
        """Bind the collaborators and the schedule reference.

        Args:
            schedules (ScheduleService): The schedule domain service.
            runtime (ScheduleWorkerRuntime): The shared worker runtime.
            reference (str): The schedule id or name.
            now (datetime): The boundary clock instant.
        """
        self._schedules: ScheduleService = schedules
        self._runtime: ScheduleWorkerRuntime = runtime
        self._reference: str = reference
        self._now: datetime = now

    async def invoke(self) -> OperationalScheduleDAO:
        """Enable the schedule (an enabled one stays as it is), then activate.

        Returns:
            OperationalScheduleDAO: The enabled schedule with its healthy worker.

        Raises:
            ScheduleNotFoundError: No active schedule matches.
            ScheduleInvalidError: A one-shot can no longer fire.
            ScheduleNotOperationalError: Enabled, but no healthy worker.
        """
        started: ScheduleDAO = await self._schedules.start(reference=self._reference, now=self._now)
        return await _activate(runtime=self._runtime, schedule=started)


class ScheduleStatusAppService:
    """Observe the shared worker and the next due time; never starts or creates anything."""

    def __init__(
        self,
        *,
        schedules: ScheduleService,
        runtime: ScheduleWorkerRuntime,
        db_path: Path,
        reference: Optional[str],
    ) -> None:
        """Bind the collaborators and the optional schedule reference.

        Args:
            schedules (ScheduleService): The schedule domain service (opened lazily).
            runtime (ScheduleWorkerRuntime): The shared worker runtime.
            db_path (Path): The schedules database; not opened when absent.
            reference (Optional[str]): The schedule id or name, or None for all.
        """
        self._schedules: ScheduleService = schedules
        self._runtime: ScheduleWorkerRuntime = runtime
        self._db_path: Path = db_path
        self._reference: Optional[str] = reference

    async def invoke(self) -> ScheduleStatusDAO:
        """Observe the worker, then read the selected schedule or the earliest next due.

        Returns:
            ScheduleStatusDAO: The status.

        Raises:
            ScheduleNotFoundError: The reference matches no active schedule.
        """
        worker: ScheduleWorkerHealthDAO = await self._runtime.inspect_health()
        schedule: Optional[ScheduleDAO] = await self._selected_schedule()
        return ScheduleStatusDAO(
            worker=worker, schedule=schedule, next_due_at=await self._next_due(schedule=schedule)
        )

    async def _selected_schedule(self) -> Optional[ScheduleDAO]:
        """Read the referenced schedule, if any.

        Returns:
            Optional[ScheduleDAO]: The schedule, or None when no reference was given.

        Raises:
            ScheduleNotFoundError: The reference matches nothing (also with no store yet).
        """
        if self._reference is None:
            return None
        if not self._db_path.exists():
            raise ScheduleNotFoundError(reference=self._reference)
        return await self._schedules.show(reference=self._reference)

    async def _next_due(self, *, schedule: Optional[ScheduleDAO]) -> Optional[datetime]:
        """Return the selected schedule's next due, or the earliest of all enabled ones.

        Args:
            schedule (Optional[ScheduleDAO]): The selected schedule.

        Returns:
            Optional[datetime]: The next due instant, if any.
        """
        if schedule is not None:
            return schedule.next_due_at
        if self._reference is not None or not self._db_path.exists():
            return None
        summaries = await self._schedules.list_by_state(state="active")
        due_times: list[datetime] = [
            summary.schedule.next_due_at for summary in summaries if summary.schedule.next_due_at is not None
        ]
        return min(due_times, default=None)
