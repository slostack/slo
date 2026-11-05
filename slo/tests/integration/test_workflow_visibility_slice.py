"""First runnable Feature 98 journey; real app/service/coordinator, no execution."""

from pathlib import Path
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Any
from textual.pilot import Pilot
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

import pytest
from collections.abc import Callable
from typing import Optional

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.tui.authentication._painted_output import wait_for_condition, wait_until_painted
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
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
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


@pytest.fixture(autouse=True)
def workflow_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unrelated authentication UI out of workflow visibility scenarios."""

    def resolve(*, provider: ProviderName) -> CredentialDAO:
        return CredentialDAO(provider=provider, auth_type=AuthType.API_KEY, access_token="workflow-test")

    monkeypatch.setattr("src.tui.app.CredentialResolver.resolve", resolve)


@dataclass
class RunningVisibility:
    app: SloTUI
    pilot: Pilot
    factory: RunningBatchFactory
    root: Path

    @property
    def panel(self) -> SubAgentFleetPanel:
        return self.app.query_one(SubAgentFleetPanel)

    @property
    def rows(self) -> tuple:
        return tuple(row.row for row in self.panel.query(SubAgentFleetRow))

    async def command(self, text: str) -> None:
        editor = self.app.query_one(PromptInputComponent)
        editor.focus()
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: self.app.focused is editor,
            description="workflow editor owns focus",
        )
        editor.text = text
        await self.pilot.press("enter")

    async def hide(self) -> None:
        await self.command("/workflows tui dismiss")
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: not self.rows and self.panel.size.height == 0,
            description="hidden fleet releases layout space",
        )

    async def show(self) -> None:
        await self.command("/workflows tui show")
        await wait_for_condition(
            pilot=self.pilot,
            predicate=lambda: len(self.rows) == 6,
            description="six cached fleet rows are restored",
        )


@asynccontextmanager
async def running_visibility(
    tmp_path: Path, *, theme: str = "slo-dark", size: tuple[int, int] = (120, 40)
) -> AsyncIterator[RunningVisibility]:
    """Create fresh real workflow service state for each independently collected test."""
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
        panel = app.query_one(SubAgentFleetPanel)
        editor = app.query_one(PromptInputComponent)
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: len(panel.query(SubAgentFleetRow)) == 6,
            description="six running fleet rows are mounted",
        )
        yield RunningVisibility(app, pilot, factory, root)


@pytest.mark.parametrize("theme", ["slo-dark", "slo-default"])
@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
async def test_running_fleet_is_painted_and_editor_focused(
    tmp_path: Path, theme: str, size: tuple[int, int]
) -> None:
    async with running_visibility(tmp_path, theme=theme, size=size) as ui:
        painted = await wait_until_painted(pilot=ui.pilot, widget=ui.panel, text="Ongoing workflow tasks")
        assert "Ongoingworkflowtasks" in painted
        assert ui.app.focused is ui.app.query_one(PromptInputComponent)


@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
async def test_dismiss_reclaims_transcript_space(tmp_path: Path, size: tuple[int, int]) -> None:
    async with running_visibility(tmp_path, size=size) as ui:
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: ui.panel.size.height > 0,
            description="visible fleet occupies layout space",
        )
        height = ui.app.query_one("#transcript-scroll").size.height
        await ui.hide()
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: ui.app.query_one("#transcript-scroll").size.height > height,
            description="transcript reclaims hidden fleet space",
        )
        assert ui.app.query_one("#transcript-scroll").size.height > height
        assert ui.app.focused is ui.app.query_one(PromptInputComponent)


async def test_hidden_fleet_stays_collapsed_after_resize(tmp_path: Path) -> None:
    async with running_visibility(tmp_path) as ui:
        await ui.hide()
        await ui.pilot.resize_terminal(width=50, height=18)
        await ui.pilot.pause()
        assert ui.panel.size.height == 0
        assert "Resize" not in "".join(strip.text for strip in ui.app.screen._compositor.render_strips())


async def test_clear_preserves_hidden_fleet(tmp_path: Path) -> None:
    async with running_visibility(tmp_path) as ui:
        await ui.hide()
        await ui.command("/clear")
        await ui.pilot.pause()
        assert ui.panel.size.height == 0
        service = ui.factory.service
        assert service is not None and service.current_list_snapshot().rows == ()


async def test_show_restores_cached_identity_and_text_when_file_disappears(tmp_path: Path) -> None:
    async with running_visibility(tmp_path) as ui:
        original = ui.rows
        await ui.hide()
        await ui.command("/clear")
        (ui.root / "detached-parent/fleet.json").unlink()
        await ui.show()
        assert [row.key for row in ui.rows] == [row.key for row in original]
        assert [row.task_text for row in ui.rows] == [row.task_text for row in original]


async def test_show_restores_layout_and_keeps_editor_focus(tmp_path: Path) -> None:
    async with running_visibility(tmp_path) as ui:
        await ui.hide()
        await ui.show()
        await wait_for_condition(
            pilot=ui.pilot,
            predicate=lambda: ui.panel.size.height > 0,
            description="shown fleet occupies layout space",
        )
        assert ui.panel.size.height > 0
        assert ui.app.focused is ui.app.query_one(PromptInputComponent)


@pytest.mark.parametrize("operation", ["dismiss", "clear", "offline-show"])
async def test_visibility_commands_preserve_durable_files(tmp_path: Path, operation: str) -> None:
    async with running_visibility(tmp_path) as ui:
        if operation != "dismiss":
            await ui.hide()
        if operation == "offline-show":
            await ui.command("/clear")
            (ui.root / "detached-parent/fleet.json").unlink()
        before = tree_state(ui.root)
        if operation == "dismiss":
            await ui.hide()
        elif operation == "clear":
            await ui.command("/clear")
        else:
            await ui.show()
        assert tree_state(ui.root) == before


async def test_visibility_commands_do_not_change_execution(tmp_path: Path) -> None:
    async with running_visibility(tmp_path) as ui:
        before = ui.factory.snapshot()
        await ui.hide()
        await ui.command("/clear")
        await ui.show()
        assert ui.factory.snapshot() == before
        assert ui.factory.abort_calls == []


async def test_visibility_commands_do_not_cross_launch_or_auth_boundaries(tmp_path: Path) -> None:
    import sys
    from types import FrameType

    async with running_visibility(tmp_path) as ui:
        forbidden_calls: list[str] = []

        def record_forbidden(frame: FrameType, event: str, arg: object) -> None:
            module = str(frame.f_globals.get("__name__", ""))
            if event == "call" and (
                module == "src.auth.credential_resolver"
                or (module == "src.tui.visualizer_launcher" and frame.f_code.co_name == "launch")
                or module == "src.agents.slo_agent.orchestrator.relaunch"
            ):
                forbidden_calls.append(f"{module}.{frame.f_code.co_name}")

        previous = sys.getprofile()
        sys.setprofile(record_forbidden)
        try:
            await ui.hide()
            await ui.command("/clear")
            await ui.show()
        finally:
            sys.setprofile(previous)
        assert forbidden_calls == []


async def test_new_waits_for_old_service_disposal_before_session_assignment(tmp_path: Path) -> None:
    """Committed /new joins old cleanup before adoption despite caller cancellation."""
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
        command = asyncio.create_task(
            app.on_prompt_input_component_submitted(PromptInputComponent.Submitted(text="/new"))
        )
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
        assert app._session is not session
        assert len(owners) == 2
        assert owners[1] == app._session.session_id


@asynccontextmanager
async def replacement_barrier(tmp_path: Path, *, phase: str) -> AsyncIterator[dict[str, Any]]:
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
        await wait_for_condition(
            pilot=pilot,
            predicate=lambda: isinstance(app.screen, SessionProgressScreen),
            description="child progress screen is mounted",
        )
        screen = app.screen
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
        command = asyncio.create_task(
            app.on_prompt_input_component_submitted(PromptInputComponent.Submitted(text="/new"))
        )
        await asyncio.wait_for(cancelled.wait(), timeout=5)
        command.cancel()
        await checkpoint()
        command.cancel()
        state = dict(
            app=app,
            session=session,
            screen=screen,
            services=services,
            order=order,
            command=command,
            world=world,
        )
        try:
            if phase == "observation":
                yield state
            release.set()
            await asyncio.wait_for(close_entered.wait(), timeout=5)
            if phase == "abort":
                yield state
        finally:
            release.set()
            world.abort.gate.set()
            result = await asyncio.wait_for(asyncio.gather(command, return_exceptions=True), timeout=5)
        await pilot.pause()
        state["result"] = result
        if phase == "retired":
            yield state


async def test_new_keeps_owner_and_screen_until_observation_joins(tmp_path: Path) -> None:
    async with replacement_barrier(tmp_path, phase="observation") as state:
        assert state["order"] == []
        assert state["app"].screen is state["screen"] and state["app"]._session is state["session"]


async def test_new_keeps_view_until_accepted_abort_joins(tmp_path: Path) -> None:
    async with replacement_barrier(tmp_path, phase="abort") as state:
        assert state["order"] == ["observation-joined", "service-close"] and not state["command"].done()
        assert state["app"].screen is state["screen"] and len(state["app"].query(SubAgentFleetRow)) == 2


async def test_new_cancellation_preserves_join_order(tmp_path: Path) -> None:
    import asyncio

    async with replacement_barrier(tmp_path, phase="retired") as state:
        assert isinstance(state["result"][0], asyncio.CancelledError)
        assert state["order"] == ["observation-joined", "service-close", "abort-joined"]


async def test_new_replaces_service_after_owned_work_joins(tmp_path: Path) -> None:
    async with replacement_barrier(tmp_path, phase="retired") as state:
        assert state["app"]._session is not state["session"]
        services = state["services"]
        assert len(services) == 2 and services[0]._closed and not services[1]._closed


async def test_new_retires_old_screen_and_rows(tmp_path: Path) -> None:
    async with replacement_barrier(tmp_path, phase="retired") as state:
        assert state["screen"] not in state["app"].screen_stack
        assert all(
            row.row.key.orchestrator_session_id != state["session"].session_id
            for row in state["app"].query(SubAgentFleetRow)
        )


async def test_new_does_not_duplicate_accepted_abort(tmp_path: Path) -> None:
    async with replacement_barrier(tmp_path, phase="retired") as state:
        assert len(state["world"].abort.calls) == 1
