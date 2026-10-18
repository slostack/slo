"""Tests for visualizer fleet overlays, orchestrator node, bounded observation and progress (94 a.3)."""

from __future__ import annotations

import hashlib
import json
import asyncio
import os
import threading
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    ChildExecutionEvidenceDAO,
    ExecutionIndexDAO,
    FleetSnapshotDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.task_preview import TaskPreview
from src.tui.jsonl_tail import JsonlTail
from src.tui.workflows.dao import SessionProgressSnapshotDAO, WorkflowSessionKeyDAO, WorkflowSessionRowDAO
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    HeadlessWorkflowVisualizerConfigDAO,
    WorkflowVisualizerLoader,
    _CaptureView,
    _ObservationReader,
)


def _loader(*, root: Path) -> WorkflowVisualizerLoader:
    """Build a loader backed by a capture root for filesystem tests."""
    store: MagicMock = MagicMock()
    store.root = root
    return WorkflowVisualizerLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="parent", follow=False),
        store=store,
    )


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

    result = _loader(root=tmp_path)._overlay_fleet(
        child=child, entry=fleet.entries[0], parent_session_id="parent"
    )

    assert result.pid == 42
    assert result.heartbeat_phase == "streaming"
    assert result.last_stdout_at == 10.0
    assert result.liveness_state in {"healthy", "degraded", "silent"}


def test_overlay_noops_without_fleet(tmp_path: Path) -> None:
    """Leaves pre-fleet capture summaries unchanged."""
    child = ChildSessionSummaryDAO(session_id="child", status="completed")

    result = _loader(root=tmp_path)._overlay_fleet(child=child, entry=None, parent_session_id="parent")

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
        child=ChildSessionSummaryDAO(session_id="child"), entry=fleet.entries[0], parent_session_id="parent"
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
        entry=fleet.entries[0],
        parent_session_id="parent",
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


# ---------------------------------------------------------------------------
# Feature 94 a.3: bounded observation group, incarnation identity, enrichment
# ---------------------------------------------------------------------------

_PARENT: str = "parent-1"
_RUN: str = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
_DISPATCH: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
_EXEC_A: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"
_EXEC_B: str = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
_MIB: int = 1024 * 1024


class _Layout:
    """Real temp-owned history layout for one parent orchestrator."""

    def __init__(self, *, root: Path) -> None:
        """Create the history root and parent session directory."""
        self.root: Path = root
        (root / _PARENT).mkdir(parents=True, exist_ok=True)

    def child_dir(self, *, child: str) -> Path:
        """Return (and create) one child's capture directory."""
        path: Path = OrchestrationLayout.child_capture_dir(
            history_root=self.root, parent_session_id=_PARENT, child_session_id=child
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def fleet(self, *, entries: list[SubAgentStatusDAO], run_id: Optional[str] = _RUN) -> None:
        """Persist fleet.json and, for a run-bound writer, execution-index.v1.json."""
        FleetStore(history_root=self.root, orchestrator_session_id=_PARENT, run_id=run_id).persist(
            entries=entries
        )

    def context(self, *, child: str, prompt: str, execution_id: str = "") -> str:
        """Write spawn_context.json and return the SHA-256 of its exact bytes."""
        data: bytes = dump_json_bytes(
            SpawnContextDAO.build(
                task_id="task",
                prompt=prompt,
                system_prompt="SYSTEM-PRIVATE",
                inactivity_timeout_seconds=1.0,
                model=None,
                reasoning_level=None,
                cwd=None,
                execution_id=execution_id,
            )
        )
        (self.child_dir(child=child) / "spawn_context.json").write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def capture(self, *, child: str, events: list[dict[str, object]]) -> StdoutCaptureIdentityDAO:
        """Write a child stdout capture and return its file identity."""
        path: Path = self.child_dir(child=child) / "stdout.jsonl"
        path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        status = os.stat(path)
        return StdoutCaptureIdentityDAO(device=status.st_dev, inode=status.st_ino)

    def publish(self, *, evidence: ChildExecutionEvidenceDAO) -> None:
        """Publish one child's execution.v1.json sibling."""
        FleetStore(history_root=self.root, orchestrator_session_id=_PARENT, run_id=_RUN).publish_execution(
            evidence=evidence
        )

    def running_child(self, *, child: str, execution_id: str, prompt: str) -> ChildExecutionEvidenceDAO:
        """Create verified running evidence with fresh context and capture."""
        digest: str = self.context(child=child, prompt=prompt, execution_id=execution_id)
        identity = self.capture(child=child, events=[{"kind": "text_delta", "delta": f"live-{child}"}])
        evidence = ChildExecutionEvidenceDAO.pending(
            session_id=child, execution_id=execution_id, dispatch_id=_DISPATCH
        ).running(stdout_identity=identity, spawn_context_sha256=digest)
        self.publish(evidence=evidence)
        return evidence

    def history(self, *, session_id: str, events: list[SessionHistoryEventDAO]) -> Path:
        """Write a canonical events.jsonl for one session."""
        session_dir: Path = self.root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path: Path = session_dir / "events.jsonl"
        path.write_bytes(b"".join(event.model_dump_json().encode() + b"\n" for event in events))
        return path


def _status(
    *, child: str, status: str = "running", execution_id: str = "", preview: str = ""
) -> SubAgentStatusDAO:
    """Build one fleet entry."""
    return SubAgentStatusDAO(
        task_id=f"task-{child}",
        session_id=child,
        status=status,  # type: ignore[arg-type]
        execution_id=execution_id,
        prompt_preview=preview,
    )


def _event(*, session_id: str, sequence: int, kind: str, **payload: object) -> SessionHistoryEventDAO:
    """Build one canonical history event."""
    return SessionHistoryEventDAO(
        session_id=session_id,
        sequence=sequence,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO.model_validate(payload),
    )


def _observer(*, root: Path) -> WorkflowVisualizerLoader:
    """Build a loader over a real store with an exact parent id."""
    return WorkflowVisualizerLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference=_PARENT, follow=False),
        store=FilesystemSessionHistoryStore(root=root),
    )


@pytest.fixture
def layout(tmp_path: Path) -> _Layout:
    """Return a temp-owned history layout."""
    return _Layout(root=tmp_path / "history")


@pytest.fixture
def no_full_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if any observation path loads, recovers or resolves full history."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("full-history or recovery path used by observation")

    monkeypatch.setattr(FilesystemSessionHistoryStore, "load_events", _forbidden)
    monkeypatch.setattr(FilesystemSessionHistoryStore, "_load_events_sync", _forbidden)
    monkeypatch.setattr(FilesystemSessionHistoryStore, "resolve_session_reference", _forbidden)


class TestObservationGroup:
    """``load_observation_group`` bounds every read before decode."""

    async def test_list_poll_never_loads_full_parent_history(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Parent history above the byte budget is read only as a bounded suffix."""
        filler: list[SessionHistoryEventDAO] = [
            _event(session_id=_PARENT, sequence=index, kind="user_message", content="f" * 2048)
            for index in range(1, 1_200)
        ]
        spawned = _event(
            session_id=_PARENT, sequence=1_200, kind="sub_agent_spawned", metadata={"sub_agent_id": "child-a"}
        )
        events_path: Path = layout.history(session_id=_PARENT, events=[*filler, spawned])
        before: bytes = events_path.read_bytes()

        group = await _observer(root=layout.root).load_observation_group()

        assert events_path.stat().st_size > 2 * _MIB
        assert group.availability == "available"
        assert [child.session_id for child in group.children] == ["child-a"]
        assert 0 < len(group.parent_events) <= 2_000
        assert events_path.read_bytes() == before

    @pytest.mark.parametrize("name", ["fleet.json", "execution-index.v1.json"])
    async def test_observation_discovery_limits_before_decode(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None, name: str
    ) -> None:
        """Oversized membership evidence makes the group unavailable without decoding it."""
        (layout.root / _PARENT / name).write_bytes(b"{" + b" " * (2 * _MIB) + b"}")

        def _no_decode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("oversized evidence decoded")

        monkeypatch.setattr(FleetSnapshotDAO, "model_validate_json", _no_decode)
        monkeypatch.setattr(ExecutionIndexDAO, "model_validate_json", _no_decode)

        group = await _observer(root=layout.root).load_observation_group()

        assert group.availability == "unavailable"
        assert group.children == []
        assert group.notice == "Workflow group unavailable; retrying on the next refresh."

    async def test_child_directory_limit_is_unavailable_not_truncated(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """2,000 child directories are listed; 2,001 make the group unavailable."""
        for index in range(2_000):
            layout.child_dir(child=f"c{index:04d}")
        loader = _observer(root=layout.root)

        full = await loader.load_observation_group()
        layout.child_dir(child="c2000")
        over = await loader.load_observation_group()

        assert (full.availability, len(full.children)) == ("available", 2_000)
        assert (over.availability, over.children) == ("unavailable", [])
        assert over.notice == "Too many child sessions to observe."

    async def test_malformed_fleet_is_unavailable_not_empty(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An unreadable membership authority never reads as an empty fleet."""
        (layout.root / _PARENT / "fleet.json").write_text("{not json", encoding="utf-8")

        group = await _observer(root=layout.root).load_observation_group()

        assert group.availability == "unavailable"

    async def test_symlinked_children_root_is_unavailable(
        self, layout: _Layout, tmp_path: Path, no_full_history: None
    ) -> None:
        """A children directory that escapes the root through a symlink is refused."""
        outside: Path = tmp_path / "outside"
        (outside / "planted").mkdir(parents=True)
        (layout.root / _PARENT / "children").symlink_to(outside, target_is_directory=True)

        group = await _observer(root=layout.root).load_observation_group()

        assert group.availability == "unavailable"
        assert group.children == []

    async def test_fleet_order_then_sorted_legacy_extras_and_run_id(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Fleet registration order leads; directory-only extras follow sorted; run_id from index."""
        layout.child_dir(child="z-extra")
        layout.child_dir(child="a-extra")
        layout.fleet(entries=[_status(child="second", preview="p2"), _status(child="first", preview="p1")])

        group = await _observer(root=layout.root).load_observation_group()

        assert [child.session_id for child in group.children] == ["second", "first", "a-extra", "z-extra"]
        assert group.run_id == _RUN

    async def test_oversized_status_and_context_degrade_per_child(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Oversized orchestrator status or spawn context degrade that field, not the group."""
        (layout.root / _PARENT / "orchestrator.json").write_bytes(b" " * (2 * _MIB + 1))
        (layout.child_dir(child="legacy") / "spawn_context.json").write_bytes(b" " * (2 * _MIB + 1))

        group = await _observer(root=layout.root).load_observation_group()

        assert group.availability == "available"
        assert group.orchestrator is not None and group.orchestrator.state == "unknown"
        assert group.children[0].task_text == ""
        assert group.children[0].has_spawn_context is False

    async def test_verified_terminal_status_rewrite_is_not_trusted(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """status.json rewritten after verification shows the fleet exit code; matching bytes are kept."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        entry = _status(child="child-a", status="completed", execution_id=_EXEC_A).model_copy(
            update={"exit_code": 3}
        )
        layout.fleet(entries=[entry])
        _terminal(layout=layout, evidence=evidence)
        loader = _observer(root=layout.root)
        matching = (await loader.load_observation_group()).children[0]
        verify = FleetStore.verify_execution

        def _verify_then_rewrite(**kwargs: object) -> Optional[ChildExecutionEvidenceDAO]:
            verified = verify(**kwargs)  # type: ignore[arg-type]
            (layout.child_dir(child="child-a") / "status.json").write_bytes(
                SubAgentResultDAO(task_id="task", session_id="child-a", status="completed", exit_code=99)
                .model_dump_json()
                .encode()
            )
            return verified

        monkeypatch.setattr(FleetStore, "verify_execution", _verify_then_rewrite)

        rewritten = (await loader.load_observation_group()).children[0]

        assert (matching.status, matching.exit_code) == ("completed", 0)
        assert (rewritten.execution_verified, rewritten.status) == (True, "completed")
        assert rewritten.exit_code == 3


class TestChildIncarnation:
    """Modern children trust old-shaped files only through matching evidence."""

    async def test_verified_running_child_supplies_full_task_and_identity(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Matching sibling/index/digest give full task text and execution/dispatch identity."""
        prompt: str = "Implement " + "x" * 200
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt=prompt)
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A, preview="registry preview")])

        child = (await _observer(root=layout.root).load_observation_group()).children[0]

        assert (child.execution_id, child.dispatch_id) == (_EXEC_A, _DISPATCH)
        assert (child.task_text, child.task_text_complete) == (prompt, True)
        assert child.prompt_preview == TaskPreview.build(task_text=prompt)
        assert child.has_stdout_capture is True
        assert child.status == "running"

    async def test_reused_pending_child_never_uses_old_task_or_capture(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An index naming a new incarnation over an old sibling yields only the registry preview."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="OLD TASK")
        layout.fleet(
            entries=[_status(child="child-a", status="pending", execution_id=_EXEC_B, preview="new preview")]
        )

        child = (await _observer(root=layout.root).load_observation_group()).children[0]

        assert child.execution_id == _EXEC_B
        assert (child.task_text, child.task_text_complete) == ("new preview", False)
        assert child.has_stdout_capture is False
        assert child.has_spawn_context is False
        assert child.status == "pending"
        assert child.dispatch_id == ""

    async def test_context_rewritten_after_evidence_is_not_trusted(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A context whose bytes no longer match the sibling digest supplies no task text."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="REAL")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A, preview="preview")])
        layout.context(child="child-a", prompt="FORGED", execution_id=_EXEC_A)

        child = (await _observer(root=layout.root).load_observation_group()).children[0]

        assert "FORGED" not in child.task_text
        assert child.task_text_complete is False

    async def test_status_file_is_trusted_only_for_verified_terminal_incarnation(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An old incarnation's status.json never overrides a reused child's fleet status."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="OLD")
        _terminal(layout=layout, evidence=evidence, status="failed")
        loader = _observer(root=layout.root)
        layout.fleet(entries=[_status(child="child-a", status="failed", execution_id=_EXEC_A)])
        verified = (await loader.load_observation_group()).children[0]
        layout.fleet(entries=[_status(child="child-a", status="pending", execution_id=_EXEC_B)])

        reused = (await loader.load_observation_group()).children[0]

        assert (verified.status, verified.exit_code, verified.execution_verified) == ("failed", 0, True)
        assert (reused.status, reused.exit_code, reused.execution_verified) == ("pending", None, False)

    async def test_legacy_child_keeps_full_prompt_with_task_preview(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Without an execution index a legacy child keeps its full prompt and a 150-point preview."""
        prompt: str = "y" * 400
        layout.context(child="legacy", prompt=prompt)

        child = (await _observer(root=layout.root).load_observation_group()).children[0]

        assert (child.execution_id, child.task_text, child.task_text_complete) == ("", prompt, True)
        assert child.prompt_preview == "y" * 149 + "…"


def _row(
    *, child: str = "child-a", execution_id: str = _EXEC_A, status: str = "running"
) -> WorkflowSessionRowDAO:
    """Build an attached child row with a registry preview."""
    return WorkflowSessionRowDAO(
        key=WorkflowSessionKeyDAO(orchestrator_session_id=_PARENT, session_id=child),
        role="child",
        task_id="task",
        execution_id=execution_id,
        dispatch_id=_DISPATCH,
        status=status,
        task_text="registry preview",
        task_text_complete=False,
    )


class TestEnrichTaskRow:
    """``enrich_task_row`` reads only matching bounded spawn context."""

    async def test_matching_context_enriches_full_task(self, layout: _Layout, no_full_history: None) -> None:
        """A verified matching incarnation replaces the preview with the full task."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="FULL TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])

        row = await _observer(root=layout.root).enrich_task_row(row=_row())

        assert (row.task_text, row.task_text_complete) == ("FULL TASK", True)
        assert (row.key, row.status, row.execution_id) == (_row().key, "running", _EXEC_A)

    @pytest.mark.parametrize("case", ["mismatch", "missing", "pending", "parent", "legacy_row"])
    async def test_unverifiable_context_returns_original_row(
        self, layout: _Layout, no_full_history: None, case: str
    ) -> None:
        """Mismatched, missing or pending evidence, parent and legacy rows keep the original row."""
        if case != "missing":
            layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="OLD")
            layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        if case == "pending":
            layout.publish(
                evidence=ChildExecutionEvidenceDAO.pending(
                    session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
                )
            )
        rows: dict[str, WorkflowSessionRowDAO] = {
            "mismatch": _row(execution_id=_EXEC_B),
            "missing": _row(),
            "pending": _row(),
            "parent": WorkflowSessionRowDAO(
                key=WorkflowSessionKeyDAO(orchestrator_session_id=_PARENT, session_id=_PARENT),
                role="orchestrator",
                status="running",
                task_text="Orchestrator",
                task_text_complete=True,
            ),
            "legacy_row": _row(execution_id=""),
        }

        result = await _observer(root=layout.root).enrich_task_row(row=rows[case])

        assert result == rows[case]

    async def test_row_from_another_parent_is_rejected(self, layout: _Layout) -> None:
        """A row naming a different orchestrator is not this loader's member."""
        foreign = WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(orchestrator_session_id="other", session_id="child-a"),
            role="child",
            status="running",
            task_text="t",
            task_text_complete=False,
        )

        with pytest.raises(ValueError):
            await _observer(root=layout.root).enrich_task_row(row=foreign)


# ---------------------------------------------------------------------------
# Feature 94 a.3: load_session_progress
# ---------------------------------------------------------------------------

_SENTINEL: str = "PRIVATE-SENTINEL-94"


def _parent_row(*, status: str = "running") -> WorkflowSessionRowDAO:
    """Build the parent orchestrator row with a run identity."""
    return WorkflowSessionRowDAO(
        key=WorkflowSessionKeyDAO(orchestrator_session_id=_PARENT, session_id=_PARENT),
        role="orchestrator",
        status=status,
        dispatch_id=_RUN,
        task_text="Orchestrator",
        task_text_complete=True,
    )


def _terminal(*, layout: _Layout, evidence: ChildExecutionEvidenceDAO, status: str = "completed") -> None:
    """Write status.json for ``evidence`` and publish its terminal phase."""
    data: bytes = (
        SubAgentResultDAO(task_id="task", session_id=evidence.session_id, status=status, exit_code=0)  # type: ignore[arg-type]
        .model_dump_json()
        .encode()
    )
    (layout.child_dir(child=evidence.session_id) / "status.json").write_bytes(data)
    layout.publish(evidence=evidence.terminal(status=status, status_sha256=hashlib.sha256(data).hexdigest()))  # type: ignore[arg-type]


def _canonical(*, layout: _Layout, session_id: str, answer: str, terminal: bool) -> Path:
    """Write canonical history with one user turn carrying a private sentinel."""
    events: list[SessionHistoryEventDAO] = [
        _event(
            session_id=session_id, sequence=1, kind="user_message", content=answer, metadata={"x": _SENTINEL}
        ),
    ]
    if terminal:
        events.append(_event(session_id=session_id, sequence=2, kind="run_completed"))
    return layout.history(session_id=session_id, events=events)


def _text(*, snapshot: SessionProgressSnapshotDAO) -> str:
    """Return every public entry serialized, for content and privacy assertions."""
    return "".join(entry.model_dump_json() for entry in snapshot.entries)


class TestLoadSessionProgress:
    """``load_session_progress`` picks one safe source and never concatenates."""

    @pytest.mark.parametrize("sibling", ["old_running", "new_pending"])
    async def test_pending_reused_session_does_not_show_old_capture(
        self, layout: _Layout, no_full_history: None, sibling: str
    ) -> None:
        """A reused session path waiting for its new incarnation shows no old task or capture."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="OLD TASK")
        layout.fleet(entries=[_status(child="child-a", status="pending", execution_id=_EXEC_B)])
        if sibling == "new_pending":
            layout.publish(
                evidence=ChildExecutionEvidenceDAO.pending(
                    session_id="child-a", execution_id=_EXEC_B, dispatch_id=_DISPATCH
                )
            )

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_row(execution_id=_EXEC_B, status="pending")
        )

        assert (snapshot.availability, snapshot.entries) == ("empty", ())
        assert "OLD" not in _text(snapshot=snapshot) + snapshot.task_text
        assert "live-child-a" not in _text(snapshot=snapshot)
        assert (snapshot.task_text, snapshot.task_text_complete) == ("registry preview", False)
        assert snapshot.final_read_complete is False
        assert snapshot.abort_target is None
        assert snapshot.notice == "Waiting for this session's progress."

    async def test_live_child_uses_capture_not_canonical(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A running child shows its incomplete live capture, never canonical duplicates."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        _canonical(layout=layout, session_id="child-a", answer="CANONICAL", terminal=False)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row())

        assert [entry.answer for entry in snapshot.entries] == ["live-child-a"]
        assert "CANONICAL" not in _text(snapshot=snapshot)
        assert snapshot.availability == "available"
        assert snapshot.source_generation.startswith(f"capture:{_EXEC_A}:")
        assert (snapshot.task_text, snapshot.task_text_complete) == ("TASK", True)
        assert (snapshot.execution_id, snapshot.dispatch_id) == (_EXEC_A, _DISPATCH)
        assert snapshot.final_read_complete is False

    async def test_live_and_terminal_progress_sources(self, layout: _Layout, no_full_history: None) -> None:
        """Live capture while running; canonical replay after terminal; final only with terminal record."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        loader = _observer(root=layout.root)
        live = await loader.load_session_progress(row=_row())
        _terminal(layout=layout, evidence=evidence)
        _canonical(layout=layout, session_id="child-a", answer="FINAL ANSWER", terminal=True)

        terminal = await loader.load_session_progress(row=_row(status="completed"))

        assert [entry.answer for entry in live.entries] == ["live-child-a"]
        assert [entry.content for entry in terminal.entries] == ["FINAL ANSWER"]
        assert "live-child-a" not in _text(snapshot=terminal)
        assert _SENTINEL not in _text(snapshot=terminal) and "SYSTEM-PRIVATE" not in _text(snapshot=terminal)
        assert terminal.source_generation.startswith(f"canonical:{_EXEC_A}:")
        assert terminal.source_generation != live.source_generation
        assert (terminal.status, terminal.final_read_complete) == ("completed", True)
        assert terminal.notice == "Showing session history; it may include earlier runs."

    async def test_terminal_without_terminal_record_is_not_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Canonical history that has not flushed its terminal record keeps polling."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", status="completed", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=evidence)
        _canonical(layout=layout, session_id="child-a", answer="PARTIAL", terminal=False)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="completed"))

        assert [entry.content for entry in snapshot.entries] == ["PARTIAL"]
        assert snapshot.final_read_complete is False

    async def test_terminal_without_history_uses_complete_capture(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """No canonical history: a matching capture with a run terminal event is a final read."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", status="completed", execution_id=_EXEC_A)])
        identity = layout.capture(
            child="child-a", events=[{"kind": "text_delta", "delta": "done"}, {"kind": "run_completed"}]
        )
        evidence = evidence.model_copy(update={"stdout_identity": identity})
        _terminal(layout=layout, evidence=evidence)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="completed"))

        assert [entry.answer for entry in snapshot.entries] == ["done"]
        assert snapshot.final_read_complete is True

    async def test_terminal_without_history_or_complete_capture_keeps_polling(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An incomplete terminal capture is shown but not final."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", status="completed", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=evidence)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="completed"))

        assert [entry.answer for entry in snapshot.entries] == ["live-child-a"]
        assert snapshot.final_read_complete is False

    async def test_confirmed_pending_abort_is_an_empty_final_read(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A child aborted before spawn has no capture or history; its empty result is final."""
        pending = ChildExecutionEvidenceDAO.pending(
            session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
        )
        layout.fleet(entries=[_status(child="child-a", status="aborted", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=pending, status="aborted")

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="aborted"))

        assert (snapshot.availability, snapshot.entries, snapshot.final_read_complete) == ("empty", (), True)

    async def test_live_without_capture_falls_back_with_notice(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Running without a trusted capture shows canonical history labelled live-capture-unavailable."""
        digest = layout.context(child="child-a", prompt="TASK", execution_id=_EXEC_A)
        layout.publish(
            evidence=ChildExecutionEvidenceDAO.pending(
                session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
            ).running(stdout_identity=None, spawn_context_sha256=digest)
        )
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        _canonical(layout=layout, session_id="child-a", answer="HISTORY", terminal=False)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row())

        assert [entry.content for entry in snapshot.entries] == ["HISTORY"]
        assert snapshot.notice == "Live capture unavailable; showing session history."
        assert snapshot.final_read_complete is False

    async def test_no_capture_and_no_history_is_unavailable(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A legacy running child with no capture and no history is unavailable, not empty."""
        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(execution_id=""))

        assert (snapshot.availability, snapshot.entries) == ("unavailable", ())
        assert snapshot.notice == "Progress unavailable; retrying."

    async def test_parent_live_capture_then_terminal_history(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """The parent reads its stdout capture while running and its canonical events when terminal."""
        capture: Path = layout.root / _PARENT / "stdout.jsonl"
        capture.write_text(
            json.dumps({"kind": "text_delta", "delta": "parent-live"}) + "\n", encoding="utf-8"
        )
        _canonical(layout=layout, session_id=_PARENT, answer="PARENT-HISTORY", terminal=True)
        loader = _observer(root=layout.root)

        live = await loader.load_session_progress(row=_parent_row())
        terminal = await loader.load_session_progress(row=_parent_row(status="completed"))

        assert [entry.answer for entry in live.entries] == ["parent-live"]
        assert live.source_generation.startswith(f"capture:{_RUN}:")
        assert [entry.content for entry in terminal.entries] == ["PARENT-HISTORY"]
        assert (terminal.dispatch_id, terminal.final_read_complete) == (_RUN, True)

    async def test_incarnation_change_during_read_returns_stale(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """Evidence replaced while the capture is read discards the late content."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        real_observe = _CaptureView.observe

        def _observe_then_reuse(view: _CaptureView) -> object:
            observation = real_observe(view)
            layout.fleet(entries=[_status(child="child-a", status="pending", execution_id=_EXEC_B)])
            return observation

        monkeypatch.setattr(_CaptureView, "observe", _observe_then_reuse)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row())

        assert (snapshot.availability, snapshot.entries) == ("stale", ())
        assert snapshot.final_read_complete is False

    async def test_history_read_failure_is_unavailable_not_raised(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """A failing bounded history read becomes a safe unavailable snapshot without error text."""

        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk exploded: secret path")

        monkeypatch.setattr(FilesystemSessionHistoryStore, "load_observation_window", _fail)

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_parent_row(status="completed")
        )

        assert snapshot.availability == "unavailable"
        assert "secret" not in (snapshot.notice or "")

    async def test_row_from_another_parent_is_rejected(self, layout: _Layout) -> None:
        """Progress is refused for rows outside this loader's parent."""
        foreign = WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(orchestrator_session_id="other", session_id="other"),
            role="orchestrator",
            status="running",
            task_text="t",
            task_text_complete=True,
        )

        with pytest.raises(ValueError):
            await _observer(root=layout.root).load_session_progress(row=foreign)

    async def test_progress_tail_rotation_and_limits(self, layout: _Layout, no_full_history: None) -> None:
        """Split, corrupt and oversized lines stay bounded; replacement resets with a notice."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        loader = _observer(root=layout.root)
        capture: Path = layout.child_dir(child="child-a") / "stdout.jsonl"
        first = await loader.load_session_progress(row=_row())
        with capture.open("ab") as handle:
            handle.write(b"not-json\n")
            handle.write(json.dumps({"kind": "text_delta", "delta": "z" * (2 * _MIB + 10)}).encode() + b"\n")
            handle.write(b'{"kind": "text_delta", "delta": " more"')
        split = await loader.load_session_progress(row=_row())
        with capture.open("ab") as handle:
            handle.write(b"}\n")
        joined = await loader.load_session_progress(row=_row())
        unchanged = await loader.load_session_progress(row=_row())

        assert [entry.answer for entry in split.entries] == ["live-child-a"]
        assert split.notice == "Earlier output omitted from this view."
        assert [entry.answer for entry in joined.entries] == ["live-child-a more"]
        assert joined.source_generation == first.source_generation
        assert joined.revision != first.revision
        assert unchanged.revision == joined.revision
        assert sum(len(entry.model_dump_json()) for entry in joined.entries) <= 2 * _MIB

    async def test_capture_replacement_resets_view(self, layout: _Layout, no_full_history: None) -> None:
        """A replaced capture of the same incarnation is a new source generation with a reset notice."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        loader = _observer(root=layout.root)
        before = await loader.load_session_progress(row=_row())
        capture: Path = layout.child_dir(child="child-a") / "stdout.jsonl"
        replacement: Path = capture.with_name("replacement.jsonl")
        replacement.write_text(json.dumps({"kind": "text_delta", "delta": "fresh"}) + "\n", encoding="utf-8")
        os.replace(replacement, capture)
        status = os.stat(capture)
        layout.publish(
            evidence=evidence.model_copy(
                update={
                    "stdout_identity": StdoutCaptureIdentityDAO(device=status.st_dev, inode=status.st_ino)
                }
            )
        )

        after = await loader.load_session_progress(row=_row())

        assert [entry.answer for entry in after.entries] == ["fresh"]
        assert after.source_generation != before.source_generation
        assert after.notice == "Progress source restarted; showing new output."

    async def test_partial_canonical_window_never_falls_back_to_full_history(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Canonical history above the budget shows only the bounded suffix with the omission notice."""
        events: list[SessionHistoryEventDAO] = [
            _event(session_id=_PARENT, sequence=index, kind="user_message", content=f"{index}:" + "h" * 4096)
            for index in range(1, 700)
        ]
        events.append(_event(session_id=_PARENT, sequence=700, kind="run_completed"))
        layout.history(session_id=_PARENT, events=events)

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_parent_row(status="completed")
        )

        assert 0 < len(snapshot.entries) < 699
        assert snapshot.entries[-1].content is not None and snapshot.entries[-1].content.startswith("699:")
        assert "Earlier output omitted from this view." in (snapshot.notice or "")
        assert snapshot.final_read_complete is True


async def test_concurrent_progress_reads_never_duplicate_capture_text(
    layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
) -> None:
    """Two overlapping reads of one row's capture absorb each new delta exactly once."""
    capture: Path = layout.child_dir(child="child-a") / "stdout.jsonl"
    capture.write_text(json.dumps({"kind": "text_delta", "delta": "hello "}) + "\n", encoding="utf-8")
    loader = _observer(root=layout.root)
    row = _row(execution_id="")
    await loader.load_session_progress(row=row)
    with capture.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "text_delta", "delta": "world"}) + "\n")
    barrier = threading.Barrier(2, timeout=1.0)
    real_read = JsonlTail._read_appended

    def _meet_then_read(tail: JsonlTail, **kwargs: object) -> object:
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return real_read(tail, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(JsonlTail, "_read_appended", _meet_then_read)
    first, second = await asyncio.gather(
        loader.load_session_progress(row=row), loader.load_session_progress(row=row)
    )
    monkeypatch.setattr(JsonlTail, "_read_appended", real_read)
    later = await loader.load_session_progress(row=row)

    assert [entry.answer for entry in first.entries] == ["hello world"]
    assert [entry.answer for entry in second.entries] == ["hello world"]
    assert [entry.answer for entry in later.entries] == ["hello world"]


async def test_capture_view_cache_is_bounded(layout: _Layout, no_full_history: None) -> None:
    """Observing more than 64 live captures retains only the 64 most recent views."""
    loader = _observer(root=layout.root)
    for index in range(65):
        child: str = f"c{index:02d}"
        layout.capture(child=child, events=[{"kind": "text_delta", "delta": child}])
        snapshot = await loader.load_session_progress(row=_row(child=child, execution_id=""))
        assert [entry.answer for entry in snapshot.entries] == [child]

    assert len(loader._capture_views) == 64
    assert all(path.parent.name != "c00" for path, _ in loader._capture_views)


def _runs(*, session_id: str, boundaries: list[str]) -> list[SessionHistoryEventDAO]:
    """Build canonical events: each boundary kind preceded by one visible user turn."""
    events: list[SessionHistoryEventDAO] = []
    for index, kind in enumerate(boundaries):
        events.append(
            _event(
                session_id=session_id, sequence=2 * index + 1, kind="user_message", content=f"turn-{index}"
            )
        )
        events.append(_event(session_id=session_id, sequence=2 * index + 2, kind=kind))
    return events


class TestFinalReadMatchesCurrentExecution:
    """``final_read_complete`` needs the current run's terminal record or a confirmed pending abort."""

    async def test_reused_child_with_earlier_run_terminal_is_not_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An earlier run's run_completed followed by a newer open run never completes the read."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_B, prompt="NEW TASK")
        layout.fleet(entries=[_status(child="child-a", status="completed", execution_id=_EXEC_B)])
        _terminal(layout=layout, evidence=evidence)
        layout.history(
            session_id="child-a",
            events=_runs(session_id="child-a", boundaries=["run_started", "run_completed", "run_started"]),
        )

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_row(execution_id=_EXEC_B, status="completed")
        )

        assert snapshot.availability == "available"
        assert snapshot.final_read_complete is False

    async def test_resumed_parent_with_earlier_run_terminal_is_not_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A resumed parent whose window still holds the previous run's terminal keeps polling."""
        layout.history(
            session_id=_PARENT,
            events=_runs(session_id=_PARENT, boundaries=["run_started", "run_aborted", "run_started"]),
        )

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_parent_row(status="completed")
        )

        assert snapshot.availability == "available"
        assert snapshot.final_read_complete is False

    async def test_latest_run_terminal_after_latest_start_is_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """The newest run's terminal record after its run_started completes the read."""
        layout.history(
            session_id=_PARENT,
            events=_runs(
                session_id=_PARENT,
                boundaries=["run_started", "run_completed", "run_started", "run_failed"],
            ),
        )

        snapshot = await _observer(root=layout.root).load_session_progress(row=_parent_row(status="failed"))

        assert snapshot.final_read_complete is True

    async def test_non_run_event_after_latest_terminal_keeps_the_read_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A workflow_update appended after the run terminal does not reopen the run."""
        events = _runs(session_id=_PARENT, boundaries=["run_started", "run_completed"])
        events.append(_event(session_id=_PARENT, sequence=99, kind="workflow_update", content="note"))
        layout.history(session_id=_PARENT, events=events)

        snapshot = await _observer(root=layout.root).load_session_progress(
            row=_parent_row(status="completed")
        )

        assert snapshot.final_read_complete is True

    async def test_failure_before_running_is_not_a_confirmed_pending_abort(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Only an abort qualifies; a pre-spawn failure without history keeps polling."""
        pending = ChildExecutionEvidenceDAO.pending(
            session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
        )
        layout.fleet(entries=[_status(child="child-a", status="failed", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=pending, status="failed")

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="failed"))

        assert snapshot.final_read_complete is False

    async def test_terminal_child_that_ran_without_capture_is_not_a_pending_abort(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A child that reached running but never opened its capture keeps polling for history."""
        digest = layout.context(child="child-a", prompt="TASK", execution_id=_EXEC_A)
        running = ChildExecutionEvidenceDAO.pending(
            session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
        ).running(stdout_identity=None, spawn_context_sha256=digest)
        layout.fleet(entries=[_status(child="child-a", status="completed", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=running)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="completed"))

        assert snapshot.entries == ()
        assert snapshot.final_read_complete is False

    async def test_terminal_abort_after_running_without_capture_is_not_a_pending_abort(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """An abort after running started (context written) is not a confirmed pending abort."""
        digest = layout.context(child="child-a", prompt="TASK", execution_id=_EXEC_A)
        running = ChildExecutionEvidenceDAO.pending(
            session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
        ).running(stdout_identity=None, spawn_context_sha256=digest)
        layout.fleet(entries=[_status(child="child-a", status="aborted", execution_id=_EXEC_A)])
        _terminal(layout=layout, evidence=running, status="aborted")

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(status="aborted"))

        assert snapshot.final_read_complete is False

    async def test_live_fallback_never_inherits_canonical_final(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """A running child without capture shows completed history labelled live, never final."""
        digest = layout.context(child="child-a", prompt="TASK", execution_id=_EXEC_A)
        layout.publish(
            evidence=ChildExecutionEvidenceDAO.pending(
                session_id="child-a", execution_id=_EXEC_A, dispatch_id=_DISPATCH
            ).running(stdout_identity=None, spawn_context_sha256=digest)
        )
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])
        layout.history(
            session_id="child-a",
            events=_runs(session_id="child-a", boundaries=["run_started", "run_completed"]),
        )

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row())

        assert snapshot.entries != ()
        assert snapshot.notice == "Live capture unavailable; showing session history."
        assert snapshot.final_read_complete is False


class TestUncoveredDecisionPoints:
    """Error and precedence branches pinned against the review's mutation survivors."""

    async def test_capture_read_error_is_unavailable_without_error_text(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """An OSError escaping the capture read becomes a fixed unavailable snapshot."""
        layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        layout.fleet(entries=[_status(child="child-a", execution_id=_EXEC_A)])

        def _fail(_tail: JsonlTail) -> list[bytes]:
            raise OSError("capture exploded: secret path")

        monkeypatch.setattr(JsonlTail, "read_new", _fail)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row())

        assert (snapshot.availability, snapshot.entries) == ("unavailable", ())
        assert snapshot.notice == "Progress unavailable; retrying."
        assert snapshot.final_read_complete is False

    async def test_symlinked_child_capture_dir_is_unavailable_and_unread(
        self, layout: _Layout, tmp_path: Path, no_full_history: None
    ) -> None:
        """A child directory reached through a symlink fails containment; nothing behind it is shown."""
        outside: Path = tmp_path / "outside-child"
        outside.mkdir()
        (outside / "stdout.jsonl").write_text(
            json.dumps({"kind": "text_delta", "delta": "PLANTED-OUTSIDE"}) + "\n", encoding="utf-8"
        )
        children: Path = layout.root / _PARENT / "children"
        children.mkdir(parents=True)
        (children / "child-a").symlink_to(outside, target_is_directory=True)

        snapshot = await _observer(root=layout.root).load_session_progress(row=_row(execution_id=""))

        assert (snapshot.availability, snapshot.entries) == ("unavailable", ())
        assert snapshot.notice == "Progress unavailable; retrying."
        assert "PLANTED" not in _text(snapshot=snapshot)

    async def test_verified_terminal_evidence_status_beats_running_fleet(
        self, layout: _Layout, no_full_history: None
    ) -> None:
        """Verified terminal evidence supplies the status even when the fleet still says running."""
        evidence = layout.running_child(child="child-a", execution_id=_EXEC_A, prompt="TASK")
        data: bytes = (
            SubAgentResultDAO(task_id="task", session_id="child-a", status="failed", answer="a" * (2 * _MIB))
            .model_dump_json()
            .encode()
        )
        (layout.child_dir(child="child-a") / "status.json").write_bytes(data)
        layout.publish(
            evidence=evidence.terminal(status="failed", status_sha256=hashlib.sha256(data).hexdigest())
        )
        layout.fleet(entries=[_status(child="child-a", status="running", execution_id=_EXEC_A)])

        child = (await _observer(root=layout.root).load_observation_group()).children[0]

        assert (child.execution_verified, child.status) == (True, "failed")

    async def test_symlinked_child_entry_is_not_listed_or_read(
        self, layout: _Layout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """A symlinked ``children/<name>`` entry is skipped and no file behind it is opened."""
        outside: Path = tmp_path / "outside-child"
        outside.mkdir()
        (outside / "spawn_context.json").write_text('{"prompt": "PLANTED"}', encoding="utf-8")
        layout.child_dir(child="real")
        (layout.root / _PARENT / "children" / "linked").symlink_to(outside, target_is_directory=True)
        opened: list[Path] = []
        real_read = _ObservationReader.read_bytes

        def _spy(reader: _ObservationReader, *, path: Path, max_bytes: int = 2 * _MIB) -> Optional[bytes]:
            opened.append(path)
            return real_read(reader, path=path, max_bytes=max_bytes)

        monkeypatch.setattr(_ObservationReader, "read_bytes", _spy)

        group = await _observer(root=layout.root).load_observation_group()

        assert [child.session_id for child in group.children] == ["real"]
        assert opened and all("linked" not in path.parts for path in opened)
        assert all("PLANTED" not in child.task_text for child in group.children)


class TestModernGroupScale:
    """Modern children verify against the group's single bounded index decode."""

    async def test_two_thousand_modern_children_verify_with_one_index_decode(
        self, layout: _Layout, monkeypatch: pytest.MonkeyPatch, no_full_history: None
    ) -> None:
        """All 2,000 modern children verify; the execution index is decoded exactly once per poll."""
        execution_ids: dict[str, str] = {
            f"c{index:04d}": f"{index:08x}-0000-4000-8000-000000000000" for index in range(2_000)
        }
        for child, execution_id in execution_ids.items():
            layout.running_child(child=child, execution_id=execution_id, prompt=f"task {child}")
        layout.fleet(entries=[_status(child=child, execution_id=eid) for child, eid in execution_ids.items()])
        decodes: list[int] = []
        real_decode = ExecutionIndexDAO.model_validate_json

        def _counting(data: object, *args: object, **kwargs: object) -> ExecutionIndexDAO:
            decodes.append(1)
            return real_decode(data, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(ExecutionIndexDAO, "model_validate_json", _counting)

        group = await _observer(root=layout.root).load_observation_group()

        assert group.availability == "available"
        assert len(group.children) == 2_000
        assert all(child.execution_verified for child in group.children)
        assert all(child.task_text_complete for child in group.children)
        assert len(decodes) == 1


@pytest.mark.parametrize(
    ("boundaries", "complete"),
    [
        (["run_started", "run_completed"], True),
        (["run_started", "run_completed", "run_started"], False),
        ([], False),
    ],
)
async def test_group_completion_follows_the_newest_run_boundary(
    layout: _Layout, no_full_history: None, boundaries: list[str], complete: bool
) -> None:
    """A resumed parent with an earlier run's terminal record is not a complete workflow."""
    layout.history(session_id=_PARENT, events=_runs(session_id=_PARENT, boundaries=boundaries))

    group = await _observer(root=layout.root).load_observation_group()

    assert group.is_complete is complete
