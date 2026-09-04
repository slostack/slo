"""Tests for the headless watchdog thread duties."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
from src.cli.headless_watchdog import AbortCallback, HeadlessWatchdog


def _watchdog(
    *,
    status_store: Optional[OrchestratorStatusStore] = None,
    abort_request_path: Optional[Path] = None,
    parent_pid: Optional[int] = None,
    on_abort: Optional[AbortCallback] = None,
) -> HeadlessWatchdog:
    """Build a watchdog with a deterministic phase and attempt snapshot."""
    return HeadlessWatchdog(
        session_id="session-1",
        state_supplier=lambda: ("streaming", 2),
        status_store=status_store,
        abort_request_path=abort_request_path,
        parent_pid=parent_pid,
        on_abort=on_abort,
    )


def test_watchdog_without_duties_emits_heartbeat_only() -> None:
    """A plain watchdog emits status but has no durable or control duties."""
    watchdog: HeadlessWatchdog = _watchdog()
    with patch("src.cli.headless_watchdog.emit_lifecycle_event") as emit:
        watchdog._emit_heartbeat(phase="streaming", attempt=2)
        watchdog._write_status_tick(phase="streaming")
        watchdog._poll_abort_request()
        watchdog._probe_parent()
    emit.assert_called_once()


def test_watchdog_skips_status_tick_without_store() -> None:
    """A plain run does not create orchestrator status evidence."""
    watchdog: HeadlessWatchdog = _watchdog()
    watchdog._write_status_tick(phase="streaming")


def test_poll_abort_request_fires_once(tmp_path: Path) -> None:
    """One durable abort request invokes the cooperative funnel only once."""
    abort_request: Path = tmp_path / "abort_request.json"
    abort_request.write_text("{}", encoding="utf-8")
    reasons: list[str] = []
    watchdog: HeadlessWatchdog = _watchdog(abort_request_path=abort_request, on_abort=reasons.append)
    watchdog._poll_abort_request()
    watchdog._poll_abort_request()
    assert reasons == ["operator_abort"]


def test_poll_abort_request_ignores_absent_file(tmp_path: Path) -> None:
    """No abort callback fires before the durable request file exists."""
    reasons: list[str] = []
    watchdog: HeadlessWatchdog = _watchdog(
        abort_request_path=tmp_path / "abort_request.json", on_abort=reasons.append
    )
    watchdog._poll_abort_request()
    assert reasons == []


def test_probe_parent_ignores_live_parent() -> None:
    """A live parent is not treated as an orphaning event."""
    reasons: list[str] = []
    watchdog: HeadlessWatchdog = _watchdog(parent_pid=os.getpid(), on_abort=reasons.append)
    with patch("src.cli.headless_watchdog.ProcessProbe.is_alive", return_value=True):
        watchdog._probe_parent()
    assert reasons == []


def test_probe_parent_fires_on_dead_parent() -> None:
    """A provably missing parent requests cooperative orphan shutdown."""
    reasons: list[str] = []
    watchdog: HeadlessWatchdog = _watchdog(parent_pid=42, on_abort=reasons.append)
    with patch("src.cli.headless_watchdog.ProcessProbe.is_alive", return_value=False):
        watchdog._probe_parent()
    assert reasons == ["orchestrator_died"]


def test_probe_parent_ignores_eperm() -> None:
    """Permission denial is conservative liveness evidence, not parent death."""
    reasons: list[str] = []
    watchdog: HeadlessWatchdog = _watchdog(parent_pid=42, on_abort=reasons.append)
    with patch("src.cli.headless_watchdog.ProcessProbe.is_alive", return_value=True):
        watchdog._probe_parent()
    assert reasons == []


def test_stop_joins_thread_and_is_idempotent() -> None:
    """Stopping an unstarted watchdog is prompt and safe to repeat."""
    watchdog: HeadlessWatchdog = _watchdog()
    watchdog.stop(timeout_seconds=0.001)
    watchdog.stop(timeout_seconds=0.001)
