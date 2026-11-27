"""Schedule timing — the pure rules for validating and placing due times."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from cronsim import CronSim

from src.schedules.dao import CronTriggerDAO, IntervalTriggerDAO, OneShotTriggerDAO, TriggerDAO
from src.schedules.exceptions import ScheduleInvalidError

__all__ = ["ScheduleTiming"]


class ScheduleTiming:
    """The only place that knows the three trigger rules; never reads the clock."""

    @classmethod
    def validate(cls, *, trigger: TriggerDAO, now: datetime) -> None:
        """Reject a trigger that cannot fire.

        Args:
            trigger (TriggerDAO): The trigger to check.
            now (datetime): The current instant supplied by the boundary.

        Raises:
            ScheduleInvalidError: When an interval is below the floor, a one-shot is
                not in the future, or a cron expression or timezone is unusable.
        """
        if isinstance(trigger, IntervalTriggerDAO):
            return
        if isinstance(trigger, OneShotTriggerDAO):
            if trigger.run_at <= now:
                raise ScheduleInvalidError(reason="one-shot run_at must be in the future")
            return
        cls._validate_cron(trigger=trigger, now=now)

    @classmethod
    def first_due_at(cls, *, trigger: TriggerDAO, created_at: datetime) -> Optional[datetime]:
        """Return the first due instant for a freshly created schedule.

        Args:
            trigger (TriggerDAO): The trigger to place.
            created_at (datetime): The schedule's creation instant.

        Returns:
            Optional[datetime]: The first due instant, or None when a one-shot is
                already past.
        """
        if isinstance(trigger, IntervalTriggerDAO):
            if trigger.anchor is None:
                return created_at + timedelta(seconds=trigger.every_seconds)
            return cls._first_after_anchor(trigger=trigger, created_at=created_at)
        if isinstance(trigger, OneShotTriggerDAO):
            return trigger.run_at if trigger.run_at > created_at else None
        return cls._cron_after(trigger=trigger, after=created_at)

    @classmethod
    def next_due_after(cls, *, trigger: TriggerDAO, after: datetime) -> Optional[datetime]:
        """Return the next due instant strictly after the given instant.

        Args:
            trigger (TriggerDAO): The trigger to place.
            after (datetime): The instant the previous fire happened.

        Returns:
            Optional[datetime]: The next due instant, or None for a one-shot.
        """
        if isinstance(trigger, IntervalTriggerDAO):
            return after + timedelta(seconds=trigger.every_seconds)
        if isinstance(trigger, OneShotTriggerDAO):
            return None
        return cls._cron_after(trigger=trigger, after=after)

    @classmethod
    def catch_up_to(
        cls,
        *,
        trigger: TriggerDAO,
        missed_due_at: datetime,
        now: datetime,
    ) -> Optional[datetime]:
        """Return the first due instant strictly after ``now`` on the missed phase.

        Args:
            trigger (TriggerDAO): The trigger to place.
            missed_due_at (datetime): The missed due instant defining the phase.
            now (datetime): The boundary clock instant supplied by the caller.

        Returns:
            Optional[datetime]: The first due instant strictly after ``now`` on
                the phase of ``missed_due_at``, or None for a one-shot.
        """
        if isinstance(trigger, OneShotTriggerDAO):
            return None
        if isinstance(trigger, IntervalTriggerDAO):
            elapsed: int = int((now - missed_due_at).total_seconds())
            steps: int = elapsed // trigger.every_seconds + 1
            return missed_due_at + timedelta(seconds=steps * trigger.every_seconds)
        return cls._cron_after(trigger=trigger, after=now)

    @classmethod
    def _validate_cron(cls, *, trigger: CronTriggerDAO, now: datetime) -> None:
        """Reject an unparseable cron expression or an unknown timezone.

        Args:
            trigger (CronTriggerDAO): The cron trigger to check.
            now (datetime): The caller-supplied instant the expression is anchored at.

        Raises:
            ScheduleInvalidError: When the expression or timezone is unusable.
        """
        try:
            ZoneInfo(trigger.tz)
        except Exception as error:
            raise ScheduleInvalidError(reason=f"unknown timezone: {trigger.tz}") from error
        try:
            CronSim(trigger.expression, now.astimezone(ZoneInfo(trigger.tz)))
        except Exception as error:
            raise ScheduleInvalidError(reason=f"invalid cron expression: {trigger.expression}") from error

    @classmethod
    def _first_after_anchor(cls, *, trigger: IntervalTriggerDAO, created_at: datetime) -> datetime:
        """Return the first ``anchor + k * every_seconds`` strictly after ``created_at``.

        Args:
            trigger (IntervalTriggerDAO): The anchored interval trigger.
            created_at (datetime): The schedule's creation instant.

        Returns:
            datetime: The first anchored due instant.
        """
        anchor: Optional[datetime] = trigger.anchor
        if anchor is None:
            raise ValueError("anchor must not be None")
        if created_at < anchor:
            return anchor
        elapsed: int = int((created_at - anchor).total_seconds())
        steps: int = elapsed // trigger.every_seconds + 1
        return anchor + timedelta(seconds=steps * trigger.every_seconds)

    @classmethod
    def _cron_after(cls, *, trigger: CronTriggerDAO, after: datetime) -> datetime:
        """Return the next cron match strictly after the given instant, in UTC.

        Args:
            trigger (CronTriggerDAO): The cron trigger to place.
            after (datetime): The instant the previous fire happened.

        Returns:
            datetime: The next due instant in UTC.
        """
        zone: ZoneInfo = ZoneInfo(trigger.tz)
        local_after: datetime = after.astimezone(zone)
        local_next: datetime = next(iter(CronSim(trigger.expression, local_after)))
        return local_next.astimezone(timezone.utc)
