"""Linux cron integration for scheduled tasks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.scheduling.dao import CronTriggerDAO, ScheduleDefinitionDAO
from src.scheduling.os.status import ScheduleInstallStatusDAO, ScheduleLogPathsDAO

__all__ = ["CronScheduleInstaller"]


class CronScheduleInstaller:
    """Rewrite the user crontab with stable schedule marker blocks."""

    def install(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        executable: Path,
        log_paths: ScheduleLogPathsDAO,
    ) -> ScheduleInstallStatusDAO:
        """Insert or replace the schedule's cron block.

        Args:
            definition (ScheduleDefinitionDAO): Schedule to install.
            executable (Path): Resolved `slo` executable path.
            log_paths (ScheduleLogPathsDAO): Stdout/stderr log paths.

        Returns:
            ScheduleInstallStatusDAO: Install result.
        """
        current: str = self._read_current_crontab()
        updated: str = self._replace_block(
            current=current,
            definition=definition,
            executable=executable,
            log_paths=log_paths,
        )
        self._write_crontab(text=updated)
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="linux",
            installed=True,
            detail=definition.schedule_id,
        )

    def uninstall(self, *, definition: ScheduleDefinitionDAO) -> ScheduleInstallStatusDAO:
        """Remove the schedule's cron block.

        Args:
            definition (ScheduleDefinitionDAO): Schedule to uninstall.

        Returns:
            ScheduleInstallStatusDAO: Uninstall result.
        """
        current: str = self._read_current_crontab()
        updated: str = self._remove_block(current=current, schedule_id=definition.schedule_id)
        self._write_crontab(text=updated)
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="linux",
            installed=False,
            detail=definition.schedule_id,
        )

    def status(self, *, definition: ScheduleDefinitionDAO) -> ScheduleInstallStatusDAO:
        """Report whether the schedule's marker block is present in crontab.

        Args:
            definition (ScheduleDefinitionDAO): Schedule whose registration should be checked.

        Returns:
            ScheduleInstallStatusDAO: Current registration status.
        """
        current: str = self._read_current_crontab()
        installed: bool = f"# slo-schedule:{definition.schedule_id}" in current
        return ScheduleInstallStatusDAO(
            schedule_id=definition.schedule_id,
            platform="linux",
            installed=installed,
            detail=definition.schedule_id,
        )

    def render_block(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        executable: Path,
        log_paths: ScheduleLogPathsDAO,
    ) -> str:
        """Render the stable marker block for one schedule.

        Args:
            definition (ScheduleDefinitionDAO): Schedule to render.
            executable (Path): Resolved `slo` executable path.
            log_paths (ScheduleLogPathsDAO): Stdout/stderr log paths.

        Returns:
            str: Cron marker block.
        """
        expression: str = self._expression_for(definition=definition)
        command: str = (
            f"{executable} schedule execute --name {definition.schedule_id} "
            f">> {log_paths.stdout} 2>> {log_paths.stderr}"
        )
        return (
            f"# slo-schedule:{definition.schedule_id}\n"
            f"{expression} {command}\n"
            f"# /slo-schedule:{definition.schedule_id}\n"
        )

    def _expression_for(self, *, definition: ScheduleDefinitionDAO) -> str:
        """Return the cron expression supported by the installer.

        Args:
            definition (ScheduleDefinitionDAO): Schedule under installation.

        Returns:
            str: Five-field cron expression.
        """
        if not isinstance(definition.trigger, CronTriggerDAO):
            raise ValueError("Cron installer currently supports cron triggers only.")
        return definition.trigger.expression

    def _replace_block(
        self,
        *,
        current: str,
        definition: ScheduleDefinitionDAO,
        executable: Path,
        log_paths: ScheduleLogPathsDAO,
    ) -> str:
        """Replace or append the schedule block in the current crontab text."""
        without_block: str = self._remove_block(current=current, schedule_id=definition.schedule_id)
        if without_block and not without_block.endswith("\n"):
            without_block += "\n"
        return without_block + self.render_block(
            definition=definition,
            executable=executable,
            log_paths=log_paths,
        )

    @staticmethod
    def _remove_block(*, current: str, schedule_id: str) -> str:
        """Remove one marker block from crontab text.

        Args:
            current (str): Existing crontab text.
            schedule_id (str): Schedule whose block should be removed.

        Returns:
            str: Updated crontab text.
        """
        lines: list[str] = current.splitlines()
        start_marker: str = f"# slo-schedule:{schedule_id}"
        end_marker: str = f"# /slo-schedule:{schedule_id}"
        kept_lines: list[str] = []
        skipping: bool = False
        for line in lines:
            if line == start_marker:
                skipping = True
                continue
            if line == end_marker:
                skipping = False
                continue
            if not skipping:
                kept_lines.append(line)
        return "\n".join(line for line in kept_lines if line.strip()).strip()

    @staticmethod
    def _read_current_crontab() -> str:
        """Read the current user crontab text."""
        process = subprocess.run(
            ["crontab", "-l"],
            check=False,
            capture_output=True,
            text=True,
        )
        return process.stdout if process.returncode == 0 else ""

    @staticmethod
    def _write_crontab(*, text: str) -> None:
        """Overwrite the user crontab with ``text``."""
        subprocess.run(
            ["crontab", "-"],
            check=True,
            input=(text + "\n") if text else "",
            text=True,
        )
