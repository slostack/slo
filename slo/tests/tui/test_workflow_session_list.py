"""Session list and progress selection inside the real ``SloTUI`` (feature 94 a.2/a.3).

Rows reach the panel only through the production path: the session's attached
supplier, the real ``DetachedWorkflowAppService``, the single
``WorkflowProgressCoordinator`` and the app's progress sink. Tests cover the
layout, editor coexistence, observation lifecycle (one five-second timer,
retention at prompt end, ``/new`` and unmount teardown order), lifecycle-event
refresh requests, typed dismiss/resume routing, list-to-modal selection and the
queued-prompt block staying above the input while the list and modal show.

No test touches files outside ``tmp_path``, providers, processes or terminals.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.pilot import Pilot
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, SubAgentStatusDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.slash_router import SlashCommandResultDAO
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.queued_prompt_block import QueuedPromptBlock
from src.tui.widgets.sub_agent_fleet_panel import FleetSessionList, SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.widgets.usage_status_bar import UsageStatusBar
from src.tui.workflows.dao import (
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
    WorkflowListVisibilityRequestDAO,
)
from tests.integration.test_workflow_visibility_slice import RunningBatchFactory
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator
from src.tui.workflows.service import DetachedWorkflowAppService
from src.tui.workflows.session_progress_screen import ProgressLog, SessionProgressScreen
from tests.tui._scroll_settle import pump_until
from tests.tui.authentication._painted_output import painted_widget_strips
from tests.tui.test_prompt_input_rules import _recording_invoke, _submit_prompt

_DISPATCH_ID: str = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"


class _AttachedSupplier:
    """Stand-in for ``session.attached_dispatch_snapshot``; tests replace its batch."""

    def __init__(self) -> None:
        """Start with the explicit no-dispatch value."""
        self.snapshot: AttachedDispatchSnapshotDAO = AttachedDispatchSnapshotDAO.empty()
        self.calls: int = 0

    def publish(self, *, children: int, aborted_first: bool = True) -> None:
        """Replace the batch with ``children`` entries with distinct markup-like previews.

        Args:
            children (int): Number of child entries.
            aborted_first (bool, optional): Whether ``child-00`` is aborted. Defaults to True.
        """
        self.snapshot = AttachedDispatchSnapshotDAO(
            dispatch_id=_DISPATCH_ID,
            dispatch_sequence=1,
            entries=tuple(
                SubAgentStatusDAO(
                    task_id=f"task-{index:02d}",
                    session_id=f"child-{index:02d}",
                    status="aborted" if aborted_first and index == 0 else "running",
                    prompt_preview=f"Task summary v1: [b]task[/b] number {index}",
                )
                for index in range(children)
            ),
        )

    def __call__(self) -> AttachedDispatchSnapshotDAO:
        """Return the current batch and count the read.

        Returns:
            AttachedDispatchSnapshotDAO: Current batch.
        """
        self.calls += 1
        return self.snapshot


def _build_session(*, workdir: Path, supplier: Optional[_AttachedSupplier] = None) -> SloAgentSession:
    """Build a faux-backed, no-history session whose attached batch a test controls.

    Args:
        workdir (Path): Test-owned working directory.
        supplier (Optional[_AttachedSupplier], optional): Attached batch supplier;
            a fresh empty one when None. Defaults to None.

    Returns:
        SloAgentSession: Session with no real model calls.
    """
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
        workdir=workdir,
        session_id=str(uuid4()),
    )
    session.attached_dispatch_snapshot = supplier or _AttachedSupplier()  # type: ignore[method-assign]
    return session


class _ListApp(SloTUI):
    """Mount a real visibility owner through the public service factory."""

    CSS_PATH = Path(__file__).resolve().parents[2] / "src/tui/app.tcss"

    def __init__(self, *, workdir: Path) -> None:
        """Bind the controlled registry without replacing session methods."""
        self.supplier = _AttachedSupplier()
        supplier = self.supplier

        class Factory(RunningBatchFactory):
            """Supply registry evidence to the real service."""

            def snapshot(self) -> AttachedDispatchSnapshotDAO:
                """Read the test-owned registry boundary."""
                return supplier()

        self.factory = Factory()
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        session = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")]), tools=[]),
            workdir=workdir,
            session_id=str(uuid4()),
            enable_history=False,
            config=SessionConfigDAO(workdir=workdir, model_name="claude-sonnet-4-6", enable_history=False),
        )
        super().__init__(session=session, workflow_service_factory=self.factory)


def _supplier(*, app: SloTUI) -> _AttachedSupplier:
    """Return the test supplier installed on the app's current session.

    Args:
        app (SloTUI): App built around ``_build_session``.

    Returns:
        _AttachedSupplier: The session's supplier.
    """
    if isinstance(app, _ListApp):
        return app.supplier
    supplier = app._session.attached_dispatch_snapshot
    assert isinstance(supplier, _AttachedSupplier)
    return supplier


def _coordinator(*, app: SloTUI) -> WorkflowProgressCoordinator:
    """Return the bound coordinator.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        WorkflowProgressCoordinator: The single coordinator.
    """
    assert app._workflow_progress_coordinator is not None
    return app._workflow_progress_coordinator


async def _settle(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Await the coordinator's in-flight refresh, then let Textual paint twice.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Active pilot.
    """
    coordinator: Optional[WorkflowProgressCoordinator] = app._workflow_progress_coordinator
    task: Optional[asyncio.Task[None]] = coordinator._task if coordinator is not None else None
    if task is not None:
        await task
    await pilot.pause()
    await pilot.pause()


async def _refresh(*, app: SloTUI, pilot: Pilot[None]) -> None:
    """Request one coordinator refresh and wait until it painted.

    Args:
        app (SloTUI): Mounted app.
        pilot (Pilot[None]): Active pilot.
    """
    _coordinator(app=app).request_refresh()
    await _settle(app=app, pilot=pilot)


def _painted_text(*, app: SloTUI, widget: Static | SubAgentFleetRow) -> str:
    """Return one widget's painted cells as text.

    Args:
        app (SloTUI): Running app.
        widget (Static | SubAgentFleetRow): Widget to read.

    Returns:
        str: Painted text, outer blanks removed.
    """
    return "".join(strip.text for strip in painted_widget_strips(app=app, widget=widget)).strip()


async def _populated_app(*, app: SloTUI, pilot: Pilot[None], children: int) -> SubAgentFleetPanel:
    """Publish an attached batch and let the production refresh path paint it.

    Args:
        app (SloTUI): Running app.
        pilot (Pilot[None]): Active pilot.
        children (int): Number of child rows.

    Returns:
        SubAgentFleetPanel: The single mounted panel.
    """
    await _settle(app=app, pilot=pilot)
    _supplier(app=app).publish(children=children)
    await _refresh(app=app, pilot=pilot)
    assert app._fleet_panel is not None
    return app._fleet_panel


class TestSessionListLayout:
    """Heading plus at most five rows, a quarter of the screen, below the editor."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize(
        ("width", "height", "visible_rows"),
        [(60, 20, 1), (80, 24, 5), (120, 40, 5)],
        ids=["60x20", "80x24", "120x40"],
    )
    async def test_list_geometry_and_literal_paint(
        self, tmp_path: Path, theme: Theme, width: int, height: int, visible_rows: int
    ) -> None:
        """One panel sits between editor and usage bar with the size-bounded row count."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(width, height)) as pilot:
            app.theme = theme.name
            await pilot.pause()
            panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=20)
            await pilot.pause()

            assert len(app.query(SubAgentFleetPanel)) == 1
            assert app._input is not None
            session_list: FleetSessionList = panel.query_one(FleetSessionList)
            usage_bar: UsageStatusBar = app.query_one(UsageStatusBar)
            assert panel.region.y >= app._input.region.bottom
            assert usage_bar.region.y >= panel.region.bottom
            assert usage_bar.region.bottom <= height
            assert app._input.region.height >= 3
            assert session_list.region.height == visible_rows
            assert panel.region.height == visible_rows + 1
            assert panel.region.height <= height // 4
            heading: Static = panel.query_one(".workflow-sessions-heading", Static)
            assert _painted_text(app=app, widget=heading) == "Ongoing workflow tasks"
            first_child: SubAgentFleetRow = list(panel.query(SubAgentFleetRow))[0]
            assert _painted_text(app=app, widget=first_child).startswith(
                f"[running] {app._session.session_id}"
            )

    @pytest.mark.asyncio
    async def test_child_row_paints_literal_markup_and_aborted_status(self, tmp_path: Path) -> None:
        """A child row paints its status and markup-like task text literally."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=2)
            await pilot.pause()

            child: SubAgentFleetRow = list(panel.query(SubAgentFleetRow))[1]
            assert _painted_text(app=app, widget=child) == "[aborted] child-00: [b]task[/b] number 0"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("width", "height"), [(59, 20), (60, 19), (40, 12)], ids=["narrow", "short", "tiny"]
    )
    async def test_below_minimum_size_shows_resize_notice(
        self, tmp_path: Path, width: int, height: int
    ) -> None:
        """Below 60x20 the rows give way to a compact notice; Escape is harmless and idle Ctrl+C still quits."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause()
            panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=5)
            await pilot.pause()

            assert panel.query_one(FleetSessionList).display is False
            notice: Static = panel.query_one(".workflow-sessions-resize-notice", Static)
            assert _painted_text(app=app, widget=notice).startswith("Enlarge the terminal")
            await pilot.press("escape")
            assert app.is_running
            with patch.object(app, "exit", wraps=app.exit) as exit_spy:
                await pilot.press("ctrl+c")
                await pilot.pause()
            exit_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_resizing_back_restores_the_rows(self, tmp_path: Path) -> None:
        """Growing past the minimum hides the notice and shows the rows again."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(50, 15)) as pilot:
            await pilot.pause()
            panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=5)
            await pilot.resize_terminal(width=120, height=40)
            await pilot.pause()

            assert panel.query_one(FleetSessionList).region.height == 5
            assert panel.query_one(".workflow-sessions-resize-notice", Static).display is False


class TestEditorCoexistence:
    """The list adds no global keys and leaves the editor's own bindings intact."""

    @pytest.mark.asyncio
    async def test_ctrl_w_still_deletes_the_previous_word(self, tmp_path: Path) -> None:
        """With rows shown, Ctrl+W in the editor deletes the previous word as before."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _populated_app(app=app, pilot=pilot, children=3)
            assert app._input is not None
            app._input.focus()
            app._input.text = "hello world"
            app._input.move_cursor((0, 11))
            await pilot.pause()

            await pilot.press("ctrl+w")
            await pilot.pause()

            assert app._input.text == "hello "
            assert app.focused is app._input

    @pytest.mark.asyncio
    async def test_editor_arrows_do_not_move_the_list(self, tmp_path: Path) -> None:
        """Up/Down/Left/Right in the editor never change the list selection."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=3)
            assert app._input is not None
            app._input.focus()
            await pilot.pause()
            session_list: FleetSessionList = panel.query_one(FleetSessionList)
            before: tuple[int | None, int] = (session_list.index, session_list.navigation_revision)

            await pilot.press("down", "up", "left", "right")
            await pilot.pause()

            assert (session_list.index, session_list.navigation_revision) == before
            assert app.focused is app._input


class _BlockingModal(ModalScreen[None]):
    """An unrelated dialog above the base screen."""


def _rows(*, app: SloTUI) -> dict[str, str]:
    """Return each mounted row's status by session id.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        dict[str, str]: Session id to displayed status.
    """
    assert app._fleet_panel is not None
    return {item.row.key.session_id: item.row.status for item in app._fleet_panel.query(SubAgentFleetRow)}


def _row_widget(*, app: SloTUI, session_id: str) -> SubAgentFleetRow:
    """Return the mounted row for one session id.

    Args:
        app (SloTUI): Mounted app.
        session_id (str): Row session id.

    Returns:
        SubAgentFleetRow: Row widget.
    """
    assert app._fleet_panel is not None
    return next(
        item for item in app._fleet_panel.query(SubAgentFleetRow) if item.row.key.session_id == session_id
    )


def _progress_screens(*, app: SloTUI) -> list[SessionProgressScreen]:
    """Return every progress screen on the stack.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        list[SessionProgressScreen]: Progress screens, bottom first.
    """
    return [screen for screen in app.screen_stack if isinstance(screen, SessionProgressScreen)]


class TestObservationLifecycle:
    """One coordinator per owner: one 5.0 s timer, retention at prompt end, ordered teardown."""

    @pytest.mark.asyncio
    async def test_mount_registers_one_five_second_timer_and_paints_immediately(self, tmp_path: Path) -> None:
        """Mount registers exactly one 5.0 s observation interval and paints rows without any event."""
        supplier: _AttachedSupplier = _AttachedSupplier()
        supplier.publish(children=2)
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path, supplier=supplier))

        with patch.object(SloTUI, "set_interval", autospec=True, side_effect=SloTUI.set_interval) as interval:
            async with app.run_test(size=(120, 40)) as pilot:
                await _settle(app=app, pilot=pilot)

                five_second: list[Any] = [
                    call for call in interval.call_args_list if call.kwargs.get("interval") == 5.0
                ]
                assert len(five_second) == 1
                assert five_second[0].kwargs["callback"] == _coordinator(app=app).request_refresh
                assert set(_rows(app=app)) == {app._session.session_id, "child-00", "child-01"}

    @pytest.mark.asyncio
    async def test_rows_survive_prompt_end_cleanup(self, tmp_path: Path) -> None:
        """Ordinary prompt end keeps the rows; only the visualizer launch guard resets."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            app._visualizer_launched_for_run = True

            with patch.object(_coordinator(app=app), "request_refresh"):
                await app._cleanup_sub_agent_state()
                await pilot.pause()

            assert app._visualizer_launched_for_run is False
            assert set(_rows(app=app)) == {app._session.session_id, "child-00", "child-01"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event",
        [
            AgentStreamEventDAO(kind="sub_agent_dispatch_started", metadata={}),
            AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child-00", task_id="t"),
            AgentStreamEventDAO(kind="sub_agent_completed", sub_agent_id="child-00", task_id="t"),
            AgentStreamEventDAO(kind="sub_agent_failed", sub_agent_id="child-00", task_id="t"),
            AgentStreamEventDAO(kind="sub_agent_aborted", sub_agent_id="child-00", task_id="t"),
        ],
        ids=["dispatch_started", "spawned", "completed", "failed", "aborted"],
    )
    async def test_lifecycle_events_request_one_refresh(
        self, tmp_path: Path, event: AgentStreamEventDAO
    ) -> None:
        """Dispatch start and every child lifecycle event ask the coordinator for a refresh."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with (
                patch.object(_coordinator(app=app), "request_refresh") as request,
                patch("src.tui.visualizer_launcher.VisualizerLauncher.launch", return_value=False),
            ):
                await app._render_event(event)

            request.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_content_event_requests_no_refresh(self, tmp_path: Path) -> None:
        """Child content never asks for a refresh."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            with patch.object(_coordinator(app=app), "request_refresh") as request:
                await app._render_event(
                    AgentStreamEventDAO(kind="text_delta", sub_agent_id="child-00", task_id="t", delta="x")
                )

            request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", ["dismissed", "resumed", "neither"])
    async def test_typed_dismiss_and_resume_results_route_to_service(
        self, tmp_path: Path, outcome: str
    ) -> None:
        """Typed slash results suppress or restore the group and refresh; untyped results do neither."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))
        result: SlashCommandResultDAO = SlashCommandResultDAO(
            rendered="workflow wf-1 updated",
            dismissed_workflow_id="wf-1" if outcome == "dismissed" else None,
            resumed_workflow_id="wf-1" if outcome == "resumed" else None,
        )

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert service is not None
            with (
                patch("src.tui.app.SlashRouter.dispatch", return_value=result),
                patch.object(service, "dismiss_group") as dismiss,
                patch.object(service, "resume_group") as resume,
                patch.object(_coordinator(app=app), "request_refresh") as request,
            ):
                await app._dispatch_slash_command(line="/workflows dismiss wf-1")

            assert dismiss.call_args_list == (
                [((), {"workflow_id": "wf-1"})] if outcome == "dismissed" else []
            )
            assert resume.call_args_list == ([((), {"workflow_id": "wf-1"})] if outcome == "resumed" else [])
            assert request.call_count == (0 if outcome == "neither" else 1)

    @pytest.mark.asyncio
    async def test_new_session_discards_old_projection(self, tmp_path: Path) -> None:
        """A list read still in flight at ``/new`` never paints into the new owner."""
        old_supplier: _AttachedSupplier = _AttachedSupplier()
        new_supplier: _AttachedSupplier = _AttachedSupplier()
        new_session: SloAgentSession = _build_session(workdir=tmp_path, supplier=new_supplier)
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path, supplier=old_supplier))

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            old_service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert old_service is not None
            gate: asyncio.Event = asyncio.Event()
            entered: asyncio.Event = asyncio.Event()
            real_load = old_service.load_session_snapshot

            async def gated_load() -> object:
                entered.set()
                await gate.wait()
                old_supplier.publish(children=3)
                return await real_load()

            with patch.object(old_service, "load_session_snapshot", new=gated_load):
                _coordinator(app=app).request_refresh()
                await entered.wait()
                with patch("src.tui.app.SloAgentSession.build", return_value=new_session):
                    replacing: asyncio.Task[None] = asyncio.create_task(
                        app._start_new_session(requested_name=None)
                    )
                    await asyncio.sleep(0)
                    gate.set()
                    await replacing
            await _settle(app=app, pilot=pilot)

            assert _rows(app=app) == {}
            assert app._workflow_app_service is not old_service
            assert await old_service.load_session_snapshot() == WorkflowSessionSnapshotDAO()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trigger", ["new_session", "unmount"])
    async def test_teardown_order_is_coordinator_service_sink_panel(
        self, tmp_path: Path, trigger: str
    ) -> None:
        """Owner replacement and unmount close coordinator, service, sink, then reset the panel."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))
        order: list[str] = []

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            coordinator: WorkflowProgressCoordinator = _coordinator(app=app)
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            sink = app._workflow_progress_sink
            panel: Optional[SubAgentFleetPanel] = app._fleet_panel
            assert service is not None and sink is not None and panel is not None
            real_close, real_service_close = coordinator.close, service.close
            real_dispose, real_reset = sink.dispose, panel.reset

            async def close() -> None:
                order.append("coordinator")
                await real_close()

            async def service_close() -> None:
                order.append("service")
                await real_service_close()

            def dispose() -> None:
                order.append("sink")
                real_dispose()

            async def reset() -> None:
                order.append("panel")
                await real_reset()

            coordinator.close = close  # type: ignore[method-assign]
            service.close = service_close  # type: ignore[method-assign]
            sink.dispose = dispose  # type: ignore[method-assign]
            panel.reset = reset  # type: ignore[method-assign]
            if trigger == "new_session":
                with patch(
                    "src.tui.app.SloAgentSession.build", return_value=_build_session(workdir=tmp_path)
                ):
                    await app._start_new_session(requested_name=None)
                assert order == ["coordinator", "service", "sink", "panel"]
                assert coordinator._closed is True and coordinator._task is None

        if trigger == "unmount":
            assert order == ["coordinator", "service", "sink", "panel"]


class TestProgressSelection:
    """Mouse and Enter open the exact session; Escape minimizes without aborting."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("activation", ["click", "enter"])
    async def test_activation_opens_progress_for_the_exact_key(self, tmp_path: Path, activation: str) -> None:
        """Click and Enter both open one progress screen keyed by the activated row."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=3)
            if activation == "click":
                await pilot.click(_row_widget(app=app, session_id="child-01"))
            else:
                assert app._fleet_panel is not None
                app._fleet_panel.focus_sessions()
                await pilot.press("down", "down", "enter")
            await _settle(app=app, pilot=pilot)

            [screen] = _progress_screens(app=app)
            assert screen.key == WorkflowSessionKeyDAO(
                orchestrator_session_id=app._session.session_id,
                session_id="child-01",
                attached_dispatch_id=_DISPATCH_ID,
            )
            assert app.screen is screen
            assert _coordinator(app=app)._selected == screen.key

    @pytest.mark.asyncio
    async def test_repeated_activation_never_stacks_screens(self, tmp_path: Path) -> None:
        """Activating the open row again keeps one screen."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            key: WorkflowSessionKeyDAO = _row_widget(app=app, session_id="child-00").row.key
            app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
            app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
            await _settle(app=app, pilot=pilot)

            assert len(_progress_screens(app=app)) == 1

    @pytest.mark.asyncio
    async def test_escape_minimizes_returns_focus_and_never_aborts(self, tmp_path: Path) -> None:
        """Escape closes observation only: no session abort, the list regains focus."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            await pilot.click(_row_widget(app=app, session_id="child-01"))
            await _settle(app=app, pilot=pilot)
            with (
                patch.object(app._session, "abort") as abort,
                patch.object(app, "_escalate_abort") as escalate,
            ):
                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)

            abort.assert_not_called()
            escalate.assert_not_called()
            assert _progress_screens(app=app) == []
            assert _coordinator(app=app)._selected is None
            assert app._fleet_panel is not None
            assert app.focused is not None and app._fleet_panel in app.focused.ancestors_with_self

    @pytest.mark.asyncio
    async def test_unrelated_modal_refuses_selection_and_stays_open(self, tmp_path: Path) -> None:
        """A selection behind an unrelated dialog shows a notice; the dialog is never popped."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await pilot.pause()
            with patch.object(app, "notify") as notify:
                app.post_message(
                    SubAgentFleetPanel.SessionSelected(
                        key=_row_widget(app=app, session_id="child-00").row.key
                    )
                )
                await _settle(app=app, pilot=pilot)

            assert app.screen is modal
            assert _progress_screens(app=app) == []
            assert _coordinator(app=app)._selected is None
            notify.assert_called_once()
            assert (
                notify.call_args.kwargs["message"] == "Close the current dialog before inspecting progress."
            )

    @pytest.mark.asyncio
    async def test_no_history_attached_session_shows_unavailable_progress(self, tmp_path: Path) -> None:
        """A session without history lists its children; progress is a fixed unavailable notice."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            await pilot.click(_row_widget(app=app, session_id="child-00"))
            await _settle(app=app, pilot=pilot)

            [screen] = _progress_screens(app=app)
            state: str = str(screen.query_one("#session-state", Static).render())
            assert "Progress unavailable; retrying." in state
            assert screen.query_one("#abort-child", Button).disabled is True
            assert screen.query_one(ProgressLog).lines == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize(
        ("width", "height"), [(60, 20), (80, 24), (120, 40)], ids=["60x20", "80x24", "120x40"]
    )
    async def test_modal_over_real_app_keeps_controls_reachable(
        self, tmp_path: Path, theme: Theme, width: int, height: int
    ) -> None:
        """Over the real app, both buttons fit on screen; one panel and the usage bar remain."""
        app: SloTUI = SloTUI(session=_build_session(workdir=tmp_path))

        async with app.run_test(size=(width, height)) as pilot:
            app.theme = theme.name
            await _populated_app(app=app, pilot=pilot, children=3)
            app.post_message(
                SubAgentFleetPanel.SessionSelected(key=_row_widget(app=app, session_id="child-00").row.key)
            )
            await _settle(app=app, pilot=pilot)

            [screen] = _progress_screens(app=app)
            for button in screen.query(Button):
                assert button.region.height >= 1
                assert button.region.right <= width and button.region.bottom <= height
            assert len(app.query(SubAgentFleetPanel)) == 1
            assert len(app.query(UsageStatusBar)) == 1
            await pilot.click("#minimize")
            await _settle(app=app, pilot=pilot)
            assert _progress_screens(app=app) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme", [SLO_DARK_THEME, SLO_DEFAULT_THEME], ids=lambda theme: theme.name)
    @pytest.mark.parametrize(
        ("width", "height"), [(60, 20), (80, 24), (120, 40)], ids=["60x20", "80x24", "120x40"]
    )
    async def test_queue_stays_above_input_with_list_and_modal(
        self, tmp_path: Path, theme: Theme, width: int, height: int
    ) -> None:
        """With the list showing, the queue sits above the input and survives a modal round trip."""
        session: SloAgentSession = _build_session(workdir=tmp_path)
        app: SloTUI = SloTUI(session=session)
        invoke_log: list[str] = []
        release: asyncio.Event = asyncio.Event()

        with patch.object(
            target=session, attribute="invoke", new=_recording_invoke(invoke_log=invoke_log, release=release)
        ):
            async with app.run_test(size=(width, height)) as pilot:
                app.theme = theme.name
                panel: SubAgentFleetPanel = await _populated_app(app=app, pilot=pilot, children=3)
                await _submit_prompt(app=app, pilot=pilot, text="first")
                await _submit_prompt(app=app, pilot=pilot, text="queued second")
                await _settle(app=app, pilot=pilot)

                assert app._input is not None
                [queued] = list(app.query(QueuedPromptBlock))
                usage: UsageStatusBar = app.query_one(UsageStatusBar)
                assert invoke_log == ["first"]
                assert len(app.query(SubAgentFleetPanel)) == 1
                assert queued.region.height >= 1
                assert queued.region.bottom <= app._input.region.y
                assert panel.region.y >= app._input.region.bottom
                assert usage.region.y >= panel.region.bottom
                assert usage.region.height >= 1 and usage.region.bottom <= height

                app.post_message(
                    SubAgentFleetPanel.SessionSelected(
                        key=_row_widget(app=app, session_id="child-00").row.key
                    )
                )
                await _settle(app=app, pilot=pilot)
                assert len(_progress_screens(app=app)) == 1
                await pilot.press("escape")
                await _settle(app=app, pilot=pilot)

                assert _progress_screens(app=app) == []
                assert list(app.query(QueuedPromptBlock)) == [queued]
                assert app._queued_prompt_text == "queued second"
                assert invoke_log == ["first"]
                release.set()
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: app._in_flight_task is None and app._queued_prompt_text is None,
                )
                assert invoke_log == ["first", "queued second"]


class TestProgressLifecycleEdges:
    """Removal closes the view to the prompt; deferred paint targets one screen object."""

    @pytest.mark.asyncio
    async def test_removed_selection_closes_view_and_focuses_empty_prompt(self, tmp_path: Path) -> None:
        """When the batch disappears the view closes, a notice shows and the empty list yields to the prompt."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            await pilot.click(_row_widget(app=app, session_id="child-00"))
            await _settle(app=app, pilot=pilot)
            _supplier(app=app).snapshot = AttachedDispatchSnapshotDAO.empty()
            with patch.object(app, "notify", wraps=app.notify) as notify:
                await _refresh(app=app, pilot=pilot)

            assert _progress_screens(app=app) == []
            assert (
                notify.call_args.kwargs["message"]
                == "This session is no longer in the current workflow list."
            )
            assert app.focused is app._input

    @pytest.mark.asyncio
    async def test_activating_a_row_whose_child_just_left_the_batch_closes_without_a_crash(
        self, tmp_path: Path
    ) -> None:
        """A painted row whose child left the batch opens and closes once, with a notice and list focus."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            key: WorkflowSessionKeyDAO = _row_widget(app=app, session_id="child-01").row.key
            _supplier(app=app).publish(children=1)
            with patch.object(app, "notify", wraps=app.notify) as notify:
                app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
                await _settle(app=app, pilot=pilot)
                await pilot.pause()

            assert app.return_code is None
            assert _progress_screens(app=app) == []
            assert app.screen_stack == [app.screen_stack[0]]
            assert (
                notify.call_args.kwargs["message"]
                == "This session is no longer in the current workflow list."
            )
            assert app._fleet_panel is not None
            assert app.focused is not None and app._fleet_panel in app.focused.ancestors_with_self

    @pytest.mark.asyncio
    async def test_deferred_paint_for_a_replaced_screen_with_the_same_key_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """A delayed delivery captured for a dismissed screen never paints, even with a matching key."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            key: WorkflowSessionKeyDAO = _row_widget(app=app, session_id="child-00").row.key
            app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
            await _settle(app=app, pilot=pilot)
            [old_screen] = _progress_screens(app=app)
            await pilot.press("escape")
            await _settle(app=app, pilot=pilot)
            app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
            await _settle(app=app, pilot=pilot)
            [new_screen] = _progress_screens(app=app)
            sink = app._workflow_progress_sink
            assert sink is not None and new_screen is not old_screen
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert service is not None
            snapshot = await service.load_session_progress(key=key)

            with (
                patch.object(old_screen, "apply_snapshot") as old_paint,
                patch.object(new_screen, "apply_snapshot") as new_paint,
            ):
                sink._deliver_progress(screen=old_screen, snapshot=snapshot)
                sink._deliver_progress(screen=new_screen, snapshot=snapshot)

            old_paint.assert_not_called()
            new_paint.assert_called_once_with(snapshot=snapshot)

    @pytest.mark.asyncio
    async def test_repeated_failures_notify_once_until_a_good_refresh(self, tmp_path: Path) -> None:
        """Unexpected refresh failures notify once per streak; a good list re-arms the notice."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert service is not None
            real_load = service.load_session_snapshot
            with patch.object(app, "notify") as notify:
                with patch.object(service, "load_session_snapshot", side_effect=RuntimeError("bug")):
                    await _refresh(app=app, pilot=pilot)
                    await _refresh(app=app, pilot=pilot)
                assert notify.call_count == 1
                with patch.object(service, "load_session_snapshot", new=real_load):
                    await _refresh(app=app, pilot=pilot)
                with patch.object(service, "load_session_snapshot", side_effect=RuntimeError("bug")):
                    await _refresh(app=app, pilot=pilot)

            assert notify.call_count == 2
            assert (
                notify.call_args.kwargs["message"]
                == "Progress refresh unavailable; retrying on the next tick."
            )

    @pytest.mark.asyncio
    async def test_minimize_never_pops_an_unrelated_modal_above_the_view(self, tmp_path: Path) -> None:
        """Closing an owned view covered by an unrelated dialog leaves that dialog open."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            app.post_message(
                SubAgentFleetPanel.SessionSelected(key=_row_widget(app=app, session_id="child-00").row.key)
            )
            await _settle(app=app, pilot=pilot)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await pilot.pause()

            _coordinator(app=app).minimize()
            await pilot.pause()

            assert app.screen is modal
            assert _coordinator(app=app)._selected is None
            with patch.object(_coordinator(app=app), "select") as select:
                modal.dismiss()
                await _settle(app=app, pilot=pilot)

            assert _progress_screens(app=app) == []
            assert app.screen_stack == [app.screen_stack[0]]
            assert app._fleet_panel is not None
            assert app.focused is not None and app._fleet_panel in app.focused.ancestors_with_self
            select.assert_not_called()

    @pytest.mark.asyncio
    async def test_removal_under_an_unrelated_modal_closes_the_view_once_uncovered(
        self, tmp_path: Path
    ) -> None:
        """A removal tick behind a dialog keeps it open; closing it removes the view and focuses the prompt."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            app.post_message(
                SubAgentFleetPanel.SessionSelected(key=_row_widget(app=app, session_id="child-00").row.key)
            )
            await _settle(app=app, pilot=pilot)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await pilot.pause()
            _supplier(app=app).snapshot = AttachedDispatchSnapshotDAO.empty()
            await _refresh(app=app, pilot=pilot)

            assert app.screen is modal
            with patch.object(_coordinator(app=app), "select") as select:
                modal.dismiss()
                await _settle(app=app, pilot=pilot)

            assert _progress_screens(app=app) == []
            assert app.focused is app._input
            select.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("replacement", ["dispatch", "execution"])
    async def test_incarnation_change_under_an_unrelated_modal_closes_the_view_once_uncovered(
        self, tmp_path: Path, replacement: str
    ) -> None:
        """A same-key new dispatch behind a dialog routes once; closing the dialog removes the view."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=1)
            key: WorkflowSessionKeyDAO = _row_widget(app=app, session_id="child-00").row.key
            app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
            await _settle(app=app, pilot=pilot)
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await pilot.pause()
            supplier: _AttachedSupplier = _supplier(app=app)
            if replacement == "dispatch":
                supplier.snapshot = supplier.snapshot.model_copy(
                    update={"dispatch_id": "5d6e7f80-9a1b-4c2d-8e3f-405162738495", "dispatch_sequence": 2}
                )
            else:
                supplier.snapshot = supplier.snapshot.model_copy(
                    update={
                        "entries": (
                            supplier.snapshot.entries[0].model_copy(update={"execution_id": str(uuid4())}),
                        )
                    }
                )
            await _refresh(app=app, pilot=pilot)
            assert _coordinator(app=app)._selected is None
            assert app.screen is modal
            with patch.object(_coordinator(app=app), "select") as select:
                modal.dismiss()
                await _settle(app=app, pilot=pilot)

            assert _progress_screens(app=app) == []
            assert app._fleet_panel is not None
            assert app.focused is not None and app._fleet_panel in app.focused.ancestors_with_self
            select.assert_not_called()

    @pytest.mark.asyncio
    async def test_view_opened_with_unknown_identity_routes_an_incarnation_change_when_its_row_appears(
        self, tmp_path: Path
    ) -> None:
        """A view whose row identity was unknown at open is never silently retargeted to a listed execution."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            sink = app._workflow_progress_sink
            assert sink is not None
            await _coordinator(app=app).close()
            key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
                orchestrator_session_id=app._session.session_id, session_id="child-00"
            )
            assert sink.open_progress(key=key) is True
            await _settle(app=app, pilot=pilot)
            row: WorkflowSessionRowDAO = WorkflowSessionRowDAO(
                key=key,
                dispatch_id=_DISPATCH_ID,
                role="child",
                status="running",
                task_text="t",
                task_text_complete=False,
            )
            with patch.object(app, "_on_progress_incarnation_changed") as handler:
                await sink.apply_sessions(snapshot=WorkflowSessionSnapshotDAO(rows=(row,)))

            handler.assert_called_once_with(key=key)


_CLEARED_ONE: str = "Hidden 1 workflow group(s). Execution continues. Use /workflows tui show to restore."


def _publish_finished(
    *, supplier: _AttachedSupplier, dispatch_id: str = _DISPATCH_ID, sequence: int = 1
) -> None:
    """Replace the attached batch with two terminal children.

    Args:
        supplier (_AttachedSupplier): Session supplier.
        dispatch_id (str, optional): Batch identity. Defaults to ``_DISPATCH_ID``.
        sequence (int, optional): Admission sequence. Defaults to 1.
    """
    supplier.snapshot = AttachedDispatchSnapshotDAO(
        dispatch_id=dispatch_id,
        dispatch_sequence=sequence,
        entries=tuple(
            SubAgentStatusDAO(
                task_id=f"task-{status}", session_id=f"child-{status}", status=status  # type: ignore[arg-type]
            )
            for status in ("completed", "failed")
        ),
    )


async def _finished_app(*, app: SloTUI, pilot: Pilot[None]) -> SubAgentFleetPanel:
    """Paint a finished attached batch through the production refresh path.

    Args:
        app (SloTUI): Running app.
        pilot (Pilot[None]): Active pilot.

    Returns:
        SubAgentFleetPanel: The populated panel.
    """
    await _settle(app=app, pilot=pilot)
    _publish_finished(supplier=_supplier(app=app))
    await _refresh(app=app, pilot=pilot)
    assert app._fleet_panel is not None
    assert set(_rows(app=app)) == {app._session.session_id, "child-completed", "child-failed"}
    return app._fleet_panel


def _transcript(*, app: SloTUI) -> list[str]:
    """Return every transcript line written through the adapter.

    Args:
        app (SloTUI): Mounted app.

    Returns:
        list[str]: Line contents in order.
    """
    assert app._adapter is not None
    return [content for content, _classes in app._adapter.lines]


class TestClearFinishedGroups:
    """``/workflows tui dismiss`` hides finished groups in memory through the real app (94.a.5)."""

    @pytest.mark.asyncio
    async def test_typed_command_removes_rows_and_collapses_the_panel(self, tmp_path: Path) -> None:
        """Typing the command clears the finished batch, renders one line and hides the panel."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            panel: SubAgentFleetPanel = await _finished_app(app=app, pilot=pilot)
            lines_before: int = len(_transcript(app=app))

            await _submit_prompt(app=app, pilot=pilot, text="/workflows tui dismiss")
            await _settle(app=app, pilot=pilot)

            assert _rows(app=app) == {}
            assert panel.display is False
            assert panel.region.height == 0
            assert app.focused is app._input
            new_lines: list[str] = _transcript(app=app)[lines_before:]
            assert _CLEARED_ONE in new_lines
            assert "" not in new_lines

    @pytest.mark.asyncio
    async def test_focused_list_returns_focus_to_the_prompt(self, tmp_path: Path) -> None:
        """When the emptied list held focus, focus returns to PromptInput."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            panel: SubAgentFleetPanel = await _finished_app(app=app, pilot=pilot)
            panel.query_one(FleetSessionList).focus()
            await pilot.pause()
            assert app._session_list_holds_focus()

            await app._dispatch_slash_command(line="/workflows tui dismiss")
            await _settle(app=app, pilot=pilot)

            assert panel.region.height == 0
            assert app.focused is app._input

    @pytest.mark.asyncio
    async def test_modal_keeps_focus_while_the_list_empties(self, tmp_path: Path) -> None:
        """Clearing behind an unrelated dialog never steals focus from it."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            panel: SubAgentFleetPanel = await _finished_app(app=app, pilot=pilot)
            panel.query_one(FleetSessionList).focus()
            await pilot.pause()
            modal: _BlockingModal = _BlockingModal()
            await app.push_screen(modal)
            await pilot.pause()
            focused_before = app.focused

            await app._dispatch_slash_command(line="/workflows tui dismiss")
            await _settle(app=app, pilot=pilot)

            assert app.screen is modal
            assert app.focused is focused_before
            assert app.focused is not app._input
            assert _rows(app=app) == {}

    @pytest.mark.asyncio
    async def test_coordinator_tick_does_not_resurrect_and_new_dispatch_shows(self, tmp_path: Path) -> None:
        """A five-second refresh keeps the batch hidden; the next attached dispatch paints normally."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _finished_app(app=app, pilot=pilot)
            await _submit_prompt(app=app, pilot=pilot, text="/workflows tui dismiss")
            await _settle(app=app, pilot=pilot)

            await _refresh(app=app, pilot=pilot)
            assert _rows(app=app) == {}
            _publish_finished(supplier=_supplier(app=app), dispatch_id=str(uuid4()), sequence=2)
            await _refresh(app=app, pilot=pilot)

            assert set(_rows(app=app)) == {app._session.session_id, "child-completed", "child-failed"}

    @pytest.mark.asyncio
    async def test_chain_step_in_hidden_dispatch_stays_hidden_until_show(self, tmp_path: Path) -> None:
        """A new chain member remains hidden until explicit restoration."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            supplier: _AttachedSupplier = _supplier(app=app)
            step_1 = SubAgentStatusDAO(task_id="task-1", session_id="step-1", status="completed")
            supplier.snapshot = AttachedDispatchSnapshotDAO(
                dispatch_id=_DISPATCH_ID, dispatch_sequence=1, entries=(step_1,)
            )
            await _refresh(app=app, pilot=pilot)
            await _submit_prompt(app=app, pilot=pilot, text="/workflows tui dismiss")
            await _settle(app=app, pilot=pilot)
            assert _rows(app=app) == {}

            step_2 = SubAgentStatusDAO(task_id="task-2", session_id="step-2", status="running")
            supplier.snapshot = AttachedDispatchSnapshotDAO(
                dispatch_id=_DISPATCH_ID, dispatch_sequence=1, entries=(step_1, step_2)
            )
            await _refresh(app=app, pilot=pilot)

            assert _rows(app=app) == {}
            await _submit_prompt(app=app, pilot=pilot, text="/workflows tui show")
            await _settle(app=app, pilot=pilot)
            assert set(_rows(app=app)) == {app._session.session_id, "step-1", "step-2"}
            assert app._fleet_panel is not None and app._fleet_panel.display is True
            assert app._fleet_panel.region.height > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("line", "target_id"),
        [("/workflows tui dismiss", None), ("/wf tui dismiss wf-1", "wf-1")],
        ids=["all", "target"],
    )
    async def test_request_routes_to_service_and_requests_one_refresh(
        self, tmp_path: Path, line: str, target_id: Optional[str]
    ) -> None:
        """The typed request reaches the service once, then one coalesced refresh is requested."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert service is not None
            await app.on_prompt_input_submitted(PromptInput.Submitted(text=line))
            await _settle(app=app, pilot=pilot)
            assert service.current_list_snapshot().rows == ()
            expected = (
                "No visible workflow groups to hide."
                if target_id is None
                else "No workflow wf-1 in this session list."
            )
            assert _transcript(app=app).count(expected) == 1

    @pytest.mark.asyncio
    async def test_running_target_hides_without_changing_registry(self, tmp_path: Path) -> None:
        """A running batch can be hidden without altering execution evidence."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _populated_app(app=app, pilot=pilot, children=2)
            owner: str = app._session.session_id

            await app._dispatch_slash_command(line=f"/workflows tui dismiss {owner}")
            await _refresh(app=app, pilot=pilot)

            assert _transcript(app=app)[-1] == _CLEARED_ONE
            assert _rows(app=app) == {}
            assert _supplier(app=app).snapshot.entries[1].status == "running"

    @pytest.mark.asyncio
    async def test_empty_observation_reports_nothing_to_hide(self, tmp_path: Path) -> None:
        """A real empty owner gives truthful zero feedback."""
        app = _ListApp(workdir=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/workflows tui dismiss"))
            assert _transcript(app=app)[-1] == "No visible workflow groups to hide."

    @pytest.mark.asyncio
    async def test_bad_tui_usage_renders_usage_without_touching_the_service(self, tmp_path: Path) -> None:
        """``/workflows tui`` alone renders the usage line and never calls the service."""
        app: SloTUI = _ListApp(workdir=tmp_path)

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(app=app, pilot=pilot)
            service: Optional[DetachedWorkflowAppService] = app._workflow_app_service
            assert service is not None
            before = service.current_list_snapshot()
            await app.on_prompt_input_submitted(PromptInput.Submitted(text="/workflows tui"))
            assert service.current_list_snapshot() == before
            assert _transcript(app=app)[-1].startswith("usage: /workflows [")


async def test_hide_selected_row_acknowledges_once(tmp_path: Path) -> None:
    """Semantic submission while the modal covers the editor retires it and acknowledges once."""
    app = _ListApp(workdir=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _populated_app(app=app, pilot=pilot, children=2)
        key = _row_widget(app=app, session_id="child-01").row.key
        app.post_message(SubAgentFleetPanel.SessionSelected(key=key))
        await _settle(app=app, pilot=pilot)
        assert len(_progress_screens(app=app)) == 1
        await app.on_prompt_input_submitted(PromptInput.Submitted(text="/workflows tui dismiss"))
        await _settle(app=app, pilot=pilot)
        assert _progress_screens(app=app) == []
        assert _rows(app=app) == {}
        assert _transcript(app=app).count(_CLEARED_ONE) == 1
        assert "Workflow visibility saved; display refresh pending." not in _transcript(app=app)
        assert app.focused is app._input
        await app.on_prompt_input_submitted(PromptInput.Submitted(text="/workflows tui show"))
        await _settle(app=app, pilot=pilot)
        assert app.focused is app._input
        assert _progress_screens(app=app) == []
        assert _supplier(app=app).snapshot.entries[1].status == "running"


@pytest.mark.parametrize("line", ["/wf tui\tshow", "/workflows\ttui\tshow", "/wf  tui  show  "])
async def test_public_tab_grammar_restores_hidden_attached_owner(tmp_path: Path, line: str) -> None:
    """General whitespace and aliases reach the real no-history visibility owner."""
    app = _ListApp(workdir=tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await _populated_app(app=app, pilot=pilot, children=1)
        await app.on_prompt_input_submitted(PromptInput.Submitted(text="/wf\ttui\tdismiss"))
        await _settle(app=app, pilot=pilot)
        assert _rows(app=app) == {}
        await app.on_prompt_input_submitted(PromptInput.Submitted(text=line))
        await _settle(app=app, pilot=pilot)
        assert len(_rows(app=app)) == 2
        assert (
            _transcript(app=app).count(
                "Shown 1 previously hidden workflow group(s). Retained rows may be stale."
            )
            == 1
        )
