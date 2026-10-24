"""Nested detached capability cutoffs through the existing control adapter seam."""

import asyncio
from pathlib import Path
from typing import ClassVar, Optional

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortStore
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, ChildControlCapabilityDAO
from src.tui.workflows.dao import WorkflowListVisibilityRequestDAO
from src.tui.workflows.service import DetachedWorkflowAppService
from tests.tui.workflows.test_child_abort_confirmation import _Detached, _OWNER


class ObservedCapability(ChildControlCapabilityDAO):
    """Record authority consumption on the value returned by the injected adapter."""

    authority_reads: ClassVar[list[str]] = []

    def __getattribute__(self, name: str) -> object:
        """Record only public capability authority fields, not validation internals."""
        if name in {"accepting", "owner_session_id", "orchestrator_session_id", "run_id"}:
            type(self).authority_reads.append(name)
        return super().__getattribute__(name)


class GatedControlStore(ChildAbortStore):
    """Read actual temp persistence, then gate delivery of its capability value."""

    def __init__(self, *, history_root: Path, orchestrator_session_id: str) -> None:
        """Bind the real adapter and deterministic delivery events."""
        super().__init__(history_root=history_root, orchestrator_session_id=orchestrator_session_id)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def load_capability(self) -> Optional[ChildControlCapabilityDAO]:
        """Pause after reading bytes but before the service consumes authority."""
        capability = await super().load_capability()
        assert capability is not None
        observed = ObservedCapability.model_validate(capability.model_dump())
        ObservedCapability.authority_reads.clear()
        self.entered.set()
        await self.release.wait()
        return observed


@pytest.mark.parametrize("transition", ["hide", "hide-show", "reproject", "workflow-reprojection"])
async def test_detached_capability_delivery_stops_before_authority_consumption(
    tmp_path: Path, transition: str
) -> None:
    """Invalidated progress does not even consume capability authority after its await."""
    world = _Detached(root=tmp_path / "history")
    await world.seed()
    control = GatedControlStore(history_root=world.root, orchestrator_session_id="orch-a")

    def factory(*, history_root: Path, orchestrator_session_id: str) -> ChildAbortStore:
        """Return the gated real control adapter at the existing public seam."""
        assert history_root == world.root
        assert orchestrator_session_id == "orch-a"
        return control

    service = DetachedWorkflowAppService(
        workflow_handle_store=world.handles,
        owner_session_id=_OWNER,
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
        history_store=FilesystemSessionHistoryStore(root=world.root),
        control_store_factory=factory,
    )
    initial = await service.load_session_snapshot()
    assert len(initial.rows) == 2
    progress = asyncio.create_task(service.load_session_progress(key=world.key))
    await asyncio.wait_for(control.entered.wait(), timeout=5)
    try:
        if transition == "workflow-reprojection":
            from datetime import timedelta

            original = await world.handles.read(owner_session_id=_OWNER, workflow_id="wf-a")
            assert original is not None
            await world.handles.write(
                handle=original.model_copy(
                    update={
                        "workflow_id": "wf-earlier",
                        "started_at": original.started_at - timedelta(seconds=1),
                    }
                )
            )
            projected = await service.load_session_snapshot()
            assert {row.workflow_id for row in projected.rows} == {"wf-earlier"}
        else:
            service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="dismiss"))
        if transition in {"hide-show", "reproject"}:
            service.apply_list_visibility(request=WorkflowListVisibilityRequestDAO(action="show"))
        if transition == "reproject":
            await service.load_session_snapshot()
    finally:
        control.release.set()
    result = await asyncio.wait_for(progress, timeout=5)
    assert result.abort_target is None
    assert result.entries == ()
    assert ObservedCapability.authority_reads == []
    await service.close()
    await world.service.close()
