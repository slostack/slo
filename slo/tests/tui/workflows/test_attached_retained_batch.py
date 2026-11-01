"""Public attached-dispatch retention and identity contracts for Feature 98."""

from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.tui.workflows.dao import WorkflowListVisibilityRequestDAO, WorkflowSessionKeyDAO
from src.tui.workflows.service import DetachedWorkflowAppService
from tests.tui.workflows.test_session_snapshot import (
    _DISPATCH_1,
    _DISPATCH_2,
    _EXEC_B,
    _OWNER,
    _Supplier,
    _attached,
    _entry,
)
from tests.tui.workflows.test_visibility_loader_slice import RecordingLoaderFactory, CountingLoader
from src.tui.workflow_visualizer_loader import HeadlessWorkflowVisualizerConfigDAO
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol


@pytest.mark.parametrize("change", ["grow", "replace", "remove", "empty"])
async def test_hidden_same_dispatch_uses_latest_membership(change: str) -> None:
    """Hidden membership stays live, including an empty batch that later gains members."""
    supplier = _Supplier(
        snapshot=_attached(entries=(_entry(session_id="child-a"), _entry(session_id="child-b")))
    )
    service = DetachedWorkflowAppService(
        workflow_handle_store=None, owner_session_id=_OWNER, attached_snapshot=supplier
    )
    await service.load_session_snapshot()
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    entries = {
        "grow": (_entry(session_id="child-a"), _entry(session_id="child-b"), _entry(session_id="child-c")),
        "replace": (_entry(session_id="child-a", execution_id=_EXEC_B),),
        "remove": (_entry(session_id="child-b"),),
        "empty": (),
    }[change]
    supplier.snapshot = _attached(entries=entries)
    assert (await service.load_session_snapshot()).rows == ()
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert shown.changed_groups == 1
    assert [(row.key.session_id, row.execution_id) for row in shown.snapshot.rows if row.role == "child"] == [
        (entry.session_id, entry.execution_id) for entry in entries
    ]
    if change == "empty":
        assert shown.snapshot.rows == ()
        supplier.snapshot = _attached(entries=(_entry(session_id="child-new"),))
        assert [row.key.session_id for row in (await service.load_session_snapshot()).rows] == [
            _OWNER,
            "child-new",
        ]
    await service.close()


def test_attached_scope_participates_in_key_equality_and_hash() -> None:
    """Identical session IDs in distinct batches remain separate selectable rows."""
    first = WorkflowSessionKeyDAO(
        orchestrator_session_id=_OWNER, session_id="child", attached_dispatch_id=_DISPATCH_1
    )
    second = WorkflowSessionKeyDAO(
        orchestrator_session_id=_OWNER, session_id="child", attached_dispatch_id=_DISPATCH_2
    )
    legacy = WorkflowSessionKeyDAO(orchestrator_session_id=_OWNER, session_id="child")
    assert len({first, second, legacy}) == 3


async def test_retained_batch_keeps_original_detail_without_loader_or_pool(tmp_path: Path) -> None:
    """Restored old and current batches coexist without borrowing new progress authority."""
    supplier = _Supplier(snapshot=_attached(entries=(_entry(session_id="child"),)))
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    loader = CountingLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference=_OWNER), store=history
    )
    constructions: list[str] = []

    def factory(*, parent_session_id: str, history_store: SessionHistoryStoreProtocol) -> CountingLoader:
        """Record construction and use real counted reads for the current batch."""
        constructions.append(parent_session_id)
        return loader

    from src.agents.slo_agent.orchestrator.dao import ChildAbortRequestDAO, ChildAbortOutcomeDAO

    abort_calls: list[ChildAbortRequestDAO] = []

    async def abort(*, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Record forbidden execution calls without touching any process."""
        abort_calls.append(request)
        raise AssertionError("retained detail must not abort")

    service = DetachedWorkflowAppService(
        workflow_handle_store=None,
        owner_session_id=_OWNER,
        attached_snapshot=supplier,
        attached_abort=abort,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        loader_factory=factory,
    )
    first = await service.load_session_snapshot()
    service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
    replacement = _entry(session_id="child", execution_id=_EXEC_B)
    replacement.prompt_preview = "new task"
    supplier.snapshot = _attached(entries=(replacement,), dispatch_id=_DISPATCH_2, sequence=2)
    current = await service.load_session_snapshot()
    shown = service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
    assert len(shown.snapshot.rows) == 4
    assert len({row.key for row in shown.snapshot.rows}) == 4
    assert [row.key for row in shown.snapshot.rows[:2]] == [row.key for row in current.rows]
    parent, child = shown.snapshot.rows[2:]
    assert parent.retained_batch is True
    assert child.availability == "stale"
    assert child.key == first.rows[1].key
    before_reads = loader.reads
    before_supplier_reads = supplier.calls
    before_constructions = list(constructions)
    progress = await service.load_session_progress(key=child.key)
    assert constructions == before_constructions
    assert loader.reads == before_reads
    assert supplier.calls == before_supplier_reads
    assert progress.key == child.key
    assert progress.execution_id == child.execution_id
    assert progress.dispatch_id == _DISPATCH_1
    assert progress.task_text == first.rows[1].task_text
    assert progress.task_text_complete == first.rows[1].task_text_complete
    assert progress.status == child.status
    assert progress.availability == "unavailable"
    assert progress.notice == f"Retained batch; live progress unavailable. Dispatch: {_DISPATCH_1}"
    assert progress.entries == ()
    assert progress.revision == progress.source_generation == ""
    assert progress.final_read_complete is False
    assert progress.abort_target is None
    assert progress.membership_removed is False
    assert abort_calls == []
    await service.close()
    assert abort_calls == []
