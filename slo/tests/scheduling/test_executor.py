"""Tests for the scheduling runtime executor and cleanup helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.scheduling.dao import (
    LoadedScheduleDAO,
    OneShotTriggerDAO,
    ScheduleDefinitionDAO,
    ScheduleRunRecordDAO,
    ScheduleSessionPolicyDAO,
)
from src.scheduling.runtime.cleanup import ScheduleCleanupService
from src.scheduling.runtime.dao import ResolvedSessionTargetDAO, ScheduleSubprocessResultDAO
from src.scheduling.runtime.executor import ScheduleExecutor
from src.scheduling.runtime.fire_lock import ScheduleFireLockFactory
from src.scheduling.runtime.reporting import ScheduleReportWriter
from src.scheduling.store import ScheduleStore


def _utc_datetime(*, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a deterministic aware UTC datetime.

    Args:
        year (int): UTC year.
        month (int): UTC month.
        day (int): UTC day.
        hour (int, optional): UTC hour. Defaults to 0.
        minute (int, optional): UTC minute. Defaults to 0.

    Returns:
        datetime: Constructed aware datetime.
    """
    return datetime(year=year, month=month, day=day, hour=hour, minute=minute, tzinfo=timezone.utc)


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect ``ScheduleStore`` into a test-local root.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        tmp_path (Path): Test-local temp directory.
    """
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))


def _build_definition(
    *,
    schedule_id: str,
    session_mode: str,
    enabled: bool = True,
) -> ScheduleDefinitionDAO:
    """Build a schedule definition for executor tests.

    Args:
        schedule_id (str): Stable schedule identifier.
        session_mode (str): Fresh or continuous.
        enabled (bool, optional): Whether the schedule is enabled.

    Returns:
        ScheduleDefinitionDAO: Test definition.
    """
    return ScheduleDefinitionDAO(
        schedule_id=schedule_id,
        name=f"Schedule {schedule_id}",
        name_key=f"schedule-{schedule_id}",
        enabled=enabled,
        trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=12, hour=10)),
        prompt="Check the repo and summarize new failures.",
        cwd="/tmp/project",
        model="gpt-5.4",
        session_mode=session_mode,  # type: ignore[arg-type]
        session_policy=(
            ScheduleSessionPolicyDAO(
                session_reference="release-prep",
                coalescing_mode="latest_by_key",
                coalescing_key="repo-watch",
            )
            if session_mode == "continuous"
            else None
        ),
    )


class _FakeRunner:
    """Test double for ``ScheduleSubprocessRunner``."""

    def __init__(self, *, result: ScheduleSubprocessResultDAO) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def run_fresh(self, **kwargs) -> ScheduleSubprocessResultDAO:
        self.calls.append(("fresh", kwargs))
        return self.result

    async def run_resume(self, **kwargs) -> ScheduleSubprocessResultDAO:
        self.calls.append(("resume", kwargs))
        return self.result


class _FakeLock:
    """Fixed-result overlap lock."""

    def __init__(self, *, acquired: bool) -> None:
        self._acquired = acquired

    async def acquire(self) -> bool:
        return self._acquired

    async def release(self) -> None:
        return None


class _FakeLockFactory:
    """Build fixed-result overlap locks."""

    def __init__(self, *, acquired: bool) -> None:
        self._acquired = acquired

    def build(self, *, schedule_id: str) -> _FakeLock:
        del schedule_id
        return _FakeLock(acquired=self._acquired)


class _FakeTargetResolver:
    """Test double for ``SessionTargetResolver``."""

    def __init__(self, *, target: ResolvedSessionTargetDAO) -> None:
        self.target = target

    async def resolve(self, **kwargs) -> ResolvedSessionTargetDAO:
        del kwargs
        return self.target


class _FakeLeaseStore:
    """Test double for active/inactive target classification."""

    def __init__(self, *, active: bool) -> None:
        self.active = active

    async def is_active(self, *, session_id: str, now=None) -> bool:
        del session_id, now
        return self.active


class _FakeInboxStore:
    """Test double for SessionInbox enqueue behavior."""

    def __init__(self, *, result: str) -> None:
        self.result = result
        self.messages: list[SessionInboxMessageDAO] = []

    async def enqueue(self, *, message: SessionInboxMessageDAO):
        from src.agents.slo_agent.history.inbox.dao import InboxEnqueueResultDAO

        self.messages.append(message)
        return InboxEnqueueResultDAO(
            result=self.result,  # type: ignore[arg-type]
            message=message,
            replaced_message_id="older-message" if self.result == "coalesced" else None,
        )


def _load_run_records(*, schedule_id: str) -> list[ScheduleRunRecordDAO]:
    """Load persisted run records for ``schedule_id``.

    Args:
        schedule_id (str): Schedule identifier.

    Returns:
        list[ScheduleRunRecordDAO]: Persisted run records.
    """
    runs_dir: Path = ScheduleStore.directory_for(schedule_id=schedule_id) / "runs"
    return [
        ScheduleRunRecordDAO.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob("*.json"))
    ]


class TestScheduleExecutor:
    """Fresh, resume, queue, and overlap runtime paths."""

    @pytest.mark.asyncio
    async def test_disabled_schedule_records_skipped_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disabled schedules write one skipped record and do not call the runner."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-disabled",
            session_mode="fresh",
            enabled=False,
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(status="completed", exit_code=0, summary="done"),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert runner.calls == []
        assert records[0].delivery_path == "none"
        assert records[0].delivery_state == "skipped_disabled"

    @pytest.mark.asyncio
    async def test_overlapping_fire_records_skipped_overlapping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failure to acquire the overlap lock records `skipped_overlapping`."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-overlap", session_mode="fresh"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        executor: ScheduleExecutor = ScheduleExecutor(
            fire_lock_factory=cast(Any, _FakeLockFactory(acquired=False)),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert records[0].delivery_path == "none"
        assert records[0].delivery_state == "skipped_overlapping"

    @pytest.mark.asyncio
    async def test_fresh_mode_launches_headless_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fresh schedules run the fresh headless path and persist the result."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-fresh", session_mode="fresh"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(
                status="completed",
                exit_code=0,
                session_id=None,
                summary="fresh summary",
                stdout_summary="stdout",
                stderr_summary="",
            ),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert runner.calls[0][0] == "fresh"
        assert records[0].delivery_path == "fresh_headless"
        assert records[0].delivery_state == "executed"

    @pytest.mark.asyncio
    async def test_continuous_inactive_target_launches_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inactive continuous targets use the headless `--resume` path."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-resume", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(
                status="completed",
                exit_code=0,
                session_id="session-123",
                summary="resume summary",
                stdout_summary="stdout",
                stderr_summary="",
            ),
        )
        target_resolver = _FakeTargetResolver(
            target=ResolvedSessionTargetDAO(
                resolved_reference="release-prep",
                target_session_id="session-123",
                explicit_session_id=None,
            ),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, target_resolver),
            session_lease_store=cast(Any, _FakeLeaseStore(active=False)),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert runner.calls[0][0] == "resume"
        assert records[0].delivery_path == "resume_headless"
        assert records[0].session_id == "session-123"

    @pytest.mark.asyncio
    async def test_continuous_active_target_enqueues_inbox_instead_of_running_subprocess(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Active continuous targets enqueue inbox work and skip the runner."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-queue", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(status="completed", exit_code=0, summary="unused"),
        )
        inbox_store = _FakeInboxStore(result="queued")
        target_resolver = _FakeTargetResolver(
            target=ResolvedSessionTargetDAO(
                resolved_reference="release-prep",
                target_session_id="session-123",
                explicit_session_id=None,
            ),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, target_resolver),
            session_lease_store=cast(Any, _FakeLeaseStore(active=True)),
            session_inbox_store=cast(Any, inbox_store),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert runner.calls == []
        assert len(inbox_store.messages) == 1
        assert inbox_store.messages[0].run_id == records[0].run_id
        assert records[0].delivery_path == "session_inbox"
        assert records[0].delivery_state == "queued"

    @pytest.mark.asyncio
    async def test_coalesced_enqueue_records_coalesced_delivery_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Coalesced active-session enqueues persist the `coalesced` delivery state."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-coalesce", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        inbox_store = _FakeInboxStore(result="coalesced")
        target_resolver = _FakeTargetResolver(
            target=ResolvedSessionTargetDAO(
                resolved_reference="release-prep",
                target_session_id="session-123",
                explicit_session_id=None,
            ),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            target_resolver=cast(Any, target_resolver),
            session_lease_store=cast(Any, _FakeLeaseStore(active=True)),
            session_inbox_store=cast(Any, inbox_store),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert records[0].delivery_state == "coalesced"
        assert records[0].coalesced_fire_count == 1


class TestScheduleCleanupService:
    """Pruning immutable fire records under ``runs/``."""

    def test_prune_keeps_newest_records(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cleanup removes older run files and keeps the newest `keep` count."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-cleanup", session_mode="fresh"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        records_by_minute: dict[int, str] = {}
        for index in range(5):
            run_id: str = str(uuid4())
            records_by_minute[index] = run_id
            record: ScheduleRunRecordDAO = ScheduleRunRecordDAO(
                run_id=run_id,
                schedule_id=definition.schedule_id,
                started_at=_utc_datetime(year=2026, month=7, day=12, hour=10, minute=index),
                finished_at=_utc_datetime(year=2026, month=7, day=12, hour=10, minute=index),
                status="completed",
                delivery_path="fresh_headless",
                delivery_state="executed",
                session_id=None,
                target_session_id=None,
                exit_code=0,
                summary=f"run {index}",
            )
            ScheduleStore.append_run_record(schedule_id=definition.schedule_id, record=record)

        deleted_count: int = ScheduleCleanupService().prune(schedule_id=definition.schedule_id, keep=2)
        remaining_records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert deleted_count == 3
        assert {record.run_id for record in remaining_records} == {
            records_by_minute[3],
            records_by_minute[4],
        }
