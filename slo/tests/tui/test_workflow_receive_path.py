"""TUI integration tests for the detached-workflow receive path (spec 57.a.5).

Proves ``SloTUI`` delegates to the ``src/tui/workflows`` namespace:
``launch_workflow`` tool results seed the live-state cache and launch the
visualizer, and the startup reconcile feeds the resume/exit hint. The file
inbox that once carried workflow lifecycle messages is retired (108.6); the
service-level lifecycle advance remains covered at the end of this module.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscriptComponent
import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage

import pytest

from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui._scroll_settle import pump_until
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.service import DetachedWorkflowAppService


@pytest.fixture(autouse=True)
def _enable_fake_visualizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise platform compatibility with suite-wide real spawn blocking intact."""
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")


async def _join_viewers(app: SloTUI) -> None:
    """Await registered workers while their fake platform boundary is installed."""
    for task in tuple(app._visualizer_launch_tasks.values()):
        await asyncio.wait_for(task, timeout=5)


def _mock_session(*, history_root: Path) -> MagicMock:
    """Build the standard mocked ``SloAgentSession`` for TUI receive-path tests.

    Args:
        history_root (Path): History root exposed by the mock session.

    Returns:
        MagicMock: Session mock matching the ``SloAgentSession`` surface.
    """
    session: MagicMock = MagicMock(spec=SloAgentSession)
    # This receive-path double owns no external reporting resources.
    session.finish_retired_reporting_cleanup.return_value = HerdrReporterCloseOutcomeDAO(
        replacement="safe", resources="drained"
    )
    session.workdir = Path(".").resolve()
    session.session_id = "session-1234"
    session.workflow_visualizer_destination = "platform"
    session.session_name = None
    session.active_model_name = "claude-sonnet-4-6"
    session.routed_model_name = "claude-sonnet-4-6"
    session.active_reasoning_level = "high"
    session.history_enabled = True
    session.history_root = history_root
    # An idle session: the TUI is not running a prompt and owns no channel
    # poller (108.1).
    session.is_running = False
    session.channel_poller = None
    session.subscribe = MagicMock()
    session.unsubscribe = MagicMock()
    session.hydrate_transcript_entries = AsyncMock(return_value=[])
    session.should_show_startup_notice = AsyncMock(return_value=False)
    session.usage_snapshot = MagicMock(
        return_value=SessionUsageSnapshotDAO(
            active_model_name="claude-sonnet-4-6",
            active_reasoning_level="high",
        )
    )
    session.refresh_usage_snapshot = MagicMock(return_value=MagicMock())
    session.record_workflow_update = AsyncMock(return_value=True)
    # Workflow observation polls these on mount; no pool and no history adapter.
    session.attached_dispatch_snapshot = MagicMock(return_value=AttachedDispatchSnapshotDAO.empty())
    session.history_store = None
    return session


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
        owner_session_id="session-1234",
        orchestrator_session_id="orch-1",
        pid=4242,
        brief="run the workflow",
        cwd="/tmp",
        state=state,
    )
    await store.write(handle=handle)
    return handle


class TestVisualizerRetarget:
    """The visualizer launches against the orchestrator session id (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_launch_result_triggers_visualizer_with_orch_sid(self, tmp_path: Path) -> None:
        """The launch_workflow tool result opens the visualizer on the orch session."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"}',
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._render_event(event)
                await _join_viewers(app)

            mock_launch.assert_called_once_with(parent_session_id="orch-1")
            assert app.query_one(ChatTranscriptComponent)._adapter is not None
            assert any(
                "Opened workflow visualizer in a new window." in content
                for content, _classes in app.query_one(ChatTranscriptComponent)._adapter.lines
            )

    @pytest.mark.asyncio
    async def test_launch_result_error_json_does_not_trigger(self, tmp_path: Path) -> None:
        """A launch_workflow error JSON (no orchestrator id) never launches."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content='{"error": "workflow cap reached"}',
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._render_event(event)
                await _join_viewers(app)

            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_launch_result_malformed_json_does_not_trigger(self, tmp_path: Path) -> None:
        """A malformed launch_workflow result is a safe no-op."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content="not json {",
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                await app._render_event(event)
                await _join_viewers(app)

            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_launch_result_launches_once(self, tmp_path: Path) -> None:
        """Redelivered launch results are guarded by the renderer."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ) as mock_launch:
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )
                await _join_viewers(app)
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )
                await _join_viewers(app)

            mock_launch.assert_called_once_with(parent_session_id="orch-1")

    @pytest.mark.asyncio
    async def test_launch_failure_writes_manual_command_hint(self, tmp_path: Path) -> None:
        """A failed window spawn writes the manual visualize command instead."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=False,
            ):
                app._maybe_launch_workflow_visualizer(
                    result_text='{"orchestrator_session_id": "orch-1"}',
                )
                await _join_viewers(app)

            assert app.query_one(ChatTranscriptComponent)._adapter is not None
            assert any(
                "slo visualize --session orch-1 --follow" in content
                for content, _classes in app.query_one(ChatTranscriptComponent)._adapter.lines
            )


class TestWorkflowHandleStateAdvance:
    """Claimed lifecycle notes advance the durable handle (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_mount_reconciles_handles(self, tmp_path: Path) -> None:
        """A resumed TUI shows accurate states before any note arrives."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root, pid_alive=False)
        await _write_handle(store=store, state="running")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()

            assert app._workflow_app_service is not None
            labels = app._workflow_app_service.live_workflow_labels()
            assert labels == []
            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "stalled"

    @pytest.mark.asyncio
    async def test_mount_reconcile_failure_is_nonfatal(self, tmp_path: Path) -> None:
        """A store failure at mount never breaks session delivery startup."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._workflow_app_service is not None
            with patch.object(
                app._workflow_app_service._store,
                "reconcile",
                new=AsyncMock(side_effect=OSError("disk gone")),
            ):
                snapshot = await app._workflow_app_service.reconcile_snapshot()

            assert snapshot == {}


class TestAbortSeparationAndExit:
    """Abort separation and the live-workflow exit hint (spec 57.a.5)."""

    @pytest.mark.asyncio
    async def test_session_abort_leaves_detached_handles_untouched(self, tmp_path: Path) -> None:
        """``^C`` during a prompt aborts only the prompt — no handle writes."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="running")
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()
            app._in_flight_task = asyncio.create_task(asyncio.sleep(60))
            with patch.object(store, "update_state", wraps=store.update_state) as update_state_spy:
                await app.action_interrupt()

            session.abort.assert_called_once_with()
            update_state_spy.assert_not_called()
            handle = await store.read(owner_session_id="session-1234", workflow_id="wf-1")
            assert handle is not None
            assert handle.state == "running"
            app._in_flight_task.cancel()
            app._in_flight_task = None

    @pytest.mark.asyncio
    async def test_exit_hint_lists_live_workflows(self, tmp_path: Path) -> None:
        """Live workflows appear next to the resume command on exit."""
        history_root: Path = tmp_path / "history"
        store: WorkflowHandleStore = _build_store(history_root=history_root)
        await _write_handle(store=store, state="running")
        await _write_handle(store=store, workflow_id="wf-2", state="running")
        await store.update_state(
            owner_session_id="session-1234",
            workflow_id="wf-2",
            state="completed",
        )
        session: MagicMock = _mock_session(history_root=history_root)
        app: SloTUI = SloTUI(session=session, workflow_handle_store=store)

        async with app.run_test() as pilot:
            await pilot.pause()

            hint: str = app._resume_command_hint()

        assert hint == (
            "Resume this session: slo --resume session-1234\n"
            "Live workflows: wf-1 (running). "
            "They keep running — list with /workflows after resume."
        )

    @pytest.mark.asyncio
    async def test_exit_hint_without_workflows_is_unchanged(self, tmp_path: Path) -> None:
        """Sessions without workflows print today's hint byte-identically."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)

        assert app._resume_command_hint() == "Resume this session: slo --resume session-1234"


class TestLaunchResultSeedsExitHint:
    """The launch turn itself makes the new workflow visible to the exit hint."""

    @pytest.mark.asyncio
    async def test_launch_result_seeds_state_cache_and_exit_hint(self, tmp_path: Path) -> None:
        """A workflow launched this session is listed before any note is claimed."""
        session: MagicMock = _mock_session(history_root=tmp_path / "history")
        app: SloTUI = SloTUI(session=session)
        event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="tool_result",
            tool_name="launch_workflow",
            tool_call_id="call-1",
            content=(
                '{"workflow_id": "wf-9a1b", "orchestrator_session_id": "orch-1", ' '"state": "launching"}'
            ),
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            with patch(
                "src.tui.visualizer_launcher.VisualizerLauncher.launch",
                return_value=True,
            ):
                await app._render_event(event)
                await _join_viewers(app)

            assert app._resume_command_hint() == (
                "Resume this session: slo --resume session-1234\n"
                "Live workflows: wf-9a1b (launching). "
                "They keep running — list with /workflows after resume."
            )


def _launch_result_event(*, workflow_id: str) -> AgentStreamEventDAO:
    """Build the ``launch_workflow`` tool result for one workflow of orchestrator ``orch-1``.

    Args:
        workflow_id (str): Launched workflow id.

    Returns:
        AgentStreamEventDAO: The streamed tool result.
    """
    return AgentStreamEventDAO(
        kind="tool_result",
        tool_name="launch_workflow",
        tool_call_id=f"call-{workflow_id}",
        content=f'{{"workflow_id": "{workflow_id}", "orchestrator_session_id": "orch-1", "state": "launching"}}',
    )


class RecordingHandleStore(WorkflowHandleStore):
    """Real handle store that also counts reconcile passes (injected through the app constructor)."""

    def __init__(self, *, history_root: Path) -> None:
        """Build the real store with every pid reported alive.

        Args:
            history_root (Path): Test-owned history root.
        """
        super().__init__(history_root=history_root, pid_alive=lambda pid: True)
        self.reconcile_calls: int = 0

    async def reconcile(self, *, owner_session_id: str) -> list[WorkflowHandleDAO]:
        """Count the pass, then reconcile for real.

        Args:
            owner_session_id (str): Owning TUI session id.

        Returns:
            list[WorkflowHandleDAO]: Reconciled handles.
        """
        self.reconcile_calls += 1
        return await super().reconcile(owner_session_id=owner_session_id)


class _LifecycleWorld:
    """A real mounted-TUI world: session, gateway, handle store and the workflow's real notifier."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Build (without opening) every real collaborator under ``tmp_path``.

        Args:
            tmp_path (Path): Test-owned root for history and ``channels.db``.
        """
        from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
        from tests.tui.test_channel_adapter import _build_session

        self.history_root: Path = tmp_path / "history"
        self.session: SloAgentSession = _build_session(
            tmp_path=tmp_path, responses=[AIMessage(content="presented")], session_id="session-1234"
        )
        self.gateway: ChannelGateway = ChannelGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        self.store: RecordingHandleStore = RecordingHandleStore(history_root=self.history_root)
        self.status: OrchestratorStatusStore = OrchestratorStatusStore(
            history_root=self.history_root, orchestrator_session_id="orch-1", workflow_id="wf-1"
        )
        self.notifier: WorkflowNotifier = WorkflowNotifier(
            gateway=self.gateway,
            target_session_id="session-1234",
            orchestrator_session_id="orch-1",
            workflow_id="wf-1",
        )

    def build_app(self) -> SloTUI:
        """Return the TUI wired to this world's real gateway and handle store.

        Returns:
            SloTUI: The unmounted app.
        """
        return SloTUI(session=self.session, channel_gateway=self.gateway, workflow_handle_store=self.store)

    async def handle_state(self) -> Optional[WorkflowState]:
        """Return the durable state of ``wf-1``.

        Returns:
            Optional[WorkflowState]: The stored state, or ``None`` when absent.
        """
        handle: Optional[WorkflowHandleDAO] = await self.store.read(
            owner_session_id="session-1234", workflow_id="wf-1"
        )
        return handle.state if handle is not None else None


class TestChannelLifecycleReconcile:
    """Workflow rows arriving through the channel queue keep handle lifecycle truthful (57.a.5).

    Journey: the real ``WorkflowNotifier`` sends through the real gateway; the
    mounted session's real poller hands the row to the TUI's display sink
    (notes) or turn runner (the terminal prompt); the app reconciles the
    durable handles from the orchestrator's own ``orchestrator.json``, which the
    orchestrator writes before its terminal prompt. Only the platform window
    launcher is replaced.
    """

    @pytest.mark.asyncio
    async def test_terminal_prompt_reconciles_handle_clears_live_label_and_resets_guard(
        self, tmp_path: Path
    ) -> None:
        """A workflow's terminal prompt: handle terminal, exit hint clean, and a relaunch opens a window."""
        world: _LifecycleWorld = _LifecycleWorld(tmp_path=tmp_path)
        await _write_handle(store=world.store, state="running")
        app: SloTUI = world.build_app()
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                panel: SubAgentFleetPanel = app.query_one(SubAgentFleetPanel)
                panel_before: tuple[bool, int] = (bool(panel.display), len(panel.query(SubAgentFleetRow)))
                with patch(
                    "src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=True
                ) as launch:
                    await app._render_event(_launch_result_event(workflow_id="wf-1"))
                    await _join_viewers(app)
                    world.status.write_terminal(state="completed", exit_code=0, phase="done")
                    await world.notifier.completed(synthesis="all green", result_json="{}")
                    await pump_until(pilot=pilot, predicate=lambda: not app._live_workflow_labels())
                    await _join_viewers(app)
                    hint_after_terminal: str = app._resume_command_hint()
                    await app._render_event(_launch_result_event(workflow_id="wf-2"))
                    await _join_viewers(app)
                state_after_terminal: Optional[WorkflowState] = await world.handle_state()
                # The channel lifecycle neither paints nor resets the fleet panel (57.a.5 v1
                # decision); its rows belong to owner-scoped observation, which shows the owned
                # handle from mount on.
                panel_after: tuple[bool, int] = (bool(panel.display), len(panel.query(SubAgentFleetRow)))
        finally:
            await world.gateway.close()

        assert state_after_terminal == "completed"
        assert hint_after_terminal == "Resume this session: slo --resume session-1234"
        assert launch.call_count == 2
        assert panel_after == panel_before

    @pytest.mark.asyncio
    async def test_started_note_reconciles_to_running_and_opens_the_resume_visualizer(
        self, tmp_path: Path
    ) -> None:
        """The resume case: a started note with fresh running evidence opens the visualizer once."""
        world: _LifecycleWorld = _LifecycleWorld(tmp_path=tmp_path)
        await _write_handle(store=world.store, state="launching")
        app: SloTUI = world.build_app()
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                world.status.write_running(phase="model")
                with patch(
                    "src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=True
                ) as launch:
                    await world.notifier.started(brief_preview="run the workflow")
                    await pump_until(pilot=pilot, predicate=lambda: bool(app._live_workflow_labels()))
                    await world.notifier.phase_update(phase_summary="review done")
                    await pump_until(
                        pilot=pilot,
                        predicate=lambda: sum("phase 1" in line for line, _classes in _lines(app=app)) == 1,
                    )
                    await _join_viewers(app)
                labels = app._live_workflow_labels()
                state_after_started: Optional[WorkflowState] = await world.handle_state()
        finally:
            await world.gateway.close()

        assert state_after_started == "running"
        assert [(label.workflow_id, label.state) for label in labels] == [("wf-1", "running")]
        launch.assert_called_once_with(parent_session_id="orch-1")

    @pytest.mark.asyncio
    async def test_the_operators_own_prompt_never_reconciles_workflow_handles(self, tmp_path: Path) -> None:
        """Only rows from other participants are workflow traffic; the user's prompt reconciles nothing."""
        world: _LifecycleWorld = _LifecycleWorld(tmp_path=tmp_path)
        await _write_handle(store=world.store, state="running")
        app: SloTUI = world.build_app()
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                passes_after_mount: int = world.store.reconcile_calls
                app.query_one(PromptInputComponent).text = "hello"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot, predicate=lambda: any("presented" in line for line, _c in _lines(app=app))
                )
                passes_after_prompt: int = world.store.reconcile_calls
        finally:
            await world.gateway.close()

        assert passes_after_mount >= 1
        assert passes_after_prompt == passes_after_mount


def _lines(*, app: SloTUI) -> list[tuple[str, str]]:
    """Return the mounted transcript's recorded (content, classes) lines.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        list[tuple[str, str]]: Transcript lines.
    """
    from tests.tui.test_channel_adapter import _transcript_lines

    return _transcript_lines(app=app)


@pytest.mark.parametrize("with_evidence", [True, False])
async def test_run_aborted_advance_marks_handle_aborted(tmp_path: Path, with_evidence: bool) -> None:
    """An abort lifecycle advance converges even when terminal evidence is withheld."""
    from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = _build_store(history_root=root)
    await _write_handle(store=store, state="running")
    if with_evidence:
        OrchestratorStatusStore(
            history_root=root, orchestrator_session_id="orch-1", workflow_id="wf-1"
        ).write_terminal(state="aborted", exit_code=2, phase="done")
    service = DetachedWorkflowAppService(
        workflow_handle_store=store,
        owner_session_id="session-1234",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
    )
    outcome = await service.advance_from_inbox_message(
        kind="workflow_aborted", payload={"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"}
    )
    assert outcome.advanced_state == "aborted"
    assert [effect.effect for effect in outcome.effects] == ["reset_launch_guard"]
    path = root / "session-1234" / "workflows" / "wf-1.json"
    before = path.read_bytes()
    assert (await store.reconcile(owner_session_id="session-1234"))[0].state == "aborted"
    assert path.read_bytes() == before


@pytest.mark.parametrize("state", ["launching", "running", "aborted", "stalled", "failed", "completed"])
async def test_aborted_note_then_reconcile_converges_each_handle_state(
    tmp_path: Path, state: WorkflowState
) -> None:
    """Legal notes advance; illegal notes defer to matching evidence without overriding finality."""
    from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = _build_store(history_root=root)
    await _write_handle(store=store, state=state)
    OrchestratorStatusStore(
        history_root=root, orchestrator_session_id="orch-1", workflow_id="wf-1"
    ).write_terminal(state="aborted", exit_code=2, phase="done")
    path = root / "session-1234" / "workflows" / "wf-1.json"
    before = path.read_bytes()
    service = DetachedWorkflowAppService(
        workflow_handle_store=store,
        owner_session_id="session-1234",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
    )
    outcome = await service.advance_from_inbox_message(
        kind="workflow_aborted", payload={"workflow_id": "wf-1", "orchestrator_session_id": "orch-1"}
    )
    legal = state in {"launching", "running", "aborted"}
    assert outcome.advanced_handle is legal
    assert outcome.workflow_id == "wf-1"
    assert outcome.advanced_state == ("aborted" if legal else None)
    assert [effect.effect for effect in outcome.effects] == (["reset_launch_guard"] if legal else [])
    result = await store.reconcile(owner_session_id="session-1234")
    assert result[0].state == ("completed" if state == "completed" else "aborted")
    if state in {"completed", "aborted"}:
        assert path.read_bytes() == before


class _UnreadableHandleStore(WorkflowHandleStore):
    """Handle store stub whose reconcile always fails (a vanished or unreadable history root)."""

    async def reconcile(self, *, owner_session_id: str) -> list[WorkflowHandleDAO]:
        """Fail the way a broken filesystem would.

        Args:
            owner_session_id (str): Ignored owning session id.

        Raises:
            OSError: Always.
        """
        raise OSError("history root unreadable")


async def test_reconciliation_advance_emits_each_lifecycle_step_once(tmp_path: Path) -> None:
    """Started then terminal evidence each produce one effect; an unchanged reconcile produces none."""
    from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

    root: Path = tmp_path / "history"
    store: WorkflowHandleStore = _build_store(history_root=root)
    await _write_handle(store=store, state="launching")
    service: DetachedWorkflowAppService = DetachedWorkflowAppService(
        workflow_handle_store=store,
        owner_session_id="session-1234",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
    )
    await service.reconcile_snapshot()
    status = OrchestratorStatusStore(history_root=root, orchestrator_session_id="orch-1", workflow_id="wf-1")

    status.write_running(phase="model")
    started = await service.advance_from_reconciliation()
    unchanged = await service.advance_from_reconciliation()
    status.write_terminal(state="failed", exit_code=1, phase="done")
    terminal = await service.advance_from_reconciliation()

    assert [(effect.effect, effect.state, effect.orchestrator_session_id) for effect in started] == [
        ("launch_visualizer", "running", "orch-1")
    ]
    assert unchanged == []
    assert [(effect.effect, effect.state) for effect in terminal] == [("reset_launch_guard", "failed")]
    assert service.live_workflow_labels() == []


async def test_reconciliation_advance_survives_a_failing_store_and_keeps_the_cache(tmp_path: Path) -> None:
    """A broken handle store is logged, never raised; delivery continues and cached labels stay."""
    service: DetachedWorkflowAppService = DetachedWorkflowAppService(
        workflow_handle_store=_UnreadableHandleStore(history_root=tmp_path / "history"),
        owner_session_id="session-1234",
        attached_snapshot=AttachedDispatchSnapshotDAO.empty,
    )
    service.advance_from_launch_result(
        result_text='{"workflow_id": "wf-1", "orchestrator_session_id": "orch-1", "state": "launching"}'
    )

    effects = await service.advance_from_reconciliation()

    assert effects == []
    assert [(label.workflow_id, label.state) for label in service.live_workflow_labels()] == [
        ("wf-1", "launching")
    ]
