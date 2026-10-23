"""First runnable Feature 98 journey; real app/service/coordinator, no execution."""

from pathlib import Path

import pytest
from collections.abc import Callable
from typing import Optional

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.tui.workflows.test_session_snapshot import _Files, _entry, _handle
from tests.tui.workflows.test_visibility_loader_slice import file_state, tree_state
from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    ChildControlCapabilityDAO,
    SubAgentStatusDAO,
    ChildAbortRequestDAO,
    ChildAbortOutcomeDAO,
)
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.tui.app import PromptInput, SloTUI
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.service import AttachedChildAbort, DetachedWorkflowAppService


class RunningBatchFactory:
    """Inject the pool observation boundary, never replace the visibility service."""

    def __init__(self, *, detached_root: Optional[Path] = None) -> None:
        """Keep one running batch and retain the composed owner for assertions."""
        self.detached_root: Optional[Path] = detached_root
        self.batch = AttachedDispatchSnapshotDAO(
            dispatch_id="11111111-1111-4111-8111-111111111111",
            dispatch_sequence=1,
            entries=(
                SubAgentStatusDAO(
                    task_id="audit",
                    session_id="child-a",
                    status="running",
                    prompt_preview="Audit parser boundaries",
                ),
            ),
        )
        self.service: Optional[DetachedWorkflowAppService] = None
        self.abort_calls: list[ChildAbortRequestDAO] = []

    async def abort(self, *, request: ChildAbortRequestDAO) -> ChildAbortOutcomeDAO:
        """Record any forbidden execution call without signaling a process."""
        self.abort_calls.append(request)
        raise AssertionError("visibility must never abort execution")

    def snapshot(self) -> AttachedDispatchSnapshotDAO:
        """Return unchanged execution evidence throughout display commands."""
        return self.batch

    def __call__(
        self,
        *,
        workflow_handle_store: Optional[WorkflowHandleStore],
        owner_session_id: str,
        attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO],
        history_store: Optional[SessionHistoryStoreProtocol],
        attached_abort: Optional[AttachedChildAbort],
        attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]],
    ) -> DetachedWorkflowAppService:
        """Compose the real service using a controlled registry supplier."""
        self.service = DetachedWorkflowAppService(
            workflow_handle_store=(
                WorkflowHandleStore(history_root=self.detached_root)
                if self.detached_root is not None
                else workflow_handle_store
            ),
            owner_session_id=owner_session_id,
            attached_snapshot=self.snapshot,
            history_store=(
                FilesystemSessionHistoryStore(root=self.detached_root)
                if self.detached_root is not None
                else history_store
            ),
            attached_abort=self.abort,
            attached_capability=attached_capability,
        )
        return self.service


@pytest.mark.parametrize("theme", ["slo-dark", "slo-default"])
@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
async def test_running_group_dismiss_show_reclaims_and_restores_mounted_rows(
    tmp_path: Path, theme: str, size: tuple[int, int]
) -> None:
    """Enter commands through the real editor; hiding never alters the running batch."""
    root = tmp_path / "detached-history"
    files = _Files(root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-detached",
            orchestrator_session_id="detached-parent",
            owner_session_id="visibility-owner",
        )
    )
    files.fleet(
        parent="detached-parent", entries=[_entry(session_id="detached-child", execution_id="")], run_id=None
    )
    factory = RunningBatchFactory(detached_root=root)
    await files.handle(
        handle=_handle(
            workflow_id="wf-completed",
            orchestrator_session_id="completed-parent",
            owner_session_id="visibility-owner",
            state="completed",
        )
    )
    files.fleet(
        parent="completed-parent",
        entries=[_entry(session_id="completed-child", status="completed", execution_id="")],
        run_id=None,
    )
    original_files = tree_state(root)
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="ok")]),
            model_name="claude-sonnet-4-6",
            cwd=str(tmp_path),
            tools=[],
        ),
        workdir=tmp_path,
        session_id="visibility-owner",
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-sonnet-4-6", enable_history=False),
    )
    app = SloTUI(session=session, workflow_service_factory=factory)
    async with app.run_test(size=size) as pilot:
        app.theme = theme
        await pilot.pause()
        panel = app.query_one(SubAgentFleetPanel)
        editor = app.query_one(PromptInput)
        assert app.focused is editor
        original = tuple(row.row for row in panel.query(SubAgentFleetRow))
        assert len(original) == 6
        from tests.tui.authentication._painted_output import assert_widget_painted

        assert_widget_painted(app=app, widget=panel, text="Ongoing workflow tasks")
        assert panel.size.height > 0
        transcript_height = app.query_one("#transcript-scroll").size.height
        import sys
        from types import FrameType

        forbidden_calls: list[str] = []

        def record_forbidden(frame: FrameType, event: str, arg: object) -> None:
            """Observe forbidden boundaries without replacing any dependency."""
            module = str(frame.f_globals.get("__name__", ""))
            if event == "call" and (
                module == "src.auth.credential_resolver"
                or (module == "src.tui.visualizer_launcher" and frame.f_code.co_name == "launch")
                or module == "src.agents.slo_agent.orchestrator.relaunch"
            ):
                forbidden_calls.append(f"{module}.{frame.f_code.co_name}")

        previous_profile = sys.getprofile()
        sys.setprofile(record_forbidden)
        try:
            editor.text = "/workflows tui dismiss"
            await pilot.press("enter")
            await pilot.pause()
            assert panel.size.height == 0
            await pilot.resize_terminal(width=50, height=18)
            await pilot.pause()
            assert panel.size.height == 0
            assert "Resize" not in "".join(strip.text for strip in app.screen._compositor.render_strips())
            await pilot.resize_terminal(width=size[0], height=size[1])
            await pilot.pause()
            assert app.query_one("#transcript-scroll").size.height > transcript_height
            assert app.focused is editor
            assert factory.snapshot().entries[0].status == "running"
            assert tree_state(root) == original_files
            editor.text = "/clear"
            await pilot.press("enter")
            await pilot.pause()
            assert panel.size.height == 0
            assert factory.service is not None
            assert factory.service.current_list_snapshot().rows == ()
            assert tree_state(root) == original_files
            (root / "detached-parent" / "fleet.json").unlink()
            offline_files = tree_state(root)
            editor.text = "/workflows tui show"
            await pilot.press("enter")
            await pilot.pause()
            restored = tuple(row.row for row in panel.query(SubAgentFleetRow))
            assert [row.key for row in restored] == [row.key for row in original]
            assert [row.task_text for row in restored] == [row.task_text for row in original]
            assert tree_state(root) == offline_files
        finally:
            sys.setprofile(previous_profile)
        assert forbidden_calls == []
        assert factory.abort_calls == []
        assert panel.size.height > 0
        assert app.focused is editor
        assert factory.snapshot().entries[0].status == "running"


async def test_new_waits_for_old_service_disposal_before_session_assignment(tmp_path: Path) -> None:
    """Semantic /new cancellation leaves the old session until service cleanup joins."""
    import asyncio
    from tests.tui.workflows.test_visibility_paint_barriers import checkpoint

    entered = asyncio.Event()
    release = asyncio.Event()
    owners: list[str] = []

    class ClosingService(DetachedWorkflowAppService):
        """Gate the public service-close boundary, not app internals."""

        async def close(self) -> None:
            """Hold cleanup so replacement publication can be observed."""
            entered.set()
            await release.wait()
            await super().close()

    def factory(
        *,
        workflow_handle_store: Optional[WorkflowHandleStore],
        owner_session_id: str,
        attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO],
        history_store: Optional[SessionHistoryStoreProtocol],
        attached_abort: Optional[AttachedChildAbort],
        attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]],
    ) -> DetachedWorkflowAppService:
        """Compose an owner-specific real service with gated disposal."""
        owners.append(owner_session_id)
        return ClosingService(
            workflow_handle_store=workflow_handle_store,
            owner_session_id=owner_session_id,
            attached_snapshot=attached_snapshot,
            history_store=history_store,
            attached_abort=attached_abort,
            attached_capability=attached_capability,
        )

    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")]), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="old-owner",
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-sonnet-4-6", enable_history=False),
    )
    app = SloTUI(session=session, workflow_service_factory=factory)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        command = asyncio.create_task(app.on_prompt_input_submitted(PromptInput.Submitted(text="/new")))
        await asyncio.wait_for(entered.wait(), timeout=5)
        command.cancel()
        await checkpoint()
        command.cancel()
        await checkpoint()
        try:
            assert app._session is session
            assert owners == ["old-owner"]
            assert not command.done()
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(command, return_exceptions=True), timeout=5)
        assert app._session is session


async def test_new_joins_observation_then_accepted_abort_before_retiring_sink(tmp_path: Path) -> None:
    """Cancellation cannot retire the mounted view or reset rows while old operations remain."""
    import asyncio
    from tests.tui.workflows.test_child_abort_confirmation import _Attached, _capability
    from tests.tui.workflows.test_visibility_paint_barriers import checkpoint
    from src.tui.workflows.session_progress_screen import SessionProgressScreen
    from src.tui.workflows.dao import ChildAbortTargetDAO, WorkflowSessionSnapshotDAO

    world = _Attached()
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    release = asyncio.Event()
    close_entered = asyncio.Event()
    order: list[str] = []
    services: list[DetachedWorkflowAppService] = []

    class ObservedService(DetachedWorkflowAppService):
        """Gate one public observation and record real close completion."""

        block = False

        async def load_session_snapshot(self) -> WorkflowSessionSnapshotDAO:
            """Join a cancelled read before allowing disposal to advance."""
            result = await super().load_session_snapshot()
            if self.block:
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()
                    order.append("observation-joined")
                    raise
            return result

        async def close(self) -> None:
            """Delegate accepted-operation joining to the actual service."""
            order.append("service-close")
            close_entered.set()
            await super().close()
            order.append("abort-joined")

    def factory(
        *,
        workflow_handle_store: Optional[WorkflowHandleStore],
        owner_session_id: str,
        attached_snapshot: Callable[[], AttachedDispatchSnapshotDAO],
        history_store: Optional[SessionHistoryStoreProtocol],
        attached_abort: Optional[AttachedChildAbort],
        attached_capability: Optional[Callable[[], Optional[ChildControlCapabilityDAO]]],
    ) -> DetachedWorkflowAppService:
        """Compose real visibility and abort ownership for each adopted session."""
        service = ObservedService(
            workflow_handle_store=workflow_handle_store,
            owner_session_id=owner_session_id,
            attached_snapshot=world._snapshot,
            attached_abort=world.abort,
            attached_capability=lambda: _capability(
                owner_session_id=owner_session_id, orchestrator_session_id=owner_session_id
            ),
        )
        services.append(service)
        return service

    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")]), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="owner-1",
        enable_history=False,
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-sonnet-4-6", enable_history=False),
    )
    app = SloTUI(session=session, workflow_service_factory=factory)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        service = services[0]
        rows = service.current_list_snapshot().rows
        key = rows[1].key
        app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionProgressScreen)
        progress = await service.load_session_progress(key=key)
        assert isinstance(progress.abort_target, ChildAbortTargetDAO)
        world.abort.gate.clear()
        service.begin_child_abort(target=progress.abort_target)
        await asyncio.wait_for(world.abort.entered.wait(), timeout=5)
        assert isinstance(service, ObservedService)
        service.block = True
        app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
        # Use the existing coordinator's public refresh operation, never replace it.
        assert app._workflow_progress_coordinator is not None
        app._workflow_progress_coordinator.request_refresh()
        await asyncio.wait_for(entered.wait(), timeout=5)
        command = asyncio.create_task(app.on_prompt_input_submitted(PromptInput.Submitted(text="/new")))
        await asyncio.wait_for(cancelled.wait(), timeout=5)
        command.cancel()
        await checkpoint()
        command.cancel()
        try:
            assert order == []
            assert app.screen is screen
            assert app._session is session
            release.set()
            await asyncio.wait_for(close_entered.wait(), timeout=5)
            assert order == ["observation-joined", "service-close"]
            assert not command.done()
            assert app.screen is screen
            assert len(app.query(SubAgentFleetRow)) == 2
        finally:
            release.set()
            world.abort.gate.set()
            result = await asyncio.wait_for(asyncio.gather(command, return_exceptions=True), timeout=5)
        await pilot.pause()
        assert isinstance(result[0], asyncio.CancelledError)
        assert order == ["observation-joined", "service-close", "abort-joined"]
        assert app._session is session
        assert len(services) == 1
        assert screen not in app.screen_stack
        assert list(app.query(SubAgentFleetRow)) == []
        assert len(world.abort.calls) == 1
