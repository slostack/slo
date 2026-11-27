"""Service lifecycle tests (111.a.1 A2-domain, A6, A10, A14) on real SQLite."""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleStateFilter,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.exceptions import ScheduleInvalidError, ScheduleNotFoundError, ScheduleNameTakenError
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService


def _utc(*, minute: int = 0, hour: int = 12) -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=hour, minute=minute, tzinfo=timezone.utc)


def _interval_input(name: str = "Daily Summary") -> NewScheduleDAO:
    """Build a valid interval schedule input."""
    return NewScheduleDAO(
        name=name,
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
    )


@pytest.fixture
async def service(tmp_path: Path) -> AsyncIterator[ScheduleService]:
    """Build a real service on a tmp_path database."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    built = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    yield built
    await database.close()


async def test_create_assigns_a_uuid_identity(service: ScheduleService) -> None:
    """EF111-08: the schedule id is a UUID object at the domain boundary, not a bare string."""
    created = await service.create(new_schedule=_interval_input(), now=_utc())

    assert isinstance(created.id, UUID)
    assert created.id.version == 4


async def test_create_persists_one_row_and_computes_next_due(service: ScheduleService) -> None:
    """Create writes one enabled row whose next due is now + every_seconds."""
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    shown = await service.show(reference=str(created.id))
    assert shown.enabled is True
    assert shown.next_due_at == now + timedelta(seconds=60)
    assert shown.created_at == now
    assert shown.updated_at == now
    assert shown.deleted_at is None


async def test_create_persists_cwd_model_and_misfire_grace(service: ScheduleService) -> None:
    """EF111-01: cwd, model and misfire grace survive create and read back from the store."""
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Pinned Fresh",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            cwd="/tmp/scheduler-runs",
            model="openrouter:vendor/schedule-only",
            misfire_grace_seconds=120,
        ),
        now=now,
    )

    shown = await service.show(reference=str(created.id))
    assert shown.cwd == "/tmp/scheduler-runs"
    assert shown.model == "openrouter:vendor/schedule-only"
    assert shown.misfire_grace_seconds == 120


async def test_edit_persists_cwd_model_and_resets_misfire_grace(service: ScheduleService) -> None:
    """EF111-01: edit replaces the whole definition, including cwd, model and the grace default."""
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Pinned Fresh",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            cwd="/tmp/first-runs",
            misfire_grace_seconds=120,
        ),
        now=now,
    )

    edited = await service.edit(
        reference=str(created.id),
        changes=NewScheduleDAO(
            name="Pinned Fresh",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            cwd="/tmp/second-runs",
            model="openrouter:vendor/schedule-only",
        ),
        now=now + timedelta(hours=1),
    )

    shown = await service.show(reference=str(created.id))
    assert shown.cwd == "/tmp/second-runs"
    assert shown.model == "openrouter:vendor/schedule-only"
    assert shown.misfire_grace_seconds == 300
    assert edited.created_at == now


async def test_repeated_hyphen_names_share_one_key(service: ScheduleService) -> None:
    """EF111-04: Repo--Watch and Repo-Watch normalise to the same key, so the second is taken."""
    now: datetime = _utc()
    await service.create(
        new_schedule=NewScheduleDAO(
            name="Repo--Watch",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
        ),
        now=now,
    )

    with pytest.raises(ScheduleNameTakenError):
        await service.create(
            new_schedule=NewScheduleDAO(
                name="Repo-Watch",
                prompt="Summarise the repo",
                trigger=IntervalTriggerDAO(every_seconds=60),
            ),
            now=now,
        )


async def test_uuid_shaped_name_falls_back_to_name_lookup(service: ScheduleService) -> None:
    """EF111-04: a UUID-shaped reference that matches no id falls back to the name key."""
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="123e4567-e89b-42d3-a456-426614174000",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
        ),
        now=now,
    )

    found = await service.show(reference="123e4567-e89b-42d3-a456-426614174000")
    assert found.id == created.id


async def test_create_rejects_a_taken_name_without_a_row(service: ScheduleService) -> None:
    """A second create with the same name key raises and leaves one row."""
    now: datetime = _utc()
    await service.create(new_schedule=_interval_input(), now=now)

    with pytest.raises(ScheduleNameTakenError):
        await service.create(new_schedule=_interval_input(name="daily summary"), now=now)

    listed = await service.list_by_state(state="active")
    assert len(listed) == 1


async def test_create_rejects_invalid_inputs_without_a_row(service: ScheduleService) -> None:
    """Blank names, empty prompts and sub-floor intervals raise before any write."""
    now: datetime = _utc()
    with pytest.raises(ValidationError):
        NewScheduleDAO(name="   ", prompt="P", trigger=IntervalTriggerDAO(every_seconds=60))
    with pytest.raises(ValidationError):
        NewScheduleDAO(name="Blank Prompt", prompt="", trigger=IntervalTriggerDAO(every_seconds=60))
    with pytest.raises(ValidationError):
        NewScheduleDAO(name="Sub Floor", prompt="P", trigger=IntervalTriggerDAO(every_seconds=14))

    listed = await service.list_by_state(state="active")
    assert listed == []


async def test_create_rejects_a_past_one_shot_without_a_row(service: ScheduleService) -> None:
    """A one-shot run_at at or before now raises and leaves no row."""
    now: datetime = _utc()
    with pytest.raises(ScheduleInvalidError):
        await service.create(
            new_schedule=NewScheduleDAO(
                name="Past Shot",
                prompt="P",
                trigger=OneShotTriggerDAO(run_at=now - timedelta(seconds=1)),
            ),
            now=now,
        )

    listed = await service.list_by_state(state="active")
    assert listed == []


async def test_edit_recomputes_next_due_only_when_enabled(service: ScheduleService) -> None:
    """A10: editing an enabled schedule recomputes next due; a disabled one stays NULL."""
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    later: datetime = now + timedelta(hours=3)
    edited = await service.edit(
        reference=str(created.id),
        changes=NewScheduleDAO(
            name="Daily Summary",
            prompt="Summarise the repo",
            trigger=OneShotTriggerDAO(run_at=later + timedelta(seconds=120)),
        ),
        now=later,
    )
    assert edited.next_due_at == later + timedelta(seconds=120)
    assert edited.enabled is True
    # EF111-07: prove the persisted row, not the returned object.
    reloaded_enabled = await service.show(reference=str(created.id))
    assert reloaded_enabled.enabled is True
    assert reloaded_enabled.next_due_at == later + timedelta(seconds=120)

    await service.stop(reference=str(created.id), now=later)
    disabled = await service.edit(
        reference=str(created.id),
        changes=NewScheduleDAO(
            name="Daily Summary",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=30),
        ),
        now=later,
    )
    assert disabled.enabled is False
    assert disabled.next_due_at is None
    # EF111-07: the disabled row kept enabled=0 after the write, read back from the store.
    reloaded_disabled = await service.show(reference=str(created.id))
    assert reloaded_disabled.enabled is False
    assert reloaded_disabled.next_due_at is None


async def test_edit_rejects_an_unknown_reference(service: ScheduleService) -> None:
    """Editing an unknown reference raises and writes nothing."""
    now: datetime = _utc()
    with pytest.raises(ScheduleNotFoundError):
        await service.edit(reference="missing", changes=_interval_input(), now=now)
    assert await service.list_by_state(state="active") == []


async def test_stop_then_start_recomputes_next_due_without_replay(service: ScheduleService) -> None:
    """A6: stop clears next due; start recomputes from now with no missed-time replay."""
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    stopped = await service.stop(reference=str(created.id), now=now + timedelta(hours=1))
    assert stopped.enabled is False
    assert stopped.next_due_at is None

    restarted = await service.start(reference=str(created.id), now=now + timedelta(hours=4))
    assert restarted.enabled is True
    assert restarted.next_due_at == now + timedelta(hours=4, seconds=60)

    shown = await service.show(reference=str(created.id))
    assert shown.enabled is True
    assert shown.next_due_at == now + timedelta(hours=4, seconds=60)


async def test_start_of_a_past_one_shot_is_rejected(service: ScheduleService) -> None:
    """Starting a one-shot whose run_at has passed raises and writes nothing."""
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="One Shot",
            prompt="P",
            trigger=OneShotTriggerDAO(run_at=now + timedelta(seconds=60)),
        ),
        now=now,
    )
    await service.stop(reference=str(created.id), now=now)

    with pytest.raises(ScheduleInvalidError):
        await service.start(reference=str(created.id), now=now + timedelta(hours=1))

    shown = await service.show(reference=str(created.id))
    assert shown.enabled is False
    assert shown.next_due_at is None


async def test_delete_soft_deletes_and_frees_the_name(service: ScheduleService) -> None:
    """A7: delete hides the row and frees the name for a new schedule."""
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    deleted = await service.delete(reference=str(created.id), now=now + timedelta(hours=1))
    assert deleted.deleted_at == now + timedelta(hours=1)

    with pytest.raises(ScheduleNotFoundError):
        await service.show(reference=str(created.id))
    assert await service.list_by_state(state="active") == []
    assert await service.list_by_state(state="disabled") == []

    recreated = await service.create(new_schedule=_interval_input(), now=now + timedelta(hours=2))
    assert recreated.id != created.id


async def test_reference_resolves_by_id_or_name_among_active_rows(service: ScheduleService) -> None:
    """A14: the id and a case-insensitive name select the same row; deleted rows never match."""
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(name="Repo Watch"), now=now)

    by_id = await service.show(reference=str(created.id))
    by_name = await service.show(reference="REPO WATCH")
    assert by_id.id == by_name.id == created.id

    with pytest.raises(ScheduleNotFoundError):
        await service.show(reference="unknown-name")

    await service.delete(reference=str(created.id), now=now)
    with pytest.raises(ScheduleNotFoundError):
        await service.show(reference=str(created.id))
    with pytest.raises(ScheduleNotFoundError):
        await service.show(reference="Repo Watch")
