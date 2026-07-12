"""Tests for OS scheduler integration helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.scheduling.dao import CronTriggerDAO, IntervalTriggerDAO, ScheduleDefinitionDAO
from src.scheduling.os.cron import CronScheduleInstaller
from src.scheduling.os.integration import ScheduleOSIntegration
from src.scheduling.os.executable_locator import ScheduleExecutableLocator
from src.scheduling.os.launchd import LaunchdScheduleInstaller
from src.scheduling.os.status import ScheduleInstallStatusDAO, ScheduleLogPathsDAO
from src.scheduling.store import ScheduleStore


def _build_definition() -> ScheduleDefinitionDAO:
    """Build a cron-backed schedule definition for installer tests."""
    return ScheduleDefinitionDAO(
        schedule_id="schedule-1",
        name="Friday Standup Digest",
        name_key="friday-standup-digest",
        trigger=CronTriggerDAO(expression="0 17 * * 5", tz="UTC"),
        prompt="Summarize the week.",
    )


def _build_logs(*, tmp_path: Path) -> ScheduleLogPathsDAO:
    """Build deterministic log paths for installer tests."""
    return ScheduleLogPathsDAO(
        stdout=tmp_path / "stdout.log",
        stderr=tmp_path / "stderr.log",
    )


def _set_schedules_dir(*, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect schedule persistence into a test-local root."""
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path / "schedules"))


class TestLaunchdScheduleInstaller:
    """Plist rendering and install/uninstall behavior."""

    def test_plist_rendering_contains_execute_arguments(self, tmp_path: Path) -> None:
        """The launchd payload invokes `slo schedule execute --name <id>`."""
        installer: LaunchdScheduleInstaller = LaunchdScheduleInstaller(launch_agents_dir=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition()

        payload = installer._plist_payload(
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )

        assert payload["ProgramArguments"] == [
            "/usr/local/bin/slo",
            "schedule",
            "execute",
            "--name",
            definition.schedule_id,
        ]

    def test_install_rewrites_existing_plist_cleanly(self, tmp_path: Path) -> None:
        """Reinstall overwrites the prior plist and returns installed status."""
        installer: LaunchdScheduleInstaller = LaunchdScheduleInstaller(launch_agents_dir=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition()

        with patch("subprocess.run") as mock_run:
            first = installer.install(
                definition=definition,
                executable=Path("/usr/local/bin/slo"),
                log_paths=_build_logs(tmp_path=tmp_path),
            )
            second = installer.install(
                definition=definition,
                executable=Path("/usr/local/bin/slo"),
                log_paths=_build_logs(tmp_path=tmp_path),
            )

        assert first.installed is True
        assert second.installed is True
        assert installer._plist_path(definition=definition).exists()
        assert mock_run.call_count == 4

    def test_plist_rendering_handles_wildcard_cron_fields(self, tmp_path: Path) -> None:
        """Wildcard cron fields are omitted instead of crashing integer parsing."""
        installer: LaunchdScheduleInstaller = LaunchdScheduleInstaller(launch_agents_dir=tmp_path)
        definition: ScheduleDefinitionDAO = ScheduleDefinitionDAO(
            schedule_id="schedule-wildcard",
            name="Daily Summary",
            name_key="daily-summary",
            trigger=CronTriggerDAO(expression="0 9 * * *", tz="UTC"),
            prompt="Summarize the repo.",
        )

        payload = installer._plist_payload(
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )

        assert payload["StartCalendarInterval"] == {"Minute": 0, "Hour": 9}

    def test_plist_rendering_supports_interval_triggers(self, tmp_path: Path) -> None:
        """Interval-backed schedules render `StartInterval` for launchd."""
        installer: LaunchdScheduleInstaller = LaunchdScheduleInstaller(launch_agents_dir=tmp_path)
        definition: ScheduleDefinitionDAO = ScheduleDefinitionDAO(
            schedule_id="schedule-interval",
            name="Repo Watch",
            name_key="repo-watch",
            trigger=IntervalTriggerDAO(every_seconds=300),
            prompt="Watch the repo.",
        )

        payload = installer._plist_payload(
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )

        assert payload["StartInterval"] == 300

    def test_status_reflects_plist_presence(self, tmp_path: Path) -> None:
        """Status reports installation based on plist presence."""
        installer: LaunchdScheduleInstaller = LaunchdScheduleInstaller(launch_agents_dir=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition()

        absent_status: ScheduleInstallStatusDAO = installer.status(definition=definition)
        installer._plist_path(definition=definition).write_text("plist", encoding="utf-8")
        present_status: ScheduleInstallStatusDAO = installer.status(definition=definition)

        assert absent_status.installed is False
        assert present_status.installed is True


class TestCronScheduleInstaller:
    """Marker-block insertion and removal behavior."""

    def test_cron_block_insertion_is_idempotent(self, tmp_path: Path) -> None:
        """Repeated inserts do not duplicate the schedule block."""
        installer: CronScheduleInstaller = CronScheduleInstaller()
        definition: ScheduleDefinitionDAO = _build_definition()
        initial: str = ""

        once: str = installer._replace_block(
            current=initial,
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )
        twice: str = installer._replace_block(
            current=once,
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )

        assert twice.count(f"# slo-schedule:{definition.schedule_id}") == 1
        assert "schedule execute --name schedule-1" in twice

    def test_uninstall_removes_only_target_block(self, tmp_path: Path) -> None:
        """Removing one block preserves unrelated cron entries."""
        installer: CronScheduleInstaller = CronScheduleInstaller()
        definition: ScheduleDefinitionDAO = _build_definition()
        other_block: str = (
            "# slo-schedule:schedule-2\n"
            "* * * * * /usr/local/bin/slo schedule execute --name schedule-2\n"
            "# /slo-schedule:schedule-2\n"
        )
        current: str = other_block + installer.render_block(
            definition=definition,
            executable=Path("/usr/local/bin/slo"),
            log_paths=_build_logs(tmp_path=tmp_path),
        )

        updated: str = installer._remove_block(current=current, schedule_id=definition.schedule_id)

        assert "schedule-1" not in updated
        assert "schedule-2" in updated

    def test_status_detects_marker_block_presence(self) -> None:
        """Status reports installation from the marker block presence."""
        installer: CronScheduleInstaller = CronScheduleInstaller()
        definition: ScheduleDefinitionDAO = _build_definition()

        with patch.object(installer, "_read_current_crontab", return_value=""):
            absent_status: ScheduleInstallStatusDAO = installer.status(definition=definition)
        with patch.object(
            installer,
            "_read_current_crontab",
            return_value=f"# slo-schedule:{definition.schedule_id}\n* * * * * true\n# /slo-schedule:{definition.schedule_id}\n",
        ):
            present_status: ScheduleInstallStatusDAO = installer.status(definition=definition)

        assert absent_status.installed is False
        assert present_status.installed is True


class TestScheduleOSIntegration:
    """Platform routing for install-state queries."""

    def test_status_routes_to_launchd_on_macos(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """macOS status uses the launchd installer."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition()
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        launchd_status: ScheduleInstallStatusDAO = ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="darwin",
            installed=True,
            detail="plist",
        )
        integration: ScheduleOSIntegration = ScheduleOSIntegration(
            launchd_installer=SimpleNamespace(status=lambda **kwargs: launchd_status),  # type: ignore[arg-type]
            cron_installer=SimpleNamespace(),  # type: ignore[arg-type]
        )

        with patch("sys.platform", "darwin"):
            status: ScheduleInstallStatusDAO = integration.status(reference=definition.schedule_id)

        assert status.installed is True

    def test_status_routes_to_cron_on_linux(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Linux status uses the cron installer."""
        _set_schedules_dir(monkeypatch=monkeypatch, tmp_path=tmp_path)
        definition: ScheduleDefinitionDAO = _build_definition()
        ScheduleStore.create(definition=definition, initial_next_run_at=None)
        cron_status: ScheduleInstallStatusDAO = ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="linux",
            installed=False,
            detail="cron",
        )
        integration: ScheduleOSIntegration = ScheduleOSIntegration(
            launchd_installer=SimpleNamespace(),  # type: ignore[arg-type]
            cron_installer=SimpleNamespace(status=lambda **kwargs: cron_status),  # type: ignore[arg-type]
        )

        with patch("sys.platform", "linux"):
            status: ScheduleInstallStatusDAO = integration.status(reference=definition.schedule_id)

        assert status.installed is False


class TestScheduleExecutableLocator:
    """`slo` executable resolution order."""

    def test_prefers_virtualenv_executable(self, tmp_path: Path) -> None:
        """The in-venv `slo` binary wins when present."""
        fake_python: Path = tmp_path / "bin" / "python"
        fake_slo: Path = tmp_path / "bin" / "slo"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")
        fake_slo.write_text("", encoding="utf-8")

        with patch("sys.executable", str(fake_python)):
            resolved: Path = ScheduleExecutableLocator.locate()

        assert resolved == fake_slo.resolve()

    def test_falls_back_to_shutil_which(self) -> None:
        """`shutil.which('slo')` is used when the venv binary is absent."""
        with (
            patch("sys.executable", "/tmp/missing/python"),
            patch("shutil.which", return_value="/usr/local/bin/slo"),
        ):
            resolved: Path = ScheduleExecutableLocator.locate()

        assert resolved == Path("/usr/local/bin/slo").resolve()

    def test_raises_when_nothing_is_resolvable(self) -> None:
        """A clear failure is raised when `slo` cannot be located."""
        with (
            patch("sys.executable", "/tmp/missing/python"),
            patch("shutil.which", return_value=None),
        ):
            with pytest.raises(FileNotFoundError, match="Could not resolve"):
                ScheduleExecutableLocator.locate()
