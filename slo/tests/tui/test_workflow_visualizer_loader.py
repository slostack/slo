"""Tests for visualizer fleet overlays, orchestrator node, and stdout tails."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    HeadlessWorkflowVisualizerConfigDAO,
    WorkflowVisualizerLoader,
)


def _loader(*, root: Path) -> WorkflowVisualizerLoader:
    """Build a loader backed by a capture root for filesystem tests."""
    store: MagicMock = MagicMock()
    store.root = root
    return WorkflowVisualizerLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="parent", follow=False),
        store=store,
    )


def test_context_delegates_to_shared_reader(tmp_path: Path) -> None:
    """Preserve the loader API while using only the lower-layer parser."""
    from src.agents.slo_agent.orchestrator.context_reader import OrchestratorContextReader
    from src.agents.slo_agent.orchestrator.context_dao import OrchestratorContextDAO

    context = OrchestratorContextDAO.build(system_prompt="private", user_prompt="private", model=None)
    with patch.object(OrchestratorContextReader, "load", return_value=context) as load:
        assert _loader(root=tmp_path).load_orchestrator_context(parent_session_id="parent") is context
    load.assert_called_once_with(history_root=tmp_path, parent_session_id="parent")


def test_overlay_populates_fleet_fields(tmp_path: Path) -> None:
    """Merges matching durable fleet fields into the discovered child."""
    child = ChildSessionSummaryDAO(session_id="child")
    fleet = FleetSnapshotDAO(
        orchestrator_session_id="parent",
        updated_at="2026-01-01T00:00:00+00:00",
        entries=[
            SubAgentStatusDAO(
                task_id="task",
                session_id="child",
                status="running",
                pid=42,
                heartbeat_phase="streaming",
                last_stdout_at=10.0,
            )
        ],
    )

    result = _loader(root=tmp_path)._overlay_fleet(child=child, fleet=fleet)

    assert result.pid == 42
    assert result.heartbeat_phase == "streaming"
    assert result.last_stdout_at == 10.0
    assert result.liveness_state in {"healthy", "degraded", "silent"}


def test_overlay_noops_without_fleet(tmp_path: Path) -> None:
    """Leaves pre-fleet capture summaries unchanged."""
    child = ChildSessionSummaryDAO(session_id="child", status="completed")

    result = _loader(root=tmp_path)._overlay_fleet(child=child, fleet=None)

    assert result == child


def test_overlay_reads_terminal_exit_code(tmp_path: Path) -> None:
    """Uses terminal status.json exit code for a fleet-overlaid child."""
    child_dir: Path = tmp_path / "parent" / "children" / "child"
    child_dir.mkdir(parents=True)
    (child_dir / "status.json").write_text(
        '{"task_id":"task","session_id":"child","status":"failed","exit_code":7}',
        encoding="utf-8",
    )
    fleet = FleetSnapshotDAO(
        orchestrator_session_id="parent",
        updated_at="2026-01-01T00:00:00+00:00",
        entries=[SubAgentStatusDAO(task_id="task", session_id="child", status="failed")],
    )

    result = _loader(root=tmp_path)._overlay_fleet(
        child=ChildSessionSummaryDAO(session_id="child"), fleet=fleet
    )

    assert result.exit_code == 7


def test_overlay_fleet_when_status_file_exists_uses_terminal_status(tmp_path: Path) -> None:
    """Terminal status.json overrides a stale discovery status."""
    child_dir: Path = tmp_path / "parent" / "children" / "child"
    child_dir.mkdir(parents=True)
    (child_dir / "status.json").write_text(
        '{"task_id":"task","session_id":"child","status":"failed","exit_code":7}',
        encoding="utf-8",
    )
    fleet = FleetSnapshotDAO(
        orchestrator_session_id="parent",
        updated_at="2026-01-01T00:00:00+00:00",
        entries=[SubAgentStatusDAO(task_id="task", session_id="child", status="running")],
    )

    result = _loader(root=tmp_path)._overlay_fleet(
        child=ChildSessionSummaryDAO(session_id="child", status="running"),
        fleet=fleet,
    )

    assert result.status == "failed"
    assert result.exit_code == 7


def test_build_orchestrator_node_reads_status(tmp_path: Path) -> None:
    """Builds the orchestrator node from its self-reported durable status."""
    session_dir: Path = tmp_path / "parent"
    session_dir.mkdir()
    (session_dir / "orchestrator.json").write_text(
        '{"workflow_id":"wf","orchestrator_session_id":"parent","pid":11,'
        '"state":"running","phase":"streaming","updated_at":"2026-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )

    result = _loader(root=tmp_path)._build_orchestrator_node(parent_session_id="parent")

    assert result.state == "running"
    assert result.phase == "streaming"
    assert result.pid == 11


def test_build_orchestrator_node_defaults_unknown(tmp_path: Path) -> None:
    """Builds an unknown node when a pre-71 session has no status file."""
    result = _loader(root=tmp_path)._build_orchestrator_node(parent_session_id="parent")

    assert result.state == "unknown"
    assert result.phase == "awaiting_provider_stream"
