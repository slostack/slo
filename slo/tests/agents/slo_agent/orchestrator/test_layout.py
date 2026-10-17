"""Tests for canonical orchestration durable paths."""

from __future__ import annotations

from pathlib import Path

import pytest

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


# ── Feature 94 T02: versioned execution evidence and child-control paths ─────

_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_REQUEST_ID: str = "c3b2a190-8e7d-4c6b-9a58-473625140f0e"


def test_layout_child_execution_path() -> None:
    """The versioned execution sibling sits beside the child's old-shaped files."""
    assert OrchestrationLayout.child_execution_path(
        history_root=Path("/history"), parent_session_id="parent", child_session_id="child"
    ) == Path("/history/parent/children/child/execution.v1.json")


def test_layout_execution_index_path() -> None:
    """The execution index sits beside fleet.json."""
    assert OrchestrationLayout.execution_index_path(
        history_root=Path("/history"), orchestrator_session_id="parent"
    ) == Path("/history/parent/execution-index.v1.json")


def test_layout_child_control_paths() -> None:
    """Child control uses a separate versioned directory, never abort_request.json."""
    root: Path = Path("/history")

    assert OrchestrationLayout.child_control_dir(history_root=root, orchestrator_session_id="parent") == Path(
        "/history/parent/child-control.v1"
    )
    assert OrchestrationLayout.child_control_capability_path(
        history_root=root, orchestrator_session_id="parent"
    ) == Path("/history/parent/child-control.v1/capability.json")
    assert OrchestrationLayout.child_abort_request_path(
        history_root=root, orchestrator_session_id="parent", run_id=_RUN_ID, request_id=_REQUEST_ID
    ) == Path(f"/history/parent/child-control.v1/{_RUN_ID}/requests/{_REQUEST_ID}.json")
    assert OrchestrationLayout.child_abort_receipt_path(
        history_root=root, orchestrator_session_id="parent", run_id=_RUN_ID, request_id=_REQUEST_ID
    ) == Path(f"/history/parent/child-control.v1/{_RUN_ID}/receipts/{_REQUEST_ID}.json")


@pytest.mark.parametrize("unsafe", ["", "..", "../x", "a/b", "a\\b"])
def test_layout_new_paths_reject_unsafe_session_ids(unsafe: str) -> None:
    """Traversal or separator identities never reach a filesystem join."""
    root: Path = Path("/history")
    with pytest.raises(ValueError):
        OrchestrationLayout.child_execution_path(
            history_root=root, parent_session_id="parent", child_session_id=unsafe
        )
    with pytest.raises(ValueError):
        OrchestrationLayout.child_execution_path(
            history_root=root, parent_session_id=unsafe, child_session_id="child"
        )
    with pytest.raises(ValueError):
        OrchestrationLayout.execution_index_path(history_root=root, orchestrator_session_id=unsafe)
    with pytest.raises(ValueError):
        OrchestrationLayout.child_control_dir(history_root=root, orchestrator_session_id=unsafe)


@pytest.mark.parametrize("field", ["run_id", "request_id"])
def test_layout_control_paths_reject_non_uuid_identity(field: str) -> None:
    """Run and request path components must be canonical UUIDs."""
    identity: dict[str, str] = {"run_id": _RUN_ID, "request_id": _REQUEST_ID, field: "../escape"}
    with pytest.raises(ValueError):
        OrchestrationLayout.child_abort_request_path(
            history_root=Path("/history"), orchestrator_session_id="parent", **identity
        )
    with pytest.raises(ValueError):
        OrchestrationLayout.child_abort_receipt_path(
            history_root=Path("/history"), orchestrator_session_id="parent", **identity
        )
