"""Textual app for the ``slo`` default subcommand (sub-spec 02.a.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Optional, Protocol, cast

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.timer import Timer
from textual.widget import Widget
from textual.worker import Worker, WorkerCancelled, WorkerFailed
from textual.widgets import Footer, Header, Static

from config.ai_model_config import default_model_for_provider
from config.cfg import cfg
from config.logger import log_error
from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO, VisualizerLaunchOutcomeDAO
from src.agents.slo_agent.herdr.service import HerdrTaskJoin
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowResumeLauncher
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.dao import SessionOwnershipLeaseDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.reasoning_capabilities import resolve_reasoning_config
from src.auth.browser_host import BrowserHost
from src.auth.credential_dao import CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.chat_transcript.commands import (
    SetTranscriptVisibilityDAO,
    ScrollTranscriptBottomDAO,
    ToggleTranscriptDetailsDAO,
    TranscriptNoticeDAO,
    EchoUserDAO,
    PresentAgentEventDAO,
    HydrateTranscriptDAO,
    BindHistoryDAO,
    ClearTranscriptDAO,
    BeginTranscriptRunDAO,
    ShowPendingSteeringDAO,
    MountTreeOutputDAO,
)
from src.tui.components.workflow_progress.component import WorkflowProgressComponent
from src.tui.components.workflow_progress.events import ConfirmAbortDAO
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.components.prompt_input.commands import (
    ClearSubmissionDAO,
    ReplacePromptDAO,
    HideSuggestionsDAO,
    RecordAcceptedPromptDAO,
    SetModelContextDAO,
    RecordModelSelectionDAO,
    RefreshPublishedSuggestionsDAO,
    PublishSuggestionsDAO,
    ReplacePathSpanDAO,
)
from src.tui.authentication import AuthenticationScreen
from src.tui.path_suggestion_engine import PathSuggestionReader
from src.tui.path_suggestion_controller import PathPromptSnapshotDAO, PathSuggestionController
from src.tui.slash_router import SlashCommandAdmissionDAO, SlashCommandResultDAO, SlashRouter
from src.tui.session_event_presentation import SessionEventPresentation, SessionEventPresentationDAO
from src.tui.model_catalog import ModelSuggestionProjection
from src.tui.slash_suggestion_engine import SlashSuggestionEngine, SlashSuggestionStateDAO
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.thinking_spinner import ThinkingSpinner
from src.tui.tree_export_format import TreeExportFormat
from src.tui.editor_launcher import EditorLauncher
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
    ProgressViewportDAO,
    SessionProgressSnapshotDAO,
    WorkflowListVisibilityOutcomeDAO,
    WorkflowListVisibilityRequestDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.progress_coordinator import (
    WorkflowProgressCoordinator,
    WorkflowProgressSink,
    WorkflowProgressSource,
)
from src.tui.workflows.renderer import DetachedWorkflowRenderer
from src.tui.workflows.service import AttachedChildAbort, DetachedWorkflowAppService
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO, ChildControlCapabilityDAO
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.session_progress_screen import SessionProgressScreen


class WorkflowCoordinatorFactory(Protocol):
    """Construct one coordinator with the app-owned source, sink and timer."""

    def __call__(
        self,
        *,
        service: WorkflowProgressSource,
        sink: WorkflowProgressSink,
        schedule: Callable[[float, Callable[[], None]], Timer],
    ) -> WorkflowProgressCoordinator:
        """Bind observation without starting another timer or owner.

        Args:
            service: Current observation source.
            sink: App-owned presentation sink.
            schedule: App-owned timer registration.

        Returns:
            WorkflowProgressCoordinator: Unstarted coordinator borrowing these boundaries.
        """
        ...


class WorkflowAppServiceFactory(Protocol):
    """Compose a fresh real workflow observation owner for each mounted session."""

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
        """Bind the supplied owner and borrowed adapters without starting reads.

        Args:
            workflow_handle_store: Optional durable handle adapter.
            owner_session_id: Current session identity.
            attached_snapshot: Current pool membership supplier.
            history_store: Optional bounded history source.
            attached_abort: Optional pool child-abort gateway.
            attached_capability: Optional current abort capability supplier.

        Returns:
            DetachedWorkflowAppService: Fresh session-owned observation service.
        """
        ...


__all__ = ["SloTUI"]


@dataclass(frozen=True)
class _DeliveryInitialization:
    """Exact app-owned binding captured before initialization yields."""

    session: SloAgentSession
    session_id: str
    owner_id: str
    lease_store: Optional[SessionOwnershipLeaseStore]
    inbox_store: Optional[SessionInboxStore]
    service: Optional[DetachedWorkflowAppService]
    renderer: Optional[DetachedWorkflowRenderer]


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
        visualizer_launcher: Optional[Callable[..., bool]] = None,
        workflow_service_factory: Optional[WorkflowAppServiceFactory] = None,
        workflow_coordinator_factory: Optional[WorkflowCoordinatorFactory] = None,
        workflow_resume_launcher: Optional[WorkflowResumeLauncher] = None,
        path_reader: Optional[PathSuggestionReader] = None,
        editor_launcher: Optional[EditorLauncher] = None,
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
            path_reader: Optional off-thread path reader; defaults to real immediate enumeration.
            editor_launcher: Optional local editor validation/submission boundary.
            workflow_resume_launcher: Optional workflow process/capture launch boundary.
            workflow_service_factory: Optional real-service composition boundary.
            workflow_coordinator_factory: Optional coordinator composition boundary;
                defaults to the production coordinator with the app-owned sink.
        """
        super().__init__()
        self._session_factory = session_factory
        self._visualizer_launcher = visualizer_launcher
        self._workflow_resume_launcher = workflow_resume_launcher
        self._escape_deadline: float = 0.0
        self._editor_launcher = editor_launcher or EditorLauncher()
        self._editor_launch_tasks: dict[Worker[None], asyncio.Task[None]] = {}
        self._workflow_service_factory: WorkflowAppServiceFactory = (
            workflow_service_factory or DetachedWorkflowAppService
        )
        self._workflow_coordinator_factory: WorkflowCoordinatorFactory = (
            workflow_coordinator_factory or WorkflowProgressCoordinator
        )
        self._workflow_visibility_lock: asyncio.Lock = asyncio.Lock()
        self._workflow_observation_close_task: Optional[asyncio.Task[None]] = None
        self._browser_host: BrowserHost = browser_host or BrowserHost.current()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = self.DEFAULT_THEME
        self._session: SloAgentSession = session
        self._preparation_task: Optional[asyncio.Task[None]] = None
        self._candidate_cleanup_task: Optional[asyncio.Task[None]] = None
        self._mount_runtime_task: Optional[asyncio.Task[None]] = None
        self._app_closing: bool = False
        self._app_shutdown_task: Optional[asyncio.Task[None]] = None
        self._shutdown_started: bool = False
        self._session_replacement_task: Optional[asyncio.Task[None]] = None
        self._session_transitioning: bool = False
        self._retired_herdr_session: Optional[SloAgentSession] = None
        self._retired_herdr_drain_task: Optional[asyncio.Task[None]] = None
        self._selected_herdr_drain_task: Optional[asyncio.Task[None]] = None
        self._herdr_successor_suppressed: bool = False
        self._replacement_delivery_safe: bool = True
        self._delivery_quiescing: bool = False
        self._attach_pool_to_session(session=self._session)
        self._chat_transcript: ChatTranscriptComponent = ChatTranscriptComponent(
            history_reader=self._session.hydrate_transcript_entries
        )
        self._chat_shell: Optional[Vertical] = None
        self._status_region: Optional[Vertical] = None
        self._input: Optional[PromptInputComponent] = None
        self._suggestion_menu: Optional[SlashSuggestionMenu] = None
        self._suggestions_bound: bool = False
        """True once the mounted editor has adopted its suggestion collaborators."""
        self._usage_status_bar: Optional[UsageStatusBar] = None
        self._in_flight_task: Optional[asyncio.Task[None]] = None
        self._prompt_submission_lock: asyncio.Lock = asyncio.Lock()
        """Serializes ordinary-prompt acceptance and run-completion handoff only."""
        self._queued_prompt_text: Optional[str] = None
        """One-deep latest-wins ordinary text not yet accepted as a user turn."""
        self._queued_prompt_block: Optional[QueuedPromptBlock] = None
        """Mounted visual counterpart of ``_queued_prompt_text``, when mounted."""
        self._spinner: Optional[ThinkingSpinner] = None
        self._path_suggestions = PathSuggestionController(
            view=self, reader=path_reader, run_worker=self.run_worker
        )
        # Workflow progress owns the fleet panel and its observation-lifetime adapter.
        self._workflow_progress: Optional[WorkflowProgressComponent] = None
        # Guards one-per-run auto-launch of the workflow visualizer window.
        self._visualizer_launched_for_run: bool = False
        self._visualizer_launch_tasks: dict[str, asyncio.Task[None]] = {}
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
        self._workflow_progress_updates_adapter: Optional[WorkflowProgressSink] = None
        # Session the observation trio is bound to; None while unbound. Recorded
        # only after the coordinator's no-await start completes, and cleared first
        # on close, so a matching session ID alone never proves a healthy binding:
        # rollback and rebind require coordinator, service and sink to be present
        # and unclosed for that exact identity.
        self._workflow_observation_session_id: Optional[str] = None
        self._workflow_renderer: Optional[DetachedWorkflowRenderer] = None
        self._inbox_store: Optional[SessionInboxStore] = inbox_store
        self._lease_store: Optional[SessionOwnershipLeaseStore] = lease_store
        self._session_owner_id: str = SessionOwnershipLeaseStore.default_owner_id()
        self._lease_timer: Optional[Timer] = None
        self._inbox_timer: Optional[Timer] = None
        self._failed_delivery_timers: tuple[Timer, ...] = ()

    def compose(self) -> ComposeResult:
        """Build the widget tree.

        Yields:
            Header, the transcript + input vertical, and Footer.
        """
        yield Header(show_clock=False)
        self._chat_shell = Vertical(id="chat-shell")
        with self._chat_shell:
            yield self._chat_transcript
            self._status_region = Vertical(id="status-region")
            self._suggestion_menu = SlashSuggestionMenu()
            with self._status_region:
                yield self._suggestion_menu
            self._input = PromptInputComponent()
            yield self._input
            # Workflow progress: below PromptInputComponent, hidden while it has no rows.
            # The orchestrator transcript always stays in the foreground.
            self._workflow_progress = WorkflowProgressComponent(host=self)
            yield self._workflow_progress
            self._usage_status_bar = UsageStatusBar()
            yield self._usage_status_bar
        yield Footer()

    async def set_transcript_visible(self, *, visible: bool) -> None:
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
        await transcript.handle(command=SetTranscriptVisibilityDAO(visible=visible))

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
        session = self._session
        if not self._runtime_may_start(session=session):
            return
        ModelSuggestionProjection.refresh_authentication()
        if self._input is not None and self._suggestion_menu is not None and not self._suggestions_bound:
            await self._input.replace_suggestion_binding(
                path_controller=self._path_suggestions,
                menu=self._suggestion_menu,
                engine=SlashSuggestionEngine(registry=SlashRouter.registry()),
                active_model_name=session.active_model_name,
            )
            self._suggestions_bound = True
        await self._chat_transcript.handle(
            command=HydrateTranscriptDAO(is_current=lambda: self._runtime_may_start(session=session))
        )
        if not self._runtime_may_start(session=session):
            return
        try:
            await self._maybe_render_startup_notice()
        except Exception:
            # A closed or displaced owner must not repaint even a fixed failure
            # notice; revalidate the captured owner before rendering (C7.13).
            if self._runtime_may_start(session=session):
                await self._write_lifecycle_notice(
                    content="Session startup notice unavailable.", classes="tool-result"
                )
        if not self._runtime_may_start(session=session):
            return
        self._session.subscribe(handler=self._render_event)
        # The initial owner's observation binds here, once; the mount runtime
        # task below (and every later adoption) goes through the guarded
        # ``_ensure_workflow_observation_bound`` re-entry point instead.
        await self._bind_workflow_observation()
        self._mount_runtime_task = asyncio.create_task(coro=self._initialize_mounted_delivery())
        cancelled = await HerdrTaskJoin.wait(task=self._mount_runtime_task)
        self._mount_runtime_task.result()
        if cancelled:
            raise asyncio.CancelledError
        if not self._runtime_may_start(session=session):
            return
        if self._input is not None:
            self._input.focus()
        if not self._has_credential_for_active_model():
            self._push_auth_modal()

    def _runtime_may_start(self, *, session: SloAgentSession) -> bool:
        """Check captured identity against the irreversible app cutoff.

        Args:
            session: Owner captured before the asynchronous continuation.

        Returns:
            bool: Whether that owner remains selected and the app is open.
        """
        return not self._app_closing and self._session is session

    def _start_session_preparation(self) -> None:
        """Start one tracked catalog worker after mount or explicit recovery.

        The session owns discovery and atomic adoption; the app owns task lifetime
        and safe status rendering. Repeated retry requests join the active worker.
        """
        if self._app_closing:
            return
        if self._preparation_task is not None and not self._preparation_task.done():
            return
        if self._session.preparation_status == "ready":
            return
        session: SloAgentSession = self._session
        self._preparation_task = asyncio.create_task(self._prepare_mounted_session(session=session))

    async def _prepare_mounted_session(self, *, session: SloAgentSession) -> None:
        """Prepare ``session`` and render only while it remains the mounted session.

        Capturing the target session prevents a worker superseded by ``/new`` from
        preparing or repainting the replacement session after its cancellation.
        """
        await self._write_lifecycle_notice(
            content="Preparing model catalog; limits unknown.", classes="tool-result"
        )
        try:
            await session.prepare_startup()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._runtime_may_start(session=session):
                guidance = (
                    str(error)
                    if session.active_model_name.startswith("claude-bridge:")
                    else "Model preparation failed; use /auth or /model refresh to retry."
                )
                await self._write_lifecycle_notice(
                    content=guidance,
                    classes="tool-result",
                )
        else:
            if self._runtime_may_start(session=session):
                await self._write_lifecycle_notice(content="Model catalog ready.", classes="tool-result")
                if self._input is not None:
                    await self._input.handle(
                        command=SetModelContextDAO(active_model_name=session.active_model_name)
                    )
        if self._runtime_may_start(session=session):
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
        """Render the one-time startup notice for new sessions only.

        The session is captured at entry and revalidated after the real
        history predicate await and before any rendering or marker
        persistence: ``on_mount`` is not yet registered as
        ``_mount_runtime_task`` while it awaits this helper, so public
        ``on_unmount`` may complete first. A closed or displaced owner must
        not repaint or persist ``startup_notice_shown_at`` after that
        cutoff (C7.13). A marker write already admitted before the cutoff
        remains owned and is never cancelled.
        """
        session = self._session
        if session.preparation_status != "ready":
            return
        if not await session.should_show_startup_notice():
            return
        if not self._runtime_may_start(session=session):
            return
        fallback_notice: Optional[str] = session.startup_fallback_notice
        if fallback_notice:
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(
                        content=fallback_notice,
                        classes="tool-result",
                    )
                )
        resolved_reasoning = resolve_reasoning_config(
            model_name=session.active_model_name,
            requested_level=session.active_reasoning_level,
            snapshot=session.catalog_snapshot,
        )
        reasoning_detail: str = self._reasoning_detail_text(
            provider_effort=resolved_reasoning.provider_effort,
            provider_budget_tokens=resolved_reasoning.provider_budget_tokens,
        )
        await self._chat_transcript.handle(
            command=TranscriptNoticeDAO(
                content=(
                    "slo, Copyright (C) 2026 Siddharth Ravichandran. "
                    "This program comes with ABSOLUTELY NO WARRANTY; see LICENSE. "
                    "This is free software, and you are welcome to redistribute it under GPLv2."
                ),
                classes="tool-result",
            )
        )
        await self._chat_transcript.handle(
            command=TranscriptNoticeDAO(
                content=(
                    "Tip: use /help to see available commands. "
                    f"Session: {session.session_id}. "
                    f"Initialized model: {session.active_model_name}. "
                    f"Reasoning: {session.active_reasoning_level}. "
                    f"Provider detail: {reasoning_detail}."
                ),
                classes="tool-result",
            )
        )
        await session.mark_startup_notice_shown()

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
        if self._session.active_model_name.startswith("claude-bridge:"):
            return True  # Native login is checked by the bridge, never the Slo token modal.
        try:
            provider: ProviderName = provider_for_model(
                model_name=self._session.active_model_name,
            )
        except ValueError:
            return True
        return CredentialResolver.resolve(provider=provider) is not None

    async def _toggle_theme(self) -> None:
        """Toggle the active theme between slo-default and slo-dark.

        If the current theme is neither of the two, switches to slo-default.
        """
        next_theme: str = (
            SLO_DARK_THEME.name if self.theme == SLO_DEFAULT_THEME.name else SLO_DEFAULT_THEME.name
        )
        self.theme = next_theme
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(content=f"theme: {next_theme}", classes="tool-result")
            )

    def _push_auth_modal(self) -> None:
        """Push ``AuthenticationScreen`` only while the app lifetime is open."""
        if getattr(self, "_app_closing", False):
            return
        session = self._session
        token = session.set_operator_attention(reason="Authentication required")

        async def dismiss(value: Optional[CredentialDAO]) -> None:
            """Complete only the auth request owned by this captured session."""
            if not self._runtime_may_start(session=session):
                return
            if value is not None or self._has_credential_for_active_model():
                session.clear_operator_attention(token=token)
            await self._on_auth_dismissed(value)

        self.push_screen(AuthenticationScreen(), callback=dismiss)

    async def _on_auth_dismissed(self, value: Optional[CredentialDAO]) -> None:
        """Refresh the active model and title state after auth success.

        Args:
            value (Optional[CredentialDAO]): ``CredentialDAO`` on success,
                ``None`` on cancel.
        """
        if getattr(self, "_app_closing", False):
            return
        ModelSuggestionProjection.refresh_authentication(verified_credential=value)
        if self._input is not None:
            await self._input.handle(
                command=SetModelContextDAO(active_model_name=self._session.active_model_name)
            )
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
                    await self._chat_transcript.handle(
                        command=TranscriptNoticeDAO(
                            content="Key verified; choose a model with /model.", classes="tool-result"
                        )
                    )
                await self._prime_model_picker_after_auth()
                return
            try:
                self._session.switch_model(model_name=new_model_name)
            except RuntimeError:
                pass
            else:
                if self._input is not None:
                    await self._input.handle(command=SetModelContextDAO(active_model_name=new_model_name))
                if self._chat_transcript is not None:
                    await self._chat_transcript.handle(
                        command=TranscriptNoticeDAO(
                            content=f"active model switched to {new_model_name}",
                            classes="tool-result",
                        )
                    )
        self._refresh_title_bar(subject=value.subject)
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    async def _prime_model_picker_after_auth(self) -> None:
        """Focus and seed the local model picker after authentication has no landing route.

        WHAT: Gives API-key-only providers a direct path to cached ``/model``
            search without selecting an arbitrary remote route.
        WHO: ``_on_auth_dismissed`` calls it after a verified provider has no
            configured default model.
        WHEN: Only after the authentication modal returns a successful credential.
        """
        if self._input is None:
            return
        await self._input.handle(command=ReplacePromptDAO(text="/model "))
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
        """Refresh the main header from the selected session after lifecycle changes.

        Model, authentication and usage details remain on their separate surfaces.

        Args:
            subject (Optional[str]): Accepted for auth-callback compatibility;
                authenticated identity is not displayed in the header.
        """
        workdir_text: str = self._collapse_home_in_path(path=self._session.workdir)
        self.title = f"slo · {workdir_text} · session {self._session.session_id}"
        self.sub_title = ""

    def _refresh_usage_status_bar(self) -> None:
        """Refresh the persistent usage-and-limits widget."""
        if self._usage_status_bar is None:
            return
        self._usage_status_bar.update_snapshot(
            snapshot=self._session.usage_snapshot(),
            plugin_statuses=self._session.plugin_status_map(),
        )

    async def _shutdown(self) -> None:
        """Join the observation barrier before Textual prunes the presentation tree.

        WHAT: Seals application admission, joins in-flight mount/replacement
            runtime work outside the prompt-submission lock, then joins the one
            retained observation close task (coordinator → service → component
            retirement) before delegating to the superclass's actual shutdown
            batch (screen pruning, message close, driver close). Reentrant calls
            (``run_test`` exit and ``run_async`` finally can both dispatch this)
            return at once: the first call owns the full sequence.
        WHO: Installed Textual dispatches this on the SloTUI subclass from both
            ``run_async`` (shielded, normal exit/error/cancellation) and
            ``run_test`` context exit; it is application lifecycle integration,
            not framework modification. The private seam keeps the installed
            no-argument async signature and delegates exactly once.
        WHEN: Before any superclass pruning: ``App._shutdown`` closes screens
            and unmounts widgets *before* dispatching app Unmount, so the
            observation join must already have happened here. The superclass
            call lives in ``finally`` so a pre-close failure or cancellation
            can never skip real framework cleanup.
        """
        if self._shutdown_started:
            return
        self._shutdown_started = True
        try:
            await self._join_observation_before_superclass_pruning()
        finally:
            await super()._shutdown()

    async def _join_observation_before_superclass_pruning(self) -> None:
        """Seal admission, join runtime work, then join the observation close.

        The cutoff mirrors ``on_unmount`` so no prompt, delivery or external
        report is admitted after shutdown begins; the joins reuse the retained
        mount/replacement tasks outside ``_prompt_submission_lock`` and the one
        shielded observation close task — no second shutdown owner is created.
        """
        self._app_closing = True
        self._delivery_quiescing = True
        self._session.begin_external_reporting_close()
        if self._mount_runtime_task is not None:
            await HerdrTaskJoin.wait(task=self._mount_runtime_task)
        if self._session_replacement_task is not None:
            await HerdrTaskJoin.wait(task=self._session_replacement_task)
        await self._close_workflow_observation()

    async def on_unmount(self) -> None:
        """Seal admission before awaiting the single retained shutdown task."""
        self._app_closing = True
        self._path_suggestions.close()
        self._delivery_quiescing = True
        self._session.begin_external_reporting_close()
        if self._app_shutdown_task is None:
            self._app_shutdown_task = asyncio.create_task(coro=self._finish_app_shutdown())
        cancelled = await HerdrTaskJoin.wait(task=self._app_shutdown_task)
        self._app_shutdown_task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _finish_app_shutdown(self) -> None:
        """Join commit outside its caller's gate, then drain the adopted owner."""
        if self._mount_runtime_task is not None:
            await HerdrTaskJoin.wait(task=self._mount_runtime_task)
        replacement = self._session_replacement_task
        if replacement is not None:
            await HerdrTaskJoin.wait(task=replacement)
        await self._shutdown_step(cleanup=self._drain_editor_launches)
        await self._shutdown_step(cleanup=self._cancel_visualizer_launches)
        async with self._prompt_submission_lock:
            session = self._session
            session.begin_external_reporting_close()
            await self._shutdown_step(cleanup=self._cancel_session_preparation)
            await self._shutdown_step(cleanup=self._close_workflow_observation)
            admitted_prompt = self._in_flight_task
            await self._shutdown_step(cleanup=session.close_external_reporting)
            await self._shutdown_step(cleanup=self._close_selected_delivery)
        await self._drain_shutdown_owners(session=session)
        # Ordinary registered tasks may not have entered the session yet.
        # They own no bridge resource and must remain admissible after unmount.
        if admitted_prompt is None or admitted_prompt.done():
            await self._shutdown_step(cleanup=session.close_agent_resources)
        elif session.active_model_name.startswith("claude-bridge:"):
            # Bridge shutdown must settle native waiters. Ordinary admitted
            # prompts retain their established finish/abort policy at unmount.
            await self._shutdown_step(cleanup=session.close_agent_resources)
        await self._shutdown_step(cleanup=self._path_suggestions.join)
        # A failed viewer helper is not evidence that its retained workers ended.
        for task in tuple(self._visualizer_launch_tasks.values()):
            await HerdrTaskJoin.wait(task=task)

    async def _drain_shutdown_owners(self, *, session: SloAgentSession) -> None:
        """Start both final attempts before joining either potentially retained owner.

        Args:
            session: Selected owner captured under the submission gate.
        """
        if self._selected_herdr_drain_task is None:
            self._selected_herdr_drain_task = asyncio.create_task(
                coro=self._finish_shutdown_owner(session=session)
            )
        if self._retired_herdr_session is not None and self._retired_herdr_drain_task is None:
            self._retired_herdr_drain_task = asyncio.create_task(coro=self._finish_retired_session_drain())
        for task in (self._selected_herdr_drain_task, self._retired_herdr_drain_task):
            if task is not None:
                await HerdrTaskJoin.wait(task=task)
                task.result()

    async def _finish_shutdown_owner(self, *, session: SloAgentSession) -> None:
        """Retain failed final cleanup rather than falsely completing graceful teardown.

        Args:
            session: Strongly retained owner of this single final attempt.
        """
        try:
            outcome = await session.finish_retired_reporting_cleanup()
            if outcome.resources == "drained":
                return
        except Exception:
            await self._write_lifecycle_notice(content="Session cleanup incomplete.", classes="tool-result")
        await asyncio.Future()

    async def _shutdown_step(self, *, cleanup: Callable[[], Awaitable[object]]) -> None:
        """Attempt an independent owner even when prior cleanup or diagnostics fail.

        Args:
            cleanup: Bound cleanup for one retained owner.
        """
        try:
            await cleanup()
        except Exception:
            await self._write_lifecycle_notice(content="Session cleanup incomplete.", classes="tool-result")

    async def _close_selected_delivery(self) -> None:
        """Release the captured binding even if subscription removal fails."""
        session = self._session
        try:
            session.unsubscribe(handler=self._render_event)
        finally:
            self._stop_delivery_timers()
            await self._release_replaced_session_lease(session=session)

    async def _drain_retired_session_at_unmount(self) -> None:
        """Join the quarantined session's one final local attempt, never remote retry."""
        if self._retired_herdr_session is None:
            return
        if self._retired_herdr_drain_task is None:
            self._retired_herdr_drain_task = asyncio.create_task(coro=self._finish_retired_session_drain())
        cancelled = await HerdrTaskJoin.wait(task=self._retired_herdr_drain_task)
        self._retired_herdr_drain_task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _finish_retired_session_drain(self) -> None:
        """Keep the explicit owner reachable until its session gateway proves drain."""
        session = self._retired_herdr_session
        assert session is not None
        await self._finish_shutdown_owner(session=session)
        self._retired_herdr_session = None

    async def _initialize_mounted_delivery(self) -> None:
        """Retain mount-owned filesystem work under the submission gate."""
        async with self._prompt_submission_lock:
            await self._finish_replacement_runtime()

    async def _initialize_session_delivery(self) -> None:
        """Contain partial startup before mount or replacement continues."""
        if self._lease_timer is not None or self._inbox_timer is not None:
            return
        session = self._session
        owner_id = self._session_owner_id
        self._delivery_quiescing = True
        if not self._replacement_delivery_safe or not self._session_supports_inbox_delivery():
            return
        try:
            self._build_session_delivery(session=session)
        except Exception:
            await self._rollback_session_delivery(session=session, owner_id=owner_id, timers=())
            await self._write_lifecycle_notice(
                content="Session inbox unavailable; local prompts remain available.", classes="tool-result"
            )
            return
        binding = _DeliveryInitialization(
            session=session,
            session_id=session.session_id,
            owner_id=owner_id,
            lease_store=self._lease_store,
            inbox_store=self._inbox_store,
            service=self._workflow_app_service,
            renderer=self._workflow_renderer,
        )
        timers: list[Timer] = []
        try:
            await self._prepare_session_delivery(binding=binding)
            if binding.service is not None:
                self._publish_delivery_timers(binding=binding, timers=timers)
        except Exception:
            await self._rollback_session_delivery(
                session=session,
                owner_id=owner_id,
                binding=binding,
                timers=tuple(timers),
            )
            await self._write_lifecycle_notice(
                content="Session inbox unavailable; local prompts remain available.",
                classes="tool-result",
            )

    async def _rollback_session_delivery(
        self,
        *,
        session: SloAgentSession,
        owner_id: str,
        binding: Optional[_DeliveryInitialization] = None,
        timers: Optional[tuple[Timer, ...]] = None,
    ) -> None:
        """Unwind partial delivery while retaining timer handles whose stop failed.

        Args:
            session (SloAgentSession): Captured initialization owner, never its successor.
            owner_id (str): Owner captured before the first initialization await.
        """
        self._delivery_quiescing = True
        self._replacement_delivery_safe = False
        try:
            self._stop_delivery_timers(timers=timers)
        finally:
            try:
                await self._release_captured_session_lease(
                    lease_store=self._lease_store if binding is None else binding.lease_store,
                    session_id=session.session_id if binding is None else binding.session_id,
                    owner_id=owner_id,
                )
            finally:
                if binding is not None:
                    if self._workflow_renderer is binding.renderer:
                        self._workflow_renderer = None
                    if self._workflow_app_service is binding.service:
                        await self._close_captured_observation_owner(binding=binding)
                elif self._session is session and self._session_owner_id == owner_id:
                    self._workflow_app_service = None
                    self._workflow_renderer = None

    async def _close_captured_observation_owner(self, *, binding: _DeliveryInitialization) -> None:
        """Retire the still-published owner captured by a failed delivery initialization.

        WHAT: When rollback runs for a binding whose captured service is still
            the app's published observation service, the whole captured
            coordinator → service → sink trio is closed and the panel reset
            once, in the canonical teardown order, so a failed inbox/timer setup
            never orphans a live reader the app can no longer reach. When any
            successor binding (rebind, adoption or an earlier close) displaced
            the capture, nothing is touched: a displaced successor owns its own
            close, and clearing or closing after the lease-release await is
            forbidden.
        WHO: ``_rollback_session_delivery`` only, after the captured lease
            release has been joined.
        WHEN: While the captured identity is still the selected one; a matching
            session ID without the surviving trio is never treated as the
            captured owner.

        Args:
            binding (_DeliveryInitialization): Captured initialization whose
                service is still published.
        """
        coordinator: Optional[WorkflowProgressCoordinator] = self._workflow_progress_coordinator
        service: Optional[DetachedWorkflowAppService] = self._workflow_app_service
        sink: Optional[WorkflowProgressSink] = self._workflow_progress_updates_adapter
        if not (
            self._workflow_observation_session_id == binding.session_id
            and self._session is binding.session
            and coordinator is not None
            and service is not None
            and sink is not None
        ):
            return
        await self._close_workflow_observation()

    def _build_session_delivery(self, *, session: SloAgentSession) -> None:
        """Build inert delivery collaborators before initialization captures ownership.

        Args:
            session: Session whose unchanged history root owns delivery.
        """
        if not self._runtime_may_start(session=session):
            return
        if not self._session_supports_inbox_delivery():
            return
        history_root: Path = cast(Path, self._session.history_root)
        if self._lease_store is None:
            self._lease_store = SessionOwnershipLeaseStore(history_root=history_root)
        if self._inbox_store is None:
            self._inbox_store = SessionInboxStore(history_root=history_root)

    def _require_initialization_binding(self, *, binding: _DeliveryInitialization) -> None:
        """Reject any displaced collaborator before continuing initialization.

        Args:
            binding: Immutable pre-await identity and collaborator capture.

        Raises:
            RuntimeError: The captured initialization no longer owns delivery.
        """
        if not (
            self._runtime_may_start(session=binding.session)
            and binding.session.session_id == binding.session_id
            and self._session_owner_id == binding.owner_id
            and self._lease_store is binding.lease_store
            and self._inbox_store is binding.inbox_store
            and self._workflow_app_service is binding.service
            and self._workflow_renderer is binding.renderer
        ):
            raise RuntimeError("Session delivery unavailable")

    async def _prepare_session_delivery(self, *, binding: _DeliveryInitialization) -> None:
        """Prepare delivery under the retained mount or replacement task.

        Args:
            binding (_DeliveryInitialization): Captured session, lease owner and
                delivery collaborators, revalidated after each awaited boundary.
        """
        if binding.service is None or binding.inbox_store is None:
            return
        await binding.service.reconcile_snapshot()
        self._require_initialization_binding(binding=binding)
        lease = await self._acquire_session_lease(session=binding.session, owner_id=binding.owner_id)
        self._require_initialization_binding(binding=binding)
        if lease.session_id != binding.session_id or lease.owner_id != binding.owner_id:
            raise RuntimeError("Session lease unavailable")
        await binding.inbox_store.ensure_session_inbox(session_id=binding.session_id)
        self._require_initialization_binding(binding=binding)

    def _publish_delivery_timers(self, *, binding: _DeliveryInitialization, timers: list[Timer]) -> None:
        """Publish both timers only while the captured lifetime remains open.

        Args:
            binding (_DeliveryInitialization): Captured lifetime whose preparation
                completed and whose authority is checked before publication.
            timers (list[Timer]): Caller-owned rollback list receiving each created
                timer before its authority check and publication.

        Raises:
            RuntimeError: Shutdown or identity change requires caller-owned rollback.
        """
        self._require_initialization_binding(binding=binding)
        for slot, interval, callback in (
            ("_lease_timer", _SESSION_LEASE_HEARTBEAT_SECONDS, self._renew_session_lease),
            ("_inbox_timer", _SESSION_INBOX_POLL_SECONDS, self._poll_session_inbox),
        ):
            timer = self.set_interval(interval=interval, callback=callback)
            timers.append(timer)
            self._require_initialization_binding(binding=binding)
            if getattr(self, slot) is not None:
                raise RuntimeError("Session delivery unavailable")
            setattr(self, slot, timer)
        self._require_initialization_binding(binding=binding)
        self._delivery_quiescing = False

    def _require_delivery_start(self, *, session: SloAgentSession) -> None:
        """Reject a late setup continuation so its caller rolls back acquired resources.

        Args:
            session (SloAgentSession): Exact owner captured before initialization.

        Raises:
            RuntimeError: The captured owner no longer has startup authority.
        """
        if not self._runtime_may_start(session=session):
            raise RuntimeError("Session delivery unavailable")

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
        self._workflow_observation_close_task = None
        self._workflow_app_service = self._build_workflow_service()
        if self._workflow_progress is None:
            # Unmounted (pre-mount) callers build the service but cannot bind the
            # component; leave the sink unbound so a later mounted bind succeeds.
            return
        try:
            self._workflow_progress_updates_adapter = self._workflow_progress.bind_observation()
            self._workflow_progress_coordinator = self._workflow_coordinator_factory(
                service=self._workflow_app_service,
                sink=self._workflow_progress_updates_adapter,
                schedule=self._schedule_workflow_refresh,
            )
            self._workflow_progress_coordinator.start()
        except BaseException as startup_error:
            # The initiating startup error is the one the caller must see. Join the
            # shared close barrier so the partially acquired owner (service, sink
            # and any started coordinator) is retired. A cleanup failure is
            # reported through the fixed lifecycle diagnostic and chained as the
            # startup error's context; it never replaces the original exception,
            # and the failed close task stays published, permanently blocking
            # reuse because a completed failed task is never retried.
            try:
                await self._close_workflow_observation()
            except BaseException as cleanup_error:
                await self._write_lifecycle_notice(
                    content="Session cleanup incomplete.", classes="tool-result"
                )
                raise startup_error from cleanup_error
            raise
        self._workflow_observation_session_id = self._session.session_id

    async def _ensure_workflow_observation_bound(self) -> None:
        """Rebind observation only when the selected session lost or never had it.

        WHAT: Mount and ``/new`` adoption both converge on runtime delivery;
            rebinding the identical already-bound owner would tear down and
            recreate the one five-second timer, so an intact, unclosed binding
            for the selected session is kept and only a missing, mid-teardown
            or foreign one is rebuilt. A coordinator/service pair whose
            ``close`` already started is always rebuilt, never reused.
        WHO: ``_finish_replacement_runtime`` for the current session.
        WHEN: At every runtime delivery point, mount or replacement.
        """
        if (
            self._workflow_observation_session_id == self._session.session_id
            and self._workflow_progress_coordinator is not None
            and self._workflow_app_service is not None
            and self._workflow_progress_updates_adapter is not None
        ):
            return
        await self._bind_workflow_observation()

    async def _close_workflow_observation(self) -> None:
        """Join the current owner's observation in the fixed teardown order.

        WHAT: ``coordinator.close`` (no read task survives) → ``service.close``
            (caches cleared, later reads empty) → ``adapter.close`` (owned screens
            dismissed, viewports forgotten) → panel reset, which joins any
            shielded row application before clearing. Never cancels execution.
        WHO: ``_bind_workflow_observation`` before adopting a new owner, and
            ``on_unmount``.
        WHEN: Once per owner replacement or app teardown. Genuinely inert when
            unbound: with no coordinator, service or sink left to retire there
            is no owner whose panel rows must be cleared, so the panel is not
            reset again.
        """
        if self._workflow_observation_close_task is None:
            self._workflow_observation_close_task = asyncio.create_task(self._dispose_workflow_observation())
        task = self._workflow_observation_close_task
        cancelled: bool = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError()
        task.result()

    async def _dispose_workflow_observation(self) -> None:
        """Invalidate old references, join owned work, dispose the sink, then reset."""
        self._workflow_observation_session_id = None
        coordinator: Optional[WorkflowProgressCoordinator] = self._workflow_progress_coordinator
        service: Optional[DetachedWorkflowAppService] = self._workflow_app_service
        sink: Optional[WorkflowProgressSink] = self._workflow_progress_updates_adapter
        self._workflow_progress_coordinator = None
        self._workflow_app_service = None
        self._workflow_progress_updates_adapter = None
        if coordinator is None and service is None and sink is None:
            return
        try:
            if coordinator is not None:
                await coordinator.close()
        finally:
            try:
                if service is not None:
                    await service.close()
            finally:
                if sink is not None and self._workflow_progress is not None:
                    await self._workflow_progress.retire_observation(sink=sink)

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
        return self._workflow_service_factory(
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

    async def _acquire_session_lease(
        self, *, session: SloAgentSession, owner_id: str
    ) -> SessionOwnershipLeaseDAO:
        """Acquire a lease for the captured binding, never the later selected owner.

        Args:
            session: Session captured before initialization awaits.
            owner_id: App owner captured before acquisition.

        Returns:
            The store's typed acquisition evidence, validated by the initializer.

        Raises:
            RuntimeError: No lease store was constructed.
        """
        if self._lease_store is None:
            raise RuntimeError("Session lease unavailable")
        return await self._lease_store.acquire(
            session_id=session.session_id,
            owner_id=owner_id,
            ttl_seconds=_SESSION_LEASE_TTL_SECONDS,
        )

    async def _renew_session_lease(self) -> None:
        """Resolve the committed lease binding only after acquiring the swap gate."""
        async with self._prompt_submission_lock:
            if self._lease_store is None or self._delivery_quiescing or not self._replacement_delivery_safe:
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
        if self._inbox_store is None or not self._inbox_delivery_may_start():
            return
        session: SloAgentSession = self._session
        store: SessionInboxStore = self._inbox_store
        message: Optional[SessionInboxMessageDAO] = await store.claim_next(session_id=session.session_id)
        if message is None:
            return
        if self._session is not session or not self._inbox_delivery_may_start():
            await self._notice_retained_inbox_claim()
            return
        if not await self._handle_inbox_message(message=message):
            await self._notice_retained_inbox_claim()
            return
        await store.ack(session_id=session.session_id, message_id=message.message_id)

    async def _notice_retained_inbox_claim(self) -> None:
        """Report deferred admission without private content or disposition changes."""
        await self._write_lifecycle_notice(
            content="Inbox delivery deferred during shutdown; claimed item retained.",
            classes="tool-result",
        )

    def _inbox_delivery_may_start(self) -> bool:
        """Return delivery authority under the caller-owned submission gate."""
        return (
            not self._app_closing
            and not self._session_transitioning
            and not self._delivery_quiescing
            and self._replacement_delivery_safe
            and self._in_flight_task is None
        )

    async def _handle_inbox_message(self, *, message: SessionInboxMessageDAO) -> bool:
        """Route one claimed inbox item according to its delivery mode.

        Workflow lifecycle messages (spec 57.a.5) additionally advance the
        durable workflow handle before their delivery-mode rendering runs, so
        `/workflows` state stays truthful regardless of the delivery mode.

        Args:
            message (SessionInboxMessageDAO): Claimed inbox item.
        """
        if not self._inbox_delivery_may_start():
            return False
        session = self._session
        await self._advance_workflow_handle_state(message=message)
        if self._session is not session or not self._inbox_delivery_may_start():
            return False
        if message.delivery_mode == "ui_notice":
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=self._format_inbox_notice(message=message),
                    classes="tool-result",
                )
            )
            return True
        if message.delivery_mode == "transcript_note":
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=self._format_inbox_note(message=message),
                    classes="tool-result",
                )
            )
            return True
        if message.delivery_mode == "context_note":
            await self._deliver_context_note(message=message)
            return True
        return await self._start_inbox_chat_turn(message=message)

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
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=f"⊛ {message.title or message.kind}: {message.text}",
                    classes="sub-agent-notice",
                )
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

    async def _start_inbox_chat_turn(self, *, message: SessionInboxMessageDAO) -> bool:
        """Submit one claimed inbox item as a real chat turn.

        Called while the caller holds ``_prompt_submission_lock`` (see
        ``_claim_and_handle_idle_inbox_message``), so the machine turn's task
        creation is atomic with local prompt acceptance. A machine turn never
        enters the user queue: it must not call ``_queue_prompt``,
        the component's accepted-prompt recall, or ``_echo_user_line``.

        Args:
            message (SessionInboxMessageDAO): Claimed inbox item.
        """
        if not self._inbox_delivery_may_start():
            return False
        await self._chat_transcript.handle(
            command=TranscriptNoticeDAO(
                content=self._format_inbox_note(message=message),
                classes="tool-result",
            )
        )
        return self._register_prompt_task(text=message.text)

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
                schedule=self._schedule_visualizer_launch,
            )
        return self._workflow_renderer

    def _maybe_launch_workflow_visualizer(self, *, result_text: str) -> None:
        """Translate a ``launch_workflow`` tool result into a visualizer launch.

        Invoked from ``_render_event`` when a ``launch_workflow`` tool result
        streams through. The app service validates the result (seeding the
        live-state cache on success); the renderer schedules its typed effects.
        Malformed or error JSON produces no effects, and any result in a session
        without history is a safe no-op (launch effects are history-gated, as
        before the session list observed every session).

        Args:
            result_text (str): Raw ``launch_workflow`` tool-result text.
        """
        service: Optional[DetachedWorkflowAppService] = self._history_backed_workflow_service()
        if service is None:
            return
        outcome = service.advance_from_launch_result(result_text=result_text)
        self._ensure_workflow_renderer().apply_effects(effects=outcome.effects)

    async def on_event(self, event: events.Event) -> None:
        """Observe original input before Textual forwards it to consuming widgets.

        Escape remains widget-owned dismissal on the first press. Only a second
        prompt-focused Escape within 0.5 seconds dispatches the real /abort path.
        Forwarded/bubbled keys must not be counted twice.
        """
        if isinstance(event, (events.DescendantFocus, events.DescendantBlur, events.AppBlur, events.Paste)):
            self._reset_escape_sequence()
        if isinstance(event, events.Key) and not event.is_forwarded:
            if await self._consume_double_escape(event=event):
                return
        await super().on_event(event)

    def _reset_escape_sequence(self) -> None:
        """Revoke the armed key when input, focus, session or run context changes."""
        self._escape_deadline = 0.0

    async def _consume_double_escape(self, *, event: events.Key) -> bool:
        """Translate only consecutive main-prompt Escapes into existing abort dispatch.

        Args:
            event: Original, not-yet-forwarded terminal key.

        Returns:
            True when the second Escape was consumed by /abort.
        """
        if (
            event.key != "escape"
            or self._input is None
            or not self._input.is_prompt_input_open
            or self.focused is not self._input
        ):
            self._reset_escape_sequence()
            return False
        if self._input.screen is not self.screen:
            self._reset_escape_sequence()
            return False
        now = monotonic()
        if now > self._escape_deadline:
            self._escape_deadline = now + 0.5
            return False
        self._reset_escape_sequence()
        if self._input is not None:
            await self._input.handle(command=HideSuggestionsDAO())
        await self._dispatch_slash_command(line="/abort")
        return True

    def capture_path_prompt(self) -> Optional[PathPromptSnapshotDAO]:
        """Adapt mounted TextArea state and selected cwd to immutable completion input.

        Returns:
            Current prompt authority, or None after closing/before composition.
        """
        if self._input is None or self._app_closing or not self._input.is_prompt_input_open:
            return None
        return PathPromptSnapshotDAO(
            text=self._input.text,
            cursor=self._input.cursor_location,
            workdir=self._session.workdir,
            selection_empty=self._input.selection.is_empty,
            prompt_version=self._input.prompt_version,
        )

    async def publish_path_suggestions(
        self,
        *,
        state: SlashSuggestionStateDAO,
        controller: PathSuggestionController,
        snapshot: PathPromptSnapshotDAO,
    ) -> None:
        """Await path publication only while the captured app/prompt is current."""
        if self._input is not None and snapshot == self.capture_path_prompt():
            await self._input.handle(
                command=PublishSuggestionsDAO(
                    state=state,
                    controller=controller,
                    snapshot=snapshot,
                )
            )

    async def replace_path_span(
        self,
        *,
        insert_text: str,
        start: tuple[int, int],
        end: tuple[int, int],
        cursor_inside_quote: bool,
        controller: PathSuggestionController,
        snapshot: PathPromptSnapshotDAO,
    ) -> None:
        """Await an undo-aware edit without admitting a stale controller callback."""
        if self._input is not None and snapshot == self.capture_path_prompt():
            await self._input.handle(
                command=ReplacePathSpanDAO(
                    insert_text=insert_text,
                    start=start,
                    end=end,
                    cursor_inside_quote=cursor_inside_quote,
                    controller=controller,
                    snapshot=snapshot,
                )
            )

    def on_prompt_input_component_edited(self, event: PromptInputComponent.Edited) -> None:
        """Revoke double-Escape when the prompt buffer or selection changes."""
        event.stop()
        if self._input is not None and self._input.is_prompt_intent_current(event=event):
            self._reset_escape_sequence()

    # ---- Input handling ---------------------------------------------------

    async def on_key(self, event: events.Key) -> None:
        """Redirect a printable keystroke back to the prompt input.

        Textual bubbles every key the focused widget did not consume up to the
        application. When the prompt editor has lost focus (the user scrolled
        the transcript, or focus moved to ``VerticalScroll#transcript-scroll``),
        a printable keystroke means "I want to start typing", so we move focus
        back to ``PromptInputComponent`` and replay the character into its buffer.
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
        if self._input is None or not self._input.is_prompt_input_open:
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
        slash-suggestion refresh via ``PromptInputComponent.on_text_area_changed``.

        Args:
            event (events.Key): The printable key event to replay.
        """
        if self._input is None:
            return
        self._input.focus()
        self._input.insert(text=event.character or "")

    async def on_prompt_input_component_submitted(self, event: PromptInputComponent.Submitted) -> None:
        """Route a submitted input line as a slash command, new turn, or held prompt.

        WHAT: Preserves immediate slash dispatch, then serializes normal-prompt
        acceptance with the active-run completion handoff.
        WHO: ``PromptInputComponent`` posts this event after the operator submits text.
        WHEN: Runs once per Enter submission while the TUI is mounted.

        Args:
            event (PromptInputComponent.Submitted): Custom input submission message.
        """
        if self._input is not None and not self._input.is_prompt_intent_current(event=event):
            return
        text: str = (event.text or "").strip()
        if self._input is not None:
            await self._input.handle(command=ClearSubmissionDAO())
            if not self._input.is_prompt_intent_current(event=event):
                return
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
        WHO: ``on_prompt_input_component_submitted`` calls it for non-slash non-empty input.
        WHEN: Runs at operator submission time; it does not hold the lock during a run.

        Args:
            text (str): Normalized ordinary prompt text.
        """
        if self._app_closing or self._session_transitioning:
            return
        if self._session.preparation_status != "ready":
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(
                        content="Model preparation required; use /auth or /model refresh.",
                        classes="tool-result",
                    )
                )
            return
        async with self._prompt_submission_lock:
            if self._app_closing or self._session_transitioning:
                return
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
        if self._app_closing or self._session_transitioning:
            return
        if self._input is not None:
            await self._input.handle(command=RecordAcceptedPromptDAO(text=text))
        await self._chat_transcript.handle(command=EchoUserDAO(text=text))
        self._register_prompt_task(text=text)

    def _register_prompt_task(self, *, text: str) -> bool:
        """Commit prompt admission under the caller-owned submission lock.

        No rendering, callback or suspension may separate the closing check from
        task registration. Already registered runs retain their execution policy.

        Args:
            text (str): Accepted prompt text, never logged by this gate.

        Returns:
            bool: Whether the app registered the task before shutdown.
        """
        if self._app_closing or self._session_transitioning:
            return False
        self._in_flight_task = asyncio.create_task(coro=self._run_prompt(text=text))
        return True

    async def _queue_prompt(self, *, text: str) -> None:
        """Store the newest held text and mount or update its one visible block.

        WHAT: Applies one-deep latest-wins policy without creating a user turn.
        WHO: ``_submit_or_queue_prompt`` calls it under the submission gate.
        WHEN: An ordinary prompt arrives while an app-owned run task is active.

        Args:
            text (str): Newest ordinary prompt text.
        """
        if self._app_closing or self._session_transitioning:
            return
        self._queued_prompt_text = text
        if self._queued_prompt_block is not None:
            self._queued_prompt_block.replace_text(text=text)
            return
        await self._mount_queued_prompt_block(text=text)

    async def _mount_queued_prompt_block(self, *, text: str) -> None:
        """Mount the visible held-prompt block directly above the prompt input.

        WHAT: Anchors the block as a ``#chat-shell`` child immediately before
        ``PromptInputComponent`` — outside the scroll region, so it stays visible while
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
        if self._app_closing:
            return
        await self._announce_queued_prompt_survival()
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(content="(aborting…)", classes="tool-result")
            )

    async def _announce_queued_prompt_survival(self) -> None:
        """Explain that an abort retains the held prompt when one exists.

        WHAT: Writes one operator-facing notice without changing queue/task state.
        WHO: ``action_interrupt`` and ``_dispatch_slash_command`` call it after an
        abort has been requested.
        WHEN: Only while a user-held prompt remains queued behind the aborted run.
        """
        if self._queued_prompt_text is None:
            return
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=(
                        "(queued prompt held — it will run next; resubmit to replace it, "
                        "/clear to drop it)"
                    ),
                    classes="tool-result",
                )
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
                await self._chat_transcript.handle(command=MountTreeOutputDAO(widget=viewer))
        elif tree_format == TreeExportFormat.MARKDOWN.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode

            if isinstance(tree, SessionTreeNode):
                md = TreeMarkdownExporter.export(tree=tree)
                await self._chat_transcript.handle(command=MountTreeOutputDAO(widget=LiteralTextStatic(md)))
        elif tree_format == TreeExportFormat.HTML.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode

            if isinstance(tree, SessionTreeNode):
                path = TreeHtmlExporter.export(
                    tree=tree,
                    session_name=self._session.session_name or "unnamed",
                )
                await self._chat_transcript.handle(
                    command=MountTreeOutputDAO(widget=LiteralTextStatic(f"HTML tree written to: {path}"))
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
            await self._chat_transcript.handle(command=ClearTranscriptDAO())

    async def action_copy_visible_text(self) -> None:
        """Copy the focused block text, selected prompt text, or visible transcript.

        Resolution priority:
        1. Text from the focused transcript block via ``get_copyable_text()``.
        2. Selected text from the ``PromptInputComponent`` editor.
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
        if self._chat_transcript is not None and self._chat_transcript.is_attached:
            await self._chat_transcript.handle(command=ScrollTranscriptBottomDAO())

    async def action_toggle_expandable_details(self) -> None:
        """Toggle global expand-all mode for every transcript block.

        Cycles natural-default -> expand-all -> collapse-all -> expand-all ...
        The first press always expands; subsequent presses alternate. The new
        state is pushed onto every existing block and inherited by new ones.
        """
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(command=ToggleTranscriptDetailsDAO())
        self.refresh_bindings()

    # ---- Private helpers --------------------------------------------------

    async def on_idle(self) -> None:
        """Adopt a published picker status revision without waiting for a keystroke."""
        if self._input is not None and self._input.is_prompt_input_open:
            await self._input.handle(command=RefreshPublishedSuggestionsDAO())

    async def _dispatch_slash_command(self, *, line: str) -> None:
        """Hand a slash command to ``SlashRouter`` and render the result.

        Long-running commands (the registry's ``shows_activity`` flag) mount the
        fixed activity spinner for the duration of the dispatch so the operator
        sees work in progress instead of a blank screen.

        Args:
            line (str): The full input line including the leading slash.
        """
        if self._input is not None:
            await self._input.handle(command=HideSuggestionsDAO())
        self._reset_escape_sequence()
        admission: SlashCommandAdmissionDAO = SlashRouter.admit(
            line=line, preparation_status=self._session.preparation_status
        )
        if admission.action == "prepare":
            self._start_session_preparation()
            return
        if admission.action == "reject":
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content="Model preparation required.", classes="tool-result")
                )
            return
        mounted_activity: bool = await self._mount_slash_activity(line=line)
        session = self._session
        previous_model = session.active_model_name
        try:
            result = await SlashRouter.dispatch(
                line=line, session=session, workflow_resume_launcher=self._workflow_resume_launcher
            )
            if admission.refresh_model_context:
                ModelSuggestionProjection.refresh_authentication()
            if self._runtime_may_start(session=session) and self._input is not None:
                if session.active_model_name != previous_model:
                    await self._input.handle(
                        command=RecordModelSelectionDAO(model_name=session.active_model_name)
                    )
                    await self._input.handle(
                        command=SetModelContextDAO(active_model_name=session.active_model_name)
                    )
                elif admission.refresh_model_context:
                    await self._input.handle(
                        command=SetModelContextDAO(active_model_name=session.active_model_name)
                    )
        finally:
            if mounted_activity:
                await self._unmount_spinner()
        if isinstance(result.code_path, str):
            self._schedule_editor_launch(argument=result.code_path)
            return
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
            await self._announce_queued_prompt_survival()
        if result.steer_pending_message is not None:
            assert self._chat_transcript is not None
            await self._chat_transcript.handle(
                command=ShowPendingSteeringDAO(message=result.steer_pending_message)
            )
        if result.render_tree is not None:
            await self._mount_tree_viewer(tree=result.render_tree, tree_format=result.tree_format)
        git_diff_path: Optional[str] = result.git_diff_path if isinstance(result.git_diff_path, str) else None
        if git_diff_path is not None:
            await self._open_git_diff(path=git_diff_path)
            return
        tui_visibility: Optional[WorkflowListVisibilityRequestDAO] = (
            result.tui_visibility
            if isinstance(result.tui_visibility, WorkflowListVisibilityRequestDAO)
            else None
        )
        if tui_visibility is not None:
            await self._apply_workflow_list_visibility(request=tui_visibility)
            return
        if result.rendered is not None:
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content=result.rendered, classes="tool-result")
                )
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
            await self._toggle_theme()
        if result.open_auth_modal:
            self._push_auth_modal()
        if result.should_exit:
            self.exit()

    def _schedule_editor_launch(self, *, argument: str) -> None:
        """Capture the session before background validation without blocking prompt input.

        Args:
            argument: Raw single-path slash intent.
        """
        if self._app_closing or self._session_transitioning:
            return
        worker: Worker[None] = self.run_worker(
            work=partial(self._run_editor_launch, argument=argument, session=self._session),
            group="editor-launch",
            exit_on_error=False,
        )
        self._editor_launch_tasks[worker] = asyncio.create_task(
            coro=self._wait_for_editor_worker(worker=worker)
        )

    async def _run_editor_launch(self, *, argument: str, session: SloAgentSession) -> None:
        """Render submission evidence only while its captured owner remains selected.

        Args:
            argument: Raw operator token for off-thread validation.
            session: Selected session captured synchronously at registration.
        """
        notice = await self._editor_launcher.invoke(argument=argument, session=session)
        if not self._app_closing and not self._session_transitioning and session is self._session:
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content=notice, classes="tool-result")
                )

    async def _drain_editor_launches(self) -> None:
        """Cancel/join request mechanics, never close user-owned editor panes."""
        tasks = tuple(self._editor_launch_tasks.items())
        for worker, _wait in tasks:
            worker.cancel()
        for _worker, wait in tasks:
            await HerdrTaskJoin.wait(task=wait)
            wait.result()

    async def _wait_for_editor_worker(self, *, worker: Worker[None]) -> None:
        """Retire a launch only after actual completion, including pre-entry cancellation.

        Started and retained at admission, this wait does not depend on Textual's
        state messages. In-flight cancellation keeps the handle until validation
        and terminal request cleanup have joined their work. Unexpected failures
        are accounted with a fixed diagnostic, never exception details or a late
        transcript notice, before the retained wait releases ownership.

        Args:
            worker: App-owned editor worker whose request mechanics must finish.
        """
        try:
            await worker.wait()
        except WorkerCancelled:
            pass
        except WorkerFailed:
            log_error(msg="editor_launch_worker_failed", stack_trace=False)
        finally:
            self._editor_launch_tasks.pop(worker, None)

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
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content=exception.operator_message, classes="tool-result")
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
            if self._app_closing or self._session_transitioning:
                return
            if self._in_flight_task is not None or self._session.is_running:
                if self._chat_transcript is not None:
                    await self._chat_transcript.handle(
                        command=TranscriptNoticeDAO(
                            content="cannot start a new session while a prompt is in flight; run /abort first",
                            classes="tool-result",
                        )
                    )
                return
            replacement = await self._replace_idle_session_and_clear_queue(requested_name=requested_name)
        if replacement is None:
            return
        cancelled = await HerdrTaskJoin.wait(task=replacement)
        replacement.result()
        if self._session_replacement_task is replacement:
            self._session_replacement_task = None
        if cancelled:
            raise asyncio.CancelledError

    async def _replace_idle_session_and_clear_queue(
        self, *, requested_name: Optional[str]
    ) -> Optional[asyncio.Task[None]]:
        """Prepare and register a retained replacement while holding the gate.

        WHAT: Prepares the candidate before touching the selected session, then
        revokes the captured predecessor and returns the owned commit task.
        Preparation failure preserves the old queue and delivery binding.
        WHO: ``_start_new_session`` calls it only while holding
        ``_prompt_submission_lock`` after establishing the app is idle.
        WHEN: The operator requests `/new` while no run is active.

        Args:
            requested_name (Optional[str]): Optional initial human-readable session name.

        Returns:
            Optional[asyncio.Task[None]]: Commit to join outside the gate, or no replacement.
        """
        if self._app_closing:
            return None
        candidate = await self._prepare_replacement_session(requested_name=requested_name)
        if candidate is None:
            return None
        if self._app_closing:
            await self._discard_replacement_session(candidate=candidate)
            return None
        old_session = self._session
        self._session_transitioning = True
        self._delivery_quiescing = True
        old_session.begin_external_reporting_close()
        self._session_replacement_task = asyncio.create_task(
            coro=self._commit_replacement_session(old_session=old_session, candidate=candidate)
        )
        return self._session_replacement_task

    async def _commit_replacement_session(
        self, *, old_session: SloAgentSession, candidate: SloAgentSession
    ) -> None:
        """Drain viewers outside their finalizer gate, then serialize adoption.

        Args:
            old_session: Revoked predecessor captured at commit registration.
            candidate: Fully prepared inactive successor.
        """
        try:
            await self._drain_editor_launches()
            await self._cancel_visualizer_launches()
        except Exception:
            self._replacement_delivery_safe = False
            await self._write_lifecycle_notice(content="Viewer cleanup incomplete.", classes="tool-result")
        async with self._prompt_submission_lock:
            await self._finish_replacement_commit(old_session=old_session, candidate=candidate)
            self._session_transitioning = False

    async def _finish_replacement_commit(
        self, *, old_session: SloAgentSession, candidate: SloAgentSession
    ) -> None:
        """Close and adopt captured owners under the retained transaction's gate."""
        try:
            await self._cancel_session_preparation()
        except Exception:
            self._replacement_delivery_safe = False
        try:
            await old_session.close_agent_resources()
        except Exception:
            await self._discard_replacement_session(candidate=candidate)
            self._delivery_quiescing = False
            await self._write_lifecycle_notice(
                content="Current session resources could not close; retry resource cleanup.",
                classes="tool-result",
            )
            return
        await self._transfer_replacement_delivery(old_session=old_session)
        try:
            outcome = await old_session.close_external_reporting()
        except Exception:
            outcome = HerdrReporterCloseOutcomeDAO(replacement="uncertain", resources="retained")
        await self._close_workflow_observation()
        subscription_retired = self._adopt_replacement_session(
            old_session=old_session, candidate=candidate, outcome=outcome
        )
        if not subscription_retired:
            await self._write_lifecycle_notice(
                content="Previous subscription cleanup incomplete.", classes="tool-result"
            )
        await self._finish_replacement_ui()

    async def _transfer_replacement_delivery(self, *, old_session: SloAgentSession) -> None:
        """Release the captured old binding before establishing any successor lease.

        WHAT: Stops delivery timers and releases the old inbox lease. The old
            owner's workflow observation stays bound until predecessor retirement;
            ``_finish_replacement_commit`` closes it before adoption through the canonical
            coordinator → service → sink → panel teardown so no rows, caches
            or timers cross sessions.
        WHO: ``_finish_replacement_commit`` before reporter close/adoption.

        Args:
            old_session (SloAgentSession): Predecessor captured before adoption.
        """
        self._delivery_quiescing = True
        self._stop_delivery_timers()
        await self._release_replaced_session_lease(session=old_session)
        self._workflow_renderer = None

    def _stop_delivery_timers(self, *, timers: Optional[tuple[Timer, ...]] = None) -> None:
        """Stop captured handles; omitted input selects normal teardown's current pair.

        Args:
            timers: Exact init-owned handles, or None for selected-owner teardown.
        """
        selected = (self._lease_timer, self._inbox_timer) if timers is None else timers
        retained = self._failed_delivery_timers
        timers_to_stop = tuple(dict.fromkeys((*retained, *selected) if timers is None else selected))
        failed: list[Timer] = [timer for timer in retained if timer not in timers_to_stop]
        for timer in timers_to_stop:
            if timer is None:
                continue
            try:
                timer.stop()
            except Exception:
                self._replacement_delivery_safe = False
                failed.append(timer)
            else:
                for slot in ("_lease_timer", "_inbox_timer"):
                    if getattr(self, slot) is timer:
                        setattr(self, slot, None)
        # Failed startup permanently disables subsequent timer creation, bounding
        # retained initialization resources to its two original handles.
        self._failed_delivery_timers = tuple(failed)

    async def _release_replaced_session_lease(
        self,
        *,
        session: SloAgentSession,
    ) -> None:
        """Capture current delivery ownership for replacement or global teardown."""
        await self._release_captured_session_lease(
            lease_store=self._lease_store, session_id=session.session_id, owner_id=self._session_owner_id
        )

    async def _release_captured_session_lease(
        self,
        *,
        lease_store: Optional[SessionOwnershipLeaseStore],
        session_id: str,
        owner_id: str,
    ) -> None:
        """Join release of exactly the supplied capture; absent storage is a no-op.

        Args:
            lease_store: Captured store, never resolved from current app state.
            session_id: Immutable ID belonging to the captured initialization.
            owner_id: Captured lease owner.
        """
        if lease_store is None:
            return
        release_task = asyncio.create_task(coro=lease_store.release(session_id=session_id, owner_id=owner_id))
        cancellation: Optional[asyncio.CancelledError] = None
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError as exc:
            cancellation = exc
            await HerdrTaskJoin.wait(task=release_task)
        except Exception:
            pass
        try:
            self._replacement_delivery_safe &= release_task.result()
        except Exception:
            self._replacement_delivery_safe = False
            await self._write_lifecycle_notice(
                content="Previous inbox lease could not be released; new inbox disabled.",
                classes="tool-result",
            )
        if cancellation is not None:
            raise cancellation

    def _adopt_replacement_session(
        self,
        *,
        old_session: SloAgentSession,
        candidate: SloAgentSession,
        outcome: HerdrReporterCloseOutcomeDAO,
    ) -> bool:
        """Publish the successor subscription without yielding after irreversible close.

        Args:
            old_session (SloAgentSession): Closed predecessor.
            candidate (SloAgentSession): Prepared successor.
            outcome (HerdrReporterCloseOutcomeDAO): Independent remote/local evidence.
        """
        if outcome.resources == "retained":
            if self._retired_herdr_session is not None and self._retired_herdr_session is not old_session:
                raise RuntimeError("Multiple quarantined integration owners")
            self._retired_herdr_session = old_session
        self._herdr_successor_suppressed |= outcome.replacement == "uncertain"
        if self._herdr_successor_suppressed or self._app_closing:
            candidate.suppress_external_reporting()
        subscription_retired = True
        try:
            old_session.unsubscribe(handler=self._render_event)
        except Exception:
            subscription_retired = False
        self._reset_escape_sequence()
        self._path_suggestions.invalidate()
        self._session = candidate
        candidate.subscribe(handler=self._render_event)
        return subscription_retired

    async def _finish_replacement_ui(self) -> None:
        """Refresh only the adopted session; never reinstall its closed predecessor."""
        session = self._session
        if not self._runtime_may_start(session=session):
            return
        try:
            await self._refresh_replacement_ui()
        except Exception:
            await self._write_lifecycle_notice(
                content="New session selected; some UI state could not refresh.", classes="tool-result"
            )
        if self._runtime_may_start(session=session):
            await self._finish_replacement_runtime()

    async def _finish_replacement_runtime(self) -> None:
        """Activate current-session delivery/reporting before refreshing presentation."""
        session = self._session
        if not self._runtime_may_start(session=session):
            return
        await self._ensure_workflow_observation_bound()
        if not self._runtime_may_start(session=session):
            return
        try:
            await self._initialize_session_delivery()
        except Exception:
            await self._rollback_session_delivery(session=session, owner_id=self._session_owner_id)
        if not self._runtime_may_start(session=session):
            return
        try:
            await session.start_external_reporting(interactive=True)
        except Exception:
            await self._write_lifecycle_notice(
                content="External reporting unavailable.", classes="tool-result"
            )
        if not self._runtime_may_start(session=session):
            return
        try:
            await session.refresh_context_window_snapshot()
            if not self._runtime_may_start(session=session):
                return
            self._refresh_title_bar()
            self._refresh_usage_status_bar()
        except Exception:
            await self._write_lifecycle_notice(
                content="Session selected; usage refresh unavailable.", classes="tool-result"
            )
        if self._runtime_may_start(session=session) and session.preparation_status != "ready":
            self._start_session_preparation()

    async def _refresh_replacement_ui(self) -> None:
        """Clear the adopted transcript and input independently of runtime refresh."""
        session = self._session
        await self._clear_transcript_and_prompt_queue()
        await self._chat_transcript.handle(
            command=BindHistoryDAO(history_reader=session.hydrate_transcript_entries)
        )
        if not self._runtime_may_start(session=session):
            return
        if self._input is not None:
            await self._input.reset()
            await self._input.handle(command=SetModelContextDAO(active_model_name=session.active_model_name))
        await self._maybe_render_startup_notice()

    async def _prepare_replacement_session(
        self, *, requested_name: Optional[str]
    ) -> Optional[SloAgentSession]:
        """Build an inactive candidate without mutating the selected session.

        Args:
            requested_name (Optional[str]): Name persisted only on the candidate.

        Returns:
            Optional[SloAgentSession]: Prepared candidate, or None on ordinary failure.

        Raises:
            asyncio.CancelledError: After candidate-owned cleanup has joined.
        """
        candidate: Optional[SloAgentSession] = None
        try:
            config = self._build_replacement_session_config(old_session=self._session)
            # An injected factory owns its construction; the default keeps the bridge transport.
            candidate = (
                self._session_factory(config=config, allow_pending_preparation=True)
                if self._session_factory is not None
                else SloAgentSession.build(
                    config=config,
                    allow_pending_preparation=True,
                    bridge_adapter_class=self._session.bridge_adapter_class,
                )
            )
            if candidate.history_root != self._session.history_root:
                raise ValueError("Replacement history root must remain unchanged")
            self._attach_pool_to_session(session=candidate)
            if requested_name is not None:
                await candidate.rename_session(session_name=requested_name)
            return candidate
        except asyncio.CancelledError:
            await self._discard_replacement_session(candidate=candidate)
            raise
        except Exception:
            await self._discard_replacement_session(candidate=candidate)
            await self._write_lifecycle_notice(
                content="New session could not be prepared; current session retained.", classes="tool-result"
            )
            return None

    async def _discard_replacement_session(self, *, candidate: Optional[SloAgentSession]) -> None:
        """Join failed preparation's resources before returning to the mounted owner.

        Args:
            candidate (Optional[SloAgentSession]): Inactive partial build, if available.

        Raises:
            asyncio.CancelledError: After retained candidate disposal finishes.
        """
        if candidate is None:
            return
        self._candidate_cleanup_task = asyncio.create_task(coro=candidate.dispose_unmounted_session())
        cancelled = await HerdrTaskJoin.wait(task=self._candidate_cleanup_task)
        self._candidate_cleanup_task.result()
        self._candidate_cleanup_task = None
        if cancelled:
            raise asyncio.CancelledError

    async def _write_lifecycle_notice(self, *, content: str, classes: str) -> None:
        """Render fixed lifecycle copy without making cleanup depend on the sink.

        Args:
            content (str): Fixed lifecycle diagnostic, never exception text.
            classes (str): Existing transcript presentation class.
        """
        try:
            await self._chat_transcript.handle(command=TranscriptNoticeDAO(content=content, classes=classes))
        except Exception:
            return

    async def _rename_current_session(self, *, session_name: str) -> None:
        """Rename the active session and refresh visible title state.

        Args:
            session_name (str): Requested human-readable session name.
        """
        try:
            await self._session.rename_session(session_name=session_name)
        except Exception as exc:  # noqa: BLE001 - inline operator feedback required
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content=f"(rename failed: {exc})", classes="tool-result")
                )
            return
        self._refresh_title_bar()
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=f"session renamed to {session_name}", classes="tool-result"
                )
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
        await self._write_sub_agent_notice(event=event)
        if event.kind == "sub_agent_spawned":
            self._maybe_launch_visualizer()
        if event.kind not in _SUB_AGENT_LIST_REFRESH_KINDS:
            return
        self._request_workflow_refresh()

    async def _write_sub_agent_notice(self, *, event: AgentStreamEventDAO) -> None:
        """Write the ``⊇ task: status`` transcript notice for a noticed lifecycle kind.

        Args:
            event (AgentStreamEventDAO): Child event; other kinds write nothing.
        """
        status: Optional[str] = _SUB_AGENT_NOTICE_STATUSES.get(event.kind)
        if status is None or self._chat_transcript is None:
            return
        if self._chat_transcript is not None:
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=f"⊇ {event.task_id or ''}: {status}", classes="sub-agent-notice"
                )
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

    async def on_session_progress_screen_minimized(self, message: SessionProgressScreen.Minimized) -> None:
        """Close progress observation on Escape/Minimize without touching execution.

        Args:
            message (SessionProgressScreen.Minimized): Minimize intent.
        """
        if (
            self._workflow_progress_coordinator is None
            or not message.screen.is_live
            or self.screen is not message.screen
        ):
            return
        await self._workflow_progress_coordinator.minimize()

    async def on_session_progress_screen_abort_requested(
        self, message: SessionProgressScreen.AbortRequested
    ) -> None:
        """Ask the sink to confirm the exact target the progress view displayed.

        Args:
            message (SessionProgressScreen.AbortRequested): Captured confirmation target.
        """
        if self._workflow_progress is None or not message.screen.is_live or self.screen is not message.screen:
            return
        await self._workflow_progress.handle(command=ConfirmAbortDAO(target=message.target))

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

    async def _apply_workflow_list_visibility(self, *, request: WorkflowListVisibilityRequestDAO) -> None:
        """Commit and paint local visibility before acknowledging the command.

        Args:
            request: Router-validated display operation, never execution control.
        """
        async with self._workflow_visibility_lock:
            service = self._workflow_app_service
            coordinator = self._workflow_progress_coordinator
            if service is None or coordinator is None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(
                        content="Workflow list unavailable in this session.", classes="tool-result"
                    )
                )
                return
            outcome = service.apply_list_visibility(request=request)
            try:
                painted = await coordinator.apply_local_snapshot(snapshot=outcome.snapshot)
            except Exception:
                painted = False
            if (
                service is not self._workflow_app_service
                or coordinator is not self._workflow_progress_coordinator
            ):
                return
            content = (
                "Workflow visibility saved; display refresh pending."
                if not painted and outcome.outcome == "changed"
                else outcome.rendered
            )
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(content=content, classes="tool-result")
            )
            coordinator.request_refresh()

    def may_open_progress(self, *, current: Optional[SessionProgressScreen]) -> bool:
        """Allow a progress view to open unless an unrelated modal is active.

        Args:
            current (Optional[SessionProgressScreen]): The adapter's already open
                view; it never blocks its own replacement.

        Returns:
            bool: False while another modal covers the base screen.
        """
        return not (len(self.screen_stack) > 1 and self.screen is not current)

    def is_active_progress(self, *, screen: SessionProgressScreen) -> bool:
        """Return whether the owned progress view is the active screen.

        Args:
            screen (SessionProgressScreen): View to compare with the stack top.
        """
        return self.screen is screen

    def present_progress(
        self, *, screen: SessionProgressScreen, on_closed: Callable[[None], None]
    ) -> Awaitable[None]:
        """Push one owned progress view with its dismissal callback.

        Args:
            screen (SessionProgressScreen): Fresh view to present.
            on_closed (Callable[[None], None]): Callback after the view leaves the stack.
        """
        return self.push_screen(screen=screen, callback=on_closed)

    def present_confirmation(
        self, *, screen: AbortConfirmationScreen, on_closed: Callable[[Optional[bool]], None]
    ) -> None:
        """Push one owned abort confirmation with its result callback.

        Args:
            screen (AbortConfirmationScreen): Confirmation to present.
            on_closed (Callable[[Optional[bool]], None]): Result callback.
        """
        self.push_screen(screen=screen, callback=on_closed)

    def notify_progress(self, *, message: str, warning: bool = False) -> None:
        """Show one fixed workflow-progress notice.

        Args:
            message (str): Literal notice text.
            warning (bool, optional): Whether to use warning severity. Defaults to False.
        """
        if warning:
            self.notify(message=message, markup=False, severity="warning")
            return
        self.notify(message=message, markup=False)

    def return_prompt_focus(self) -> None:
        """Focus the prompt editor on the base screen only, never behind a modal."""
        if len(self.screen_stack) > 1 or self._input is None:
            return
        self._input.focus()

    def progress_closed(self) -> None:
        """Return focus to the visible session list, or to the prompt when empty.

        WHO: The bound adapter once its progress view has left the stack.
        WHEN: Only when no other modal remains above the base screen.
        """
        if len(self.screen_stack) > 1 or self._workflow_progress is None or self._input is None:
            return
        if self._workflow_progress.is_session_list_visible():
            self._workflow_progress.focus_sessions()
            return
        self._input.focus()

    def progress_incarnation_changed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Close the old execution view when the sink observes same-key reuse.

        WHAT: Invalidate the coordinator first; the calling adapter then releases
            its view without reentering its delivery lock. Runs
            synchronously so invalidation precedes any further paint.
        WHO: The bound adapter's typed list delivery, while reconciling the
            selected identity against fresh rows.
        WHEN: When the open view's key now names a different execution or dispatch.

        Args:
            key (WorkflowSessionKeyDAO): Selected key whose incarnation changed.
        """
        if self._workflow_progress_coordinator is not None:
            self._workflow_progress_coordinator.invalidate_selection()
        self.notify(message=f"Session execution changed; select {key.session_id} again.", markup=False)

    def child_abort_confirmed(self, *, target: ChildAbortTargetDAO) -> None:
        """Hand an explicitly confirmed target to the service and refresh at once.

        WHAT: The service owns the submission (minimizing never withdraws it);
            the immediate refresh paints the pending notice and disabled Abort.
        WHO: The bound adapter from its confirmation callback, only on True.
        WHEN: Once per explicit Abort child choice.

        Args:
            target (ChildAbortTargetDAO): Identity captured when confirmation opened.
        """
        if self._workflow_app_service is None:
            return
        self._workflow_app_service.begin_child_abort(target=target)
        self._request_workflow_refresh()

    def _schedule_visualizer_launch(self, *, parent_session_id: str) -> None:
        """Capture the selected owner and register one pending request per parent.

        Args:
            parent_session_id: Requested workflow parent, not a later session lookup.
        """
        from src.tui.visualizer_launcher import VisualizerLauncher

        if self._app_closing or self._session_transitioning:
            return
        if self._delivery_quiescing and self._session_supports_inbox_delivery():
            return
        if not VisualizerLauncher._auto_visualize_enabled():
            return
        if parent_session_id in self._visualizer_launch_tasks:
            return
        task = asyncio.create_task(
            coro=self._run_visualizer_launch(parent_session_id=parent_session_id, session=self._session)
        )
        self._visualizer_launch_tasks[parent_session_id] = task
        task.add_done_callback(partial(self._on_visualizer_launch_done, parent_session_id=parent_session_id))

    async def _cancel_visualizer_launches(self) -> None:
        """Drain registered workers before reporter close, outside the submission gate.

        Scheduling must already be revoked by the owning lifetime transition.
        Each worker receives one cancellation; repeated caller cancellation cannot
        abandon its platform thread or finalizer. Identity cleanup preserves any
        newer entry rather than blindly clearing the registry.
        """
        pending = tuple(self._visualizer_launch_tasks.items())
        for _, task in pending:
            task.cancel()
        failure: Optional[Exception] = None
        for parent_session_id, task in pending:
            try:
                await HerdrTaskJoin.wait(task=task)
                self._on_visualizer_launch_done(task, parent_session_id=parent_session_id)
            except Exception as exc:
                failure = failure or exc
        if failure is not None:
            raise failure

    def _on_visualizer_launch_done(self, task: asyncio.Task[None], *, parent_session_id: str) -> None:
        """Retrieve completion and remove only the identical registered task.

        Args:
            task: Positional asyncio completion callback input.
            parent_session_id: Captured request key.
        """
        if not task.cancelled():
            task.exception()
        if self._visualizer_launch_tasks.get(parent_session_id) is task:
            del self._visualizer_launch_tasks[parent_session_id]

    async def _run_visualizer_launch(self, *, parent_session_id: str, session: SloAgentSession) -> None:
        """Delegate a still-current captured request to the existing async gateway.

        Args:
            parent_session_id: Requested workflow parent.
            session: Owner captured at synchronous registration.
        """
        from src.tui.visualizer_launcher import VisualizerLauncher

        if (
            self._app_closing
            or self._session_transitioning
            or (self._delivery_quiescing and self._session_supports_inbox_delivery())
            or self._session is not session
        ):
            return
        try:
            if self._visualizer_launcher is not None:
                launched = self._visualizer_launcher(parent_session_id=parent_session_id)
                outcome = VisualizerLaunchOutcomeDAO(status="opened" if launched else "failed")
            else:
                outcome = await VisualizerLauncher.launch_async(
                    parent_session_id=parent_session_id, session=session
                )
        except Exception:
            outcome = VisualizerLaunchOutcomeDAO(status="failed")
        if (
            self._app_closing
            or self._session_transitioning
            or (self._delivery_quiescing and self._session_supports_inbox_delivery())
            or self._session is not session
        ):
            return
        try:
            await self._ensure_workflow_renderer().write_launch_outcome(
                parent_session_id=parent_session_id, outcome=outcome
            )
        except Exception:
            pass  # Optional notice failure must not escape into the workflow.
        finally:
            if outcome.status == "failed":
                self._visualizer_launched_for_run = False

    def _maybe_launch_visualizer(self) -> None:
        """Schedule the attached parent's viewer without blocking event routing."""
        if self._visualizer_launched_for_run:
            return
        self._visualizer_launched_for_run = True
        self._schedule_visualizer_launch(parent_session_id=self._session.session_id)

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
            model_pool_dao=(
                old_session.model_pool_dao.model_copy(deep=True)
                if old_session.model_pool_dao is not None
                else None
            ),
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
        await self._chat_transcript.handle(command=BeginTranscriptRunDAO())
        self._reset_escape_sequence()
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
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(content="(aborted)", classes="assistant-aborted")
                )
        except ValueError as exc:
            if self._chat_transcript is not None:
                await self._chat_transcript.handle(
                    command=TranscriptNoticeDAO(
                        content=f"(configuration error: {exc})",
                        classes="tool-result",
                    )
                )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the user
            if not saw_failed_event:
                await self._render_run_error(exc=exc)
        finally:
            self._reset_escape_sequence()
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
        if self._app_closing or self._session_transitioning:
            self._in_flight_task = None
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

    async def _render_run_error(self, *, exc: BaseException) -> None:
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
            await self._chat_transcript.handle(
                command=TranscriptNoticeDAO(
                    content=f"(error: {message})",
                    classes="assistant-aborted",
                )
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
        """Deliver presentation while retaining app-owned routing and usage lifetime.

        Args:
            event: Normalized event from the subscribed session.
        """
        presentation: SessionEventPresentationDAO = SessionEventPresentation.build(event=event)
        if presentation.update_spinner and self._spinner is not None:
            self._spinner.set_override_status(text=presentation.spinner_status)
        if presentation.notice is not None and self._chat_transcript is not None:
            await self._chat_transcript.handle(command=presentation.notice)
        if presentation.notice_only:
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            return
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
            await self._chat_transcript.handle(command=PresentAgentEventDAO(event=event))
        if event.kind == "steering_applied":
            return
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

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
        does not implement the protocol (e.g. ``PromptInputComponent``,
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
