"""macOS launchd integration for scheduled tasks."""

from __future__ import annotations

import plistlib
import os
import subprocess
from pathlib import Path

from src.scheduling.dao import CronTriggerDAO, IntervalTriggerDAO, ScheduleDefinitionDAO
from src.scheduling.os.status import ScheduleInstallStatusDAO, ScheduleLogPathsDAO

__all__ = ["LaunchdScheduleInstaller"]


class LaunchdScheduleInstaller:
    """Install and uninstall one user-level launchd agent per schedule."""

    def __init__(self, *, launch_agents_dir: Path | None = None) -> None:
        """Allow the plist directory to be overridden in tests.

        Args:
            launch_agents_dir (Path | None): Optional override directory.
        """
        self._launch_agents_dir: Path = (
            launch_agents_dir.expanduser().resolve()
            if launch_agents_dir is not None
            else (Path.home() / "Library" / "LaunchAgents").resolve()
        )

    def install(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        executable: Path,
        log_paths: ScheduleLogPathsDAO,
    ) -> ScheduleInstallStatusDAO:
        """Write and bootstrap the launchd plist.

        Args:
            definition (ScheduleDefinitionDAO): Schedule to install.
            executable (Path): Resolved `slo` executable path.
            log_paths (ScheduleLogPathsDAO): Stdout/stderr log paths.

        Returns:
            ScheduleInstallStatusDAO: Install result.
        """
        plist_path: Path = self._plist_path(definition=definition)
        self._launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist_path.write_bytes(
            plistlib.dumps(
                self._plist_payload(
                    definition=definition,
                    executable=executable,
                    log_paths=log_paths,
                )
            )
        )
        plist_path.chmod(0o644)
        gui_target: str = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", gui_target, str(plist_path)], check=False)
        subprocess.run(["launchctl", "bootstrap", gui_target, str(plist_path)], check=False)
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="darwin",
            installed=True,
            detail=str(plist_path),
        )

    def uninstall(self, *, definition: ScheduleDefinitionDAO) -> ScheduleInstallStatusDAO:
        """Remove and boot out the launchd plist.

        Args:
            definition (ScheduleDefinitionDAO): Schedule to uninstall.

        Returns:
            ScheduleInstallStatusDAO: Uninstall result.
        """
        plist_path: Path = self._plist_path(definition=definition)
        gui_target: str = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", gui_target, str(plist_path)], check=False)
        plist_path.unlink(missing_ok=True)
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="darwin",
            installed=False,
            detail=str(plist_path),
        )

    def status(self, *, definition: ScheduleDefinitionDAO) -> ScheduleInstallStatusDAO:
        """Report whether the schedule's plist is currently present.

        Args:
            definition (ScheduleDefinitionDAO): Schedule whose registration should be checked.

        Returns:
            ScheduleInstallStatusDAO: Current registration status.
        """
        plist_path: Path = self._plist_path(definition=definition)
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="darwin",
            installed=plist_path.exists(),
            detail=str(plist_path),
        )

    def _plist_path(self, *, definition: ScheduleDefinitionDAO) -> Path:
        """Return the plist path for one schedule.

        Args:
            definition (ScheduleDefinitionDAO): Schedule under installation.

        Returns:
            Path: Resolved plist path.
        """
        return self._launch_agents_dir / f"com.slo.schedule.{definition.name_key}.plist"

    def _plist_payload(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        executable: Path,
        log_paths: ScheduleLogPathsDAO,
    ) -> dict[str, object]:
        """Render the launchd plist payload.

        Args:
            definition (ScheduleDefinitionDAO): Schedule under installation.
            executable (Path): Resolved `slo` executable path.
            log_paths (ScheduleLogPathsDAO): Stdout/stderr log paths.

        Returns:
            dict[str, object]: plist payload.
        """
        payload: dict[str, object] = {
            "Label": f"com.slo.schedule.{definition.name_key}",
            "ProgramArguments": [
                str(executable),
                "schedule",
                "execute",
                "--name",
                definition.schedule_id,
            ],
            "StandardOutPath": str(log_paths.stdout),
            "StandardErrorPath": str(log_paths.stderr),
        }
        if isinstance(definition.trigger, CronTriggerDAO):
            minute, hour, day, month, weekday = definition.trigger.expression.split()
            interval: dict[str, int] = {}
            if minute != "*":
                interval["Minute"] = int(minute)
            if hour != "*":
                interval["Hour"] = int(hour)
            if day != "*":
                interval["Day"] = int(day)
            if month != "*":
                interval["Month"] = int(month)
            if weekday != "*":
                interval["Weekday"] = int(weekday)
            if interval:
                payload["StartCalendarInterval"] = interval
            return payload
        if isinstance(definition.trigger, IntervalTriggerDAO):
            payload["StartInterval"] = definition.trigger.every_seconds
            return payload
        raise ValueError("launchd installer supports cron and interval triggers only.")
