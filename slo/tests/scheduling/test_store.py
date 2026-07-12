"""Tests for scheduling DAOs and ``ScheduleStore``."""

from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from src.scheduling.dao import (
    CalendarTriggerDAO,
    CronTriggerDAO,
    IntervalTriggerDAO,
    LoadedScheduleDAO,
    NotificationTargetDAO,
    OneShotTriggerDAO,
    ScheduleDefinitionDAO,
    ScheduleRunRecordDAO,
    ScheduleSessionPolicyDAO,
    ScheduleStateDAO,
    SlackTargetDAO,
    TriggerDAO,
    WebhookTargetDAO,
)
from src.scheduling.exceptions import ScheduleNotFoundError, ScheduleStoreCorruptError
from src.scheduling.store import ScheduleStore


def _utc_datetime(*, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a timezone-aware UTC datetime for deterministic tests.

    Args:
        year (int): UTC year.
        month (int): UTC month.
        day (int): UTC day.
        hour (int, optional): UTC hour. Defaults to 0.
        minute (int, optional): UTC minute. Defaults to 0.

    Returns:
        datetime: The constructed aware datetime.
    """
    return datetime(year=year, month=month, day=day, hour=hour, minute=minute, tzinfo=timezone.utc)


def _build_definition(
    *,
    schedule_id: str,
    name: str,
    trigger: TriggerDAO,
    prompt: str = "Summarize the repo changes.",
    enabled: bool = True,
) -> ScheduleDefinitionDAO:
    """Build a representative schedule definition for store tests.

    Args:
        schedule_id (str): Stable schedule identifier.
        name (str): Human-facing schedule name.
        trigger (TriggerDAO): Trigger variant under test.
        prompt (str, optional): Prompt body for the schedule. Defaults to
            ``"Summarize the repo changes."``.
        enabled (bool, optional): Whether the definition starts enabled.
            Defaults to True.

    Returns:
        ScheduleDefinitionDAO: Deterministic definition fixture.
    """
    return ScheduleDefinitionDAO(
        schedule_id=schedule_id,
        name=name,
        name_key=ScheduleStore.normalize_name_key(name=name),
        enabled=enabled,
        trigger=trigger,
        prompt=prompt,
        cwd="/Users/siddharth/Code/slo/slo",
        model="gpt-5.4",
        session_mode="continuous",
        session_policy=ScheduleSessionPolicyDAO(
            session_reference="release prep",
            coalescing_mode="latest_by_key",
            coalescing_key="repo-watch",
        ),
        misfire_grace_seconds=900,
        notifications=[
            WebhookTargetDAO(
                url="https://example.com/hooks/schedule",
                headers={"X-Test": "fixture"},
            ),
            SlackTargetDAO(
                webhook_url_env="SLO_SLACK_WEBHOOK",
                channel="#ops",
            ),
        ],
    )


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect ``ScheduleStore`` into a test-local schedules root.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        tmp_path (Path): Test-local temp directory.

    Returns:
        Path: The schedules root path used by the test.
    """
    root: Path = tmp_path / "schedules"
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(root))
    return root


def _build_run_record(*, schedule_id: str, run_id: str = "run-1") -> ScheduleRunRecordDAO:
    """Build a representative run record for append tests.

    Args:
        schedule_id (str): Parent schedule identifier.
        run_id (str, optional): Run record identifier. Defaults to ``"run-1"``.

    Returns:
        ScheduleRunRecordDAO: Deterministic run record fixture.
    """
    return ScheduleRunRecordDAO(
        run_id=run_id,
        schedule_id=schedule_id,
        started_at=_utc_datetime(year=2026, month=7, day=1, hour=9, minute=0),
        finished_at=_utc_datetime(year=2026, month=7, day=1, hour=9, minute=2),
        status="completed",
        delivery_path="resume_headless",
        delivery_state="executed",
        session_id="session-123",
        target_session_id="session-123",
        exit_code=0,
        summary="Weekly summary completed successfully.",
        stdout_summary="stdout summary",
        stderr_summary="stderr summary",
        skipped_reason=None,
        coalesced_fire_count=0,
    )


class TestScheduleDAOs:
    """DAO-level discrimination and default behaviour."""

    def test_trigger_union_discriminates_each_kind(self) -> None:
        """Each trigger ``kind`` maps to its concrete DAO class."""
        trigger_adapter: TypeAdapter[TriggerDAO] = TypeAdapter(TriggerDAO)

        one_shot: TriggerDAO = trigger_adapter.validate_python(
            {
                "kind": "one_shot",
                "run_at": _utc_datetime(year=2026, month=7, day=1, hour=12).isoformat(),
            }
        )
        interval: TriggerDAO = trigger_adapter.validate_python(
            {
                "kind": "interval",
                "every_seconds": 300,
                "anchor": _utc_datetime(year=2026, month=7, day=1, hour=12).isoformat(),
            }
        )
        cron: TriggerDAO = trigger_adapter.validate_python(
            {
                "kind": "cron",
                "expression": "0 17 * * 5",
                "tz": "UTC",
            }
        )
        calendar: TriggerDAO = trigger_adapter.validate_python(
            {
                "kind": "calendar",
                "rrule": "FREQ=WEEKLY;BYDAY=FR",
                "tz": "UTC",
            }
        )

        assert isinstance(one_shot, OneShotTriggerDAO)
        assert isinstance(interval, IntervalTriggerDAO)
        assert isinstance(cron, CronTriggerDAO)
        assert isinstance(calendar, CalendarTriggerDAO)

    def test_notification_target_union_discriminates_each_kind(self) -> None:
        """Each notification ``kind`` maps to its concrete DAO class."""
        target_adapter: TypeAdapter[NotificationTargetDAO] = TypeAdapter(NotificationTargetDAO)

        webhook: NotificationTargetDAO = target_adapter.validate_python(
            {
                "kind": "webhook",
                "url": "https://example.com/hook",
            }
        )
        slack: NotificationTargetDAO = target_adapter.validate_python(
            {
                "kind": "slack",
                "webhook_url_env": "SLO_SLACK_WEBHOOK",
            }
        )

        assert isinstance(webhook, WebhookTargetDAO)
        assert isinstance(slack, SlackTargetDAO)

    def test_schedule_definition_defaults_enabled_fresh_mode_and_notifications(self) -> None:
        """Optional schedule fields default to the spec's baseline values."""
        definition: ScheduleDefinitionDAO = ScheduleDefinitionDAO(
            schedule_id="schedule-1",
            name="Friday Standup Digest",
            name_key="friday-standup-digest",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=4, hour=15)),
            prompt="Summarize the week.",
        )

        assert definition.enabled is True
        assert definition.session_mode == "fresh"
        assert definition.session_policy is None
        assert definition.notifications == []

    def test_schedule_definition_rejects_session_policy_for_fresh_mode(self) -> None:
        """Fresh schedules must not persist continuous-session policy."""
        with pytest.raises(ValueError, match="session_policy is not allowed"):
            ScheduleDefinitionDAO(
                schedule_id="schedule-1",
                name="Friday Standup Digest",
                name_key="friday-standup-digest",
                trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=4, hour=15)),
                prompt="Summarize the week.",
                session_mode="fresh",
                session_policy=ScheduleSessionPolicyDAO(session_reference="release prep"),
            )

    def test_schedule_definition_requires_session_policy_for_continuous_mode(self) -> None:
        """Continuous schedules require a session policy block."""
        with pytest.raises(ValueError, match="session_policy is required"):
            ScheduleDefinitionDAO(
                schedule_id="schedule-1",
                name="Friday Standup Digest",
                name_key="friday-standup-digest",
                trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=4, hour=15)),
                prompt="Summarize the week.",
                session_mode="continuous",
            )

    def test_session_policy_rejects_coalescing_key_without_enabled_mode(self) -> None:
        """A coalescing key requires ``latest_by_key`` mode."""
        with pytest.raises(ValueError, match="coalescing_key requires"):
            ScheduleSessionPolicyDAO(
                session_reference="release prep",
                coalescing_mode="none",
                coalescing_key="repo-watch",
            )

    def test_session_policy_requires_coalescing_key_when_latest_by_key(self) -> None:
        """``latest_by_key`` mode requires an explicit key."""
        with pytest.raises(ValueError, match="coalescing_key is required"):
            ScheduleSessionPolicyDAO(
                session_reference="release prep",
                coalescing_mode="latest_by_key",
            )


class TestScheduleStoreCreateAndLoad:
    """``create`` and ``load`` round-trips plus filesystem modes."""

    @pytest.mark.parametrize(
        ("trigger", "schedule_id"),
        [
            (OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=7, hour=10)), "schedule-one"),
            (
                IntervalTriggerDAO(
                    every_seconds=900,
                    anchor=_utc_datetime(year=2026, month=7, day=7, hour=10),
                ),
                "schedule-interval",
            ),
            (CronTriggerDAO(expression="0 17 * * 5", tz="UTC"), "schedule-cron"),
            (
                CalendarTriggerDAO(
                    rrule="FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=0",
                    tz="UTC",
                    exclude_holidays="US",
                    blackout_dates=["2026-12-25"],
                ),
                "schedule-calendar",
            ),
        ],
    )
    def test_create_then_load_roundtrips_definition(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        trigger: TriggerDAO,
        schedule_id: str,
    ) -> None:
        """``load`` returns the exact definition previously created."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id=schedule_id,
            name=f"{schedule_id} name",
            trigger=trigger,
        )
        initial_next_run_at: datetime = _utc_datetime(year=2026, month=7, day=8, hour=8)

        ScheduleStore.create(
            definition=definition,
            initial_next_run_at=initial_next_run_at,
        )
        loaded: LoadedScheduleDAO = ScheduleStore.load(reference=schedule_id)

        assert loaded.definition == definition
        assert loaded.state.next_run_at == initial_next_run_at
        assert loaded.state.run_count == 0

    def test_create_writes_both_files_with_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Create writes the definition, state, and runs directory with strict modes."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-create",
            name="Create Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=10, hour=11)),
        )

        ScheduleStore.create(
            definition=definition,
            initial_next_run_at=_utc_datetime(year=2026, month=7, day=10, hour=11),
        )

        schedule_dir: Path = root / definition.schedule_id
        schedule_md: Path = schedule_dir / "schedule.md"
        state_json: Path = schedule_dir / "state.json"
        runs_dir: Path = schedule_dir / "runs"

        assert schedule_md.exists()
        assert state_json.exists()
        assert runs_dir.exists()
        assert stat.S_IMODE(schedule_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(schedule_md.stat().st_mode) == 0o600
        assert stat.S_IMODE(state_json.stat().st_mode) == 0o600
        assert stat.S_IMODE(runs_dir.stat().st_mode) == 0o700

        state: ScheduleStateDAO = ScheduleStateDAO.model_validate_json(state_json.read_text(encoding="utf-8"))
        assert state.run_count == 0

    def test_hand_edited_body_is_reflected_on_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Editing the markdown body directly changes the loaded prompt."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-body-edit",
            name="Body Edit",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=11, hour=12)),
            prompt="Initial prompt.",
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        schedule_md: Path = root / definition.schedule_id / "schedule.md"
        existing_text: str = schedule_md.read_text(encoding="utf-8")
        schedule_md.write_text(
            existing_text.replace("Initial prompt.", "Updated prompt.\n\n- Bullet one"),
            encoding="utf-8",
        )

        loaded: LoadedScheduleDAO = ScheduleStore.load(reference=definition.schedule_id)

        assert loaded.definition.prompt == "Updated prompt.\n\n- Bullet one"

    def test_one_shot_initial_state_next_run_none_when_past(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``initial_next_run_at=None`` persists a terminal one-shot state."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-terminal",
            name="Terminal One Shot",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=12, hour=9)),
        )

        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        loaded: LoadedScheduleDAO = ScheduleStore.load(reference=definition.schedule_id)

        assert loaded.state.next_run_at is None

    def test_load_and_load_all_return_loaded_schedule_dao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both load APIs return ``LoadedScheduleDAO`` instances, never tuples."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-loaded-dao",
            name="Loaded DAO",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=13, hour=9)),
        )
        ScheduleStore.create(
            definition=definition,
            initial_next_run_at=_utc_datetime(year=2026, month=7, day=13, hour=9),
        )

        loaded_one: LoadedScheduleDAO = ScheduleStore.load(reference=definition.schedule_id)
        loaded_many: list[LoadedScheduleDAO] = ScheduleStore.load_all()

        assert isinstance(loaded_one, LoadedScheduleDAO)
        assert len(loaded_many) == 1
        assert isinstance(loaded_many[0], LoadedScheduleDAO)


class TestScheduleStoreLoadAll:
    """``load_all`` happy path, empty-root path, and skip behaviour."""

    def test_load_all_skips_malformed_and_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Malformed schedules are skipped, logged, and do not break valid siblings."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-valid",
            name="Valid Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=14, hour=10)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        invalid_dir: Path = root / "schedule-invalid"
        invalid_dir.mkdir(parents=True)
        (invalid_dir / "schedule.md").write_text("No frontmatter here.", encoding="utf-8")

        log_rows: list[dict[str, str]] = []

        def _capture_log(msg: str, **kwargs: str) -> None:
            """Capture ``log_info`` calls for assertion.

            Args:
                msg (str): Log message name.
                **kwargs (str): Structured log fields.
            """
            row: dict[str, str] = {"msg": msg}
            row.update(kwargs)
            log_rows.append(row)

        monkeypatch.setattr("src.scheduling.store.log_info", _capture_log)

        loaded: list[LoadedScheduleDAO] = ScheduleStore.load_all()

        assert [item.schedule_id for item in loaded] == [definition.schedule_id]
        assert len(log_rows) == 1
        assert log_rows[0]["msg"] == "schedule_skipped_malformed"
        assert log_rows[0]["path"].endswith("schedule-invalid/schedule.md")

    def test_load_all_empty_when_root_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing schedules root returns an empty list."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

        loaded: list[LoadedScheduleDAO] = ScheduleStore.load_all()

        assert loaded == []


class TestScheduleStoreMutations:
    """State-only updates, enabled flag flips, deletes, and run records."""

    def test_update_state_only_touches_state_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Updating state changes only ``state.json`` and preserves ``schedule.md``."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-update-state",
            name="Update State",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=15, hour=8)),
        )
        ScheduleStore.create(
            definition=definition,
            initial_next_run_at=_utc_datetime(year=2026, month=7, day=15, hour=8),
        )

        schedule_md: Path = root / definition.schedule_id / "schedule.md"
        state_json: Path = root / definition.schedule_id / "state.json"
        schedule_text_before: str = schedule_md.read_text(encoding="utf-8")
        schedule_mtime_before: int = schedule_md.stat().st_mtime_ns
        state_text_before: str = state_json.read_text(encoding="utf-8")

        updated_state: ScheduleStateDAO = ScheduleStateDAO(
            next_run_at=_utc_datetime(year=2026, month=7, day=16, hour=8),
            last_run_at=_utc_datetime(year=2026, month=7, day=15, hour=8),
            last_status="completed",
            last_session_id="session-456",
            last_delivery_path="resume_headless",
            last_delivery_state="executed",
            run_count=1,
        )
        ScheduleStore.update_state(schedule_id=definition.schedule_id, state=updated_state)

        assert schedule_md.read_text(encoding="utf-8") == schedule_text_before
        assert schedule_md.stat().st_mtime_ns == schedule_mtime_before
        assert state_json.read_text(encoding="utf-8") != state_text_before
        assert ScheduleStore.load(reference=definition.schedule_id).state == updated_state

    def test_set_enabled_flips_flag_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``set_enabled`` updates only the enabled flag on the definition."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-enable",
            name="Enable Toggle",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=16, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        updated: ScheduleDefinitionDAO = ScheduleStore.set_enabled(
            schedule_id=definition.schedule_id,
            enabled=False,
        )

        assert updated.enabled is False
        assert updated.model_dump(exclude={"enabled"}) == definition.model_dump(exclude={"enabled"})

    def test_delete_removes_directory_returns_bool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Delete returns True once and False once the schedule is gone."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-delete",
            name="Delete Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=17, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        first: bool = ScheduleStore.delete(schedule_id=definition.schedule_id)
        second: bool = ScheduleStore.delete(schedule_id=definition.schedule_id)

        assert first is True
        assert second is False
        assert not (root / definition.schedule_id).exists()

    def test_append_run_record_writes_under_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Run records are persisted as one file per run under ``runs/``."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-runs",
            name="Run Record Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=18, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        record: ScheduleRunRecordDAO = _build_run_record(schedule_id=definition.schedule_id, run_id="run-123")

        ScheduleStore.append_run_record(schedule_id=definition.schedule_id, record=record)

        record_path: Path = root / definition.schedule_id / "runs" / "run-123.json"
        assert record_path.exists()
        assert ScheduleRunRecordDAO.model_validate_json(record_path.read_text(encoding="utf-8")) == record

    def test_append_run_record_roundtrips_queued_delivery_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Queued SessionInbox records persist without executed-run fields."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-queued-runs",
            name="Queued Run Record Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=18, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        record: ScheduleRunRecordDAO = ScheduleRunRecordDAO(
            run_id="run-queued",
            schedule_id=definition.schedule_id,
            started_at=_utc_datetime(year=2026, month=7, day=18, hour=8),
            finished_at=_utc_datetime(year=2026, month=7, day=18, hour=8, minute=1),
            status=None,
            delivery_path="session_inbox",
            delivery_state="queued",
            session_id=None,
            target_session_id="session-456",
            exit_code=None,
            summary="",
            stdout_summary="",
            stderr_summary="",
            skipped_reason=None,
            coalesced_fire_count=0,
        )

        ScheduleStore.append_run_record(schedule_id=definition.schedule_id, record=record)

        record_path: Path = root / definition.schedule_id / "runs" / "run-queued.json"
        assert record_path.exists()
        assert ScheduleRunRecordDAO.model_validate_json(record_path.read_text(encoding="utf-8")) == record


class TestScheduleStoreReferenceResolution:
    """Id and name-key resolution paths."""

    def test_resolve_reference_by_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exact schedule id resolves immediately."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-id-only",
            name="Reference by Id",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=19, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        resolved: str = ScheduleStore.resolve_reference(reference=definition.schedule_id)

        assert resolved == definition.schedule_id

    def test_resolve_reference_by_name_key_case_insensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mixed-case references resolve via the stored normalised ``name_key``."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-name-key",
            name="Friday Standup Digest",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=20, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        resolved: str = ScheduleStore.resolve_reference(reference="Friday-Standup-Digest")

        assert resolved == definition.schedule_id

    def test_resolve_reference_not_found_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown references raise ``ScheduleNotFoundError`` with the original input."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

        with pytest.raises(ScheduleNotFoundError) as exc_info:
            ScheduleStore.resolve_reference(reference="missing-schedule")

        assert exc_info.value.reference == "missing-schedule"


class TestScheduleStoreOtherHelpers:
    """Corruption, directory helper, and tick marker helpers."""

    def test_corrupt_state_json_raises_on_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Single-schedule loads raise on malformed ``state.json``."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-corrupt-state",
            name="Corrupt State",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=21, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        state_path: Path = root / definition.schedule_id / "state.json"
        state_path.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(ScheduleStoreCorruptError) as exc_info:
            ScheduleStore.load(reference=definition.schedule_id)

        assert exc_info.value.path == state_path

    def test_directory_for_matches_create_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``directory_for`` matches the directory ``create`` wrote into."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-directory",
            name="Directory Helper",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=22, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        assert (
            ScheduleStore.directory_for(schedule_id=definition.schedule_id) == root / definition.schedule_id
        )

    def test_touch_last_tick_writes_iso_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``touch_last_tick`` writes a root-level marker ignored by ``load_all``."""
        root: Path = _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition(
            schedule_id="schedule-last-tick",
            name="Last Tick Schedule",
            trigger=OneShotTriggerDAO(run_at=_utc_datetime(year=2026, month=7, day=23, hour=8)),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        moment: datetime = _utc_datetime(year=2026, month=7, day=23, hour=8, minute=30)

        ScheduleStore.touch_last_tick(moment=moment)

        last_tick_path: Path = root / ".last_tick"
        assert last_tick_path.read_text(encoding="utf-8") == moment.isoformat()
        assert [item.schedule_id for item in ScheduleStore.load_all()] == [definition.schedule_id]
