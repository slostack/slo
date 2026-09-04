"""Tests for canonical orchestration durable paths."""

from __future__ import annotations

from pathlib import Path

from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout


def test_layout_session_dir() -> None:
    """Session paths live directly below the history root."""
    assert OrchestrationLayout.session_dir(history_root=Path("/history"), session_id="session") == Path(
        "/history/session"
    )


def test_layout_workflows_dir() -> None:
    """Workflow handles share the owner session workflows directory."""
    assert OrchestrationLayout.workflows_dir(history_root=Path("/history"), owner_session_id="owner") == Path(
        "/history/owner/workflows"
    )


def test_layout_workflow_handle_path() -> None:
    """Workflow handles use their workflow identifier as a JSON file name."""
    assert OrchestrationLayout.workflow_handle_path(
        history_root=Path("/history"), owner_session_id="owner", workflow_id="wf-1"
    ) == Path("/history/owner/workflows/wf-1.json")


def test_layout_orchestrator_status_path() -> None:
    """Orchestrator status belongs to its session directory."""
    assert OrchestrationLayout.orchestrator_status_path(
        history_root=Path("/history"), orchestrator_session_id="orchestrator"
    ) == Path("/history/orchestrator/orchestrator.json")


def test_layout_fleet_path() -> None:
    """Fleet snapshots belong to their orchestrator session directory."""
    assert OrchestrationLayout.fleet_path(
        history_root=Path("/history"), orchestrator_session_id="orchestrator"
    ) == Path("/history/orchestrator/fleet.json")


def test_layout_abort_request_path() -> None:
    """Abort requests belong to their orchestrator session directory."""
    assert OrchestrationLayout.abort_request_path(
        history_root=Path("/history"), orchestrator_session_id="orchestrator"
    ) == Path("/history/orchestrator/abort_request.json")


def test_layout_capture_path() -> None:
    """Capture files belong directly to their owning session directory."""
    assert OrchestrationLayout.capture_path(
        history_root=Path("/history"), session_id="session", name="stdout.jsonl"
    ) == Path("/history/session/stdout.jsonl")


def test_layout_child_paths() -> None:
    """Child capture directories and status files share the child layout."""
    assert OrchestrationLayout.children_dir(
        history_root=Path("/history"), parent_session_id="parent"
    ) == Path("/history/parent/children")
    assert OrchestrationLayout.child_capture_dir(
        history_root=Path("/history"), parent_session_id="parent", child_session_id="child"
    ) == Path("/history/parent/children/child")
    assert OrchestrationLayout.child_status_path(
        history_root=Path("/history"), parent_session_id="parent", child_session_id="child"
    ) == Path("/history/parent/children/child/status.json")
