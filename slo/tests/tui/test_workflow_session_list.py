"""Session list layout inside the real ``SloTUI`` composition (feature 94 a.2).

Ticket T07 scope: the redesigned panel's geometry, paint and editor coexistence
in the production composition, with snapshots handed straight to the app's
``_apply_session_snapshot`` seam. The real-app gate (service wiring, refresh
coordinator, modal, retention on prompt cleanup, ``/new``) is completed by
ticket T08 in this same file; nothing here claims that gate.

No test touches files outside ``tmp_path``, providers, processes or terminals.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.theme import Theme
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.sub_agent_fleet_panel import FleetSessionList, SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.widgets.usage_status_bar import UsageStatusBar
from src.tui.workflows.dao import WorkflowSessionKeyDAO, WorkflowSessionRowDAO, WorkflowSessionSnapshotDAO
from tests.tui.authentication._painted_output import painted_widget_strips


def _build_session(*, workdir: Path) -> SloAgentSession:
    """Build a faux-backed session rooted in the test's temporary directory.

    Args:
        workdir (Path): Test-owned working directory.

    Returns:
        SloAgentSession: Session with no real model calls.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="ok")])),
        workdir=workdir,
        session_id=str(uuid4()),
    )


def _fleet_snapshot(*, parent_id: str, children: int) -> WorkflowSessionSnapshotDAO:
    """Build the parent row plus ``children`` child rows with distinct task text.

    Args:
        parent_id (str): Orchestrator session id.
        children (int): Number of child rows.

    Returns:
        WorkflowSessionSnapshotDAO: Ordered snapshot.
    """
    parent: WorkflowSessionRowDAO = WorkflowSessionRowDAO(
        key=WorkflowSessionKeyDAO(orchestrator_session_id=parent_id, session_id=parent_id),
        role="orchestrator",
        status="running",
        task_text="",
        task_text_complete=False,
    )
    child_rows: tuple[WorkflowSessionRowDAO, ...] = tuple(
        WorkflowSessionRowDAO(
            key=WorkflowSessionKeyDAO(orchestrator_session_id=parent_id, session_id=f"child-{index:02d}"),
            role="child",
            status="aborted" if index == 0 else "running",
            task_text=f"[b]task[/b] number {index}",
            task_text_complete=True,
        )
        for index in range(children)
    )
    return WorkflowSessionSnapshotDAO(rows=(parent, *child_rows))


def _painted_text(*, app: SloTUI, widget: Static | SubAgentFleetRow) -> str:
    """Return one widget's painted cells as text.

    Args:
        app (SloTUI): Running app.
        widget (Static | SubAgentFleetRow): Widget to read.

    Returns:
        str: Painted text, outer blanks removed.
    """
    return "".join(strip.text for strip in painted_widget_strips(app=app, widget=widget)).strip()


async def _populated_app(*, app: SloTUI, children: int) -> SubAgentFleetPanel:
    """Apply a fleet snapshot through the app seam and return the panel.

    Args:
        app (SloTUI): Running app.
        children (int): Number of child rows.

    Returns:
        SubAgentFleetPanel: The single mounted panel.
    """
    await app._apply_session_snapshot(
        snapshot=_fleet_snapshot(parent_id=app._session.session_id, children=children)
    )
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
            panel: SubAgentFleetPanel = await _populated_app(app=app, children=20)
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
            panel: SubAgentFleetPanel = await _populated_app(app=app, children=2)
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
            panel: SubAgentFleetPanel = await _populated_app(app=app, children=5)
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
            panel: SubAgentFleetPanel = await _populated_app(app=app, children=5)
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
            await _populated_app(app=app, children=3)
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
            panel: SubAgentFleetPanel = await _populated_app(app=app, children=3)
            assert app._input is not None
            app._input.focus()
            await pilot.pause()
            session_list: FleetSessionList = panel.query_one(FleetSessionList)
            before: tuple[int | None, int] = (session_list.index, session_list.navigation_revision)

            await pilot.press("down", "up", "left", "right")
            await pilot.pause()

            assert (session_list.index, session_list.navigation_revision) == before
            assert app.focused is app._input
