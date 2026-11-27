"""`/schedules` slash-command acceptance tests (111.a.1 A4, A5, A11)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.schedules.dao import ScheduleDAO
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    ScheduleStateFilter,
    ScheduleSummaryDAO,
)
from src.schedules.database import ScheduleTransaction
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.database import ScheduleDatabase
from src.tui.slash_router import SlashRouter


class RecordingScheduleRepository(ScheduleRepository):
    """Delegating repository spy: counts list reads while persistence stays real."""

    def __init__(self) -> None:
        """Start with zero recorded reads."""
        self.list_read_count: int = 0

    async def list_by_state(
        self, *, state: ScheduleStateFilter, transaction: ScheduleTransaction
    ) -> list[ScheduleDAO]:
        """Record the read, then delegate to the real repository.

        Args:
            state (ScheduleStateFilter): The requested state.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleDAO]: The real repository's rows.
        """
        self.list_read_count += 1
        return await super().list_by_state(state=state, transaction=transaction)


@pytest.fixture
async def schedule_service(tmp_path: Path) -> AsyncIterator[ScheduleService]:
    """Build a real service on a tmp_path database with a recording repository spy."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    repository = RecordingScheduleRepository()
    built = ScheduleService(
        database=database,
        schedules=repository,
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    yield built


async def _seed(
    *,
    service: ScheduleService,
    name: str,
    enabled: bool,
    deleted: bool,
) -> None:
    """Create one interval schedule in the requested end state."""
    now: datetime = datetime.now(timezone.utc)
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name=name,
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
        ),
        now=now,
    )
    reference = str(created.id)
    if not enabled:
        await service.stop(reference=reference, now=now + timedelta(seconds=1))
    if deleted:
        await service.delete(reference=reference, now=now + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("line", "expected_rows", "state"),
    [
        ("/schedules", ["Active One", "Active Two"], "active"),
        ("/schedules disabled", ["Disabled One"], "disabled"),
    ],
)
async def test_schedules_lists_only_matching_rows(
    schedule_service: ScheduleService,
    line: str,
    expected_rows: list[str],
    state: str,
) -> None:
    """A4: `/schedules` and `/schedules disabled` list exactly the rows of that state."""
    await _seed(service=schedule_service, name="Active One", enabled=True, deleted=False)
    await _seed(service=schedule_service, name="Active Two", enabled=True, deleted=False)
    await _seed(service=schedule_service, name="Disabled One", enabled=False, deleted=False)
    await _seed(service=schedule_service, name="Deleted One", enabled=True, deleted=True)

    result = await SlashRouter.dispatch(line=line, session=MagicMock(), schedule_service=schedule_service)

    assert result.rendered is not None
    for row in expected_rows:
        assert row in result.rendered
    assert "Deleted One" not in result.rendered
    if state == "active":
        assert "Disabled One" not in result.rendered
    else:
        assert "Active One" not in result.rendered


async def test_schedules_rejects_unknown_argument_without_reading(
    schedule_service: ScheduleService,
) -> None:
    """A4: an unknown argument prints usage and performs zero repository reads."""
    await _seed(service=schedule_service, name="Active One", enabled=True, deleted=False)
    repository = schedule_service._schedules
    assert isinstance(repository, RecordingScheduleRepository)
    reads_before: int = repository.list_read_count

    result = await SlashRouter.dispatch(
        line="/schedules bogus", session=MagicMock(), schedule_service=schedule_service
    )

    assert result.rendered is not None
    assert "usage" in result.rendered.lower()
    assert repository.list_read_count == reads_before


async def test_empty_listing_text(schedule_service: ScheduleService) -> None:
    """A11: with no schedules the listing is exactly `No active schedules.`"""
    result = await SlashRouter.dispatch(
        line="/schedules", session=MagicMock(), schedule_service=schedule_service
    )

    assert result.rendered == "No active schedules."
    await schedule_service.close()


async def test_schedules_without_injected_service_uses_the_default_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A4: with no injected service the handler builds the default-path service and closes it."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))

    result = await SlashRouter.dispatch(line="/schedules", session=MagicMock())

    assert result.rendered == "No active schedules."
