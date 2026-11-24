"""Tests for the scheduling runtime executor and cleanup helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
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


_TARGET_SESSION_ID: str = "6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
"""Canonical UUID session id of the TUI session the continuous schedules target."""


async def _lease_store_with_active_owner(*, tmp_path: Path) -> SessionOwnershipLeaseStore:
    """Return a real lease store whose target session is owned by a live TUI.

    Args:
        tmp_path (Path): Test-local temp directory holding the history root.

    Returns:
        SessionOwnershipLeaseStore: Store with an unexpired ``owner.json`` lease.
    """
    store: SessionOwnershipLeaseStore = SessionOwnershipLeaseStore(history_root=tmp_path / "history")
    await store.acquire(session_id=_TARGET_SESSION_ID, owner_id="tui-owner-test", ttl_seconds=300.0)
    return store


async def _gateway_with_open_target(*, tmp_path: Path) -> ChannelGateway:
    """Open a real channel gateway and register the target TUI agent, as its poller does.

    Args:
        tmp_path (Path): Test-local temp directory holding ``channels.db``.

    Returns:
        ChannelGateway: Open gateway with the target agent participant open.
    """
    gateway: ChannelGateway = ChannelGateway(
        repository=ChannelRepository(db_path=tmp_path / "channels" / "channels.db")
    )
    await gateway.open()
    await gateway.register_agent(session_id=UUID(_TARGET_SESSION_ID), name="slo target", durable_inbox=True)
    return gateway


def _active_target_resolver() -> "_FakeTargetResolver":
    """Return a resolver stub that always resolves to the target TUI session.

    Returns:
        _FakeTargetResolver: Resolver stub for ``_TARGET_SESSION_ID``.
    """
    return _FakeTargetResolver(
        target=ResolvedSessionTargetDAO(
            resolved_reference="release-prep",
            target_session_id=_TARGET_SESSION_ID,
            explicit_session_id=None,
        ),
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
    async def test_continuous_inactive_target_launches_resume_and_queues_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I2: with no live lease the headless ``--resume`` path runs and no channel row is written."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-resume", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(
                status="completed",
                exit_code=0,
                session_id=_TARGET_SESSION_ID,
                summary="resume summary",
                stdout_summary="stdout",
                stderr_summary="",
            ),
        )
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=SessionOwnershipLeaseStore(history_root=tmp_path / "history"),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        await gateway.close()

        assert exit_code == 0
        assert runner.calls == [
            (
                "resume",
                {
                    "definition": definition,
                    "session_reference": "release-prep",
                    "target_session_id": _TARGET_SESSION_ID,
                },
            )
        ]
        assert records[0].delivery_path == "resume_headless"
        assert records[0].delivery_state == "executed"
        assert records[0].session_id == _TARGET_SESSION_ID
        assert pending == []

    @pytest.mark.asyncio
    async def test_expired_lease_is_inactive_and_launches_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """I2: a stale ``owner.json`` (crashed TUI) still chooses the headless path, unchanged."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-stale-lease", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        lease_store: SessionOwnershipLeaseStore = SessionOwnershipLeaseStore(
            history_root=tmp_path / "history"
        )
        await lease_store.acquire(session_id=_TARGET_SESSION_ID, owner_id="tui-crashed", ttl_seconds=-1.0)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(status="completed", exit_code=0, summary="resumed"),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=lease_store,
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert [call[0] for call in runner.calls] == ["resume"]
        assert records[0].delivery_path == "resume_headless"

    @pytest.mark.asyncio
    async def test_active_lease_sends_one_scheduler_prompt_row_instead_of_running_subprocess(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """I1: an active lease queues exactly one channel prompt from the schedule's sender."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-queue", session_mode="continuous"
        ).model_copy(update={"model": "openrouter:vendor/scheduled"})
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(status="completed", exit_code=0, summary="unused"),
        )
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        await gateway.close()

        assert exit_code == 0
        assert runner.calls == []
        assert len(pending) == 1
        row: ChannelMessageDAO = pending[0]
        assert row.message_type == "prompt"
        assert row.message_contents == definition.prompt
        assert row.sender_name == f"scheduler {definition.name}"
        assert row.recipient_id == UUID(_TARGET_SESSION_ID)
        assert row.agent_session_id == UUID(_TARGET_SESSION_ID)
        assert row.coalesce_key == "repo-watch"
        assert row.forced_at is None
        assert len(records) == 1
        assert records[0].delivery_path == "session_channel"
        assert records[0].delivery_state == "queued"
        assert records[0].target_session_id == _TARGET_SESSION_ID
        assert records[0].summary == definition.prompt[:200]
        assert records[0].coalesced_fire_count == 0

    @pytest.mark.asyncio
    async def test_two_fires_with_the_same_coalescing_key_leave_one_pending_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """I1: the newer fire supersedes the older pending row and records ``coalesced``."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-coalesce", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        first_exit: int = await executor.execute(reference=definition.schedule_id)
        first_pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        second_exit: int = await executor.execute(reference=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        superseded: Optional[ChannelMessageDAO] = await gateway.get(message_id=first_pending[0].id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)
        await gateway.close()

        assert (first_exit, second_exit) == (0, 0)
        assert len(pending) == 1
        assert pending[0].id != first_pending[0].id
        assert superseded is not None
        assert superseded.cancel_reason == "superseded"
        assert sorted(record.delivery_state for record in records) == ["coalesced", "queued"]
        coalesced: ScheduleRunRecordDAO = next(r for r in records if r.delivery_state == "coalesced")
        assert coalesced.delivery_path == "session_channel"
        assert coalesced.coalesced_fire_count == 1

    @pytest.mark.asyncio
    async def test_two_fires_without_a_coalescing_key_queue_two_prompts_in_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without ``latest_by_key`` every fire stays queued, FIFO by message index."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-no-coalesce", session_mode="continuous"
        ).model_copy(update={"session_policy": ScheduleSessionPolicyDAO(session_reference="release-prep")})
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        await executor.execute(reference=definition.schedule_id)
        await executor.execute(reference=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)
        await gateway.close()

        assert [row.message_index for row in pending] == [1, 2]
        assert {row.coalesce_key for row in pending} == {None}
        assert [record.delivery_state for record in records] == ["queued", "queued"]

    @pytest.mark.asyncio
    async def test_schedule_sender_identity_is_one_system_sender_per_schedule(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Repeated fires reuse one sender; a second schedule gets its own sender."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        first: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-a", session_mode="continuous")
        second: ScheduleDefinitionDAO = _build_definition(schedule_id="schedule-b", session_mode="continuous")
        ScheduleStore.create(definition=first, initial_next_run_at=None)
        ScheduleStore.create(definition=second, initial_next_run_at=None)
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        await executor.execute(reference=first.schedule_id)
        await executor.execute(reference=second.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        senders = [await gateway.get_participant(participant_id=row.sender_id) for row in pending]
        await gateway.close()

        assert len(pending) == 2
        assert len({row.sender_id for row in pending}) == 2
        assert [sender.external_ref for sender in senders if sender is not None] == [
            first.schedule_id,
            second.schedule_id,
        ]
        assert [sender.kind for sender in senders if sender is not None] == ["system", "system"]

    @pytest.mark.asyncio
    async def test_active_lease_for_an_unregistered_session_fails_loudly_and_queues_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A live lease whose session never registered on the queue raises; no row, no subprocess."""
        from src.channels.errors import UnknownParticipantError

        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-unregistered", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(status="completed", exit_code=0, summary="unused"),
        )
        gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels" / "channels.db")
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        with pytest.raises(UnknownParticipantError):
            await executor.execute(reference=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        await gateway.close()

        assert pending == []
        assert runner.calls == []
        assert _load_run_records(schedule_id=definition.schedule_id) == []

    @pytest.mark.asyncio
    async def test_active_lease_without_a_channel_gateway_fails_loudly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A misconfigured executor never silently drops a fire for an active session."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-no-gateway", session_mode="continuous"
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        executor: ScheduleExecutor = ScheduleExecutor(
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=await _lease_store_with_active_owner(tmp_path=tmp_path),
            report_writer=ScheduleReportWriter(),
        )

        with pytest.raises(RuntimeError, match="channel gateway"):
            await executor.execute(reference=definition.schedule_id)

    @pytest.mark.asyncio
    async def test_continuous_inactive_openrouter_target_persists_completed_headless_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An inactive route reaches the existing headless runner and persists its completion report."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-openrouter-inactive",
            session_mode="continuous",
        ).model_copy(update={"model": "openrouter:vendor/scheduled"})
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(
                status="completed",
                exit_code=0,
                session_id=_TARGET_SESSION_ID,
                summary="prepared exact route",
                stdout_summary="ordinary output",
                stderr_summary="",
            ),
        )
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=SessionOwnershipLeaseStore(history_root=tmp_path / "history"),
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)

        assert exit_code == 0
        assert runner.calls == [
            (
                "resume",
                {
                    "definition": definition,
                    "session_reference": "release-prep",
                    "target_session_id": _TARGET_SESSION_ID,
                },
            )
        ]
        assert len(records) == 1
        assert records[0].status == "completed"
        assert records[0].delivery_path == "resume_headless"
        assert records[0].summary == "prepared exact route"

    @pytest.mark.asyncio
    async def test_continuous_inactive_openrouter_target_persists_failed_headless_report(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed inactive preparation persists a failed report without queueing a channel row."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-openrouter-inactive-failed",
            session_mode="continuous",
        ).model_copy(update={"model": "openrouter:vendor/scheduled"})
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        runner = _FakeRunner(
            result=ScheduleSubprocessResultDAO(
                status="failed",
                exit_code=1,
                session_id=_TARGET_SESSION_ID,
                summary="Model preparation failed",
                stdout_summary="",
                stderr_summary="ordinary safe diagnostic",
            ),
        )
        gateway: ChannelGateway = await _gateway_with_open_target(tmp_path=tmp_path)
        executor: ScheduleExecutor = ScheduleExecutor(
            subprocess_runner=cast(Any, runner),
            target_resolver=cast(Any, _active_target_resolver()),
            session_lease_store=SessionOwnershipLeaseStore(history_root=tmp_path / "history"),
            channel_gateway=gateway,
            report_writer=ScheduleReportWriter(),
        )

        exit_code: int = await executor.execute(reference=definition.schedule_id)
        records: list[ScheduleRunRecordDAO] = _load_run_records(schedule_id=definition.schedule_id)
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(
            recipient_id=UUID(_TARGET_SESSION_ID)
        )
        await gateway.close()

        assert exit_code == 1
        assert len(records) == 1
        assert records[0].status == "failed"
        assert records[0].delivery_path == "resume_headless"
        assert records[0].summary == "Model preparation failed"
        assert records[0].stderr_summary == "ordinary safe diagnostic"
        assert pending == []


class TestActiveSessionDeliveryPolicy:
    """The policy names channel delivery; stored legacy definitions still load (108.6 §3)."""

    def test_default_is_session_channel_and_legacy_session_inbox_still_validates(self) -> None:
        """New policies default to ``session_channel``; a pre-108.6 ``session_inbox`` value is readable."""
        fresh_policy: ScheduleSessionPolicyDAO = ScheduleSessionPolicyDAO(session_reference="release-prep")
        legacy_policy: ScheduleSessionPolicyDAO = ScheduleSessionPolicyDAO.model_validate(
            {"session_reference": "release-prep", "active_session_delivery": "session_inbox"}
        )

        assert fresh_policy.active_session_delivery == "session_channel"
        assert legacy_policy.active_session_delivery == "session_inbox"


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
