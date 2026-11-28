"""Fresh-run delivery tests (111.a.3 A3–A6, T3.3) on real SQLite with a scripted runner."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import subprocess
import sys
import time

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.channel_delivery import ScheduleChannelSender
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleInvocationDAO,
    TriggerDAO,
)
from src.schedules.database import ScheduleDatabase, format_instant
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.fresh_run import (
    FreshRunCommand,
    FreshRunInvoker,
    FreshRunResultDAO,
    SubprocessFreshRunLauncher,
    UnsupportedFreshRunWrapperError,
)
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


_RUN_DURATION_SECONDS = 1200


class ScriptedClock:
    """Test-owned boundary clock: the instant moves only when a test moves it."""

    def __init__(self, *, now: datetime) -> None:
        """Start the scripted clock at one fixed instant.

        Args:
            now (datetime): The instant the clock starts at.
        """
        self._now: datetime = now

    def now(self) -> datetime:
        """Return the current scripted instant."""
        return self._now

    def advance_by(self, *, seconds: float) -> None:
        """Move the scripted instant forward.

        Args:
            seconds (float): How far the instant moves.
        """
        self._now = self._now + timedelta(seconds=seconds)


def _fresh_input(
    *, trigger: TriggerDAO | None = None, cwd: str | None = None, model: str | None = None
) -> NewScheduleDAO:
    """Build one fresh schedule input.

    Args:
        trigger (TriggerDAO | None): The trigger; an hourly interval when None.
        cwd (str | None): The fresh-run working directory override.
        model (str | None): The fresh-run model override.

    Returns:
        NewScheduleDAO: The validated schedule input.
    """
    return NewScheduleDAO(
        name="Fresh target",
        prompt="fresh run prompt",
        trigger=trigger if trigger is not None else IntervalTriggerDAO(every_seconds=3600),
        session_mode="fresh",
        cwd=cwd,
        model=model,
    )


class FreshRunCallDAO(BaseModel):
    """One start call the scripted fresh runner received."""

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(description="The schedule prompt the run was started with.")
    cwd: str | None = Field(description="The working directory override, or None.")
    model: str | None = Field(description="The model override, or None.")
    session_id: str = Field(description="The minted session id of the run.")


class ScriptedFreshRunner:
    """Records start calls and returns a configured exit code.

    The stub reads the invocation row inside ``start`` through the real database,
    so the test can assert that ``running`` was committed before the child started.
    """

    def __init__(
        self,
        *,
        exit_code: int,
        schedules_db: ScheduleDatabase,
        clock: ScriptedClock | None = None,
    ) -> None:
        """Bind the scripted outcome, the database and the optional clock.

        Args:
            exit_code (int): The child exit code each start reports.
            schedules_db (ScheduleDatabase): The real database the start reads.
            clock (ScriptedClock | None): Moved forward by the run duration on
                every start, when given.
        """
        self._exit_code: int = exit_code
        self._schedules_db: ScheduleDatabase = schedules_db
        self._clock: ScriptedClock | None = clock
        self._launch_error: Exception | None = None
        self.calls: list[FreshRunCallDAO] = []
        self.status_at_start: str | None = None

    def configure(self, *, exit_code: int) -> None:
        """Set the exit code the next start call returns.

        Args:
            exit_code (int): The child exit code to script.
        """
        self._exit_code = exit_code

    def fail_launches(self, *, error: Exception) -> None:
        """Make every later start fail as a launch the invoker could not start.

        Args:
            error (Exception): The error each start raises before recording a call.
        """
        self._launch_error = error

    async def start(
        self,
        *,
        prompt: str,
        cwd: str | None,
        model: str | None,
        session_id: str,
    ) -> FreshRunResultDAO:
        """Record the call, observe the row status and return the configured result.

        Args:
            prompt (str): The schedule prompt.
            cwd (str | None): The working directory override.
            model (str | None): The model override.
            session_id (str): The minted session id.

        Returns:
            FreshRunResultDAO: The scripted result.

        Raises:
            Exception: The configured launch error, when one is set.
        """
        if self._launch_error is not None:
            raise self._launch_error
        self.calls.append(FreshRunCallDAO(prompt=prompt, cwd=cwd, model=model, session_id=session_id))
        async with self._schedules_db.transaction() as transaction:
            row = await transaction.fetch_one(
                sql=("SELECT status FROM schedule_invocations" " WHERE recipient_session_id = ?"),
                parameters=(session_id,),
            )
        self.status_at_start = row["status"] if row is not None else None
        if self._clock is not None:
            self._clock.advance_by(seconds=_RUN_DURATION_SECONDS)
        status: Literal["completed", "run_failed"] = "completed" if self._exit_code == 0 else "run_failed"
        return FreshRunResultDAO(session_id=session_id, exit_code=self._exit_code, status=status)


class FreshRunHarnessDAO(BaseModel):
    """The typed collaborator set one fresh-run delivery test owns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    schedules_db: ScheduleDatabase = Field(description="The real tmp schedules database.")
    gateway: ChannelGateway = Field(description="The opened real channel gateway on a tmp store.")
    service: ScheduleService = Field(description="The schedule service over the tmp database.")
    deliver: DeliverScheduleInvocationAppService = Field(description="The deliver service under test.")
    runner: ScriptedFreshRunner = Field(
        description="The scripted fresh-run starter the deliver service uses."
    )
    clock: ScriptedClock = Field(description="The boundary clock the deliver service reads.")

    async def close(self) -> None:
        """Close the gateway, then the schedules database."""
        await self.gateway.close()
        await self.schedules_db.close()


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[FreshRunHarnessDAO]:
    """Real service, gateway and sender on tmp databases with a scripted runner."""
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    clock = ScriptedClock(now=_utc_now())
    runner = ScriptedFreshRunner(exit_code=0, schedules_db=schedules_db, clock=clock)
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    deliver = DeliverScheduleInvocationAppService(
        database=schedules_db,
        schedules=service,
        invocations=ScheduleInvocationRepository(),
        sender=ScheduleChannelSender(gateway=gateway),
        fresh_runs=runner,
        now_provider=clock.now,
    )
    built = FreshRunHarnessDAO(
        schedules_db=schedules_db,
        gateway=gateway,
        service=service,
        deliver=deliver,
        runner=runner,
        clock=clock,
    )
    yield built
    await built.close()


async def _create_and_trigger(
    *,
    harness: FreshRunHarnessDAO,
    now: datetime,
    trigger: TriggerDAO | None = None,
    cwd: str | None = None,
    model: str | None = None,
) -> ScheduleInvocationDAO:
    """Create one fresh schedule, trigger it and return the pending invocation.

    Args:
        harness (FreshRunHarnessDAO): The test's collaborators.
        now (datetime): The creation and trigger instant.
        trigger (TriggerDAO | None): The trigger; an hourly interval when None.
        cwd (str | None): The fresh-run working directory override.
        model (str | None): The fresh-run model override.

    Returns:
        ScheduleInvocationDAO: The pending invocation.
    """
    created = await harness.service.create(
        new_schedule=_fresh_input(trigger=trigger, cwd=cwd, model=model), now=now
    )
    return await harness.service.trigger_now(reference=str(created.id), now=now)


async def test_fresh_run_records_running_before_start_and_completes(
    harness: FreshRunHarnessDAO,
) -> None:
    """A3: running is committed before the start call; the run completes with exit code 0."""
    runner: ScriptedFreshRunner = harness.runner
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()

    invocation = await _create_and_trigger(harness=harness, now=now)
    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert runner.status_at_start == "running"
    assert delivered.status == "completed"
    assert delivered.run_exit_code == 0
    assert delivered.recipient_session_id == runner.calls[0].session_id
    assert len(runner.calls) == 1


async def test_failed_fresh_run_is_not_retried(harness: FreshRunHarnessDAO) -> None:
    """A4: a failed run is final; replay returns the stored row without a second start."""
    runner: ScriptedFreshRunner = harness.runner
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()
    runner.configure(exit_code=2)

    invocation = await _create_and_trigger(harness=harness, now=now)
    failed = await deliver.invoke(invocation_id=invocation.id, now=now)
    assert failed.status == "run_failed"
    assert failed.run_exit_code == 2

    replayed = await deliver.invoke(invocation_id=invocation.id, now=now)
    assert replayed.status == "run_failed"
    assert replayed.id == failed.id
    assert len(runner.calls) == 1


async def test_cwd_and_model_apply_only_to_headless_starts(
    harness: FreshRunHarnessDAO,
) -> None:
    """A6: the runner receives the schedule's cwd and model for the fresh run."""
    runner: ScriptedFreshRunner = harness.runner
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()

    invocation = await _create_and_trigger(harness=harness, now=now, cwd="/tmp/fresh-cwd", model="test-model")
    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "completed"
    assert runner.calls[0].cwd == "/tmp/fresh-cwd"
    assert runner.calls[0].model == "test-model"


async def test_running_rows_are_not_rerun_after_restart(
    harness: FreshRunHarnessDAO,
) -> None:
    """A8: a running row older than the run timeout is marked run_failed with
    its recovery reason and never re-run."""
    runner: ScriptedFreshRunner = harness.runner
    schedules_db: ScheduleDatabase = harness.schedules_db
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()
    invocation = await _create_and_trigger(harness=harness, now=now)
    async with schedules_db.transaction() as transaction:
        await ScheduleInvocationRepository().mark_running(
            invocation_id=invocation.id,
            recipient_session_id="stale-session",
            transaction=transaction,
        )
    # Age the row beyond the run timeout (3600 s default).
    async with schedules_db.transaction() as transaction:
        await transaction.execute(
            sql=("UPDATE schedule_invocations SET created_at = ?" " WHERE id = ? AND status = 'running'"),
            parameters=(
                format_instant(value=now - timedelta(seconds=3601)),
                str(invocation.id),
            ),
        )

    await deliver.recover_stale_running(now=now)

    recovered = await deliver.invoke(invocation_id=invocation.id, now=now)
    assert recovered.status == "run_failed"
    assert recovered.failure_reason == "run_timeout"
    assert recovered.delivered_at is not None
    assert len(runner.calls) == 0


async def test_stale_running_one_shot_is_disabled_by_recovery(
    harness: FreshRunHarnessDAO,
) -> None:
    """FIR111-06: restart recovery ends a recovered one-shot atomically."""
    service: ScheduleService = harness.service
    schedules_db: ScheduleDatabase = harness.schedules_db
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()
    invocation = await _create_and_trigger(
        harness=harness,
        now=now,
        trigger=OneShotTriggerDAO(run_at=now + timedelta(hours=1)),
    )
    async with schedules_db.transaction() as transaction:
        await ScheduleInvocationRepository().mark_running(
            invocation_id=invocation.id,
            recipient_session_id="stale-session",
            transaction=transaction,
        )
        await transaction.execute(
            sql=("UPDATE schedule_invocations SET created_at = ?" " WHERE id = ? AND status = 'running'"),
            parameters=(
                format_instant(value=now - timedelta(seconds=3601)),
                str(invocation.id),
            ),
        )

    await deliver.recover_stale_running(now=now)

    row = await service.show(reference=str(invocation.schedule_id))
    assert row.enabled is False
    assert row.next_due_at is None


async def test_launch_failure_settles_the_running_row(
    harness: FreshRunHarnessDAO,
) -> None:
    """FIR111-06: a launch failure after mark_running settles the row as
    run_failed with a reason and ends the one-shot; the row never sits running."""
    runner: ScriptedFreshRunner = harness.runner
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    now = _utc_now()
    invocation = await _create_and_trigger(
        harness=harness,
        now=now,
        trigger=OneShotTriggerDAO(run_at=now + timedelta(hours=1)),
    )

    runner.fail_launches(error=RuntimeError("spawn failed"))
    settled = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert settled.status == "run_failed"
    assert settled.failure_reason == "fresh_run_launch_failed"
    assert settled.run_exit_code is None
    row = await service.show(reference=str(invocation.schedule_id))
    assert row.enabled is False
    replayed = await deliver.invoke(invocation_id=invocation.id, now=now)
    assert replayed.status == "run_failed"


async def test_delivered_at_is_when_the_run_finished(harness: FreshRunHarnessDAO) -> None:
    """111.a.3 §5.3 step 4: ``delivered_at`` records the time the run finished.

    A fresh run can outlast the delivery entry instant (the run timeout allows
    3600 s), so the finish instant comes from the boundary clock the deliver
    service reads after the child exits — never from the invoke-entry ``now``.
    """
    clock: ScriptedClock = harness.clock
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    started_at: datetime = clock.now()

    invocation = await _create_and_trigger(harness=harness, now=started_at)
    delivered = await deliver.invoke(invocation_id=invocation.id, now=started_at)

    assert delivered.status == "completed"
    finished_at: datetime = started_at + timedelta(seconds=_RUN_DURATION_SECONDS)
    assert delivered.delivered_at is not None
    assert delivered.delivered_at > started_at
    assert abs((delivered.delivered_at - finished_at).total_seconds()) < 0.001


async def test_cancelled_launcher_reaps_its_child(tmp_path: Path) -> None:
    """FIR111-06: cancelling a running fresh run terminates and reaps the child."""
    launcher = SubprocessFreshRunLauncher()
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    script = (
        "import os, time\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    run_task = asyncio.create_task(launcher.run(argv=[sys.executable, "-c", script], cwd=str(tmp_path)))
    for _ in range(200):
        if marker_file.exists():
            break
        await asyncio.sleep(0.05)
    assert marker_file.exists(), "the child never started"
    child_pid = int(pid_file.read_text())

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    for _ in range(200):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the cancelled child was not reaped")


async def test_cancelled_launcher_reaps_a_terminate_resistant_child(tmp_path: Path) -> None:
    """FRR111-02 reconciliation: a child that ignores SIGTERM is killed after
    the grace period and reaped, never orphaned."""
    launcher = SubprocessFreshRunLauncher()
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    run_task = asyncio.create_task(launcher.run(argv=[sys.executable, "-c", script], cwd=str(tmp_path)))
    for _ in range(200):
        if marker_file.exists():
            break
        await asyncio.sleep(0.05)
    assert marker_file.exists(), "the child never started"
    child_pid = int(pid_file.read_text())

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    for _ in range(200):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the terminate-resistant child was not reaped")


async def test_second_cancellation_during_the_reap_still_reaps_the_child(tmp_path: Path) -> None:
    """FRR111-02 reconciliation: a second cancellation while the reap is in
    progress must not skip the kill; the child is still reaped."""
    launcher = SubprocessFreshRunLauncher()
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    run_task = asyncio.create_task(launcher.run(argv=[sys.executable, "-c", script], cwd=str(tmp_path)))
    for _ in range(200):
        if marker_file.exists():
            break
        await asyncio.sleep(0.05)
    assert marker_file.exists(), "the child never started"
    child_pid = int(pid_file.read_text())

    run_task.cancel()
    await asyncio.sleep(0.1)  # the reap is now inside the grace wait
    run_task.cancel()  # second cancellation during the reap
    with pytest.raises(asyncio.CancelledError):
        await run_task

    for _ in range(200):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the second cancellation abandoned the child")


def _assert_child_already_exited(*, pid: int) -> None:
    """Assert the child is reaped now — not merely signalled — with no polling.

    Args:
        pid (int): The child process id.
    """
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_repeated_cancellation_keeps_the_termination_grace(tmp_path: Path) -> None:
    """CSD lifecycle (FRR111 reconciliation): further cancellations while the
    reap is in progress neither cut the cooperative child's termination grace
    nor return early; the run ends only after the child exited and was
    reaped, leaves no task behind, and still reports the cancellation."""
    launcher = SubprocessFreshRunLauncher()
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    graceful_file = tmp_path / "graceful.marker"
    script = (
        "import os, signal, sys, time\n"
        "def finish_cleanup(signum, frame):\n"
        "    time.sleep(0.5)\n"
        f"    open({str(graceful_file)!r}, 'w').write('done')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, finish_cleanup)\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        "time.sleep(60)\n"
    )
    tasks_before: set[asyncio.Task[object]] = asyncio.all_tasks()
    run_task = asyncio.create_task(launcher.run(argv=[sys.executable, "-c", script], cwd=str(tmp_path)))
    for _ in range(200):
        if marker_file.exists():
            break
        await asyncio.sleep(0.05)
    assert marker_file.exists(), "the child never started"
    child_pid = int(pid_file.read_text())

    cancelled_at: float = time.monotonic()
    run_task.cancel()
    for _ in range(3):
        await asyncio.sleep(0.1)
        run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task
    elapsed: float = time.monotonic() - cancelled_at

    assert graceful_file.exists(), "a repeated cancellation cut the child's termination grace"
    _assert_child_already_exited(pid=child_pid)
    assert asyncio.all_tasks() - tasks_before == set(), "the reap left a task behind"
    assert elapsed < 5.0, "the cooperative child's reap was not bounded by its own exit"


async def test_cancelling_every_task_during_the_reap_still_kills_the_child(tmp_path: Path) -> None:
    """CSD lifecycle: a loop-wide cancel during the reap (what ``asyncio.run``
    does at shutdown, reaching the reap task too) still kills a
    terminate-resistant child instead of abandoning it mid-grace."""
    launcher = SubprocessFreshRunLauncher()
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    script = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        "time.sleep(60)\n"
    )
    run_task = asyncio.create_task(launcher.run(argv=[sys.executable, "-c", script], cwd=str(tmp_path)))
    for _ in range(200):
        if marker_file.exists():
            break
        await asyncio.sleep(0.05)
    assert marker_file.exists(), "the child never started"
    child_pid = int(pid_file.read_text())

    run_task.cancel()
    await asyncio.sleep(0.1)  # the reap is now inside the grace wait
    for task in asyncio.all_tasks() - {asyncio.current_task()}:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    for _ in range(40):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("a loop-wide cancel during the reap left the child running")


async def test_launcher_returns_the_child_exit_code(tmp_path: Path) -> None:
    """Return semantics: an uncancelled run returns the real child's exit code."""
    launcher = SubprocessFreshRunLauncher()

    exit_code = await launcher.run(argv=[sys.executable, "-c", "raise SystemExit(7)"], cwd=str(tmp_path))

    assert exit_code == 7


async def test_worker_stop_reaps_an_active_fresh_run_child(tmp_path: Path) -> None:
    """FRR111-02 reconciliation: stopping the worker while a fresh run is in
    flight cancels the delivery and reaps the child (111.a.3 §5.6)."""
    from src.channels.gateway import ChannelGateway
    from src.channels.repository import ChannelRepository
    from src.schedules.dao import NewScheduleDAO
    from src.schedules.database import ScheduleDatabase
    from src.schedules.fresh_run import FreshRunCommand, FreshRunInvoker, SubprocessFreshRunLauncher
    from src.schedules.invocation_repository import ScheduleInvocationRepository
    from src.schedules.repository import ScheduleRepository
    from src.schedules.service import ScheduleService
    from src.schedules.workflows import ScheduleEngine

    probe_dir = tmp_path / "probe-bin"
    probe_dir.mkdir()
    probe = probe_dir / "slo"
    pid_file = tmp_path / "child.pid"
    marker_file = tmp_path / "started.marker"
    # A supported console-script shape (absolute interpreter shebang): an
    # ``env`` shebang is refused before start by the isolation policy.
    probe.write_text(
        f"#!{sys.executable}\n"
        "import os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        f"open({str(marker_file)!r}, 'w').write('started')\n"
        "time.sleep(60)\n"
    )
    probe.chmod(0o755)

    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Stop child target",
            prompt="stop child prompt",
            trigger=IntervalTriggerDAO(every_seconds=15),
            session_mode="fresh",
        ),
        now=_utc_now() - timedelta(seconds=30),
    )

    probe_command = FreshRunCommand(venv_bin_dir=probe_dir)
    deliver = DeliverScheduleInvocationAppService(
        database=schedules_db,
        schedules=service,
        invocations=ScheduleInvocationRepository(),
        sender=ScheduleChannelSender(gateway=gateway),
        fresh_runs=FreshRunInvoker(launcher=SubprocessFreshRunLauncher(), command=probe_command),
        now_provider=_utc_now,
    )

    @asynccontextmanager
    async def deliver_services() -> AsyncIterator[DeliverScheduleInvocationAppService]:
        """Yield the real deliver service on the tmp databases."""
        yield deliver

    engine = ScheduleEngine(
        db_path=tmp_path / "schedules.db",
        channel_db_path=tmp_path / "channels.db",
        deliver_services=deliver_services,
    )
    engine.open()
    try:
        await engine.tick_once()
        stop_event: asyncio.Event = asyncio.Event()
        engine_task: asyncio.Task[None] = asyncio.create_task(engine.run(stop_event=stop_event))
        for _ in range(200):
            if marker_file.exists():
                break
            await asyncio.sleep(0.05)
        assert marker_file.exists(), "the fresh-run child never started"
        child_pid = int(pid_file.read_text())

        stop_event.set()
        await asyncio.wait_for(engine_task, timeout=30)

        for _ in range(200):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("the worker stop left the fresh-run child running")
    finally:
        engine.close()
        await gateway.close()
        await service.close()
        await schedules_db.close()


def test_scheduler_child_drops_inherited_herdr_environment() -> None:
    """A10: the child environment drops HERDR_-prefixed keys in any case and
    keeps every other key; the parent environment is not changed."""
    inherited = {
        "HERDR_ENV": "1",
        "HERDR_SESSION": "s",
        "HERDR_PANE": "p",
        "HERDR_SOCKET": "sock",
        "HERDR_TEST": "t",
        "herdr_future": "f",
        "HERDR": "kept",
        "HERDRFOO": "kept",
        "OTHER_HERDR_TEST": "kept",
        "SLO_TEST_SETTING": "kept",
        "SLO_OPENAI_API_KEY": "kept",
        "PATH": "/usr/bin",
    }
    command = FreshRunCommand()
    saved_prior: dict[str, str | None] = {key: os.environ.get(key) for key in inherited}
    try:
        for key, value in inherited.items():
            os.environ[key] = value
        child_environment = command.child_environment()
        assert os.environ["HERDR_ENV"] == "1", "the parent environment is not changed"
    finally:
        for key, prior in saved_prior.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior
    assert "HERDR_ENV" not in child_environment
    assert "HERDR_SESSION" not in child_environment
    assert "HERDR_PANE" not in child_environment
    assert "HERDR_SOCKET" not in child_environment
    assert "HERDR_TEST" not in child_environment
    assert "herdr_future" not in child_environment
    assert child_environment["HERDR"] == "kept"
    assert child_environment["HERDRFOO"] == "kept"
    assert child_environment["OTHER_HERDR_TEST"] == "kept"
    assert child_environment["SLO_TEST_SETTING"] == "kept"
    assert child_environment["SLO_OPENAI_API_KEY"] == "kept"
    assert child_environment["PATH"] == "/usr/bin"


class InstalledSloLayout:
    """A disposable editable Slo install: a real venv whose site-packages
    ``.pth`` names this checkout, the shape ``pip install -e`` produces.

    The entry script reports how ``src.cli`` resolved without running the CLI,
    so no provider or session work happens.
    """

    def __init__(self, *, root: Path, system_site_packages: bool = False) -> None:
        """Create the venv, the editable path entry and the reporting entry script.

        Args:
            root (Path): Test-owned directory that holds every created file.
            system_site_packages (bool): Let the venv see the test interpreter's
                installed dependencies, so checkout modules can be imported in it.
        """
        self.bin_dir: Path = root / "venv" / "bin"
        self.report_path: Path = root / "entry-report.json"
        venv_options: list[str] = [
            "--without-pip",
            *(["--system-site-packages"] if system_site_packages else []),
        ]
        subprocess.run(
            [sys.executable, "-m", "venv", *venv_options, str(root / "venv")],
            check=True,
            capture_output=True,
        )
        self.python: Path = self.bin_dir / "python"
        purelib: str = subprocess.run(
            [str(self.python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        Path(purelib, "slo_editable.pth").write_text(f"{_CHECKOUT_ROOT}\n", encoding="utf-8")

    def write_reporting_entry(self, *, path: Path) -> None:
        """Write a script that resolves ``src.cli`` and reports, never calling main.

        Args:
            path (Path): Where the script is written (made executable).
        """
        path.write_text(
            f"#!{self.python}\n"
            "import importlib.util\n"
            "import json\n"
            "import sys\n"
            "spec = importlib.util.find_spec('src.cli')\n"
            "report = {\n"
            "    'argv0': sys.argv[0],\n"
            "    'arguments': sys.argv[1:],\n"
            "    'isolated': sys.flags.isolated,\n"
            "    'sys_path': sys.path,\n"
            "    'src_cli_origin': spec.origin if spec is not None else None,\n"
            "}\n"
            f"with open({str(self.report_path)!r}, 'w', encoding='utf-8') as handle:\n"
            "    json.dump(report, handle)\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def write_installer_launcher(self, *, entry: Path) -> Path:
        """Write the installer's canonical isolated launcher as ``bin/slo``.

        The bytes match ``install.sh:slo_render_isolated_launcher``.

        Args:
            entry (Path): The generated ``slo-entry`` script the launcher execs.

        Returns:
            Path: The launcher path.
        """
        launcher: Path = self.bin_dir / "slo"
        launcher.write_text(
            "#!/bin/sh\n"
            "# >>> slo isolated launcher (v1) >>>\n"
            "# Generated by the Slo installer; do not edit.\n"
            f"exec '{self.python}' -I '{entry}' \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        return launcher

    def read_report(self) -> dict[str, object]:
        """Return the report the entry script wrote."""
        report: dict[str, object] = json.loads(self.report_path.read_text(encoding="utf-8"))
        return report


_CHECKOUT_ROOT: Path = Path(__file__).resolve().parents[2]


def _plant_hostile_package(*, hostile_dir: Path, marker: Path) -> None:
    """Plant a foreign ``src`` package whose import leaves a marker and fails.

    Args:
        hostile_dir (Path): The hostile cwd / PYTHONPATH directory.
        marker (Path): File the planted package writes when imported.
    """
    package_dir: Path = hostile_dir / "src"
    package_dir.mkdir(parents=True)
    planted: str = (
        f"open({str(marker)!r}, 'w').write('planted')\nraise RuntimeError('planted module imported')\n"
    )
    (package_dir / "__init__.py").write_text(planted, encoding="utf-8")
    (package_dir / "cli.py").write_text(planted, encoding="utf-8")


@pytest.mark.parametrize("wrapper_kind", ["installer-launcher", "console-script"])
async def test_fresh_run_ignores_hostile_cwd_and_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wrapper_kind: str
) -> None:
    """A11 (FRR111-02): the production invoker selects and starts each
    supported installed wrapper under a hostile cwd and PYTHONPATH; the
    intended installed ``src.cli`` resolves, the planted package is never
    imported and no hostile entry reaches the child's ``sys.path``."""
    layout = InstalledSloLayout(root=tmp_path / "install")
    if wrapper_kind == "installer-launcher":
        entry: Path = layout.bin_dir / "slo-entry"
        layout.write_reporting_entry(path=entry)
        layout.write_installer_launcher(entry=entry)
    else:
        entry = layout.bin_dir / "slo"
        layout.write_reporting_entry(path=entry)
    hostile_dir = tmp_path / "hostile"
    planted_marker = tmp_path / "planted.marker"
    _plant_hostile_package(hostile_dir=hostile_dir, marker=planted_marker)
    monkeypatch.setenv("PYTHONPATH", str(hostile_dir))
    command = FreshRunCommand(venv_bin_dir=layout.bin_dir)
    invoker = FreshRunInvoker(launcher=SubprocessFreshRunLauncher(command=command), command=command)
    session_id = str(uuid4())

    result = await invoker.start(
        prompt="run the schedule", cwd=str(hostile_dir), model=None, session_id=session_id
    )

    assert result.exit_code == 0, "the installed entry must run harmlessly"
    assert result.status == "completed"
    assert not planted_marker.exists(), "the planted package was imported"
    report = layout.read_report()
    assert report["argv0"] == str(entry), "the intended installed entrypoint ran"
    assert report["isolated"] == 1
    assert report["src_cli_origin"] == str(_CHECKOUT_ROOT / "src" / "cli" / "__init__.py")
    sys_path = report["sys_path"]
    assert isinstance(sys_path, list)
    assert [entry_path for entry_path in sys_path if str(hostile_dir) in entry_path] == []
    assert report["arguments"] == [
        "run",
        "--prompt",
        "run the schedule",
        "--json",
        "--cwd",
        str(hostile_dir),
        "--session-id",
        session_id,
    ]


def _unsupported_wrapper(*, kind: str, started_marker: Path) -> str:
    """Return one unsupported ``slo`` wrapper body that marks any execution.

    Args:
        kind (str): Which unsupported shape to build.
        started_marker (Path): File the wrapper writes if it is ever executed.

    Returns:
        str: The wrapper text.
    """
    shell_mark: str = f"touch '{started_marker}'"
    python_mark: str = f"open({str(started_marker)!r}, 'w')"
    wrappers: dict[str, str] = {
        "env-shell-shim": f"#!/usr/bin/env bash\n{shell_mark}\n",
        "launcher-without-isolation": (
            "#!/bin/sh\n"
            "# >>> slo isolated launcher (v1) >>>\n"
            "# Generated by the Slo installer; do not edit.\n"
            f"{shell_mark}\n"
            f"exec '{sys.executable}' -c 'pass' \"$@\"\n"
        ),
        "env-python-script": f"#!/usr/bin/env python3\n{python_mark}\n",
        "python-shebang-with-arguments": f"#!{sys.executable} -X dev\n{python_mark}\n",
    }
    return wrappers[kind]


_UNSUPPORTED_WRAPPER_KINDS: list[str] = [
    "env-shell-shim",
    "launcher-without-isolation",
    "env-python-script",
    "python-shebang-with-arguments",
]


@pytest.mark.parametrize("wrapper_kind", _UNSUPPORTED_WRAPPER_KINDS)
async def test_unsupported_wrapper_is_refused_before_any_start(tmp_path: Path, wrapper_kind: str) -> None:
    """FRR111-02: a wrapper that does not carry the isolation contract (a
    shell shim, an unmarked or flag-less launcher) is refused before any
    process starts; it is never executed un-isolated."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started_marker = tmp_path / "started.marker"
    wrapper = bin_dir / "slo"
    wrapper.write_text(
        _unsupported_wrapper(kind=wrapper_kind, started_marker=started_marker), encoding="utf-8"
    )
    wrapper.chmod(0o755)
    command = FreshRunCommand(venv_bin_dir=bin_dir)
    invoker = FreshRunInvoker(launcher=SubprocessFreshRunLauncher(command=command), command=command)

    with pytest.raises(UnsupportedFreshRunWrapperError, match=re.escape(str(wrapper))):
        await invoker.start(prompt="p", cwd=str(tmp_path), model=None, session_id=str(uuid4()))

    assert not started_marker.exists(), "an unsupported wrapper was executed"


async def test_unsupported_wrapper_settles_the_run_as_a_launch_failure(tmp_path: Path) -> None:
    """FRR111-02 through the deliver service: the real invoker's refusal is a
    known launch failure — run_failed with a reason, no exit code, no retry."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "slo"
    wrapper.write_text(
        _unsupported_wrapper(kind="env-shell-shim", started_marker=tmp_path / "started.marker"),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    try:
        service = ScheduleService(
            database=schedules_db,
            schedules=ScheduleRepository(),
            invocations=ScheduleInvocationRepository(),
            session_history=None,
        )
        command = FreshRunCommand(venv_bin_dir=bin_dir)
        deliver = DeliverScheduleInvocationAppService(
            database=schedules_db,
            schedules=service,
            invocations=ScheduleInvocationRepository(),
            sender=ScheduleChannelSender(gateway=gateway),
            fresh_runs=FreshRunInvoker(launcher=SubprocessFreshRunLauncher(command=command), command=command),
            now_provider=_utc_now,
        )
        now = _utc_now()
        created = await service.create(new_schedule=_fresh_input(), now=now)
        invocation = await service.trigger_now(reference=str(created.id), now=now)

        settled = await deliver.invoke(invocation_id=invocation.id, now=now)
        replayed = await deliver.invoke(invocation_id=invocation.id, now=now)

        assert settled.status == "run_failed"
        assert settled.failure_reason == "fresh_run_launch_failed"
        assert settled.run_exit_code is None
        assert replayed.status == "run_failed"
        assert replayed.delivered_at == settled.delivered_at
    finally:
        await gateway.close()
        await schedules_db.close()


def test_no_second_headless_argv_builder() -> None:
    """A9: only the fresh-run launcher module builds a ``slo run`` command line.

    OPS111 adds exactly one other process owner: the shared worker runtime,
    which starts ``schedule worker`` and never a run, so it may import
    ``subprocess`` but must still carry no run argv token.
    """
    argv_tokens = ("--session-id", "--prompt")
    process_owners: frozenset[str] = frozenset({"worker_runtime.py"})
    offenders: list[str] = []
    for path in sorted(Path("src/schedules").glob("*.py")):
        if path.name == "fresh_run.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in argv_tokens:
                    offenders.append(f"{path}: {node.value!r}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else ""
                names = [alias.name for alias in node.names]
                if path.name in process_owners:
                    continue
                if "subprocess" in names or (module or "").startswith("subprocess"):
                    offenders.append(f"{path}: subprocess import")
    assert offenders == []


def test_locator_prefers_virtualenv_executable(tmp_path: Path) -> None:
    """A12 (a): the virtualenv binary wins when it exists."""
    venv_bin_dir = tmp_path / "venv-bin"
    venv_bin_dir.mkdir()
    venv_executable = venv_bin_dir / "slo"
    venv_executable.write_text("#!/bin/sh\n")
    venv_executable.chmod(0o755)
    command = FreshRunCommand(venv_bin_dir=venv_bin_dir)
    assert command.locate_executable() == venv_executable


def test_locator_falls_back_to_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A12 (b): without a venv binary, the PATH entry is used, resolved."""
    path_bin_dir = tmp_path / "path-bin"
    path_bin_dir.mkdir()
    path_executable = path_bin_dir / "slo"
    path_executable.write_text("#!/bin/sh\n")
    path_executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_bin_dir))
    command = FreshRunCommand(venv_bin_dir=tmp_path / "empty-venv-bin")
    (tmp_path / "empty-venv-bin").mkdir()
    assert command.locate_executable() == path_executable.resolve()


def test_locator_raises_when_nothing_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A12 (c): neither lookup resolves -> FileNotFoundError, no silent fallback."""
    (tmp_path / "empty-venv-bin").mkdir()
    empty_path_dir = tmp_path / "empty-path-bin"
    empty_path_dir.mkdir()
    monkeypatch.setenv("PATH", str(empty_path_dir))
    command = FreshRunCommand(venv_bin_dir=tmp_path / "empty-venv-bin")
    with pytest.raises(FileNotFoundError, match="Could not resolve"):
        command.locate_executable()


def test_default_locator_finds_the_running_virtualenv_slo_through_a_symlinked_interpreter(
    tmp_path: Path,
) -> None:
    """HIR111-02: a worker running from a virtualenv — whose ``bin/python`` is
    a symlink to the base interpreter — starts that virtualenv's own ``slo``,
    not whatever ``slo`` happens to be on PATH (here none is)."""
    layout = InstalledSloLayout(root=tmp_path / "install", system_site_packages=True)
    assert layout.python.is_symlink(), "venv interpreters are symlinks on this platform"
    venv_slo: Path = layout.bin_dir / "slo"
    layout.write_reporting_entry(path=venv_slo)
    empty_path_dir: Path = tmp_path / "empty-path"
    empty_path_dir.mkdir()

    located = subprocess.run(
        [
            str(layout.python),
            "-I",
            "-c",
            "from src.schedules.fresh_run import FreshRunCommand; print(FreshRunCommand().locate_executable())",
        ],
        env={"PATH": str(empty_path_dir)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert located.returncode == 0, located.stderr
    assert located.stdout.strip() == str(venv_slo.parent.resolve() / "slo")
