"""Tests for orchestrator self-report status persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore


def _make_store(tmp_path: Path) -> OrchestratorStatusStore:
    """Build a status store rooted in pytest's temporary history directory."""
    return OrchestratorStatusStore(
        history_root=tmp_path / "history",
        orchestrator_session_id="orchestrator-1",
        workflow_id="workflow-1",
    )


def _status_path(tmp_path: Path) -> Path:
    """Return the canonical test status-file path."""
    return tmp_path / "history" / "orchestrator-1" / "orchestrator.json"


def test_write_running_then_load_status(tmp_path: Path) -> None:
    """A heartbeat write round-trips the running orchestrator identity and phase."""
    store: OrchestratorStatusStore = _make_store(tmp_path=tmp_path)

    store.write_running(phase="streaming")

    status = OrchestratorStatusStore.load_status(path=_status_path(tmp_path=tmp_path))
    assert status is not None
    assert status.workflow_id == "workflow-1"
    assert status.orchestrator_session_id == "orchestrator-1"
    assert status.state == "running"
    assert status.phase == "streaming"
    assert status.exit_code is None


def test_write_terminal_records_exit_code(tmp_path: Path) -> None:
    """A terminal write persists its terminal state and POSIX exit code."""
    store: OrchestratorStatusStore = _make_store(tmp_path=tmp_path)

    store.write_terminal(state="aborted", exit_code=2, phase="streaming")

    status = OrchestratorStatusStore.load_status(path=_status_path(tmp_path=tmp_path))
    assert status is not None
    assert status.state == "aborted"
    assert status.exit_code == 2


def test_load_status_returns_none_when_absent(tmp_path: Path) -> None:
    """A missing status file provides no durable evidence."""
    assert OrchestratorStatusStore.load_status(path=_status_path(tmp_path=tmp_path)) is None


def test_load_status_returns_none_when_corrupt(tmp_path: Path) -> None:
    """A corrupt status file is ignored after the reader logs its parse failure."""
    path: Path = _status_path(tmp_path=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert OrchestratorStatusStore.load_status(path=path) is None


def test_write_swallows_oserror(tmp_path: Path) -> None:
    """A durable status write failure cannot interrupt the running orchestrator."""
    store: OrchestratorStatusStore = _make_store(tmp_path=tmp_path)

    with patch(
        "src.agents.slo_agent.orchestrator.status_store.AtomicFileWriter.write_json",
        side_effect=OSError("disk full"),
    ):
        store.write_running(phase="streaming")
