"""Real-file retention through the public visibility and loader seams."""

import asyncio
import json
import weakref
from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, ChildControlCapabilityDAO
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowHandleDAO
from src.tui.workflow_visualizer_loader import (
    HeadlessWorkflowVisualizerConfigDAO,
    WorkflowVisualizerLoader,
    WorkflowDataDAO,
)
from src.tui.workflows.dao import (
    WorkflowListVisibilityRequestDAO,
    WorkflowSessionRowDAO,
    SessionProgressSnapshotDAO,
)
from src.tui.workflows.service import DetachedWorkflowAppService
from tests.tui.workflows.test_session_snapshot import (
    _Files,
    _entry,
    _handle,
    _Supplier,
    _attached,
    _OWNER,
    _RUN,
    _EXEC_A,
    _DISPATCH_1,
    _DISPATCH_2,
)


@pytest.mark.parametrize("previously_observed", [False, True])
@pytest.mark.parametrize("missing", ["index", "mapping"])
async def test_lost_modern_identity_never_admits_legacy_progress(
    tmp_path: Path, missing: str, previously_observed: bool
) -> None:
    """Service and shared loader refuse orphaned modern detail and recover read-only."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    files.running(
        parent="orch-a",
        child="child-a",
        execution_id=_EXEC_A,
        prompt="Task: Inspect original assignment\n",
        dispatch_id=_DISPATCH_1,
    )
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id=_EXEC_A)])
    capture = root / "orch-a" / "children" / "child-a" / "stdout.jsonl"
    capture.write_text('{"kind":"text_delta","delta":"Captured original execution"}\n')
    # The fixture's running helper deliberately has no capture identity. Bind the
    # actual temp-owned capture so recovery can prove readable modern output.
    from src.agents.slo_agent.orchestrator.dao import StdoutCaptureIdentityDAO

    evidence_path = capture.parent / "execution.v1.json"
    evidence = json.loads(evidence_path.read_text())
    metadata = capture.stat()
    evidence["stdout_identity"] = StdoutCaptureIdentityDAO(
        device=metadata.st_dev, inode=metadata.st_ino
    ).model_dump()
    evidence_path.write_text(json.dumps(evidence))
    index = root / "orch-a" / "execution-index.v1.json"
    original = index.read_bytes()
    from tests.tui.workflows.test_session_snapshot import _service

    service = _service(root=root)
    history = FilesystemSessionHistoryStore(root=root)
    loader = WorkflowVisualizerLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="orch-a"), store=history
    )
    if previously_observed:
        observed_files = tree_state(root)
        row = (await service.load_session_snapshot()).rows[1]
        assert row.execution_id == _EXEC_A
        assert row.task_text_complete
        for result in (
            await service.load_session_progress(key=row.key),
            await loader.load_session_progress(row=row),
        ):
            assert result.availability == "available"
            assert result.entries
            assert result.task_text == "Task: Inspect original assignment\n"
            assert result.task_text_complete
        assert tree_state(root) == observed_files
    if missing == "index":
        index.unlink()
    else:
        payload = json.loads(original)
        payload["executions"].pop("child-a")
        index.write_text(json.dumps(payload))
    before = tree_state(root)
    if not previously_observed:
        row = (await service.load_session_snapshot()).rows[1]
        assert row.execution_id == ""
        assert row.task_summary == "Task summary unavailable — open details"
        assert not row.task_text_complete
    progress = await service.load_session_progress(key=row.key)
    direct = await loader.load_session_progress(row=row)
    group = await loader.load_observation_group()
    for result in (progress, direct):
        assert result.entries == ()
        assert result.abort_target is None
    assert progress.availability == ("stale" if previously_observed else "unavailable")
    assert not progress.task_text_complete
    assert direct.availability == "unavailable"
    if previously_observed:
        assert direct.task_text == row.task_text
    else:
        assert not direct.task_text_complete
        assert "Inspect original" not in direct.task_text
    assert not group.children[0].task_text_complete
    assert group.children[0].task_summary == "Task summary unavailable — open details"
    assert tree_state(root) == before
    index.write_bytes(original)
    restored_files = tree_state(root)
    recovered = (await service.load_session_snapshot()).rows[1]
    assert recovered.execution_id == _EXEC_A
    assert recovered.task_text_complete
    assert recovered.task_text == "Task: Inspect original assignment\n"
    recovered_group = await loader.load_observation_group()
    assert recovered_group.children[0].execution_id == _EXEC_A
    assert recovered_group.children[0].task_text_complete
    for result in (
        await service.load_session_progress(key=recovered.key),
        await loader.load_session_progress(row=row if previously_observed else recovered),
    ):
        assert result.availability == "available"
        assert result.task_text == recovered.task_text
        assert result.task_text_complete
        assert result.entries
    assert tree_state(root) == restored_files
    await service.close()


@pytest.mark.parametrize("shared_visible", [False, True])
async def test_hidden_loader_lifetime_follows_committed_groups(tmp_path: Path, shared_visible: bool) -> None:
    """Hidden observations release progress adapters unless a visible group still needs one."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    if shared_visible:
        await files.handle(handle=_handle(workflow_id="wf-b", orchestrator_session_id="orch-a"))
    files.context(parent="orch-a", child="child-a", prompt="Task: Inspect original assignment")
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    capture = root / "orch-a" / "children" / "child-a" / "stdout.jsonl"
    capture.write_text('{"kind":"text_delta","delta":"Original progress buffer"}\n')
    references: list[weakref.ReferenceType[CountingLoader]] = []

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> CountingLoader:
        """Record only weak references so ownership is tested rather than prolonged."""
        loader = CountingLoader(
            config=HeadlessWorkflowVisualizerConfigDAO(session_reference=parent_session_id),
            store=history_store,
        )
        references.append(weakref.ref(loader))
        return loader

    from tests.tui.workflows.test_session_snapshot import _service

    service = _service(root=root, loader_factory=factory)
    row = (await service.load_session_snapshot()).rows[1]
    assert (await service.load_session_progress(key=row.key)).entries
    service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id="wf-a")
    )
    await service.load_session_snapshot()
    assert (references[0]() is not None) == shared_visible
    await service.load_session_snapshot()
    assert sum(reference() is not None for reference in references) == int(shared_visible)
    constructions = len(references)
    before = tree_state(root)
    reads = tuple(reference().reads if reference() is not None else None for reference in references)
    restored = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert restored.snapshot.rows
    assert len(references) == constructions
    assert tuple(reference().reads if reference() is not None else None for reference in references) == reads
    assert tree_state(root) == before
    await service.load_session_snapshot()
    assert len(references) == constructions + int(not shared_visible)
    assert (await service.load_session_progress(key=row.key)).entries
    await service.close()
    assert all(reference() is None for reference in references)


class CountingHandleStore(WorkflowHandleStore):
    """Count the real bounded ownership reads without replacing persistence."""

    def __init__(self, *, history_root: Path) -> None:
        """Bind the test-owned root and initialize the read counter."""
        super().__init__(history_root=history_root)
        self.reads: int = 0

    async def list_observation(self, *, owner_session_id: str) -> tuple[WorkflowHandleDAO, ...]:
        """Count and delegate the actual bounded handle read."""
        self.reads += 1
        return await super().list_observation(owner_session_id=owner_session_id)


class CountingLoader(WorkflowVisualizerLoader):
    """Count real group, detail and progress reads at the injected boundary."""

    reads: int = 0

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Count and delegate bounded group reads."""
        self.reads += 1
        return await super().load_observation_group()

    async def load_session_progress(self, *, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
        """Count and delegate bounded progress reads."""
        self.reads += 1
        return await super().load_session_progress(row=row)


def tree_state(root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Snapshot files, directories and links without following fixture symlinks."""
    result: dict[str, tuple[bytes, int, int]] = {}
    for path in (root, *root.rglob("*")):
        metadata = path.lstat()
        content = b""
        if path.is_symlink():
            content = str(path.readlink()).encode()
        elif path.is_file():
            content = path.read_bytes()
        result[str(path.relative_to(root))] = (content, metadata.st_mode, metadata.st_mtime_ns)
    return result


@pytest.mark.parametrize("modern", [False, True], ids=["legacy", "execution-index"])
@pytest.mark.parametrize(
    "mutation",
    [
        "fleet-missing",
        "fleet-corrupt",
        "childdir-missing",
        "handle-missing",
        "handle-corrupt",
        "symlink",
        "overbudget",
        "omission",
    ],
)
async def test_restored_membership_distinguishes_loss_from_removal(
    tmp_path: Path, modern: bool, mutation: str
) -> None:
    """Lost evidence retains exact membership; only an owned valid omission removes it."""
    root = tmp_path / "history"
    files = _Files(root=root)
    handle = _handle(workflow_id="wf-a", orchestrator_session_id="orch-a")
    handle_path = await files.handle(handle=handle)
    entry = _entry(session_id="child-a", execution_id=_EXEC_A if modern else "")
    files.fleet(parent="orch-a", entries=[entry], run_id=_RUN if modern else None)
    if modern:
        files.running(
            parent="orch-a",
            child="child-a",
            execution_id=_EXEC_A,
            prompt="Original task detail",
            dispatch_id=_DISPATCH_1,
        )
    else:
        files.context(parent="orch-a", child="child-a", prompt="Original task detail")
    store = CountingHandleStore(history_root=root)
    history = FilesystemSessionHistoryStore(root=root)
    loader = CountingLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="orch-a"), store=history
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> CountingLoader:
        """Return the counting real adapter for the only admitted parent."""
        assert parent_session_id == "orch-a"
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=store,
        owner_session_id=_OWNER,
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=history,
        loader_factory=factory,
    )
    initial = await service.load_session_snapshot()
    assert [row.key.session_id for row in initial.rows] == ["orch-a", "child-a"]
    before = tree_state(root)
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    assert tree_state(root) == before
    fleet = root / "orch-a" / "fleet.json"
    fleet_bytes = fleet.read_bytes()
    extra_handles: list[Path] = []
    childdir = root / "orch-a" / "children" / "child-a"
    backup = tmp_path / "child-backup"
    if mutation == "fleet-missing":
        fleet.unlink()
    elif mutation == "fleet-corrupt":
        fleet.write_text("invalid", encoding="utf-8")
    elif mutation == "childdir-missing":
        childdir.rename(backup)
    elif mutation == "handle-missing":
        handle_path.unlink()
    elif mutation == "handle-corrupt":
        handle_path.write_text("invalid", encoding="utf-8")
    elif mutation == "symlink":
        outside = tmp_path / "outside-fleet.json"
        outside.write_bytes(fleet_bytes)
        fleet.unlink()
        fleet.symlink_to(outside)
    elif mutation == "overbudget":
        for index in range(256):
            extra_handles.append(
                await files.handle(
                    handle=_handle(workflow_id=f"wf-extra-{index}", orchestrator_session_id=f"other-{index}")
                )
            )
    if mutation in {"handle-missing", "handle-corrupt", "overbudget", "omission"}:
        files.fleet(parent="orch-a", entries=[], run_id=_RUN if modern else None)
    if mutation == "fleet-missing":
        (childdir / "stdout.jsonl").write_text(
            '{"kind":"text_delta","delta":"must not adopt stale output"}\n', encoding="utf-8"
        )
    changed = tree_state(root)
    reads_before_show = (store.reads, loader.reads)
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert (store.reads, loader.reads) == reads_before_show
    assert shown.snapshot.rows == tuple(
        row.model_copy(update={"availability": "stale"}) for row in initial.rows
    )
    assert tree_state(root) == changed
    observed = await service.load_session_snapshot()
    progress = await service.load_session_progress(key=initial.rows[1].key)
    assert tree_state(root) == changed
    if mutation == "omission":
        assert [row.key.session_id for row in observed.rows] == ["orch-a"]
        assert progress.membership_removed is True
        repeated = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
        assert [row.key.session_id for row in repeated.snapshot.rows] == ["orch-a"]
    else:
        assert [row.key for row in observed.rows] == [row.key for row in initial.rows]
        assert observed.rows[1].availability == "stale"
        assert progress.membership_removed is False
        assert progress.entries == () and progress.abort_target is None
    assert (
        service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show")).changed_groups
        == 0
    )
    if mutation == "symlink":
        fleet.unlink()
    fleet.write_bytes(fleet_bytes)
    if backup.exists():
        backup.rename(childdir)
    await files.handle(handle=handle)
    for path in extra_handles:
        path.unlink()
    recovered = await service.load_session_snapshot()
    assert [row.key for row in recovered.rows] == [row.key for row in initial.rows]
    assert recovered.rows[1].availability == "available"
    await service.close()


@pytest.mark.parametrize("collision", [False, True])
async def test_exact_workflow_precedes_alias_and_owner_selects_all_batches(
    tmp_path: Path, collision: bool
) -> None:
    """Exact workflow wins; an owner alias spans attached batches unless detached collides."""
    root = tmp_path / "history"
    files = _Files(root=root)
    supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child"),)))
    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id=_OWNER,
        attached_snapshot=supplier,
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    await service.load_session_snapshot()
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    supplier.snapshot = _attached(entries=(_entry(session_id="child"),), dispatch_id=_DISPATCH_2, sequence=2)
    await service.load_session_snapshot()
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    await files.handle(
        handle=_handle(workflow_id="wf-alias", orchestrator_session_id=_OWNER if collision else "wf-other")
    )
    await files.handle(handle=_handle(workflow_id="wf-other", orchestrator_session_id="third"))
    initial = await service.load_session_snapshot()
    exact = service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id="wf-other")
    )
    assert exact.changed_groups == 1
    assert all(row.workflow_id != "wf-other" for row in exact.snapshot.rows)
    assert any(row.workflow_id == "wf-alias" for row in exact.snapshot.rows)
    before = service.current_list_snapshot()
    owner = service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id=_OWNER)
    )
    if collision:
        assert owner.outcome == "ambiguous"
        assert owner.snapshot == before
    else:
        assert owner.changed_groups == 2
        assert not any(row.key.attached_dispatch_id for row in owner.snapshot.rows)
    assert len(initial.rows) >= 6
    await service.close()


async def test_exact_workflow_id_equal_to_owner_precedes_attached_alias(tmp_path: Path) -> None:
    """An exact detached workflow ID wins even when it equals the attached owner."""
    owner = "wf-owner"
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(workflow_id=owner, owner_session_id=owner, orchestrator_session_id="other-parent")
    )
    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id=owner,
        attached_snapshot=_Supplier(snapshot=_attached(entries=(_entry(session_id="child"),))),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    original = await service.load_session_snapshot()
    result = service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id=owner)
    )
    assert result.changed_groups == 1
    assert result.snapshot.rows == tuple(row for row in original.rows if row.key.attached_dispatch_id)
    assert len(result.snapshot.rows) == 2
    await service.close()


async def test_pending_durable_identity_uses_one_visibility_record(tmp_path: Path) -> None:
    """A durable display signal and later observation share one reversible record."""
    root = tmp_path / "history"
    files = _Files(root=root)
    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id=_OWNER,
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    before = tree_state(root)
    service.dismiss_group(workflow_id="wf-a")
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert shown.changed_groups == 1 and shown.snapshot.rows == ()
    assert tree_state(root) == before
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    observed = await service.load_session_snapshot()
    assert len(observed.rows) == 2
    before = tree_state(root)
    assert (
        service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show")).changed_groups
        == 0
    )
    service.dismiss_group(workflow_id="wf-a")
    assert service.current_list_snapshot().rows == ()
    service.resume_group(workflow_id="wf-a")
    assert [row.key for row in service.current_list_snapshot().rows] == [row.key for row in observed.rows]
    assert (
        service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show")).changed_groups
        == 0
    )
    assert tree_state(root) == before
    await service.close()
    assert service.current_list_snapshot().rows == ()
    assert (
        service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show")).outcome
        == "unavailable"
    )


class GatedLoader(WorkflowVisualizerLoader):
    """Pause a real observation after capturing its file evidence."""

    def __init__(
        self, *, config: HeadlessWorkflowVisualizerConfigDAO, store: FilesystemSessionHistoryStore
    ) -> None:
        """Bind the real adapter and a disabled observation barrier."""
        super().__init__(config=config, store=store)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def load_observation_group(self) -> WorkflowDataDAO:
        """Capture real evidence before allowing the caller to publish it."""
        result = await super().load_observation_group()
        if self.block:
            self.entered.set()
            await self.release.wait()
        return result


class GatedProgress(GatedLoader):
    """Hold a captured real progress read and count later authority reads."""

    async def load_session_progress(self, *, row: WorkflowSessionRowDAO) -> SessionProgressSnapshotDAO:
        """Capture content before a visibility mutation."""
        result = await super().load_session_progress(row=row)
        self.entered.set()
        await self.release.wait()
        return result


class RecordingLoaderFactory:
    """Construct real bounded loaders and record construction, never replace reads."""

    def __init__(self) -> None:
        """Start with no constructed adapters."""
        self.parents: list[str] = []

    def __call__(
        self, *, parent_session_id: str, history_store: SessionHistoryStoreProtocol
    ) -> WorkflowVisualizerLoader:
        """Build the production adapter over the injected temporary history store."""
        self.parents.append(parent_session_id)
        return WorkflowVisualizerLoader(
            config=HeadlessWorkflowVisualizerConfigDAO(session_reference=parent_session_id),
            store=history_store,
        )


def file_state(root: Path) -> dict[str, tuple[bytes, int, int]]:
    """Read bytes, modes and modification times without altering fixture files."""
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


async def test_detached_show_retains_missing_fleet_without_writing(tmp_path: Path) -> None:
    """Restore offline immediately, then retain lost membership through a real read."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    factory = RecordingLoaderFactory()
    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id="owner-1",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=FilesystemSessionHistoryStore(root=root),
        loader_factory=factory,
    )
    initial = await service.load_session_snapshot()
    assert len(initial.rows) == 2
    before = file_state(root)
    hidden = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    assert hidden.snapshot.rows == ()
    assert hidden.rendered == (
        "Hidden 1 workflow group(s). Execution continues. Use /workflows tui show to restore."
    )
    assert file_state(root) == before
    (root / "orch-a" / "fleet.json").unlink()
    missing = file_state(root)
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert [row.key for row in shown.snapshot.rows] == [row.key for row in initial.rows]
    assert all(row.availability == "stale" for row in shown.snapshot.rows)
    assert shown.rendered == "Shown 1 previously hidden workflow group(s). Retained rows may be stale."
    assert factory.parents == ["orch-a"]
    refreshed = await service.load_session_snapshot()
    assert [row.key for row in refreshed.rows] == [row.key for row in initial.rows]
    assert refreshed.rows[1].availability == "stale"
    assert file_state(root) == missing
    (root / "orch-a" / "fleet.json").write_text("invalid-json", encoding="utf-8")
    corrupted = file_state(root)
    unavailable = await service.load_session_snapshot()
    assert [row.key for row in unavailable.rows] == [row.key for row in initial.rows]
    assert all(row.availability == "stale" for row in unavailable.rows)
    assert file_state(root) == corrupted
    repeated = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert repeated.rendered == "No hidden workflow groups to show."
    await service.close()


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
async def test_failed_handle_admission_preserves_complete_membership(tmp_path: Path, failure: str) -> None:
    """Untrusted ownership must not admit a changed but readable fleet."""
    root = tmp_path / "history"
    files = _Files(root=root)
    handle = _handle(workflow_id="wf-a", orchestrator_session_id="orch-a")
    path = await files.handle(handle=handle)
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id="owner-1",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    initial = await service.load_session_snapshot()
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    if failure == "missing":
        path.unlink()
    else:
        path.write_text("invalid", encoding="utf-8")
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-b", execution_id="")], run_id=None)
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    before = file_state(root)
    observed = await service.load_session_snapshot()
    assert [row.key for row in observed.rows] == [row.key for row in initial.rows]
    assert all(row.availability == "stale" for row in observed.rows)
    assert file_state(root) == before
    progress = await service.load_session_progress(key=initial.rows[1].key)
    assert progress.membership_removed is False
    assert progress.entries == ()
    assert progress.abort_target is None
    await files.handle(handle=handle)
    recovered = await service.load_session_snapshot()
    assert [row.key.session_id for row in recovered.rows] == ["orch-a", "child-b"]
    await service.close()


async def test_candidate_does_not_publish_before_commit(tmp_path: Path) -> None:
    """A pre-show read cannot publish newly discovered ownership or freshness."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    loader = GatedLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="orch-a"),
        store=FilesystemSessionHistoryStore(root=root),
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> GatedLoader:
        """Return the gated real adapter for this single-parent fixture."""
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id="owner-1",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=FilesystemSessionHistoryStore(root=root),
        loader_factory=factory,
    )
    initial = await service.load_session_snapshot()
    loader.block = True
    pending = asyncio.create_task(service.load_session_snapshot())
    await asyncio.wait_for(loader.entered.wait(), timeout=5)
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    loader.release.set()
    result = await asyncio.wait_for(pending, timeout=5)
    assert result == shown.snapshot
    assert [row.key for row in result.rows] == [row.key for row in initial.rows]
    assert all(row.availability == "stale" for row in result.rows)
    assert all(row.availability == "available" for row in (await service.load_session_snapshot()).rows)
    await service.close()


class GatedEnrichment(WorkflowVisualizerLoader):
    """Record real child enrichment and hold its captured result."""

    def __init__(self, *, store: FilesystemSessionHistoryStore) -> None:
        """Bind one temp-owned history adapter."""
        super().__init__(config=HeadlessWorkflowVisualizerConfigDAO(session_reference=_OWNER), store=store)
        self.calls: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def enrich_task_row(self, *, row: WorkflowSessionRowDAO) -> WorkflowSessionRowDAO:
        """Read matching task detail, then gate the first child."""
        self.calls.append(row.key.session_id)
        result = await super().enrich_task_row(row=row)
        if self.block and row.key.session_id == "child-a":
            self.entered.set()
            await self.release.wait()
        return result


async def test_show_stops_old_observation_before_next_child_enrichment(tmp_path: Path) -> None:
    """Invalidation at a child await cuts off remaining enrichment reads."""
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    loader = GatedEnrichment(store=history)
    supplier = _Supplier(
        snapshot=_attached(entries=(_entry(session_id="child-a"), _entry(session_id="child-b")))
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> GatedEnrichment:
        """Return this fixture's real gated adapter."""
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=None,
        owner_session_id=_OWNER,
        attached_snapshot=supplier,
        history_store=history,
        loader_factory=factory,
    )
    await service.load_session_snapshot()
    loader.calls.clear()
    loader.block = True
    pending = asyncio.create_task(service.load_session_snapshot())
    await asyncio.wait_for(loader.entered.wait(), timeout=5)
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    loader.release.set()
    result = await asyncio.wait_for(pending, timeout=5)
    assert loader.calls == ["child-a"]
    assert result == shown.snapshot
    await service.close()


@pytest.mark.parametrize("show", [False, True])
async def test_progress_captured_before_visibility_change_is_refused(tmp_path: Path, show: bool) -> None:
    """A hidden selection is removed; restored selection cannot adopt old progress."""
    root = tmp_path / "history"
    files = _Files(root=root)
    await files.handle(handle=_handle(workflow_id="wf-a", orchestrator_session_id="orch-a"))
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    history = FilesystemSessionHistoryStore(root=root)
    loader = GatedProgress(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="orch-a"), store=history
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> GatedProgress:
        """Return the gated real progress adapter."""
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id="owner-1",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=history,
        loader_factory=factory,
    )
    initial = await service.load_session_snapshot()
    pending = asyncio.create_task(service.load_session_progress(key=initial.rows[1].key))
    await asyncio.wait_for(loader.entered.wait(), timeout=5)
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    if show:
        service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    loader.release.set()
    progress = await asyncio.wait_for(pending, timeout=5)
    assert progress.membership_removed is (not show)
    assert progress.entries == ()
    assert progress.abort_target is None
    if show:
        assert progress.availability == "stale"
    await service.close()


async def test_attached_replacement_during_captured_progress_is_stale(tmp_path: Path) -> None:
    """A same-scope replacement invalidates captured content before later authority reads."""
    from tests.tui.workflows.test_child_abort_confirmation import _Attached, _EXEC_B

    world = _Attached(root=tmp_path / "history")
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    loader = GatedProgress(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference=_OWNER), store=history
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> GatedProgress:
        """Use the gated real-file progress reader."""
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=None,
        owner_session_id=_OWNER,
        attached_snapshot=world._snapshot,
        history_store=history,
        loader_factory=factory,
        attached_abort=world.abort,
        attached_capability=lambda: world.capability,
    )
    await service.load_session_snapshot()
    pending = asyncio.create_task(service.load_session_progress(key=world.key))
    await asyncio.wait_for(loader.entered.wait(), timeout=5)
    world.execution_id = _EXEC_B
    loader.release.set()
    result = await asyncio.wait_for(pending, timeout=5)
    assert result.availability == "stale"
    assert result.entries == ()
    assert result.abort_target is None
    assert result.membership_removed is False
    await service.close()


async def test_attached_execution_replacement_during_capability_never_restores_abort(tmp_path: Path) -> None:
    """The last capability boundary cannot publish a target for a replaced registry execution."""
    from tests.tui.workflows.test_child_abort_confirmation import _Attached, _EXEC_B

    world = _Attached()

    def capability() -> ChildControlCapabilityDAO:
        """Replace registry evidence at the final control boundary."""
        world.execution_id = _EXEC_B
        return world.capability

    service = DetachedWorkflowAppService(
        workflow_handle_store=None,
        owner_session_id=_OWNER,
        attached_snapshot=world._snapshot,
        attached_abort=world.abort,
        attached_capability=capability,
    )
    await service.load_session_snapshot()
    progress = await service.load_session_progress(key=world.key)
    assert progress.abort_target is None
    assert progress.availability == "stale"
    assert progress.entries == ()
    await service.close()


async def test_shared_parent_targeting_and_captured_progress_use_projected_workflow(tmp_path: Path) -> None:
    """Exact IDs hide one record; ambiguous parent refuses; old projected authority is discarded."""
    root = tmp_path / "history"
    files = _Files(root=root)
    for workflow_id in ("wf-a", "wf-b"):
        await files.handle(handle=_handle(workflow_id=workflow_id, orchestrator_session_id="orch-a"))
    files.fleet(parent="orch-a", entries=[_entry(session_id="child-a", execution_id="")], run_id=None)
    history = FilesystemSessionHistoryStore(root=root)
    loader = GatedProgress(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="orch-a"), store=history
    )

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> GatedProgress:
        """Return the captured real reader for the shared parent."""
        return loader

    service = DetachedWorkflowAppService(
        workflow_handle_store=WorkflowHandleStore(history_root=root),
        owner_session_id="owner-1",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=history,
        loader_factory=factory,
    )
    initial = await service.load_session_snapshot()
    assert len(initial.rows) == 2
    assert {row.workflow_id for row in initial.rows} == {"wf-a"}
    for target, expected in (("orch-a", "ambiguous"), ("child-a", "unknown"), ("wf-foreign", "unknown")):
        outcome = service.apply_list_visibility(
            request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id=target)
        )
        assert outcome.outcome == expected
        assert service.current_list_snapshot() == initial
    pending = asyncio.create_task(service.load_session_progress(key=initial.rows[1].key))
    await asyncio.wait_for(loader.entered.wait(), timeout=5)
    hidden = service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id="wf-a")
    )
    assert hidden.changed_groups == 1
    assert {row.workflow_id for row in hidden.snapshot.rows} == {"wf-b"}
    loader.release.set()
    old = await asyncio.wait_for(pending, timeout=5)
    assert old.availability == "stale"
    assert old.entries == () and old.abort_target is None
    # The next public read must authorize wf-b, not the first handle for orch-a.
    fresh = await service.load_session_progress(key=initial.rows[1].key)
    assert fresh.membership_removed is False
    again = service.apply_list_visibility(
        request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id="wf-a")
    )
    assert again.rendered == "Workflow wf-a is already hidden."
    assert (
        service.apply_list_visibility(
            request=WorkflowListVisibilityRequestDAO(action="dismiss", target_id="wf-b")
        ).snapshot.rows
        == ()
    )
    await service.close()
