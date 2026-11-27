"""The engine's own store and the transition from the shared-file layout (ENG-X1).

The worker's schedule rows (Python ``sqlite3``) and the engine's jobs, locks,
schedules and dead letters (honker's bundled SQLite) live in separate files in
the schedules directory: two SQLite library copies in one process must never
share one WAL file. The engine file is hidden from ordinary listings, created
with the schedules database's private mode, and never shown to users.

Earlier builds kept the engine tables inside ``schedules.db``. Those rows are
preserved untouched — never read for work, migrated or deleted. Pending work
needs no import because every tick pass re-enqueues pending invocations from
the schedule rows, and a delivery of a finished invocation is a no-op.

Upgrade admission never infers that earlier workers are gone from the lock
rows in ``schedules.db``: a real earlier-layout worker opens that file through
two SQLite copies, and once its schedules pass closes, the locks it takes next
are written to an orphaned WAL no other process can read. So the first start
on a directory holding earlier-layout engine tables needs the operator's
confirmation that every earlier worker stopped; the engine file it creates
then records the admission. Visible unexpired locks still refuse the start,
as positive evidence only.

Everything is real: disposable schedules, channel and engine databases, the
honker engine, a separate process for the earlier-layout worker, and the CLI.
Only the fresh-run launcher is injected.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import honker
import pytest

from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.exceptions import ScheduleWorkerStartError
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.workflows import DELIVERY_QUEUE, DELIVERY_TASK_NAME, ScheduleEngine

_BOUND_SECONDS: float = 15.0

_EARLIER_LAYOUT_WORKER: str = """
import sys
import honker

store = honker.open(sys.argv[1])
lease = store.lock("honker-scheduler", ttl=60)
lease.__enter__()
print("held", flush=True)
sys.stdin.read()
lease.__exit__(None, None, None)
store.close()
"""
"""A worker of the earlier layout: holds its leader lock inside schedules.db until stdin closes."""

_DUAL_SQLITE_EARLIER_LAYOUT_WORKER: str = """
import sqlite3
import sys
import honker

db_path, queue, task, schedule_id, invocation_id = sys.argv[1:6]
store = honker.open(db_path)
kwargs = {"invocation_id": invocation_id, "schedule_id": schedule_id}
store.queue(queue).enqueue({"__honker_task__": {"task": task, "args": [], "kwargs": kwargs}})
schedules_pass = sqlite3.connect(db_path)
schedules_pass.execute("SELECT COUNT(*) FROM schedule_invocations").fetchone()
schedules_pass.commit()
schedules_pass.close()
lease = store.lock("honker-scheduler", ttl=60)
lease.__enter__()
print("held", flush=True)
sys.stdin.read()
lease.__exit__(None, None, None)
store.close()
"""
"""A worker of the earlier layout as it really ran: honker and Python ``sqlite3``
share schedules.db in one process. It enqueues the pending invocation's delivery
job, runs one schedules pass whose close deletes the WAL honker still uses, then
takes its leader lock — a lock other processes cannot see — and holds it until
stdin closes."""


class CompletingRunner:
    """Fresh-run starter that completes at once and counts its launches."""

    def __init__(self) -> None:
        """Start with no launches recorded."""
        self.start_calls: int = 0

    async def start(
        self,
        *,
        prompt: str,
        cwd: Optional[str],
        model: Optional[str],
        session_id: str,
    ) -> FreshRunResultDAO:
        """Record one launch and report it completed.

        Args:
            prompt (str): The schedule prompt.
            cwd (Optional[str]): The working directory override.
            model (Optional[str]): The model override.
            session_id (str): The minted session id.

        Returns:
            FreshRunResultDAO: A completed run.
        """
        self.start_calls += 1
        return FreshRunResultDAO(session_id=session_id, exit_code=0, status="completed")


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


async def _create_triggered_schedule(*, schedules_db_path: Path) -> tuple[str, str]:
    """Persist one fresh-running schedule with one pending invocation.

    Args:
        schedules_db_path (Path): The schedules database file.

    Returns:
        tuple[str, str]: The schedule id and the pending invocation id.
    """
    database = ScheduleDatabase(db_path=schedules_db_path)
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name="Earlier layout",
                prompt="earlier layout prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
            ),
            now=_utc_now(),
        )
        invocation = await service.trigger_now(reference=str(created.id), now=_utc_now())
    finally:
        await service.close()
        await database.close()
    return str(created.id), str(invocation.id)


def _seed_earlier_layout_engine_rows(
    *, schedules_db_path: Path, schedule_id: str, invocation_id: str
) -> None:
    """Write engine rows into schedules.db the way the earlier layout did.

    A pending delivery job for the invocation, a dead letter and a scheduler
    registration, written by a real honker handle that is closed before the
    test continues.

    Args:
        schedules_db_path (Path): The schedules database file.
        schedule_id (str): The schedule the delivery job names.
        invocation_id (str): The invocation the delivery job names.
    """
    store = honker.open(str(schedules_db_path))
    try:
        store.queue(DELIVERY_QUEUE).enqueue(
            {
                "__honker_task__": {
                    "task": DELIVERY_TASK_NAME,
                    "args": [],
                    "kwargs": {"invocation_id": invocation_id, "schedule_id": schedule_id},
                }
            }
        )
        with store.transaction() as transaction:
            transaction.query(
                "INSERT INTO _honker_dead (queue, payload, last_error) VALUES (?, ?, ?)",
                [DELIVERY_QUEUE, "{}", "earlier failure"],
            )
        scheduler = honker.Scheduler(store)
        scheduler.add(name="earlier-tick", queue="earlier-tick", schedule=honker.every_s(15), payload={})
    finally:
        store.close()


def _engine_rows_in(*, db_path: Path) -> dict[str, list[tuple[object, ...]]]:
    """Snapshot every engine table in one database file, read-only.

    Args:
        db_path (Path): The database file.

    Returns:
        dict[str, list[tuple[object, ...]]]: Every row of every ``_honker_*``
            table, keyed by table name.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '\\_honker\\_%' ESCAPE '\\'"
                " ORDER BY name"
            )
        ]
        return {table: list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid")) for table in tables}
    finally:
        connection.close()


def _invocation_status(*, schedules_db_path: Path, invocation_id: str) -> str:
    """Read one invocation's persisted status.

    Args:
        schedules_db_path (Path): The schedules database file.
        invocation_id (str): The invocation to read.

    Returns:
        str: The stored status.
    """
    connection = sqlite3.connect(f"file:{schedules_db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT status FROM schedule_invocations WHERE id = ?", (invocation_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


_IN_FLIGHT_STATUSES: frozenset[str] = frozenset({"pending", "running"})
"""Non-terminal invocation statuses; a fresh run is ``running`` until its child exits."""


async def _run_until_settled(*, engine: ScheduleEngine, schedules_db_path: Path, invocation_id: str) -> None:
    """Run the worker loop, tick once, and stop when the invocation reached a terminal status.

    Stopping on ``running`` would cancel the in-flight fresh run, leaving the
    row ``running`` for the caller's ``completed`` assertion.

    Args:
        engine (ScheduleEngine): The opened engine.
        schedules_db_path (Path): The schedules database file.
        invocation_id (str): The invocation to wait for.
    """
    stop_event = asyncio.Event()
    engine_run = asyncio.create_task(engine.run(stop_event=stop_event))
    try:
        await engine.tick_once()
        for _ in range(int(_BOUND_SECONDS / 0.1)):
            if (
                _invocation_status(schedules_db_path=schedules_db_path, invocation_id=invocation_id)
                not in _IN_FLIGHT_STATUSES
            ):
                break
            await asyncio.sleep(0.1)
    finally:
        stop_event.set()
        await asyncio.wait_for(engine_run, timeout=_BOUND_SECONDS)


def _engine(
    *, tmp_path: Path, runner: CompletingRunner, earlier_workers_stopped: bool = False
) -> ScheduleEngine:
    """Build one engine over the test's schedules directory.

    Args:
        tmp_path (Path): The test directory.
        runner (CompletingRunner): The injected fresh-run starter.
        earlier_workers_stopped (bool): The operator's upgrade confirmation
            that every earlier-layout worker has stopped.

    Returns:
        ScheduleEngine: The unopened engine.
    """
    return ScheduleEngine(
        db_path=tmp_path / "schedules" / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        history_root=tmp_path / "history",
        fresh_runs=runner,
        earlier_workers_stopped=earlier_workers_stopped,
    )


def _start_dual_sqlite_earlier_worker(
    *, schedules_db_path: Path, schedule_id: str, invocation_id: str
) -> subprocess.Popen[str]:
    """Start a real earlier-layout worker process and wait until it holds its lock.

    Args:
        schedules_db_path (Path): The shared schedules database file.
        schedule_id (str): The schedule its delivery job names.
        invocation_id (str): The pending invocation its delivery job names.

    Returns:
        subprocess.Popen[str]: The running process; closing its stdin stops it.
    """
    earlier_worker: subprocess.Popen[str] = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            _DUAL_SQLITE_EARLIER_LAYOUT_WORKER,
            str(schedules_db_path),
            DELIVERY_QUEUE,
            DELIVERY_TASK_NAME,
            schedule_id,
            invocation_id,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert earlier_worker.stdout is not None and earlier_worker.stdout.readline().strip() == "held"
    return earlier_worker


def _stop_earlier_worker(*, earlier_worker: subprocess.Popen[str]) -> None:
    """Stop an earlier-layout worker by closing its stdin and wait for it.

    Args:
        earlier_worker (subprocess.Popen[str]): The running process.
    """
    assert earlier_worker.stdin is not None
    earlier_worker.stdin.close()
    earlier_worker.wait(timeout=_BOUND_SECONDS)


async def test_engine_state_lives_in_a_private_hidden_file_beside_the_schedules_database(
    tmp_path: Path,
) -> None:
    """The engine opens its own private, hidden file in the schedules
    directory; a worker pass leaves no engine table in schedules.db."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    _schedule_id, invocation_id = await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    engine = _engine(tmp_path=tmp_path, runner=CompletingRunner())
    engine.open()
    try:
        await _run_until_settled(
            engine=engine, schedules_db_path=schedules_db_path, invocation_id=invocation_id
        )
    finally:
        engine.close()

    assert engine.engine_db_path.parent == schedules_db_path.parent
    assert engine.engine_db_path.name.startswith(".")
    assert stat.S_IMODE(engine.engine_db_path.stat().st_mode) == 0o600
    assert _engine_rows_in(db_path=schedules_db_path) == {}
    assert "_honker_live" in _engine_rows_in(db_path=engine.engine_db_path)
    assert _invocation_status(schedules_db_path=schedules_db_path, invocation_id=invocation_id) == "completed"
    listed_names = [path.name for path in schedules_db_path.parent.iterdir() if not path.name.startswith(".")]
    assert listed_names and all(name.startswith("schedules.db") for name in listed_names), listed_names


async def test_engine_refuses_a_symlinked_engine_file(tmp_path: Path) -> None:
    """A symlink at the engine path is refused before anything is opened."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()
    target = tmp_path / "elsewhere.db"
    target.write_bytes(b"")
    engine = _engine(tmp_path=tmp_path, runner=CompletingRunner())
    engine.engine_db_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="not a regular file"):
        engine.open()
    engine.close()
    assert target.read_bytes() == b""


async def test_earlier_layout_engine_rows_stay_untouched_and_pending_work_is_delivered_once(
    tmp_path: Path,
) -> None:
    """Upgrading from the shared-file layout: after the confirmed first start
    the earlier engine rows in schedules.db are preserved byte for byte, the
    pending invocation is delivered once through the tick re-enqueue, and a
    restart — admitted without a new confirmation — never relaunches it from
    the earlier delivery job."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    schedule_id, invocation_id = await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    _seed_earlier_layout_engine_rows(
        schedules_db_path=schedules_db_path, schedule_id=schedule_id, invocation_id=invocation_id
    )
    earlier_rows = _engine_rows_in(db_path=schedules_db_path)
    assert earlier_rows["_honker_live"] and earlier_rows["_honker_dead"]

    runner = CompletingRunner()
    for earlier_workers_stopped in (True, False):
        engine = _engine(tmp_path=tmp_path, runner=runner, earlier_workers_stopped=earlier_workers_stopped)
        engine.open()
        try:
            await _run_until_settled(
                engine=engine, schedules_db_path=schedules_db_path, invocation_id=invocation_id
            )
        finally:
            engine.close()

    assert _invocation_status(schedules_db_path=schedules_db_path, invocation_id=invocation_id) == "completed"
    assert runner.start_calls == 1, "the invocation was launched again"
    assert _engine_rows_in(db_path=schedules_db_path) == earlier_rows


async def test_worker_refuses_to_start_while_an_earlier_layout_worker_holds_its_locks(
    tmp_path: Path,
) -> None:
    """Visible unexpired earlier-layout locks are positive evidence that an
    earlier worker runs: the start is refused even with the operator's
    confirmation, that worker's rows are left alone, and the confirmed start
    succeeds once it has stopped."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    earlier_worker = subprocess.Popen(
        [sys.executable, "-I", "-c", _EARLIER_LAYOUT_WORKER, str(schedules_db_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert earlier_worker.stdout is not None and earlier_worker.stdout.readline().strip() == "held"
        engine = _engine(tmp_path=tmp_path, runner=CompletingRunner(), earlier_workers_stopped=True)
        with pytest.raises(ScheduleWorkerStartError, match="earlier version is still running"):
            engine.open()
        engine.close()
        assert not engine.engine_db_path.exists()
        held = [row[0] for row in _engine_rows_in(db_path=schedules_db_path)["_honker_locks"]]
        assert held == ["honker-scheduler"]
    finally:
        _stop_earlier_worker(earlier_worker=earlier_worker)
    assert earlier_worker.returncode == 0

    engine = _engine(tmp_path=tmp_path, runner=CompletingRunner(), earlier_workers_stopped=True)
    engine.open()
    engine.close()
    assert engine.engine_db_path.exists()


async def test_upgrade_waits_for_confirmation_while_a_dual_sqlite_earlier_worker_hides_its_locks(
    tmp_path: Path,
) -> None:
    """HIR111-01: a real earlier-layout worker whose locks are invisible to
    other processes does not get a second, unexcluded worker beside it. The
    unconfirmed start is refused without creating the engine file. After that
    worker stopped, the confirmed start delivers its pending invocation once
    through the tick re-enqueue, a restart needs no new confirmation and
    never relaunches it, and the earlier engine rows stay unchanged."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    schedule_id, invocation_id = await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    earlier_worker = _start_dual_sqlite_earlier_worker(
        schedules_db_path=schedules_db_path, schedule_id=schedule_id, invocation_id=invocation_id
    )
    try:
        visible_rows = _engine_rows_in(db_path=schedules_db_path)
        assert visible_rows["_honker_live"], "the earlier worker's delivery job is visible"
        assert visible_rows.get("_honker_locks", []) == [], "the earlier worker's lock is hidden"
        engine = _engine(tmp_path=tmp_path, runner=CompletingRunner())
        with pytest.raises(ScheduleWorkerStartError, match="--earlier-workers-stopped"):
            engine.open()
        engine.close()
        assert not engine.engine_db_path.exists()
    finally:
        _stop_earlier_worker(earlier_worker=earlier_worker)
    assert earlier_worker.returncode == 0
    earlier_rows = _engine_rows_in(db_path=schedules_db_path)

    refused = _engine(tmp_path=tmp_path, runner=CompletingRunner())
    with pytest.raises(ScheduleWorkerStartError, match="--earlier-workers-stopped"):
        refused.open()
    refused.close()
    runner = CompletingRunner()
    for earlier_workers_stopped in (True, False):
        engine = _engine(tmp_path=tmp_path, runner=runner, earlier_workers_stopped=earlier_workers_stopped)
        engine.open()
        try:
            await _run_until_settled(
                engine=engine, schedules_db_path=schedules_db_path, invocation_id=invocation_id
            )
        finally:
            engine.close()

    assert _invocation_status(schedules_db_path=schedules_db_path, invocation_id=invocation_id) == "completed"
    assert runner.start_calls == 1, "the invocation was launched again"
    assert _engine_rows_in(db_path=schedules_db_path) == earlier_rows


async def test_a_fresh_directory_starts_without_an_upgrade_confirmation(tmp_path: Path) -> None:
    """A schedules directory without earlier-layout engine tables — a new
    install or an upgrade from a released build — starts unconfirmed."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    engine = _engine(tmp_path=tmp_path, runner=CompletingRunner())
    engine.open()
    engine.close()
    assert engine.engine_db_path.exists()


async def test_cli_worker_upgrade_is_refused_while_an_earlier_worker_runs_then_starts_when_confirmed(
    tmp_path: Path,
) -> None:
    """`slo schedule worker` beside a real earlier-layout worker prints one
    diagnostic naming the confirmation flag and exits 1 without an engine
    file. Once that worker stopped, `slo schedule worker
    --earlier-workers-stopped` starts, registers its tick and stops cleanly
    on SIGTERM."""
    schedules_db_path = tmp_path / "schedules" / "schedules.db"
    schedule_id, invocation_id = await _create_triggered_schedule(schedules_db_path=schedules_db_path)
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "SLO_HOME": str(home),
        "SLO_SCHEDULES_DIR": str(schedules_db_path.parent),
        "SLO_ENV": "test",
        "SLO_HERDR_DISABLED": "1",
        "SLO_PLUGINS_DISABLED": "1",
    }
    earlier_worker = _start_dual_sqlite_earlier_worker(
        schedules_db_path=schedules_db_path, schedule_id=schedule_id, invocation_id=invocation_id
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.cli", "schedule", "worker"],
            cwd=Path.cwd(),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        _stop_earlier_worker(earlier_worker=earlier_worker)
    engine_db_path = _engine(tmp_path=tmp_path, runner=CompletingRunner()).engine_db_path
    assert completed.returncode == 1, completed.stderr
    assert "--earlier-workers-stopped" in completed.stderr
    assert not engine_db_path.exists()

    worker = subprocess.Popen(
        [sys.executable, "-m", "src.cli", "schedule", "worker", "--earlier-workers-stopped"],
        cwd=Path.cwd(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_registered_tick(engine_db_path=engine_db_path)
        worker.terminate()
        output, _ = worker.communicate(timeout=30)
        assert worker.returncode == 0, output
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=10)


def _wait_for_registered_tick(*, engine_db_path: Path) -> None:
    """Wait, with a bound, until a worker's tick registration is visible here.

    Args:
        engine_db_path (Path): The engine's own database file.
    """
    deadline: float = time.monotonic() + 30
    while time.monotonic() < deadline:
        if engine_db_path.is_file():
            try:
                tables = _engine_rows_in(db_path=engine_db_path)
            except sqlite3.Error:
                tables = {}
            if any(row[0] == "schedule-tick" for row in tables.get("_honker_scheduler_tasks", [])):
                return
        time.sleep(0.2)
    raise AssertionError("the confirmed worker never registered its tick within the wait bound")
