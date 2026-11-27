"""Schedule worker lifecycle (111.a.2 T2.9, A10; OPS111 shared-worker amendment).

``slo schedule worker`` is the one worker process of a schedules directory,
whether the runtime started it detached (``--launch-id``) or an operator runs
it in the foreground for administration or debugging. It first takes the
directory's lifetime lock, so no second worker can run beside it; then it
opens the engine (upgrade admission included), releases engine locks a dead
predecessor left behind, answers health challenges while the engine runs, and
on SIGTERM, a retire request or a lost store stops, closes and releases. A
start failure releases resources and exits 1.
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Optional, Protocol

import honker

from src.schedules.dao import ScheduleEngineReadinessDAO
from src.schedules.exceptions import ScheduleWorkerStartError
from src.schedules.worker_runtime import (
    ScheduleWorkerLifetime,
    ScheduleWorkerLocationDAO,
    ScheduleWorkerRuntime,
)
from src.schedules.workflows import ScheduleEngine

__all__ = ["ScheduleWorker", "ScheduleWorkerEngine"]

_STARTUP_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGTERM, signal.SIGINT)


class ScheduleWorkerEngine(Protocol):
    """Consumer-side seam: the engine lifecycle the worker drives.

    ``ScheduleEngine`` is the production implementation; tests inject an
    engine whose start fails through the same constructor parameter.
    """

    @property
    def run_timeout_seconds(self) -> int:
        """Return the run timeout the engine's restart recovery uses (D24)."""
        ...

    def open(self) -> None:
        """Open the engine and register its handlers and schedules."""
        ...

    def release_predecessor_locks(self) -> int:
        """Release engine locks a dead predecessor left; lifetime-lock holders only."""
        ...

    def readiness(self) -> ScheduleEngineReadinessDAO:
        """Report whether the engine can fire due work right now."""
        ...

    async def run(self, *, stop_event: asyncio.Event) -> None:
        """Run the scheduler and task workers until ``stop_event`` is set."""
        ...

    def close(self) -> None:
        """Close the engine; safe after a failed open."""
        ...


class ScheduleWorker:
    """Claim the directory, open the engine, serve health until stopped, close, release."""

    def __init__(
        self,
        *,
        db_path: Path,
        channel_db_path: Path,
        engine: Optional[ScheduleWorkerEngine] = None,
        run_timeout_seconds: int = 3600,
        earlier_workers_stopped: bool = False,
        location: Optional[ScheduleWorkerLocationDAO] = None,
        launch_id: Optional[str] = None,
    ) -> None:
        """Bind the database paths; the engine is injectable for tests.

        Args:
            db_path (Path): The schedules database file.
            channel_db_path (Path): The channels database file.
            engine (Optional[ScheduleWorkerEngine]): An engine built by the
                caller; the worker builds its own ``ScheduleEngine`` when None.
            run_timeout_seconds (int): Run timeout for restart recovery (D24);
                forwarded to the engine's deliver service.
            earlier_workers_stopped (bool): The operator's upgrade confirmation
                that every worker of the earlier shared-file layout stopped;
                forwarded to the engine's upgrade admission.
            location (Optional[ScheduleWorkerLocationDAO]): The stores this
                worker reports in its health answers; derived from the paths
                and the default history root when None.
            launch_id (Optional[str]): The generation id the runtime issued to
                a detached worker; None for a manual foreground worker.
        """
        self._engine: ScheduleWorkerEngine = engine or ScheduleEngine(
            db_path=db_path,
            channel_db_path=channel_db_path,
            run_timeout_seconds=run_timeout_seconds,
            earlier_workers_stopped=earlier_workers_stopped,
        )
        self._db_path: Path = db_path
        self._channel_db_path: Path = channel_db_path
        self._location: Optional[ScheduleWorkerLocationDAO] = location
        self._launch_id: Optional[str] = launch_id

    @property
    def engine(self) -> ScheduleWorkerEngine:
        """Return the engine the worker owns."""
        return self._engine

    @property
    def run_timeout_seconds(self) -> int:
        """Return the run timeout the engine's recovery uses (D24)."""
        return self._engine.run_timeout_seconds

    def run_foreground(self) -> None:
        """Claim the directory, open the engine, run until stopped, close, release.

        Stop signals that arrive during start stay pending until the handlers
        are installed, so the worker never dies on the default disposition
        mid-startup.

        Raises:
            ScheduleWorkerStartError: Another worker already runs on this
                directory, upgrade admission refused, or the engine could not
                start (for example the leader lock is held elsewhere).
        """
        original_mask: list[signal.Signals] = [
            signal.Signals(signal_value)
            for signal_value in signal.pthread_sigmask(signal.SIG_BLOCK, list(_STARTUP_SIGNALS))
        ]
        try:
            lifetime: ScheduleWorkerLifetime = self._runtime().claim_lifetime(launch_id=self._launch_id)
            try:
                self._engine.open()
                self._engine.release_predecessor_locks()
                asyncio.run(self._run_until_stopped(original_mask=original_mask, lifetime=lifetime))
            except honker.LockHeld as error:
                raise ScheduleWorkerStartError(
                    reason=f"another schedule worker holds the leader lock ({error})"
                ) from error
            except honker.LeadershipLost as error:
                raise ScheduleWorkerStartError(
                    reason=f"the schedule worker lost the leader lock ({error})"
                ) from error
            finally:
                self._engine.close()
                lifetime.release()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)

    def _runtime(self) -> ScheduleWorkerRuntime:
        """Build the runtime that owns this directory's lifetime lock.

        Returns:
            ScheduleWorkerRuntime: The runtime for this worker's location.
        """
        location: ScheduleWorkerLocationDAO = self._location or self._derived_location()
        return ScheduleWorkerRuntime(location=location)

    def _derived_location(self) -> ScheduleWorkerLocationDAO:
        """Derive the location from the bound paths and the default history root."""
        from src.agents.slo_agent.history.filesystem_store import default_history_root

        return ScheduleWorkerLocationDAO.from_paths(
            db_path=self._db_path, channel_db_path=self._channel_db_path, history_root=default_history_root()
        )

    async def _run_until_stopped(
        self, *, original_mask: list[signal.Signals], lifetime: ScheduleWorkerLifetime
    ) -> None:
        """Run the engine under health service until SIGTERM, SIGINT or retire.

        The startup signal block is lifted only after the handlers are
        installed, so a pending stop signal is delivered to the running loop.

        Args:
            original_mask (list[signal.Signals]): The mask to restore.
            lifetime (ScheduleWorkerLifetime): The held directory ownership.
        """
        stop_event: asyncio.Event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in _STARTUP_SIGNALS:
            loop.add_signal_handler(sig, stop_event.set)
        signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)
        try:
            async with lifetime.serve(readiness=self._engine.readiness, stop_event=stop_event):
                await self._engine.run(stop_event=stop_event)
        finally:
            for sig in _STARTUP_SIGNALS:
                try:
                    loop.remove_signal_handler(sig)
                except (NotImplementedError, ValueError):  # pragma: no cover
                    pass
