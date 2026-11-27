"""Test-owned helpers for real schedule worker processes (OPS111).

Every helper works only inside a test's own temporary directories. The cleanup
retires a worker through its identity-bound control channel first; only a
worker that cannot answer (for example one a test stopped with SIGSTOP) is
killed, and only after its process environment proves it serves this test's
own schedules directory.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.worker_runtime import (
    ScheduleWorkerLocationDAO,
    ScheduleWorkerRuntime,
)

__all__ = [
    "TUNED_WORKER_MODULE",
    "cli_environment",
    "live_worker_pids",
    "read_worker_metadata",
    "retire_workers_under",
    "run_cli",
    "location_for",
]

TUNED_WORKER_MODULE: str = "tests.schedules.worker_processes"
"""Run as ``python -m`` with ``schedule worker <schedules> <home> <cadence> <limit> <fresh seconds>``."""

_LOCK_FILE_NAME: str = ".schedule-worker.lock"
_METADATA_FILE_NAME: str = ".schedule-worker.json"


def location_for(*, schedules_dir: Path, slo_home: Path) -> ScheduleWorkerLocationDAO:
    """Build the resolved worker location a CLI run with these roots uses.

    Args:
        schedules_dir (Path): The test's schedules directory.
        slo_home (Path): The test's SLO_HOME.

    Returns:
        ScheduleWorkerLocationDAO: The resolved location.
    """
    return ScheduleWorkerLocationDAO.from_paths(
        db_path=schedules_dir / "schedules.db",
        channel_db_path=slo_home / "channels" / "channels.db",
        history_root=slo_home / "sessions" / "history",
    )


def cli_environment(*, schedules_dir: Path, slo_home: Path) -> dict[str, str]:
    """Build the environment of a CLI child confined to the test's roots.

    Args:
        schedules_dir (Path): The test's schedules directory.
        slo_home (Path): The test's SLO_HOME.

    Returns:
        dict[str, str]: The child environment.
    """
    return {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "SLO_HOME": str(slo_home),
        "SLO_SCHEDULES_DIR": str(schedules_dir),
        "SLO_ENV": "test",
        "SLO_HERDR_DISABLED": "1",
        "SLO_PLUGINS_DISABLED": "1",
    }


def run_cli(
    *, arguments: list[str], environment: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run one `slo` CLI command in its own process and wait (bounded) for it.

    Args:
        arguments (list[str]): The arguments after ``slo``.
        environment (dict[str, str]): The child environment.
        cwd (Path): The child working directory.

    Returns:
        subprocess.CompletedProcess[str]: The finished command.
    """
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


def read_worker_metadata(*, schedules_dir: Path) -> Optional[dict[str, Any]]:
    """Read the worker metadata file, or None when absent or unreadable.

    Args:
        schedules_dir (Path): The schedules directory.

    Returns:
        Optional[dict[str, Any]]: The parsed metadata.
    """
    try:
        return dict(json.loads((schedules_dir / _METADATA_FILE_NAME).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def live_worker_pids(*, schedules_dir: Path) -> list[int]:
    """Return the pids of live ``schedule worker`` processes serving one directory.

    The match is exact: the process environment's ``SLO_SCHEDULES_DIR`` must
    name this directory and its command line must run ``schedule worker``.
    Stopped zombies are excluded.

    Args:
        schedules_dir (Path): The test's schedules directory.

    Returns:
        list[int]: The matching pids.
    """
    wanted: bytes = f"SLO_SCHEDULES_DIR={schedules_dir.resolve()}".encode()
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status: str = (entry / "status").read_text(encoding="utf-8")
            command_line: bytes = (entry / "cmdline").read_bytes()
            environment: list[bytes] = (entry / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if "State:\tZ" in status:
            continue
        if b"schedule\0worker" in command_line and wanted in environment:
            matches.append(int(entry.name))
    return matches


def retire_workers_under(*, roots: list[Path]) -> None:
    """Stop every test worker whose lifetime lock lives under the given roots.

    Args:
        roots (list[Path]): Test-owned directories to search.
    """
    for root in roots:
        if not root.is_dir():
            continue
        for lock_path in root.rglob(_LOCK_FILE_NAME):
            _retire_one(schedules_dir=lock_path.parent)


def _retire_one(*, schedules_dir: Path) -> None:
    """Retire one directory's worker, killing it only when it cannot answer.

    Args:
        schedules_dir (Path): The worker's schedules directory.
    """
    pids: list[int] = live_worker_pids(schedules_dir=schedules_dir)
    for pid in pids:
        _continue_if_stopped(pid=pid)
    if pids:
        runtime = ScheduleWorkerRuntime(
            location=ScheduleWorkerLocationDAO.from_paths(
                db_path=schedules_dir / "schedules.db",
                channel_db_path=schedules_dir / "unused-channels.db",
                history_root=schedules_dir / "unused-history",
            )
        )
        try:
            asyncio.run(runtime.retire())
        except Exception:  # noqa: BLE001 — the kill below is the fallback
            pass
    deadline: float = time.monotonic() + 20
    while live_worker_pids(schedules_dir=schedules_dir) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pid in live_worker_pids(schedules_dir=schedules_dir):
        os.kill(pid, signal.SIGKILL)


def _continue_if_stopped(*, pid: int) -> None:
    """Resume a test-stopped worker so it can answer the retire request.

    Args:
        pid (int): A pid proven to serve the test's directory.
    """
    try:
        os.kill(pid, signal.SIGCONT)
    except ProcessLookupError:
        pass


class _SleepingFreshRunStarter:
    """Fresh-run starter at the process seam: each run is a real child that sleeps, then exits 0."""

    def __init__(self, *, seconds: float) -> None:
        """Bind the run length.

        Args:
            seconds (float): How long each fresh-run child runs.
        """
        self._seconds: float = seconds

    async def start(
        self, *, prompt: str, cwd: Optional[str], model: Optional[str], session_id: str
    ) -> FreshRunResultDAO:
        """Run one real child for the configured time and report its exit.

        Args:
            prompt (str): The schedule prompt (unused).
            cwd (Optional[str]): The working directory override (unused).
            model (Optional[str]): The model override (unused).
            session_id (str): The minted session id.

        Returns:
            FreshRunResultDAO: The child's result.
        """
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", f"import time; time.sleep({self._seconds})"
        )
        exit_code: int = await child.wait()
        return FreshRunResultDAO(
            session_id=session_id, exit_code=exit_code, status="completed" if exit_code == 0 else "run_failed"
        )


def run_tuned_worker(
    *,
    schedules_dir: Path,
    slo_home: Path,
    tick_cadence_seconds: int,
    progress_limit_seconds: float,
    fresh_run_seconds: float,
) -> None:
    """Run a real foreground worker whose engine uses test-sized tick and progress limits.

    Everything is real — lifetime lock, control channel, engine, stores —
    except that fresh runs are sleeping children instead of ``slo run``.

    Args:
        schedules_dir (Path): The test's schedules directory.
        slo_home (Path): The test's SLO_HOME.
        tick_cadence_seconds (int): The engine tick cadence.
        progress_limit_seconds (float): The engine's tick progress limit.
        fresh_run_seconds (float): How long each fresh run's child runs.
    """
    from src.schedules.worker import ScheduleWorker
    from src.schedules.workflows import ScheduleEngine

    location: ScheduleWorkerLocationDAO = location_for(schedules_dir=schedules_dir, slo_home=slo_home)
    engine = ScheduleEngine(
        db_path=location.db_path,
        channel_db_path=location.channel_db_path,
        history_root=location.history_root,
        tick_cadence_seconds=tick_cadence_seconds,
        progress_limit_seconds=progress_limit_seconds,
        fresh_runs=_SleepingFreshRunStarter(seconds=fresh_run_seconds),
    )
    ScheduleWorker(
        db_path=location.db_path, channel_db_path=location.channel_db_path, engine=engine, location=location
    ).run_foreground()


if __name__ == "__main__":
    _verb, _noun, schedules_arg, home_arg, cadence_arg, limit_arg, fresh_arg = sys.argv[1:]
    run_tuned_worker(
        schedules_dir=Path(schedules_arg),
        slo_home=Path(home_arg),
        tick_cadence_seconds=int(cadence_arg),
        progress_limit_seconds=float(limit_arg),
        fresh_run_seconds=float(fresh_arg),
    )
