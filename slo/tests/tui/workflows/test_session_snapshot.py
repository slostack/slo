"""Owner-scoped session snapshots and the progress gateway (feature 94 a.2/a.3, ticket T06).

Categories: isolated unit (projection helpers), orchestration unit (recording
loader fakes for cache, ordering and failure cutoffs) and adapter integration
(real temporary handle, fleet, evidence, spawn-context and history files).
Every write resolves below the test's own ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO, dump_json_bytes
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildExecutionEvidenceDAO,
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
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    OrchestratorNodeDAO,
    WorkflowDataDAO,
    WorkflowVisualizerLoader,
)
from src.tui.workflows.dao import (
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.service import DetachedWorkflowAppService

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


def _key(*, orchestrator_session_id: str, session_id: str) -> WorkflowSessionKeyDAO:
    """Build one composite key.

    Args:
        orchestrator_session_id (str): Parent orchestrator.
        session_id (str): Row session.

    Returns:
        WorkflowSessionKeyDAO: Key.
    """
    return WorkflowSessionKeyDAO(orchestrator_session_id=orchestrator_session_id, session_id=session_id)


def _service(
    *,
    root: Optional[Path],
    supplier: Optional[_Supplier] = None,
    store: Optional[WorkflowHandleStore] = None,
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
    def test_precedence(self, statuses: tuple[str, ...], expected: str) -> None:
        """Pending/running wins; MINOR-2: failed beats aborted with no active child."""
        entries: tuple[SubAgentStatusDAO, ...] = tuple(
            _entry(session_id=f"child-{index}", status=status) for index, status in enumerate(statuses)
        )

        assert DetachedWorkflowAppService._batch_status(entries=entries) == expected


class TestProjectAttachedGroup:
    """``_project_attached_group``: registry membership only; enrichment never adds members."""

    @pytest.mark.parametrize(
        "attached",
        [AttachedDispatchSnapshotDAO.empty(), _attached(entries=())],
        ids=["no_dispatch", "admitted_empty_dispatch"],
    )
    async def test_empty_batch_projects_nothing(self, attached: AttachedDispatchSnapshotDAO) -> None:
        """No entries (including an admitted empty dispatch) yields no attached rows."""
        service: DetachedWorkflowAppService = _service(root=None)

        assert await service._project_attached_group(attached=attached) == ()

    async def test_no_history_uses_registry_previews(self) -> None:
        """Without history the parent and exact registry children use previews only."""
        service: DetachedWorkflowAppService = _service(root=None)
        attached = _attached(
            entries=(
                _entry(session_id="child-b", status="failed", execution_id=_EXEC_B),
                _entry(session_id="child-a", status="aborted", execution_id=_EXEC_A),
            )
        )

        rows = await service._project_attached_group(attached=attached)

        assert rows == (
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_OWNER, session_id=_OWNER),
                role="orchestrator",
                status="failed",
                dispatch_id=_DISPATCH_1,
                task_text="Orchestrator",
                task_text_complete=True,
            ),
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_OWNER, session_id="child-b"),
                role="child",
                task_id="task-child-b",
                execution_id=_EXEC_B,
                dispatch_id=_DISPATCH_1,
                status="failed",
                task_text="preview child-b",
                task_text_complete=False,
            ),
            WorkflowSessionRowDAO(
                key=_key(orchestrator_session_id=_OWNER, session_id="child-a"),
                role="child",
                task_id="task-child-a",
                execution_id=_EXEC_A,
                dispatch_id=_DISPATCH_1,
                status="aborted",
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
        service: DetachedWorkflowAppService = _service(root=files.root)
        attached = _attached(
            entries=(
                _entry(session_id="child-a", execution_id=_EXEC_A),
                _entry(session_id="child-b", execution_id=_EXEC_B),
            )
        )

        rows = await service._project_attached_group(attached=attached)

        assert [(row.key.session_id, row.task_text, row.task_text_complete) for row in rows] == [
            (_OWNER, "Orchestrator", True),
            ("child-a", "FULL TASK A", True),
            ("child-b", "preview child-b", False),
        ]

    async def test_enrichment_storage_failure_keeps_registry_rows(self, files: _Files) -> None:
        """An unreadable context store never removes or reorders registry rows."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        loader: AsyncMock = AsyncMock()
        loader.enrich_task_row = AsyncMock(side_effect=OSError("unreadable"))
        service._loaders[_OWNER] = loader
        attached = _attached(entries=(_entry(session_id="child-a"),))

        rows = await service._project_attached_group(attached=attached)

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
            FleetSnapshotDAO(orchestrator_session_id=parent, updated_at="2026-10-18T00:00:00+00:00")
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
    def test_untrusted_group_raises(self, group: WorkflowDataDAO) -> None:
        """A foreign or unavailable group raises the fixed error so retention runs."""
        service: DetachedWorkflowAppService = _service(root=None)

        with pytest.raises(ValueError, match="workflow observation unavailable"):
            service._project_group(handle=_HANDLE_A, group=group)

    def test_valid_group_maps_parent_then_children(self) -> None:
        """Parent carries handle brief and run identity; children copy public fields in order."""
        service: DetachedWorkflowAppService = _service(root=None)
        group = _group(
            children=(
                _child(session_id="child-b"),
                _child(session_id="child-a", status="completed", complete=False),
            )
        )

        rows = service._project_group(handle=_HANDLE_A, group=group)

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
    def test_parent_status_prefers_known_self_report(
        self, orchestrator_state: Optional[str], expected: str
    ) -> None:
        """An unknown or absent self-report preserves the handle state, never ``unknown``."""
        service: DetachedWorkflowAppService = _service(root=None)

        rows = service._project_group(handle=_HANDLE_A, group=_group(orchestrator_state=orchestrator_state))

        assert rows[0].status == expected


class _FakeLoader:
    """Recording loader standing in for ``WorkflowVisualizerLoader`` in orchestration units."""

    def __init__(self, *, groups: list[object]) -> None:
        """Seed the scripted group results.

        Args:
            groups (list[object]): Results (WorkflowDataDAO) or exceptions, consumed in order;
                the last one repeats.
        """
        self._groups: list[object] = groups
        self.group_reads: int = 0
        self.progress_rows: list[WorkflowSessionRowDAO] = []
        self.progress_result: Optional[object] = None
        self.during_progress_read: Callable[[], None] = lambda: None

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Return or raise the next scripted group.

        Returns:
            WorkflowDataDAO: Scripted group.
        """
        result: object = self._groups[min(self.group_reads, len(self._groups) - 1)]
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


class TestRetainFailedGroup:
    """``_load_group``/``_retain_failed_group``: unreadable files are never deletion."""

    async def test_first_failure_shows_one_unavailable_parent(self, files: _Files) -> None:
        """Without last-good rows a failed group becomes one unavailable parent row."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._loaders[_ORCH_A] = _FakeLoader(groups=[OSError("unreadable")])  # type: ignore[assignment]

        rows = await service._load_group(handle=_HANDLE_A)

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
        service: DetachedWorkflowAppService = _service(root=files.root)
        good = _group(children=(_child(session_id="child-a"),))
        service._loaders[_ORCH_A] = _FakeLoader(groups=[good, failure])  # type: ignore[assignment]

        fresh = await service._load_group(handle=_HANDLE_A)
        retained = await service._load_group(handle=_HANDLE_A)

        assert [row.availability for row in fresh] == ["available", "available"]
        assert retained == tuple(row.model_copy(update={"availability": "stale"}) for row in fresh)

    async def test_unavailable_group_retains_rows_instead_of_clearing_membership(self, files: _Files) -> None:
        """A loader-reported unavailable group never replaces membership with emptiness."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        good = _group(children=(_child(session_id="child-a"),))
        service._loaders[_ORCH_A] = _FakeLoader(groups=[good, _group(availability="unavailable")])  # type: ignore[assignment]

        await service._load_group(handle=_HANDLE_A)
        retained = await service._load_group(handle=_HANDLE_A)

        assert [(row.key.session_id, row.availability) for row in retained] == [
            (_ORCH_A, "stale"),
            ("child-a", "stale"),
        ]

    async def test_missing_fleet_retains_known_children_as_stale(self, files: _Files) -> None:
        """Without fleet evidence a vanished known child stays listed stale; fresh rows stay fresh."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        good = _group(children=(_child(session_id="child-a"),))
        without_fleet = _group(children=(_child(session_id="child-new"),), fleet=False)
        service._loaders[_ORCH_A] = _FakeLoader(groups=[good, without_fleet])  # type: ignore[assignment]

        await service._load_group(handle=_HANDLE_A)
        retained = await service._load_group(handle=_HANDLE_A)
        again = await service._load_group(handle=_HANDLE_A)

        assert [(row.key.session_id, row.availability) for row in retained] == [
            (_ORCH_A, "available"),
            ("child-new", "available"),
            ("child-a", "stale"),
        ]
        assert again == retained
        assert service._group_rows[_ORCH_A] == retained

    async def test_valid_fleet_replaces_child_membership(self, files: _Files) -> None:
        """A present, valid fleet that lacks a known child is authoritative removal."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        good = _group(children=(_child(session_id="child-a"),))
        service._loaders[_ORCH_A] = _FakeLoader(groups=[good, _group()])  # type: ignore[assignment]

        await service._load_group(handle=_HANDLE_A)
        replaced = await service._load_group(handle=_HANDLE_A)

        assert [(row.key.session_id, row.availability) for row in replaced] == [(_ORCH_A, "available")]


class TestReadOwnedHandles:
    """``_read_owned_handles``: bounded listing with retained membership on failure."""

    async def test_missing_store_reads_nothing(self) -> None:
        """A no-history service observes no detached handles and sets no notice."""
        service: DetachedWorkflowAppService = _service(root=None)

        assert await service._read_owned_handles() == ()
        assert service._observation_notice is None

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

        handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-early", "wf-late"]
        assert service._observation_notice is None

    @pytest.mark.parametrize("failure", [OSError("denied"), ValueError("workflow observation unavailable")])
    async def test_failure_retains_known_handles_with_notice(self, files: _Files, failure: Exception) -> None:
        """Permission or validation failure keeps prior membership and sets the fixed notice."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service._read_owned_handles()
        assert service._store is not None
        with patch.object(service._store, "list_observation", AsyncMock(side_effect=failure)):
            handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service._observation_notice == _LIST_UNAVAILABLE

    async def test_overflow_admits_no_partial_new_set(self, files: _Files) -> None:
        """AMBIGUOUS-2: the 257th handle keeps exactly the retained set, never a partial one."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service._read_owned_handles()
        workflows_dir: Path = OrchestrationLayout.workflows_dir(
            history_root=files.root, owner_session_id=_OWNER
        )
        for index in range(256):
            extra = _handle(workflow_id=f"wf-{index:04d}", orchestrator_session_id=f"orch-{index}")
            (workflows_dir / f"{extra.workflow_id}.json").write_text(
                extra.model_dump_json(), encoding="utf-8"
            )

        handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service._observation_notice == _LIST_UNAVAILABLE

    async def test_union_above_limit_admits_no_new_handle(self, files: _Files) -> None:
        """A valid 256-handle listing whose union with retained handles is 257 keeps the retained set."""
        path: Path = await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service._read_owned_handles()
        for sibling in path.parent.iterdir():
            sibling.unlink()
        for index in range(256):
            extra = _handle(workflow_id=f"wf-{index:04d}", orchestrator_session_id=f"orch-{index}")
            (path.parent / f"{extra.workflow_id}.json").write_text(extra.model_dump_json(), encoding="utf-8")
        assert service._store is not None
        assert len(await service._store.list_observation(owner_session_id=_OWNER)) == 256

        handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert list(service._handles) == ["wf-a"]
        assert service._observation_notice == _LIST_UNAVAILABLE

    @pytest.mark.parametrize("removal", ["handle_file", "directory"])
    async def test_missing_files_retain_known_handles(self, files: _Files, removal: str) -> None:
        """An emptied or absent directory with known handles is retention, not fresh empty."""
        path: Path = await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service._read_owned_handles()
        for sibling in path.parent.iterdir():
            sibling.unlink()
        if removal == "directory":
            path.parent.rmdir()

        handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service._observation_notice == _LIST_UNAVAILABLE

    async def test_fresh_success_clears_notice(self, files: _Files) -> None:
        """The next complete read clears the stale notice."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        assert service._store is not None
        with patch.object(service._store, "list_observation", AsyncMock(side_effect=OSError("denied"))):
            await service._read_owned_handles()

        handles = await service._read_owned_handles()

        assert [handle.workflow_id for handle in handles] == ["wf-a"]
        assert service._observation_notice is None


class TestAdoptDispatch:
    """``_adopt_dispatch`` invalidates only attached cached content on a new batch."""

    def test_same_dispatch_keeps_caches(self, files: _Files) -> None:
        """Polling the same batch reuses the owner loader."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._adopt_dispatch(attached=_attached(entries=()))
        owner_loader = service._loader(parent_session_id=_OWNER)

        service._adopt_dispatch(attached=_attached(entries=()))

        assert service._loader(parent_session_id=_OWNER) is owner_loader

    def test_new_dispatch_drops_only_attached_caches(self, files: _Files) -> None:
        """A new batch replaces the owner loader; detached group caches survive."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._adopt_dispatch(attached=_attached(entries=()))
        owner_loader = service._loader(parent_session_id=_OWNER)
        detached_loader = service._loader(parent_session_id=_ORCH_A)
        service._group_rows[_ORCH_A] = ()

        service._adopt_dispatch(attached=_attached(entries=(), dispatch_id=_DISPATCH_2, sequence=2))

        assert service._loader(parent_session_id=_OWNER) is not owner_loader
        assert service._loader(parent_session_id=_ORCH_A) is detached_loader
        assert service._group_rows == {_ORCH_A: ()}


_HANDLE_B: WorkflowHandleDAO = _handle(workflow_id="wf-b", orchestrator_session_id=_ORCH_B, hour=13)


def _seed_loaders(*, service: DetachedWorkflowAppService) -> dict[str, _FakeLoader]:
    """Install recording loaders for both detached groups.

    Args:
        service (DetachedWorkflowAppService): Service under test.

    Returns:
        dict[str, _FakeLoader]: Loaders keyed by orchestrator id.
    """
    loaders: dict[str, _FakeLoader] = {
        _ORCH_A: _FakeLoader(groups=[_group(parent=_ORCH_A, children=(_child(session_id="child-a"),))]),
        _ORCH_B: _FakeLoader(groups=[_group(parent=_ORCH_B)]),
    }
    service._loaders.update(loaders)  # type: ignore[arg-type]
    return loaders


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
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._handles = {"wf-a": _HANDLE_A, "wf-b": _HANDLE_B}
        loaders = _seed_loaders(service=service)
        for workflow_id in dismiss:
            service.dismiss_group(workflow_id=workflow_id)
        for workflow_id in resume:
            service.resume_group(workflow_id=workflow_id)
        loaders = _seed_loaders(service=service)

        rows = await service._project_detached_groups(handles=(_HANDLE_A, _HANDLE_B))

        assert [row.key.session_id for row in rows] == expected
        assert loaders[_ORCH_A].group_reads == (0 if _ORCH_A not in expected else 1)

    async def test_dismissal_drops_group_caches(self, files: _Files) -> None:
        """Dismissal removes the group's rows and loader so nothing stale lingers."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._handles = {"wf-a": _HANDLE_A}
        _seed_loaders(service=service)
        await service._project_detached_groups(handles=(_HANDLE_A,))

        service.dismiss_group(workflow_id="wf-a")

        assert _ORCH_A not in service._group_rows
        assert _ORCH_A not in service._loaders

    async def test_list_notice_marks_detached_rows_stale(self, files: _Files) -> None:
        """While the owner list is unavailable every retained detached row is stale."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        _seed_loaders(service=service)
        service._observation_notice = _LIST_UNAVAILABLE

        rows = await service._project_detached_groups(handles=(_HANDLE_A,))

        assert {row.availability for row in rows} == {"stale"}

    async def test_list_notice_keeps_unavailable_parent_unavailable(self, files: _Files) -> None:
        """Stale marking never weakens an unavailable retained parent row to stale."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        service._loaders[_ORCH_A] = _FakeLoader(groups=[OSError("unreadable")])  # type: ignore[assignment]
        service._observation_notice = _LIST_UNAVAILABLE

        rows = await service._project_detached_groups(handles=(_HANDLE_A,))

        assert [(row.key.session_id, row.availability) for row in rows] == [(_ORCH_A, "unavailable")]

    async def test_yields_between_serial_group_reads(self, files: _Files) -> None:
        """The service yields to the event loop after each group read."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        _seed_loaders(service=service)
        sleeper: AsyncMock = AsyncMock()

        with patch("src.tui.workflows.service.asyncio.sleep", sleeper):
            await service._project_detached_groups(handles=(_HANDLE_A, _HANDLE_B))

        assert [call.args for call in sleeper.await_args_list] == [(0,), (0,)]


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

    def test_duplicate_keys_keep_registry_precedence(self) -> None:
        """A duplicated composite key keeps its first (registry) row at its first position."""
        first = WorkflowSessionRowDAO(
            key=_key(orchestrator_session_id=_ORCH_A, session_id="child"),
            role="child",
            status="completed",
            task_text="registry",
            task_text_complete=False,
        )
        other = first.model_copy(update={"key": _key(orchestrator_session_id=_ORCH_A, session_id="other")})
        duplicate = first.model_copy(update={"status": "running", "task_text": "event guess"})

        rows = DetachedWorkflowAppService._unique_rows(rows=(first, other, duplicate))

        assert rows == (first, other)

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
        service: DetachedWorkflowAppService = _service(root=files.root)

        await service.load_session_snapshot()
        loader = service._loaders[_ORCH_A]
        await service.load_session_snapshot()

        assert service._loaders[_ORCH_A] is loader

    async def test_old_dispatch_event_cannot_restore_rows(self, files: _Files) -> None:
        """A refresh requested by late old-batch events still shows only the latest batch."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(
            snapshot=_attached(entries=(_entry(session_id="old-child", execution_id=_EXEC_A),))
        )
        service: DetachedWorkflowAppService = _service(root=files.root, supplier=supplier)
        await service.load_session_snapshot()
        detached_loader = service._loaders[_ORCH_A]
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
        assert service._loaders[_ORCH_A] is detached_loader

    async def test_missed_start_event_is_repaired_by_poll(self, files: _Files) -> None:
        """Without any start event, the next poll adopts the new batch and invalidates old keys."""
        supplier = _Supplier(
            snapshot=_attached(entries=(_entry(session_id="old-child", execution_id=_EXEC_A),))
        )
        service: DetachedWorkflowAppService = _service(root=files.root, supplier=supplier)
        await service.load_session_snapshot()
        owner_loader = service._loaders[_OWNER]
        supplier.snapshot = _attached(
            entries=(_entry(session_id="new-child", execution_id=_EXEC_B),),
            dispatch_id=_DISPATCH_2,
            sequence=2,
        )

        repaired: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        old_progress: SessionProgressSnapshotDAO = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="old-child")
        )

        assert [row.key.session_id for row in repaired.rows] == [_OWNER, "new-child"]
        assert service._loaders[_OWNER] is not owner_loader
        assert (old_progress.membership_removed, old_progress.entries) == (True, ())

    async def test_close_clears_caches_and_refuses_new_observation(self, files: _Files) -> None:
        """After close the service reads nothing and returns empty observation."""
        await files.handle(handle=_HANDLE_A)
        supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1"),)))
        service: DetachedWorkflowAppService = _service(root=files.root, supplier=supplier)
        await service.load_session_snapshot()
        reads_before_close: int = supplier.calls

        await service.close()
        snapshot: WorkflowSessionSnapshotDAO = await service.load_session_snapshot()
        progress: SessionProgressSnapshotDAO = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="child-1")
        )

        assert snapshot == WorkflowSessionSnapshotDAO()
        assert supplier.calls == reads_before_close
        assert (service._group_rows, service._loaders, service._handles, service._rows) == ({}, {}, {}, {})
        assert (progress.membership_removed, progress.entries) == (True, ())

    async def test_close_during_group_read_leaves_caches_empty(
        self, files: _Files, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A snapshot blocked in a group read when close runs returns empty, caches nothing
        and starts no further group read."""
        await files.handle(handle=_HANDLE_A)
        await files.handle(handle=_HANDLE_B)
        service: DetachedWorkflowAppService = _service(root=files.root)
        loader = _BlockingLoader(group=_group(children=(_child(session_id="child-a"),)))
        service._loaders[_ORCH_A] = loader  # type: ignore[assignment]

        async def _no_read_after_close(_self: WorkflowVisualizerLoader) -> WorkflowDataDAO:
            raise AssertionError("group read started after close")

        monkeypatch.setattr(WorkflowVisualizerLoader, "load_observation_group", _no_read_after_close)
        task: asyncio.Task[WorkflowSessionSnapshotDAO] = asyncio.create_task(service.load_session_snapshot())
        await loader.entered.wait()

        await service.close()
        loader.release.set()
        snapshot: WorkflowSessionSnapshotDAO = await task

        assert snapshot == WorkflowSessionSnapshotDAO()
        assert (service._group_rows, service._loaders, service._handles, service._rows) == ({}, {}, {}, {})

    async def test_close_during_handle_listing_admits_nothing(self, files: _Files) -> None:
        """A listing that completes after close does not repopulate the handle cache."""
        await files.handle(handle=_HANDLE_A)
        service: DetachedWorkflowAppService = _service(root=files.root)
        assert service._store is not None
        listing = await service._store.list_observation(owner_session_id=_OWNER)
        entered: asyncio.Event = asyncio.Event()
        release: asyncio.Event = asyncio.Event()

        async def _blocked_listing(**_kwargs: object) -> tuple[WorkflowHandleDAO, ...]:
            entered.set()
            await release.wait()
            return listing

        with patch.object(service._store, "list_observation", _blocked_listing):
            task: asyncio.Task[WorkflowSessionSnapshotDAO] = asyncio.create_task(
                service.load_session_snapshot()
            )
            await entered.wait()
            await service.close()
            release.set()
            snapshot: WorkflowSessionSnapshotDAO = await task

        assert snapshot == WorkflowSessionSnapshotDAO()
        assert (service._group_rows, service._loaders, service._handles, service._rows) == ({}, {}, {}, {})

    async def test_loader_requested_after_close_is_not_cached(self, files: _Files) -> None:
        """Late in-flight work may still get a transient loader, but never refills the cache."""
        service: DetachedWorkflowAppService = _service(root=files.root)
        await service.close()

        loader: WorkflowVisualizerLoader = service._loader(parent_session_id=_ORCH_A)

        assert isinstance(loader, WorkflowVisualizerLoader)
        assert service._loaders == {}


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


_CHILD_1: WorkflowSessionKeyDAO = _key(orchestrator_session_id=_OWNER, session_id="child-1")
_DETACHED_CHILD: WorkflowSessionKeyDAO = _key(orchestrator_session_id=_ORCH_A, session_id="child-a")


async def _attached_service(*, files: _Files) -> tuple[DetachedWorkflowAppService, _Supplier, _FakeLoader]:
    """Build a service whose latest snapshot holds attached child-1 (dispatch 1, exec A).

    Args:
        files (_Files): Real temporary root.

    Returns:
        tuple[DetachedWorkflowAppService, _Supplier, _FakeLoader]: Service, supplier, owner loader.
    """
    supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child-1", execution_id=_EXEC_A),)))
    service: DetachedWorkflowAppService = _service(root=files.root, supplier=supplier)
    await service.load_session_snapshot()
    loader = _FakeLoader(groups=[_group(parent=_OWNER)])
    service._loaders[_OWNER] = loader  # type: ignore[assignment]
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
    service: DetachedWorkflowAppService = _service(root=files.root)
    loader = _FakeLoader(groups=[_group(children=(child,))])
    service._loaders[_ORCH_A] = loader  # type: ignore[assignment]
    await service.load_session_snapshot()
    return service, loader


class TestLoadSessionProgress:
    """Service progress gateway: membership captured before, re-read after, every read."""

    async def test_unknown_key_is_removed_without_reading(self, files: _Files) -> None:
        """A key absent from the latest snapshot returns removal and reads nothing."""
        service, _, loader = await _attached_service(files=files)

        progress = await service.load_session_progress(
            key=_key(orchestrator_session_id=_OWNER, session_id="ghost")
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
                False,
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
        parent_key = _key(orchestrator_session_id=_OWNER, session_id=_OWNER)
        loader.progress_result = _progress(key=parent_key)

        def _replace_batch() -> None:
            supplier.snapshot = _attached(
                entries=(_entry(session_id="child-1"),), dispatch_id=_DISPATCH_2, sequence=2
            )

        loader.during_progress_read = _replace_batch

        progress = await service.load_session_progress(key=parent_key)

        assert (progress.membership_removed, progress.entries, progress.notice) == (False, (), _RETRY_NOTICE)

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
        loader._groups = [post_read]
        loader.group_reads = 0

        progress = await service.load_session_progress(key=_DETACHED_CHILD)

        assert (progress.membership_removed, progress.entries) == (removed, ())
        assert progress.notice == (_REMOVED_NOTICE if removed else _RETRY_NOTICE)

    async def test_detached_dismissal_during_read_removes(self, files: _Files) -> None:
        """An explicit dismissal while reading makes the late result a removal."""
        service, loader = await _detached_service(files=files, child=_child(session_id="child-a"))
        loader.progress_result = _progress(key=_DETACHED_CHILD)
        loader.during_progress_read = lambda: service._dismissed.add("wf-a")

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
        service._loaders[_ORCH_A] = _FakeLoader(groups=[RuntimeError("bug")])  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="bug"):
            await service.load_session_snapshot()

    async def test_progress_programming_error_is_not_a_notice(self, files: _Files) -> None:
        """A RuntimeError from the progress read is raised, not a retry notice."""
        service, _, loader = await _attached_service(files=files)
        loader.progress_result = RuntimeError("bug")

        with pytest.raises(RuntimeError, match="bug"):
            await service.load_session_progress(key=_CHILD_1)
