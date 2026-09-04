"""Tests for ``DetachedWorkflowAppService`` (spec 57.a.5)."""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import AsyncMock

from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.tui.workflows.dao import HandleAdvanceOutcomeDAO, LiveWorkflowLabelDAO, ParsedFleetUpdateDAO
from src.tui.workflows.service import DetachedWorkflowAppService

_OWNER_SESSION_ID: str = "session-1234"


def _build_store(*, history_root: Path, pid_alive: bool = True) -> WorkflowHandleStore:
    """Build a workflow handle store with an injected liveness probe.

    Args:
        history_root (Path): Store root directory.
        pid_alive (bool): Fixed probe answer for every pid.

    Returns:
        WorkflowHandleStore: Store rooted at ``history_root``.
    """
    return WorkflowHandleStore(
        history_root=history_root,
        pid_alive=lambda pid: pid_alive,
    )


async def _write_handle(
    *,
    store: WorkflowHandleStore,
    workflow_id: str = "wf-1",
    state: WorkflowState = "launching",
) -> WorkflowHandleDAO:
    """Persist one handle owned by the test session.

    Args:
        store (WorkflowHandleStore): Target store.
        workflow_id (str): Handle workflow id.
        state (WorkflowState): Initial handle state.

    Returns:
        WorkflowHandleDAO: The persisted handle.
    """
    handle: WorkflowHandleDAO = WorkflowHandleDAO(
        workflow_id=workflow_id,
        owner_session_id=_OWNER_SESSION_ID,
        orchestrator_session_id="orch-1",
        pid=4242,
        brief="run the workflow",
        cwd="/tmp",
        state=state,
    )
    await store.write(handle=handle)
    return handle


def _build_service(*, store: WorkflowHandleStore) -> DetachedWorkflowAppService:
    """Build the app service bound to the test store.

    Args:
        store (WorkflowHandleStore): Store to bind.

    Returns:
        DetachedWorkflowAppService: Service for the owning test session.
    """
    return DetachedWorkflowAppService(
        workflow_handle_store=store,
        owner_session_id=_OWNER_SESSION_ID,
    )


def _lifecycle_payload(
    *,
    workflow_id: str = "wf-1",
    orchestrator_session_id: str = "orch-1",
) -> dict[str, object]:
    """Build a raw workflow lifecycle inbox payload.

    Args:
        workflow_id (str): Workflow identifier.
        orchestrator_session_id (str): Detached orchestrator session id.

    Returns:
        dict[str, object]: Raw payload as it arrives from the inbox.
    """
    return {
        "workflow_id": workflow_id,
        "orchestrator_session_id": orchestrator_session_id,
    }


class TestReconcileSnapshot:
    """Startup reconcile refreshes the live-state cache."""

    async def test_reconcile_replaces_cache_with_reconciled_states(self, tmp_path: Path) -> None:
        """A dead ``running`` workflow surfaces as ``stalled`` at mount."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="running")
        service: DetachedWorkflowAppService = _build_service(store=store)

        snapshot: dict[str, WorkflowState] = await service.reconcile_snapshot()

        assert snapshot == {"wf-1": "stalled"}

    async def test_reconcile_failure_keeps_cache_and_is_nonfatal(self, tmp_path: Path) -> None:
        """A failing store call leaves the cache untouched and never raises."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)
        service._workflow_states = {"wf-seeded": "running"}
        store.reconcile = AsyncMock(side_effect=OSError("disk gone"))

        snapshot: dict[str, WorkflowState] = await service.reconcile_snapshot()

        assert snapshot == {"wf-seeded": "running"}


class TestAdvanceFromInboxMessage:
    """Inbox lifecycle translation into durable state and UI effects."""

    async def test_fleet_update_updates_cache_without_handle_advance(self, tmp_path: Path) -> None:
        """Fleet notes refresh the cache but never mutate a workflow handle or UI effects."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="launching")
        service: DetachedWorkflowAppService = _build_service(store=store)
        payload: dict[str, object] = {
            "workflow_id": "wf-1",
            "entries": [{"task_id": "t1", "status": "running", "heartbeat_phase": "streaming"}],
            "live_count": 1,
        }

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_fleet_update",
            payload=payload,
        )

        assert outcome == HandleAdvanceOutcomeDAO(workflow_id="wf-1")
        assert service.fleet_update_for(workflow_id="wf-1") == ParsedFleetUpdateDAO(**payload)
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "launching"

    async def test_nonworkflow_kind_is_a_noop(self, tmp_path: Path) -> None:
        """Non-lifecycle kinds advance nothing and emit no effects."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="launching")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_phase_update",
            payload=_lifecycle_payload(),
        )

        assert outcome.effects == []
        assert outcome.advanced_handle is False
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "launching"

    async def test_started_advances_to_running_and_emits_launch_effect(self, tmp_path: Path) -> None:
        """``workflow_started`` advances the handle and asks for the visualizer."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="launching")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_started",
            payload=_lifecycle_payload(),
        )

        assert outcome.advanced_handle is True
        assert outcome.advanced_state == "running"
        assert outcome.workflow_id == "wf-1"
        assert [(effect.effect, effect.state) for effect in outcome.effects] == [
            ("launch_visualizer", "running")
        ]
        assert outcome.effects[0].orchestrator_session_id == "orch-1"
        assert all(effect.effect != "reset_launch_guard" for effect in outcome.effects)
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "running"

    async def test_terminal_advances_and_emits_reset_only_effect(self, tmp_path: Path) -> None:
        """Terminal notes reach terminal states and emit ONLY a guard-reset effect."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="running")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_completed",
            payload=_lifecycle_payload(),
        )

        assert outcome.advanced_handle is True
        assert outcome.advanced_state == "completed"
        assert [(effect.effect, effect.state) for effect in outcome.effects] == [
            ("reset_launch_guard", "completed")
        ]
        assert outcome.effects[0].orchestrator_session_id == "orch-1"
        assert all(effect.effect != "launch_visualizer" for effect in outcome.effects)

    async def test_failed_terminal_also_emits_reset_only_effect(self, tmp_path: Path) -> None:
        """``workflow_failed`` mirrors ``workflow_completed``: reset, never launch."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="running")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_failed",
            payload=_lifecycle_payload(),
        )

        assert outcome.advanced_handle is True
        assert outcome.advanced_state == "failed"
        assert [(effect.effect, effect.state) for effect in outcome.effects] == [
            ("reset_launch_guard", "failed")
        ]

    async def test_terminal_advance_without_orchestrator_id_emits_no_effects(self, tmp_path: Path) -> None:
        """A terminal advance without an orchestrator id still advances, effect-free."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="running")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_completed",
            payload={"workflow_id": "wf-1"},
        )

        assert outcome.advanced_handle is True
        assert outcome.advanced_state == "completed"
        assert outcome.effects == []

    async def test_missing_workflow_id_is_a_safe_noop(self, tmp_path: Path) -> None:
        """A lifecycle kind without a workflow id is ignored."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_started",
            payload={"orchestrator_session_id": "orch-1"},
        )

        assert outcome.effects == []
        assert outcome.advanced_handle is False
        assert outcome.workflow_id is None

    async def test_missing_orchestrator_id_advances_without_effects(self, tmp_path: Path) -> None:
        """A payload without an orchestrator id still advances the handle."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="launching")
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_started",
            payload={"workflow_id": "wf-1"},
        )

        assert outcome.advanced_handle is True
        assert outcome.effects == []

    async def test_store_failure_is_logged_nonfatal_and_emits_no_effects(self, tmp_path: Path) -> None:
        """Unknown workflows and illegal transitions never fail delivery."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)
        store.update_state = AsyncMock(side_effect=FileNotFoundError("wf-missing"))

        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind="workflow_started",
            payload=_lifecycle_payload(),
        )

        assert outcome.advanced_handle is False
        assert outcome.effects == []
        assert outcome.workflow_id == "wf-1"
        assert service.live_workflow_labels() == []

    async def test_state_cache_updates_on_advance(self, tmp_path: Path) -> None:
        """Successful advances feed the live-state cache."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        await _write_handle(store=store, state="launching")
        service: DetachedWorkflowAppService = _build_service(store=store)

        await service.advance_from_inbox_message(
            kind="workflow_started",
            payload=_lifecycle_payload(),
        )

        labels: List[LiveWorkflowLabelDAO] = service.live_workflow_labels()
        assert [(label.workflow_id, label.state) for label in labels] == [("wf-1", "running")]


class TestAdvanceFromLaunchResult:
    """Launch-result translation seeds the cache and reports the outcome."""

    def test_valid_launch_result_seeds_launching_and_reports_launched(self, tmp_path: Path) -> None:
        """A valid handle JSON seeds the cache and asks for the visualizer."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome = service.advance_from_launch_result(
            result_text=(
                '{"workflow_id": "wf-9a1b", "orchestrator_session_id": "orch-1", ' '"state": "launching"}'
            ),
        )

        assert outcome == "launched"
        labels: List[LiveWorkflowLabelDAO] = service.live_workflow_labels()
        assert [(label.workflow_id, label.state) for label in labels] == [("wf-9a1b", "launching")]

    def test_launch_result_without_workflow_id_seeds_nothing(self, tmp_path: Path) -> None:
        """A handle JSON without a workflow id still reports ``launched``."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome = service.advance_from_launch_result(
            result_text='{"orchestrator_session_id": "orch-1"}',
        )

        assert outcome == "launched"
        assert service.live_workflow_labels() == []

    def test_malformed_json_is_ignored(self, tmp_path: Path) -> None:
        """Malformed tool-result text is a safe no-op."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        assert service.advance_from_launch_result(result_text="not json {") == "ignored"

    def test_error_json_is_ignored(self, tmp_path: Path) -> None:
        """Error JSON never seeds the cache and never launches."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        outcome = service.advance_from_launch_result(
            result_text='{"error": "workflow cap reached"}',
        )

        assert outcome == "ignored"
        assert service.live_workflow_labels() == []


class TestLiveWorkflowLabels:
    """The live-label filter backing the exit hint."""

    async def test_only_live_states_are_labelled(self, tmp_path: Path) -> None:
        """Terminal and stalled workflows are filtered out of the exit hint."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)
        service._workflow_states = {
            "wf-1": "running",
            "wf-2": "completed",
            "wf-3": "launching",
            "wf-4": "stalled",
        }

        labels: List[LiveWorkflowLabelDAO] = service.live_workflow_labels()

        assert [(label.workflow_id, label.state) for label in labels] == [
            ("wf-1", "running"),
            ("wf-3", "launching"),
        ]

    def test_empty_cache_yields_no_labels(self, tmp_path: Path) -> None:
        """No workflows → no live labels."""
        store: WorkflowHandleStore = _build_store(history_root=tmp_path)
        service: DetachedWorkflowAppService = _build_service(store=store)

        assert service.live_workflow_labels() == []
