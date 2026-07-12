"""Per-schedule overlap lock."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from src.scheduling.store import ScheduleStore

__all__ = ["ScheduleFireLock", "ScheduleFireLockFactory"]


class ScheduleFireLock:
    """Filesystem lock that prevents overlapping fires for one schedule."""

    def __init__(self, *, lock_path: Path) -> None:
        """Bind the lock to a concrete file path.

        Args:
            lock_path (Path): Lock-file path.
        """
        self._lock_path: Path = lock_path

    async def acquire(self) -> bool:
        """Try to acquire the lock without blocking.

        Returns:
            bool: True when the lock was acquired.
        """
        return await asyncio.to_thread(self._acquire_sync)

    async def release(self) -> None:
        """Release the lock when held."""
        await asyncio.to_thread(self._release_sync)

    def _acquire_sync(self) -> bool:
        """Synchronously create the lock file with ``O_EXCL`` semantics.

        Returns:
            bool: True when the lock was acquired.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd: int = os.open(
                self._lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            return False
        os.close(fd)
        return True

    def _release_sync(self) -> None:
        """Synchronously delete the lock file."""
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            return


class ScheduleFireLockFactory:
    """Build per-schedule overlap locks from the canonical store layout."""

    def build(self, *, schedule_id: str) -> ScheduleFireLock:
        """Return the overlap lock for ``schedule_id``.

        Args:
            schedule_id (str): Schedule identifier.

        Returns:
            ScheduleFireLock: Lock bound to the schedule directory.
        """
        directory: Path = ScheduleStore.directory_for(schedule_id=schedule_id)
        return ScheduleFireLock(lock_path=directory / ".fire.lock")
