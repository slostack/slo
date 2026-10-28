"""Textual app for the ``slo`` default subcommand (sub-spec 02.a.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Optional, Protocol, cast

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Footer, Header, Static, TextArea

from config.ai_model_config import default_model_for_provider
from config.cfg import cfg
from config.logger import log_error
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.reasoning_capabilities import resolve_reasoning_config
from src.auth.browser_host import BrowserHost
from src.auth.credential_dao import CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.tui.components.chat_transcript.component import ChatTranscript
from src.tui.components.chat_transcript.adapters.workflow_progress import WorkflowProgressUpdatesAdapter
from src.tui.authentication import AuthenticationScreen
from src.tui.prompt_history import PromptHistoryNavigator
from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from src.tui.model_catalog import ModelSuggestionProjection
from src.tui.slash_suggestion_engine import (
    SlashSuggestionEngine,
    SlashSuggestionStateDAO,
)
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.thinking_spinner import ThinkingSpinner
from src.tui.tree_export_format import TreeExportFormat
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.queued_prompt_block import QueuedPromptBlock
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from src.tui.widgets.steering_pending_block import SteeringPendingBlock
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.tree_html_exporter import TreeHtmlExporter
from src.tui.widgets.tree_markdown_exporter import TreeMarkdownExporter
from src.tui.widgets.tree_viewer import SessionTreeViewer
from src.tui.widgets.usage_status_bar import UsageStatusBar
from src.tui.widgets.user_message_block import UserMessageBlock
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    HandleAdvanceOutcomeDAO,
    LiveWorkflowLabelDAO,
    WorkflowListDismissOutcomeDAO,
    WorkflowListDismissRequestDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator
from src.tui.workflows.renderer import DetachedWorkflowRenderer, DetachedVisualizerLaunch
from src.tui.workflows.service import DetachedWorkflowAppService
from src.tui.workflows.session_progress_screen import SessionProgressScreen

__all__ = ["SloTUI", "PromptInput"]

_ABORT_HARD_CANCEL_GRACE_SECONDS: float = 2.0
"""Grace period after a cooperative abort before the in-flight task is hard-cancelled.

The cooperative abort flag is only observed between agent graph stream items,
so a run blocked inside a single hung tool call would otherwise never abort.
After this grace, the TUI cancels the asyncio task outright, raising
``CancelledError`` into the blocked ``await`` and tearing the run down."""

_SESSION_LEASE_TTL_SECONDS: float = 30.0
_SESSION_LEASE_HEARTBEAT_SECONDS: float = 10.0
_SESSION_INBOX_POLL_SECONDS: float = 1.0

_SUB_AGENT_NOTICE_STATUSES: dict[str, str] = {
    "sub_agent_spawned": "spawned",
    "sub_agent_completed": "completed",
    "sub_agent_failed": "failed",
}
"""Child lifecycle kinds that write a one-line ``⊇ task: status`` transcript notice."""

_SUB_AGENT_LIST_REFRESH_KINDS: frozenset[str] = frozenset(
    {"sub_agent_spawned", "sub_agent_completed", "sub_agent_failed", "sub_agent_aborted"}
)
"""Child lifecycle kinds that request an observation refresh (feature 94 a.2).

Content events never touch the list: a row's task label stays stable while
its child streams. The stream-only ``sub_agent_dispatch_started`` event (no
``sub_agent_id``) also requests a refresh; see ``_render_event``.
"""


class PromptInput(TextArea):
    """``TextArea`` that posts prompt-specific intent messages.

    ``TextArea`` has no ``Submitted`` message of its own (that belongs to
    ``Input``), so we synthesise one. Bare Enter submits; modified Enter
    chords such as Shift+Enter, Cmd+Enter, and Ctrl+Enter insert a literal
    newline instead. When slash suggestions are visible, ``Tab`` / ``Up`` /
    ``Down`` / ``Esc`` are translated into suggestion intent messages so the
    app can keep command composition keyboard-first.
    """

    def __init__(self) -> None:
        """Construct the prompt input with explicit soft wrapping enabled."""
        super().__init__(soft_wrap=True)
        self._suggestion_navigation_enabled: bool = False
        self._prompt_history_navigation_enabled: bool = False

    class Submitted(Message):
        """Posted when the user presses Enter to submit the buffer."""

        def __init__(self, *, text: str) -> None:
            """Carry the submitted text.

            Args:
                text (str): The full multi-line buffer at submit time.
            """
            self.text: str = text
            super().__init__()

    class SuggestionAccepted(Message):
        """Posted when the prompt accepts the highlighted suggestion."""

    class SuggestionMoved(Message):
        """Posted when the prompt moves the highlighted suggestion row."""

        def __init__(self, *, delta: int) -> None:
            """Carry the row movement request.

            Args:
                delta (int): Positive or negative row movement.
            """
            self.delta: int = delta
            super().__init__()

    class SuggestionDismissed(Message):
        """Posted when the prompt dismisses slash suggestions."""

    class PromptHistoryOlderRequested(Message):
        """Posted when the prompt requests the next older prompt."""

    class PromptHistoryNewerRequested(Message):
        """Posted when the prompt requests the next newer prompt."""

    def set_suggestion_navigation_enabled(self, *, enabled: bool) -> None:
        """Enable or disable suggestion-specific key interception.

        Args:
            enabled (bool): True when slash suggestions are visible.
        """
        self._suggestion_navigation_enabled = enabled

    def set_prompt_history_navigation_enabled(self, *, enabled: bool) -> None:
        """Enable or disable prompt-history navigation mode.

        Args:
            enabled (bool): True when the prompt is browsing recalled history.
        """
        self._prompt_history_navigation_enabled = enabled

    async def _on_key(self, event: events.Key) -> None:
        """Intercept Enter chords for submit/newline semantics.

        Args:
            event (events.Key): The key event from Textual.
        """
        if self._should_accept_suggestion(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionAccepted())
            return
        if self._should_move_suggestion(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionMoved(delta=self._suggestion_delta(event=event)))
            return
        if self._should_request_older_prompt(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryOlderRequested())
            return
        if self._should_request_newer_prompt(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryNewerRequested())
            return
        if self._should_dismiss_suggestions(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionDismissed())
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(text=self.text))
            return
        if event.key in {"shift+enter", "ctrl+enter", "meta+enter"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)

    def _should_accept_suggestion(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should accept a suggestion.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the suggestion menu should accept the current row.
        """
        return self._suggestion_navigation_enabled and event.key == "tab"

    def _should_move_suggestion(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should move the highlight.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the highlighted suggestion should move.
        """
        return self._suggestion_navigation_enabled and event.key in {"up", "down"}

    def _should_request_older_prompt(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should request older prompt recall.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when history recall should move older.
        """
        return (
            not self._suggestion_navigation_enabled
            and event.key == "up"
            and (not self.text or self._prompt_history_navigation_enabled)
        )

    def _should_request_newer_prompt(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should request newer prompt recall.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when history recall should move newer.
        """
        return (
            not self._suggestion_navigation_enabled
            and event.key == "down"
            and self._prompt_history_navigation_enabled
        )

    def _should_dismiss_suggestions(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should dismiss suggestions.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the suggestion menu should close.
        """
        return self._suggestion_navigation_enabled and event.key == "escape"

    @staticmethod
    def _suggestion_delta(*, event: events.Key) -> int:
        """Return the row movement implied by ``event``.

        Args:
            event (events.Key): Up/down key event.

        Returns:
            int: ``1`` for down and ``-1`` for up.
        """
        if event.key == "down":
            return 1
        return -1


class SessionFactory(Protocol):
    """Build an unsubscribed replacement session; the application owns its adoption."""

    def __call__(self, *, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Return a session or propagate construction errors to the caller."""
        ...


class SloTUI(App):
    """Textual application wrapping a single ``SloAgentSession``."""

    CSS_PATH = "app.tcss"

    # Screen size classes consumed by the workflow session list rules in
    # app.tcss (feature 94 a.2): 60x20 is the minimum interactive size, and
    # screens shorter than 24 rows keep the list to one row.
    HORIZONTAL_BREAKPOINTS = [(0, "-workflow-below-minimum-width"), (60, "-workflow-minimum-width")]
    VERTICAL_BREAKPOINTS = [
        (0, "-workflow-below-minimum-height"),
        (20, "-workflow-short-height"),
        (24, "-workflow-full-height"),
    ]

    BINDINGS = [
        # ``priority=True`` so our interrupt wins over Textual's default
        # ctrl+c quit; ``show=False`` keeps it out of the footer.
        Binding(
            key="ctrl+c",
            action="interrupt",
            description="abort/quit",
            show=False,
            priority=True,
        ),
        Binding(key="ctrl+d", action="quit", description="quit"),
        Binding(key="ctrl+l", action="clear", description="clear"),
        Binding(key="ctrl+o", action="toggle_expandable_details", description="expand/collapse all"),
        Binding(key="ctrl+shift+c", action="copy_visible_text", description="copy"),
        Binding(key="meta+c", action="copy_visible_text", description="copy", show=False),
        Binding(key="ctrl+shift+m", action="copy_raw_markdown", description="copy raw markdown"),
        Binding(key="meta+shift+m", action="copy_raw_markdown", description="copy raw markdown", show=False),
        Binding(
            key="ctrl+end",
            action="scroll_to_bottom",
            description="scroll to bottom",
            show=False,
            priority=True,
        ),
    ]

    DEFAULT_THEME: str = SLO_DARK_THEME.name  # slo boots into the slo-dark (near-black/green) palette
    """Textual theme applied on construction.

    Defaults to the slo-dark theme (near-black/green) — the visual
    signature that distinguishes slo from poe-harness. Runtime theme
    switches via the command palette stay coherent because both themes
    are registered in ``__init__`` immediately after ``super().__init__()``
    initialises ``_registered_themes``.
    """

    def __init__(
        self,
        *,
        session: SloAgentSession,
        inbox_store: Optional[SessionInboxStore] = None,
        lease_store: Optional[SessionOwnershipLeaseStore] = None,
        workflow_handle_store: Optional[WorkflowHandleStore] = None,
        browser_host: Optional[BrowserHost] = None,
        session_factory: Optional[SessionFactory] = None,
        visualizer_launcher: Optional[DetachedVisualizerLaunch] = None,
    ) -> None:
        """Compose the TUI around a pre-built session.

        WHAT: Registers themes and initialises every app-owned piece of state,
        including the one-deep queued-prompt slot and its submission gate.
        WHO: ``TyperDispatch`` builds it for the interactive path; pilot tests
        construct it directly around a session fixture.
        WHEN: Once per interactive process or per test app instance.

        Args:
            session (SloAgentSession): The in-process session to drive.
            inbox_store (Optional[SessionInboxStore]): Optional injected inbox
                store for tests. ``None`` uses the session history root.
            lease_store (Optional[SessionOwnershipLeaseStore]): Optional injected
                lease store for tests. ``None`` uses the session history root.
            workflow_handle_store (Optional[WorkflowHandleStore]): Optional
                injected workflow handle store for tests. ``None`` uses the
                session history root.
            browser_host (Optional[BrowserHost]): Optional injected host that
                decides whether link clicks may open a browser. ``None`` uses
                ``BrowserHost.current()``.
        """
        super().__init__()
        self._session_factory = session_factory
        self._visualizer_launcher = visualizer_launcher
        self._browser_host: BrowserHost = browser_host or BrowserHost.current()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = self.DEFAULT_THEME
        self._session: SloAgentSession = session
        self._preparation_task: Optional[asyncio.Task[None]] = None
        self._attach_pool_to_session(session=self._session)
        self._chat_transcript: Optional[ChatTranscript] = None
        self._chat_shell: Optional[Vertical] = None
        self._status_region: Optional[Vertical] = None
        self._input: Optional[PromptInput] = None
        self._suggestion_menu: Optional[SlashSuggestionMenu] = None
        self._usage_status_bar: Optional[UsageStatusBar] = None
        self._in_flight_task: Optional[asyncio.Task[None]] = None
        self._prompt_submission_lock: asyncio.Lock = asyncio.Lock()
        """Serializes ordinary-prompt acceptance and run-completion handoff only."""
        self._queued_prompt_text: Optional[str] = None
        """One-deep latest-wins ordinary text not yet accepted as a user turn."""
        self._queued_prompt_block: Optional[QueuedPromptBlock] = None
        """Mounted visual counterpart of ``_queued_prompt_text``, when mounted."""
        self._spinner: Optional[ThinkingSpinner] = None
        self._slash_suggestion_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self._picker_catalog_revision: tuple[int, int] = ModelSuggestionProjection.current_revision()
        self._suggestion_engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )
        self._prompt_history: PromptHistoryNavigator = PromptHistoryNavigator()
        self._setting_prompt_from_history: bool = False
        # Fleet panel reference for sub-agent status display.
        self._fleet_panel: Optional[SubAgentFleetPanel] = None
        # Guards one-per-run auto-launch of the workflow visualizer window.
        self._visualizer_launched_for_run: bool = False
        # Detached-workflow receive path (spec 57.a.5): the app service owns
        # the handle store, legal durable transitions, and the live-state
        # cache; the renderer owns visualizer launch de-duplication and
        # transcript notices. Both are composed at delivery-init time — the
        # app only delegates and executes typed effects.
        self._workflow_handle_store: Optional[WorkflowHandleStore] = workflow_handle_store
        self._workflow_app_service: Optional[DetachedWorkflowAppService] = None
        # Feature 94 a.3: the sole observation refresh owner and its presentation
        # adapter, rebuilt together with the service for every owning session.
        self._workflow_progress_coordinator: Optional[WorkflowProgressCoordinator] = None
        self._workflow_progress_updates_adapter: Optional[WorkflowProgressUpdatesAdapter] = None
        self._workflow_renderer: Optional[DetachedWorkflowRenderer] = None
        self._inbox_store: Optional[SessionInboxStore] = inbox_store
        self._lease_store: Optional[SessionOwnershipLeaseStore] = lease_store
        self._session_owner_id: str = SessionOwnershipLeaseStore.default_owner_id()
        self._lease_timer: Optional[Timer] = None
        self._inbox_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Build the widget tree.

        Yields:
            Header, the transcript + input vertical, and Footer.
        """
        yield Header(show_clock=False)
        self._chat_shell = Vertical(id="chat-shell")
        with self._chat_shell:
            self._chat_transcript = ChatTranscript(history_reader=self._session.hydrate_transcript_entries)
            yield self._chat_transcript
            self._status_region = Vertical(id="status-region")
            self._suggestion_menu = SlashSuggestionMenu()
            with self._status_region:
                yield self._suggestion_menu
            self._input = PromptInput()
            yield self._input
            # Workflow session list: below PromptInput, hidden while it has no
            # rows. The orchestrator transcript always stays in the foreground.
            self._fleet_panel = SubAgentFleetPanel()
            yield self._fleet_panel
            self._usage_status_bar = UsageStatusBar()
            yield self._usage_status_bar
        yield Footer()

    def set_transcript_visible(self, *, visible: bool) -> None:
        """Choose visibility without stealing modal focus or changing execution."""
        transcript = self._chat_transcript
        if transcript is None:
            return
        focused = self.focused
        if (
            not visible
            and self._input is not None
            and self.screen is self._input.screen
            and focused is not None
            and (focused is transcript or transcript in focused.ancestors)
        ):
            self._input.focus()
        transcript.set_visible(visible=visible)

    def open_url(self, url: str, *, new_tab: bool = True) -> None:
        """Open a URL in a graphical browser off the event loop, or do nothing on a headless host.

        WHAT: Textual's driver opens links with a synchronous ``webbrowser.open``. On a Linux
            host without a graphical session that starts a console browser which waits for
            exit on the TUI terminal, so headless hosts rely on the painted OSC 8 link instead.
            Elsewhere the open runs in a thread worker whose failure never exits the app.
        WHO: ``AuthorizationLink.action_open_link`` and any other Textual link activation.
        WHEN: Each time the user clicks, or presses Enter on, a link.

        Args:
            url (str): URL to open; never logged.
            new_tab (bool, optional): Textual's new-tab flag. Defaults to True.
        """
        if not self._browser_host.can_open_graphical_browser():
            return
        self.run_worker(
            work=partial(self._open_url_with_driver, url=url, new_tab=new_tab),
            group="open-url",
            exit_on_error=False,
            thread=True,
        )

    def _open_url_with_driver(self, *, url: str, new_tab: bool) -> None:
        """Ask Textual's driver to open the URL.

        WHO: The thread worker started by ``open_url``.
        WHEN: Once per link activation on a host that can open a graphical browser.

        Args:
            url (str): URL to open; never logged.
            new_tab (bool): Textual's new-tab flag, passed through unchanged.
        """
        super().open_url(url, new_tab=new_tab)

    async def on_mount(self) -> None:
        """Hydrate from history, subscribe the renderer, maybe push auth.

        Call order matters (sub-spec 05.e §7.2): hydrate the transcript
        from replay projections BEFORE subscribing the live renderer
        so live events from a new prompt cannot interleave with the
        replay tail.
        """
        ModelSuggestionProjection.refresh_authentication()
        assert self._chat_transcript is not None
        await self._chat_transcript.hydrate()
        await self._maybe_render_startup_notice()
        self._session.subscribe(handler=self._render_event)
        await self._bind_workflow_observation()
        await self._initialize_session_delivery()
        self._refresh_title_bar()
        await self._session.refresh_context_window_snapshot()
        self._refresh_usage_status_bar()
        if self._input is not None:
            self._input.focus()
        if self._session.preparation_status != "ready":
            self._start_session_preparation()
        if not self._has_credential_for_active_model():
            self._push_auth_modal()

    def _start_session_preparation(self) -> None:
        """Start one tracked catalog worker after mount or explicit recovery.

        The session owns discovery and atomic adoption; the app owns task lifetime
        and safe status rendering. Repeated retry requests join the active worker.
        """
        if self._preparation_task is not None and not self._preparation_task.done():
            return
        if self._session.preparation_status == "ready":
            return
        session: SloAgentSession = self._session
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content="Preparing model catalog; limits unknown.", classes="tool-result"
            )
        self._preparation_task = asyncio.create_task(self._prepare_mounted_session(session=session))

    async def _prepare_mounted_session(self, *, session: SloAgentSession) -> None:
        """Prepare ``session`` and render only while it remains the mounted session.

        Capturing the target session prevents a worker superseded by ``/new`` from
        preparing or repainting the replacement session after its cancellation.
        """
        try:
            await session.prepare_startup()
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._session is session:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content="Model preparation failed; use /auth or /model refresh to retry.",
                        classes="tool-result",
                    )
        else:
            if self._session is session:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content="Model catalog ready.", classes="tool-result"
                    )
        if self._session is session:
            self._refresh_title_bar()
            self._refresh_usage_status_bar()

    async def _cancel_session_preparation(self) -> None:
        """Cancel and await the tracked worker before replacing its session."""
        task: Optional[asyncio.Task[None]] = self._preparation_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _maybe_render_startup_notice(self) -> None:
        """Render the one-time startup notice for new sessions only."""
        if self._session.preparation_status != "ready":
            return
        if not await self._session.should_show_startup_notice():
            return
        fallback_notice: Optional[str] = self._session.startup_fallback_notice
        if fallback_notice:
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=fallback_notice,
                    classes="tool-result",
                )
        resolved_reasoning = resolve_reasoning_config(
            model_name=self._session.active_model_name,
            requested_level=self._session.active_reasoning_level,
            snapshot=self._session.catalog_snapshot,
        )
        reasoning_detail: str = self._reasoning_detail_text(
            provider_effort=resolved_reasoning.provider_effort,
            provider_budget_tokens=resolved_reasoning.provider_budget_tokens,
        )
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=(
                    "slo, Copyright (C) 2026 Siddharth Ravichandran. "
                    "This program comes with ABSOLUTELY NO WARRANTY; see LICENSE. "
                    "This is free software, and you are welcome to redistribute it under GPLv2."
                ),
                classes="tool-result",
            )
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=(
                    "Tip: use /help to see available commands. "
                    f"Session: {self._session.session_id}. "
                    f"Initialized model: {self._session.active_model_name}. "
                    f"Reasoning: {self._session.active_reasoning_level}. "
                    f"Provider detail: {reasoning_detail}."
                ),
                classes="tool-result",
            )
        await self._session.mark_startup_notice_shown()

    @staticmethod
    def _reasoning_detail_text(
        *,
        provider_effort: str | None,
        provider_budget_tokens: int | None,
    ) -> str:
        """Return the provider-native reasoning detail copy.

        Args:
            provider_effort (str | None): Provider-native effort string.
            provider_budget_tokens (int | None): Provider-native thinking budget.

        Returns:
            str: Human-readable provider reasoning detail.
        """
        if provider_effort is not None:
            return f"effort {provider_effort}"
        if provider_budget_tokens is not None:
            return f"budget {provider_budget_tokens}"
        return "no provider-native reasoning extras"

    def _has_credential_for_active_model(self) -> bool:
        """True iff the active model's provider has a resolvable credential.

        Returns:
            bool: ``False`` when ``CredentialResolver.resolve`` returns
                ``None`` for the active provider, ``True`` otherwise.
        """
        try:
            provider: ProviderName = provider_for_model(
                model_name=self._session.active_model_name,
            )
        except ValueError:
            return True
        return CredentialResolver.resolve(provider=provider) is not None

    def _toggle_theme(self) -> None:
        """Toggle the active theme between slo-default and slo-dark.

        If the current theme is neither of the two, switches to slo-default.
        """
        next_theme: str = (
            SLO_DARK_THEME.name if self.theme == SLO_DEFAULT_THEME.name else SLO_DEFAULT_THEME.name
        )
        self.theme = next_theme
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(content=f"theme: {next_theme}", classes="tool-result")

    def _push_auth_modal(self) -> None:
        """Push ``AuthenticationScreen`` with the dismissal callback wired up."""
        self.push_screen(AuthenticationScreen(), callback=self._on_auth_dismissed)

    def _on_auth_dismissed(self, value: Optional[CredentialDAO]) -> None:
        """Refresh the active model and title state after auth success.

        Args:
            value (Optional[CredentialDAO]): ``CredentialDAO`` on success,
                ``None`` on cancel.
        """
        ModelSuggestionProjection.refresh_authentication(verified_credential=value)
        self._refresh_slash_suggestions()
        if value is None:
            return
        if self._session.preparation_status != "ready":
            self._start_session_preparation()
            return
        current_provider: ProviderName = provider_for_model(
            model_name=self._session.active_model_name,
        )
        if value.provider is not current_provider:
            new_model_name: Optional[str] = default_model_for_provider(provider=value.provider)
            if new_model_name is None:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content="Key verified; choose a model with /model.", classes="tool-result"
                    )
                self._prime_model_picker_after_auth()
                return
            try:
                self._session.switch_model(model_name=new_model_name)
            except RuntimeError:
                pass
            else:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content=f"active model switched to {new_model_name}",
                        classes="tool-result",
                    )
        self._refresh_title_bar(subject=value.subject)
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    def _prime_model_picker_after_auth(self) -> None:
        """Focus and seed the local model picker after authentication has no landing route.

        WHAT: Gives API-key-only providers a direct path to cached ``/model``
            search without selecting an arbitrary remote route.
        WHO: ``_on_auth_dismissed`` calls it after a verified provider has no
            configured default model.
        WHEN: Only after the authentication modal returns a successful credential.
        """
        if self._input is None:
            return
        self._input.load_text("/model ")
        self._move_prompt_cursor_to_end()
        self._refresh_slash_suggestions()
        self._input.focus()

    @staticmethod
    def _collapse_home_in_path(*, path: Path) -> str:
        """Render ``path`` below the user home directory with a ``~`` prefix.

        Called by ``_refresh_title_bar`` for title-only compact cwd display. Paths
        outside home, including textual-prefix lookalikes, remain absolute because
        ``Path.relative_to`` validates actual path ancestry.

        Args:
            path (Path): Absolute session working directory.

        Returns:
            str: ``~``, a ``~/...`` descendant, or the original absolute path.
        """
        home: Path = Path.home()
        try:
            relative_path: Path = path.relative_to(home)
        except ValueError:
            return str(path)
        if relative_path == Path("."):
            return "~"
        return f"~/{relative_path}"

    def _refresh_title_bar(self, *, subject: Optional[str] = None) -> None:
        """Render title and subtitle from the session's active runtime state.

        Args:
            subject (Optional[str]): Optional authenticated subject to
                append to the subtitle.
        """
        workdir_text: str = self._collapse_home_in_path(path=self._session.workdir)
        self.title = (
            f"slo · {workdir_text} · {self._session.routed_model_name} · "
            f"reasoning {self._session.active_reasoning_level}"
        )
        if self._session.session_name is not None:
            session_identity: str = f"session {self._session.session_name} · {self._session.session_id}"
        else:
            session_identity = f"session {self._session.session_id}"
        self.sub_title = f"{session_identity} · {subject}" if subject else session_identity

    def _refresh_usage_status_bar(self) -> None:
        """Refresh the persistent usage-and-limits widget."""
        if self._usage_status_bar is None:
            return
        self._usage_status_bar.update_snapshot(
            snapshot=self._session.usage_snapshot(),
            plugin_statuses=self._session.plugin_status_map(),
        )

    async def on_unmount(self) -> None:
        """Detach the renderer and join workflow observation. No subprocess to tear down."""
        await self._cancel_session_preparation()
        self._session.unsubscribe(handler=self._render_event)
        if self._chat_transcript is not None:
            await self._chat_transcript.close()
        await self._close_workflow_observation()
        await self._release_session_lease()

    async def _initialize_session_delivery(self) -> None:
        """Start lease heartbeats and inbox polling for history-backed sessions."""
        if not self._session_supports_inbox_delivery():
            return
        history_root: Path = cast(Path, self._session.history_root)
        if self._lease_store is None:
            self._lease_store = SessionOwnershipLeaseStore(history_root=history_root)
        if self._inbox_store is None:
            self._inbox_store = SessionInboxStore(history_root=history_root)
        if self._workflow_app_service is not None:
            await self._workflow_app_service.reconcile_snapshot()
        await self._acquire_session_lease()
        await self._inbox_store.ensure_session_inbox(session_id=self._session.session_id)
        self._lease_timer = self.set_interval(
            _SESSION_LEASE_HEARTBEAT_SECONDS,
            self._renew_session_lease,
        )
        self._inbox_timer = self.set_interval(
            _SESSION_INBOX_POLL_SECONDS,
            self._poll_session_inbox,
        )

    async def _bind_workflow_observation(self) -> None:
        """Bind workflow observation to the current session, replacing any prior owner.

        WHAT: Tears the previous owner down (``_close_workflow_observation``), then
            builds the service for the current session, the progress updates adapter and the
            single refresh coordinator, and starts it (five-second timer plus an
            immediate read). Every session observes its attached batch, with or
            without history; history-backed sessions also get the durable handle
            store and history adapter, and only they keep launch effects
            (``_history_backed_workflow_service``). The mount-time handle store is
            reused across ``/new`` because the replacement session copies the old
            session's ``history_root``.
        WHO: ``on_mount`` before inbox delivery, and ``/new`` session adoption.
        WHEN: Once per owning session, so no rows, caches or timers cross sessions.
        """
        await self._close_workflow_observation()
        self._workflow_app_service = self._build_workflow_service()
        self._workflow_progress_updates_adapter = WorkflowProgressUpdatesAdapter.register(tui=self)
        self._workflow_progress_coordinator = WorkflowProgressCoordinator(
            service=self._workflow_app_service,
            sink=self._workflow_progress_updates_adapter,
            schedule=self._schedule_workflow_refresh,
        )
        self._workflow_progress_coordinator.start()

    async def _close_workflow_observation(self) -> None:
        """Join the current owner's observation in the fixed teardown order.

        WHAT: ``coordinator.close`` (no read task survives) → ``service.close``
            (caches cleared, later reads empty) → ``adapter.dispose`` (owned screens
            dismissed, viewports forgotten) → panel reset, which joins any
            shielded row application before clearing. Never cancels execution.
        WHO: ``_bind_workflow_observation`` before adopting a new owner, and
            ``on_unmount``.
        WHEN: Once per owner replacement or app teardown; a no-op when unbound.
        """
        coordinator: Optional[WorkflowProgressCoordinator] = self._workflow_progress_coordinator
        self._workflow_progress_coordinator = None
        if coordinator is not None:
            await coordinator.close()
        if self._workflow_app_service is not None:
            await self._workflow_app_service.close()
        adapter: Optional[WorkflowProgressUpdatesAdapter] = self._workflow_progress_updates_adapter
        self._workflow_progress_updates_adapter = None
        if adapter is not None:
            adapter.dispose()
        await self._reset_session_list()

    def _build_workflow_service(self) -> DetachedWorkflowAppService:
        """Build the owner-scoped workflow service for the current session.

        Returns:
            DetachedWorkflowAppService: Service bound to this session's id, attached
                supplier and child-abort seams (with or without history) and, when
                history-backed, handle store and history adapter.
        """
        history_backed: bool = self._session_supports_inbox_delivery()
        if history_backed and self._workflow_handle_store is None:
            self._workflow_handle_store = WorkflowHandleStore(
                history_root=cast(Path, self._session.history_root)
            )
        return DetachedWorkflowAppService(
            workflow_handle_store=self._workflow_handle_store if history_backed else None,
            owner_session_id=self._session.session_id,
            attached_snapshot=self._session.attached_dispatch_snapshot,
            history_store=self._session.history_store if history_backed else None,
            attached_abort=self._session.abort_child,
            attached_capability=self._session.child_control_capability,
        )

    def _schedule_workflow_refresh(self, seconds: float, callback: Callable[[], None]) -> Timer:
        """Register the coordinator's interval timer on this app.

        WHO: ``WorkflowProgressCoordinator.start`` through its injected factory,
            which invokes it positionally.
        WHEN: Once per owning session, after mount.

        Args:
            seconds (float): Interval in seconds.
            callback (Callable[[], None]): Tick callback.

        Returns:
            Timer: The Textual interval timer the coordinator stops on close.
        """
        return self.set_interval(interval=seconds, callback=callback)

    def _history_backed_workflow_service(self) -> Optional[DetachedWorkflowAppService]:
        """Return the workflow service for whole-workflow launch effects, if allowed.

        WHAT: Every session gets a service so its session list observes attached
            children, but launch-result handling and the live-workflow exit hint
            stay history-gated (a.2: existing launch effects remain unchanged).
        WHO: ``_maybe_launch_workflow_visualizer`` and ``_live_workflow_labels``.
        WHEN: On each launch result and each exit-hint render.

        Returns:
            Optional[DetachedWorkflowAppService]: The bound service for a
                history-backed session, else ``None``.
        """
        if not self._session_supports_inbox_delivery():
            return None
        return self._workflow_app_service

    def _session_supports_inbox_delivery(self) -> bool:
        """Return whether this TUI session should expose inbox delivery.

        In-memory / no-history sessions cannot join the inbox delivery path:
        the session inbox is a filesystem-backed, cross-process queue that is
        colocated with the session history tree. The scheduler and detached
        workflow runners enqueue from *other* processes by writing message
        files under ``<history_root>/<session_id>/inbox/``, so this session is
        only reachable when it has BOTH ``history_enabled`` set to ``True``
        AND an on-disk ``Path`` history root for those writers to target.

        Returns:
            bool: True when history is enabled and rooted on disk.
        """
        if self._session.history_enabled is not True:
            return False
        return isinstance(self._session.history_root, Path)

    async def _acquire_session_lease(self) -> None:
        """Acquire the active-session lease for the mounted TUI session."""
        if self._lease_store is None:
            return
        await self._lease_store.acquire(
            session_id=self._session.session_id,
            owner_id=self._session_owner_id,
            ttl_seconds=_SESSION_LEASE_TTL_SECONDS,
        )

    async def _renew_session_lease(self) -> None:
        """Refresh the mounted TUI session lease."""
        if self._lease_store is None:
            return
        await self._lease_store.renew(
            session_id=self._session.session_id,
            owner_id=self._session_owner_id,
            ttl_seconds=_SESSION_LEASE_TTL_SECONDS,
        )

    async def _release_session_lease(self) -> None:
        """Release the mounted TUI session lease on app shutdown."""
        if self._lease_store is None:
            return
        await self._lease_store.release(
            session_id=self._session.session_id,
            owner_id=self._session_owner_id,
        )

    async def _poll_session_inbox(self) -> None:
        """Claim and process at most one inbox item only when the app is idle.

        WHAT: Serializes inbox claim/start with local prompt acceptance and drain.
        WHO: The mounted TUI's inbox timer calls it at its existing interval.
        WHEN: It runs for the TUI lifetime; it never holds the gate during a model run.
        """
        if self._inbox_store is None:
            return
        async with self._prompt_submission_lock:
            await self._claim_and_handle_idle_inbox_message()

    async def _claim_and_handle_idle_inbox_message(self) -> None:
        """Claim, handle, and acknowledge one inbox item under the prompt gate.

        WHAT: Leaves the inbox untouched when a local or prior inbox task is active.
        WHO: ``_poll_session_inbox`` calls it while owning the submission gate.
        WHEN: The inbox timer finds a configured store.
        """
        if self._inbox_store is None or self._in_flight_task is not None:
            return
        message: Optional[SessionInboxMessageDAO] = await self._inbox_store.claim_next(
            session_id=self._session.session_id,
        )
        if message is None:
            return
        await self._handle_inbox_message(message=message)
        await self._inbox_store.ack(
            session_id=self._session.session_id,
            message_id=message.message_id,
        )

    async def _handle_inbox_message(self, *, message: SessionInboxMessageDAO) -> None:
        """Route one claimed inbox item according to its delivery mode.

        Workflow lifecycle messages (spec 57.a.5) additionally advance the
        durable workflow handle before their delivery-mode rendering runs, so
        `/workflows` state stays truthful regardless of the delivery mode.

        Args:
            message (SessionInboxMessageDAO): Claimed inbox item.
        """
        await self._advance_workflow_handle_state(message=message)
        if message.delivery_mode == "ui_notice":
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=self._format_inbox_notice(message=message),
                    classes="tool-result",
                )
            return
        if message.delivery_mode == "transcript_note":
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=self._format_inbox_note(message=message),
                    classes="tool-result",
                )
            return
        if message.delivery_mode == "context_note":
            await self._deliver_context_note(message=message)
            return
        await self._start_inbox_chat_turn(message=message)

    async def _deliver_context_note(self, *, message: SessionInboxMessageDAO) -> None:
        """Render a context note AND persist it into model context (spec 57.a.4).

        Writes the ``⊛`` transcript line, then persists one ``workflow_update``
        history event via ``SloAgentSession.record_workflow_update`` — no LLM
        call happens. Persistence is idempotent on ``message_id``, so a
        re-claimed message (claim → crash → re-claim) renders again but is
        recorded at most once.

        Args:
            message (SessionInboxMessageDAO): Claimed ``context_note`` item.
        """
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=f"⊛ {message.title or message.kind}: {message.text}",
                classes="sub-agent-notice",
            )
        await self._session.record_workflow_update(
            text=message.text,
            message_id=message.message_id,
            workflow_id=str((message.payload or {}).get("workflow_id", "wf-unknown")),
        )

    @staticmethod
    def _format_inbox_notice(*, message: SessionInboxMessageDAO) -> str:
        """Return the transcript line for a UI notice inbox item.

        Args:
            message (SessionInboxMessageDAO): Inbox item under rendering.

        Returns:
            str: Rendered notice text.
        """
        title: str = message.title or message.kind.replace("_", " ")
        return f"[scheduled notice] {title}: {message.text}"

    @staticmethod
    def _format_inbox_note(*, message: SessionInboxMessageDAO) -> str:
        """Return the transcript line for a transcript-note inbox item.

        Args:
            message (SessionInboxMessageDAO): Inbox item under rendering.

        Returns:
            str: Rendered note text.
        """
        title: str = message.title or message.kind.replace("_", " ")
        return f"[scheduled update] {title}: {message.text}"

    async def _start_inbox_chat_turn(self, *, message: SessionInboxMessageDAO) -> None:
        """Submit one claimed inbox item as a real chat turn.

        Called while the caller holds ``_prompt_submission_lock`` (see
        ``_claim_and_handle_idle_inbox_message``), so the machine turn's task
        creation is atomic with local prompt acceptance. A machine turn never
        enters the user queue: it must not call ``_queue_prompt``,
        ``_prompt_history.record``, or ``_echo_user_line``.

        Args:
            message (SessionInboxMessageDAO): Claimed inbox item.
        """
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=self._format_inbox_note(message=message),
                classes="tool-result",
            )
        self._in_flight_task = asyncio.create_task(self._run_prompt(text=message.text))

    # ---- Detached-workflow receive path (spec 57.a.5) ----------------------

    async def _advance_workflow_handle_state(self, *, message: SessionInboxMessageDAO) -> None:
        """Delegate one claimed inbox message to the workflow app service.

        The app passes the raw kind/payload to the service exactly once;
        every durable and UI decision rides back in the typed
        ``HandleAdvanceOutcomeDAO``. The renderer executes the typed effects
        (including terminal ``reset_launch_guard`` effects) — the app never
        parses workflow payloads, mutates durable state, branches on
        terminal fields, or launches windows.

        Args:
            message (SessionInboxMessageDAO): Claimed inbox item.
        """
        service: Optional[DetachedWorkflowAppService] = self._workflow_app_service
        if service is None:
            return
        outcome: HandleAdvanceOutcomeDAO = await service.advance_from_inbox_message(
            kind=message.kind,
            payload=message.payload,
        )
        self._ensure_workflow_renderer().apply_effects(effects=outcome.effects)

    def _ensure_workflow_renderer(self) -> DetachedWorkflowRenderer:
        """Return the workflow renderer, composing it lazily on first use.

        On first use, create the renderer with a registered notice adapter.
        The adapter sends the renderer's notices through the app's normal
        transcript-writing method.

        Returns:
            DetachedWorkflowRenderer: The composed renderer.
        """
        assert self._chat_transcript is not None
        if self._workflow_renderer is None:
            self._workflow_renderer = DetachedWorkflowRenderer(
                notice_sink=self._chat_transcript.workflow_notice,
                launcher=self._visualizer_launcher,
            )
        return self._workflow_renderer

    def _maybe_launch_workflow_visualizer(self, *, result_text: str) -> None:
        """Translate a ``launch_workflow`` tool result into a visualizer launch.

        Invoked from ``_render_event`` when a ``launch_workflow`` tool result
        streams through. The app service validates the result (seeding the
        live-state cache on success); the renderer re-validates and opens the
        window. Malformed or error JSON is a safe no-op on both layers, and so
        is any result in a session without history (launch effects are
        history-gated, as before the session list observed every session).

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.
        """
        service: Optional[DetachedWorkflowAppService] = self._history_backed_workflow_service()
        if service is None:
            return
        if service.advance_from_launch_result(result_text=result_text) == "ignored":
            return
        self._ensure_workflow_renderer().handle_launch_result(result_text=result_text)

    # ---- Input handling ---------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Refresh slash suggestions when the prompt buffer changes.

        Args:
            event (TextArea.Changed): Prompt buffer change event.
        """
        if event.text_area is not self._input:
            return
        if self._setting_prompt_from_history:
            self._setting_prompt_from_history = False
        elif self._prompt_history.is_navigating:
            self._prompt_history.clear_navigation()
            if self._input is not None:
                self._input.set_prompt_history_navigation_enabled(enabled=False)
        self._refresh_slash_suggestions()

    async def on_key(self, event: events.Key) -> None:
        """Redirect a printable keystroke back to the prompt input.

        Textual bubbles every key the focused widget did not consume up to the
        application. When the prompt editor has lost focus (the user scrolled
        the transcript, or focus moved to ``VerticalScroll#transcript-scroll``),
        a printable keystroke means "I want to start typing", so we move focus
        back to ``PromptInput`` and replay the character into its buffer.
        Navigation and chord keys are not printable and fall through untouched.

        Args:
            event (events.Key): The bubbled key event.
        """
        if not self._should_redirect_typing_to_prompt(event=event):
            return
        event.prevent_default()
        event.stop()
        self._redirect_typing_to_prompt(event=event)

    def _should_redirect_typing_to_prompt(self, *, event: events.Key) -> bool:
        """Return True when ``event`` is a typing intent aimed at the prompt.

        A keystroke is typing intent only when every guard holds: the prompt
        input exists, it lives on the active screen (so a pushed modal such as
        the auth screen is never poached), it does not already own focus, and
        the key produces a printable unicode character.
        ``events.Key.is_printable`` is False for navigation and chord keys (Up,
        Down, PageUp, PageDown, Home, End, Ctrl+O, Tab, Enter, Escape, function
        keys) -- exactly the set we must not mistake for typing.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when focus should jump to the prompt and replay ``event``.
        """
        if self._input is None:
            return False
        if self._input.screen is not self.screen:
            return False
        if self.focused is self._input:
            return False
        return event.is_printable

    def _redirect_typing_to_prompt(self, *, event: events.Key) -> None:
        """Focus the prompt input and replay the triggering character.

        Called only after ``_should_redirect_typing_to_prompt`` returns True,
        so ``self._input`` is non-None and ``event.character`` is a printable
        string. Focus moves first so the editor renders its cursor; then the
        character is inserted at the cursor so the first keystroke is never
        dropped. The resulting ``TextArea.Changed`` event drives the normal
        slash-suggestion refresh via ``on_text_area_changed``.

        Args:
            event (events.Key): The printable key event to replay.
        """
        if self._input is None:
            return
        self._input.focus()
        self._input.insert(text=event.character or "")

    def on_prompt_input_suggestion_moved(self, event: PromptInput.SuggestionMoved) -> None:
        """Move the highlighted slash suggestion row.

        Args:
            event (PromptInput.SuggestionMoved): Requested row movement.
        """
        if not self._slash_suggestion_state.visible:
            return
        self._slash_suggestion_state = self._slash_suggestion_state.with_highlight_delta(
            delta=event.delta,
        )
        self._render_slash_suggestion_state(state=self._slash_suggestion_state)

    def on_prompt_input_suggestion_dismissed(self, event: PromptInput.SuggestionDismissed) -> None:
        """Dismiss visible slash suggestions.

        Args:
            event (PromptInput.SuggestionDismissed): Dismissal request.
        """
        del event
        self._hide_slash_suggestions()

    def on_prompt_input_suggestion_accepted(self, event: PromptInput.SuggestionAccepted) -> None:
        """Accept the highlighted slash suggestion when visible.

        Args:
            event (PromptInput.SuggestionAccepted): Acceptance request.
        """
        del event
        row = self._slash_suggestion_state.highlighted_row
        if row is None or self._input is None:
            return
        updated_text: str = self._replace_prompt_text(
            insert_text=row.insert_text,
            state=self._slash_suggestion_state,
        )
        self._input.load_text(updated_text)
        self._move_prompt_cursor_to_end()
        self._refresh_slash_suggestions()

    def on_prompt_input_prompt_history_older_requested(
        self,
        event: PromptInput.PromptHistoryOlderRequested,
    ) -> None:
        """Load the next older prompt into the editor when available.

        Args:
            event (PromptInput.PromptHistoryOlderRequested): History request.
        """
        del event
        if self._input is None:
            return
        recalled_text: Optional[str] = self._prompt_history.older(current_buffer=self._input.text)
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    def on_prompt_input_prompt_history_newer_requested(
        self,
        event: PromptInput.PromptHistoryNewerRequested,
    ) -> None:
        """Load the next newer prompt into the editor when available.

        Args:
            event (PromptInput.PromptHistoryNewerRequested): History request.
        """
        del event
        if self._input is None:
            return
        recalled_text: Optional[str] = self._prompt_history.newer()
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    async def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        """Route a submitted input line as a slash command, new turn, or held prompt.

        WHAT: Preserves immediate slash dispatch, then serializes normal-prompt
        acceptance with the active-run completion handoff.
        WHO: ``PromptInput`` posts this event after the operator submits text.
        WHEN: Runs once per Enter submission while the TUI is mounted.

        Args:
            event (PromptInput.Submitted): Custom input submission message.
        """
        text: str = (event.text or "").strip()
        self._hide_slash_suggestions()
        if self._input is not None:
            self._input.load_text("")
        if not text:
            return
        if text.startswith("/"):
            # Slash commands must dispatch even while a run is in flight — that
            # is the whole point of /steer and /abort. The handlers that must
            # not run mid-flight (/model, /new, /reasoning) already self-guard
            # on ``session.is_running``.
            await self._dispatch_slash_command(line=text)
            return
        await self._submit_or_queue_prompt(text=text)

    async def _submit_or_queue_prompt(self, *, text: str) -> None:
        """Accept an idle ordinary prompt or replace the one held behind a run.

        WHAT: Makes the app's task check and its consequent state transition atomic.
        WHO: ``on_prompt_input_submitted`` calls it for non-slash non-empty input.
        WHEN: Runs at operator submission time; it does not hold the lock during a run.

        Args:
            text (str): Normalized ordinary prompt text.
        """
        if self._session.preparation_status != "ready":
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content="Model preparation required; use /auth or /model refresh.", classes="tool-result"
                )
            return
        async with self._prompt_submission_lock:
            if self._in_flight_task is not None:
                await self._queue_prompt(text=text)
                return
            await self._start_accepted_prompt(text=text)

    async def _start_accepted_prompt(self, *, text: str) -> None:
        """Record, echo, and start one already-admitted ordinary prompt.

        WHAT: Converts text from either idle input or completion drain into a real
        user turn and starts the single app task.
        WHO: The submission and completion-handoff methods call it while holding
        ``_prompt_submission_lock``.
        WHEN: Only after the caller has established that no other app task may start.

        Args:
            text (str): Accepted text to persist through the normal session invoke path.
        """
        self._prompt_history.record(text=text)
        assert self._chat_transcript is not None
        await self._chat_transcript.echo_user(text=text)
        self._in_flight_task = asyncio.create_task(self._run_prompt(text=text))

    async def _queue_prompt(self, *, text: str) -> None:
        """Store the newest held text and mount or update its one visible block.

        WHAT: Applies one-deep latest-wins policy without creating a user turn.
        WHO: ``_submit_or_queue_prompt`` calls it under the submission gate.
        WHEN: An ordinary prompt arrives while an app-owned run task is active.

        Args:
            text (str): Newest ordinary prompt text.
        """
        self._queued_prompt_text = text
        if self._queued_prompt_block is not None:
            self._queued_prompt_block.replace_text(text=text)
            return
        await self._mount_queued_prompt_block(text=text)

    async def _mount_queued_prompt_block(self, *, text: str) -> None:
        """Mount the visible held-prompt block directly above the prompt input.

        WHAT: Anchors the block as a ``#chat-shell`` child immediately before
        ``PromptInput`` — outside the scroll region, so it stays visible while
        the transcript scrolls and window eviction can never reach it.
        WHO: ``_queue_prompt`` calls it only for an empty visual slot.
        WHEN: The first ordinary busy submission fills the one-deep queue.

        Args:
            text (str): Text to render in the new queued-prompt block.
        """
        if self._chat_shell is None or self._input is None:
            return
        block: QueuedPromptBlock = QueuedPromptBlock(text=text)
        await self._chat_shell.mount(block, before=self._input)
        self._queued_prompt_block = block

    async def _remove_queued_prompt_block(self) -> None:
        """Remove the current queue block and release its tracked reference.

        WHAT: Keeps the block registered until its asynchronous Textual removal is
        complete, then clears the tracked slot-block reference.
        WHO: ``_start_queued_prompt_if_idle`` and the clear path call it under the
        submission gate.
        WHEN: Immediately before a held prompt becomes an echoed user turn, or when
        ``/clear``/an allowed ``/new`` discards the held prompt.
        """
        block: Optional[QueuedPromptBlock] = self._queued_prompt_block
        if block is None:
            return
        await block.remove()
        self._queued_prompt_block = None

    # ---- Actions ----------------------------------------------------------

    async def action_interrupt(self) -> None:
        """``^C``: abort the in-flight run, or quit if idle.

        WHAT: Requests the session's cooperative abort, arms hard-cancel
        escalation, announces queued-prompt survival, and writes the aborting
        marker; an idle ``^C`` exits the app instead.
        WHO: Textual invokes it for the ``ctrl+c`` key binding.
        WHEN: Whenever the operator presses ``^C`` while the TUI is mounted.
        """
        if self._in_flight_task is None:
            self.exit()
            return
        self._session.abort()
        self._escalate_abort()
        self._announce_queued_prompt_survival()
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(content="(aborting…)", classes="tool-result")

    def _announce_queued_prompt_survival(self) -> None:
        """Explain that an abort retains the held prompt when one exists.

        WHAT: Writes one operator-facing notice without changing queue/task state.
        WHO: ``action_interrupt`` and ``_dispatch_slash_command`` call it after an
        abort has been requested.
        WHEN: Only while a user-held prompt remains queued behind the aborted run.
        """
        if self._queued_prompt_text is None:
            return
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=(
                    "(queued prompt held — it will run next; resubmit to replace it, " "/clear to drop it)"
                ),
                classes="tool-result",
            )

    def _escalate_abort(self) -> None:
        """Schedule a hard cancel of the in-flight task after the abort grace.

        ``session.abort()`` is cooperative — it is only observed between
        agent graph stream items, so a run wedged inside a single hung tool
        call never sees it. This arms a one-shot timer that cancels the
        asyncio task outright if it has not wound down on its own by the end
        of the grace period. A no-op when nothing is in flight.

        The exact task is captured now and bound into the timer callback, so
        a run that aborts cooperatively and is replaced by a fresh prompt
        within the grace window is never cancelled by this escalation.
        """
        task: Optional[asyncio.Task[None]] = self._in_flight_task
        if task is None:
            return
        self.set_timer(
            _ABORT_HARD_CANCEL_GRACE_SECONDS,
            lambda: self._hard_cancel_task(task=task),
        )

    def _hard_cancel_task(self, *, task: asyncio.Task[None]) -> None:
        """Cancel a specific in-flight task when its cooperative abort did not land.

        Fired by the abort-grace timer with the exact task that was in flight
        when the abort was requested. A no-op when that task already finished
        (cooperative abort or normal completion); otherwise it is cancelled,
        raising ``CancelledError`` into the blocked ``await`` in
        ``_run_prompt``.

        Args:
            task (asyncio.Task[None]): The task captured at abort time.
        """
        if task.done():
            return
        task.cancel()

    def exit(
        self,
        result: Optional[object] = None,
        return_code: int = 0,
        message: Optional[object] = None,
    ) -> None:
        """Quit the TUI, printing the resume command after the terminal restores.

        Overrides ``App.exit`` so every close path — ``/exit``, an idle
        ``^C``, and ``^D`` — leaves the resume command on the user's
        terminal. ``App.exit(message=...)`` is printed once the alternate
        screen is torn down, which is the only place a resume hint survives
        the TUI shutdown. An explicit ``message`` (rare) is never overridden.

        Args:
            result (Optional[object]): Optional Textual run result.
            return_code (int): Process return code.
            message (Optional[object]): Optional explicit exit message.
        """
        resolved_message: object = message if message is not None else self._resume_command_hint()
        super().exit(
            result=result,
            return_code=return_code,
            message=cast(Optional[str], resolved_message),
        )

    async def _mount_tree_viewer(self, *, tree: object, tree_format: Optional[str] = None) -> None:
        """Mount the tree viewer widget for /tree command results.

        Args:
            tree: The SessionTreeNode root from SessionTreeBuilder.
            tree_format: Optional format string ("textual", "markdown", "html").
        """
        if self._chat_transcript is None:
            return
        if tree_format is None:
            tree_format = TreeExportFormat.TEXTUAL.value

        if tree_format == TreeExportFormat.TEXTUAL.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode

            if isinstance(tree, SessionTreeNode):
                viewer = SessionTreeViewer(tree=tree)
                await self._chat_transcript.mount_tree_output(widget=viewer)
        elif tree_format == TreeExportFormat.MARKDOWN.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode

            if isinstance(tree, SessionTreeNode):
                md = TreeMarkdownExporter.export(tree=tree)
                await self._chat_transcript.mount_tree_output(widget=LiteralTextStatic(md))
        elif tree_format == TreeExportFormat.HTML.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode

            if isinstance(tree, SessionTreeNode):
                path = TreeHtmlExporter.export(
                    tree=tree,
                    session_name=self._session.session_name or "unnamed",
                )
                await self._chat_transcript.mount_tree_output(
                    widget=LiteralTextStatic(f"HTML tree written to: {path}")
                )

    def _resume_command_hint(self) -> str:
        """Return the copy-paste command that resumes the active session.

        When detached workflows are live (state ``launching``/``running`` in
        the mount-reconciled cache), a second line lists them next to the
        resume command (spec 57.a.5) — they keep running after the TUI exits.

        Returns:
            str: A ``slo --resume <session id>`` line for the active session,
                plus a live-workflows line when any workflow is live.
        """
        hint: str = f"Resume this session: slo --resume {self._session.session_id}"
        live_labels: list[LiveWorkflowLabelDAO] = self._live_workflow_labels()
        if not live_labels:
            return hint
        live_workflows: list[str] = [f"{label.workflow_id} ({label.state})" for label in live_labels]
        return (
            f"{hint}\nLive workflows: {', '.join(live_workflows)}. "
            "They keep running — list with /workflows after resume."
        )

    def _live_workflow_labels(self) -> list[LiveWorkflowLabelDAO]:
        """Return the live workflow labels from the app service cache.

        Returns:
            list[LiveWorkflowLabelDAO]: Live labels, empty when the workflow
                receive path is not initialized or the session has no history.
        """
        service: Optional[DetachedWorkflowAppService] = self._history_backed_workflow_service()
        if service is None:
            return []
        return service.live_workflow_labels()

    async def action_clear(self) -> None:
        """Clear transcript state and discard any held ordinary prompt.

        WHAT: Removes visible transcript children and clears their app-owned state.
        WHO: The Ctrl+L binding and slash-command result dispatch call it.
        WHEN: It may run while an agent task remains active; that task continues, but
        the held next prompt is intentionally discarded.
        """
        async with self._prompt_submission_lock:
            await self._clear_transcript_and_prompt_queue()

    async def _clear_transcript_and_prompt_queue(self) -> None:
        """Perform clear mutations while the prompt-submission gate is held.

        WHAT: Drops queued prompt state before removing all transcript children, then
        executes the existing projector/window/reset behavior.
        WHO: ``action_clear`` and an allowed ``_start_new_session`` call it.
        WHEN: Runs only under ``_prompt_submission_lock`` to avoid a drain/clear race.
        """
        self._queued_prompt_text = None
        await self._remove_queued_prompt_block()
        if self._chat_transcript is not None:
            await self._chat_transcript.clear()

    async def action_copy_visible_text(self) -> None:
        """Copy the focused block text, selected prompt text, or visible transcript.

        Resolution priority:
        1. Text from the focused transcript block via ``get_copyable_text()``.
        2. Selected text from the ``PromptInput`` editor.
        3. Full transcript as plain text via ``_adapter.lines``.

        The first non-empty result wins. A no-op when all three are empty.
        """
        text: str = (
            self._focused_block_text()
            or self._selected_prompt_text()
            or (self._chat_transcript.logical_copy_text() if self._chat_transcript is not None else "")
        )
        if not text:
            return
        self.copy_to_clipboard(text)

    async def action_copy_raw_markdown(self) -> None:
        """Copy whole raw Markdown from the nearest focused transcript-block provider."""
        raw_markdown: str = self._focused_raw_markdown()
        if not raw_markdown:
            return
        self.copy_to_clipboard(raw_markdown)

    async def on_text_selected(self, event: events.TextSelected) -> None:
        """Auto-copy the mouse-selected transcript span to the clipboard.

        Fired when the user releases a mouse drag over the transcript and the
        screen posts ``events.TextSelected``. Reads the current selection via
        ``Screen.get_selected_text`` and, when non-empty, hands it to the shared
        ``copy_to_clipboard`` funnel (local clipboard then OSC 52). A no-op when the
        selection is empty or ``None`` (e.g. a click with no drag).

        Args:
            event (events.TextSelected): The screen's selection-complete event.
        """
        del event
        selection: Optional[str] = self.screen.get_selected_text()
        if not selection:
            return
        self.copy_to_clipboard(selection)

    def copy_to_clipboard(self, text: str) -> None:
        """Deliver text to the clipboard via a local clipboard, then OSC 52.

        The single clipboard funnel for the TUI, shared by the keyboard copy binding
        (``action_copy_visible_text``) and mouse-selection auto-copy
        (``on_text_selected``). Tries ``pyperclip`` first so a local clipboard works
        even where OSC 52 does not (e.g. macOS Terminal), then always calls the
        Textual base implementation, which emits an OSC 52 escape so copy also works
        over SSH/tmux. A ``pyperclip`` import failure or copy error is swallowed and
        never blocks the OSC 52 write.

        Args:
            text (str): The text to place on the clipboard.
        """
        self._copy_via_local_clipboard(text=text)
        super().copy_to_clipboard(text)

    @staticmethod
    def _copy_via_local_clipboard(*, text: str) -> bool:
        """Best-effort local-clipboard copy via ``pyperclip``.

        Called only by ``copy_to_clipboard``. Import and copy errors are swallowed so
        a missing or unusable ``pyperclip`` never blocks OSC 52 delivery.

        Args:
            text (str): The text to copy locally.

        Returns:
            bool: True when ``pyperclip`` copied without raising, else False.
        """
        try:
            import pyperclip
        except ImportError:
            return False
        try:
            pyperclip.copy(text)
        except Exception:  # best-effort local clipboard; must never block OSC 52
            return False
        return True

    async def action_scroll_to_bottom(self) -> None:
        """Scroll the transcript to the latest content (``ctrl+end``).

        Delegates to ``_scroll_transcript_to_end``. Idempotent when the
        transcript is already at the bottom.
        """
        if self._chat_transcript is not None:
            self._chat_transcript.scroll_to_bottom()

    async def action_toggle_expandable_details(self) -> None:
        """Toggle global expand-all mode for every transcript block.

        Cycles natural-default -> expand-all -> collapse-all -> expand-all ...
        The first press always expands; subsequent presses alternate. The new
        state is pushed onto every existing block and inherited by new ones.
        """
        if self._chat_transcript is not None:
            self._chat_transcript.toggle_expandable_details()
        self.refresh_bindings()

    # ---- Private helpers --------------------------------------------------

    def _refresh_slash_suggestions(self) -> None:
        """Recompute slash suggestions from the current prompt buffer."""
        if self._input is None:
            return
        self._picker_catalog_revision = ModelSuggestionProjection.current_revision()
        state: SlashSuggestionStateDAO = self._suggestion_engine.evaluate(
            buffer_text=self._input.text,
            active_model_name=self._session.active_model_name,
        )
        previous = self._slash_suggestion_state.highlighted_row
        if previous is not None:
            index = next(
                (index for index, row in enumerate(state.rows) if row.insert_text == previous.insert_text), 0
            )
            state = state.model_copy(update={"highlighted_index": index})
        self._slash_suggestion_state = state
        self._render_slash_suggestion_state(state=state)

    def _refresh_visible_slash_suggestions_when_catalog_changed(self) -> None:
        """Refresh an open picker after a public catalog-status publication.

        WHAT: Observes the presentation revision and reuses the normal engine
            evaluation path without invoking credential, client, or catalog I/O.
        WHO: The mounted app calls this from Textual's idle loop.
        WHEN: Only while a visible ``/model`` suggestion menu is on screen.
        """
        if not self._slash_suggestion_state.visible:
            return
        revision = ModelSuggestionProjection.current_revision()
        if revision == self._picker_catalog_revision:
            return
        self._refresh_slash_suggestions()

    def on_idle(self) -> None:
        """Adopt a published picker status revision without waiting for a keystroke."""
        self._refresh_visible_slash_suggestions_when_catalog_changed()

    def _render_slash_suggestion_state(self, *, state: SlashSuggestionStateDAO) -> None:
        """Render one suggestion state into the prompt-adjacent menu.

        Args:
            state (SlashSuggestionStateDAO): Suggestion state to render.
        """
        if self._suggestion_menu is not None:
            self._suggestion_menu.update_state(state=state)
        if self._input is not None:
            self._input.set_suggestion_navigation_enabled(enabled=state.visible)

    def _hide_slash_suggestions(self) -> None:
        """Hide the slash suggestion menu and disable suggestion navigation."""
        hidden_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self._slash_suggestion_state = hidden_state
        self._render_slash_suggestion_state(state=hidden_state)

    def _replace_prompt_text(
        self,
        *,
        insert_text: str,
        state: SlashSuggestionStateDAO,
    ) -> str:
        """Return the prompt text after accepting one suggestion.

        Args:
            insert_text (str): Accepted suggestion text.
            state (SlashSuggestionStateDAO): Suggestion state describing the replacement span.

        Returns:
            str: Updated prompt text.
        """
        if self._input is None:
            return insert_text
        before: str = self._input.text[: state.replacement_start]
        after: str = self._input.text[state.replacement_end :]
        return f"{before}{insert_text}{after}"

    def _move_prompt_cursor_to_end(self) -> None:
        """Move the prompt cursor to the end of the current buffer."""
        if self._input is None:
            return
        line_count: int = self._input.text.count("\n")
        final_line: str = self._input.text.split("\n")[-1]
        self._input.move_cursor(location=(line_count, len(final_line)))

    def _load_prompt_history_text(self, *, text: str) -> None:
        """Load recalled prompt-history text into the editor.

        Args:
            text (str): Prompt text recalled from navigator history.
        """
        if self._input is None:
            return
        self._setting_prompt_from_history = True
        self._input.set_prompt_history_navigation_enabled(
            enabled=self._prompt_history.is_navigating,
        )
        self._input.load_text(text)
        self._move_prompt_cursor_to_end()

    async def _dispatch_slash_command(self, *, line: str) -> None:
        """Hand a slash command to ``SlashRouter`` and render the result.

        Long-running commands (the registry's ``shows_activity`` flag) mount the
        fixed activity spinner for the duration of the dispatch so the operator
        sees work in progress instead of a blank screen.

        Args:
            line (str): The full input line including the leading slash.
        """
        self._hide_slash_suggestions()
        if self._session.preparation_status != "ready":
            command = line.strip().split(maxsplit=1)[0]
            if line.strip() == "/model refresh":
                self._start_session_preparation()
                return
            if command not in {"/auth", "/help", "/quit", "/exit", "/q", "/clear", "/model"}:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content="Model preparation required.", classes="tool-result"
                    )
                return
        mounted_activity: bool = await self._mount_slash_activity(line=line)
        previous_model = self._session.active_model_name
        try:
            result = await SlashRouter.dispatch(line=line, session=self._session)
            if self._session.active_model_name != previous_model:
                self._suggestion_engine.record_selection(model_name=self._session.active_model_name)
            if line.strip() == "/model refresh":
                ModelSuggestionProjection.refresh_authentication()
        finally:
            if mounted_activity:
                await self._unmount_spinner()
        if result.should_clear:
            await self.action_clear()
        if result.replace_session:
            await self._start_new_session(requested_name=result.requested_session_name)
            return
        if result.rename_current_session_to is not None:
            await self._rename_current_session(session_name=result.rename_current_session_to)
            return
        if result.abort_run:
            self._escalate_abort()
            self._announce_queued_prompt_survival()
        if result.steer_pending_message is not None:
            assert self._chat_transcript is not None
            await self._chat_transcript.show_pending_steering(message=result.steer_pending_message)
        if result.render_tree is not None:
            await self._mount_tree_viewer(tree=result.render_tree, tree_format=result.tree_format)
        git_diff_path: Optional[str] = result.git_diff_path if isinstance(result.git_diff_path, str) else None
        if git_diff_path is not None:
            await self._open_git_diff(path=git_diff_path)
            return
        tui_dismiss: Optional[WorkflowListDismissRequestDAO] = (
            result.tui_dismiss if isinstance(result.tui_dismiss, WorkflowListDismissRequestDAO) else None
        )
        if tui_dismiss is not None:
            self._clear_finished_workflow_groups(request=tui_dismiss)
            return
        if result.rendered is not None:
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(content=result.rendered, classes="tool-result")
        self._apply_workflow_command_result(result=result)
        if result.refresh_title:
            self._refresh_title_bar()
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            await self._session.refresh_context_window_snapshot()
            self._refresh_usage_status_bar()
        if result.refresh_context_window:
            await self._session.refresh_context_window_snapshot()
            self._refresh_usage_status_bar()
        if result.refresh_usage_status:
            self._refresh_usage_status_bar()
        if result.toggle_theme:
            self._toggle_theme()
        if result.open_auth_modal:
            self._push_auth_modal()
        if result.should_exit:
            self.exit()

    async def _open_git_diff(self, *, path: str) -> None:
        """Load Git diff content and push its focused screen when it is safe.

        WHAT: Delegates all filesystem and Git validation to GitDiffContentService,
        then either pushes GitDiffScreen or writes its safe error message.
        WHO: _dispatch_slash_command calls this for a git_diff_path intent.
        WHEN: Immediately after the operator submits ``/diff <path>``.

        Args:
            path (str): Unvalidated repository-relative path from the slash router.
        """
        from src.tui.git_diff_content_service import (  # noqa: PLC0415
            GitDiffContentError,
            GitDiffContentService,
        )
        from src.tui.git_diff_screen import GitDiffScreen  # noqa: PLC0415

        try:
            content = await GitDiffContentService.invoke(
                requested_path=path,
                workdir=self._session.workdir,
            )
        except GitDiffContentError as exception:
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=exception.operator_message, classes="tool-result"
                )
            return
        self.push_screen(GitDiffScreen(content=content))

    async def _start_new_session(self, *, requested_name: Optional[str]) -> None:
        """Replace the active idle session and discard any app-local queued prompt.

        WHAT: Serializes session replacement with prompt acceptance and the
        completion handoff; a mid-run or mid-handoff `/new` is rejected with
        the existing operator notice.
        WHO: ``_dispatch_slash_command`` calls it for `/new` router results.
        WHEN: Only an idle app proceeds; the replacement's clear path runs
        under ``_prompt_submission_lock`` so no queue state crosses sessions.

        Args:
            requested_name (Optional[str]): Optional replacement session name.
        """
        async with self._prompt_submission_lock:
            if self._in_flight_task is not None or self._session.is_running:
                if self._chat_transcript is not None:
                    self._chat_transcript.write_transcript_line(
                        content="cannot start a new session while a prompt is in flight; run /abort first",
                        classes="tool-result",
                    )
                return
            await self._replace_idle_session_and_clear_queue(requested_name=requested_name)

    async def _replace_idle_session_and_clear_queue(self, *, requested_name: Optional[str]) -> None:
        """Swap in a fresh session and clear transcript plus queue state.

        WHAT: Runs the unsubscribe/build/rename/assign/re-subscribe sequence and
        clears the transcript through the gate-held clear body, so no queue
        reference can cross into the replacement session.
        WHO: ``_start_new_session`` calls it only while holding
        ``_prompt_submission_lock`` after establishing the app is idle.
        WHEN: The operator requests `/new` while no run is active.

        Args:
            requested_name (Optional[str]): Optional initial human-readable session name.
        """
        old_session: SloAgentSession = self._session
        await self._cancel_session_preparation()
        old_session.unsubscribe(handler=self._render_event)
        factory = self._session_factory or SloAgentSession.build
        new_session: SloAgentSession = factory(
            config=self._build_replacement_session_config(old_session=old_session),
            allow_pending_preparation=True,
        )
        self._attach_pool_to_session(session=new_session)
        if requested_name is not None:
            await new_session.rename_session(session_name=requested_name)
        self._queued_prompt_text = None
        await self._remove_queued_prompt_block()
        assert self._chat_transcript is not None
        await self._chat_transcript.bind_history(history_reader=new_session.hydrate_transcript_entries)
        self._session = new_session
        await self._bind_workflow_observation()
        self._prompt_history.clear_navigation()
        self._prompt_history = PromptHistoryNavigator()
        if self._input is not None:
            self._input.load_text("")
            self._input.set_prompt_history_navigation_enabled(enabled=False)
        await self._maybe_render_startup_notice()
        self._session.subscribe(handler=self._render_event)
        self._refresh_title_bar()
        await self._session.refresh_context_window_snapshot()
        self._refresh_usage_status_bar()
        if self._session.preparation_status != "ready":
            self._start_session_preparation()

    async def _rename_current_session(self, *, session_name: str) -> None:
        """Rename the active session and refresh visible title state.

        Args:
            session_name (str): Requested human-readable session name.
        """
        try:
            await self._session.rename_session(session_name=session_name)
        except Exception as exc:  # noqa: BLE001 - inline operator feedback required
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=f"(rename failed: {exc})", classes="tool-result"
                )
            return
        self._refresh_title_bar()
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=f"session renamed to {session_name}", classes="tool-result"
            )

    # ---- Sub-agent routing and fleet panel --------------------------------

    async def _route_sub_agent_event(self, event: AgentStreamEventDAO) -> None:
        """Route a tagged sub-agent event to transcript notices and the session list.

        WHAT: The orchestrator transcript stays in the foreground; child content
            never appears there and never changes the session list, so a row's
            task label stays stable while its child streams. Lifecycle events
            write their one-line notice, open the workflow visualizer on the first
            spawn of a run, then ask the observation coordinator for a coalesced
            refresh (rows come only from the service snapshot).
        WHO: ``_render_event`` for every event carrying ``sub_agent_id``.
        WHEN: As the attached orchestrator streams child events.

        Args:
            event (AgentStreamEventDAO): Event carrying a non-``None`` ``sub_agent_id``.
        """
        self._write_sub_agent_notice(event=event)
        if event.kind == "sub_agent_spawned":
            self._maybe_launch_visualizer()
        if event.kind not in _SUB_AGENT_LIST_REFRESH_KINDS:
            return
        self._request_workflow_refresh()

    def _write_sub_agent_notice(self, *, event: AgentStreamEventDAO) -> None:
        """Write the ``⊇ task: status`` transcript notice for a noticed lifecycle kind.

        Args:
            event (AgentStreamEventDAO): Child event; other kinds write nothing.
        """
        status: Optional[str] = _SUB_AGENT_NOTICE_STATUSES.get(event.kind)
        if status is None or self._chat_transcript is None:
            return
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=f"⊇ {event.task_id or ''}: {status}", classes="sub-agent-notice"
            )

    def _request_workflow_refresh(self) -> None:
        """Ask the observation coordinator for one coalesced refresh, if bound.

        WHO: Child lifecycle and dispatch-start events, typed dismiss/resume
            slash results and ``/workflows tui dismiss``.
        WHEN: Whenever list membership or status may have changed; the five-second
            tick repairs anything missed.
        """
        if self._workflow_progress_coordinator is None:
            return
        self._workflow_progress_coordinator.request_refresh()

    def on_sub_agent_fleet_panel_session_selected(self, message: SubAgentFleetPanel.SessionSelected) -> None:
        """Open progress for the exact row the user activated (Enter or click).

        Args:
            message (SubAgentFleetPanel.SessionSelected): Selected composite key.
        """
        if self._workflow_progress_coordinator is None:
            return
        self._workflow_progress_coordinator.select(key=message.key)

    def on_session_progress_screen_minimized(self, message: SessionProgressScreen.Minimized) -> None:
        """Close progress observation on Escape/Minimize without touching execution.

        Args:
            message (SessionProgressScreen.Minimized): Minimize intent.
        """
        if self._workflow_progress_coordinator is None:
            return
        self._workflow_progress_coordinator.minimize()

    def on_session_progress_screen_abort_requested(
        self, message: SessionProgressScreen.AbortRequested
    ) -> None:
        """Ask the sink to confirm the exact target the progress view displayed.

        Args:
            message (SessionProgressScreen.AbortRequested): Captured confirmation target.
        """
        if self._workflow_progress_updates_adapter is None:
            return
        self._workflow_progress_updates_adapter.confirm_abort(target=message.target)

    def _on_child_abort_confirmed(self, *, target: ChildAbortTargetDAO) -> None:
        """Hand an explicitly confirmed target to the service and refresh at once.

        WHAT: The service owns the submission (minimizing never withdraws it);
            the immediate refresh paints the pending notice and disabled Abort.
        WHO: ``WorkflowProgressUpdatesAdapter`` from its confirmation callback, only on True.
        WHEN: Once per explicit Abort child choice.

        Args:
            target (ChildAbortTargetDAO): Identity captured when confirmation opened.
        """
        if self._workflow_app_service is None:
            return
        self._workflow_app_service.begin_child_abort(target=target)
        self._request_workflow_refresh()

    def _on_progress_incarnation_changed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Close the old execution view when the sink observes same-key reuse.

        WHAT: The coordinator invalidates its generation first, then asks the sink
            to dismiss the view; the reader must select the session again.
        WHO: ``WorkflowProgressUpdatesAdapter.apply_sessions`` only, while reconciling the
            selected identity against fresh rows.
        WHEN: When the open view's key now names a different execution or dispatch.

        Args:
            key (WorkflowSessionKeyDAO): Selected key whose incarnation changed.
        """
        if self._workflow_progress_coordinator is not None:
            self._workflow_progress_coordinator.minimize()
        self.notify(message=f"Session execution changed; select {key.session_id} again.", markup=False)

    def _apply_workflow_command_result(self, *, result: SlashCommandResultDAO) -> None:
        """Route typed ``/workflows dismiss|resume`` outcomes to observation.

        WHAT: A successful dismissal suppresses that group in memory; a successful
            resume clears the suppression; either requests a refresh. Never parses
            the rendered text.
        WHO: ``_dispatch_slash_command`` after every slash result.
        WHEN: Immediately after the router returns.

        Args:
            result (SlashCommandResultDAO): Router result with typed workflow ids.
        """
        service: Optional[DetachedWorkflowAppService] = self._workflow_app_service
        if service is None or (result.dismissed_workflow_id is None and result.resumed_workflow_id is None):
            return
        if result.dismissed_workflow_id is not None:
            service.dismiss_group(workflow_id=result.dismissed_workflow_id)
        if result.resumed_workflow_id is not None:
            service.resume_group(workflow_id=result.resumed_workflow_id)
        self._request_workflow_refresh()

    def _clear_finished_workflow_groups(self, *, request: WorkflowListDismissRequestDAO) -> None:
        """Apply ``/workflows tui dismiss [<id>]`` to observation and render its outcome.

        WHAT: The service hides finished groups from its membership first; the
            outcome's own line is written as a normal slash result; then one
            coalesced refresh repaints the list through the coordinator (the
            panel is never mutated here). Without observation nothing is listed,
            so the nothing-to-clear line is rendered.
        WHO: ``_dispatch_slash_command`` for a result carrying ``tui_dismiss``,
            in place of writing the result's empty ``rendered`` text.
        WHEN: Immediately after the router returns.

        Args:
            request (WorkflowListDismissRequestDAO): Validated list-clearing request.
        """
        service: Optional[DetachedWorkflowAppService] = self._workflow_app_service
        outcome: WorkflowListDismissOutcomeDAO = (
            WorkflowListDismissOutcomeDAO()
            if service is None
            else service.dismiss_from_list(target_id=request.target_id)
        )
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(content=outcome.rendered, classes="tool-result")
        self._request_workflow_refresh()

    async def _apply_session_snapshot(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Apply a snapshot to the panel and return focus if its list vanished.

        WHAT: The panel never focuses anything itself. When an empty snapshot hides
            a list that held focus, focus returns to the prompt editor, but only on
            the base screen (never behind a modal).
        WHO: ``WorkflowProgressUpdatesAdapter.apply_sessions`` for every coordinator refresh.
        WHEN: Whenever a fresh session snapshot is available.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Ordered rows to display.
        """
        if self._fleet_panel is None:
            return
        list_focused: bool = self._session_list_holds_focus()
        await self._fleet_panel.apply_snapshot(snapshot=snapshot)
        if snapshot.rows:
            return
        self._return_focus_from_hidden_list(list_focused=list_focused)

    async def _reset_session_list(self) -> None:
        """Empty and hide the session list, returning focus if the list held it.

        WHAT: The single app-owned reset path, so every emptying of the panel
            carries the same base-screen focus-return rule as an empty snapshot.
        WHO: ``_close_workflow_observation`` on owner replacement and unmount.
        WHEN: After the coordinator, service and sink of the old owner are closed.
        """
        if self._fleet_panel is None:
            return
        list_focused: bool = self._session_list_holds_focus()
        await self._fleet_panel.reset()
        self._return_focus_from_hidden_list(list_focused=list_focused)

    def _session_list_holds_focus(self) -> bool:
        """Return whether the session list (or one of its rows) holds focus.

        Returns:
            bool: True when the mounted panel or a descendant is focused.
        """
        if self._fleet_panel is None:
            return False
        return self._fleet_panel.has_focus or self._fleet_panel.has_focus_within

    def _focus_after_progress(self) -> None:
        """Return focus to the list, or to the prompt when the list is empty, on the base screen.

        WHO: ``WorkflowProgressUpdatesAdapter`` once its progress view has left the stack.
        WHEN: Only when no other modal remains above the base screen.
        """
        if len(self.screen_stack) > 1 or self._fleet_panel is None or self._input is None:
            return
        if self._fleet_panel.display:
            self._fleet_panel.focus_sessions()
            return
        self._input.focus()

    def _return_focus_from_hidden_list(self, *, list_focused: bool) -> None:
        """Focus the prompt editor after a focused list was hidden on the base screen.

        Args:
            list_focused (bool): Whether the list held focus before it was emptied.
        """
        if not list_focused or len(self.screen_stack) > 1 or self._input is None:
            return
        self._input.focus()

    def _maybe_launch_visualizer(self) -> None:
        """Open the workflow visualizer window on the first sub-agent of a run.

        Launches ``slo visualize --session <id> --follow`` in a new terminal
        window exactly once per run so the operator sees the sub-agent workflow
        live without running the command by hand. Best-effort: when the launch
        is skipped or fails (auto-visualize disabled, unsupported platform, no
        terminal emulator), a one-line hint with the manual command is written
        to the transcript instead. A no-op after the first spawn of a run.
        """
        if self._visualizer_launched_for_run:
            return
        self._visualizer_launched_for_run = True
        from src.tui.visualizer_launcher import VisualizerLauncher  # noqa: PLC0415

        parent_session_id: str = self._session.session_id
        launcher = self._visualizer_launcher or VisualizerLauncher.launch
        launched: bool = launcher(parent_session_id=parent_session_id)
        if self._chat_transcript is None:
            return
        if launched:
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=f"⊇ Opened workflow visualizer in a new window (session {parent_session_id}).",
                    classes="sub-agent-notice",
                )
            return
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=("⊇ Watch sub-agents live: " f"slo visualize --session {parent_session_id} --follow"),
                classes="sub-agent-notice",
            )

    async def _cleanup_sub_agent_state(self) -> None:
        """Reset per-run sub-agent state at the end of a run.

        Called from ``_run_prompt``'s ``finally`` block after
        ``_unmount_spinner``. Clears the per-run visualizer-launch guard so the
        next run that spawns sub-agents opens a fresh visualizer window. The
        session list is deliberately kept: group retention belongs to the
        workflow service and the observation coordinator (feature 94 a.2), so a
        finished prompt never hides or clears rows.
        """
        self._visualizer_launched_for_run = False
        self._refresh_title_bar()

    # ---- Session and pool management ---------------------------------------

    @staticmethod
    def _attach_pool_to_session(*, session: SloAgentSession) -> None:
        """Promote ``session`` to orchestrator mode via the shared bootstrapper.

        Delegates to ``OrchestratorSessionBootstrap.attach`` — the single
        promotion point shared with the headless ``slo run --orchestrator`` path.
        Called both at boot (``__init__``) and during ``_start_new_session()``
        so every TUI-managed session is silently orchestrator-capable before
        its first prompt.

        Args:
            session (SloAgentSession): Session to promote to orchestrator mode.
        """
        from src.agents.slo_agent.orchestrator.bootstrap import (  # noqa: PLC0415
            OrchestratorSessionBootstrap,
        )

        OrchestratorSessionBootstrap.attach(session=session)

    @staticmethod
    def _build_replacement_session_config(*, old_session: SloAgentSession) -> SessionConfigDAO:
        """Build the session config used when `/new` replaces the active session.

        Args:
            old_session (SloAgentSession): Current session whose runtime shell state is preserved.

        Returns:
            SessionConfigDAO: Replacement session config.
        """
        return SessionConfigDAO(
            workdir=old_session.workdir,
            model_name=old_session.active_model_name,
            model_pool_dao=old_session.model_pool_dao,
            reasoning_level=old_session.active_reasoning_level,
            history_root=old_session.history_root,
            enable_history=old_session.history_enabled,
        )

    async def _run_prompt(self, *, text: str) -> None:
        """Drain ``session.invoke`` to completion.

        WHAT: Renders one run's stream events, surfaces failures inline, and
        hands off to any held queued prompt from its ``finally``.
        WHO: ``_start_accepted_prompt`` and ``_start_inbox_chat_turn`` schedule
        it as the single app-owned run task.
        WHEN: Once per accepted user turn or claimed inbox chat turn; success,
        provider failure, cooperative abort, and hard cancellation all reach
        the same terminal cleanup.

        Args:
            text (str): The user prompt.
        """
        assert self._chat_transcript is not None
        self._chat_transcript.begin_run()
        await self._mount_spinner()
        saw_failed_event: bool = False
        try:
            async for event in self._session.invoke(text=text):
                if event.kind in {"run_failed", "recovery_exhausted"}:
                    saw_failed_event = True
        except asyncio.CancelledError:
            # Hard-cancel escalation from /abort or ^C landed on a run that
            # would not wind down cooperatively (e.g. a hung tool call).
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(content="(aborted)", classes="assistant-aborted")
        except ValueError as exc:
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=f"(configuration error: {exc})",
                    classes="tool-result",
                )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the user
            if not saw_failed_event:
                self._render_run_error(exc=exc)
        finally:
            await self._refresh_context_window_after_prompt()
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            await self._unmount_spinner()
            await self._cleanup_sub_agent_state()
            await self._finish_prompt_run()

    async def _finish_prompt_run(self) -> None:
        """Atomically hand off a completed run to its queued successor.

        WHAT: Keeps the completed task as the app run guard until the queue is
        consumed or the app becomes idle.
        WHO: ``_run_prompt`` calls it as its final cleanup step.
        WHEN: Runs after successful, failed, aborted, or cancelled prompt runs.
        """
        completed_task: Optional[asyncio.Task[None]] = self._in_flight_task
        if completed_task is None or completed_task is not asyncio.current_task():
            return

        async with self._prompt_submission_lock:
            tracked_task: Optional[asyncio.Task[None]] = self._in_flight_task
            if tracked_task is None or tracked_task is not completed_task:
                return
            await self._start_queued_prompt_if_idle(completed_task=tracked_task)

    async def _start_queued_prompt_if_idle(
        self,
        *,
        completed_task: asyncio.Task[None],
    ) -> None:
        """Consume the held prompt or mark the completed app run idle.

        WHAT: Removes and starts the held prompt before releasing app task ownership.
        WHO: ``_finish_prompt_run`` calls it while holding the submission gate.
        WHEN: Immediately after the tracked run reaches its terminal cleanup.

        Args:
            completed_task (asyncio.Task[None]): The finished run task that must
                still own the app run guard for the handoff to proceed.
        """
        if self._in_flight_task is not completed_task:
            return

        text: Optional[str] = self._queued_prompt_text
        if text is None:
            self._in_flight_task = None
            return

        self._queued_prompt_text = None
        await self._remove_queued_prompt_block()
        await self._start_accepted_prompt(text=text)

    async def _refresh_context_window_after_prompt(self) -> None:
        """Refresh durable Context Window Snapshot exactly once at prompt cleanup."""
        try:
            await self._session.refresh_context_window_snapshot()
        except Exception as exc:  # noqa: BLE001
            log_error(msg="context_window_prompt_refresh_failed", error=str(exc))

    def _render_run_error(self, *, exc: BaseException) -> None:
        """Render a run-level error into the transcript.

        The provider exception type is the most useful signal for the
        common cases (``RateLimitError``, ``AuthenticationError``,
        ``APIConnectionError``, ``BadRequestError``, ...), so it is
        included verbatim alongside the message body. Long upstream
        bodies are truncated to keep the transcript scannable.

        Args:
            exc (BaseException): The exception that terminated the run.
        """
        message: str = self._format_exception_for_transcript(exc=exc)
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=f"(error: {message})",
                classes="assistant-aborted",
            )

    @staticmethod
    def _format_exception_for_transcript(*, exc: BaseException) -> str:
        """Format ``exc`` for a single transcript line.

        Specialises ``openai.RateLimitError`` so the body is shown
        without the noisy ``<ExcType>:`` prefix — the message body is
        already user-friendly (plan-aware quota copy from OpenAI) and
        the prefix adds visual clutter on the only failure mode users
        hit regularly when their ChatGPT plan resets (feature 07).

        Args:
            exc (BaseException): The exception to format.

        Returns:
            str: ``"<ExcType>: <body>"`` for generic exceptions, or just
                ``"<body>"`` for the specialised ones, truncated to a
                readable cap in either case.
        """
        body: str = str(exc) or repr(exc)
        first_line: str = body.split(sep="\n", maxsplit=1)[0]
        cap: int = 300
        if len(first_line) > cap:
            first_line = f"{first_line[:cap]}…"
        if SloTUI._is_user_friendly_provider_error(exc=exc):
            return first_line
        return f"{type(exc).__name__}: {first_line}"

    @staticmethod
    def _is_user_friendly_provider_error(*, exc: BaseException) -> bool:
        """Return ``True`` for provider errors whose body is user-ready.

        Lazy-imports ``openai.RateLimitError`` so the TUI module remains
        buildable in any future configuration that strips the ``openai``
        dependency.

        Args:
            exc (BaseException): The exception under inspection.

        Returns:
            bool: ``True`` when the exception class is known to carry a
                self-contained, user-readable message.
        """
        try:
            from openai import RateLimitError
        except ImportError:
            return False
        return isinstance(exc, RateLimitError)

    async def _render_event(self, event: AgentStreamEventDAO) -> None:
        """Project one normalized stream event into transcript widgets.

        Special-case handling before the generic projector path:

        - ``run_retrying`` — updates the spinner and refreshes the status bar,
          then returns early (no transcript entry written).
        - Compaction lifecycle events (``compaction_started``, ``compaction_completed``,
          ``compaction_failed``, ``compaction_retrying``) — update the spinner via
          ``_apply_compaction_spinner_update``, do NOT clear the spinner override
          to ``None``, and then fall through to the projector so a transcript notice
          is also written.
        - Sub-agent events route to ``_route_sub_agent_event`` and never reach the
          orchestrator projector.
        - Orchestrator events render into pane [0] through the normal projector path.

        Args:
            event (AgentStreamEventDAO): Normalized stream event.
        """
        if event.kind == "run_retrying":
            if self._spinner is not None:
                self._spinner.set_override_status(text=event.content or "Retrying…")
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            return
        if event.kind == "stream_reconnecting":
            self._render_stream_reconnecting_event(event=event)
            return
        if event.kind == "preflight_bypassed":
            self._render_preflight_bypassed_event()
            return
        if event.kind == "compaction_advised":
            if self._chat_transcript is not None:
                self._chat_transcript.write_transcript_line(
                    content=event.content or "Run /compact to help latency.",
                    classes="tool-result",
                )
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            return
        self._apply_compaction_spinner_update(event=event)
        self._apply_recovery_spinner_update(event=event)
        if self._spinner is not None and event.kind not in {
            "compaction_started",
            "compaction_completed",
            "compaction_failed",
            "compaction_retrying",
            "recovery_started",
            "recovery_succeeded",
            "recovery_exhausted",
        }:
            self._spinner.set_override_status(text=None)
        if event.kind == "tool_result" and event.tool_name == "launch_workflow":
            # Primary visualizer trigger (spec 57.a.5): the launch turn's tool
            # result carries the handle JSON with the orchestrator session id.
            self._maybe_launch_workflow_visualizer(result_text=event.content or "")
        if event.sub_agent_id is not None:
            await self._route_sub_agent_event(event=event)
            return
        if event.kind == "sub_agent_dispatch_started":
            # Stream-only batch start (no sub_agent_id): the list shows the new group.
            self._request_workflow_refresh()
            return
        if self._chat_transcript is not None:
            await self._chat_transcript.present_event(event=event)
        if event.kind == "steering_applied":
            return
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    def _render_preflight_bypassed_event(self) -> None:
        """Render the fixed local TPM bypass note without diagnostic metadata."""
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content="(local token preflight bypassed; request sent to provider)",
                classes="tool-result",
            )
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    def _render_stream_reconnecting_event(self, *, event: AgentStreamEventDAO) -> None:
        """Render the public pre-commit reconnect boundary without raw provider text.

        ``_render_event`` calls this for the session-owned audit event before the
        fresh provider request begins. The copy intentionally uses only the
        approved reason code and exception family metadata.
        """
        reason_code: object = event.metadata.get("reason_code")
        exception_family: object = event.metadata.get("exception_family")
        reason: str = reason_code if isinstance(reason_code, str) else "provider_stream_disconnected"
        family: str = exception_family if isinstance(exception_family, str) else "transport error"
        if self._spinner is not None:
            self._spinner.set_override_status(text="Reconnecting provider stream…")
        if self._chat_transcript is not None:
            self._chat_transcript.write_transcript_line(
                content=f"(reconnecting after {reason}: {family})",
                classes="tool-result",
            )
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    def _apply_compaction_spinner_update(self, *, event: AgentStreamEventDAO) -> None:
        """Update spinner copy for compaction lifecycle events.

        A no-op for non-compaction event kinds. Called unconditionally from
        ``_render_event`` before the projector path so the spinner reflects
        compaction state while the projector writes the transcript notice.

        Args:
            event (AgentStreamEventDAO): Live stream event.
        """
        if event.kind == "compaction_started":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Compacting session history…")
        elif event.kind == "compaction_completed":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Compaction complete.")
        elif event.kind == "compaction_retrying":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Retrying original message…")
        elif event.kind == "compaction_failed":
            if self._spinner is not None:
                self._spinner.set_override_status(
                    text=f"Compaction failed: {event.content}" if event.content else "Compaction failed."
                )

    def _apply_recovery_spinner_update(self, *, event: AgentStreamEventDAO) -> None:
        """Update spinner copy for recovery lifecycle events.

        A no-op for non-recovery event kinds. Called unconditionally from
        ``_render_event`` before the projector path so the spinner reflects
        recovery state while the projector writes the transcript notice.

        Args:
            event (AgentStreamEventDAO): Live stream event.
        """
        if event.kind == "recovery_started":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Recovering from error…")
        elif event.kind == "recovery_succeeded":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Recovered — continuing.")
        elif event.kind == "recovery_exhausted":
            if self._spinner is not None:
                self._spinner.set_override_status(text="Could not recover automatically.")

    async def _mount_slash_activity(self, *, line: str) -> bool:
        """Mount the fixed activity spinner for a long-running slash command.

        WHAT: Returns ``True`` only when this call mounted the spinner.
        WHO: ``_dispatch_slash_command`` calls it before dispatch.
        WHEN: Only for a registry command flagged ``shows_activity`` and only
        while no run spinner is already mounted, so a caller never removes a
        spinner it did not mount.

        Args:
            line (str): The full input line including the leading slash.

        Returns:
            bool: ``True`` when this call mounted the spinner.
        """
        if not SlashRouter.requires_activity(line=line):
            return False
        if self._spinner is not None:
            return False
        await self._mount_spinner()
        return True

    async def _mount_spinner(self) -> None:
        """Mount a fixed ``ThinkingSpinner`` above the prompt input.

        Idempotent: if a spinner is already mounted it is left in
        place. Called once at the start of each ``_run_prompt`` and
        kept mounted until the run terminates.
        """
        if self._spinner is not None:
            return
        spinner: ThinkingSpinner = ThinkingSpinner()
        self._spinner = spinner
        if self._status_region is not None:
            await self._status_region.mount(spinner)

    async def _unmount_spinner(self) -> None:
        """Remove the fixed status spinner when the run terminates.

        Idempotent: a no-op when there is no spinner. Called from
        ``_run_prompt``'s ``finally`` clause when the run terminates.
        """
        if self._spinner is None:
            return
        spinner: ThinkingSpinner = self._spinner
        self._spinner = None
        await spinner.remove()

    def _focused_block_text(self) -> str:
        """Return the copyable text of the focused transcript block, or ``""``.

        Inspects ``self.focused`` for a ``get_copyable_text`` method. Used
        by ``action_copy_visible_text`` to implement the focused-block-first
        resolution tier. A no-op (returns ``""``) for any focused widget that
        does not implement the protocol (e.g. ``PromptInput``,
        ``VerticalScroll``, ``Footer``).

        Returns:
            str: The transcript block's copyable text, or ``""`` when the
                focused widget does not participate in the copy protocol.
        """
        focused = self.focused
        if focused is None:
            return ""
        get_text = getattr(focused, "get_copyable_text", None)
        if get_text is None:
            return ""
        return get_text()

    def _focused_raw_markdown(self) -> str:
        """Resolve raw Markdown from the focused widget or nearest provider ancestor."""
        focused = self.focused
        if focused is None:
            return ""
        for widget in (focused, *focused.ancestors):
            if "get_raw_markdown_for_copy" not in vars(widget):
                provider = getattr(widget, "get_raw_markdown_for_copy", None)
                if provider is None:
                    continue
            else:
                provider = vars(widget)["get_raw_markdown_for_copy"]
            if not callable(provider):
                return ""
            raw_markdown = provider()
            return raw_markdown if isinstance(raw_markdown, str) and raw_markdown else ""
        return ""

    def _selected_prompt_text(self) -> str:
        """Return the selected prompt text, or ``""`` when nothing is selected."""
        if self._input is None:
            return ""
        return self._input.selected_text or ""
