"""Scheduler stdout/stderr log path helpers."""

from __future__ import annotations

from pathlib import Path

from config.cfg import SLO_HOME as _CFG_SLO_HOME
from src.scheduling.os.status import ScheduleLogPathsDAO

__all__ = ["ScheduleLogs"]


class ScheduleLogs:
    """Resolve and ensure scheduler log paths."""

    @classmethod
    def ensure(cls, *, schedule_id: str) -> ScheduleLogPathsDAO:
        """Ensure stdout/stderr log files exist for ``schedule_id``.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            ScheduleLogPathsDAO: Resolved log paths.
        """
        logs_dir: Path = (_CFG_SLO_HOME / "schedules" / "logs").resolve()
        logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stdout_path: Path = logs_dir / f"{schedule_id}.stdout.log"
        stderr_path: Path = logs_dir / f"{schedule_id}.stderr.log"
        stdout_path.touch(mode=0o600, exist_ok=True)
        stderr_path.touch(mode=0o600, exist_ok=True)
        return ScheduleLogPathsDAO(stdout=stdout_path, stderr=stderr_path)
