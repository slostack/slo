"""HeadlessWorkflowVisualizer — read-only Textual TUI for ``slo visualize``.

A standalone Textual app that renders a headless orchestrator workflow:
  - Orchestrator pane (top, hidden by default): orchestrator system + user prompt.
  - Left pane: list of discovered child (sub-agent) sessions with status icons.
  - Right pane (top): transcript entries for the selected child (RichLog).
  - Right pane (bottom): stderr diagnostics for the selected child (RichLog).
  - Title bar: parent session id, model name, and working directory.
  - Sub-title: detail-mode format label (textual / markdown / html).
  - Status bar: workflow state, last refresh timestamp, follow mode, detail view.

Key bindings:
  q          — quit
  r          — force immediate refresh
  f          — toggle follow mode
  o          — toggle orchestrator context pane
  v          — toggle detail view (transcript ↔ invocation)
  t          — cycle detail pane format (textual → markdown → html)
  d          — toggle the diagnostics pane
  ctrl+left  — narrow the sub-agent list panel
  ctrl+right — widen the sub-agent list panel
  ctrl+up    — shrink the diagnostics pane
  ctrl+down  — grow the diagnostics pane

Sub-spec 53.a.5. Extended in 54.a.5 with orchestrator pane, invocation view,
prompt previews, thinking/reasoning formatting, and new key bindings. Extended
again with a workflow-summary bar, themed styling matching the main TUI,
markdown transcript rendering, coloured sub-agent status, and keyboard-resizable
panes.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Footer, Header, ListView, ListItem, Label, RichLog

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.orchestrator.dao import build_cleanup_summary
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.tree_export_format import TreeExportFormat
from src.tui.workflow_visualizer_loader import (
    ChildSessionSummaryDAO,
    HeadlessWorkflowVisualizerConfigDAO,
    OrchestratorNodeDAO,
    WorkflowDataDAO,
    WorkflowVisualizerLoader,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
    from src.agents.slo_agent.orchestrator.context_dao import SpawnContextDAO

__all__ = ["HeadlessWorkflowVisualizer"]

_STATUS_ICON: dict[str, str] = {
    "running": "⏳",
    "completed": "✓",
    "failed": "✗",
    "aborted": "⊘",
    "pending": "◌",
}

# Rich style per status, mirroring the main TUI's success/warning/muted palette
# so a glance at the sub-agent list reads the same as the orchestrator view.
_STATUS_STYLE: dict[str, str] = {
    "running": "yellow",
    "completed": "green",
    "failed": "red",
    "aborted": "red",
    "pending": "dim",
}

# Child-list panel width bounds and step (cells) for keyboard resizing.
_CHILD_PANEL_WIDTH_DEFAULT: int = 40
_CHILD_PANEL_WIDTH_MIN: int = 24
_CHILD_PANEL_WIDTH_MAX: int = 90
_CHILD_PANEL_WIDTH_STEP: int = 6

# Diagnostics-pane height bounds and step (cells) for keyboard resizing.
_DIAG_HEIGHT_DEFAULT: int = 10
_DIAG_HEIGHT_MIN: int = 3
_DIAG_HEIGHT_MAX: int = 40
_DIAG_HEIGHT_STEP: int = 3

# Ordered cycle for the `t` key binding.
_FORMAT_CYCLE: list[TreeExportFormat] = [
    TreeExportFormat.TEXTUAL,
    TreeExportFormat.MARKDOWN,
    TreeExportFormat.HTML,
]

_FORMAT_LABEL: dict[TreeExportFormat, str] = {
    TreeExportFormat.TEXTUAL: "textual",
    TreeExportFormat.MARKDOWN: "markdown",
    TreeExportFormat.HTML: "html (preview)",
}


class _LiveToolBuffers:
    """Accumulate one live tool invocation until its result arrives."""

    def __init__(self, *, tool_name: str) -> None:
        """Create an empty buffer for one streamed tool call.

        Args:
            tool_name (str): Name reported by the tool-call start event.
        """
        self.tool_name: str = tool_name
        self.arguments_chunks: list[str] = []

    def append_arguments(self, *, delta: str) -> None:
        """Record one incremental tool-arguments fragment.

        Args:
            delta (str): JSON/text fragment from a tool-call delta event.
        """
        self.arguments_chunks.append(delta)

    def build_call_entry(self) -> TranscriptEntryDAO:
        """Build the visible tool-call entry from buffered arguments.

        Returns:
            TranscriptEntryDAO: Tool-call entry matching capture projection.
        """
        raw_arguments: str = "".join(self.arguments_chunks)
        try:
            parsed_arguments: object = json.loads(raw_arguments)
        except (json.JSONDecodeError, ValueError):
            parsed_arguments = {"raw": raw_arguments}
        tool_input: dict[str, object] = (
            parsed_arguments if isinstance(parsed_arguments, dict) else {"raw": raw_arguments}
        )
        return TranscriptEntryDAO(
            kind="tool",
            tool_name=self.tool_name,
            tool_input=tool_input,
        )


class HeadlessWorkflowVisualizer(App[None]):
    """Read-only Textual TUI for inspecting headless workflow runs.

    Lays out a two-pane view: child session list on the left, transcript
    detail (top-right) and stderr diagnostics (bottom-right) on the right.
    When ``config.follow`` is ``True``, a background timer reloads the
    workflow data and refreshes all panes.

    CSS_PATH is intentionally not used — all sizing is inlined in
    ``DEFAULT_CSS`` so the widget is self-contained.
    """

    TITLE = "Slo — Workflow Visualizer"
    BINDINGS = [
        Binding(key="q", action="quit", description="Quit"),
        Binding(key="r", action="refresh", description="Refresh"),
        Binding(key="f", action="toggle_follow", description="Toggle follow"),
        Binding(key="o", action="toggle_orchestrator_context", description="Orchestrator ctx"),
        Binding(key="v", action="toggle_detail_view", description="Toggle detail view"),
        Binding(key="t", action="cycle_format", description="Cycle format"),
        Binding(key="d", action="toggle_diagnostics", description="Toggle diag"),
        Binding(key="ctrl+right", action="widen_child_panel", description="Wider list"),
        Binding(key="ctrl+left", action="narrow_child_panel", description="Narrower list"),
        Binding(key="ctrl+down", action="grow_diagnostics", description="Taller diag"),
        Binding(key="ctrl+up", action="shrink_diagnostics", description="Shorter diag"),
    ]

    DEFAULT_CSS = """
    HeadlessWorkflowVisualizer {
        layout: vertical;
        background: $surface;
    }
    Header {
        background: $surface;
    }
    Footer {
        background: $surface;
    }
    #workflow-summary {
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    #orchestrator-context-panel {
        height: 12;
        padding: 0 1;
        border: round $accent;
    }
    #orchestrator-context-panel.hidden {
        display: none;
    }
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }
    #child-list-panel {
        width: 40;
        min-width: 22;
        height: 100%;
        border-right: solid $accent;
    }
    #child-list-panel ListView {
        height: 1fr;
        background: $surface;
    }
    #child-list-panel ListView > ListItem {
        padding: 0 1;
    }
    #child-list-panel ListView > ListItem.--highlight {
        background: $boost;
    }
    #detail-panel {
        width: 1fr;
        height: 100%;
        layout: vertical;
    }
    #detail-log {
        height: 1fr;
        padding: 0 1;
        border-bottom: dashed $accent;
        background: $surface;
    }
    #diagnostics-log {
        height: 10;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    #diagnostics-log.hidden {
        display: none;
    }
    #diag-title.hidden {
        display: none;
    }
    #status-bar {
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
        dock: bottom;
    }
    #panel-title {
        background: $boost;
        color: $accent;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    #diag-title {
        background: $boost;
        color: $text-muted;
        padding: 0 1;
        height: 1;
    }
    """

    def __init__(
        self,
        *,
        config: HeadlessWorkflowVisualizerConfigDAO,
        loader: Optional[WorkflowVisualizerLoader] = None,
    ) -> None:
        """Bind the app to its config and optional loader override.

        Args:
            config (HeadlessWorkflowVisualizerConfigDAO): Visualizer config
                (session reference, follow mode, refresh interval, format).
            loader (Optional[WorkflowVisualizerLoader]): Override for tests;
                ``None`` constructs a default loader from ``config``.
        """
        super().__init__()
        self._config: HeadlessWorkflowVisualizerConfigDAO = config
        self._loader: WorkflowVisualizerLoader = loader or WorkflowVisualizerLoader(
            config=config,
        )
        self._workflow_data: Optional[WorkflowDataDAO] = None
        self._selected_child_index: int = 0
        self._follow: bool = config.follow
        self._last_refresh: Optional[datetime] = None
        self._detail_format: TreeExportFormat = config.detail_format
        self._diagnostics_visible: bool = True
        self._refresh_timer: Optional[Timer] = None
        self._orchestrator_context_visible: bool = False
        self._detail_view: Literal["transcript", "invocation"] = "transcript"
        self._child_panel_width: int = _CHILD_PANEL_WIDTH_DEFAULT
        self._diag_height: int = _DIAG_HEIGHT_DEFAULT
        self._live_entries: dict[str, list[TranscriptEntryDAO]] = {}
        self._live_open_assistant: set[str] = set()
        self._live_open_thinking: set[str] = set()
        self._live_tools: dict[str, dict[str, _LiveToolBuffers]] = {}

    def compose(self) -> ComposeResult:
        """Lay out the three-pane interface with orchestrator context panel.

        Returns:
            ComposeResult: Header, optional orchestrator pane, main horizontal
                layout, status bar, Footer.
        """
        yield Header()
        yield Label("Loading workflow …", id="workflow-summary")
        with Vertical(id="orchestrator-context-panel", classes="hidden"):
            yield RichLog(id="orchestrator-context-log", highlight=True, markup=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="child-list-panel"):
                yield Label("Sub-agents", id="panel-title")
                yield ListView(id="child-list")
            with Vertical(id="detail-panel"):
                yield RichLog(id="detail-log", highlight=True, markup=True)
                yield Label("Diagnostics (stderr)", id="diag-title")
                yield RichLog(id="diagnostics-log", highlight=False, markup=False)
        yield Label("Loading …", id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Load initial data, apply pane sizes, and start the follow timer."""
        self._apply_layout_sizes()
        await self._do_refresh()
        if self._follow and not self._workflow_data_is_terminal():
            self._start_refresh_timer()

    async def _on_timer(self) -> None:
        """Periodic follow-mode tick — reloads data and stops when complete."""
        if not self._follow:
            return
        await self._do_refresh()
        if self._workflow_data_is_terminal():
            self._stop_refresh_timer()

    def _start_refresh_timer(self) -> None:
        """Start the follow-mode polling timer, replacing any existing one."""
        self._stop_refresh_timer()
        self._refresh_timer = self.set_interval(
            interval=self._config.refresh_seconds,
            callback=self._on_timer,
        )

    def _stop_refresh_timer(self) -> None:
        """Stop the follow-mode polling timer if one is running."""
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    async def _do_refresh(self) -> None:
        """Reload workflow data from the loader and redraw all panes."""
        try:
            self._workflow_data = await self._loader.load()
        except Exception as exc:  # noqa: BLE001
            self._update_status_bar(f"[red]Load error: {exc}[/red]")
            return
        self._last_refresh = datetime.now()
        self._update_app_header()
        self._rebuild_summary_bar()
        await self._rebuild_child_list()
        await self._rebuild_detail_pane()
        self._rebuild_diagnostics_pane()
        self._rebuild_orchestrator_pane()
        self._update_status_bar_from_data()

    def _update_app_header(self) -> None:
        """Set the app title and sub_title to show parent session metadata."""
        if self._workflow_data is None:
            return
        parent_id: str = self._workflow_data.parent_session_id
        short_id: str = parent_id[:16] if len(parent_id) > 16 else parent_id
        self.title = f"Slo — session={short_id}"
        format_label: str = _FORMAT_LABEL.get(self._detail_format, "textual")
        self.sub_title = f"format={format_label}  " f"children={len(self._workflow_data.children)}"

    def _rebuild_summary_bar(self) -> None:
        """Rebuild the top workflow-summary bar from the current data snapshot.

        Shows the overall run state followed by a coloured tally of sub-agents
        by status (running / completed / failed) so the operator sees fleet
        health at a glance, mirroring the main TUI's status palette.
        """
        summary: Label = self.query_one("#workflow-summary", Label)
        if self._workflow_data is None:
            summary.update("Loading workflow …")
            return
        counts: dict[str, int] = self._status_counts()
        state_markup: str = (
            "[green]● complete[/green]" if self._workflow_data.is_complete else "[yellow]● running[/yellow]"
        )
        total: int = len(self._workflow_data.children)
        parts: list[str] = [
            state_markup,
            f"[bold]{total}[/bold] sub-agents",
            f"[yellow]⏳ {counts['running']}[/yellow]",
            f"[green]✓ {counts['completed']}[/green]",
            f"[red]✗ {counts['failed'] + counts['aborted']}[/red]",
        ]
        cleanup: Optional[str] = self._cleanup_summary()
        if cleanup is not None:
            parts.append(cleanup)
        summary.update("   ".join(parts))

    def _cleanup_summary(self) -> Optional[str]:
        """Return recorded fleet cleanup text for the summary bar when available."""
        if self._workflow_data is None or self._workflow_data.fleet_snapshot is None:
            return None
        entries = self._workflow_data.fleet_snapshot.entries
        live_count: int = sum(1 for entry in entries if entry.status == "running")
        summary: str = build_cleanup_summary(entries=entries, live_count=live_count)
        all_terminal: bool = all(entry.status in {"completed", "failed", "aborted"} for entry in entries)
        if self._workflow_data.is_complete and all_terminal:
            return summary + " · all sub-processes reaped ✓"
        return summary

    def _status_counts(self) -> dict[str, int]:
        """Tally the current children by status.

        Returns:
            dict[str, int]: Counts keyed by status name; every known status is
                present (zero when absent) so callers can index without guards.
        """
        counts: dict[str, int] = {
            "running": 0,
            "completed": 0,
            "failed": 0,
            "aborted": 0,
            "pending": 0,
        }
        if self._workflow_data is None:
            return counts
        for child in self._workflow_data.children:
            counts[child.status] = counts.get(child.status, 0) + 1
        return counts

    async def _rebuild_child_list(self) -> None:
        """Repopulate the left-pane child session list from current data."""
        list_view: ListView = self.query_one("#child-list", ListView)
        await list_view.clear()
        if not self._workflow_data:
            await list_view.append(ListItem(Label("[dim]No sub-agents found[/dim]")))
            return
        if self._workflow_data.orchestrator is not None:
            await list_view.append(
                ListItem(Label(self._orchestrator_label(node=self._workflow_data.orchestrator)))
            )
        if not self._workflow_data.children and self._workflow_data.orchestrator is None:
            await list_view.append(ListItem(Label("[dim]No sub-agents found[/dim]")))
            return
        for child in self._workflow_data.children:
            await list_view.append(ListItem(Label(self._child_label(child=child))))
        list_view.focus()

    async def _rebuild_detail_pane(self) -> None:
        """Reload the right-pane based on the active detail view mode."""
        detail_log: RichLog = self.query_one("#detail-log", RichLog)
        detail_log.clear()
        if not self._workflow_data:
            detail_log.write("[dim]Select a sub-agent to inspect its transcript.[/dim]")
            return
        orchestrator: Optional[OrchestratorNodeDAO] = self._current_orchestrator()
        if orchestrator is not None:
            self._render_live_entries(detail_log=detail_log, session_id=orchestrator.session_id)
            return
        child: Optional[ChildSessionSummaryDAO] = self._current_child()
        if child is None:
            detail_log.write("[dim]No sub-agent selected.[/dim]")
            return
        if self._detail_view == "invocation":
            spawn = self._loader.load_spawn_context(
                parent_session_id=self._workflow_data.parent_session_id,
                child_session_id=child.session_id,
            )
            self._render_invocation(detail_log=detail_log, spawn=spawn)
            return
        if child.status == "running":
            self._render_live_entries(detail_log=detail_log, session_id=child.session_id)
            return
        entries = await self._loader.load_child_transcript_entries(
            parent_session_id=self._workflow_data.parent_session_id,
            child_session_id=child.session_id,
        )
        if not entries:
            detail_log.write(f"[dim]No transcript entries for {child.session_id}.[/dim]")
            return
        for entry in entries:
            if self._detail_format == TreeExportFormat.TEXTUAL:
                self._write_entry_rich(detail_log=detail_log, entry=entry)
            else:
                detail_log.write(
                    self._format_transcript_entry(
                        entry=entry,
                        fmt=self._detail_format,
                    )
                )

    def _rebuild_diagnostics_pane(self) -> None:
        """Reload diagnostics for the selected child or orchestrator node."""
        diag_log: RichLog = self.query_one("#diagnostics-log", RichLog)
        diag_log.clear()
        if self._workflow_data is None:
            diag_log.write("No workflow loaded.")
            return
        orchestrator: Optional[OrchestratorNodeDAO] = self._current_orchestrator()
        child: Optional[ChildSessionSummaryDAO] = self._current_child()
        session_id: Optional[str] = (
            orchestrator.session_id
            if orchestrator is not None
            else child.session_id if child is not None else None
        )
        if session_id is None:
            diag_log.write("No node selected.")
            return
        lines: list[str] = self._loader.load_node_stderr_lines(
            parent_session_id=self._workflow_data.parent_session_id,
            session_id=session_id,
        )
        if not lines:
            diag_log.write(f"No stderr capture for {session_id[:8]}.")
            return
        for line in lines:
            diag_log.write(line)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Update the detail and diagnostics panes on child selection change.

        Args:
            event (ListView.Selected): Selection event from the child list.
        """
        if self._workflow_data is None:
            return
        self._selected_child_index = event.list_view.index or 0
        self.call_after_refresh(self._rebuild_detail_pane)
        self.call_after_refresh(self._rebuild_diagnostics_pane)

    async def action_refresh(self) -> None:
        """Key-binding action: force an immediate data reload."""
        await self._do_refresh()

    def action_toggle_follow(self) -> None:
        """Key-binding action: toggle follow mode on or off."""
        self._follow = not self._follow
        if self._follow and not self._workflow_data_is_terminal():
            self._start_refresh_timer()
        else:
            self._stop_refresh_timer()
        self._update_status_bar_from_data()

    async def action_cycle_format(self) -> None:
        """Key-binding action: advance the detail-pane format by one step.

        Cycles textual → markdown → html → textual and re-renders the pane.
        """
        current_index: int = _FORMAT_CYCLE.index(self._detail_format)
        next_index: int = (current_index + 1) % len(_FORMAT_CYCLE)
        self._detail_format = _FORMAT_CYCLE[next_index]
        self._update_app_header()
        await self._rebuild_detail_pane()

    def action_toggle_diagnostics(self) -> None:
        """Key-binding action: show or hide the stderr diagnostics pane."""
        self._diagnostics_visible = not self._diagnostics_visible
        diag_log: RichLog = self.query_one("#diagnostics-log", RichLog)
        diag_title: Label = self.query_one("#diag-title", Label)
        if self._diagnostics_visible:
            diag_log.remove_class("hidden")
            diag_title.remove_class("hidden")
        else:
            diag_log.add_class("hidden")
            diag_title.add_class("hidden")

    def action_toggle_orchestrator_context(self) -> None:
        """Key-binding action: show or hide the orchestrator context pane."""
        self._orchestrator_context_visible = not self._orchestrator_context_visible
        panel: Vertical = self.query_one("#orchestrator-context-panel", Vertical)
        if self._orchestrator_context_visible:
            panel.remove_class("hidden")
            self._rebuild_orchestrator_pane()
        else:
            panel.add_class("hidden")

    async def action_toggle_detail_view(self) -> None:
        """Key-binding action: toggle detail pane between transcript and invocation."""
        self._detail_view = "invocation" if self._detail_view == "transcript" else "transcript"
        await self._rebuild_detail_pane()
        self._update_status_bar_from_data()

    def action_widen_child_panel(self) -> None:
        """Key-binding action: widen the sub-agent list panel by one step."""
        self._child_panel_width = min(
            self._child_panel_width + _CHILD_PANEL_WIDTH_STEP,
            _CHILD_PANEL_WIDTH_MAX,
        )
        self._apply_layout_sizes()

    def action_narrow_child_panel(self) -> None:
        """Key-binding action: narrow the sub-agent list panel by one step."""
        self._child_panel_width = max(
            self._child_panel_width - _CHILD_PANEL_WIDTH_STEP,
            _CHILD_PANEL_WIDTH_MIN,
        )
        self._apply_layout_sizes()

    def action_grow_diagnostics(self) -> None:
        """Key-binding action: grow the diagnostics pane height by one step."""
        self._diag_height = min(
            self._diag_height + _DIAG_HEIGHT_STEP,
            _DIAG_HEIGHT_MAX,
        )
        self._apply_layout_sizes()

    def action_shrink_diagnostics(self) -> None:
        """Key-binding action: shrink the diagnostics pane height by one step."""
        self._diag_height = max(
            self._diag_height - _DIAG_HEIGHT_STEP,
            _DIAG_HEIGHT_MIN,
        )
        self._apply_layout_sizes()

    def _apply_layout_sizes(self) -> None:
        """Apply the stored pane sizes to the child-list and diagnostics widgets.

        Called on mount and after every resize action. Silently no-ops when the
        target widgets are not yet mounted so it is safe to call early.
        """
        try:
            self.query_one("#child-list-panel").styles.width = self._child_panel_width
            self.query_one("#diagnostics-log", RichLog).styles.height = self._diag_height
        except Exception:  # noqa: BLE001 — widgets may not be mounted yet.
            return

    # ── helpers ──────────────────────────────────────────────────────────────

    def _current_child(self) -> Optional[ChildSessionSummaryDAO]:
        """Return the currently selected child summary.

        Returns:
            Optional[ChildSessionSummaryDAO]: Selected child, or ``None``.
        """
        if not self._workflow_data or not self._workflow_data.children:
            return None
        offset: int = 1 if self._workflow_data.orchestrator is not None else 0
        if self._selected_child_index < offset:
            return None
        idx: int = min(self._selected_child_index - offset, len(self._workflow_data.children) - 1)
        return self._workflow_data.children[idx]

    def _current_orchestrator(self) -> Optional[OrchestratorNodeDAO]:
        """Return the orchestrator node when its first list row is selected."""
        if self._workflow_data is None or self._selected_child_index != 0:
            return None
        return self._workflow_data.orchestrator

    def _workflow_data_is_terminal(self) -> bool:
        """Return ``True`` when the loaded workflow has reached a terminal state.

        Returns:
            bool: ``True`` when the parent session is complete.
        """
        return self._workflow_data is not None and self._workflow_data.is_complete

    def _rebuild_orchestrator_pane(self) -> None:
        """Populate the orchestrator context log when the pane is visible.

        Renders the orchestrator system prompt and user prompt from
        ``WorkflowDataDAO.orchestrator_context`` when available.
        """
        if not self._orchestrator_context_visible:
            return
        log: RichLog = self.query_one("#orchestrator-context-log", RichLog)
        log.clear()
        if self._workflow_data is None or self._workflow_data.orchestrator_context is None:
            log.write(Text("No orchestrator context captured", style="dim"))
            return
        ctx = self._workflow_data.orchestrator_context
        table: Table = Table(show_header=False, expand=True)
        table.add_row("Model", ctx.model or "(unset)")
        table.add_row("Recorded", ctx.recorded_at)
        log.write(table)
        log.write(Text("─ System Prompt ─", style="bold dim"))
        log.write(Text(ctx.system_prompt[:300] or "(empty)", style="dim italic"))
        log.write(Text("─ User Prompt ─", style="bold dim"))
        log.write(Text(ctx.user_prompt or "(empty)"))

    @staticmethod
    def _render_invocation(
        *,
        detail_log: RichLog,
        spawn: "Optional[SpawnContextDAO]",
    ) -> None:
        """Render spawn invocation metadata into the detail log.

        Args:
            detail_log (RichLog): Target log widget to write into.
            spawn (Optional[SpawnContextDAO]): Loaded spawn context, or ``None``.
        """
        if spawn is None:
            detail_log.write(Text("No spawn context captured", style="dim"))
            return
        table: Table = Table(show_header=False, expand=True)
        table.add_row("Task ID", spawn.task_id)
        table.add_row("Model", spawn.model or "(inherited)")
        table.add_row("Reasoning level", spawn.reasoning_level or "default")
        table.add_row("Timeout", f"{spawn.inactivity_timeout_seconds:.1f}s")
        table.add_row("CWD", spawn.cwd or "(inherited)")
        detail_log.write(table)
        detail_log.write(Text("─ Prompt ─", style="bold dim"))
        detail_log.write(Text(spawn.prompt))
        detail_log.write(Text("─ System Prompt ─", style="bold dim"))
        sys_preview: str = spawn.system_prompt[:300]
        if len(spawn.system_prompt) > 300:
            sys_preview += "…"
        detail_log.write(Text(sys_preview, style="dim italic"))

    def _render_live_entries(self, *, detail_log: RichLog, session_id: str) -> None:
        """Read and render the selected live node's newly captured stdout entries."""
        self._append_live_stdout_events(session_id=session_id)
        entries: list[TranscriptEntryDAO] = self._live_entries.get(session_id, [])
        if not entries:
            detail_log.write(f"[dim]No transcript entries for {session_id}.[/dim]")
            return
        for entry in entries:
            self._write_entry_rich(detail_log=detail_log, entry=entry)

    def _append_live_stdout_events(self, *, session_id: str) -> None:
        """Coalesce new text deltas from the loader's incremental stdout tail."""
        lines: list[bytes] = self._loader.read_child_stdout_tail(session_id=session_id)
        for line in lines:
            try:
                event: AgentStreamEventDAO = AgentStreamEventDAO.model_validate_json(line)
            except ValueError:
                continue
            self._append_live_event(session_id=session_id, event=event)

    def _append_live_event(self, *, session_id: str, event: AgentStreamEventDAO) -> None:
        """Apply one captured stream event to a live node transcript.

        Args:
            session_id (str): Session that owns the captured event.
            event (AgentStreamEventDAO): Parsed stdout stream event.
        """
        if event.kind == "thinking_delta" and event.delta:
            self._append_live_thinking_delta(session_id=session_id, delta=event.delta)
            return
        if event.kind == "thinking_end":
            self._live_open_thinking.discard(session_id)
            return
        if event.kind == "text_delta" and event.delta:
            self._append_live_text_delta(session_id=session_id, delta=event.delta)
            return
        if event.kind == "tool_call_start" and event.block_id and event.tool_name:
            self._live_tools.setdefault(session_id, {})[event.block_id] = _LiveToolBuffers(
                tool_name=event.tool_name,
            )
            return
        if event.kind == "tool_call_delta" and event.block_id and event.tool_arguments_delta:
            buffers: Optional[_LiveToolBuffers] = self._live_tools.get(session_id, {}).get(event.block_id)
            if buffers is not None:
                buffers.append_arguments(delta=event.tool_arguments_delta)
            return
        if event.kind == "tool_call_end" and event.block_id:
            buffers = self._live_tools.get(session_id, {}).get(event.block_id)
            if buffers is not None:
                self._live_entries.setdefault(session_id, []).append(buffers.build_call_entry())
            return
        if event.kind == "tool_result" and event.tool_call_id:
            buffers = self._live_tools.get(session_id, {}).pop(event.tool_call_id, None)
            if buffers is not None:
                self._live_entries.setdefault(session_id, []).append(
                    TranscriptEntryDAO(kind="tool", tool_name=buffers.tool_name, output=event.content)
                )
            return
        if event.kind in ("text_end", "run_completed", "run_failed", "run_aborted"):
            self._live_open_assistant.discard(session_id)
            self._live_open_thinking.discard(session_id)

    def _append_live_thinking_delta(self, *, session_id: str, delta: str) -> None:
        """Append one thinking delta to the open live thinking entry.

        Args:
            session_id (str): Session that owns the visible thinking block.
            delta (str): New thinking text.
        """
        entries: list[TranscriptEntryDAO] = self._live_entries.setdefault(session_id, [])
        if session_id not in self._live_open_thinking:
            entries.append(TranscriptEntryDAO(kind="thinking", content=delta))
            self._live_open_thinking.add(session_id)
            return
        current: TranscriptEntryDAO = entries[-1]
        entries[-1] = current.model_copy(update={"content": (current.content or "") + delta})

    def _append_live_text_delta(self, *, session_id: str, delta: str) -> None:
        """Append one text delta to the open assistant entry for a live node."""
        entries: list[TranscriptEntryDAO] = self._live_entries.setdefault(session_id, [])
        if session_id not in self._live_open_assistant:
            entries.append(TranscriptEntryDAO(kind="assistant", answer=delta))
            self._live_open_assistant.add(session_id)
            return
        current: TranscriptEntryDAO = entries[-1]
        entries[-1] = current.model_copy(update={"answer": (current.answer or "") + delta})

    @staticmethod
    def _orchestrator_label(*, node: OrchestratorNodeDAO) -> Text:
        """Format the first list row for the visualizer's orchestrator node."""
        icon: str = _STATUS_ICON.get(node.state, "?")
        style: str = _STATUS_STYLE.get(node.state, "")
        return Text(f"{icon} orchestrator · {node.state} · {node.phase}", style=style)

    @staticmethod
    def _child_label(*, child: ChildSessionSummaryDAO) -> Text:
        """Format the list-item label for one child session with prompt preview.

        The status icon and session id are coloured by status (green completed,
        yellow running, red failed/aborted) so the list reads at a glance.

        Args:
            child (ChildSessionSummaryDAO): Child session summary.

        Returns:
            Text: Rich ``Text`` object for the list item, including prompt preview
                when available.
        """
        is_reaped: bool = child.terminal_reason == "reaped_orphan"
        icon: str = "⊘ reaped" if is_reaped else _STATUS_ICON.get(child.status, "?")
        short_id: str = child.session_id[:8]
        task_suffix: str = f" ({child.task_id[:8]})" if child.task_id else ""
        style: str = _STATUS_STYLE.get("aborted" if is_reaped else child.status, "")
        label: Text = Text(f"{icon} {short_id}{task_suffix} · {child.status}", style=style)
        if child.liveness_state:
            activity_age: str = HeadlessWorkflowVisualizer._activity_age(last_stdout_at=child.last_stdout_at)
            phase: str = child.heartbeat_phase or "awaiting heartbeat"
            label.append(f" · {child.liveness_state} · {phase} · out {activity_age}", style="dim")
        terminal_parts: list[str] = [
            part
            for part in (
                f"exit {child.exit_code}" if child.exit_code is not None else None,
                child.terminal_reason,
                child.terminated_by,
            )
            if part is not None
        ]
        if terminal_parts:
            label.append(f" · {' · '.join(terminal_parts)}", style="dim")
        if child.prompt_preview:
            label.append(" │ ", style="dim")
            label.append(child.prompt_preview, style="italic")
        return label

    @staticmethod
    def _activity_age(*, last_stdout_at: Optional[float]) -> str:
        """Format a monotonic stdout timestamp as a short operator-facing age."""
        if last_stdout_at is None:
            return "unknown"
        return f"{max(0, int(time.monotonic() - last_stdout_at))}s ago"

    @staticmethod
    def _write_entry_rich(*, detail_log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write one transcript entry to the detail log as rich renderables.

        Used by the default (TEXTUAL) detail format. Assistant answers and user
        messages render through ``rich.markdown.Markdown`` so headings, lists,
        and code blocks display the same way they do in the main TUI; reasoning
        and thinking render as dim italic; tool entries show a bold header and a
        truncated output block. A dim separator closes each entry.

        Args:
            detail_log (RichLog): Target detail log widget.
            entry (TranscriptEntryDAO): Transcript entry to render.
        """
        if entry.kind == "user":
            detail_log.write(Text("▶ User", style="bold cyan"))
            if entry.content:
                detail_log.write(Markdown(entry.content))
        elif entry.kind == "assistant":
            detail_log.write(Text("◀ Assistant", style="bold green"))
            if entry.reasoning:
                detail_log.write(Text("~ reasoning", style="bold dim"))
                detail_log.write(Text(entry.reasoning[:2000], style="dim italic"))
            body: str = entry.answer or entry.content or ""
            if body:
                detail_log.write(Markdown(body))
        elif entry.kind == "thinking":
            detail_log.write(Text("~ Thinking", style="bold dim"))
            if entry.content:
                detail_log.write(Text(entry.content[:2000], style="dim italic"))
        elif entry.kind == "tool":
            detail_log.write(Text(f"⚙ {entry.tool_name or 'tool'}", style="bold yellow"))
            if entry.output:
                detail_log.write(Text(str(entry.output)[:800], style="yellow"))
        else:
            detail_log.write(Text(str(entry)))
        detail_log.write(Text("─" * 24, style="dim"))

    @staticmethod
    def _format_transcript_entry(
        *,
        entry: TranscriptEntryDAO,
        fmt: TreeExportFormat = TreeExportFormat.TEXTUAL,
    ) -> Text:
        """Convert one transcript entry to a Rich ``Text`` object.

        The *fmt* parameter controls visual decoration:
        - ``TEXTUAL``: colour roles with Rich styles (default).
        - ``MARKDOWN``: prefix each turn with its markdown-role sigil.
        - ``HTML``: prefix with an HTML-comment-style tag; useful for
          piping output but not rendered inline in the terminal.

        Args:
            entry: ``TranscriptEntryDAO`` to format.
            fmt (TreeExportFormat): Visual mode for this render pass.

        Returns:
            Text: Styled Rich text block for ``RichLog``.
        """
        if fmt == TreeExportFormat.MARKDOWN:
            return HeadlessWorkflowVisualizer._format_entry_markdown(entry=entry)
        if fmt == TreeExportFormat.HTML:
            return HeadlessWorkflowVisualizer._format_entry_html(entry=entry)
        return HeadlessWorkflowVisualizer._format_entry_textual(entry=entry)

    @staticmethod
    def _format_entry_textual(*, entry: TranscriptEntryDAO) -> Text:
        """Format a transcript entry with Rich colour styles (TEXTUAL mode).

        Args:
            entry (TranscriptEntryDAO): Entry to format.

        Returns:
            Text: Rich-styled text block.
        """
        t = Text()
        if entry.kind == "user":
            t.append("▶ User\n", style="bold cyan")
            if entry.content:
                t.append(entry.content + "\n", style="cyan")
        elif entry.kind == "assistant":
            t.append("◀ Assistant\n", style="bold green")
            if entry.reasoning:
                t.append("~ reasoning\n", style="bold dim")
                t.append(entry.reasoning[:2000] + "\n", style="dim italic")
            if entry.answer:
                t.append(entry.answer + "\n", style="green")
            elif entry.content:
                t.append(entry.content + "\n", style="green")
        elif entry.kind == "thinking":
            t.append("~ Thinking\n", style="bold dim")
            if entry.content:
                t.append(entry.content[:2000] + "\n", style="dim italic")
        elif entry.kind == "tool":
            t.append(f"⚙ {entry.tool_name or 'tool'}\n", style="bold yellow")
            if entry.output:
                t.append(str(entry.output)[:500] + "\n", style="yellow")
        else:
            t.append(str(entry) + "\n")
        return t

    @staticmethod
    def _format_entry_markdown(*, entry: TranscriptEntryDAO) -> Text:
        """Format a transcript entry with Markdown-style sigils (MARKDOWN mode).

        Args:
            entry (TranscriptEntryDAO): Entry to format.

        Returns:
            Text: Plain text block with Markdown-role sigils.
        """
        t = Text()
        if entry.kind == "user":
            t.append("## User\n", style="bold")
            if entry.content:
                t.append(entry.content + "\n")
        elif entry.kind == "assistant":
            t.append("## Assistant\n", style="bold")
            if entry.reasoning:
                t.append("> *reasoning*\n", style="dim")
                t.append(entry.reasoning[:2000] + "\n", style="dim italic")
            body: str = entry.answer or entry.content or ""
            if body:
                t.append(body + "\n")
        elif entry.kind == "thinking":
            t.append("> *thinking*\n", style="dim")
            if entry.content:
                t.append(entry.content[:2000] + "\n", style="dim italic")
        elif entry.kind == "tool":
            tool_name: str = entry.tool_name or "tool"
            t.append(f"### `{tool_name}`\n", style="bold")
            if entry.output:
                t.append(f"```\n{str(entry.output)[:500]}\n```\n")
        else:
            t.append(str(entry) + "\n")
        return t

    @staticmethod
    def _format_entry_html(*, entry: TranscriptEntryDAO) -> Text:
        """Format a transcript entry with HTML-comment role tags (HTML mode).

        Note: the HTML tags are shown as plain text in the terminal; this mode
        is intended for users who copy-paste the log output into HTML documents.

        Args:
            entry (TranscriptEntryDAO): Entry to format.

        Returns:
            Text: Text block with HTML-role tags.
        """
        t = Text()
        if entry.kind == "user":
            t.append("<!-- user -->\n", style="dim")
            if entry.content:
                t.append(entry.content + "\n")
        elif entry.kind == "assistant":
            t.append("<!-- assistant -->\n", style="dim")
            if entry.reasoning:
                t.append(f"<!-- reasoning -->\n{entry.reasoning[:2000]}\n", style="dim")
            body: str = entry.answer or entry.content or ""
            if body:
                t.append(body + "\n")
        elif entry.kind == "thinking":
            t.append("<!-- thinking -->\n", style="dim")
            if entry.content:
                t.append(entry.content[:2000] + "\n", style="dim italic")
        elif entry.kind == "tool":
            tool_name: str = entry.tool_name or "tool"
            t.append(f'<!-- tool name="{tool_name}" -->\n', style="dim")
            if entry.output:
                t.append(f"<pre>{str(entry.output)[:500]}</pre>\n")
        else:
            t.append(str(entry) + "\n")
        return t

    def _update_status_bar(self, message: str) -> None:
        """Set the status bar to an arbitrary rich-markup message.

        Args:
            message (str): Rich-markup status text.
        """
        status: Label = self.query_one("#status-bar", Label)
        status.update(message)

    def _update_status_bar_from_data(self) -> None:
        """Rebuild the status bar from the current workflow data snapshot."""
        if self._workflow_data is None:
            self._update_status_bar("Loading …")
            return
        state: str = "complete" if self._workflow_data.is_complete else "running"
        follow_flag: str = "follow=on" if self._follow else "follow=off"
        refresh_ts: str = self._last_refresh.strftime("%H:%M:%S") if self._last_refresh else "—"
        n_children: int = len(self._workflow_data.children)
        parent_short: str = self._workflow_data.parent_session_id[:8]
        fmt_label: str = _FORMAT_LABEL.get(self._detail_format, "textual")
        view_label: str = f"[{self._detail_view}]"
        self._update_status_bar(
            f"parent={parent_short}  state={state}  "
            f"children={n_children}  fmt={fmt_label}  "
            f"view={view_label}  {follow_flag}  "
            f"list={self._child_panel_width}  diag={self._diag_height}  "
            f"last_refresh={refresh_ts}"
        )
