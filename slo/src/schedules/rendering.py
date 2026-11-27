"""`ScheduleTableRenderer` — the one table format shared by CLI `list` and `/schedules`."""

from __future__ import annotations

from datetime import datetime

from src.schedules.dao import (
    CronTriggerDAO,
    IntervalTriggerDAO,
    OneShotTriggerDAO,
    ScheduleStateFilter,
    ScheduleSummaryDAO,
)

__all__ = ["ScheduleTableRenderer"]

_HEADER: str = "Name | Trigger | Next Due | Recipient Session | Last Status"


def trigger_summary(*, trigger: object) -> str:
    """Return a one-line trigger summary.

    Args:
        trigger (object): The trigger DAO of one schedule.

    Returns:
        str: ``cron:<expression>``, ``interval:<seconds>s`` or ``one-shot:<iso>``.
    """
    if isinstance(trigger, CronTriggerDAO):
        return f"cron:{trigger.expression}"
    if isinstance(trigger, IntervalTriggerDAO):
        return f"interval:{trigger.every_seconds}s"
    if isinstance(trigger, OneShotTriggerDAO):
        return f"one-shot:{trigger.run_at.isoformat()}"
    return f"unknown:{type(trigger).__name__}"


def _recipient_summary(*, summary: ScheduleSummaryDAO) -> str:
    """Return the recipient-session summary for one row.

    Args:
        summary (ScheduleSummaryDAO): The row to describe.

    Returns:
        str: ``-`` for fresh runs, ``fresh per invocation`` for a continuous
            schedule without a reference (D5 part 3), otherwise the session
            reference.
    """
    if summary.schedule.session_mode == "fresh":
        return "-"
    if summary.schedule.session_reference is None:
        return "fresh per invocation"
    return summary.schedule.session_reference


def _next_due_summary(*, summary: ScheduleSummaryDAO) -> str:
    """Return the next-due summary for one row.

    Args:
        summary (ScheduleSummaryDAO): The row to describe.

    Returns:
        str: The UTC instant, or ``-`` when disabled.
    """
    next_due_at: datetime | None = summary.schedule.next_due_at
    if next_due_at is None:
        return "-"
    return next_due_at.isoformat()


class ScheduleTableRenderer:
    """Renders the five-column schedule table; no state, no repository access."""

    @classmethod
    def render(
        cls,
        *,
        schedules: list[ScheduleSummaryDAO],
        state: ScheduleStateFilter,
    ) -> str:
        """Render one state's rows as a table.

        Args:
            schedules (list[ScheduleSummaryDAO]): The rows in repository order.
            state (ScheduleStateFilter): The state the list was taken for.

        Returns:
            str: The header plus one line per row, or the empty-state line.
        """
        if not schedules:
            return f"No {'active' if state == 'active' else 'disabled'} schedules."
        lines: list[str] = [_HEADER]
        for summary in schedules:
            lines.append(
                " | ".join(
                    (
                        summary.schedule.name,
                        trigger_summary(trigger=summary.schedule.trigger),
                        _next_due_summary(summary=summary),
                        _recipient_summary(summary=summary),
                        summary.last_invocation_status or "-",
                    )
                )
            )
        return "\n".join(lines)
