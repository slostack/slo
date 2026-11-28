"""Schedule engine upgrade admission (HIR111-01, ENG-X1, OPS111-09).

Two earlier development layouts ran workers this build cannot exclude:

- the **shared-file layout** kept Honker's tables inside ``schedules.db``.
  Its workers suffer the two-SQLite defect, so the locks they take after their
  first pass are invisible: lock rows never prove that such a worker stopped;
- the **hidden-engine layout without lifetime lock** kept them in the engine's
  own ``.schedule-engine.db`` but took no worker lifetime lock, so the lock that
  serializes every worker of this build cannot see it.

This module is the one owner of the admission decision. The worker applies it
before it opens the engine; the shared worker runtime applies the same
decision before it would launch a worker, so an unadmitted directory never
gets a competing process. Admission is recorded durably in a private marker
file the first time a start is admitted; from then on every worker of the
directory is one that takes the lifetime lock, and the marker alone admits.

The rules, in order:

1. Visible unexpired earlier-layout locks in ``schedules.db`` refuse every start.
2. A recorded admission admits.
3. Visible unexpired locks in an engine file that has no admission record
   refuse every start, even a confirmed one.
4. Otherwise earlier engine state (tables in ``schedules.db`` or an engine file
   without admission record) needs the operator's confirmation that every
   earlier worker stopped (``slo schedule worker --earlier-workers-stopped``).
   Missing or expired lock rows never stand in for that confirmation.
5. A directory without earlier engine state is admitted.

Nothing here writes ``schedules.db`` or the engine file; both are read through
read-only connections, and the engine file only before this process opens
Honker on it (two SQLite copies must never hold one file at once).
"""

from __future__ import annotations

import os
import sqlite3
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from src.schedules.exceptions import ScheduleWorkerStartError

__all__ = ["ENGINE_DATABASE_NAME", "EarlierLayoutStateDAO", "ScheduleEngineAdmission"]

ENGINE_DATABASE_NAME: str = ".schedule-engine.db"
"""The engine's own file in the schedules directory; the dot keeps it out of ordinary listings."""
_ADMISSION_RECORD_NAME: str = ".schedule-engine-admitted"
_ADMISSION_RECORD_MODE: int = 0o600
_READ_TIMEOUT_SECONDS: float = 5.0

EARLIER_WORKER_RUNNING_REASON: str = (
    "a schedule worker from an earlier version is still running; stop it, then start again"
)
UNCONFIRMED_UPGRADE_REASON: str = (
    "this schedules directory holds engine state from an earlier development build of the schedule"
    " worker, whose running workers cannot be detected; stop every earlier `slo schedule worker`,"
    " then run `slo schedule worker --earlier-workers-stopped` once"
)


class EarlierLayoutStateDAO(BaseModel):
    """What one store shows of an earlier engine layout.

    Read-only facts for upgrade admission. An absent lock count never proves
    that no earlier worker runs.
    """

    has_engine_state: bool = Field(
        description="True when the store holds any _honker_* table an earlier build created."
    )
    held_lock_count: int = Field(
        ge=0,
        description="Unexpired _honker_locks rows other processes can see; positive evidence only.",
    )


class ScheduleEngineAdmission:
    """Decide whether a worker may start on one schedules directory, and record it."""

    def __init__(self, *, db_path: Path) -> None:
        """Bind the schedules database; the engine file and record live beside it.

        Args:
            db_path (Path): The schedules database file.
        """
        self._db_path: Path = db_path
        self._engine_db_path: Path = db_path.with_name(ENGINE_DATABASE_NAME)
        self._record_path: Path = db_path.with_name(_ADMISSION_RECORD_NAME)

    @property
    def engine_db_path(self) -> Path:
        """Return the engine's own database file."""
        return self._engine_db_path

    def ensure_admitted(self, *, earlier_workers_stopped: bool) -> None:
        """Refuse a start that an earlier worker could run beside; never writes anything.

        Args:
            earlier_workers_stopped (bool): The operator's confirmation that
                every earlier worker stopped; never assumed automatically.

        Raises:
            ScheduleWorkerStartError: When an earlier worker visibly runs, or
                earlier engine state lacks the confirmation.
        """
        self._ensure_engine_path_regular()
        shared_file: EarlierLayoutStateDAO = self._read(path=self._db_path)
        if shared_file.held_lock_count > 0:
            raise ScheduleWorkerStartError(reason=EARLIER_WORKER_RUNNING_REASON)
        if self._is_recorded():
            return
        if self._read(path=self._engine_db_path).held_lock_count > 0:
            raise ScheduleWorkerStartError(reason=EARLIER_WORKER_RUNNING_REASON)
        has_earlier_state: bool = shared_file.has_engine_state or os.path.lexists(self._engine_db_path)
        if earlier_workers_stopped or not has_earlier_state:
            return
        raise ScheduleWorkerStartError(reason=UNCONFIRMED_UPGRADE_REASON)

    def record(self) -> None:
        """Record that this directory's starts are admitted; called by an admitted worker only.

        Raises:
            RuntimeError: When the record path exists but is not a regular file.
        """
        if self._is_recorded():
            return
        if os.path.lexists(self._record_path):
            raise RuntimeError(f"Schedule engine admission record is not a regular file: {self._record_path}")
        staging: Path = self._record_path.with_name(f"{_ADMISSION_RECORD_NAME}.{os.getpid()}.tmp")
        descriptor: int = os.open(
            staging,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC,
            _ADMISSION_RECORD_MODE,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(datetime.now(tz=timezone.utc).isoformat())
        os.replace(staging, self._record_path)

    def _ensure_engine_path_regular(self) -> None:
        """Refuse an engine path that exists but is not a regular file; it is never followed or read.

        Raises:
            ScheduleWorkerStartError: When the engine path is a symlink, directory or other kind.
        """
        try:
            mode: int = self._engine_db_path.lstat().st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISREG(mode):
            raise ScheduleWorkerStartError(
                reason=f"Schedule engine path is not a regular file: {self._engine_db_path.name}"
            )

    def _is_recorded(self) -> bool:
        """Tell whether the admission record exists as a regular file (never following links)."""
        try:
            return stat.S_ISREG(self._record_path.lstat().st_mode)
        except FileNotFoundError:
            return False

    @staticmethod
    def _read(*, path: Path) -> EarlierLayoutStateDAO:
        """Read what one store shows of an engine layout, read-only.

        Args:
            path (Path): ``schedules.db`` or the engine file.

        Returns:
            EarlierLayoutStateDAO: No state and no locks when the file is
                absent; no visible locks when it cannot be read (the
                confirmation rule still applies).
        """
        if not path.is_file():
            return EarlierLayoutStateDAO(has_engine_state=False, held_lock_count=0)
        try:
            connection: sqlite3.Connection = sqlite3.connect(
                database=f"file:{path}?mode=ro", uri=True, timeout=_READ_TIMEOUT_SECONDS
            )
        except sqlite3.Error:
            return EarlierLayoutStateDAO(has_engine_state=True, held_lock_count=0)
        try:
            return ScheduleEngineAdmission._read_open(connection=connection)
        except sqlite3.Error:
            return EarlierLayoutStateDAO(has_engine_state=True, held_lock_count=0)
        finally:
            connection.close()

    @staticmethod
    def _read_open(*, connection: sqlite3.Connection) -> EarlierLayoutStateDAO:
        """Count the engine tables and the unexpired lock rows of one open store.

        Args:
            connection (sqlite3.Connection): A read-only connection.

        Returns:
            EarlierLayoutStateDAO: The facts.
        """
        engine_tables: set[str] = {
            str(table_row[0])
            for table_row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '\\_honker\\_%' ESCAPE '\\'"
            )
        }
        if "_honker_locks" not in engine_tables:
            return EarlierLayoutStateDAO(has_engine_state=bool(engine_tables), held_lock_count=0)
        held_lock_count: int = int(
            connection.execute(
                "SELECT COUNT(*) FROM _honker_locks WHERE expires_at > ?", (int(time.time()),)
            ).fetchone()[0]
        )
        return EarlierLayoutStateDAO(has_engine_state=True, held_lock_count=held_lock_count)
