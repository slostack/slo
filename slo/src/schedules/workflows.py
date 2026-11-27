"""Engine wiring — the only source modules that import ``honker`` (111.a.2 A9).

One ``ScheduleEngine`` owns one Honker engine per worker process. The tick
handler runs one tick pass; the deliver handler delivers one invocation while
renewing the per-schedule lock; the purge handler runs the retention purge and
the engine dead-letter sweep. The handlers are module-level functions that bind
to the engine running them through a context variable, so two engines can live
in one process without a mutable global routing table.

The engine keeps its jobs, locks, scheduler state and dead letters in its own
hidden file beside ``schedules.db`` (ENG-X1, authorized D1 amendment). The
worker process opens ``schedules.db`` through Python's ``sqlite3`` and the
engine file through honker's bundled SQLite; two SQLite library copies in one
process must never share one database file, or closing one deletes the WAL
the other still writes. Engine rows an earlier build kept inside
``schedules.db`` are left untouched: pending work is re-enqueued from the
schedule rows by every tick.

Upgrade admission is owned by ``src/schedules/engine_admission.py``: the
engine applies it before it opens its file and records an admitted start, so a
worker of an earlier layout — the shared-file one, or the hidden-engine one
that took no worker lifetime lock — is never joined or robbed of its locks.
An earlier build started after the upgrade cannot be excluded by this build,
so the upgrade procedure is: stop every earlier worker, upgrade, and never
start an earlier build on the directory again.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
import stat
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Protocol
from uuid import UUID

import honker

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import EngineReadinessPhase, ScheduleEngineReadinessDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService, FreshRunStarter
from src.schedules.engine_admission import ScheduleEngineAdmission
from src.schedules.fresh_run import FreshRunInvoker, SubprocessFreshRunLauncher
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.repository import ScheduleRepository
from src.schedules.retention import RETENTION_DAYS, ScheduleRetentionService
from src.schedules.service import ScheduleService
from src.schedules.tick_app_service import ScheduleTickAppService

__all__ = [
    "DELIVERY_QUEUE",
    "DELIVERY_TASK_NAME",
    "TICK_CADENCE_SECONDS",
    "TICK_QUEUE",
    "TICK_TASK_NAME",
    "DeliveryLease",
    "DeliveryLockOpener",
    "ScheduleEngine",
    "ScheduleEngineServices",
    "delivery_lock_name",
]


class DeliveryLease(Protocol):
    """The per-schedule delivery lock honker hands out (its ``_Lock`` shape)."""

    def __enter__(self) -> "DeliveryLease":
        """Acquire the lock or raise ``honker.LockHeld``."""
        ...

    def renew(self, ttl: Optional[int] = None) -> bool:
        """Extend the lease; False when another owner took it."""
        ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        """Release the lock; a lost lease releases nothing."""
        ...


TICK_QUEUE = "schedule-tick"
DELIVERY_QUEUE = "schedule-delivery"
PURGE_QUEUE = "schedule-purge"
TICK_TASK_NAME = "schedule-tick"
DELIVERY_TASK_NAME = "schedule-delivery"
PURGE_TASK_NAME = "schedule-purge"
TICK_CADENCE_SECONDS = 15
TICK_PROGRESS_LIMIT_SECONDS: float = 4.0 * TICK_CADENCE_SECONDS
"""A ready engine leads and has finished a tick pass within this long (monotonic clock).

Four cadences: a tick that waits out one busy database timeout or one missed
fire does not flap the health, while an engine whose ticks stopped finishing
is reported within a minute. Startup gets the same grace, counted from the
moment the loops start, so no first tick is needed to be ready.
"""
DELIVERY_LOCK_TTL_SECONDS = 60
LOCK_HELD_RETRY_DELAY_SECONDS = 5.0
_PURGE_CRONTAB = "0 3 * * *"

_RUN_TIMEOUT_SECONDS = 3600

_LOOP_RECANCEL_INTERVAL_SECONDS: float = 0.05
"""How long a stopping engine waits for its loops before cancelling the rest again.

Honker joins its drain loops one by one, so each re-delivered cancellation
reaches the one drain being joined: a short interval keeps a stop with many
stuck drains within seconds, and every cleanup that absorbs cancellation
(delivery join, fresh-run reap) is unaffected by the extra wakeups.
"""
_LOOP_ENDED_REASON: str = "the schedule worker's scheduler or delivery loop stopped; the worker is exiting"
_ENGINE_FILE_MODE: int = 0o600
_ENGINE_DIR_MODE: int = 0o700


DeliverServiceOpener = Callable[[], AbstractAsyncContextManager[DeliverScheduleInvocationAppService]]
"""Opens one deliver application service with everything the pass owns."""

DeliveryLockOpener = Callable[[str], DeliveryLease]
"""Opens the per-schedule delivery lock for one schedule id."""

_HANDLER_ENGINE: contextvars.ContextVar[Optional["ScheduleEngine"]] = contextvars.ContextVar(
    "schedule-engine-handlers", default=None
)
"""The engine whose worker loop is running the current handler.

``asyncio.create_task`` copies the ambient context, so the value set around
``ScheduleEngine.run`` reaches every handler invocation of that engine's
workers — and only those, because each engine sets it for its own run.
"""


def _task_envelope(*, task_name: str) -> dict[str, object]:
    """Build the honker decorated-task envelope the scheduler must enqueue.

    The scheduler enqueues its registered payload raw; a decorated-task queue
    accepts only jobs wrapped in the ``__honker_task__`` envelope (the same
    envelope the task wrapper writes), so every scheduler-fired job carries it.

    Args:
        task_name (str): The registered task the envelope must name.

    Returns:
        dict[str, object]: The envelope payload.
    """
    return {"__honker_task__": {"task": task_name, "args": [], "kwargs": {}}}


def delivery_lock_name(*, schedule_id: str) -> str:
    """Return the per-schedule delivery lock name."""
    return f"schedule-{schedule_id}"


def _handler_engine() -> "ScheduleEngine":
    """Return the engine whose worker loop is running the calling handler.

    Returns:
        ScheduleEngine: The engine bound by ``ScheduleEngine.run``.

    Raises:
        AssertionError: When no engine is bound (the handler ran outside a
            worker loop).
    """
    engine = _HANDLER_ENGINE.get()
    assert engine is not None, "engine handlers run only inside ScheduleEngine.run()"
    return engine


async def _tick_handler() -> None:
    """Run one tick pass over due schedules."""
    await _handler_engine().tick_once()


async def _deliver_handler(*, invocation_id: str, schedule_id: str) -> None:
    """Deliver one invocation under the per-schedule lock."""
    await _handler_engine().deliver_one(invocation_id=invocation_id, schedule_id=schedule_id)


async def _purge_handler() -> None:
    """Run one retention purge pass (111.a.5 A7, T5.4)."""
    await _handler_engine().purge_once()


class ScheduleEngineServices:
    """Opens the collaborators one engine pass owns and closes them together.

    The schedules database, the channel gateway and the schedule service are
    one owned resource set: a failure while opening closes what was already
    opened, and leaving the context closes the gateway, then the database —
    the database close runs even when the gateway close fails.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        channel_db_path: Path,
        history_root: Optional[Path],
        channel_gateway: Optional[ChannelGateway] = None,
    ) -> None:
        """Store the paths; nothing is opened until the context is entered.

        Args:
            db_path (Path): The schedules database file.
            channel_db_path (Path): The channels database file.
            history_root (Optional[Path]): The session history root for
                reference resolution, or None for the configured default.
            channel_gateway (Optional[ChannelGateway]): An unopened gateway
                this resource set opens and closes; None builds the production
                gateway over ``channel_db_path``.
        """
        self._db_path: Path = db_path
        self._history_root: Optional[Path] = history_root
        self._unopened_gateway: ChannelGateway = (
            channel_gateway
            if channel_gateway is not None
            else ChannelGateway(repository=ChannelRepository(db_path=channel_db_path))
        )
        self._database: Optional[ScheduleDatabase] = None
        self._gateway: Optional[ChannelGateway] = None
        self._schedule_service: Optional[ScheduleService] = None

    @property
    def database(self) -> ScheduleDatabase:
        """Return the opened schedules database."""
        assert self._database is not None, "services used outside their context"
        return self._database

    @property
    def gateway(self) -> ChannelGateway:
        """Return the opened channel gateway."""
        assert self._gateway is not None, "services used outside their context"
        return self._gateway

    @property
    def schedule_service(self) -> ScheduleService:
        """Return the schedule service wired to the opened database."""
        assert self._schedule_service is not None, "services used outside their context"
        return self._schedule_service

    async def __aenter__(self) -> "ScheduleEngineServices":
        """Open the database, the gateway and the schedule service.

        Any opening failure closes what was already opened before it
        propagates.

        Returns:
            ScheduleEngineServices: The opened collaborator set.
        """
        self._database = ScheduleDatabase(db_path=self._db_path)
        try:
            await self._unopened_gateway.open()
            self._gateway = self._unopened_gateway
            self._schedule_service = ScheduleService(
                database=self._database,
                schedules=ScheduleRepository(),
                invocations=ScheduleInvocationRepository(),
                session_history=FilesystemSessionHistoryStore(root=self._history_root),
            )
        except BaseException:
            await self._close_opened()
            raise
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the gateway, then the database, whatever the pass did."""
        await self._close_opened()

    async def _close_opened(self) -> None:
        """Close the opened gateway, then the opened database.

        The database close sits in a ``finally``, so a gateway close error
        still closes the schedules connection before it propagates.
        """
        gateway: Optional[ChannelGateway] = self._gateway
        database: Optional[ScheduleDatabase] = self._database
        self._gateway = None
        self._schedule_service = None
        self._database = None
        try:
            if gateway is not None:
                await gateway.close()
        finally:
            if database is not None:
                await database.close()


class ScheduleEngine:
    """One Honker engine: scheduler registration, handlers, worker loop."""

    def __init__(
        self,
        *,
        db_path: Path,
        channel_db_path: Path,
        history_root: Optional[Path] = None,
        run_timeout_seconds: int = _RUN_TIMEOUT_SECONDS,
        delivery_lock_ttl_seconds: int = DELIVERY_LOCK_TTL_SECONDS,
        deliver_services: Optional[DeliverServiceOpener] = None,
        delivery_locks: Optional[DeliveryLockOpener] = None,
        fresh_runs: Optional[FreshRunStarter] = None,
        earlier_workers_stopped: bool = False,
        tick_cadence_seconds: int = TICK_CADENCE_SECONDS,
        progress_limit_seconds: float = TICK_PROGRESS_LIMIT_SECONDS,
    ) -> None:
        """Store the paths and the delivery tuning; nothing is opened yet.

        Args:
            db_path (Path): The schedules database file; the engine keeps its
                own hidden file in the same directory.
            channel_db_path (Path): The channels database file.
            history_root (Optional[Path]): Session history root for reference
                resolution; None keeps the configured default (111.a.2 §6.7).
            run_timeout_seconds (int): Run timeout for restart recovery (D24).
            delivery_lock_ttl_seconds (int): TTL of the per-schedule delivery
                lock; the engine renews it while a delivery runs (111.a.4 §5.6).
            deliver_services (Optional[DeliverServiceOpener]): Test seam that
                opens the deliver service instead of the engine's own assembly.
            delivery_locks (Optional[DeliveryLockOpener]): Test seam that opens
                the per-schedule delivery lock for one schedule id; None keeps
                the engine's own honker lock (111.a.4 §5.6).
            fresh_runs (Optional[FreshRunStarter]): Process-launch seam the
                engine's own deliver service uses for fresh runs; None keeps
                the production ``FreshRunInvoker`` over
                ``SubprocessFreshRunLauncher``.
            earlier_workers_stopped (bool): The operator's confirmation that
                every worker of an earlier layout has stopped.
            tick_cadence_seconds (int): How often the scheduler fires a tick pass.
            progress_limit_seconds (float): How long a running engine may go
                without leadership or a finished tick pass before it reports
                itself stalled (OPS111-03).
        """
        self._earlier_workers_stopped: bool = earlier_workers_stopped
        self._db_path: Path = db_path
        self._admission: ScheduleEngineAdmission = ScheduleEngineAdmission(db_path=db_path)
        self._engine_db_path: Path = self._admission.engine_db_path
        self._channel_db_path: Path = channel_db_path
        self._history_root: Optional[Path] = history_root
        self._run_timeout_seconds: int = run_timeout_seconds
        self._lock_ttl_seconds: int = delivery_lock_ttl_seconds
        self._renew_interval_seconds: float = max(delivery_lock_ttl_seconds / 3.0, 0.05)
        self._deliver_services: Optional[DeliverServiceOpener] = deliver_services
        self._delivery_locks: DeliveryLockOpener = (
            delivery_locks if delivery_locks is not None else self._default_delivery_lock_opener
        )
        self._fresh_runs: FreshRunStarter = (
            fresh_runs if fresh_runs is not None else FreshRunInvoker(launcher=SubprocessFreshRunLauncher())
        )
        self._db: Optional[honker.Database] = None
        self._scheduler: Optional[honker.Scheduler] = None
        self._delivery_task: Optional[Callable[..., object]] = None
        self._loops: tuple[asyncio.Task[None], ...] = ()
        self._last_tick_at: Optional[datetime] = None
        self._tick_cadence_seconds: int = tick_cadence_seconds
        self._progress_limit_seconds: float = progress_limit_seconds
        self._stop_event: Optional[asyncio.Event] = None
        self._progress_at: float = 0.0

    @property
    def run_timeout_seconds(self) -> int:
        """Return the run timeout the engine's restart recovery uses (D24)."""
        return self._run_timeout_seconds

    @property
    def engine_db_path(self) -> Path:
        """Return the engine's own database file, beside the schedules database."""
        return self._engine_db_path

    def open(self) -> None:
        """Open the engine, register the handlers for this engine, and register
        the tick and purge schedules.

        The task functions are module-level objects, so a second registration
        in the same process re-binds this engine's queue wrapper without
        conflicting in honker's per-process registry (the same function object
        under the same name is accepted).

        Raises:
            ScheduleWorkerStartError: When upgrade admission refuses the start
                (``ScheduleEngineAdmission.ensure_admitted``).
            RuntimeError: When the engine path or the admission record is not
                a regular file.
        """
        self._admission.ensure_admitted(earlier_workers_stopped=self._earlier_workers_stopped)
        self._admission.record()
        self._prepare_engine_file()
        self._db = honker.open(str(self._engine_db_path))
        self._db.queue(TICK_QUEUE).task(name=TICK_TASK_NAME)(_tick_handler)
        delivery_wrapper = self._db.queue(DELIVERY_QUEUE).task(name=DELIVERY_TASK_NAME)(_deliver_handler)
        self._db.queue(PURGE_QUEUE).task(name=PURGE_TASK_NAME)(_purge_handler)
        self._delivery_task = delivery_wrapper
        self._scheduler = honker.Scheduler(self._db)
        self._scheduler.add(
            name=TICK_TASK_NAME,
            queue=TICK_QUEUE,
            schedule=honker.every_s(self._tick_cadence_seconds),
            payload=_task_envelope(task_name=TICK_TASK_NAME),
        )
        self._scheduler.add(
            name=PURGE_TASK_NAME,
            queue=PURGE_QUEUE,
            schedule=honker.crontab(_PURGE_CRONTAB),
            payload=_task_envelope(task_name=PURGE_TASK_NAME),
        )

    def _prepare_engine_file(self) -> None:
        """Create the engine file privately before honker opens it.

        The directory gets the schedules database's 0700 mode and the file its
        0600 mode; SQLite creates the WAL and shared-memory files with the
        main file's mode. A symlink or other non-regular path is refused.

        Raises:
            RuntimeError: When the engine path is not a regular file.
        """
        self._engine_db_path.parent.mkdir(parents=True, exist_ok=True, mode=_ENGINE_DIR_MODE)
        if os.path.lexists(self._engine_db_path) and not stat.S_ISREG(self._engine_db_path.lstat().st_mode):
            raise RuntimeError(f"Schedule engine path is not a regular file: {self._engine_db_path}")
        descriptor: int = os.open(
            path=self._engine_db_path, flags=os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, mode=_ENGINE_FILE_MODE
        )
        os.close(descriptor)
        os.chmod(path=self._engine_db_path, mode=_ENGINE_FILE_MODE)

    async def enqueue_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Enqueue one delivery job through this engine's task wrapper.

        Args:
            invocation_id (UUID): The invocation to deliver.
            schedule_id (UUID): The schedule that owns the invocation; the
                delivery lock and the worker binding key on it.
        """
        assert self._delivery_task is not None, "enqueue_delivery runs only on an open engine"
        self._delivery_task(invocation_id=str(invocation_id), schedule_id=str(schedule_id))

    async def run(self, *, stop_event: asyncio.Event) -> None:
        """Run the leader-elected scheduler and the task workers until stopped.

        The engine binds itself for the handlers of its own worker loop only;
        the binding ends when the run ends. The two loops are one owned
        lifetime: when either ends — the caller's stop, a lost or held leader
        lock, a worker failure — the other is stopped through the same stop
        event and joined, so no loop outlives the run (OPS111-03).

        Args:
            stop_event (asyncio.Event): Set by the caller to stop the run.

        Raises:
            honker.LockHeld: When another scheduler holds the leader lock.
            honker.LeadershipLost: When the leader lock was taken over.
            RuntimeError: When a loop ended although nobody asked it to stop.
        """
        assert self._db is not None and self._scheduler is not None
        handler_binding = _HANDLER_ENGINE.set(self)
        try:
            await self._recover_stale_running()
            await self._run_loops(stop_event=stop_event)
        finally:
            _HANDLER_ENGINE.reset(handler_binding)

    async def _run_loops(self, *, stop_event: asyncio.Event) -> None:
        """Run both loops until the first ends, then stop and join the other.

        Args:
            stop_event (asyncio.Event): The run's stop event.

        Raises:
            BaseException: The first loop failure; RuntimeError when a loop
                ended on its own without a failure.
        """
        assert self._db is not None and self._scheduler is not None
        scheduler_loop: asyncio.Task[None] = asyncio.create_task(
            self._scheduler.run(stop_event=stop_event), name="schedule-scheduler-loop"
        )
        worker_loop: asyncio.Task[None] = asyncio.create_task(
            self._db.run_workers(stop_event=stop_event), name="schedule-delivery-loop"
        )
        self._stop_event = stop_event
        self._progress_at = time.monotonic()
        self._loops = (scheduler_loop, worker_loop)
        try:
            await asyncio.wait(self._loops, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            stop_event.set()
            for loop in self._loops:
                loop.cancel()
            await self._join_loops(tasks=self._loops)
            raise
        stop_requested: bool = stop_event.is_set()
        stop_event.set()
        caller_cancelled: bool = await self._join_loops(tasks=self._loops)
        self._ensure_not_cancelled(caller_cancelled=caller_cancelled)
        self._raise_loop_outcome(stop_requested=stop_requested)

    @staticmethod
    async def _join_loops(*, tasks: tuple[asyncio.Task[None], ...]) -> bool:
        """Join loops that were told to stop, re-delivering cancellation until they end.

        Python 3.11's ``asyncio.wait_for`` drops a cancellation that lands as
        its inner wait completes, and Honker's drain loops wait for jobs
        through it: such a drain keeps waiting for a next job after the stop,
        and the run would never end. Every interval without an end therefore
        cancels the remaining loops again; cleanup that absorbs repeated
        cancellation (a delivery join, a fresh-run reap) still completes. A
        cancellation of the caller is recorded and joining continues.

        Args:
            tasks (tuple[asyncio.Task[None], ...]): The loops.

        Returns:
            bool: True when the caller was cancelled while joining.
        """
        caller_cancelled: bool = False
        pending: set[asyncio.Task[None]] = {task for task in tasks if not task.done()}
        while pending:
            try:
                _finished, pending = await asyncio.wait(pending, timeout=_LOOP_RECANCEL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                caller_cancelled = True
            for task in pending:
                task.cancel()
        return caller_cancelled

    def _raise_loop_outcome(self, *, stop_requested: bool) -> None:
        """Re-raise the first loop failure, or report a loop that quit on its own.

        Args:
            stop_requested (bool): Whether the caller's stop ended the run.

        Raises:
            BaseException: The first loop failure.
            RuntimeError: When a loop ended without failure and without a stop.
        """
        for loop in self._loops:
            failure: Optional[BaseException] = None if loop.cancelled() else loop.exception()
            if failure is not None:
                raise failure
        if not stop_requested:
            raise RuntimeError("a schedule engine loop stopped unexpectedly")

    def readiness(self) -> ScheduleEngineReadinessDAO:
        """Report whether this engine can fire due work right now (OPS111-03).

        Ready only while both loops run, the scheduler holds an unexpired
        leader lock, and a tick pass finished within the progress limit
        (counted from the loops' start until the first one, so startup needs
        no tick). Long deliveries run on their own queue and never delay a
        tick. ``stalled`` means the loops still run but the engine no longer
        leads or no longer finishes ticks; ``retiring`` means it was asked to
        stop; ``failed`` means a loop ended on its own or with an error.

        Returns:
            ScheduleEngineReadinessDAO: The live readiness.
        """
        if not self._loops:
            return self._readiness(phase="starting", reason="the schedule worker is starting")
        ended: Optional[ScheduleEngineReadinessDAO] = self._ended_readiness()
        if ended is not None:
            return ended
        overdue: bool = time.monotonic() - self._progress_at > self._progress_limit_seconds
        if not self._leads():
            if not overdue:
                return self._readiness(phase="starting", reason="the schedule worker is taking leadership")
            return self._readiness(
                phase="stalled",
                reason=f"the schedule worker has not held scheduler leadership for "
                f"{self._progress_limit_seconds:g} seconds",
            )
        if overdue:
            return self._readiness(
                phase="stalled",
                reason=f"the schedule worker's engine has not finished a tick pass in "
                f"{self._progress_limit_seconds:g} seconds",
            )
        return self._readiness(phase="ready", reason=None)

    def _ended_readiness(self) -> Optional[ScheduleEngineReadinessDAO]:
        """Report a failed or retiring run; None while both loops run unasked.

        Returns:
            Optional[ScheduleEngineReadinessDAO]: ``failed`` for a loop error
                or a loop that ended unasked, ``retiring`` after a stop request.
        """
        if any(loop.done() and not loop.cancelled() and loop.exception() is not None for loop in self._loops):
            return self._readiness(phase="failed", reason=_LOOP_ENDED_REASON)
        if self._stop_event is not None and self._stop_event.is_set():
            return self._readiness(phase="retiring", reason="the schedule worker is stopping")
        if any(loop.done() for loop in self._loops):
            return self._readiness(phase="failed", reason=_LOOP_ENDED_REASON)
        return None

    def _leads(self) -> bool:
        """Tell whether the scheduler's leader lock is held and unexpired in the engine file.

        Only this worker can hold it: admission and the lifetime lock exclude
        every other worker, and a predecessor's rows were released at start.

        Returns:
            bool: True while the leader lock row is live.
        """
        assert self._db is not None, "readiness runs on an open engine"
        rows = self._db.query(
            "SELECT COUNT(*) AS n FROM _honker_locks WHERE name = ? AND expires_at > ?",
            [honker.Scheduler.LOCK_NAME, int(time.time())],
        )
        return int(rows[0]["n"]) > 0

    def _readiness(self, *, phase: EngineReadinessPhase, reason: Optional[str]) -> ScheduleEngineReadinessDAO:
        """Build one readiness answer carrying the last finished tick.

        Args:
            phase (EngineReadinessPhase): The phase.
            reason (Optional[str]): The safe explanation when not ready.

        Returns:
            ScheduleEngineReadinessDAO: The answer.
        """
        return ScheduleEngineReadinessDAO(phase=phase, reason=reason, last_tick_at=self._last_tick_at)

    def release_predecessor_locks(self) -> int:
        """Delete engine lock rows left by a dead worker of this directory.

        Only the holder of the worker lifetime lock may call this, after
        ``open`` admitted the start. Admission proved that no worker of an
        earlier layout can run here (it refuses while such a worker's locks are
        visible and needs the operator's confirmation otherwise), and the
        lifetime lock proves no other worker of this build is alive, so every
        row in the engine's own file belongs to a dead predecessor (for
        example a killed worker's unexpired leader lock, which would otherwise
        refuse the restart for its whole TTL). Earlier-layout rows in
        ``schedules.db`` are never touched.

        Returns:
            int: The number of lock rows released.
        """
        assert self._db is not None, "release_predecessor_locks runs on an open engine"
        with self._db.transaction() as transaction:
            counted = transaction.query("SELECT COUNT(*) AS n FROM _honker_locks", [])
            released: int = int(counted[0]["n"])
            if released:
                transaction.query("DELETE FROM _honker_locks", [])
        return released

    async def _recover_stale_running(self) -> None:
        """Mark rows left running after a restart run_failed (D24, 111.a.3 §5.6)."""
        async with self._open_deliver_service() as deliver:
            await deliver.recover_stale_running(now=datetime.now(tz=timezone.utc))

    def close(self) -> None:
        """Close the engine database and release this engine's registrations."""
        if self._db is not None:
            self._db.close()
            self._db = None
        self._scheduler = None
        self._delivery_task = None

    async def tick_once(self) -> None:
        """Run the tick application service once; used by the tick handler."""
        async with ScheduleEngineServices(
            db_path=self._db_path,
            channel_db_path=self._channel_db_path,
            history_root=self._history_root,
        ) as services:
            reconciler = InvocationOutcomeReconciler(
                database=services.database,
                gateway=services.gateway,
                invocations=ScheduleInvocationRepository(),
            )
            service = ScheduleTickAppService(
                database=services.database,
                schedules=ScheduleRepository(),
                schedule_service=services.schedule_service,
                invocations=ScheduleInvocationRepository(),
                queue=self,
                reconciler=reconciler,
            )
            await service.invoke(now=datetime.now(tz=timezone.utc), batch_limit=100)
        self._last_tick_at = datetime.now(tz=timezone.utc)
        self._progress_at = time.monotonic()

    async def purge_once(self) -> None:
        """Run one retention purge pass and the engine dead-letter sweep.

        The schedule rows belong to the retention service; the dead-letter
        rows belong to the engine and live in its own file (D25). The channel
        store is never opened.
        """
        now: datetime = datetime.now(tz=timezone.utc)
        schedules_db = ScheduleDatabase(db_path=self._db_path)
        try:
            retention = ScheduleRetentionService(
                database=schedules_db,
                schedules=ScheduleRepository(),
                invocations=ScheduleInvocationRepository(),
            )
            await retention.purge(now=now)
        finally:
            await schedules_db.close()
        self.purge_dead_letters(older_than=now - timedelta(days=RETENTION_DAYS))

    def purge_dead_letters(self, *, older_than: datetime) -> int:
        """Delete engine dead-letter jobs created at or before the cutoff (D25).

        Args:
            older_than (datetime): Rows created at or before this instant are
                deleted; the same inclusive rule the retention purge uses.

        Returns:
            int: The number of dead-letter rows removed.
        """
        assert self._db is not None, "purge_dead_letters runs on an open engine"
        cutoff_epoch: float = older_than.timestamp()
        with self._db.transaction() as transaction:
            counted = transaction.query(
                "SELECT COUNT(*) AS n FROM _honker_dead WHERE created_at <= ?", [cutoff_epoch]
            )
            expired_count: int = int(counted[0]["n"])
            if expired_count == 0:
                return 0
            transaction.query("DELETE FROM _honker_dead WHERE created_at <= ?", [cutoff_epoch])
        return expired_count

    async def deliver_one(self, *, invocation_id: str, schedule_id: str) -> None:
        """Deliver one invocation while this engine holds the schedule lock.

        The delivery and the lease renewal are one owned lifetime (111.a.4
        §5.6): whichever ends first, the other is stopped and joined before
        this method returns, and the lock is released in a ``finally`` even
        when joining or the delivery itself fails. The idempotent invocation
        row makes a retry after a lost lease safe.

        Args:
            invocation_id (str): The invocation to deliver.
            schedule_id (str): The schedule that owns the invocation.

        Raises:
            honker.Retryable: When another delivery holds the lock, or the
                lease was lost or could not be renewed (the renewal error is
                the cause) so the delivery was stopped.
            asyncio.CancelledError: When the worker stopped; the delivery and
                its fresh-run child were stopped and joined first.
        """
        lease: DeliveryLease = self._acquire_delivery_lease(schedule_id=schedule_id)
        try:
            await self._deliver_while_lease_renews(
                lease=lease, invocation_id=UUID(invocation_id), schedule_id=UUID(schedule_id)
            )
        finally:
            lease.__exit__(None, None, None)

    def _acquire_delivery_lease(self, *, schedule_id: str) -> DeliveryLease:
        """Acquire the per-schedule delivery lock or ask the worker to retry.

        Args:
            schedule_id (str): The schedule that owns the delivery lock.

        Returns:
            DeliveryLease: The held lock; the caller releases it.

        Raises:
            honker.Retryable: When another delivery of the schedule holds it.
        """
        assert self._db is not None, "deliver_one runs on an open engine"
        lease: DeliveryLease = self._delivery_locks(schedule_id)
        try:
            lease.__enter__()
        except honker.LockHeld:
            raise honker.Retryable(
                message=f"schedule {schedule_id} delivery lock held",
                delay_s=LOCK_HELD_RETRY_DELAY_SECONDS,
            ) from None
        return lease

    async def _deliver_while_lease_renews(
        self, *, lease: DeliveryLease, invocation_id: UUID, schedule_id: UUID
    ) -> None:
        """Run the delivery and the lease renewal together until one ends.

        A finished delivery stops the renewal and returns the delivery's own
        outcome. A renewal that ends first (lease refused or renewal error)
        stops the delivery, joins it, and raises a retry. A cancellation of
        the caller stops and joins both, then propagates.

        Args:
            lease (DeliveryLease): The held per-schedule lock.
            invocation_id (UUID): The invocation to deliver.
            schedule_id (UUID): The schedule that owns the invocation.

        Raises:
            honker.Retryable: When the lease could not be maintained.
            asyncio.CancelledError: When the caller was cancelled.
        """
        delivery: asyncio.Task[None] = asyncio.create_task(
            self._run_delivery(invocation_id=invocation_id, schedule_id=schedule_id)
        )
        renewal: asyncio.Task[None] = asyncio.create_task(self._renew_lease_until_lost(lease=lease))
        try:
            await asyncio.wait({delivery, renewal}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            await self._stop_and_join(tasks=(delivery, renewal))
            raise
        if delivery.done():
            caller_cancelled: bool = await self._stop_and_join(tasks=(renewal,))
            self._ensure_not_cancelled(caller_cancelled=caller_cancelled)
            delivery.result()
            return
        caller_cancelled = await self._stop_and_join(tasks=(delivery,))
        self._ensure_not_cancelled(caller_cancelled=caller_cancelled)
        raise self._build_lost_lease_retry(schedule_id=schedule_id, renewal=renewal, delivery=delivery)

    @staticmethod
    async def _stop_and_join(*, tasks: tuple[asyncio.Task[None], ...]) -> bool:
        """Cancel each task once and wait until every one has finished.

        A cancellation of the caller while waiting is recorded, not forwarded:
        the tasks were already told to stop, and a second cancellation must
        not cut short the cleanup they are running (for example a fresh-run
        child reap). Every task's outcome is retrieved so none is reported as
        never retrieved.

        Args:
            tasks (tuple[asyncio.Task[None], ...]): The tasks to stop.

        Returns:
            bool: True when the caller was cancelled while waiting.
        """
        for task in tasks:
            task.cancel()
        caller_cancelled: bool = False
        pending: set[asyncio.Task[None]] = {task for task in tasks if not task.done()}
        while pending:
            try:
                _finished, pending = await asyncio.wait(pending)
            except asyncio.CancelledError:
                caller_cancelled = True
        for task in tasks:
            if not task.cancelled():
                task.exception()
        return caller_cancelled

    @staticmethod
    def _ensure_not_cancelled(*, caller_cancelled: bool) -> None:
        """Re-raise a caller cancellation that arrived while joining.

        Args:
            caller_cancelled (bool): Whether the caller was cancelled while
                its tasks were being joined.

        Raises:
            asyncio.CancelledError: When it was.
        """
        if caller_cancelled:
            raise asyncio.CancelledError()

    @staticmethod
    def _build_lost_lease_retry(
        *, schedule_id: UUID, renewal: asyncio.Task[None], delivery: asyncio.Task[None]
    ) -> honker.Retryable:
        """Build the retry raised when the lease ended before the delivery.

        Args:
            schedule_id (UUID): The schedule whose lease ended.
            renewal (asyncio.Task[None]): The finished renewal task.
            delivery (asyncio.Task[None]): The stopped and joined delivery.

        Returns:
            honker.Retryable: A retry whose cause is the renewal error, or the
                delivery's own error when the renewal only reported the lease
                lost.
        """
        renewal_error: Optional[BaseException] = renewal.exception()
        if renewal_error is not None:
            retry = honker.Retryable(
                message=f"schedule {schedule_id} delivery lease renewal failed",
                delay_s=LOCK_HELD_RETRY_DELAY_SECONDS,
            )
            retry.__cause__ = renewal_error
            return retry
        retry = honker.Retryable(
            message=f"schedule {schedule_id} delivery lock lost mid-delivery",
            delay_s=LOCK_HELD_RETRY_DELAY_SECONDS,
        )
        retry.__cause__ = None if delivery.cancelled() else delivery.exception()
        return retry

    def _default_delivery_lock_opener(self, schedule_id: str) -> DeliveryLease:
        """Open the engine's own honker delivery lock for one schedule.

        Args:
            schedule_id (str): The schedule that owns the delivery lock.

        Returns:
            DeliveryLease: The honker per-schedule lock, bound to the engine's
                database and TTL.
        """
        assert self._db is not None, "delivery locks open on an open engine"
        return self._db.lock(
            delivery_lock_name(schedule_id=schedule_id),
            ttl=self._lock_ttl_seconds,
        )

    async def _renew_lease_until_lost(self, *, lease: DeliveryLease) -> None:
        """Renew the delivery lease every interval until it is refused.

        Returns when the lease was refused (another owner took it). A renewal
        error propagates (honker renew performs a real database transaction).
        The caller cancels this task when the delivery ends first.

        Args:
            lease (DeliveryLease): The held per-schedule lock.
        """
        while True:
            await asyncio.sleep(self._renew_interval_seconds)
            if not lease.renew():
                return

    async def _run_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Run the deliver application service once; the caller holds the lock."""
        async with self._open_deliver_service() as service:
            await service.invoke(invocation_id=invocation_id, now=datetime.now(tz=timezone.utc))

    @asynccontextmanager
    async def _open_deliver_service(
        self,
    ) -> AsyncIterator[DeliverScheduleInvocationAppService]:
        """Open one deliver application service with everything the pass owns.

        Yields:
            DeliverScheduleInvocationAppService: The deliver service with its
                own database, gateway and session history; all closed on exit.
        """
        if self._deliver_services is not None:
            async with self._deliver_services() as service:
                yield service
            return
        from src.schedules.channel_delivery import ScheduleChannelSender

        async with ScheduleEngineServices(
            db_path=self._db_path,
            channel_db_path=self._channel_db_path,
            history_root=self._history_root,
        ) as services:
            sender = ScheduleChannelSender(gateway=services.gateway)
            yield DeliverScheduleInvocationAppService(
                database=services.database,
                schedules=services.schedule_service,
                invocations=ScheduleInvocationRepository(),
                sender=sender,
                fresh_runs=self._fresh_runs,
                now_provider=lambda: datetime.now(tz=timezone.utc),
                run_timeout_seconds=self._run_timeout_seconds,
            )
