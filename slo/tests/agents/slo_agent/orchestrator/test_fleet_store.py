"""Tests for the durable orchestrator fleet projection (sub-spec 71.a.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.agents.slo_agent.orchestrator.dao import SubAgentStatusDAO
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore


def _entry() -> SubAgentStatusDAO:
    """Build one terminal fleet entry for FleetStore tests.

    Returns:
        SubAgentStatusDAO: Completed child entry with durable cleanup fields.
    """
    return SubAgentStatusDAO(
        task_id="task-1",
        session_id="child-1",
        status="completed",
        pid=1234,
        started_at=10.0,
        exit_code=0,
        terminal_reason="completed",
        terminated_by="natural",
    )


class TestFleetStore:
    """FleetStore durable snapshot behavior."""

    def test_persist_then_load_round_trips_snapshot(self, tmp_path: Path) -> None:
        """Persisted fleet entries can be loaded after the writer exits."""
        store: FleetStore = FleetStore(
            history_root=tmp_path,
            orchestrator_session_id="orchestrator-1",
            workflow_id="workflow-1",
        )

        store.persist(entries=[_entry()])

        snapshot = store.load()

        assert snapshot is not None
        assert snapshot.orchestrator_session_id == "orchestrator-1"
        assert snapshot.workflow_id == "workflow-1"
        assert snapshot.entries == [_entry()]
        assert snapshot.updated_at

    def test_load_returns_none_when_file_absent(self, tmp_path: Path) -> None:
        """Loading before a registry transition returns no fleet snapshot."""
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        assert store.load() is None

    def test_load_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        """Corrupt fleet JSON is logged and never escapes to a reader."""
        fleet_path: Path = tmp_path / "orchestrator-1" / "fleet.json"
        fleet_path.parent.mkdir()
        fleet_path.write_text("not json", encoding="utf-8")
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        with patch(target="src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning:
            assert store.load() is None

        warning.assert_called_once()

    def test_persist_swallows_oserror(self, tmp_path: Path) -> None:
        """A failed best-effort fleet write only logs a warning."""
        store: FleetStore = FleetStore(history_root=tmp_path, orchestrator_session_id="orchestrator-1")

        with (
            patch(
                target="src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_json",
                side_effect=OSError("disk full"),
            ),
            patch(target="src.agents.slo_agent.orchestrator.fleet_store.log_warning") as warning,
        ):
            store.persist(entries=[_entry()])

        warning.assert_called_once()
