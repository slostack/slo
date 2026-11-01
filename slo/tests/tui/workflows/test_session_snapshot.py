"""Owner-scoped session snapshots and the progress gateway (feature 94 a.2/a.3, ticket T06).

Categories: public service projection and orchestration (recording
constructor-injected loaders for reuse, ordering and failure cutoffs) and adapter integration
(real temporary handle, fleet, evidence, spawn-context and history files).
Every write resolves below the test's own ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildExecutionEvidenceDAO,
    ChildAbortRequestDAO,
    ChildAbortOutcomeDAO,
    FleetSnapshotDAO,
    SubAgentStatusDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowCommandService,
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.tui.workflow_visualizer_loader import (
    HeadlessWorkflowVisualizerConfigDAO,
    ChildSessionSummaryDAO,
    OrchestratorNodeDAO,
    WorkflowDataDAO,
    WorkflowVisualizerLoader,
)
from src.tui.workflows.dao import (
    SessionProgressSnapshotDAO,
    WorkflowListVisibilityRequestDAO,
    WorkflowListVisibilityOutcomeDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.service import DetachedWorkflowAppService, WorkflowObservationLoaderFactory

_OWNER: str = "owner-1"
_ORCH_A: str = "orch-a"
_ORCH_B: str = "orch-b"
_DISPATCH_1: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
_DISPATCH_2: str = "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f"
_RUN: str = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
_EXEC_A: str = "5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9"
_EXEC_B: str = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
_EXEC_C: str = "3b4c5d6e-7f80-4a9b-8c0d-1e2f3a4b5c6d"
_LIST_UNAVAILABLE: str = "Workflow list unavailable; showing last known sessions."


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _entry(*, session_id: str, status: str = "running", execution_id: str = _EXEC_A) -> SubAgentStatusDAO:
    """Build one registry entry with a TaskPreview-shaped prompt preview.

    Args:
        session_id (str): Child session id.
        status (str, optional): Lifecycle status. Defaults to ``"running"``.
        execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.

    Returns:
        SubAgentStatusDAO: Registry entry.
    """
    return SubAgentStatusDAO(
        task_id=f"task-{session_id}",
        session_id=session_id,
        status=status,  # type: ignore[arg-type]
        execution_id=execution_id,
        prompt_preview=f"preview {session_id}",
    )


def _attached(
    *, entries: tuple[SubAgentStatusDAO, ...], dispatch_id: str = _DISPATCH_1, sequence: int = 1
) -> AttachedDispatchSnapshotDAO:
    """Build one admitted attached dispatch snapshot.

    Args:
        entries (tuple[SubAgentStatusDAO, ...]): Current-batch entries.
        dispatch_id (str, optional): Batch identity. Defaults to ``_DISPATCH_1``.
        sequence (int, optional): Admission sequence. Defaults to 1.

    Returns:
        AttachedDispatchSnapshotDAO: Supplier value.
    """
    return AttachedDispatchSnapshotDAO(dispatch_id=dispatch_id, dispatch_sequence=sequence, entries=entries)


class _Supplier:
    """Mutable attached-snapshot supplier standing in for ``session.attached_dispatch_snapshot``."""

    def __init__(self, *, snapshot: Optional[AttachedDispatchSnapshotDAO] = None) -> None:
        """Seed the supplier.

        Args:
            snapshot (Optional[AttachedDispatchSnapshotDAO]): Initial value; empty when None.
        """
        self.snapshot: AttachedDispatchSnapshotDAO = snapshot or AttachedDispatchSnapshotDAO.empty()
        self.calls: int = 0

    def __call__(self) -> AttachedDispatchSnapshotDAO:
        """Return the current value and count the read.

        Returns:
            AttachedDispatchSnapshotDAO: Current attached projection.
        """
        self.calls += 1
        return self.snapshot


def _handle(
    *,
    workflow_id: str,
    orchestrator_session_id: str,
    state: WorkflowState = "running",
    owner_session_id: str = _OWNER,
    hour: int = 12,
) -> WorkflowHandleDAO:
    """Build one deterministic owned workflow handle.

    Args:
        workflow_id (str): Workflow id.
        orchestrator_session_id (str): Detached orchestrator session.
        state (WorkflowState, optional): Handle state. Defaults to ``"running"``.
        owner_session_id (str, optional): Owning TUI session. Defaults to ``_OWNER``.
        hour (int, optional): Launch hour for ordering. Defaults to 12.

    Returns:
        WorkflowHandleDAO: Handle fixture.
    """
    return WorkflowHandleDAO(
        workflow_id=workflow_id,
        owner_session_id=owner_session_id,
        orchestrator_session_id=orchestrator_session_id,
        pid=4242,
        brief=f"brief for {workflow_id}",
        cwd="/repo",
        state=state,
        started_at=datetime(2026, 10, 1, hour, 0, tzinfo=timezone.utc),
    )


def _key(
    *, orchestrator_session_id: str, session_id: str, attached_dispatch_id: str = ""
) -> WorkflowSessionKeyDAO:
    """Build one composite key.

    Args:
        orchestrator_session_id (str): Parent orchestrator.
        session_id (str): Row session.

    Returns:
        WorkflowSessionKeyDAO: Key.
    """
    return WorkflowSessionKeyDAO(
        orchestrator_session_id=orchestrator_session_id,
        session_id=session_id,
        attached_dispatch_id=attached_dispatch_id,
    )


def _service(
    *,
    root: Optional[Path],
    supplier: Optional[_Supplier] = None,
    store: Optional[WorkflowHandleStore] = None,
    loader_factory: Optional[WorkflowObservationLoaderFactory] = None,
) -> DetachedWorkflowAppService:
    """Build the service over a real temporary root, or a no-history service.

    Args:
        root (Optional[Path]): History root; None builds the no-history variant.
        supplier (Optional[_Supplier], optional): Attached supplier. Defaults to empty.
        store (Optional[WorkflowHandleStore], optional): Handle store override.

    Returns:
        DetachedWorkflowAppService: Service owned by ``_OWNER``.
    """
    history_store: Optional[FilesystemSessionHistoryStore] = (
        None if root is None else FilesystemSessionHistoryStore(root=root)
    )
    handle_store: Optional[WorkflowHandleStore] = store or (
        None if root is None else WorkflowHandleStore(history_root=root, pid_alive=lambda pid: False)
    )
    return DetachedWorkflowAppService(
        workflow_handle_store=handle_store,
        owner_session_id=_OWNER,
        attached_snapshot=supplier or _Supplier(),
        history_store=history_store,
        loader_factory=loader_factory,
    )


class TestBatchStatus:
    """``_batch_status`` precedence for the displayed attached batch."""

    @pytest.mark.parametrize(
        ("statuses", "expected"),
        [
            (("pending", "completed"), "running"),
            (("running", "failed", "aborted"), "running"),
            (("failed", "aborted"), "failed"),
            (("failed", "completed"), "failed"),
            (("aborted", "completed"), "aborted"),
            (("completed",), "completed"),
        ],
    )
    async def test_precedence(self, statuses: tuple[str, ...], expected: str) -> None:
        """Pending/running wins; MINOR-2: failed beats aborted with no active child."""
        entries: tuple[SubAgentStatusDAO, ...] = tuple(
            _entry(session_id=f"child-{index}", status=status) for index, status in enumerate(statuses)
        )

        service = _service(root=None, supplier=_Supplier(snapshot=_attached(entries=entries)))
        assert (await service.load_session_snapshot()).rows[0].status == expected


class TestProjectAttachedGroup:
    """``_project_attached_group``: registry membership only; enrichment never adds members."""

    @pytest.mark.parametrize(
        "attached",
        [AttachedDispatchSnapshotDAO.empty(), _attached(entries=())],
        ids=["no_dispatch", "admitted_empty_dispatch"],
    )
    async def test_empty_batch_projects_nothing(self, attached: AttachedDispatchSnapshotDAO) -> None:
        """No entries (including an admitted empty dispatch) yields no attached rows."""
        service = _service(root=None, supplier=_Supplier(snapshot=attached))

        assert (await service.load_session_snapshot()).rows == ()

    async def test_no_history_uses_registry_previews(self) -> None:
        """Without history the parent and exact registry children use previews only."""
        attached = _attached(
            entries=(
                _entry(session_id="child-b", status="failed", execution_id=_EXEC_B),
                _entry(session_id="child-a", status="aborted", execution_id=_EXEC_A),
            )
        )

        service = _service(root=None, supplier=_Supplier(snapshot=attached))
        rows = (await service.load_session_snapshot()).rows

        assert rows == (
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_OWNER, session_id=_OWNER, attached_dispatch_id=_DISPATCH_1),
                role="orchestrator",
                status="failed",
                dispatch_id=_DISPATCH_1,
                task_text="Orchestrator",
                task_text_complete=True,
            ),
            WorkflowSessionRowDAO(
                key=_key(
                    orchestrator_session_id=_OWNER, session_id="child-b", attached_dispatch_id=_DISPATCH_1
                ),
                role="child",
                task_id="task-child-b",
                execution_id=_EXEC_B,
                dispatch_id=_DISPATCH_1,
                status="failed",
                task_summary="Task summary unavailable — open details",
                task_text="preview child-b",
                task_text_complete=False,
            ),
            WorkflowSessionRowDAO(
                key=_key(
                    orchestrator_session_id=_OWNER, session_id="child-a", attached_dispatch_id=_DISPATCH_1
                ),
                role="child",
                task_id="task-child-a",
                execution_id=_EXEC_A,
                dispatch_id=_DISPATCH_1,
                status="aborted",
                task_summary="Task summary unavailable — open details",
                task_text="preview child-a",
                task_text_complete=False,
            ),
        )


class _Files:
    """Real temp-owned orchestration files for one history root."""

    def __init__(self, *, root: Path) -> None:
        """Create the history root.

        Args:
            root (Path): History root below the test's ``tmp_path``.
        """
        self.root: Path = root
        root.mkdir(parents=True, exist_ok=True)

    def fleet(self, *, parent: str, entries: list[SubAgentStatusDAO], run_id: Optional[str] = _RUN) -> None:
        """Persist the parent's fleet.json and, when run-bound, its execution index.

        Args:
            parent (str): Orchestrator session id.
            entries (list[SubAgentStatusDAO]): Fleet membership in registration order.
            run_id (Optional[str], optional): Runner identity. Defaults to ``_RUN``.
        """
        FleetStore(history_root=self.root, orchestrator_session_id=parent, run_id=run_id).persist(
            entries=entries
        )

    def context(self, *, parent: str, child: str, prompt: str, execution_id: str = "") -> str:
        """Write one child's spawn_context.json and return the digest of its bytes.

        Args:
            parent (str): Orchestrator session id.
            child (str): Child session id.
            prompt (str): Full task prompt.
            execution_id (str, optional): Incarnation; empty for legacy. Defaults to "".

        Returns:
            str: SHA-256 of the exact bytes written.
        """
        directory: Path = OrchestrationLayout.child_capture_dir(
            history_root=self.root, parent_session_id=parent, child_session_id=child
        )
        directory.mkdir(parents=True, exist_ok=True)
        data: bytes = dump_json_bytes(
            SpawnContextDAO.build(
                task_id=f"task-{child}",
                prompt=prompt,
                system_prompt="SYSTEM-PRIVATE",
                inactivity_timeout_seconds=1.0,
                model=None,
                reasoning_level=None,
                cwd=None,
                execution_id=execution_id,
            )
        )
        (directory / "spawn_context.json").write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def running(self, *, parent: str, child: str, execution_id: str, prompt: str, dispatch_id: str) -> None:
        """Publish verified running evidence bound to a fresh matching spawn context.

        Args:
            parent (str): Orchestrator session id.
            child (str): Child session id.
            execution_id (str): Current incarnation.
            prompt (str): Full task prompt.
            dispatch_id (str): Admitting dispatch.
        """
        digest: str = self.context(parent=parent, child=child, prompt=prompt, execution_id=execution_id)
        evidence = ChildExecutionEvidenceDAO.pending(
            session_id=child, execution_id=execution_id, dispatch_id=dispatch_id
        ).running(stdout_identity=None, spawn_context_sha256=digest)
        FleetStore(history_root=self.root, orchestrator_session_id=parent, run_id=_RUN).publish_execution(
            evidence=evidence
        )

    async def handle(self, *, handle: WorkflowHandleDAO) -> Path:
        """Persist one workflow handle through the real store.

        Args:
            handle (WorkflowHandleDAO): Handle to write.

        Returns:
            Path: Written handle path.
        """
        return await WorkflowHandleStore(history_root=self.root).write(handle=handle)


@pytest.fixture
def files(tmp_path: Path) -> _Files:
    """Return real temp-owned orchestration files."""
    return _Files(root=tmp_path / "history")


@pytest.fixture
def no_full_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if observation loads full history, recovers, resolves names or reconciles."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("forbidden full-load, recovery or mutation path used by observation")

    monkeypatch.setattr(FilesystemSessionHistoryStore, "load_events", _forbidden)
    monkeypatch.setattr(FilesystemSessionHistoryStore, "_load_events_sync", _forbidden)
    monkeypatch.setattr(FilesystemSessionHistoryStore, "resolve_session_reference", _forbidden)
    monkeypatch.setattr(WorkflowHandleStore, "reconcile", _forbidden)
    monkeypatch.setattr(WorkflowHandleStore, "list", _forbidden)
    monkeypatch.setattr(WorkflowHandleStore, "update_state", _forbidden)
    monkeypatch.setattr(WorkflowCommandService, "list_text", _forbidden)
    monkeypatch.setattr(WorkflowCommandService, "_sweep_terminal_handle_if_needed", _forbidden)


class TestAttachedEnrichment:
    """Attached rows use matching bounded spawn context only; storage never hides rows."""

    async def test_matching_context_completes_task_text(self, files: _Files, no_full_history: None) -> None:
        """A verified matching incarnation supplies the full task; others keep previews."""
        files.running(
            parent=_OWNER,
            child="child-a",
            execution_id=_EXEC_A,
            prompt="FULL TASK A",
            dispatch_id=_DISPATCH_1,
        )
        files.running(
            parent=_OWNER, child="child-b", execution_id=_EXEC_C, prompt="OLD TASK B", dispatch_id=_DISPATCH_1
        )
        files.fleet(
            parent=_OWNER,
            entries=[
                _entry(session_id="child-a", execution_id=_EXEC_A),
                _entry(session_id="child-b", execution_id=_EXEC_C),
            ],
        )
        attached = _attached(
            entries=(
                _entry(session_id="child-a", execution_id=_EXEC_A),
                _entry(session_id="child-b", execution_id=_EXEC_B),
            )
        )

        service = _service(root=files.root, supplier=_Supplier(snapshot=attached))
        rows = (await service.load_session_snapshot()).rows

        assert [(row.key.session_id, row.task_text, row.task_text_complete) for row in rows] == [
            (_OWNER, "Orchestrator", True),
            ("child-a", "FULL TASK A", True),
            ("child-b", "preview child-b", False),
        ]

    async def test_enrichment_storage_failure_keeps_registry_rows(self, files: _Files) -> None:
        """An unreadable context store never removes or reorders registry rows."""

        class UnreadableLoader(_FakeLoader):
            async def enrich_task_row(self, *, row: WorkflowSessionRowDAO) -> WorkflowSessionRowDAO:
                """Simulate unreadable enrichment without replacing service internals."""
                raise OSError("unreadable")

        loader = UnreadableLoader(groups=[])
        attached = _attached(entries=(_entry(session_id="child-a"),))
        service = _service(
            root=files.root, supplier=_Supplier(snapshot=attached), loader_factory=lambda **kwargs: loader
        )
        rows = (await service.load_session_snapshot()).rows

        assert [(row.key.session_id, row.task_text, row.task_text_complete) for row in rows] == [
            (_OWNER, "Orchestrator", True),
            ("child-a", "preview child-a", False),
        ]


def _group(
    *,
    parent: str = _ORCH_A,
    children: tuple[ChildSessionSummaryDAO, ...] = (),
    availability: str = "available",
    orchestrator_state: Optional[str] = None,
    run_id: str = _RUN,
    fleet: bool = True,
) -> WorkflowDataDAO:
    """Build one bounded loader group result.

    Args:
        parent (str, optional): Group parent id. Defaults to ``_ORCH_A``.
        children (tuple[ChildSessionSummaryDAO, ...], optional): Child summaries.
        availability (str, optional): Group trust. Defaults to ``"available"``.
        orchestrator_state (Optional[str], optional): Parent self-report; None omits the node.
        run_id (str, optional): Current run identity. Defaults to ``_RUN``.
        fleet (bool, optional): Whether valid fleet evidence was read (authoritative
            membership); False models a missing ``fleet.json``. Defaults to True.

    Returns:
        WorkflowDataDAO: Group fixture.
    """
    return WorkflowDataDAO(
        parent_session_id=parent,
        children=list(children),
        availability=availability,  # type: ignore[arg-type]
        fleet_snapshot=(
            FleetSnapshotDAO(
                orchestrator_session_id=parent,
                updated_at="2026-10-18T00:00:00+00:00",
                entries=[
                    _entry(session_id=child.session_id, execution_id=child.execution_id) for child in children
                ],
            )
            if fleet
            else None
        ),
        orchestrator=(
            None
            if orchestrator_state is None
            else OrchestratorNodeDAO(session_id=parent, state=orchestrator_state)
        ),
        run_id=run_id,
    )


def _child(*, session_id: str, status: str = "running", complete: bool = True) -> ChildSessionSummaryDAO:
    """Build one public child summary.

    Args:
        session_id (str): Child session id.
        status (str, optional): Display status. Defaults to ``"running"``.
        complete (bool, optional): Whether the task text is full. Defaults to True.

    Returns:
        ChildSessionSummaryDAO: Summary fixture.
    """
    return ChildSessionSummaryDAO(
        session_id=session_id,
        task_id=f"task-{session_id}",
        status=status,
        task_text=f"task text {session_id}",
        task_text_complete=complete,
        has_spawn_context=complete,
        execution_id=_EXEC_A,
        dispatch_id=_DISPATCH_1,
    )


_HANDLE_A: WorkflowHandleDAO = _handle(workflow_id="wf-a", orchestrator_session_id=_ORCH_A, state="running")


class TestProjectGroup:
    """``_project_group`` validates the group before mapping literal display records."""

    @pytest.mark.parametrize(
        "group",
        [_group(parent="someone-else"), _group(availability="unavailable")],
        ids=["wrong_parent", "unavailable"],
    )
    async def test_untrusted_group_raises(self, files: _Files, group: WorkflowDataDAO) -> None:
        """A foreign or unavailable group raises the fixed error so retention runs."""
        await files.handle(handle=_HANDLE_A)
        service = _service(root=files.root, loader_factory=lambda **kwargs: _FakeLoader(groups=[group]))
        snapshot = await service.load_session_snapshot()
        assert [(r.key.session_id, r.availability) for r in snapshot.rows] == [(_ORCH_A, "unavailable")]

    async def test_valid_group_maps_parent_then_children(self, files: _Files) -> None:
        """Parent carries handle brief and run identity; children copy public fields in order."""
        service: DetachedWorkflowAppService = _service(root=None)
        group = _group(
            children=(
                _child(session_id="child-b"),
                _child(session_id="child-a", status="completed", complete=False),
            )
        )

        await files.handle(handle=_HANDLE_A)
        service = _service(root=files.root, loader_factory=lambda **kwargs: _FakeLoader(groups=[group]))
        rows = (await service.load_session_snapshot()).rows

        assert rows == (
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_ORCH_A, session_id=_ORCH_A),
                workflow_id="wf-a",
                role="orchestrator",
                status="running",
                task_text="brief for wf-a",
                task_text_complete=True,
                dispatch_id=_RUN,
            ),
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_ORCH_A, session_id="child-b"),
                workflow_id="wf-a",
                task_id="task-child-b",
                role="child",
                execution_id=_EXEC_A,
                dispatch_id=_DISPATCH_1,
                status="running",
                task_text="task text child-b",
                task_text_complete=True,
            ),
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_ORCH_A, session_id="child-a"),
                workflow_id="wf-a",
                task_id="task-child-a",
                role="child",
                execution_id=_EXEC_A,
                dispatch_id=_DISPATCH_1,
                status="completed",
                task_text="task text child-a",
                task_text_complete=False,
            ),
        )

    @pytest.mark.parametrize(
        ("orchestrator_state", "expected"),
        [(None, "running"), ("unknown", "running"), ("completed", "completed")],
        ids=["no_self_report", "unknown_self_report", "current_self_report"],
    )
    async def test_parent_status_prefers_known_self_report(
        self, files: _Files, orchestrator_state: Optional[str], expected: str
    ) -> None:
        """An unknown or absent self-report preserves the handle state, never ``unknown``."""
        service: DetachedWorkflowAppService = _service(root=None)

        await files.handle(handle=_HANDLE_A)
        service = _service(
            root=files.root,
            loader_factory=lambda **kwargs: _FakeLoader(
                groups=[_group(orchestrator_state=orchestrator_state)]
            ),
        )
        rows = (await service.load_session_snapshot()).rows

        assert rows[0].status == expected


class _FakeLoader:
    """Recording loader standing in for ``WorkflowVisualizerLoader`` in orchestration units."""

    def __init__(self, *, groups: list[object]) -> None:
        """Seed the scripted group results.

        Args:
            groups (list[object]): Results (WorkflowDataDAO) or exceptions, consumed in order;
                the last one repeats.
        """
        self.groups: list[object] = groups
        self.next_loader: Optional[_FakeLoader] = None
        self.group_reads: int = 0
        self.progress_rows: list[WorkflowSessionRowDAO] = []
        self.progress_result: Optional[object] = None
        self.during_progress_read: Callable[[], None] = lambda: None

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Return or raise the next scripted group.

        Returns:
            WorkflowDataDAO: Scripted group.
        """
        if self.next_loader is not None:
            return await self.next_loader.load_observation_group()
        result: object = self.groups[min(self.group_reads, len(self.groups) - 1)]
        self.group_reads += 1
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, WorkflowDataDAO)
        return result

    async def enrich_task_row(self, *, row: WorkflowSessionRowDAO) -> WorkflowSessionRowDAO:
        """Return the row unchanged.

        Args:
            row (WorkflowSessionRowDAO): Registry row.

        Returns:
            WorkflowSessionRowDAO: Same row.
        """
        return row

    async def load_session_progress(self, *, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
        """Record the row and return or raise the scripted progress result.

        Args:
            row (WorkflowSessionRowDAO): Row captured by the service.

        Returns:
            SessionProgressSnapshotDAO: Scripted progress.
        """
        self.progress_rows.append(row)
        self.during_progress_read()
        if isinstance(self.progress_result, BaseException):
            raise self.progress_result
        assert isinstance(self.progress_result, SessionProgressSnapshotDAO)
        return self.progress_result


class TestAbortedWorkflowStatus:
    """Confirmed workflow aborts override parent reports, not child evidence."""

    @pytest.mark.parametrize("reported", [None, "unknown", "running", "completed", "failed"])
    async def test_aborted_handle_overrides_parent_self_report(
        self, files: _Files, reported: Optional[str]
    ) -> None:
        """A confirmed abort cannot be resurrected by an older parent report."""
        service = _service(root=None)
        handle = _HANDLE_A.model_copy(update={"state": "aborted"})
        group = _group(
            orchestrator_state=reported,
            children=(_child(session_id="done", status="completed"), _child(session_id="active")),
        )

        await files.handle(handle=handle)
        service = _service(root=files.root, loader_factory=lambda **kwargs: _FakeLoader(groups=[group]))
        rows = (await service.load_session_snapshot()).rows

        assert [row.status for row in rows] == ["aborted", "completed", "running"]
        assert group.orchestrator is None or group.orchestrator.state == reported

    @pytest.mark.parametrize("failure", [OSError("gone"), ValueError("corrupt")])
    async def test_abort_updates_cached_parent_during_read_failure(
        self, files: _Files, failure: Exception
    ) -> None:
        """Unreadable group files preserve history without preserving a running parent."""
        good = _group(orchestrator_state="running", children=(_child(session_id="done", status="completed"),))
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[good, failure])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
        fresh = (await service.load_session_snapshot()).rows

        await WorkflowHandleStore(history_root=files.root).update_state(
            owner_session_id=_OWNER, workflow_id="wf-a", state="aborted"
        )
        rows = (await service.load_session_snapshot()).rows

        assert [row.status for row in rows] == ["aborted", "completed"]
        assert all(row.availability == "stale" for row in rows)
        assert [row.key for row in rows] == [row.key for row in fresh]
        assert [row.task_text for row in rows] == [row.task_text for row in fresh]
        assert fresh[0].status == "running"

    async def test_snapshot_refresh_and_resume_observe_abort(self, files: _Files) -> None:
        """A persisted abort updates an existing list and a newly resumed service."""
        await files.handle(handle=_HANDLE_A)
        group = _group(orchestrator_state="running")
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[group])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
        assert (await service.load_session_snapshot()).rows[0].status == "running"
        await WorkflowHandleStore(history_root=files.root).update_state(
            owner_session_id=_OWNER, workflow_id="wf-a", state="aborted"
        )
        before = _tree_bytes(root=files.root)

        assert (await service.load_session_snapshot()).rows[0].status == "aborted"
        resumed = _service(root=files.root, loader_factory=lambda **kwargs: _FakeLoader(groups=[group]))
        assert (await resumed.load_session_snapshot()).rows[0].status == "aborted"
        assert _tree_bytes(root=files.root) == before


class TestRetainFailedGroup:
    """``_load_group``/``_retain_failed_group``: unreadable files are never deletion."""

    async def test_first_failure_shows_one_unavailable_parent(self, files: _Files) -> None:
        """Without last-good rows a failed group becomes one unavailable parent row."""
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[OSError("unreadable")])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)

        rows = (await service.load_session_snapshot()).rows

        assert rows == (
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_ORCH_A, session_id=_ORCH_A),
                workflow_id="wf-a",
                role="orchestrator",
                status="running",
                task_text="brief for wf-a",
                task_text_complete=True,
                availability="unavailable",
            ),
        )

    @pytest.mark.parametrize(
        "failure", [OSError("gone"), ValueError("corrupt")], ids=["os_error", "value_error"]
    )
    async def test_later_failure_retains_last_good_rows_as_stale(
        self, files: _Files, failure: Exception
    ) -> None:
        """After a fresh read, a failed read retains the same rows marked stale."""
        good = _group(children=(_child(session_id="child-a"),))
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[good, failure])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)

        fresh = (await service.load_session_snapshot()).rows
        retained = (await service.load_session_snapshot()).rows

        assert [row.availability for row in fresh] == ["available", "available"]
        assert retained == tuple(row.model_copy(update={"availability": "stale"}) for row in fresh)

    async def test_unavailable_group_retains_rows_instead_of_clearing_membership(self, files: _Files) -> None:
        """A loader-reported unavailable group never replaces membership with emptiness."""
        good = _group(children=(_child(session_id="child-a"),))
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[good, _group(availability="unavailable")])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)

        (await service.load_session_snapshot()).rows
        retained = (await service.load_session_snapshot()).rows

        assert [(row.key.session_id, row.availability) for row in retained] == [
            (_ORCH_A, "stale"),
            ("child-a", "stale"),
        ]

    async def test_missing_fleet_retains_known_children_as_stale(self, files: _Files) -> None:
        """Without fleet evidence a vanished known child stays listed stale; fresh rows stay fresh."""
        good = _group(children=(_child(session_id="child-a"),))
        without_fleet = _group(children=(_child(session_id="child-new"),), fleet=False)
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[good, without_fleet])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)

        (await service.load_session_snapshot()).rows
        retained = (await service.load_session_snapshot()).rows
        again = (await service.load_session_snapshot()).rows

        assert [(row.key.session_id, row.availability) for row in retained] == [
            (_ORCH_A, "available"),
            ("child-a", "stale"),
        ]
        assert again == retained
        assert service.current_list_snapshot().rows == retained

    async def test_valid_fleet_replaces_child_membership(self, files: _Files) -> None:
        """A present, valid fleet that lacks a known child is authoritative removal."""
        good = _group(children=(_child(session_id="child-a"),))
        await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[good, _group()])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)

        (await service.load_session_snapshot()).rows
        replaced = (await service.load_session_snapshot()).rows

        assert [(row.key.session_id, row.availability) for row in replaced] == [(_ORCH_A, "available")]


class _FailingObservationStore(WorkflowHandleStore):
    """Real file adapter with an injected observation failure for cutoff coverage."""

    failure: Optional[Exception] = None

    async def list_observation(self, *, owner_session_id: str) -> tuple[WorkflowHandleDAO, ...]:
        """Read real files unless the scenario has enabled a read failure."""
        if self.failure is not None:
            raise self.failure
        return await super().list_observation(owner_session_id=owner_session_id)


class TestReadOwnedHandles:
    """``_read_owned_handles``: bounded listing with retained membership on failure."""

    async def test_missing_store_reads_nothing(self) -> None:
        """A no-history service observes no detached handles and sets no notice."""
        service: DetachedWorkflowAppService = _service(root=None)

        assert (await service.load_session_snapshot()).rows == ()
        assert service.current_list_snapshot().notice is None

    async def test_fresh_listing_is_sorted_owned_only(self, files: _Files, no_full_history: None) -> None:
        """Fresh reads admit owned handles by start then id and exclude other owners."""
        await files.handle(handle=_handle(workflow_id="wf-late", orchestrator_session_id=_ORCH_A, hour=14))
        await files.handle(handle=_handle(workflow_id="wf-early", orchestrator_session_id=_ORCH_B, hour=9))
        await files.handle(
            handle=_handle(
                workflow_id="wf-foreign", orchestrator_session_id="orch-x", owner_session_id="other-owner"
            )
        )
        service: DetachedWorkflowAppService = _service(root=files.root)

        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-early", "wf-late"]
        assert service.current_list_snapshot().notice is None

    @pytest.mark.parametrize("failure", [OSError("denied"), ValueError("workflow observation unavailable")])
    async def test_failure_retains_known_handles_with_notice(self, files: _Files, failure: Exception) -> None:
        """Permission or validation failure keeps prior membership and sets the fixed notice."""
        await files.handle(handle=_HANDLE_A)
        store = _FailingObservationStore(history_root=files.root)
        service = _service(root=files.root, store=store)
        await service.load_session_snapshot()
        store.failure = failure
        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service.current_list_snapshot().notice == _LIST_UNAVAILABLE

    async def test_overflow_admits_no_partial_new_set(self, files: _Files) -> None:
        """AMBIGUOUS-2: the 257th handle keeps exactly the retained set, never a partial one."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        (await service.load_session_snapshot()).rows
        workflows_dir: Path = OrchestrationLayout.workflows_dir(
            history_root=files.root, owner_session_id=_OWNER
        )
        for index in range(256):
            extra = _handle(workflow_id=f"wf-{index:04d}", orchestrator_session_id=f"orch-{index}")
            (workflows_dir / f"{extra.workflow_id}.json").write_text(
                extra.model_dump_json(), encoding="utf-8"
            )

        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service.current_list_snapshot().notice == _LIST_UNAVAILABLE

    async def test_union_above_limit_admits_no_new_handle(self, files: _Files) -> None:
        """A valid 256-handle listing whose union with retained handles is 257 keeps the retained set."""
        path: Path = await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        (await service.load_session_snapshot()).rows
        for sibling in path.parent.iterdir():
            sibling.unlink()
        for index in range(256):
            extra = _handle(workflow_id=f"wf-{index:04d}", orchestrator_session_id=f"orch-{index}")
            (path.parent / f"{extra.workflow_id}.json").write_text(extra.model_dump_json(), encoding="utf-8")
        assert (
            len(await WorkflowHandleStore(history_root=files.root).list_observation(owner_session_id=_OWNER))
            == 256
        )

        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert [row.workflow_id for row in service.current_list_snapshot().rows] == ["wf-a"]
        assert service.current_list_snapshot().notice == _LIST_UNAVAILABLE

    @pytest.mark.parametrize("removal", ["handle_file", "directory"])
    async def test_missing_files_retain_known_handles(self, files: _Files, removal: str) -> None:
        """An emptied or absent directory with known handles is retention, not fresh empty."""
        path: Path = await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        (await service.load_session_snapshot()).rows
        for sibling in path.parent.iterdir():
            sibling.unlink()
        if removal == "directory":
            path.parent.rmdir()

        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service.current_list_snapshot().notice == _LIST_UNAVAILABLE

    async def test_fresh_success_clears_notice(self, files: _Files) -> None:
        """The next complete read clears the stale notice."""
        await files.handle(handle=_HANDLE_A)
        store = _FailingObservationStore(history_root=files.root)
        service = _service(root=files.root, store=store)
        store.failure = OSError("denied")
        await service.load_session_snapshot()
        store.failure = None

        handles = (await service.load_session_snapshot()).rows

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service.current_list_snapshot().notice is None


class _RecordingFactory:
    """Record adapter construction while delegating bounded reads to real files."""

    def __init__(self) -> None:
        """Begin with an empty construction log."""
        self.parents: list[str] = []

    def __call__(
        self, *, parent_session_id: str, history_store: SessionHistoryStoreProtocol
    ) -> WorkflowVisualizerLoader:
        """Construct a production adapter without reading during construction."""
        self.parents.append(parent_session_id)
        return WorkflowVisualizerLoader(
            config=HeadlessWorkflowVisualizerConfigDAO(session_reference=parent_session_id),
            store=history_store,
        )


class TestAdoptDispatch:
    """Public observations prove commit-only attached adapter invalidation."""

    async def test_same_dispatch_keeps_caches(self, files: _Files) -> None:
        """Initial adoption invalidates enrichment; subsequent same-batch polls reuse it."""
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child"),)))
        factory = _RecordingFactory()
        service = _service(root=files.root, supplier=supplier, loader_factory=factory)
        await service.load_session_snapshot()
        assert factory.parents == [_OWNER]
        await service.load_session_snapshot()
        assert factory.parents == [_OWNER, _OWNER]
        await service.load_session_snapshot()
        assert factory.parents == [_OWNER, _OWNER]

    async def test_new_dispatch_drops_only_attached_caches(self, files: _Files) -> None:
        """A new dispatch invalidates its adapter but not the detached adapter."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="old"),)))
        factory = _RecordingFactory()
        service = _service(root=files.root, supplier=supplier, loader_factory=factory)
        await service.load_session_snapshot()
        await service.load_session_snapshot()
        supplier.snapshot = _attached(
            entries=(_entry(session_id="new"),), dispatch_id=_DISPATCH_2, sequence=2
        )
        await service.load_session_snapshot()
        snapshot = await service.load_session_snapshot()
        assert factory.parents.count(_OWNER) == 3
        assert factory.parents.count(_ORCH_A) == 1
        assert [row.key.session_id for row in snapshot.rows] == [_OWNER, "new", _ORCH_A]


_HANDLE_B: WorkflowHandleDAO = _handle(workflow_id="wf-b", orchestrator_session_id=_ORCH_B, hour=13)


def _seed_loaders() -> dict[str, _FakeLoader]:
    """Build recording adapters to inject before service construction."""
    return {
        _OWNER: _FakeLoader(groups=[_group(parent=_OWNER)]),
        _ORCH_A: _FakeLoader(groups=[_group(parent=_ORCH_A, children=(_child(session_id="child-a"),))]),
        _ORCH_B: _FakeLoader(groups=[_group(parent=_ORCH_B)]),
    }


class TestProjectDetachedGroups:
    """``_project_detached_groups``: dismissal suppression, stale marking and yielding."""

    @pytest.mark.parametrize(
        ("dismiss", "resume", "expected"),
        [
            ((), (), [_ORCH_A, "child-a", _ORCH_B]),
            (("wf-a",), (), [_ORCH_B]),
            (("wf-a",), ("wf-a",), [_ORCH_A, "child-a", _ORCH_B]),
            (("wf-a", "wf-b"), ("wf-b",), [_ORCH_B]),
        ],
        ids=["none", "dismissed", "resumed", "mixed"],
    )
    async def test_dismissal_and_resume(
        self, files: _Files, dismiss: tuple[str, ...], resume: tuple[str, ...], expected: list[str]
    ) -> None:
        """Explicit dismissal hides only that group; a successful resume restores it."""
        await files.handle(handle=_HANDLE_A)
        await files.handle(handle=_HANDLE_B)
        loaders = _seed_loaders()
        service = _service(
            root=files.root, loader_factory=lambda **kwargs: loaders[kwargs["parent_session_id"]]
        )
        for workflow_id in dismiss:
            service.dismiss_group(workflow_id=workflow_id)
        for workflow_id in resume:
            service.resume_group(workflow_id=workflow_id)

        rows = (await service.load_session_snapshot()).rows

        assert [row.key.session_id for row in rows] == expected
        assert loaders[_ORCH_A].group_reads == 1

    async def test_dismissal_drops_group_caches(self, files: _Files) -> None:
        """Hidden progress is refused, but show preserves the original display rows."""
        await files.handle(handle=_HANDLE_A)
        loaders = _seed_loaders()
        service = _service(
            root=files.root, loader_factory=lambda **kwargs: loaders[kwargs["parent_session_id"]]
        )
        initial = await service.load_session_snapshot()
        service.dismiss_group(workflow_id="wf-a")
        assert service.current_list_snapshot().rows == ()
        assert (await service.load_session_progress(key=initial.rows[1].key)).membership_removed
        assert loaders[_ORCH_A].progress_rows == []
        shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
        assert [row.key for row in shown.snapshot.rows] == [row.key for row in initial.rows]

    async def test_list_notice_marks_detached_rows_stale(self, files: _Files) -> None:
        """Failed ownership leaves all retained rows stale, without private notice setup."""
        path = await files.handle(handle=_HANDLE_A)
        loaders = _seed_loaders()
        service = _service(
            root=files.root, loader_factory=lambda **kwargs: loaders[kwargs["parent_session_id"]]
        )
        await service.load_session_snapshot()
        path.unlink()
        snapshot = await service.load_session_snapshot()
        assert snapshot.notice == _LIST_UNAVAILABLE
        assert {row.availability for row in snapshot.rows} == {"stale"}

    async def test_list_notice_keeps_unavailable_parent_unavailable(self, files: _Files) -> None:
        """Failed ownership never weakens an unavailable row to stale."""
        path = await files.handle(handle=_HANDLE_A)
        loader = _FakeLoader(groups=[OSError("unreadable")])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
        await service.load_session_snapshot()
        path.unlink()
        snapshot = await service.load_session_snapshot()
        assert snapshot.notice == _LIST_UNAVAILABLE
        assert [(row.key.session_id, row.availability) for row in snapshot.rows] == [(_ORCH_A, "unavailable")]

    async def test_yields_between_serial_group_reads(self, files: _Files) -> None:
        """A callback scheduled by the first adapter runs before the second read."""
        await files.handle(handle=_HANDLE_A)
        await files.handle(handle=_HANDLE_B)
        events: list[str] = []

        class YieldLoader(_FakeLoader):
            async def load_observation_group(self) -> WorkflowDataDAO:
                """Record order and schedule a callback without yielding ourselves."""
                events.append("read")
                asyncio.get_running_loop().call_soon(events.append, "yield")
                return await super().load_observation_group()

        service = _service(
            root=files.root,
            loader_factory=lambda **kwargs: YieldLoader(groups=[_group(parent=kwargs["parent_session_id"])]),
        )
        await service.load_session_snapshot()
        assert events == ["read", "yield", "read", "yield"]


def _tree_bytes(*, root: Path) -> dict[str, bytes]:
    """Snapshot every regular file below ``root`` to prove observation writes nothing.

    Args:
        root (Path): Directory to snapshot.

    Returns:
        dict[str, bytes]: Relative path to exact bytes.
    """
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


async def _seed_detached(*, files: _Files) -> None:
    """Seed two owned detached groups plus one unrelated owner's workflow.

    Args:
        files (_Files): Real temporary orchestration files.
    """
    await files.handle(
        handle=_handle(workflow_id="wf-b", orchestrator_session_id=_ORCH_B, state="completed", hour=13)
    )
    await files.handle(handle=_HANDLE_A)
    await files.handle(
        handle=_handle(
            workflow_id="wf-x", orchestrator_session_id="orch-x", owner_session_id="other-owner", hour=1
        )
    )
    files.running(
        parent=_ORCH_A,
        child="child-full",
        execution_id=_EXEC_A,
        prompt="FULL DETACHED TASK",
        dispatch_id=_DISPATCH_1,
    )
    legacy = SubAgentStatusDAO(
        task_id="task-legacy", session_id="child-legacy", status="completed", prompt_preview="legacy preview"
    )
    files.fleet(parent=_ORCH_A, entries=[_entry(session_id="child-full", execution_id=_EXEC_A), legacy])


class TestLoadSessionSnapshot:
    """``load_session_snapshot`` composes attached and owned detached groups observationally."""

    async def test_owned_groups_are_ordered_and_deduplicated(
        self, files: _Files, no_full_history: None
    ) -> None:
        """Attached first, detached by start time; exact keys, status, text and completeness."""
        await _seed_detached(files=files)
        files.running(
            parent=_OWNER,
            child="child-1",
            execution_id=_EXEC_B,
            prompt="FULL ATTACHED TASK",
            dispatch_id=_DISPATCH_1,
        )
        files.fleet(parent=_OWNER, entries=[_entry(session_id="child-1", execution_id=_EXEC_B)])
        supplier = _Supplier(
            snapshot=_attached(
                entries=(
                    _entry(session_id="child-1", execution_id=_EXEC_B),
                    _entry(session_id="child-2", status="pending", execution_id=_EXEC_C),
                )
            )
        )
        service: DetachedWorkflowAppService = _service(root=files.root, supplier=supplier)
        before: dict[str, bytes] = _tree_bytes(root=files.root)

        snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert [
            (
                row.key.orchestrator_session_id,
                row.key.session_id,
                row.status,
                row.task_text,
                row.task_text_complete,
            )
            for row in snapshot.rows
        ] == [
            (_OWNER, _OWNER, "running", "Orchestrator", True),
            (_OWNER, "child-1", "running", "FULL ATTACHED TASK", True),
            (_OWNER, "child-2", "pending", "preview child-2", False),
            (_ORCH_A, _ORCH_A, "running", "brief for wf-a", True),
            (_ORCH_A, "child-full", "running", "FULL DETACHED TASK", True),
            (_ORCH_A, "child-legacy", "completed", "legacy preview", False),
            (_ORCH_B, _ORCH_B, "completed", "brief for wf-b", True),
        ]
        assert {row.workflow_id for row in snapshot.rows} == {None, "wf-a", "wf-b"}
        assert snapshot.notice is None
        assert {row.availability for row in snapshot.rows} == {"available"}
        assert _tree_bytes(root=files.root) == before

    async def test_duplicate_keys_keep_registry_precedence(self) -> None:
        """Duplicate registry keys keep the first value and position in public projection."""
        first = _entry(session_id="child", status="completed")
        other = _entry(session_id="other", status="pending")
        duplicate = first.model_copy(update={"status": "running", "prompt_preview": "event guess"})
        service = _service(
            root=None, supplier=_Supplier(snapshot=_attached(entries=(first, other, duplicate)))
        )
        rows = (await service.load_session_snapshot()).rows[1:]
        assert [(row.key.session_id, row.status, row.task_text) for row in rows] == [
            ("child", "completed", "preview child"),
            ("other", "pending", "preview other"),
        ]

    async def test_missing_corrupt_and_escaped_sources(
        self, files: _Files, tmp_path: Path, no_full_history: None
    ) -> None:
        """Corrupt fleet → unavailable parent; a symlink to another temp root is never followed."""
        await files.handle(handle=_HANDLE_A)
        (files.root / _ORCH_A).mkdir(parents=True, exist_ok=True)
        (files.root / _ORCH_A / "fleet.json").write_text("{corrupt", encoding="utf-8")
        outside: Path = tmp_path / "outside-root" / "child-escape"
        outside.mkdir(parents=True)
        (outside / "spawn_context.json").write_text("ESCAPED-SECRET", encoding="utf-8")
        children: Path = files.root / _ORCH_A / "children"
        children.mkdir()
        (children / "child-escape").symlink_to(outside)
        outside_before: dict[str, bytes] = _tree_bytes(root=outside)
        service: DetachedWorkflowAppService = _service(root=files.root)

        snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert [(row.key.session_id, row.availability) for row in snapshot.rows] == [(_ORCH_A, "unavailable")]
        assert all("ESCAPED-SECRET" not in row.task_text for row in snapshot.rows)
        assert _tree_bytes(root=outside) == outside_before

    @pytest.mark.parametrize("run_id", [None, _RUN], ids=["legacy", "run_bound"])
    async def test_deleted_fleet_retains_known_children(
        self, files: _Files, run_id: Optional[str], no_full_history: None
    ) -> None:
        """Real files: deleting fleet.json keeps the child listed stale and progress not removed."""
        await files.handle(handle=_HANDLE_A)
        pending = SubAgentStatusDAO(
            task_id="task-pending", session_id="child-pending", status="pending", prompt_preview="p"
        )
        files.fleet(parent=_ORCH_A, entries=[pending], run_id=run_id)
        service: DetachedWorkflowAppService = _service(root=files.root)
        first: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        OrchestrationLayout.fleet_path(history_root=files.root, orchestrator_session_id=_ORCH_A).unlink()
        key = _key(orchestrator_session_id=_ORCH_A, session_id="child-pending")

        progress: SessionProgressSnapshotDAO = await service.load_session_progress(key=key)
        second: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert [row.key.session_id for row in first.rows] == [_ORCH_A, "child-pending"]
        assert (progress.membership_removed, progress.entries, progress.availability) == (False, (), "stale")
        assert [(row.key.session_id, row.availability) for row in second.rows] == [
            (_ORCH_A, "available"),
            ("child-pending", "stale"),
        ]

    async def test_vanished_legacy_directory_child_is_retained(
        self, files: _Files, no_full_history: None
    ) -> None:
        """Real files: a directory-only legacy child whose directory vanished is never removal."""
        await files.handle(handle=_HANDLE_A)
        capture: Path = OrchestrationLayout.child_capture_dir(
            history_root=files.root, parent_session_id=_ORCH_A, child_session_id="child-dir-only"
        )
        capture.mkdir(parents=True)
        (capture / "stdout.jsonl").write_text('{"kind": "text_delta", "delta": "words"}\n', encoding="utf-8")
        service: DetachedWorkflowAppService = _service(root=files.root)
        first: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        for path in sorted(capture.iterdir()):
            path.unlink()
        capture.rmdir()
        key = _key(orchestrator_session_id=_ORCH_A, session_id="child-dir-only")

        progress: SessionProgressSnapshotDAO = await service.load_session_progress(key=key)
        second: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert [row.key.session_id for row in first.rows] == [_ORCH_A, "child-dir-only"]
        assert (progress.membership_removed, progress.entries) == (False, ())
        assert [(row.key.session_id, row.availability) for row in second.rows] == [
            (_ORCH_A, "available"),
            ("child-dir-only", "stale"),
        ]

    async def test_corrupt_owner_handle_keeps_last_known_groups(
        self, files: _Files, no_full_history: None
    ) -> None:
        """A corrupt sibling handle keeps known groups visible but stale with the fixed notice."""
        path: Path = await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service.load_session_snapshot()
        (path.parent / "wf-bad.json").write_text("{corrupt", encoding="utf-8")

        snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert snapshot.notice == _LIST_UNAVAILABLE
        assert [(row.key.session_id, row.availability) for row in snapshot.rows] == [(_ORCH_A, "stale")]

    async def test_loader_cache_is_reused_across_polls(self, files: _Files) -> None:
        """One bounded loader per parent serves repeated polls."""
        await files.handle(handle=_HANDLE_A)
        factory = _RecordingFactory()
        service = _service(root=files.root, loader_factory=factory)

        await service.load_session_snapshot()
        await service.load_session_snapshot()

        assert factory.parents == [_ORCH_A]

    async def test_old_dispatch_event_cannot_restore_rows(self, files: _Files) -> None:
        """A refresh requested by late old-batch events still shows only the latest batch."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(
            snapshot=_attached(entries=(_entry(session_id="old-child", execution_id=_EXEC_A),))
        )
        factory = _RecordingFactory()
        service = _service(root=files.root, supplier=supplier, loader_factory=factory)
        await service.load_session_snapshot()
        supplier.snapshot = _attached(
            entries=(_entry(session_id="new-child", execution_id=_EXEC_B),),
            dispatch_id=_DISPATCH_2,
            sequence=2,
        )
        await service.load_session_snapshot()

        late_refresh: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()

        assert [row.key.session_id for row in late_refresh.rows] == [_OWNER, "new-child", _ORCH_A]
        assert {
            row.dispatch_id for row in late_refresh.rows if row.key.orchestrator_session_id == _OWNER
        } == {_DISPATCH_2}
        assert factory.parents.count(_ORCH_A) == 1

    async def test_missed_start_event_is_repaired_by_poll(self, files: _Files) -> None:
        """Without any start event, the next poll adopts the new batch and invalidates old keys."""
        supplier = _Supplier(
            snapshot=_attached(entries=(_entry(session_id="old-child", execution_id=_EXEC_A),))
        )
        factory = _RecordingFactory()
        service = _service(root=files.root, supplier=supplier, loader_factory=factory)
        await service.load_session_snapshot()
        supplier.snapshot = _attached(
            entries=(_entry(session_id="new-child", execution_id=_EXEC_B),),
            dispatch_id=_DISPATCH_2,
            sequence=2,
        )

        repaired: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        old_progress: SessionProgressSnapshotDAO = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="old-child", attached_dispatch_id=_DISPATCH_1)
        )

        assert [row.key.session_id for row in repaired.rows] == [_OWNER, "new-child"]
        assert factory.parents.count(_OWNER) == 2
        assert (old_progress.membership_removed, old_progress.entries) == (True, ())

    async def test_close_clears_caches_and_refuses_new_observation(self, files: _Files) -> None:
        """After close the service reads nothing and returns empty observation."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1"),)))
        factory = _RecordingFactory()
        service = _service(root=files.root, supplier=supplier, loader_factory=factory)
        await service.load_session_snapshot()
        reads_before_close: int = supplier.calls

        await service.close()
        snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        progress: SessionProgressSnapshotDAO = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="child-1", attached_dispatch_id=_DISPATCH_1)
        )

        assert snapshot == WorkflowSessionSnapshotDAO()
        assert supplier.calls == reads_before_close
        assert (
            service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show")).outcome
            == "unavailable"
        )
        assert (progress.membership_removed, progress.entries) == (True, ())

    async def test_close_during_group_read_leaves_caches_empty(self, files: _Files) -> None:
        """A blocked read cannot publish after close or start another group read."""
        await files.handle(handle=_HANDLE_A)
        await files.handle(handle=_HANDLE_B)
        loader = _BlockingLoader(group=_group(children=(_child(session_id="child-a"),)))
        parents: list[str] = []

        def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> _FakeLoader:
            """Record requested adapters; B must never be reached."""
            parents.append(parent_session_id)
            assert parent_session_id == _ORCH_A
            return loader

        service = _service(root=files.root, loader_factory=factory)
        task = asyncio.create_task(service.load_session_snapshot())
        await loader.entered.wait()
        await service.close()
        loader.release.set()
        assert await task == WorkflowSessionSnapshotDAO()
        assert await service.load_session_snapshot() == WorkflowSessionSnapshotDAO()
        assert parents == [_ORCH_A]

    async def test_close_during_handle_listing_admits_nothing(self, files: _Files) -> None:
        """A listing completing after close cannot admit rows or construct loaders."""
        await files.handle(handle=_HANDLE_A)
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingStore(WorkflowHandleStore):
            async def list_observation(self, *, owner_session_id: str) -> tuple[WorkflowHandleDAO, ...]:
                """Hold the real listing at its public adapter boundary."""
                listing = await super().list_observation(owner_session_id=owner_session_id)
                entered.set()
                await release.wait()
                return listing

        factory = _RecordingFactory()
        service = _service(
            root=files.root, store=BlockingStore(history_root=files.root), loader_factory=factory
        )
        task = asyncio.create_task(service.load_session_snapshot())
        await entered.wait()
        await service.close()
        release.set()
        assert await task == WorkflowSessionSnapshotDAO()
        assert await service.load_session_snapshot() == WorkflowSessionSnapshotDAO()
        assert factory.parents == []

    async def test_loader_requested_after_close_is_not_cached(self, files: _Files) -> None:
        """Late public observations never construct an adapter after close."""
        factory = _RecordingFactory()
        service = _service(root=files.root, loader_factory=factory)
        await service.close()
        assert await service.load_session_snapshot() == WorkflowSessionSnapshotDAO()
        progress = await service.load_session_progress(
            key=_key(orchestrator_session_id=_ORCH_A, session_id="child")
        )
        assert progress.membership_removed
        assert factory.parents == []


class _BlockingLoader(_FakeLoader):
    """Loader whose group read blocks until released, to close the service mid-read."""

    def __init__(self, *, group: WorkflowDataDAO) -> None:
        """Seed the group returned after release.

        Args:
            group (WorkflowDataDAO): Group result.
        """
        super().__init__(groups=[group])
        self.entered: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Signal entry, wait for release, then return the seeded group.

        Returns:
            WorkflowDataDAO: Seeded group.
        """
        self.entered.set()
        await self.release.wait()
        return await super().load_observation_group()


_REMOVED_NOTICE: str = "Session removed from current workflow."
_RETRY_NOTICE: str = "Progress unavailable; retrying."


def _progress(
    *, key: WorkflowSessionKeyDAO, execution_id: str = _EXEC_A, dispatch_id: str = _DISPATCH_1
) -> SessionProgressSnapshotDAO:
    """Build one loader progress result carrying content.

    Args:
        key (WorkflowSessionKeyDAO): Observed key.
        execution_id (str, optional): Incarnation. Defaults to ``_EXEC_A``.
        dispatch_id (str, optional): Batch. Defaults to ``_DISPATCH_1``.

    Returns:
        SessionProgressSnapshotDAO: Progress fixture.
    """
    return SessionProgressSnapshotDAO(
        key=key,
        execution_id="" if key.is_parent else execution_id,
        dispatch_id=dispatch_id,
        revision="r1",
        source_generation="g1",
        availability="available",
        observed_at="2026-10-18T00:00:00+00:00",
        task_text="task",
        task_text_complete=True,
        status="running",
    )


_CHILD_1: WorkflowSessionKeyDAO = _key(
    orchestrator_session_id=_OWNER, session_id="child-1", attached_dispatch_id=_DISPATCH_1
)
_DETACHED_CHILD: WorkflowSessionKeyDAO = _key(orchestrator_session_id=_ORCH_A, session_id="child-a")


async def _attached_service(*, files: _Files) -> tuple[DetachedWorkflowAppService, _Supplier, _FakeLoader]:
    """Build a service whose latest snapshot holds attached child-1 (dispatch 1, exec A).

    Args:
        files (_Files): Real temporary root.

    Returns:
        tuple[DetachedWorkflowAppService, _Supplier, _FakeLoader]: Service, supplier, owner loader.
    """
    supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1", execution_id=_EXEC_A),)))
    loader = _FakeLoader(groups=[_group(parent=_OWNER)])
    service = _service(root=files.root, supplier=supplier, loader_factory=lambda **kwargs: loader)
    await service.load_session_snapshot()
    return service, supplier, loader


async def _detached_service(
    *, files: _Files, child: ChildSessionSummaryDAO
) -> tuple[DetachedWorkflowAppService, _FakeLoader]:
    """Build a service whose latest snapshot holds detached group wf-a with ``child``.

    Args:
        files (_Files): Real temporary root.
        child (ChildSessionSummaryDAO): Child present at snapshot time.

    Returns:
        tuple[DetachedWorkflowAppService, _FakeLoader]: Service and the group's loader.
    """
    await files.handle(handle=_HANDLE_A)
    loader = _FakeLoader(groups=[_group(children=(child,))])
    service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
    await service.load_session_snapshot()
    return service, loader


class TestLoadSessionProgress:
    """Service progress gateway: membership captured before, re-read after, every read."""

    async def test_unknown_key_is_removed_without_reading(self, files: _Files) -> None:
        """A key absent from the latest snapshot returns removal and reads nothing."""
        service, _, loader = await _attached_service(files=files)

        progress = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="ghost", attached_dispatch_id=_DISPATCH_1)
        )

        assert (progress.membership_removed, progress.entries, progress.notice) == (True, (), _REMOVED_NOTICE)
        assert (progress.availability, progress.abort_target) == ("stale", None)
        assert loader.progress_rows == []

    async def test_attached_matching_returns_loader_snapshot(self, files: _Files) -> None:
        """Unchanged attached membership passes the loader's bounded result through."""
        service, _, loader = await _attached_service(files=files)
        loader.progress_result = _progress(key=_CHILD_1)

        progress = await service.load_session_progress(key=_CHILD_1)

        assert progress == _progress(key=_CHILD_1)
        assert [(row.key, row.execution_id, row.dispatch_id) for row in loader.progress_rows] == [
            (_CHILD_1, _EXEC_A, _DISPATCH_1)
        ]

    async def test_pre_read_unreadable_is_stale_not_removed(self, files: _Files) -> None:
        """A failed bounded read keeps membership and returns a content-free retry notice."""
        service, _, loader = await _attached_service(files=files)
        loader.progress_result = OSError("unreadable")

        progress = await service.load_session_progress(key=_CHILD_1)

        assert (progress.membership_removed, progress.entries, progress.notice) == (False, (), _RETRY_NOTICE)
        assert (progress.execution_id, progress.dispatch_id, progress.status) == (
            _EXEC_A,
            _DISPATCH_1,
            "unknown",
        )

    @pytest.mark.parametrize(
        ("after_read", "removed"),
        [
            (
                _attached(
                    entries=(_entry(session_id="child-9", execution_id=_EXEC_B),),
                    dispatch_id=_DISPATCH_2,
                    sequence=2,
                ),
                True,
            ),
            (
                _attached(
                    entries=(_entry(session_id="child-1", execution_id=_EXEC_B),),
                    dispatch_id=_DISPATCH_2,
                    sequence=2,
                ),
                True,
            ),
            (_attached(entries=(_entry(session_id="child-1", execution_id=_EXEC_B),)), False),
            (AttachedDispatchSnapshotDAO.empty(), True),
        ],
        ids=["new_batch_without_child", "new_batch_reuses_key", "same_batch_new_incarnation", "no_dispatch"],
    )
    async def test_attached_post_read_membership_change(
        self, files: _Files, after_read: AttachedDispatchSnapshotDAO, removed: bool
    ) -> None:
        """Removal returns membership_removed; a changed incarnation discards content as stale."""
        service, supplier, loader = await _attached_service(files=files)
        loader.progress_result = _progress(key=_CHILD_1)

        def _replace_batch() -> None:
            supplier.snapshot = after_read

        loader.during_progress_read = _replace_batch

        progress = await service.load_session_progress(key=_CHILD_1)

        assert (progress.membership_removed, progress.entries) == (removed, ())
        assert progress.notice == (_REMOVED_NOTICE if removed else _RETRY_NOTICE)
        assert progress.revision == ""

    async def test_attached_parent_dispatch_change_is_stale(self, files: _Files) -> None:
        """The parent row's incarnation is its dispatch; a new batch discards its content."""
        service, supplier, loader = await _attached_service(files=files)
        parent_key = _key(orchestrator_session_id=_OWNER, session_id=_OWNER, attached_dispatch_id=_DISPATCH_1)
        loader.progress_result = _progress(key=parent_key)

        def _replace_batch() -> None:
            supplier.snapshot = _attached(
                entries=(_entry(session_id="child-1"),), dispatch_id=_DISPATCH_2, sequence=2
            )

        loader.during_progress_read = _replace_batch

        progress = await service.load_session_progress(key=parent_key)

        assert (progress.membership_removed, progress.entries, progress.notice) == (True, (), _REMOVED_NOTICE)

    async def test_detached_matching_returns_loader_snapshot(self, files: _Files) -> None:
        """A fresh matching group re-read accepts the loader's result."""
        service, loader = await _detached_service(files=files, child=_child(session_id="child-a"))
        loader.progress_result = _progress(key=_DETACHED_CHILD)

        progress = await service.load_session_progress(key=_DETACHED_CHILD)

        assert progress == _progress(key=_DETACHED_CHILD)
        assert loader.group_reads == 2

    @pytest.mark.parametrize(
        ("post_read", "removed"),
        [
            (_group(), True),
            (
                _group(children=(_child(session_id="child-a").model_copy(update={"execution_id": _EXEC_B}),)),
                False,
            ),
            (_group(availability="unavailable"), False),
            (OSError("gone"), False),
            (_group(parent="someone-else"), False),
            (_group(fleet=False), False),
        ],
        ids=[
            "fleet_removed_child",
            "changed_incarnation",
            "unavailable_group",
            "unreadable",
            "wrong_parent",
            "missing_fleet",
        ],
    )
    async def test_detached_post_read_membership_change(
        self, files: _Files, post_read: object, removed: bool
    ) -> None:
        """Authoritative absence removes; unreadable or unavailable evidence never means removal."""
        service, loader = await _detached_service(files=files, child=_child(session_id="child-a"))
        loader.progress_result = _progress(key=_DETACHED_CHILD)
        loader.groups = [post_read]
        loader.group_reads = 0

        progress = await service.load_session_progress(key=_DETACHED_CHILD)

        assert (progress.membership_removed, progress.entries) == (removed, ())
        assert progress.notice == (_REMOVED_NOTICE if removed else _RETRY_NOTICE)

    async def test_detached_dismissal_during_read_removes(self, files: _Files) -> None:
        """An explicit dismissal while reading makes the late result a removal."""
        service, loader = await _detached_service(files=files, child=_child(session_id="child-a"))
        loader.progress_result = _progress(key=_DETACHED_CHILD)
        loader.during_progress_read = lambda: service.dismiss_group(workflow_id="wf-a")

        progress = await service.load_session_progress(key=_DETACHED_CHILD)

        assert (progress.membership_removed, progress.entries) == (True, ())

    async def test_no_history_attached_progress_is_unavailable(self) -> None:
        """Attached observation without history lists rows but reports progress unavailable."""
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1"),)))
        service: DetachedWorkflowAppService = _service(root=None, supplier=supplier)
        snapshot = await service.load_session_snapshot()

        progress = await service.load_session_progress(key=_CHILD_1)

        assert [row.key.session_id for row in snapshot.rows] == [_OWNER, "child-1"]
        assert (progress.availability, progress.membership_removed, progress.entries) == (
            "unavailable",
            False,
            (),
        )

    async def test_real_detached_progress_round_trip(self, files: _Files, no_full_history: None) -> None:
        """Real files: a legacy child's public capture flows through without full loads or writes."""
        await files.handle(handle=_HANDLE_A)
        legacy = SubAgentStatusDAO(
            task_id="task-legacy", session_id="child-legacy", status="running", prompt_preview="p"
        )
        files.fleet(parent=_ORCH_A, entries=[legacy], run_id=None)
        capture_dir: Path = OrchestrationLayout.child_capture_dir(
            history_root=files.root, parent_session_id=_ORCH_A, child_session_id="child-legacy"
        )
        capture_dir.mkdir(parents=True)
        (capture_dir / "stdout.jsonl").write_text(
            '{"kind": "text_delta", "delta": "public words"}\n', encoding="utf-8"
        )
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service.load_session_snapshot()
        before: dict[str, bytes] = _tree_bytes(root=files.root)

        progress = await service.load_session_progress(
            key=_key(orchestrator_session_id=_ORCH_A, session_id="child-legacy")
        )

        assert progress.membership_removed is False
        assert "public words" in " ".join(str(entry.model_dump()) for entry in progress.entries)
        assert progress.abort_target is None
        assert _tree_bytes(root=files.root) == before


class TestUnexpectedErrorsPropagate:
    """Only expected I/O/validation failures are retained; programming errors surface."""

    async def test_snapshot_programming_error_is_not_retention(self, files: _Files) -> None:
        """A RuntimeError from group discovery is raised, not shown as a stale group."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        service = _service(
            root=files.root, loader_factory=lambda **kwargs: _FakeLoader(groups=[RuntimeError("bug")])
        )

        with pytest.raises(RuntimeError, match="bug"):
            await service.load_session_snapshot()

    async def test_progress_programming_error_is_not_a_notice(self, files: _Files) -> None:
        """A RuntimeError from the progress read is raised, not a retry notice."""
        service, _, loader = await _attached_service(files=files)
        loader.progress_result = RuntimeError("bug")

        with pytest.raises(RuntimeError, match="bug"):
            await service.load_session_progress(key=_CHILD_1)


# ---------------------------------------------------------------------------
# Feature 98 a.1: reversible all-status list visibility
# ---------------------------------------------------------------------------

_HANDLE_DONE: WorkflowHandleDAO = _handle(
    workflow_id="wf-b", orchestrator_session_id=_ORCH_B, state="completed", hour=13
)
_OWNER_PARENT: WorkflowSessionKeyDAO = _key(
    orchestrator_session_id=_OWNER, session_id=_OWNER, attached_dispatch_id=_DISPATCH_1
)


class _ListFixture:
    """A mixed list: finished attached batch, running wf-a and finished wf-b."""

    def __init__(
        self,
        *,
        files: _Files,
        supplier: _Supplier,
        loaders: Optional[dict[str, _FakeLoader]] = None,
    ) -> None:
        """Inject recording adapters before the first public observation."""
        self.supplier = supplier
        self.loaders = loaders or {
            _OWNER: _FakeLoader(groups=[_group(parent=_OWNER)]),
            _ORCH_A: _FakeLoader(groups=[_group(parent=_ORCH_A, children=(_child(session_id="child-a"),))]),
            _ORCH_B: _FakeLoader(
                groups=[_group(parent=_ORCH_B, children=(_child(session_id="child-b", status="completed"),))]
            ),
        }
        self.service = _service(
            root=files.root,
            supplier=supplier,
            loader_factory=lambda **kwargs: self.loaders[kwargs["parent_session_id"]],
        )

    def dismiss(self, target_id: Optional[str] = None) -> WorkflowListVisibilityOutcomeDAO:
        """Apply the public local visibility command."""
        return self.service.apply_list_visibility(
            request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id=target_id)
        )

    def show(self) -> WorkflowListVisibilityOutcomeDAO:
        """Restore retained groups without observation I/O."""
        return self.service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))

    async def visible_groups(self) -> list[str]:
        """Refresh once and return the orchestrator ids of the visible groups, in order.

        Returns:
            list[str]: Distinct orchestrator ids of the fresh snapshot.
        """
        snapshot: WorkflowSessionSnapshotDAO = await self.service.load_session_snapshot()
        return list(dict.fromkeys(row.key.orchestrator_session_id for row in snapshot.rows))


async def _mixed_list(
    *, files: _Files, attached_statuses: tuple[str, ...] = ("completed", "failed")
) -> _ListFixture:
    """Seed real handles, recording loaders and an attached batch, then take one snapshot.

    Args:
        files (_Files): Real temporary root.
        attached_statuses (tuple[str, ...], optional): Attached child statuses.

    Returns:
        _ListFixture: Fixture whose last committed snapshot holds all three groups.
    """
    await files.handle(handle=_HANDLE_A)
    await files.handle(handle=_HANDLE_DONE)
    entries: tuple[SubAgentStatusDAO, ...] = tuple(
        _entry(session_id=f"child-{index}", status=status) for index, status in enumerate(attached_statuses)
    )
    supplier = _Supplier(snapshot=_attached(entries=entries))
    fixture = _ListFixture(files=files, supplier=supplier)
    assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]
    return fixture


class TestAllStatusVisibility:
    """Status and freshness never gate local hide/show."""

    @pytest.mark.parametrize(
        ("statuses", "availability"),
        [
            (("completed", "completed", "failed"), "available"),
            (("aborted", "aborted"), "available"),
            (("completed", "running"), "available"),
            (("running", "completed"), "available"),
            (("completed", "pending"), "available"),
            (("completed", "unknown"), "available"),
            (("stalled",), "available"),
            (("launching",), "available"),
            (("completed", "completed"), "stale"),
            (("completed", "unknown"), "unavailable"),
        ],
        ids=[
            "all-terminal",
            "aborted",
            "child-running",
            "parent-running",
            "child-pending",
            "unknown-status",
            "stalled-parent",
            "launching-parent",
            "stale-terminal",
            "unavailable-unknown",
        ],
    )
    async def test_classification(self, files: _Files, statuses: tuple[str, ...], availability: str) -> None:
        """All statuses are hideable; restoration preserves observed status and order."""
        await files.handle(handle=_HANDLE_A)
        group = _group(
            orchestrator_state=statuses[0],
            children=tuple(
                _child(session_id=f"child-{i}", status=status) for i, status in enumerate(statuses[1:])
            ),
        )
        loader = _FakeLoader(groups=[group])
        service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
        observed = await service.load_session_snapshot()
        if availability == "stale":
            service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
            observed = service.apply_list_visibility(
                request=WorkflowListVisibilityRequestDAO(action="show")
            ).snapshot
        if availability == "unavailable":
            loader.groups = [_group(availability="unavailable")]
            unavailable_service = _service(root=files.root, loader_factory=lambda **kwargs: loader)
            service = unavailable_service
            observed = await service.load_session_snapshot()
        assert all(row.availability == availability for row in observed.rows)
        hidden = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
        assert (hidden.changed_groups, hidden.snapshot.rows) == (1, ())
        reads = loader.group_reads
        restored = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
        assert [(r.key, r.status, r.task_text) for r in restored.snapshot.rows] == [
            (r.key, r.status, r.task_text) for r in observed.rows
        ]
        assert all(
            r.availability == ("unavailable" if availability == "unavailable" else "stale")
            for r in restored.snapshot.rows
        )
        assert loader.group_reads == reads


class TestListVisibility:
    """Public all-status reversible visibility, with no lifecycle side effects."""

    async def test_clear_all_hides_all_statuses(self, files: _Files) -> None:
        """All three groups hide without changing their execution status."""
        fixture = await _mixed_list(files=files)
        outcome = fixture.dismiss()
        assert (outcome.changed_groups, outcome.snapshot.rows) == (3, ())
        assert (
            outcome.rendered
            == "Hidden 3 workflow group(s). Execution continues. Use /workflows tui show to restore."
        )
        assert await fixture.visible_groups() == []
        assert fixture.show().changed_groups == 3
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    async def test_running_groups_are_hideable(self, files: _Files) -> None:
        """Running children do not gate visibility."""
        fixture = await _mixed_list(files=files, attached_statuses=("running",))
        fixture.loaders[_ORCH_B].groups = [
            _group(parent=_ORCH_B, children=(_child(session_id="child-b", status="running"),))
        ]
        await fixture.visible_groups()
        assert fixture.dismiss().changed_groups == 3
        assert await fixture.visible_groups() == []
        assert fixture.show().changed_groups == 3

    async def test_empty_list_has_nothing_to_clear(self) -> None:
        """A service with no committed rows (including no-history) clears nothing."""
        service: DetachedWorkflowAppService = _service(root=None)

        outcome = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))

        assert outcome.rendered == "No visible workflow groups to hide."

    async def test_attached_suppression_is_keyed_by_dispatch(self, files: _Files) -> None:
        """The hidden batch stays hidden for its dispatch and a new dispatch shows normally."""
        fixture: _ListFixture = await _mixed_list(files=files)
        fixture.dismiss(target_id=_OWNER)

        assert await fixture.visible_groups() == [_ORCH_A, _ORCH_B]
        assert await fixture.visible_groups() == [_ORCH_A, _ORCH_B]
        fixture.supplier.snapshot = _attached(
            entries=(_entry(session_id="child-new"),), dispatch_id=_DISPATCH_2, sequence=2
        )

        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    @pytest.mark.parametrize(
        "grown",
        [
            (
                _entry(session_id="child-0", status="completed"),
                _entry(session_id="step-2", execution_id=_EXEC_B),
            ),
            (_entry(session_id="child-0", status="completed", execution_id=_EXEC_B),),
        ],
        ids=["chain-step-registers", "new-incarnation"],
    )
    async def test_same_dispatch_new_member_stays_hidden_until_show(
        self, files: _Files, grown: tuple[SubAgentStatusDAO, ...]
    ) -> None:
        """A chain step or incarnation in a hidden dispatch remains hidden until show."""
        fixture: _ListFixture = await _mixed_list(files=files, attached_statuses=("completed",))
        assert fixture.dismiss(target_id=_OWNER).changed_groups == 1
        assert await fixture.visible_groups() == [_ORCH_A, _ORCH_B]

        fixture.supplier.snapshot = _attached(entries=grown)
        member: WorkflowSessionKeyDAO = _key(
            orchestrator_session_id=_OWNER, session_id=grown[-1].session_id, attached_dispatch_id=_DISPATCH_1
        )

        assert await fixture.visible_groups() == [_ORCH_A, _ORCH_B]
        restored = fixture.show()
        assert member in [row.key for row in restored.snapshot.rows]
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]
        fixture.supplier.snapshot = _attached(entries=(_entry(session_id="child-0", status="completed"),))
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    async def test_hidden_batch_judged_from_older_members_commits_grown_batch(self, files: _Files) -> None:
        """A pre-command refresh cannot publish grown membership visibly after hide."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="step-1", status="completed"),)))
        fixture = _ListFixture(files=files, supplier=supplier)
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A]
        supplier.snapshot = _attached(
            entries=(
                _entry(session_id="step-1", status="completed"),
                _entry(session_id="step-2", execution_id=_EXEC_B),
            )
        )
        blocking = _BlockingLoader(group=_group(parent=_ORCH_A, children=(_child(session_id="child-a"),)))
        fixture.loaders[_ORCH_A].next_loader = blocking
        task: asyncio.Task[WorkflowSessionSnapshotDAO] = asyncio.create_task(
            fixture.service.load_session_snapshot()
        )
        await blocking.entered.wait()

        fixture.dismiss(target_id=_OWNER)
        blocking.release.set()
        snapshot: WorkflowSessionSnapshotDAO = await task

        assert all(row.key.orchestrator_session_id != _OWNER for row in snapshot.rows)
        assert await fixture.visible_groups() == [_ORCH_A]
        assert [
            row.key.session_id
            for row in fixture.show().snapshot.rows
            if row.key.orchestrator_session_id == _OWNER
        ] == [_OWNER, "step-1", "step-2"]

    async def test_detached_suppression_survives_refresh_until_resume(self, files: _Files) -> None:
        """A hidden detached group stays hidden across polls; a successful resume re-shows it."""
        fixture: _ListFixture = await _mixed_list(files=files)
        outcome = fixture.dismiss(target_id="wf-b")

        assert outcome.changed_groups == 1
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A]
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A]
        fixture.service.resume_group(workflow_id="wf-b")

        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    @pytest.mark.parametrize("target_id", ["wf-b", _ORCH_B], ids=["workflow-id", "parent-session-id"])
    async def test_target_by_workflow_or_session_id(self, files: _Files, target_id: str) -> None:
        """A detached group is addressed by its workflow id or its parent session id."""
        fixture: _ListFixture = await _mixed_list(files=files)

        outcome = fixture.dismiss(target_id=target_id)

        assert outcome.changed_groups == 1
        assert (
            outcome.rendered
            == "Hidden 1 workflow group(s). Execution continues. Use /workflows tui show to restore."
        )
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A]

    @pytest.mark.parametrize("target_id", ["wf-a", _ORCH_A], ids=["workflow-id", "parent-session-id"])
    async def test_running_target_is_hidden(self, files: _Files, target_id: str) -> None:
        """Target aliases hide a running group without touching siblings."""
        fixture = await _mixed_list(files=files)
        assert fixture.dismiss(target_id=target_id).changed_groups == 1
        assert await fixture.visible_groups() == [_OWNER, _ORCH_B]
        assert fixture.show().changed_groups == 1
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    async def test_abort_pending_child_does_not_prevent_hide(self, files: _Files) -> None:
        """A running child (including pending abort) does not prevent hiding its group."""
        fixture: _ListFixture = await _mixed_list(files=files, attached_statuses=("completed", "running"))

        outcome = fixture.dismiss(target_id=_OWNER)

        assert outcome.changed_groups == 1
        assert await fixture.visible_groups() == [_ORCH_A, _ORCH_B]

    @pytest.mark.parametrize(
        "target_id", ["wf-zz", "child-a", "orch-x"], ids=["unknown", "child-id", "other"]
    )
    async def test_unknown_target(self, files: _Files, target_id: str) -> None:
        """An id naming no group in the list (a child id included) changes nothing."""
        fixture: _ListFixture = await _mixed_list(files=files)

        outcome = fixture.dismiss(target_id=target_id)

        assert outcome.rendered == f"No workflow {target_id} in this session list."
        assert await fixture.visible_groups() == [_OWNER, _ORCH_A, _ORCH_B]

    async def test_already_hidden_target_reports_unchanged(self, files: _Files) -> None:
        """Hiding the same retained group twice reports already hidden."""
        fixture: _ListFixture = await _mixed_list(files=files)
        fixture.dismiss(target_id="wf-b")

        outcome = fixture.dismiss(target_id="wf-b")

        assert outcome.rendered == "Workflow wf-b is already hidden."

    async def test_gateway_refuses_hidden_progress_but_retains_rows(self, files: _Files) -> None:
        """Hidden progress is refused without reads; show retains the observed rows."""
        fixture: _ListFixture = await _mixed_list(files=files)
        loader_b = fixture.loaders[_ORCH_B]

        fixture.dismiss(target_id=None)
        attached_progress = await fixture.service.load_session_progress(key=_OWNER_PARENT)
        detached_progress = await fixture.service.load_session_progress(
            key=_key(orchestrator_session_id=_ORCH_B, session_id="child-b")
        )

        assert await fixture.visible_groups() == []
        restored = fixture.show()
        assert {row.key.orchestrator_session_id for row in restored.snapshot.rows} == {
            _OWNER,
            _ORCH_A,
            _ORCH_B,
        }
        assert (attached_progress.membership_removed, detached_progress.membership_removed) == (True, True)
        assert loader_b.progress_rows == []  # type: ignore[attr-defined]

    async def test_hidden_attached_row_is_not_current_membership(self, files: _Files) -> None:
        """The gateway's attached re-read drops a hidden batch, so a stale key cannot resolve."""
        fixture: _ListFixture = await _mixed_list(files=files)
        fixture.dismiss(target_id=_OWNER)

        assert (await fixture.service.load_session_progress(key=_OWNER_PARENT)).membership_removed

    async def test_refresh_in_flight_cannot_resurrect_hidden_groups(self, files: _Files) -> None:
        """A snapshot that read hidden groups before the command still commits without them."""
        await files.handle(
            handle=_handle(workflow_id="wf-b", orchestrator_session_id=_ORCH_B, state="completed", hour=11)
        )
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1", status="completed"),)))
        fixture = _ListFixture(files=files, supplier=supplier)
        assert await fixture.visible_groups() == [_OWNER, _ORCH_B, _ORCH_A]
        blocking = _BlockingLoader(group=_group(parent=_ORCH_A, children=(_child(session_id="child-a"),)))
        fixture.loaders[_ORCH_A].next_loader = blocking
        task: asyncio.Task[WorkflowSessionSnapshotDAO] = asyncio.create_task(
            fixture.service.load_session_snapshot()
        )
        await blocking.entered.wait()

        fixture.dismiss(target_id=None)
        blocking.release.set()
        snapshot: WorkflowSessionSnapshotDAO = await task

        assert snapshot.rows == ()
        assert await fixture.visible_groups() == []

    async def test_close_drops_all_suppression(self, files: _Files) -> None:
        """Teardown and ``/new`` adoption drop both detached and attached suppression."""
        fixture: _ListFixture = await _mixed_list(files=files)
        fixture.dismiss(target_id=None)

        await fixture.service.close()

        assert (await fixture.service.load_session_snapshot()).rows == ()
        assert fixture.show().outcome == "unavailable"

    async def test_clearing_writes_nothing_and_calls_no_abort(
        self, files: _Files, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Acceptance 5: handle bytes and mtimes, store writes and abort seams are untouched."""
        await files.handle(handle=_HANDLE_A)
        await files.handle(handle=_HANDLE_DONE)
        store_writes: list[str] = []
        for method in ("write", "update_state", "reconcile", "delete"):
            if hasattr(WorkflowHandleStore, method):
                monkeypatch.setattr(
                    WorkflowHandleStore,
                    method,
                    lambda *_a, _m=method, **_k: store_writes.append(_m),  # type: ignore[misc]
                )
        abort_calls: list[ChildAbortRequestDAO] = []

        async def attached_abort(*, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
            """Fail if local visibility crosses the injected execution boundary."""
            abort_calls.append(request)
            raise AssertionError("visibility must not abort")

        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1", status="completed"),)))
        loaders = {_OWNER: _FakeLoader(groups=[_group(parent=_OWNER)]), **_seed_loaders()}
        service = DetachedWorkflowAppService(
            workflow_handle_store=WorkflowHandleStore(history_root=files.root, pid_alive=lambda pid: False),
            owner_session_id=_OWNER,
            attached_snapshot=supplier,
            history_store=FilesystemSessionHistoryStore(root=files.root),
            attached_abort=attached_abort,
            loader_factory=lambda **kwargs: loaders[kwargs["parent_session_id"]],
        )
        fixture = _ListFixture(files=files, supplier=supplier, loaders=loaders)
        fixture.service = service
        await fixture.visible_groups()
        before: dict[str, tuple[bytes, int]] = _tree_state(root=files.root)

        fixture.dismiss(target_id=None)
        await fixture.visible_groups()
        fixture.dismiss(target_id="wf-a")

        assert _tree_state(root=files.root) == before
        assert store_writes == []
        assert abort_calls == []
        assert fixture.show().changed_groups == 3


def _tree_state(*, root: Path) -> dict[str, tuple[bytes, int]]:
    """Snapshot every regular file's bytes and nanosecond mtime below ``root``.

    Args:
        root (Path): Directory to snapshot.

    Returns:
        dict[str, tuple[bytes, int]]: Relative path to (bytes, ``st_mtime_ns``).
    """
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
