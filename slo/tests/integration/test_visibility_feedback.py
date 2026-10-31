"""Mounted visibility feedback through constructor-injected presentation boundaries."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest
from langchain_core.messages import AIMessage
from textual.pilot import Pilot
from textual.timer import Timer

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, ChildControlCapabilityDAO
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.workflows.dao import (
    SessionProgressSnapshotDAO,
    WorkflowListGroupKeyDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.progress_coordinator import (
    WorkflowProgressCoordinator,
    WorkflowProgressSink,
    WorkflowProgressSource,
)
from src.tui.workflow_visualizer_loader import HeadlessWorkflowVisualizerConfigDAO
from src.tui.workflows.service import (
    AttachedChildAbort,
    DetachedWorkflowAppService,
    WorkflowObservationLoader,
)
from tests.integration.test_workflow_visibility_slice import RunningBatchFactory
from tests.tui.authentication._painted_output import wait_for_condition
from tests.tui.workflows.test_visibility_loader_slice import GatedLoader, RecordingLoaderFactory, tree_state

PENDING = "Workflow visibility saved; display refresh pending."


class GatedPresentation:
    """Delegate actual paint, optionally fail one command paint at a public sink."""

    def __init__(self, *, delegate: WorkflowProgressSink) -> None:
        """Keep the mounted adapter and deterministic presentation barrier."""
        self.delegate = delegate
        self.fail = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def apply_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Fail only the armed paint, leaving subsequent refresh functional."""
        if self.fail:
            self.fail = False
            self.entered.set()
            await self.release.wait()
            raise RuntimeError("synthetic presentation failure")
        await self.delegate.apply_sessions(snapshot=snapshot)

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Delegate selection to the real mounted adapter."""
        return self.delegate.open_progress(key=key)

    def minimize_progress(self) -> None:
        """Delegate retirement."""
        self.delegate.minimize_progress()

    def apply_progress(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Delegate selected progress."""
        self.delegate.apply_progress(snapshot=snapshot)

    def membership_removed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Delegate membership loss."""
        self.delegate.membership_removed(key=key)

    def observation_failed(self) -> None:
        """Delegate ordinary observation feedback."""
        self.delegate.observation_failed()


class PresentationFactory:
    """Construct the real coordinator around its public sink protocol."""

    def __init__(self) -> None:
        """Record constructed owners for lifecycle assertions."""
        self.coordinators: list[WorkflowProgressCoordinator] = []
        self.sinks: list[GatedPresentation] = []

    def __call__(
        self,
        *,
        service: WorkflowProgressSource,
        sink: WorkflowProgressSink,
        schedule: Callable[[float, Callable[[], None]], Timer],
    ) -> WorkflowProgressCoordinator:
        """Wrap presentation only; keep real scheduling and visibility logic."""
        presentation = GatedPresentation(delegate=sink)
        coordinator = WorkflowProgressCoordinator(service=service, sink=presentation, schedule=schedule)
        self.sinks.append(presentation)
        self.coordinators.append(coordinator)
        return coordinator


def session_for_feedback(*, root: Path) -> SloAgentSession:
    """Build an offline session without altering runtime dependencies."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")]), cwd=str(root), tools=[]),
        workdir=root,
        session_id="feedback-owner",
        enable_history=False,
        config=SessionConfigDAO(workdir=root, model_name="claude-sonnet-4-6", enable_history=False),
    )


def feedback_lines(*, app: SloTUI) -> list[str]:
    """Read mounted transcript notices, not an intercepted output method."""
    assert app._adapter is not None
    return [text for text, _classes in app._adapter.lines]


async def wait_for_feedback_groups(
    *,
    pilot: Pilot,
    service: DetachedWorkflowAppService,
    observe_readiness: Optional[Callable[[bool], None]] = None,
) -> None:
    """Wait for the command's owner to observe both shared-parent workflows.

    Called by feedback journeys before capturing state or arming presentation failure.

    Args:
        pilot (Pilot): Pilot driving the mounted application.
        service (DetachedWorkflowAppService): Current owner's observation service.
        observe_readiness (Optional[Callable[[bool], None]], optional): Receive each actual
            predicate result synchronously, without changing it. Defaults to None.
    """
    # Snapshot rows deduplicate shared parent keys; require both group identities.
    expected: set[WorkflowListGroupKeyDAO] = {
        WorkflowListGroupKeyDAO(kind="detached", group_id=workflow_id) for workflow_id in ("wf-a", "wf-b")
    }

    def feedback_groups_are_committed() -> bool:
        """Report the polled readiness result before the waiter can complete.

        Returns:
            bool: Whether both committed workflow groups carry the shared-parent alias.
        """
        ready: bool = expected.issubset(service._list_groups) and all(
            service._list_groups[key].orchestrator_session_id == "shared-parent" for key in expected
        )
        if observe_readiness is not None:
            observe_readiness(ready)
        return ready

    await wait_for_condition(
        pilot=pilot,
        predicate=feedback_groups_are_committed,
        description="both owner-scoped shared-parent workflow groups are committed",
    )


async def test_feedback_readiness_waits_for_both_committed_groups(tmp_path: Path) -> None:
    """A held initial observation cannot certify alias readiness from existing files."""
    from tests.tui.workflows.test_session_snapshot import _Files, _entry, _handle

    root = tmp_path / "history"
    files = _Files(root=root)
    for workflow_id in ("wf-a", "wf-b"):
        await files.handle(
            handle=_handle(
                workflow_id=workflow_id,
                orchestrator_session_id="shared-parent",
                owner_session_id="feedback-owner",
            )
        )
    files.fleet(parent="shared-parent", entries=[_entry(session_id="child-b", execution_id="")], run_id=None)
    original_files = tree_state(root)
    history = FilesystemSessionHistoryStore(root=root)
    loader = GatedLoader(
        config=HeadlessWorkflowVisualizerConfigDAO(session_reference="shared-parent"), store=history
    )
    loader.block = True
    ordinary_loaders = RecordingLoaderFactory()
    services = RunningBatchFactory(detached_root=root)
    presentation = PresentationFactory()

    def build_loader(
        *, parent_session_id: str, history_store: SessionHistoryStoreProtocol
    ) -> WorkflowObservationLoader:
        """Gate shared-parent reads while delegating attached enrichment to real files."""
        if parent_session_id == "shared-parent":
            return loader
        return ordinary_loaders(parent_session_id=parent_session_id, history_store=history_store)

    def build_service(
        *,
        workflow_handle_store: Optional[WorkflowHandleStore],
        owner_session_id: str,
        attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO],
        history_store: Optional[SessionHistoryStoreProtocol],
        attached_abort: Optional[AttachedChildAbort],
        attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]],
    ) -> DetachedWorkflowAppService:
        """Compose real observation with a gated real-file loader at its constructor seam."""
        services.service = DetachedWorkflowAppService(
            workflow_handle_store=WorkflowHandleStore(history_root=root),
            owner_session_id=owner_session_id,
            attached_snapshot=services.snapshot,
            history_store=history,
            attached_abort=services.abort,
            attached_capability=attached_capability,
            loader_factory=build_loader,
        )
        return services.service

    app = SloTUI(
        session=session_for_feedback(root=tmp_path),
        workflow_service_factory=build_service,
        workflow_coordinator_factory=presentation,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await asyncio.wait_for(loader.entered.wait(), timeout=5)
        assert services.service is not None
        false_readiness = asyncio.Event()
        readiness_results: list[bool] = []

        def observe_readiness(ready: bool) -> None:
            """Record the real predicate result while the journey owns the read gate.

            Args:
                ready (bool): Unchanged result evaluated by the shared readiness helper.
            """
            readiness_results.append(ready)
            if not ready:
                false_readiness.set()

        readiness = asyncio.create_task(
            wait_for_feedback_groups(
                pilot=pilot, service=services.service, observe_readiness=observe_readiness
            )
        )
        try:
            await asyncio.wait_for(false_readiness.wait(), timeout=5)
            assert false_readiness.is_set(), "Readiness must be evaluated false before releasing the read"
            assert readiness_results and not any(readiness_results)
            assert not loader.release.is_set()
            assert services.service._list_groups == {}
            assert not readiness.done(), "Uncommitted workflow files are not command readiness"
        finally:
            loader.release.set()
            await asyncio.wait_for(readiness, timeout=5)
        assert readiness_results[-1] is True
        assert services.service._owner_session_id == "feedback-owner"
        assert {key.group_id for key in services.service._list_groups if key.kind == "detached"} == {
            "wf-a",
            "wf-b",
        }
        sink = presentation.sinks[0]
        before = services.service.current_list_snapshot()
        sink.fail = True
        command = asyncio.create_task(
            app.on_prompt_input_submitted(PromptInput.Submitted(text="/workflows tui dismiss shared-parent"))
        )
        try:
            await asyncio.wait_for(sink.entered.wait(), timeout=5)
        finally:
            sink.release.set()
            await asyncio.wait_for(command, timeout=5)
        lines = feedback_lines(app=app)
        assert lines.count("Workflow shared-parent is ambiguous; use its workflow ID.") == 1
        assert lines.count("No workflow shared-parent in this session list.") == 0
        assert lines.count(PENDING) == 0
        assert not any(line.startswith(("Shown ", "Hidden ")) for line in lines)
        assert services.service.current_list_snapshot() == before
        assert tree_state(root) == original_files
        assert services.abort_calls == []


@pytest.mark.parametrize("failure", ["false", "error", "replacement"])
@pytest.mark.parametrize(
    "refusal",
    ["", "unknown", "ambiguous", "unavailable"],
    ids=["changed", "unknown", "ambiguous", "unavailable"],
)
async def test_visibility_feedback_is_exact_and_owner_scoped(
    tmp_path: Path, failure: str, refusal: str
) -> None:
    """False/error acknowledge saved state once; retired-owner paint acknowledges nothing."""
    factory = PresentationFactory()
    from tests.tui.workflows.test_session_snapshot import _Files, _entry, _handle

    root = tmp_path / "history"
    files = _Files(root=root)
    for workflow_id in ("wf-a", "wf-b"):
        await files.handle(
            handle=_handle(
                workflow_id=workflow_id,
                orchestrator_session_id="shared-parent",
                owner_session_id="feedback-owner",
            )
        )
    files.fleet(parent="shared-parent", entries=[_entry(session_id="child-b", execution_id="")], run_id=None)
    services = RunningBatchFactory(detached_root=root)
    app = SloTUI(
        session=session_for_feedback(root=tmp_path),
        workflow_service_factory=services,
        workflow_coordinator_factory=factory,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        coordinator = factory.coordinators[0]
        sink = factory.sinks[0]
        assert services.service is not None
        await wait_for_feedback_groups(pilot=pilot, service=services.service)
        if refusal == "unavailable":
            await services.service.close()
        before = services.service.current_list_snapshot()
        replacement: Optional[asyncio.Task[None]] = None
        if failure == "false":
            await coordinator.close()
        else:
            sink.fail = True
        command = asyncio.create_task(
            app.on_prompt_input_submitted(
                PromptInput.Submitted(
                    text="/workflows tui dismiss"
                    + {"": "", "unknown": " unknown-id", "ambiguous": " shared-parent", "unavailable": ""}[
                        refusal
                    ]
                )
            )
        )
        if failure != "false":
            await asyncio.wait_for(sink.entered.wait(), timeout=5)
            if failure == "replacement":
                replacement = asyncio.create_task(
                    app.on_prompt_input_submitted(PromptInput.Submitted(text="/new"))
                )
                # Disposal nulls owner references before joining the blocked paint.
                from tests.tui.workflows.test_visibility_paint_barriers import checkpoint

                await checkpoint()
            sink.release.set()
        await asyncio.wait_for(command, timeout=5)
        if replacement is not None:
            await asyncio.wait_for(replacement, timeout=5)
        await pilot.pause()
        lines = feedback_lines(app=app)
        assert lines.count(PENDING) == (0 if failure == "replacement" or refusal else 1)
        expected_refusal = {
            "": "No workflow unknown-id in this session list.",
            "unknown": "No workflow unknown-id in this session list.",
            "ambiguous": "Workflow shared-parent is ambiguous; use its workflow ID.",
            "unavailable": "Workflow list unavailable in this session.",
        }[refusal]
        assert lines.count(expected_refusal) == int(bool(refusal) and failure != "replacement")
        if refusal and failure != "replacement":
            assert services.service.current_list_snapshot() == before
        assert not any(line.startswith("Shown ") for line in lines)
        assert not any(line.startswith("Hidden ") for line in lines)
        assert services.abort_calls == []
        if failure == "replacement":
            assert len(factory.coordinators) == 2
