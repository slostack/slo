"""Run headless liveness and cooperative control duties outside the event loop.

HeadlessRunner starts one daemon watchdog for each headless run. It continues
emitting heartbeats and polling durable control channels while a provider call
blocks the runner's asyncio loop.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from config.timeout_resolver import positive_float_env
from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
from src.cli.headless_events import emit_lifecycle_event

__all__ = ["AbortCallback", "HeadlessWatchdog"]

AbortCallback = Callable[[str], None]
"""Thread-safe cooperative-abort funnel accepting one canonical reason."""


class HeadlessWatchdog:
    """Emit liveness and poll control channels from a daemon thread."""

    def __init__(
        self,
        *,
        session_id: str,
        state_supplier: Callable[[], tuple[str, int]],
        status_store: Optional[OrchestratorStatusStore] = None,
        abort_request_path: Optional[Path] = None,
        parent_pid: Optional[int] = None,
        on_abort: Optional[AbortCallback] = None,
    ) -> None:
        """Configure the watchdog duties that HeadlessRunner needs for one run.

        Args:
            session_id (str): Owning session identifier for stderr heartbeats.
            state_supplier (Callable[[], tuple[str, int]]): Thread-safe phase and attempt snapshot source.
            status_store (Optional[OrchestratorStatusStore]): Workflow evidence writer, when applicable.
            abort_request_path (Optional[Path]): Durable operator-abort request to poll.
            parent_pid (Optional[int]): Orchestrator pid to watch from a child run.
            on_abort (Optional[AbortCallback]): Thread-safe cooperative abort callback.
        """
        self._interval_seconds: float = positive_float_env(
            primary_name="SLO_HEADLESS_HEARTBEAT_SECONDS", default=15.0
        )
        self._session_id: str = session_id
        self._state: Callable[[], tuple[str, int]] = state_supplier
        self._status_store: Optional[OrchestratorStatusStore] = status_store
        self._abort_request_path: Optional[Path] = abort_request_path
        self._parent_pid: Optional[int] = parent_pid
        self._on_abort: Optional[AbortCallback] = on_abort
        self._stop_event: threading.Event = threading.Event()
        self._abort_fired: bool = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start this watchdog once; HeadlessRunner calls it before session streaming."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="headless-watchdog", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        """Stop and briefly join the daemon; HeadlessRunner calls this before terminal output.

        Args:
            timeout_seconds (float): Maximum time to wait for the thread to exit.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def _run(self) -> None:
        """Perform all watchdog duties at each interval until HeadlessRunner stops it."""
        while not self._stop_event.wait(timeout=self._interval_seconds):
            phase, attempt = self._state()
            self._emit_heartbeat(phase=phase, attempt=attempt)
            self._write_status_tick(phase=phase)
            self._poll_abort_request()
            self._probe_parent()

    def _emit_heartbeat(self, *, phase: str, attempt: int) -> None:
        """Emit one locked stderr heartbeat record for the child supervisor."""
        emit_lifecycle_event(
            kind="headless_status",
            session_id=self._session_id,
            message="headless heartbeat",
            payload={"phase": phase, "attempt": attempt},
        )

    def _write_status_tick(self, *, phase: str) -> None:
        """Refresh workflow evidence when HeadlessRunner bound a status store."""
        if self._status_store is None:
            return
        self._status_store.write_running(phase=phase)

    def _poll_abort_request(self) -> None:
        """Request operator abort once when the durable abort request exists."""
        if self._abort_request_path is None or not self._abort_request_path.exists():
            return
        self._fire_abort_once(reason="operator_abort")

    def _probe_parent(self) -> None:
        """Request orphan shutdown once only when the parent is provably absent."""
        if self._parent_pid is None:
            return
        if ProcessProbe.is_alive(pid=self._parent_pid):
            return
        self._fire_abort_once(reason="orchestrator_died")

    def _fire_abort_once(self, *, reason: str) -> None:
        """Invoke the cooperative abort funnel at most once for all stop sources.

        Args:
            reason (str): Canonical operator or orphan shutdown reason.
        """
        if self._abort_fired or self._on_abort is None:
            return
        self._abort_fired = True
        self._on_abort(reason)
