"""Cleanup helpers for immutable schedule run records."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.scheduling.dao import ScheduleRunRecordDAO
from src.scheduling.store import ScheduleStore

__all__ = ["ScheduleCleanupService"]


class ScheduleCleanupService:
    """Prune old immutable fire records under ``runs/``."""

    def __init__(self, *, store: type[ScheduleStore] = ScheduleStore) -> None:
        """Bind the cleanup service to the canonical store.

        Args:
            store (type[ScheduleStore]): Store class to derive paths from.
        """
        self._store: type[ScheduleStore] = store

    def prune(self, *, schedule_id: str, keep: int) -> int:
        """Delete older run records, keeping the newest ``keep`` by fire time.

        Args:
            schedule_id (str): Schedule whose run records should be pruned.
            keep (int): Number of newest run records to retain.

        Returns:
            int: Number of deleted files.
        """
        runs_dir: Path = self._store.directory_for(schedule_id=schedule_id) / "runs"
        if not runs_dir.exists():
            return 0
        ordered_paths: list[Path] = self._paths_oldest_first(runs_dir=runs_dir)
        to_delete: list[Path] = ordered_paths[:-keep] if keep > 0 else ordered_paths
        for path in to_delete:
            path.unlink(missing_ok=True)
        return len(to_delete)

    @staticmethod
    def _paths_oldest_first(*, runs_dir: Path) -> list[Path]:
        """Return run-record paths ordered oldest-first by recorded start time.

        Args:
            runs_dir (Path): The schedule's ``runs/`` directory.

        Returns:
            list[Path]: Run-record file paths sorted by ``started_at``.
        """

        def _started_at(path: Path) -> datetime:
            try:
                record: ScheduleRunRecordDAO = ScheduleRunRecordDAO.model_validate_json(
                    path.read_text(encoding="utf-8"),
                )
            except (OSError, ValueError):
                return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            return record.started_at

        return sorted(runs_dir.glob("*.json"), key=_started_at)
