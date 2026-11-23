"""Tests for `slo schedule ...` commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.scheduling.dao import (
    CalendarTriggerDAO,
    CronTriggerDAO,
    ScheduleDefinitionDAO,
    ScheduleRunRecordDAO,
    ScheduleSessionPolicyDAO,
    ScheduleStateDAO,
)
from src.scheduling.store import ScheduleStore

runner: CliRunner = CliRunner()


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect `ScheduleStore` into a test-local root."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))


def _utc_datetime(*, year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Build a deterministic aware UTC datetime."""
    return datetime(year=year, month=month, day=day, hour=hour, minute=minute, tzinfo=timezone.utc)


def _seed_schedule(*, schedule_id: str) -> ScheduleDefinitionDAO:
    """Build a deterministic continuous schedule for CLI read-path tests."""
    return ScheduleDefinitionDAO(
        schedule_id=schedule_id,
        name="Friday Standup Digest",
        name_key="friday-standup-digest",
        trigger=CronTriggerDAO(expression="0 17 * * 5", tz="UTC"),
        prompt="Summarize the week.",
        session_mode="continuous",
        session_policy=ScheduleSessionPolicyDAO(session_reference="release-prep"),
    )


class TestScheduleCommands:
    """End-user schedule command surface."""

    def test_add_fresh_schedule(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`schedule add` persists a fresh schedule through the canonical store."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--name",
                "Daily Summary",
                "--prompt",
                "Summarize the repo.",
                "--cron",
                "0 9 * * *",
                "--session-mode",
                "fresh",
            ],
        )

        assert result.exit_code == 0
        stored = ScheduleStore.load(reference="Daily Summary")
        assert stored.definition.session_mode == "fresh"
        assert stored.definition.session_policy is None

    def test_add_continuous_schedule_with_explicit_target_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Continuous schedules persist explicit target-session and coalescing policy."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)

        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--name",
                "Repo Watch",
                "--prompt",
                "Watch the repo.",
                "--cron",
                "*/5 * * * *",
                "--session-mode",
                "continuous",
                "--session-reference",
                "release-prep",
                "--coalescing-mode",
                "latest_by_key",
                "--coalescing-key",
                "repo-watch",
            ],
        )

        assert result.exit_code == 0
        stored = ScheduleStore.load(reference="Repo Watch")
        assert stored.definition.session_mode == "continuous"
        assert stored.definition.session_policy is not None
        assert stored.definition.session_policy.session_reference == "release-prep"
        assert stored.definition.session_policy.coalescing_key == "repo-watch"

    def test_add_rejects_invalid_fresh_session_flag_combinations(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fresh schedules fail fast on session-targeting/coalescing flags."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        # Rich detects console width from the terminal, which is a pipe under
        # parallel test workers; pin the width so the error panel renders fully.
        monkeypatch.setenv("COLUMNS", "120")

        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--name",
                "Invalid Fresh",
                "--prompt",
                "Summarize the repo.",
                "--cron",
                "0 9 * * *",
                "--session-mode",
                "fresh",
                "--session-reference",
                "release-prep",
            ],
        )

        assert result.exit_code != 0
        assert result.exception is not None
        assert "Fresh schedules cannot use" in result.output

    def test_edit_updates_existing_schedule_definition(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`schedule edit` rewrites the persisted definition in place."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _seed_schedule(schedule_id="schedule-1")
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        result = runner.invoke(
            app,
            [
                "schedule",
                "edit",
                "--name",
                "schedule-1",
                "--schedule-name",
                "Repo Watch",
                "--prompt",
                "Watch the repo continuously.",
                "--interval-seconds",
                "300",
                "--session-mode",
                "continuous",
                "--session-reference",
                "release-ops",
                "--coalescing-mode",
                "latest_by_key",
                "--coalescing-key",
                "repo-watch",
            ],
        )

        assert result.exit_code == 0
        stored = ScheduleStore.load(reference="schedule-1")
        assert stored.definition.name == "Repo Watch"
        assert stored.definition.prompt == "Watch the repo continuously."
        assert stored.definition.session_policy is not None
        assert stored.definition.session_policy.session_reference == "release-ops"
        assert stored.definition.session_policy.coalescing_key == "repo-watch"

    def test_list_output_shows_mode_target_session_and_last_delivery(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`schedule list` exposes Mode, Target Session, and Last Delivery."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _seed_schedule(schedule_id="schedule-1")
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        ScheduleStore.update_state(
            schedule_id=definition.schedule_id,
            state=ScheduleStateDAO(
                last_delivery_path="session_inbox",
                last_delivery_state="queued",
            ),
        )

        with patch("src.cli.schedule.app.ScheduleOSIntegration.status") as mock_status:
            mock_status.return_value.installed = True
            result = runner.invoke(app, ["schedule", "list"])

        assert result.exit_code == 0
        assert "Mode" in result.stdout
        assert "Target Session" in result.stdout
        assert "Last Delivery" in result.stdout
        assert "continuous" in result.stdout
        assert "release-prep" in result.stdout
        assert "installed" in result.stdout
        assert "session_inbox:queued" in result.stdout

    def test_list_handles_calendar_trigger_schedules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calendar-backed schedules render without crashing the list view."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = ScheduleDefinitionDAO(
            schedule_id="schedule-calendar",
            name="Calendar Digest",
            name_key="calendar-digest",
            trigger=CalendarTriggerDAO(rrule="FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=0", tz="UTC"),
            prompt="Summarize the week.",
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)

        with patch("src.cli.schedule.app.ScheduleOSIntegration.status") as mock_status:
            mock_status.return_value.installed = False
            result = runner.invoke(app, ["schedule", "list"])

        assert result.exit_code == 0
        assert "calendar:FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=0" in result.stdout

    def test_run_and_execute_delegate_into_schedule_executor(self) -> None:
        """Both `schedule run` and `schedule execute` delegate to the runtime executor."""
        executor_mock = type("_ExecutorMock", (), {})()
        executor_mock.execute = lambda **kwargs: 0  # type: ignore[assignment]
        with (
            patch("src.cli.schedule.app._build_executor", return_value=executor_mock),
            patch("src.cli.schedule.app.asyncio.run", return_value=0) as mock_run,
        ):
            run_result = runner.invoke(app, ["schedule", "run", "--name", "schedule-1"])
            execute_result = runner.invoke(app, ["schedule", "execute", "--name", "schedule-1"])

        assert run_result.exit_code == 0
        assert execute_result.exit_code == 0
        assert mock_run.call_count == 2

    @pytest.mark.parametrize("delivery_path", ["session_channel", "session_inbox"])
    def test_show_report_renders_delivery_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        delivery_path: str,
    ) -> None:
        """`schedule show-report` prints delivery metadata; the legacy inbox path stays readable."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _seed_schedule(schedule_id="schedule-1")
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        record: ScheduleRunRecordDAO = ScheduleRunRecordDAO(
            run_id="run-1",
            schedule_id=definition.schedule_id,
            started_at=_utc_datetime(year=2026, month=7, day=12, hour=9),
            finished_at=_utc_datetime(year=2026, month=7, day=12, hour=9, minute=1),
            status=None,
            delivery_path=delivery_path,  # type: ignore[arg-type]
            delivery_state="coalesced",
            session_id=None,
            target_session_id="session-123",
            exit_code=None,
            summary="",
            coalesced_fire_count=2,
        )
        ScheduleStore.append_run_record(schedule_id=definition.schedule_id, record=record)

        result = runner.invoke(
            app,
            [
                "schedule",
                "show-report",
                "--name",
                definition.schedule_id,
                "--run-id",
                "run-1",
            ],
        )

        assert result.exit_code == 0
        assert f"delivery_path: {delivery_path}" in result.stdout
        assert "delivery_state: coalesced" in result.stdout
        assert "target_session_id: session-123" in result.stdout
        assert "coalesced_fire_count: 2" in result.stdout


class TestScheduleExecuteChannelJourney:
    """I1 journey: ``slo schedule execute`` → executor → ``channels.db`` for an open TUI session."""

    _SESSION_ID: str = "0b8f3a52-9d6e-4c1b-a7f0-3e2d1c0b9a87"

    @staticmethod
    async def _open_tui_session(*, slo_home: Path, session_id: str) -> None:
        """Make ``session_id`` look like a mounted TUI: live lease and an open agent participant.

        Args:
            slo_home (Path): The isolated per-test ``SLO_HOME``.
            session_id (str): Target session id.
        """
        from uuid import UUID

        from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore
        from src.channels.gateway import ChannelGateway

        lease_store = SessionOwnershipLeaseStore(history_root=slo_home / "sessions" / "history")
        await lease_store.acquire(session_id=session_id, owner_id="tui-journey", ttl_seconds=300.0)
        gateway: ChannelGateway = await ChannelGateway.default()
        await gateway.register_agent(session_id=UUID(session_id), name="slo journey", durable_inbox=True)
        await gateway.close()

    @staticmethod
    async def _pending_prompts(*, session_id: str) -> list:
        """Read the target session's pending inbound rows back from the shared database.

        Args:
            session_id (str): Target session id.

        Returns:
            list: Pending ``ChannelMessageDAO`` rows, FIFO.
        """
        from uuid import UUID

        from src.channels.gateway import ChannelGateway

        gateway: ChannelGateway = await ChannelGateway.default()
        try:
            return await gateway.pending_inbound(recipient_id=UUID(session_id))
        finally:
            await gateway.close()

    def test_execute_with_active_lease_queues_one_prompt_and_coalesces_the_next_fire(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        isolated_slo_home: Path,
    ) -> None:
        """Two fires with the same key leave one pending prompt row; the run records say so."""
        import asyncio

        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = ScheduleDefinitionDAO(
            schedule_id="schedule-journey",
            name="Repo Watch",
            name_key="repo-watch",
            trigger=CronTriggerDAO(expression="*/5 * * * *", tz="UTC"),
            prompt="Check CI and summarise new failures.",
            session_mode="continuous",
            session_policy=ScheduleSessionPolicyDAO(
                session_reference=self._SESSION_ID,
                coalescing_mode="latest_by_key",
                coalescing_key="repo-watch",
            ),
        )
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        asyncio.run(self._open_tui_session(slo_home=isolated_slo_home, session_id=self._SESSION_ID))

        first = runner.invoke(app, ["schedule", "execute", "--name", definition.schedule_id])
        second = runner.invoke(app, ["schedule", "execute", "--name", definition.schedule_id])
        pending = asyncio.run(self._pending_prompts(session_id=self._SESSION_ID))
        state = ScheduleStore.load(reference=definition.schedule_id).state

        assert (first.exit_code, second.exit_code) == (0, 0)
        assert len(pending) == 1
        assert pending[0].message_type == "prompt"
        assert pending[0].message_contents == definition.prompt
        assert pending[0].sender_name == "scheduler Repo Watch"
        assert state.last_delivery_path == "session_channel"
        assert state.last_delivery_state == "coalesced"
        assert not (isolated_slo_home / "sessions" / "history" / self._SESSION_ID / "inbox").exists()
