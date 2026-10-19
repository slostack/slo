"""Mounted tests for the workflow session list (feature 94 a.2, ticket T07).

``SubAgentFleetPanel`` is a presentation-only snapshot consumer: a heading and
one stable native ``ListView`` of ``SubAgentFleetRow`` items. These tests mount
the panel in a small host app that loads the production ``app.tcss`` so paint,
focus, key, mouse and wheel claims run against real Textual behaviour. Layout
claims that depend on the real editor/usage composition run inside ``SloTUI``.
No test touches files, processes, providers or terminals.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import patch

import pytest
from textual import events, on
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Static, TextArea

from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.sub_agent_fleet_panel import FleetSessionList, SubAgentFleetPanel
from src.tui.widgets.sub_agent_fleet_row import SubAgentFleetRow
from src.tui.workflows.dao import WorkflowSessionKeyDAO, WorkflowSessionRowDAO, WorkflowSessionSnapshotDAO
from tests.tui.authentication._painted_output import painted_widget_strips

APP_TCSS: Path = Path(__file__).resolve().parents[2] / "src" / "tui" / "app.tcss"
"""Production stylesheet, loaded by the host so layout rules are the real ones."""

ORCHESTRATOR_ID: str = "orch-1"
"""Parent session id shared by every row built in this module."""


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _row(
    *,
    session_id: str,
    task_text: str = "",
    status: str = "running",
    orchestrator_session_id: str = ORCHESTRATOR_ID,
) -> WorkflowSessionRowDAO:
    """Build one presentation row; the parent role follows the key.

    Args:
        session_id (str): Row session id; equal to the parent id for the parent row.
        task_text (str, optional): Task label source. Defaults to ``""``.
        status (str, optional): Display status. Defaults to ``"running"``.
        orchestrator_session_id (str, optional): Parent id. Defaults to ``ORCHESTRATOR_ID``.

    Returns:
        WorkflowSessionRowDAO: Frozen row.
    """
    key: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
        orchestrator_session_id=orchestrator_session_id,
        session_id=session_id,
    )
    return WorkflowSessionRowDAO(
        key=key,
        role="orchestrator" if key.is_parent else "child",
        status=status,
        task_text=task_text,
        task_text_complete=bool(task_text),
    )


class _ThemedHost(App[None]):
    """Load ``app.tcss`` with both Slo themes registered, as ``SloTUI`` does."""

    CSS_PATH = str(APP_TCSS)

    def __init__(self) -> None:
        """Register the Slo themes before the stylesheet resolves theme variables."""
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = SLO_DARK_THEME.name


class _RowHost(_ThemedHost):
    """Mount rows directly so the row's paint is tested before the panel exists."""

    def __init__(self, *, rows: list[SubAgentFleetRow]) -> None:
        """Keep the rows to mount.

        Args:
            rows (list[SubAgentFleetRow]): Rows yielded at compose.
        """
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        """Yield each row as a top-level widget."""
        yield from self._rows


def _painted(*, app: App, widget: Widget) -> str:
    """Return the painted text of one widget, trailing blanks removed.

    Args:
        app (App): Running host app.
        widget (Widget): Widget whose compositor cells are read.

    Returns:
        str: Painted row text.
    """
    return "".join(strip.text for strip in painted_widget_strips(app=app, widget=widget)).strip()


# ---------------------------------------------------------------------------
# SubAgentFleetRow
# ---------------------------------------------------------------------------


class TestSubAgentFleetRow:
    """One literal ``[status] session_id: task`` row per snapshot row."""

    @pytest.mark.asyncio
    async def test_child_row_paints_status_session_and_task(self) -> None:
        """A child row paints its literal status, unclipped session id and task."""
        row: SubAgentFleetRow = SubAgentFleetRow(row=_row(session_id="child-1", task_text="Audit the parser"))

        async with _RowHost(rows=[row]).run_test(size=(120, 10)) as pilot:
            await pilot.pause()
            assert _painted(app=pilot.app, widget=row) == "[running] child-1: Audit the parser"

    @pytest.mark.asyncio
    async def test_parent_row_label_is_exactly_orchestrator(self) -> None:
        """The parent row ignores task text and paints exactly ``Orchestrator``."""
        row: SubAgentFleetRow = SubAgentFleetRow(
            row=_row(session_id=ORCHESTRATOR_ID, task_text="ignored", status="completed")
        )

        async with _RowHost(rows=[row]).run_test(size=(120, 10)) as pilot:
            await pilot.pause()
            assert _painted(app=pilot.app, widget=row) == f"[completed] {ORCHESTRATOR_ID}: Orchestrator"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_text", ["", "   \n\t ", "\x1b\x07\x9b"], ids=["empty", "blank", "controls"]
    )
    async def test_child_without_displayable_task_uses_fallback(self, task_text: str) -> None:
        """Empty, whitespace-only and control-only task text fall back to the fixed label."""
        row: SubAgentFleetRow = SubAgentFleetRow(row=_row(session_id="child-1", task_text=task_text))

        async with _RowHost(rows=[row]).run_test(size=(120, 10)) as pilot:
            await pilot.pause()
            assert _painted(app=pilot.app, widget=row) == "[running] child-1: Task details unavailable"

    @pytest.mark.asyncio
    async def test_markup_and_controls_render_literally(self) -> None:
        """Markup stays literal, controls are stripped and whitespace collapses to one line."""
        task_text: str = "[bold]fix[/bold]\n\x1b]8;;http://x\x07 [link] \t done"
        row: SubAgentFleetRow = SubAgentFleetRow(row=_row(session_id="child-1", task_text=task_text))

        async with _RowHost(rows=[row]).run_test(size=(120, 10)) as pilot:
            await pilot.pause()
            assert _painted(app=pilot.app, widget=row) == (
                "[running] child-1: [bold]fix[/bold] ]8;;http://x [link] done"
            )

    @pytest.mark.asyncio
    async def test_long_task_is_capped_at_150_code_points(self) -> None:
        """A 151-code-point task paints 149 code points plus one ellipsis."""
        row: SubAgentFleetRow = SubAgentFleetRow(row=_row(session_id="child-1", task_text="é" * 151))

        async with _RowHost(rows=[row]).run_test(size=(220, 10)) as pilot:
            await pilot.pause()
            assert _painted(app=pilot.app, widget=row) == "[running] child-1: " + "é" * 149 + "…"

    @pytest.mark.asyncio
    async def test_apply_row_updates_label_in_place(self) -> None:
        """A same-key update repaints the same widget and replaces its stored row."""
        row: SubAgentFleetRow = SubAgentFleetRow(row=_row(session_id="child-1", task_text="Audit"))
        updated: WorkflowSessionRowDAO = _row(session_id="child-1", task_text="Audit", status="completed")

        async with _RowHost(rows=[row]).run_test(size=(120, 10)) as pilot:
            await pilot.pause()
            row.apply_row(row=updated)
            await pilot.pause()

            assert row.row is updated
            assert _painted(app=pilot.app, widget=row) == "[completed] child-1: Audit"


# ---------------------------------------------------------------------------
# SubAgentFleetPanel — snapshot application
# ---------------------------------------------------------------------------


def _snapshot(*, session_ids: list[str], status: str = "running") -> WorkflowSessionSnapshotDAO:
    """Build a snapshot with one child row per session id (parent id gets the parent row).

    Args:
        session_ids (list[str]): Row session ids in display order.
        status (str, optional): Status for every row. Defaults to ``"running"``.

    Returns:
        WorkflowSessionSnapshotDAO: Ordered snapshot.
    """
    return WorkflowSessionSnapshotDAO(
        rows=tuple(
            _row(session_id=session_id, task_text=f"task {session_id}", status=status)
            for session_id in session_ids
        )
    )


def _children(*, count: int) -> list[str]:
    """Return ``count`` child session ids in display order.

    Args:
        count (int): Number of children.

    Returns:
        list[str]: ``child-00`` … ids.
    """
    return [f"child-{index:02d}" for index in range(count)]


def _key(*, session_id: str) -> WorkflowSessionKeyDAO:
    """Return the composite key of one row built by ``_row``.

    Args:
        session_id (str): Row session id.

    Returns:
        WorkflowSessionKeyDAO: Composite key under ``ORCHESTRATOR_ID``.
    """
    return WorkflowSessionKeyDAO(orchestrator_session_id=ORCHESTRATOR_ID, session_id=session_id)


class _PanelHost(_ThemedHost):
    """Editor above one panel, recording every ``SessionSelected`` key."""

    def __init__(self) -> None:
        """Create the editor and panel under test."""
        super().__init__()
        self.editor: TextArea = TextArea()
        self.panel: SubAgentFleetPanel = SubAgentFleetPanel()
        self.selected: list[WorkflowSessionKeyDAO] = []

    def compose(self) -> ComposeResult:
        """Yield the editor first so Tab moves from it into the list."""
        yield self.editor
        yield self.panel

    @on(SubAgentFleetPanel.SessionSelected)
    def _record_selection(self, event: SubAgentFleetPanel.SessionSelected) -> None:
        """Record the emitted key.

        Args:
            event (SubAgentFleetPanel.SessionSelected): Semantic selection.
        """
        self.selected.append(event.key)


def _list(*, host: _PanelHost) -> FleetSessionList:
    """Return the panel's single mounted list.

    Args:
        host (_PanelHost): Running host.

    Returns:
        FleetSessionList: The list.
    """
    return host.panel.query_one(FleetSessionList)


def _row_widgets(*, host: _PanelHost) -> list[SubAgentFleetRow]:
    """Return the mounted row widgets in display order.

    Args:
        host (_PanelHost): Running host.

    Returns:
        list[SubAgentFleetRow]: Mounted rows.
    """
    return list(_list(host=host).query(SubAgentFleetRow))


def _selected_session(*, host: _PanelHost) -> Optional[str]:
    """Return the highlighted row's session id, or None.

    Args:
        host (_PanelHost): Running host.

    Returns:
        Optional[str]: Highlighted session id.
    """
    item = _list(host=host).highlighted_child
    return item.row.key.session_id if isinstance(item, SubAgentFleetRow) else None


class TestSnapshotApplication:
    """``apply_snapshot`` keeps one list, stable widgets and the selected key."""

    @pytest.mark.asyncio
    async def test_empty_panel_is_hidden(self) -> None:
        """A fresh and an empty-snapshot panel are hidden and hold no rows."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert host.panel.display is False
            await host.panel.apply_snapshot(snapshot=WorkflowSessionSnapshotDAO())
            await pilot.pause()
            assert host.panel.display is False
            assert _row_widgets(host=host) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("count", [1, 20])
    async def test_rows_mount_in_snapshot_order_under_heading(self, count: int) -> None:
        """One and twenty rows mount in order under the fixed heading."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=count)))
            await pilot.pause()

            assert host.panel.display is True
            assert [item.row.key.session_id for item in _row_widgets(host=host)] == _children(count=count)
            heading: Static = host.panel.query_one(".workflow-sessions-heading", Static)
            assert "".join(
                strip.text for strip in painted_widget_strips(app=host, widget=heading)
            ).strip() == ("Ongoing workflow tasks")
            assert _selected_session(host=host) == "child-00"

    @pytest.mark.asyncio
    async def test_same_keys_update_widgets_in_place(self) -> None:
        """Unchanged key order keeps every widget and repaints only the label."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=3)))
            before: list[SubAgentFleetRow] = _row_widgets(host=host)
            await host.panel.apply_snapshot(
                snapshot=_snapshot(session_ids=_children(count=3), status="completed")
            )
            await pilot.pause()

            after: list[SubAgentFleetRow] = _row_widgets(host=host)
            assert [id(item) for item in after] == [id(item) for item in before]
            assert {item.row.status for item in after} == {"completed"}
            assert _painted(app=host, widget=after[1]) == "[completed] child-01: task child-01"

    @pytest.mark.asyncio
    async def test_added_row_keeps_selected_key(self) -> None:
        """A row inserted before the selection keeps the same key selected."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=["child-a", "child-b"]))
            _list(host=host).index = 1
            await pilot.pause()
            await host.panel.apply_snapshot(
                snapshot=_snapshot(session_ids=["child-new", "child-a", "child-b"])
            )
            await pilot.pause()

            assert _selected_session(host=host) == "child-b"
            assert _list(host=host).index == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("remaining", "selected_before", "selected_after"),
        [
            (["child-a", "child-c", "child-d"], 1, "child-c"),
            (["child-a", "child-b"], 3, "child-b"),
        ],
        ids=["next-at-former-index", "clamped-to-last"],
    )
    async def test_removed_selection_falls_back_to_former_index(
        self, remaining: list[str], selected_before: int, selected_after: str
    ) -> None:
        """A vanished selected key selects the row now at its former index, clamped."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(
                snapshot=_snapshot(session_ids=["child-a", "child-b", "child-c", "child-d"])
            )
            _list(host=host).index = selected_before
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=remaining))
            await pilot.pause()

            assert _selected_session(host=host) == selected_after

    @pytest.mark.asyncio
    async def test_empty_snapshot_hides_populated_panel(self) -> None:
        """Removing every row hides the panel and clears the selection."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=2)))
            await host.panel.apply_snapshot(snapshot=WorkflowSessionSnapshotDAO())
            await pilot.pause()

            assert host.panel.display is False
            assert _row_widgets(host=host) == []
            assert _list(host=host).index is None

    @pytest.mark.asyncio
    async def test_duplicate_keys_mount_once(self) -> None:
        """A snapshot repeating a key mounts the first occurrence only."""
        host: _PanelHost = _PanelHost()
        first: WorkflowSessionRowDAO = _row(session_id="child-a", task_text="first")
        duplicate: WorkflowSessionRowDAO = _row(session_id="child-a", task_text="second", status="failed")

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await host.panel.apply_snapshot(
                snapshot=WorkflowSessionSnapshotDAO(rows=(first, _row(session_id="child-b"), duplicate))
            )
            await pilot.pause()

            assert [item.row for item in _row_widgets(host=host)] == [first, _row(session_id="child-b")]

    @pytest.mark.asyncio
    async def test_snapshot_never_steals_editor_focus(self) -> None:
        """Structural and in-place applications leave focus on the editor."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            host.editor.focus()
            await pilot.pause()
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=3)))
            await host.panel.apply_snapshot(
                snapshot=_snapshot(session_ids=_children(count=3), status="failed")
            )
            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=5)))
            await pilot.pause()

            assert host.focused is host.editor


# ---------------------------------------------------------------------------
# Navigation — focus-local keys, mouse and wheel
# ---------------------------------------------------------------------------


async def _post_wheel(*, pilot: Pilot, target: FleetSessionList, direction: str) -> None:
    """Deliver one native wheel event to the list and let it settle.

    Pilot has no wheel helper, so the event Textual's driver would forward to the
    widget under the pointer is posted to the list itself.

    Args:
        pilot (Pilot): Active pilot.
        target (FleetSessionList): List under the pointer.
        direction (str): ``up`` or ``down``.
    """
    event_type: type[events.MouseScrollDown] | type[events.MouseScrollUp] = (
        events.MouseScrollDown if direction == "down" else events.MouseScrollUp
    )
    target.post_message(
        event_type(
            widget=target,
            x=1,
            y=1,
            delta_x=0,
            delta_y=1 if direction == "down" else -1,
            button=0,
            shift=False,
            meta=False,
            ctrl=False,
        )
    )
    await pilot.pause()


async def _mounted_panel(
    *, pilot: Pilot, host: _PanelHost, count: int, focus: bool = True
) -> FleetSessionList:
    """Apply ``count`` child rows and optionally focus the list.

    Args:
        pilot (Pilot): Active pilot.
        host (_PanelHost): Running host.
        count (int): Number of child rows.
        focus (bool, optional): Whether to focus the list. Defaults to True.

    Returns:
        FleetSessionList: The populated list.
    """
    await pilot.pause()
    await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=count)))
    if focus:
        host.panel.focus_sessions()
    # Two refreshes: the post-layout offset restoration runs one hop behind
    # the native highlight scroll.
    await pilot.pause()
    await pilot.pause()
    return _list(host=host)


class TestNavigation:
    """Native ListView navigation with clamped ends and one semantic selection."""

    @pytest.mark.asyncio
    async def test_up_and_down_are_clamped(self) -> None:
        """Up at the top and Down at the bottom keep the end row selected (no wrap)."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=3)
            await pilot.press("up")
            assert session_list.index == 0
            await pilot.press("down", "down", "down", "down")
            assert session_list.index == 2
            await pilot.press("up")
            assert session_list.index == 1

    @pytest.mark.asyncio
    async def test_left_and_right_do_not_change_selection(self) -> None:
        """Left and Right leave the selection and focus unchanged."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=3)
            await pilot.press("down")
            await pilot.press("left", "right", "left")

            assert session_list.index == 1
            assert host.focused is session_list
            assert host.selected == []

    @pytest.mark.asyncio
    async def test_tab_enters_and_shift_tab_leaves_the_list(self) -> None:
        """Tab moves from the editor into the list; Shift+Tab returns to the editor."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=2, focus=False
            )
            host.editor.focus()
            await pilot.pause()
            await pilot.press("tab")
            assert host.focused is session_list
            await pilot.press("shift+tab")
            assert host.focused is host.editor

    @pytest.mark.asyncio
    async def test_empty_panel_is_not_focusable(self) -> None:
        """With zero rows neither ``focus_sessions`` nor Tab reaches the hidden list."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            host.editor.focus()
            host.panel.focus_sessions()
            await pilot.pause()
            assert host.focused is host.editor
            await pilot.press("tab")
            assert host.focused is not _list(host=host)

    @pytest.mark.asyncio
    async def test_enter_and_click_emit_the_same_exact_key(self) -> None:
        """Enter and a mouse click both emit ``SessionSelected`` with the unclipped key."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            await _mounted_panel(pilot=pilot, host=host, count=3)
            await pilot.press("down", "enter")
            await pilot.click(_row_widgets(host=host)[2])
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert host.selected == [
                _key(session_id="child-01"),
                _key(session_id="child-02"),
                _key(session_id="child-02"),
            ]

    @pytest.mark.asyncio
    async def test_twenty_rows_scroll_to_keep_selection_visible(self) -> None:
        """Twenty rows show five at a time and scroll as Down moves the selection."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=20)
            assert session_list.outer_size.height == 5
            for _ in range(12):
                await pilot.press("down")
            await pilot.pause()

            assert session_list.index == 12
            assert session_list.scroll_y > 0
            highlighted: SubAgentFleetRow = _row_widgets(host=host)[12]
            assert session_list.region.contains_region(highlighted.region)

    @pytest.mark.asyncio
    async def test_key_click_and_wheel_advance_the_revision_natively(self) -> None:
        """Each local input kind advances the revision without breaking native behaviour."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=20)
            start: int = session_list.navigation_revision
            await pilot.press("down")
            assert (session_list.navigation_revision, session_list.index) == (start + 1, 1)
            await pilot.click(_row_widgets(host=host)[3])
            await pilot.pause()
            assert session_list.navigation_revision > start + 1
            assert session_list.index == 3
            after_click: int = session_list.navigation_revision
            await _post_wheel(pilot=pilot, target=session_list, direction="down")
            assert session_list.navigation_revision == after_click + 1
            scrolled_y: float = session_list.scroll_y
            assert scrolled_y > 0
            await _post_wheel(pilot=pilot, target=session_list, direction="up")
            assert session_list.navigation_revision == after_click + 2
            assert session_list.scroll_y < scrolled_y


# ---------------------------------------------------------------------------
# Races — user navigation during a structural mount or before restoration
# ---------------------------------------------------------------------------


class _GatedExtend:
    """Hold ``FleetSessionList.extend`` after mounting until the test releases it.

    Models a structural refresh whose mount is still awaiting Textual when the
    user acts: the new rows exist, the index is not restored yet.
    """

    def __init__(self, *, session_list: FleetSessionList) -> None:
        """Wrap the list's native extend.

        Args:
            session_list (FleetSessionList): List whose extend is gated.
        """
        self._native_extend = session_list.extend
        self.mounted: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()

    async def __call__(self, items: list[SubAgentFleetRow]) -> None:
        """Mount natively, signal, then wait for release.

        Args:
            items (list[SubAgentFleetRow]): Rows to mount.
        """
        await self._native_extend(items)
        self.mounted.set()
        await self.release.wait()


async def _act(*, pilot: Pilot, host: _PanelHost, kind: str) -> None:
    """Perform one user input of ``kind`` on the populated list.

    Args:
        pilot (Pilot): Active pilot.
        host (_PanelHost): Running host.
        kind (str): ``key`` (Down), ``click`` (fourth visible row) or ``wheel`` (scroll down).
    """
    if kind == "key":
        await pilot.press("down")
        return
    if kind == "click":
        await pilot.pause()
        first_visible: int = int(_list(host=host).scroll_y)
        await pilot.click(_row_widgets(host=host)[first_visible + 3])
        await pilot.pause()
        return
    await _post_wheel(pilot=pilot, target=_list(host=host), direction="down")


class TestNavigationRaces:
    """The latest user navigation wins over a queued selection or scroll restoration."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kind", "expected"), [("key", "child-new"), ("click", "child-02"), ("wheel", "child-01")]
    )
    async def test_input_during_structural_mount_wins(self, kind: str, expected: str) -> None:
        """Input while new rows mount keeps the user's latest row, not a stale one.

        Key and click move the highlight, so their row wins; a wheel only
        scrolls, so the previously selected key stays selected.
        """
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=4)
            session_list.index = 1
            await pilot.pause()
            gate: _GatedExtend = _GatedExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=gate):
                apply = asyncio.create_task(
                    host.panel.apply_snapshot(
                        snapshot=_snapshot(session_ids=["child-new", *_children(count=4)])
                    )
                )
                await gate.mounted.wait()
                await _act(pilot=pilot, host=host, kind=kind)
                gate.release.set()
                await apply
            await pilot.pause()

            assert _selected_session(host=host) == expected

    @pytest.mark.asyncio
    async def test_structural_mount_without_input_restores_old_key(self) -> None:
        """Control: the same gated mount with no input restores the previously selected key."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=4)
            session_list.index = 1
            await pilot.pause()
            gate: _GatedExtend = _GatedExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=gate):
                apply = asyncio.create_task(
                    host.panel.apply_snapshot(
                        snapshot=_snapshot(session_ids=["child-new", *_children(count=4)])
                    )
                )
                await gate.mounted.wait()
                gate.release.set()
                await apply
            await pilot.pause()

            assert _selected_session(host=host) == "child-01"

    @pytest.mark.asyncio
    async def test_wheel_offset_survives_structural_refresh_with_offscreen_highlight(self) -> None:
        """A wheel-scrolled list keeps its offset; the off-screen highlight does not pull it back."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=20)
            assert session_list.index == 0
            for _ in range(4):
                await _post_wheel(pilot=pilot, target=session_list, direction="down")
            wheeled_y: float = session_list.scroll_y
            assert wheeled_y > session_list.outer_size.height

            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=21)))
            await pilot.pause()
            await pilot.pause()

            assert (session_list.scroll_y, _selected_session(host=host)) == (wheeled_y, "child-00")

    @pytest.mark.asyncio
    async def test_visible_highlight_stays_visible_across_structural_refresh(self) -> None:
        """Control: a highlighted row on screen keeps the same offset and stays on screen."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=20)
            for _ in range(8):
                await pilot.press("down")
            await pilot.pause()
            old_y: float = session_list.scroll_y
            assert old_y > 0

            await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=21)))
            await pilot.pause()
            await pilot.pause()

            highlighted: SubAgentFleetRow = _row_widgets(host=host)[8]
            assert (session_list.scroll_y, _selected_session(host=host)) == (old_y, "child-08")
            assert session_list.region.contains_region(highlighted.region)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["none", "key", "click", "wheel"])
    async def test_input_before_layout_restoration_cancels_it(self, kind: str) -> None:
        """Input after the rebuild but before the post-layout callback skips scroll restoration."""
        host: _PanelHost = _PanelHost()
        deferred: list[tuple[Callable[..., object], dict[str, object]]] = []

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(pilot=pilot, host=host, count=20)
            session_list.index = 10
            await pilot.pause()
            old_y: float = session_list.scroll_y
            assert old_y > 0
            native_after_refresh = session_list.call_after_refresh

            def _defer_panel_callbacks(
                callback: Callable[..., object], *args: object, **kwargs: object
            ) -> bool:
                """Hold the panel's restoration hops; pass native list callbacks through."""
                if getattr(callback, "__self__", None) is not host.panel:
                    return native_after_refresh(callback, *args, **kwargs)
                deferred.append((callback, kwargs))
                return True

            with patch.object(session_list, "call_after_refresh", new=_defer_panel_callbacks):
                await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=21)))
                await pilot.pause()
                session_list.scroll_to(y=0, animate=False, immediate=True)
                await pilot.pause()
                if kind != "none":
                    await _act(pilot=pilot, host=host, kind=kind)
                user_y: float = session_list.scroll_y
                while deferred:
                    callback, kwargs = deferred.pop(0)
                    callback(**kwargs)
            await pilot.pause()

            if kind == "none":
                assert session_list.scroll_y == old_y
                return
            assert session_list.scroll_y == user_y


# ---------------------------------------------------------------------------
# Reset — shielded application and no stale repaint
# ---------------------------------------------------------------------------


class TestReset:
    """``reset`` joins the in-flight application and always ends empty."""

    @pytest.mark.asyncio
    async def test_reset_waits_for_in_flight_apply_and_ends_empty(self) -> None:
        """A reset requested during a mount waits for it, then clears and hides the panel."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=2, focus=False
            )
            gate: _GatedExtend = _GatedExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=gate):
                apply = asyncio.create_task(
                    host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=5)))
                )
                await gate.mounted.wait()
                reset = asyncio.create_task(host.panel.reset())
                await pilot.pause()
                assert not reset.done()
                gate.release.set()
                await asyncio.gather(apply, reset)
            await pilot.pause()

            assert _row_widgets(host=host) == []
            assert host.panel.display is False

    @pytest.mark.asyncio
    async def test_cancelled_caller_cannot_repaint_after_reset(self) -> None:
        """Cancelling an apply caller mid-mount finishes that apply before reset; nothing repaints later."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=2, focus=False
            )
            gate: _GatedExtend = _GatedExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=gate):
                stale = asyncio.create_task(
                    host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=5)))
                )
                await gate.mounted.wait()
                stale.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await stale
                reset = asyncio.create_task(host.panel.reset())
                await pilot.pause()
                assert not reset.done()
                assert (
                    len(_row_widgets(host=host)) == 5
                ), "reset must not start before the shielded apply ends"
                gate.release.set()
                await reset
            await pilot.pause()
            await pilot.pause()

            assert _row_widgets(host=host) == []
            assert host.panel.display is False
            assert session_list.index is None


# ---------------------------------------------------------------------------
# Failed application — the next application and reset still work
# ---------------------------------------------------------------------------


class _PartiallyFailingExtend:
    """Mount only the first row, then raise once; later calls mount natively.

    Models a transient Textual mount failure that leaves the list partially
    populated, so the panel must not trust its own pre-mount bookkeeping.
    """

    def __init__(self, *, session_list: FleetSessionList) -> None:
        """Wrap the list's native extend.

        Args:
            session_list (FleetSessionList): List whose first extend fails.
        """
        self._native_extend = session_list.extend
        self.calls: int = 0

    async def __call__(self, items: list[SubAgentFleetRow]) -> None:
        """Fail the first call after a partial mount; delegate afterwards.

        Args:
            items (list[SubAgentFleetRow]): Rows to mount.

        Raises:
            RuntimeError: On the first call only, after mounting one row.
        """
        self.calls += 1
        if self.calls > 1:
            await self._native_extend(items)
            return
        await self._native_extend(items[:1])
        raise RuntimeError("mount failed once")


async def _fail_one_apply(*, pilot: Pilot, host: _PanelHost) -> None:
    """Run one structural application that fails partway through its mount.

    Requires ``_PartiallyFailingExtend`` installed on the list.

    Args:
        pilot (Pilot): Active pilot.
        host (_PanelHost): Running host.
    """
    with pytest.raises(RuntimeError, match="mount failed once"):
        await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=3)))
    await pilot.pause()


class TestFailedApplication:
    """One failed application reaches only its own caller and never wedges the panel."""

    @pytest.mark.asyncio
    async def test_later_apply_paints_new_rows_after_a_failed_apply(self) -> None:
        """After a partial mount failure, the next snapshot paints exactly its rows."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=0, focus=False
            )
            extend: _PartiallyFailingExtend = _PartiallyFailingExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=extend):
                await _fail_one_apply(pilot=pilot, host=host)
                await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=["a", "b"]))
            await pilot.pause()

            assert [row.row.key.session_id for row in _row_widgets(host=host)] == ["a", "b"]
            assert host.panel.display is True

    @pytest.mark.asyncio
    async def test_retrying_the_failed_snapshot_mounts_every_row(self) -> None:
        """Bookkeeping follows the mounted rows, so a retry of the same keys rebuilds them."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=0, focus=False
            )
            extend: _PartiallyFailingExtend = _PartiallyFailingExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=extend):
                await _fail_one_apply(pilot=pilot, host=host)
                await host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=3)))
            await pilot.pause()

            assert [row.row.key.session_id for row in _row_widgets(host=host)] == _children(count=3)

    @pytest.mark.asyncio
    async def test_reset_after_a_failed_apply_ends_empty_and_hidden(self) -> None:
        """Reset after a partial mount failure removes the stray row and hides the panel."""
        host: _PanelHost = _PanelHost()

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=0, focus=False
            )
            extend: _PartiallyFailingExtend = _PartiallyFailingExtend(session_list=session_list)
            with patch.object(session_list, "extend", new=extend):
                await _fail_one_apply(pilot=pilot, host=host)
                await host.panel.reset()
            await pilot.pause()

            assert _row_widgets(host=host) == []
            assert host.panel.display is False

    @pytest.mark.asyncio
    async def test_reset_joining_an_orphaned_failing_apply_still_ends_empty(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A cancelled caller's failing application is logged, never raised into the waiting reset."""
        host: _PanelHost = _PanelHost()
        failures: list[str] = []

        async with host.run_test(size=(120, 30)) as pilot:
            session_list: FleetSessionList = await _mounted_panel(
                pilot=pilot, host=host, count=2, focus=False
            )
            native_extend = session_list.extend
            gate: _GatedExtend = _GatedExtend(session_list=session_list)

            async def gated_then_failing(items: list[SubAgentFleetRow]) -> None:
                """Mount through the gate and fail once released; later mounts are native.

                Args:
                    items (list[SubAgentFleetRow]): Rows to mount.

                Raises:
                    RuntimeError: On the first call only, after the gate opens.
                """
                if failures:
                    await native_extend(items)
                    return
                failures.append("orphan")
                await gate(items)
                raise RuntimeError("mount failed after release")

            with patch.object(session_list, "extend", new=gated_then_failing):
                orphan = asyncio.create_task(
                    host.panel.apply_snapshot(snapshot=_snapshot(session_ids=_children(count=5)))
                )
                await gate.mounted.wait()
                orphan.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await orphan
                reset = asyncio.create_task(host.panel.reset())
                await pilot.pause()
                assert not reset.done()
                gate.release.set()
                await reset
            await pilot.pause()

            assert _row_widgets(host=host) == []
            assert host.panel.display is False
            assert "workflow_session_list_apply_failed" in caplog.messages
