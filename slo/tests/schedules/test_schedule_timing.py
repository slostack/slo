"""Timing rule unit tests (111.a.1 A9)."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.schedules.dao import CronTriggerDAO, IntervalTriggerDAO, OneShotTriggerDAO
from src.schedules.exceptions import ScheduleInvalidError
from src.schedules.timing import ScheduleTiming


def _utc(*, second: int = 0, minute: int = 0, hour: int = 12) -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=hour, minute=minute, second=second, tzinfo=timezone.utc)


def test_timing_module_never_reads_the_wall_clock() -> None:
    """EF111-08: ScheduleTiming is pure — the source never calls the wall clock."""
    source: str = Path("src/schedules/timing.py").read_text(encoding="utf-8")
    definitions: list[ast.stmt] = list(ast.parse(source).body)
    calls: list[str] = [
        ast.unparse(call.func)
        for definition in definitions
        if isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for call in ast.walk(definition)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]
    forbidden: set[str] = {"datetime.now", "datetime.utcnow", "datetime.today"}
    assert not forbidden.intersection(calls), f"clock reads found: {sorted(forbidden.intersection(calls))}"


def test_interval_floor_14_and_15() -> None:
    """An interval below 15 seconds is rejected; 15 seconds is accepted."""
    with pytest.raises(ValidationError):
        IntervalTriggerDAO(every_seconds=14)
    accepted: IntervalTriggerDAO = IntervalTriggerDAO(every_seconds=15)
    assert accepted.every_seconds == 15


def test_one_shot_past_and_future_run_at() -> None:
    """A one-shot run_at must be strictly after now; the past is rejected."""
    now: datetime = _utc()
    future: OneShotTriggerDAO = OneShotTriggerDAO(run_at=now + timedelta(seconds=1))
    past: OneShotTriggerDAO = OneShotTriggerDAO(run_at=now - timedelta(seconds=1))
    equal: OneShotTriggerDAO = OneShotTriggerDAO(run_at=now)

    ScheduleTiming.validate(trigger=future, now=now)
    with pytest.raises(ScheduleInvalidError):
        ScheduleTiming.validate(trigger=past, now=now)
    with pytest.raises(ScheduleInvalidError):
        ScheduleTiming.validate(trigger=equal, now=now)


def test_one_shot_naive_run_at_is_rejected() -> None:
    """A naive run_at is rejected by the trigger DAO."""
    with pytest.raises(ValidationError):
        OneShotTriggerDAO(run_at=datetime(2026, 1, 1, 12, 0, 0))


def test_first_due_at_with_and_without_anchor() -> None:
    """Without anchor the first due is created_at + every_seconds; with anchor the first step after it."""
    created_at: datetime = _utc()
    plain: IntervalTriggerDAO = IntervalTriggerDAO(every_seconds=60)
    assert ScheduleTiming.first_due_at(trigger=plain, created_at=created_at) == created_at + timedelta(
        seconds=60
    )

    anchored: IntervalTriggerDAO = IntervalTriggerDAO(
        every_seconds=60,
        anchor=_utc(second=30, minute=59, hour=11),
    )
    # anchor 11:59:30; the first anchor + k * 60 strictly after 12:00:00 is 12:00:30.
    assert ScheduleTiming.first_due_at(trigger=anchored, created_at=created_at) == _utc(second=30)

    anchored_before: IntervalTriggerDAO = IntervalTriggerDAO(
        every_seconds=60,
        anchor=_utc(hour=11, minute=58),
    )
    # anchor 11:58:00 lies before creation; the first step strictly after created_at is 12:01:00.
    assert ScheduleTiming.first_due_at(trigger=anchored_before, created_at=created_at) == _utc(minute=1)


def test_one_shot_first_due_at_returns_none_once_passed() -> None:
    """A one-shot run_at at or before creation yields no first due."""
    now: datetime = _utc()
    future: OneShotTriggerDAO = OneShotTriggerDAO(run_at=now + timedelta(seconds=900))
    assert ScheduleTiming.first_due_at(trigger=future, created_at=now) == now + timedelta(seconds=900)
    passed: OneShotTriggerDAO = OneShotTriggerDAO(run_at=now - timedelta(seconds=1))
    assert ScheduleTiming.first_due_at(trigger=passed, created_at=now) is None


def test_interval_next_due_after_is_anchor_free() -> None:
    """The next due for an interval is after + every_seconds, ignoring the anchor."""
    after: datetime = _utc(minute=30)
    trigger: IntervalTriggerDAO = IntervalTriggerDAO(every_seconds=60, anchor=_utc())
    assert ScheduleTiming.next_due_after(trigger=trigger, after=after) == after + timedelta(seconds=60)


def test_one_shot_next_due_after_is_none() -> None:
    """A one-shot never repeats, so the next due after any instant is None."""
    trigger: OneShotTriggerDAO = OneShotTriggerDAO(run_at=_utc())
    assert ScheduleTiming.next_due_after(trigger=trigger, after=_utc(minute=1)) is None


def test_cron_validate_rejects_bad_expression_and_unknown_timezone() -> None:
    """An unparsable expression or unknown timezone is rejected."""
    now: datetime = _utc()
    with pytest.raises(ScheduleInvalidError):
        ScheduleTiming.validate(trigger=CronTriggerDAO(expression="not a cron", tz="UTC"), now=now)
    with pytest.raises(ScheduleInvalidError):
        ScheduleTiming.validate(trigger=CronTriggerDAO(expression="*/5 * * * *", tz="Mars/Olympus"), now=now)
    ScheduleTiming.validate(trigger=CronTriggerDAO(expression="*/5 * * * *", tz="UTC"), now=now)


def test_cron_next_due_after_finds_the_next_match() -> None:
    """The cron next due is the first match strictly after the given instant."""
    after: datetime = _utc(minute=3)
    trigger: CronTriggerDAO = CronTriggerDAO(expression="*/5 * * * *", tz="UTC")
    assert ScheduleTiming.next_due_after(trigger=trigger, after=after) == _utc(minute=5)


def test_cron_first_due_at_finds_the_next_match_after_creation() -> None:
    """The cron first due is the first match strictly after creation."""
    created_at: datetime = _utc(minute=3)
    trigger: CronTriggerDAO = CronTriggerDAO(expression="0 9 * * *", tz="UTC")
    assert ScheduleTiming.first_due_at(trigger=trigger, created_at=created_at) == datetime(
        2026, 1, 2, 9, 0, 0, tzinfo=timezone.utc
    )


def test_cron_next_due_after_respects_the_trigger_timezone() -> None:
    """A cron trigger in another timezone returns its next match converted to UTC."""
    after: datetime = _utc(minute=3)
    trigger: CronTriggerDAO = CronTriggerDAO(expression="30 14 * * *", tz="Europe/Berlin")
    # 14:30 Berlin on 2026-01-01 is 13:30 UTC.
    assert ScheduleTiming.next_due_after(trigger=trigger, after=after) == datetime(
        2026, 1, 1, 13, 30, 0, tzinfo=ZoneInfo("UTC")
    )


def test_catch_up_to_interval_stays_on_the_missed_phase() -> None:
    """A1: the catch-up instant is the first phase point strictly after now."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    missed = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
    trigger = IntervalTriggerDAO(every_seconds=900)

    caught = ScheduleTiming.catch_up_to(trigger=trigger, missed_due_at=missed, now=now)

    assert caught is not None
    assert caught == datetime(2026, 1, 1, 12, 15, 0, tzinfo=timezone.utc)


def test_catch_up_to_one_shot_is_none() -> None:
    """A1: a one-shot has no catch-up instant; the schedule disables instead."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    missed = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
    trigger = OneShotTriggerDAO(run_at=missed)

    caught = ScheduleTiming.catch_up_to(trigger=trigger, missed_due_at=missed, now=now)

    assert caught is None


def test_catch_up_to_cron_finds_the_next_match_after_now() -> None:
    """A1: a cron trigger's catch-up is the next expression match after now."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    missed = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
    trigger = CronTriggerDAO(expression="0 12 * * *", tz="UTC")

    caught = ScheduleTiming.catch_up_to(trigger=trigger, missed_due_at=missed, now=now)

    assert caught is not None
    assert caught == datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
