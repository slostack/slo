"""Engine delivery lifetime under lease loss, worker stop and repeated
cancellation (FRR111-03, 111.a.3 §5.6, 111.a.4 §5.6).

One delivery and its lease maintenance are one owned lifetime: whichever ends
first, the engine stops and joins the other before ``deliver_one`` returns,
releases the per-schedule lock in a ``finally``, and propagates the right
outcome — ``honker.Retryable`` for a lost or unmaintainable lease,
``asyncio.CancelledError`` for a worker stop. A cancellation that arrives while
the delivery is still cleaning up is not forwarded into that cleanup.

The process launcher and the honker lock are the injected boundaries; the
schedules database, channel store and honker engine are real.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID

import honker
import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.fresh_run import (
    FreshRunCommand,
    FreshRunInvoker,
    FreshRunResultDAO,
    SubprocessFreshRunLauncher,
)
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.workflows import DELIVERY_QUEUE, ScheduleEngine

_BOUND_SECONDS: float = 15.0


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


class PendingDeliveryDAO(BaseModel):
    """One persisted schedule and its pending invocation, ready to deliver."""

    model_config = ConfigDict(frozen=True)

    schedule_id: UUID = Field(description="The schedule that owns the invocation and the lock.")
    invocation_id: UUID = Field(description="The pending invocation the engine delivers.")


class CleanupRecordingRunner:
    """Fresh-run starter whose run blocks until cancelled, then cleans up.

    It stands in for the process launcher (an injected boundary). The cleanup
    takes ``cleanup_seconds`` like a child reap does; ``on_cancel`` decides
    what the cleanup ends with: re-raise the cancellation, swallow it and
    return a result, or fail with a cleanup error.
    """

    def __init__(
        self,
        *,
        cleanup_seconds: float,
        on_cancel: Literal["reraise", "swallow", "fail"] = "reraise",
        blocked_starts: int = 1,
    ) -> None:
        """Bind the cleanup duration and the cancellation outcome.

        Args:
            cleanup_seconds (float): How long the cancellation cleanup takes.
            on_cancel (Literal["reraise", "swallow", "fail"]): How the cleanup
                ends after it finishes.
            blocked_starts (int): How many initial starts block until
                cancelled; later starts complete at once with exit code 0.
        """
        self._cleanup_seconds: float = cleanup_seconds
        self._on_cancel: Literal["reraise", "swallow", "fail"] = on_cancel
        self._blocked_starts: int = blocked_starts
        self.start_calls: int = 0
        self.started: asyncio.Event = asyncio.Event()
        self.cleanup_started: asyncio.Event = asyncio.Event()
        self.cleanup_finished: bool = False

    async def start(
        self,
        *,
        prompt: str,
        cwd: Optional[str],
        model: Optional[str],
        session_id: str,
    ) -> FreshRunResultDAO:
        """Block until cancelled, then run the cleanup to completion.

        Starts after the first ``blocked_starts`` complete at once.

        Args:
            prompt (str): The schedule prompt.
            cwd (Optional[str]): The schedule's working directory override.
            model (Optional[str]): The schedule's model override.
            session_id (str): The minted session id for this run.

        Returns:
            FreshRunResultDAO: A completed result for an unblocked start, or a
                run_failed result when the cleanup swallows the cancellation.

        Raises:
            asyncio.CancelledError: When the cleanup re-raises.
            RuntimeError: When the cleanup fails.
        """
        self.start_calls += 1
        if self.start_calls > self._blocked_starts:
            return FreshRunResultDAO(session_id=session_id, exit_code=0, status="completed")
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cleanup_started.set()
            await asyncio.sleep(self._cleanup_seconds)
            self.cleanup_finished = True
            if self._on_cancel == "fail":
                raise RuntimeError("child cleanup failed") from None
            if self._on_cancel == "swallow":
                return FreshRunResultDAO(session_id=session_id, exit_code=143, status="run_failed")
            raise
        raise AssertionError("an un-set event never finishes waiting")


class RefusingRenewalLease:
    """Honker lock double whose first renewal reports the lease lost."""

    def __init__(self) -> None:
        """Start unacquired with no renewals or releases recorded."""
        self.renew_calls: int = 0
        self.release_calls: int = 0

    def __enter__(self) -> "RefusingRenewalLease":
        """Acquire the lease."""
        return self

    def renew(self, ttl: Optional[int] = None) -> bool:
        """Report the lease lost.

        Args:
            ttl (Optional[int]): Unused; matches the honker signature.

        Returns:
            bool: False — another owner took the lease.
        """
        self.renew_calls += 1
        return False

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        """Record the release."""
        self.release_calls += 1
        return False


class FailingRenewalLease(RefusingRenewalLease):
    """Honker lock double whose renewal transaction raises."""

    def renew(self, ttl: Optional[int] = None) -> bool:
        """Fail like a renewal whose storage write cannot commit.

        Args:
            ttl (Optional[int]): Unused; matches the honker signature.

        Returns:
            bool: Never returns.

        Raises:
            OSError: The renewal transaction failed.
        """
        self.renew_calls += 1
        raise OSError("renewal storage failed")


async def _create_pending_delivery(*, tmp_path: Path, name: str) -> PendingDeliveryDAO:
    """Persist one no-reference (fresh-running) schedule and one pending invocation.

    Args:
        tmp_path (Path): The test directory holding schedules.db.
        name (str): The schedule name.

    Returns:
        PendingDeliveryDAO: The schedule and invocation ids.
    """
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name=name,
                prompt=f"{name} prompt",
                trigger=IntervalTriggerDAO(every_seconds=3600),
                session_mode="continuous",
                cwd=str(tmp_path),
            ),
            now=_utc_now(),
        )
        invocation = await service.trigger_now(reference=str(created.id), now=_utc_now())
    finally:
        await service.close()
        await database.close()
    return PendingDeliveryDAO(schedule_id=created.id, invocation_id=invocation.id)


async def _trigger_again(*, tmp_path: Path, schedule_id: UUID) -> UUID:
    """Persist one more pending invocation for an existing schedule.

    Args:
        tmp_path (Path): The test directory holding schedules.db.
        schedule_id (UUID): The schedule to trigger.

    Returns:
        UUID: The new invocation id.
    """
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    try:
        invocation = await service.trigger_now(reference=str(schedule_id), now=_utc_now())
    finally:
        await service.close()
        await database.close()
    return invocation.id


async def _read_invocation_state(*, tmp_path: Path, invocation_id: UUID) -> tuple[str, Optional[str]]:
    """Read one invocation's persisted status and failure reason back.

    Args:
        tmp_path (Path): The test directory holding schedules.db.
        invocation_id (UUID): The invocation to read.

    Returns:
        tuple[str, Optional[str]]: The status and the failure reason.
    """
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    try:
        async with database.transaction() as transaction:
            invocation = await ScheduleInvocationRepository().get(
                invocation_id=invocation_id, transaction=transaction
            )
    finally:
        await database.close()
    assert invocation is not None
    return invocation.status, invocation.failure_reason


def _delivery_jobs_seen_by_another_process(*, engine_db_path: Path) -> list[str]:
    """Read the engine's delivery-job states the way a separate process (the CLI) sees them.

    The read runs in an isolated child interpreter with a read-only connection,
    so it shares no SQLite state with the engine under test.

    Args:
        engine_db_path (Path): The engine's own database file.

    Returns:
        list[str]: One state per queued delivery job, in id order.
    """
    reader = (
        "import sqlite3, sys\n"
        "connection = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=5)\n"
        "rows = connection.execute('SELECT state FROM _honker_live WHERE queue = ? ORDER BY id', (sys.argv[2],))\n"
        "print(' '.join(row[0] for row in rows))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", reader, str(engine_db_path), DELIVERY_QUEUE],
        capture_output=True,
        text=True,
        timeout=_BOUND_SECONDS,
        check=True,
    )
    return completed.stdout.split()


def _held_lock_names_seen_by_another_process(*, engine_db_path: Path) -> list[str]:
    """Read the engine's held lock names from a separate read-only process.

    Args:
        engine_db_path (Path): The engine's own database file.

    Returns:
        list[str]: The held lock names, sorted.
    """
    reader = (
        "import sqlite3, sys\n"
        "connection = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=5)\n"
        "print(' '.join(row[0] for row in connection.execute('SELECT name FROM _honker_locks ORDER BY name')))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", reader, str(engine_db_path)],
        capture_output=True,
        text=True,
        timeout=_BOUND_SECONDS,
        check=True,
    )
    return completed.stdout.split()


def _engine(
    *,
    tmp_path: Path,
    fresh_runs: object,
    lease: Optional[RefusingRenewalLease] = None,
    run_timeout_seconds: int = 3600,
) -> ScheduleEngine:
    """Build one engine on the test databases with the injected boundaries.

    Args:
        tmp_path (Path): The test directory.
        fresh_runs (object): The fresh-run starter the engine's deliver service uses.
        lease (Optional[RefusingRenewalLease]): A lock double; None keeps the
            engine's real honker lock.
        run_timeout_seconds (int): The restart-recovery run timeout.

    Returns:
        ScheduleEngine: The unopened engine.
    """
    return ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        history_root=tmp_path / "history",
        run_timeout_seconds=run_timeout_seconds,
        delivery_lock_ttl_seconds=1 if lease is not None else 60,
        delivery_locks=(lambda schedule_id: lease) if lease is not None else None,
        fresh_runs=fresh_runs,  # type: ignore[arg-type]  # each double implements FreshRunStarter
    )


async def test_lease_refusal_joins_the_delivery_cleanup_before_retrying(tmp_path: Path) -> None:
    """A refused renewal cancels the delivery, waits for its cleanup, releases
    the lease, then asks the worker to retry."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Refused lease")
    runner = CleanupRecordingRunner(cleanup_seconds=0.3)
    lease = RefusingRenewalLease()
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner, lease=lease)
    engine.open()
    try:
        with pytest.raises(honker.Retryable, match="lost"):
            await asyncio.wait_for(
                engine.deliver_one(
                    invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id)
                ),
                timeout=_BOUND_SECONDS,
            )
        assert runner.cleanup_finished, "deliver_one returned before the delivery finished its cleanup"
        assert lease.release_calls == 1
        assert runner.start_calls == 1
    finally:
        engine.close()


async def test_renewal_error_joins_the_delivery_and_chains_the_error(tmp_path: Path) -> None:
    """A renewal that raises stops and joins the delivery, releases the lease,
    and surfaces a retry whose cause is the renewal error."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Failing renewal")
    runner = CleanupRecordingRunner(cleanup_seconds=0.3)
    lease = FailingRenewalLease()
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner, lease=lease)
    engine.open()
    try:
        with pytest.raises(honker.Retryable) as raised:
            await asyncio.wait_for(
                engine.deliver_one(
                    invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id)
                ),
                timeout=_BOUND_SECONDS,
            )
        assert isinstance(raised.value.__cause__, OSError)
        assert runner.cleanup_finished
        assert lease.renew_calls == 1
        assert lease.release_calls == 1
    finally:
        engine.close()


async def test_lease_refusal_retries_even_when_the_delivery_swallows_cancellation(tmp_path: Path) -> None:
    """A delivery that absorbs its cancellation still ran without ownership:
    the engine reports the lost lease instead of a silent success."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Swallowing delivery")
    runner = CleanupRecordingRunner(cleanup_seconds=0.1, on_cancel="swallow")
    lease = RefusingRenewalLease()
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner, lease=lease)
    engine.open()
    try:
        with pytest.raises(honker.Retryable, match="lost"):
            await asyncio.wait_for(
                engine.deliver_one(
                    invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id)
                ),
                timeout=_BOUND_SECONDS,
            )
        assert lease.release_calls == 1
    finally:
        engine.close()


async def test_release_runs_when_the_delivery_cleanup_raises(tmp_path: Path) -> None:
    """A delivery whose cleanup fails after a renewal error still releases the
    lease exactly once; the retry carries the renewal error."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Failing cleanup")
    runner = CleanupRecordingRunner(cleanup_seconds=0.05, on_cancel="fail")
    lease = FailingRenewalLease()
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner, lease=lease)
    engine.open()
    try:
        with pytest.raises(honker.Retryable) as raised:
            await asyncio.wait_for(
                engine.deliver_one(
                    invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id)
                ),
                timeout=_BOUND_SECONDS,
            )
        assert isinstance(raised.value.__cause__, OSError)
        assert lease.release_calls == 1
    finally:
        engine.close()


async def test_cancellation_during_lease_loss_cleanup_finishes_cleanup_and_propagates(
    tmp_path: Path,
) -> None:
    """A worker stop that arrives while a lease-lost delivery is cleaning up
    neither interrupts that cleanup nor turns into a retry: the cleanup ends,
    the lease is released and the cancellation propagates."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Stop during lease cleanup")
    runner = CleanupRecordingRunner(cleanup_seconds=0.5)
    lease = RefusingRenewalLease()
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner, lease=lease)
    engine.open()
    try:
        delivery = asyncio.create_task(
            engine.deliver_one(invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id))
        )
        await asyncio.wait_for(runner.cleanup_started.wait(), timeout=_BOUND_SECONDS)
        delivery.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(delivery, timeout=_BOUND_SECONDS)
        assert runner.cleanup_finished, "the stop interrupted the delivery cleanup"
        assert lease.release_calls == 1
    finally:
        engine.close()


async def test_repeated_worker_cancellation_keeps_joining_and_releases_the_real_lock(
    tmp_path: Path,
) -> None:
    """Worker stop cancels a running delivery; further cancellations while its
    cleanup runs are not forwarded. The cleanup finishes, the cancellation
    propagates, and the real honker lock is free: the next invocation of the
    same schedule delivers instead of being refused."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Repeated stop")
    next_invocation_id = await _trigger_again(tmp_path=tmp_path, schedule_id=pending.schedule_id)
    runner = CleanupRecordingRunner(cleanup_seconds=0.6)
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner)
    engine.open()
    try:
        delivery = asyncio.create_task(
            engine.deliver_one(invocation_id=str(pending.invocation_id), schedule_id=str(pending.schedule_id))
        )
        await asyncio.wait_for(runner.started.wait(), timeout=_BOUND_SECONDS)
        delivery.cancel()
        await asyncio.wait_for(runner.cleanup_started.wait(), timeout=_BOUND_SECONDS)
        for _ in range(3):
            await asyncio.sleep(0.05)
            delivery.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(delivery, timeout=_BOUND_SECONDS)
        assert runner.cleanup_finished, "a repeated cancellation cut the delivery cleanup short"

        await asyncio.wait_for(
            engine.deliver_one(invocation_id=str(next_invocation_id), schedule_id=str(pending.schedule_id)),
            timeout=_BOUND_SECONDS,
        )
        assert runner.start_calls == 2, "the released lock admitted the next delivery"
    finally:
        engine.close()
    assert await _read_invocation_state(tmp_path=tmp_path, invocation_id=next_invocation_id) == (
        "completed",
        None,
    )


def _terminate_resistant_slo(*, bin_dir: Path, pid_file: Path) -> FreshRunCommand:
    """Write a harmless python ``slo`` stand-in that ignores SIGTERM.

    It records its pid and sleeps; only SIGKILL stops it. It lives only under
    the test directory; no system or PATH binary is touched.

    Args:
        bin_dir (Path): The test-owned directory that holds the stand-in.
        pid_file (Path): Where each started child appends its pid.

    Returns:
        FreshRunCommand: The real command policy pointed at the stand-in.
    """
    bin_dir.mkdir()
    stand_in = bin_dir / "slo"
    stand_in.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"with open({str(pid_file)!r}, 'a') as pid_out:\n"
        "    pid_out.write(f'{os.getpid()}\\n')\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    stand_in.chmod(0o755)
    assert stand_in.resolve().is_relative_to(bin_dir.resolve())
    return FreshRunCommand(venv_bin_dir=bin_dir, path_lookup=lambda name: None)


def _is_process_alive(*, pid: int) -> bool:
    """Return whether one pid still names a live (unreaped) process."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_for_child_pids(*, pid_file: Path, count: int) -> list[int]:
    """Wait, with a bound, until ``count`` children recorded their pids."""
    for _ in range(int(_BOUND_SECONDS / 0.05)):
        if pid_file.exists():
            pids = [int(line) for line in pid_file.read_text(encoding="utf-8").split()]
            if len(pids) >= count:
                return pids
        await asyncio.sleep(0.05)
    raise AssertionError("the fresh-run child never started")


async def test_worker_stop_kills_a_terminate_resistant_child_and_recovery_never_relaunches(
    tmp_path: Path,
) -> None:
    """Worker stop with an active fresh child that ignores SIGTERM: the engine
    run ends only after the child is killed and reaped, and the next worker start recovers the row as run_failed without a second
    launch (111.a.3 §5.6, D24)."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Stubborn child")
    pid_file = tmp_path / "children.pid"
    command = _terminate_resistant_slo(bin_dir=tmp_path / "probe-bin", pid_file=pid_file)
    fresh_runs = FreshRunInvoker(launcher=SubprocessFreshRunLauncher(command=command), command=command)

    engine = _engine(tmp_path=tmp_path, fresh_runs=fresh_runs)
    engine.open()
    child_pid: Optional[int] = None
    try:
        stop_event = asyncio.Event()
        engine_run = asyncio.create_task(engine.run(stop_event=stop_event))
        await engine.enqueue_delivery(invocation_id=pending.invocation_id, schedule_id=pending.schedule_id)
        child_pid = (await _wait_for_child_pids(pid_file=pid_file, count=1))[0]
        assert await _read_invocation_state(tmp_path=tmp_path, invocation_id=pending.invocation_id) == (
            "running",
            None,
        )

        stop_event.set()
        await asyncio.wait_for(engine_run, timeout=_BOUND_SECONDS + 10)
        assert not _is_process_alive(pid=child_pid), "worker stop left the terminate-resistant child running"
    finally:
        engine.close()
        if child_pid is not None and _is_process_alive(pid=child_pid):
            os.kill(child_pid, signal.SIGKILL)

    restarted = _engine(tmp_path=tmp_path, fresh_runs=fresh_runs, run_timeout_seconds=0)
    restarted.open()
    try:
        stop_event = asyncio.Event()
        restarted_run = asyncio.create_task(restarted.run(stop_event=stop_event))
        for _ in range(int(_BOUND_SECONDS / 0.1)):
            state = await _read_invocation_state(tmp_path=tmp_path, invocation_id=pending.invocation_id)
            if state[0] != "running":
                break
            await asyncio.sleep(0.1)
        stop_event.set()
        await asyncio.wait_for(restarted_run, timeout=_BOUND_SECONDS)
    finally:
        restarted.close()
    assert await _read_invocation_state(tmp_path=tmp_path, invocation_id=pending.invocation_id) == (
        "run_failed",
        "run_timeout",
    )
    assert len(pid_file.read_text(encoding="utf-8").split()) == 1, "the recovered row was launched again"


async def test_engine_lifetimes_repeat_open_run_stop_close_in_one_process(tmp_path: Path) -> None:
    """Three sequential engines on one database each open, deliver through
    their own registration, stop and close; per-engine registration survives
    repetition (FIR111-03)."""
    for round_number in range(3):
        pending = await _create_pending_delivery(tmp_path=tmp_path, name=f"Repeat round {round_number}")
        runner = CleanupRecordingRunner(cleanup_seconds=0.0, on_cancel="swallow")
        engine = _engine(tmp_path=tmp_path, fresh_runs=runner)
        engine.open()
        try:
            stop_event = asyncio.Event()
            engine_run = asyncio.create_task(engine.run(stop_event=stop_event))
            await engine.enqueue_delivery(
                invocation_id=pending.invocation_id, schedule_id=pending.schedule_id
            )
            await asyncio.wait_for(runner.started.wait(), timeout=_BOUND_SECONDS)
            stop_event.set()
            await asyncio.wait_for(engine_run, timeout=_BOUND_SECONDS)
        finally:
            engine.close()
        assert runner.start_calls == 1


async def test_engine_writes_after_a_schedules_pass_stay_visible_to_other_connections(
    tmp_path: Path,
) -> None:
    """Every delivery job the engine enqueues between production tick passes
    is visible to another process (the CLI, a restarted worker) while the
    engine is open, and still there after it closes (ENG-X1)."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Visible engine write")
    engine = _engine(tmp_path=tmp_path, fresh_runs=CleanupRecordingRunner(cleanup_seconds=0.0))
    engine.open()
    try:
        for enqueued_count in range(1, 4):
            await engine.tick_once()
            await engine.enqueue_delivery(
                invocation_id=pending.invocation_id, schedule_id=pending.schedule_id
            )
            # Each tick pass re-enqueues the pending row too: two jobs per round.
            assert len(_delivery_jobs_seen_by_another_process(engine_db_path=engine.engine_db_path)) == (
                2 * enqueued_count
            ), "an engine write after a schedules pass is invisible to other processes"
    finally:
        engine.close()
    assert _delivery_jobs_seen_by_another_process(engine_db_path=engine.engine_db_path) == ["pending"] * 6


async def test_engine_writes_stay_visible_while_the_worker_delivers(tmp_path: Path) -> None:
    """While the worker loop runs a delivery, another process sees the claimed
    job and the held schedule lock in the engine store, and the running row in
    the schedules database; after stop and close the store is still readable
    (ENG-X1)."""
    pending = await _create_pending_delivery(tmp_path=tmp_path, name="Visible active write")
    runner = CleanupRecordingRunner(cleanup_seconds=0.0)
    engine = _engine(tmp_path=tmp_path, fresh_runs=runner)
    engine.open()
    try:
        stop_event = asyncio.Event()
        engine_run = asyncio.create_task(engine.run(stop_event=stop_event))
        await engine.enqueue_delivery(invocation_id=pending.invocation_id, schedule_id=pending.schedule_id)
        await asyncio.wait_for(runner.started.wait(), timeout=_BOUND_SECONDS)

        assert _delivery_jobs_seen_by_another_process(engine_db_path=engine.engine_db_path) == ["processing"]
        assert f"schedule-{pending.schedule_id}" in _held_lock_names_seen_by_another_process(
            engine_db_path=engine.engine_db_path
        )
        assert await _read_invocation_state(tmp_path=tmp_path, invocation_id=pending.invocation_id) == (
            "running",
            None,
        )
        stop_event.set()
        await asyncio.wait_for(engine_run, timeout=_BOUND_SECONDS)
    finally:
        engine.close()
    assert f"schedule-{pending.schedule_id}" not in _held_lock_names_seen_by_another_process(
        engine_db_path=engine.engine_db_path
    ), "worker stop left the schedule lock held"
    assert runner.start_calls == 1
