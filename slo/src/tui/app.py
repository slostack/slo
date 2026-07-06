"""Textual app for the ``slo`` default subcommand (sub-spec 02.a.3)."""

from __future__ import annotations

import asyncio
from typing import Optional, cast

from rich.markdown import Markdown
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Header, Static, TextArea

from config.ai_model_config import default_model_for_provider
from config.cfg import cfg
from src.agents.slo_agent.orchestrator.dao import SubAgentStatus
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.reasoning_capabilities import resolve_reasoning_config
from src.auth.credential_dao import CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.tui.authentication import AuthenticationScreen
from src.tui.prompt_history import PromptHistoryNavigator
from src.tui.slash_router import SlashCommandResultDAO, SlashRouter
from src.tui.slash_suggestion_engine import (
    SlashSuggestionEngine,
    SlashSuggestionStateDAO,
)
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.thinking_spinner import ThinkingSpinner
from src.tui.transcript_projector import TranscriptProjector
from src.tui.tree_export_format import TreeExportFormat
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu
from src.tui.widgets.steering_pending_block import SteeringPendingBlock
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.tree_html_exporter import TreeHtmlExporter
from src.tui.widgets.tree_markdown_exporter import TreeMarkdownExporter
from src.tui.widgets.tree_viewer import SessionTreeViewer
from src.tui.widgets.usage_status_bar import UsageStatusBar
from src.tui.widgets.user_message_block import UserMessageBlock

__all__ = ["SloTUI", "PromptInput"]


_ABORT_HARD_CANCEL_GRACE_SECONDS: float = 2.0
"""Grace period after a cooperative abort before the in-flight task is hard-cancelled.

The cooperative abort flag is only observed between agent graph stream items,
so a run blocked inside a single hung tool call would otherwise never abort.
After this grace, the TUI cancels the asyncio task outright, raising
``CancelledError`` into the blocked ``await`` and tearing the run down."""


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


class SloTUI(App):
    """Textual application wrapping a single ``SloAgentSession``."""

    CSS_PATH = "app.tcss"

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
    ]

    DEFAULT_THEME: str = SLO_DARK_THEME.name  # slo boots into the slo-dark (near-black/green) palette
    """Textual theme applied on construction.

    Defaults to the slo-dark theme (near-black/green) — the visual
    signature that distinguishes slo from poe-harness. Runtime theme
    switches via the command palette stay coherent because both themes
    are registered in ``__init__`` immediately after ``super().__init__()``
    initialises ``_registered_themes``.
    """

    def __init__(self, *, session: SloAgentSession) -> None:
        """Compose the TUI around a pre-built session.

        Args:
            session (SloAgentSession): The in-process session to drive.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme = self.DEFAULT_THEME
        self._session: SloAgentSession = session
        self._attach_pool_to_session(session=self._session)
        self._transcript_scroll: Optional[VerticalScroll] = None
        self._transcript_content: Optional[Vertical] = None
        self._status_region: Optional[Vertical] = None
        self._input: Optional[PromptInput] = None
        self._suggestion_menu: Optional[SlashSuggestionMenu] = None
        self._usage_status_bar: Optional[UsageStatusBar] = None
        self._active_expandable_tool_block: Optional[ToolExecutionBlock] = None
        # Global expand-all state for the Ctrl+O toggle. None = natural default
        # (full user text, visible reasoning, compact tool blocks); True =
        # expand all; False = collapse all. New blocks inherit this via
        # ``force_expanded`` so the toggle persists across new messages.
        self._global_expand_all: Optional[bool] = None
        self._adapter: Optional[_TranscriptAdapter] = None
        self._in_flight_task: Optional[asyncio.Task[None]] = None
        self._spinner: Optional[ThinkingSpinner] = None
        # Pending steering blocks awaiting consumption, oldest first. Each
        # ``steering_applied`` event drains one (FIFO), matching the agent's
        # drain order.
        self._pending_steer_blocks: list[SteeringPendingBlock] = []
        self._slash_suggestion_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self._suggestion_engine: SlashSuggestionEngine = SlashSuggestionEngine(
            registry=SlashRouter.registry(),
        )
        self._projector: TranscriptProjector = TranscriptProjector(host=self)
        self._prompt_history: PromptHistoryNavigator = PromptHistoryNavigator()
        self._setting_prompt_from_history: bool = False
        # Fleet panel reference for sub-agent status display.
        self._fleet_panel: Optional[SubAgentFleetPanel] = None

    def compose(self) -> ComposeResult:
        """Build the widget tree.

        Yields:
            Header, the transcript + input vertical, and Footer.
        """
        yield Header(show_clock=False)
        with Vertical(id="chat-shell"):
            self._transcript_scroll = VerticalScroll(id="transcript-scroll")
            self._transcript_content = Vertical(id="transcript-content")
            with self._transcript_scroll:
                yield self._transcript_content
            self._status_region = Vertical(id="status-region")
            self._suggestion_menu = SlashSuggestionMenu()
            with self._status_region:
                yield self._suggestion_menu
            self._adapter = _TranscriptAdapter(tui=self)
            self._input = PromptInput()
            yield self._input
            # Fleet panel: below PromptInput; hidden until first sub_agent_spawned.
            # Shows live sub-agent status rows; the orchestrator transcript always
            # stays in the foreground above the prompt.
            self._fleet_panel = SubAgentFleetPanel()
            yield self._fleet_panel
            self._usage_status_bar = UsageStatusBar()
            yield self._usage_status_bar
        yield Footer()

    async def on_mount(self) -> None:
        """Hydrate from history, subscribe the renderer, maybe push auth.

        Call order matters (sub-spec 05.e §7.2): hydrate the transcript
        from replay projections BEFORE subscribing the live renderer
        so live events from a new prompt cannot interleave with the
        replay tail.
        """
        await self._hydrate_transcript_from_history()
        await self._maybe_render_startup_notice()
        self._session.subscribe(handler=self._render_event)
        self._refresh_title_bar()
        self._refresh_usage_status_bar()
        if self._input is not None:
            self._input.focus()
        if not self._has_credential_for_active_model():
            self._push_auth_modal()

    async def _hydrate_transcript_from_history(self) -> None:
        """Replay-derived transcript bootstrap for resumed sessions (05.e).

        No-ops when the session has no persisted events or history is
        disabled. Replay entries are mounted through the same
        ``TranscriptProjector`` (and therefore the same component widgets)
        as live events, so a resumed session renders identically to the
        live session that produced it. No canonical write happens here —
        replay is a pure read path. Runs before the live renderer
        subscribes so replay and live events cannot interleave.
        """
        try:
            entries = await self._session.hydrate_transcript_entries()
        except Exception:  # noqa: BLE001 — replay must never crash boot
            return
        for entry in entries:
            await self._projector.project_replay_entry(entry=entry)
        self._scroll_transcript_to_end()

    async def _maybe_render_startup_notice(self) -> None:
        """Render the one-time startup notice for new sessions only."""
        if not await self._session.should_show_startup_notice():
            return
        resolved_reasoning = resolve_reasoning_config(
            model_name=self._session.active_model_name,
            requested_level=self._session.active_reasoning_level,
        )
        reasoning_detail: str = self._reasoning_detail_text(
            provider_effort=resolved_reasoning.provider_effort,
            provider_budget_tokens=resolved_reasoning.provider_budget_tokens,
        )
        self._write_adapter_line(
            content=(
                "slo, Copyright (C) 2026 Siddharth Ravichandran. "
                "This program comes with ABSOLUTELY NO WARRANTY; see LICENSE. "
                "This is free software, and you are welcome to redistribute it under GPLv2."
            ),
            classes="tool-result",
        )
        self._write_adapter_line(
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
        next_theme: str = SLO_DARK_THEME.name if self.theme == SLO_DEFAULT_THEME.name else SLO_DEFAULT_THEME.name
        self.theme = next_theme
        self._write_adapter_line(content=f"theme: {next_theme}", classes="tool-result")

    def _push_auth_modal(self) -> None:
        """Push ``AuthenticationScreen`` with the dismissal callback wired up."""
        self.push_screen(AuthenticationScreen(), callback=self._on_auth_dismissed)

    def _on_auth_dismissed(self, value: Optional[CredentialDAO]) -> None:
        """Refresh the active model and title state after auth success.

        Args:
            value (Optional[CredentialDAO]): ``CredentialDAO`` on success,
                ``None`` on cancel.
        """
        if value is None:
            return
        current_provider: ProviderName = provider_for_model(
            model_name=self._session.active_model_name,
        )
        if value.provider is not current_provider:
            new_model_name: str = default_model_for_provider(provider=value.provider)
            try:
                self._session.switch_model(model_name=new_model_name)
            except RuntimeError:
                pass
            else:
                self._write_adapter_line(
                    content=f"active model switched to {new_model_name}",
                    classes="tool-result",
                )
        self._refresh_title_bar(subject=value.subject)
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    def _refresh_title_bar(self, *, subject: Optional[str] = None) -> None:
        """Render title and subtitle from the session's active runtime state.

        Args:
            subject (Optional[str]): Optional authenticated subject to
                append to the subtitle.
        """
        self.title = (
            f"slo · {self._session.workdir} · {self._session.routed_model_name} · "
            f"reasoning {self._session.active_reasoning_level}"
        )
        if self._session.session_name is not None:
            session_identity: str = (
                f"session {self._session.session_name} · {self._session.session_id}"
            )
        else:
            session_identity = f"session {self._session.session_id}"
        self.sub_title = f"{session_identity} · {subject}" if subject else session_identity

    def _refresh_usage_status_bar(self) -> None:
        """Refresh the persistent usage-and-limits widget."""
        if self._usage_status_bar is None:
            return
        self._usage_status_bar.update_snapshot(
            snapshot=self._session.usage_snapshot(),
        )

    async def on_unmount(self) -> None:
        """Detach the renderer. No subprocess to tear down."""
        self._session.unsubscribe(handler=self._render_event)

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
        """Route one submitted line through the session.

        Args:
            event (PromptInput.Submitted): The custom submission event.
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
        if self._in_flight_task is not None:
            self._render_busy_line()
            return
        self._prompt_history.record(text=text)
        await self._echo_user_line(text=text)
        self._in_flight_task = asyncio.create_task(self._run_prompt(text=text))

    # ---- Actions ----------------------------------------------------------

    async def action_interrupt(self) -> None:
        """``^C``: abort the in-flight run, or quit if idle."""
        if self._in_flight_task is None:
            self.exit()
            return
        self._session.abort()
        self._escalate_abort()
        self._write_adapter_line(content="(aborting…)", classes="tool-result")

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
        resolved_message: object = (
            message if message is not None else self._resume_command_hint()
        )
        super().exit(
            result=result,
            return_code=return_code,
            message=cast(Optional[str], resolved_message),
        )

    async def _render_steer_pending(self, *, message: str) -> None:
        """Mount a pending ``SteeringPendingBlock`` for a freshly queued steer.

        Shown the moment ``/steer`` is accepted. The steer sits in the
        agent's queue until the run reaches a turn boundary; until then the
        muted pending block is visibly distinct from a consumed user message.
        When the agent folds it into the model context it emits
        ``steering_applied``; ``_consume_pending_steer_block`` then removes the
        block and ``_render_event`` re-renders it as a regular user message.

        Args:
            message (str): The verbatim steering text awaiting consumption.
        """
        if self._transcript_content is None:
            return
        follow_snapshot: bool = self._capture_follow_snapshot()
        block: SteeringPendingBlock = SteeringPendingBlock(message=message)
        await self._transcript_content.mount(block)
        self._pending_steer_blocks.append(block)
        self._restore_follow_after_mutation(follow_snapshot=follow_snapshot)

    async def _consume_pending_steer_block(self) -> None:
        """Remove the oldest pending steer block when its steer is consumed.

        Called from the ``steering_applied`` path (FIFO, matching the agent's
        drain order) just before the steer is re-rendered as a user message.
        A no-op when no pending block is tracked.
        """
        if not self._pending_steer_blocks:
            return
        block: SteeringPendingBlock = self._pending_steer_blocks.pop(0)
        await block.remove()

    async def _mount_tree_viewer(self, *, tree: object, tree_format: Optional[str] = None) -> None:
        """Mount the tree viewer widget for /tree command results.

        Args:
            tree: The SessionTreeNode root from SessionTreeBuilder.
            tree_format: Optional format string ("textual", "markdown", "html").
        """
        if self._transcript_scroll is None:
            return
        if tree_format is None:
            tree_format = TreeExportFormat.TEXTUAL.value

        if tree_format == TreeExportFormat.TEXTUAL.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode
            if isinstance(tree, SessionTreeNode):
                viewer = SessionTreeViewer(tree=tree)
                await self._transcript_scroll.mount(viewer)
        elif tree_format == TreeExportFormat.MARKDOWN.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode
            if isinstance(tree, SessionTreeNode):
                md = TreeMarkdownExporter.export(tree=tree)
                await self._transcript_scroll.mount(Static(md))
        elif tree_format == TreeExportFormat.HTML.value:
            from src.agents.slo_agent.history.tree_builder import SessionTreeNode
            if isinstance(tree, SessionTreeNode):
                path = TreeHtmlExporter.export(
                    tree=tree,
                    session_name=self._session.session_name or "unnamed",
                )
                await self._transcript_scroll.mount(Static(f"HTML tree written to: {path}"))

    def _resume_command_hint(self) -> str:
        """Return the copy-paste command that resumes the active session.

        Returns:
            str: A ``slo --resume <session id>`` line for the active session.
        """
        return f"Resume this session: slo --resume {self._session.session_id}"

    async def action_clear(self) -> None:
        """``^L``: clear the transcript without affecting agent state."""
        if self._adapter is not None:
            self._adapter.lines.clear()
        if self._transcript_content is not None:
            for child in list(self._transcript_content.children):
                await child.remove()
        self._active_expandable_tool_block = None
        # Pending steer widgets were just removed with the transcript; drop the
        # tracked references so a later ``steering_applied`` does not try to
        # remove an already-detached widget.
        self._pending_steer_blocks.clear()
        self._projector.reset_for_new_run()

    async def action_copy_visible_text(self) -> None:
        """Copy the selected prompt text or the visible transcript.

        Selection takes precedence when the prompt editor has one.
        Otherwise Slo copies the current transcript as plain text, one
        rendered line per newline, which makes the visible conversation
        extractable from the widget-based transcript surface.
        """
        text: str = self._selected_prompt_text() or self._copyable_transcript_text()
        if not text:
            return
        self.copy_to_clipboard(text)

    async def action_toggle_expandable_details(self) -> None:
        """Toggle global expand-all mode for every transcript block.

        Cycles natural-default -> expand-all -> collapse-all -> expand-all ...
        The first press always expands; subsequent presses alternate. The new
        state is pushed onto every existing block and inherited by new ones.
        """
        self._global_expand_all = not bool(self._global_expand_all)
        self._apply_global_expand_state()
        self.refresh_bindings()

    def _apply_global_expand_state(self) -> None:
        """Push the current global expand state onto every transcript block.

        Widgets without a ``set_expanded`` method (separators, plain statics,
        steering and tree blocks) are skipped.
        """
        if self._transcript_content is None:
            return
        expanded: bool = bool(self._global_expand_all)
        for widget in self._transcript_content.children:
            set_expanded = getattr(widget, "set_expanded", None)
            if set_expanded is not None:
                set_expanded(expanded=expanded)

    # ---- Private helpers --------------------------------------------------

    def _refresh_slash_suggestions(self) -> None:
        """Recompute slash suggestions from the current prompt buffer."""
        if self._input is None:
            return
        state: SlashSuggestionStateDAO = self._suggestion_engine.evaluate(
            buffer_text=self._input.text,
            active_model_name=self._session.active_model_name,
        )
        self._slash_suggestion_state = state
        self._render_slash_suggestion_state(state=state)

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

        Args:
            line (str): The full input line including the leading slash.
        """
        self._hide_slash_suggestions()
        result = await SlashRouter.dispatch(line=line, session=self._session)
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
        if result.steer_pending_message is not None:
            await self._render_steer_pending(message=result.steer_pending_message)
        if result.render_tree is not None:
            await self._mount_tree_viewer(tree=result.render_tree, tree_format=result.tree_format)
        if result.rendered is not None:
            self._write_adapter_line(content=result.rendered, classes="tool-result")
        if result.refresh_title:
            self._refresh_title_bar()
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
        if result.toggle_theme:
            self._toggle_theme()
        if result.open_auth_modal:
            self._push_auth_modal()
        if result.should_exit:
            self.exit()

    async def _start_new_session(self, *, requested_name: Optional[str]) -> None:
        """Replace the active session with a brand-new one.

        Args:
            requested_name (Optional[str]): Optional initial human-readable session name.
        """
        if self._session.is_running:
            self._write_adapter_line(
                content="cannot start a new session while a prompt is in flight; run /abort first",
                classes="tool-result",
            )
            return
        old_session: SloAgentSession = self._session
        old_session.unsubscribe(handler=self._render_event)
        new_session: SloAgentSession = SloAgentSession.build(
            config=self._build_replacement_session_config(old_session=old_session),
        )
        self._attach_pool_to_session(session=new_session)
        if requested_name is not None:
            await new_session.rename_session(session_name=requested_name)
        self._session = new_session
        await self.action_clear()
        self._prompt_history.clear_navigation()
        self._prompt_history = PromptHistoryNavigator()
        if self._input is not None:
            self._input.load_text("")
            self._input.set_prompt_history_navigation_enabled(enabled=False)
        await self._maybe_render_startup_notice()
        self._session.subscribe(handler=self._render_event)
        self._refresh_title_bar()
        self._session.refresh_usage_snapshot()
        self._refresh_usage_status_bar()

    async def _rename_current_session(self, *, session_name: str) -> None:
        """Rename the active session and refresh visible title state.

        Args:
            session_name (str): Requested human-readable session name.
        """
        try:
            await self._session.rename_session(session_name=session_name)
        except Exception as exc:  # noqa: BLE001 - inline operator feedback required
            self._write_adapter_line(content=f"(rename failed: {exc})", classes="tool-result")
            return
        self._refresh_title_bar()
        self._write_adapter_line(content=f"session renamed to {session_name}", classes="tool-result")

    # ---- Sub-agent routing and fleet panel --------------------------------

    async def _route_sub_agent_event(self, event: AgentStreamEventDAO) -> None:
        """Route a tagged sub-agent event to the fleet panel.

        The orchestrator transcript is always in the foreground; sub-agent
        content never appears there. Lifecycle events write a one-line notice
        to the main transcript. Content events update the fleet panel's
        live-activity field so the user can see what each sub-agent is doing
        without leaving the orchestrator view.

        Args:
            event (AgentStreamEventDAO): Event carrying a non-``None`` ``sub_agent_id``.
        """
        task_id: str = event.task_id or ""
        session_id: str = event.sub_agent_id or ""

        if event.kind == "sub_agent_spawned":
            prompt_preview: str = event.content or ""
            if self._adapter is not None:
                self._adapter.write(
                    content=f"⊇ {task_id}: spawned",
                    classes="sub-agent-notice",
                )
            if self._fleet_panel is not None:
                await self._fleet_panel.register_row(
                    session_id=session_id,
                    task_id=task_id,
                    prompt_preview=prompt_preview,
                )
            return

        if event.kind in ("sub_agent_completed", "sub_agent_failed"):
            terminal_status: SubAgentStatus = (
                "completed" if event.kind == "sub_agent_completed" else "failed"
            )
            if self._adapter is not None:
                self._adapter.write(
                    content=f"⊇ {task_id}: {terminal_status}",
                    classes="sub-agent-notice",
                )
            if self._fleet_panel is not None:
                self._fleet_panel.mark_terminal(
                    session_id=session_id,
                    status=terminal_status,
                )
            return

        # Content events: update fleet row last-activity only.
        # Sub-agent content never reaches the orchestrator transcript.
        if self._fleet_panel is None:
            return
        activity: Optional[str] = self._sub_agent_activity_text(event=event)
        if activity is not None:
            self._fleet_panel.update_last_text(
                session_id=session_id,
                text=activity,
            )

    @staticmethod
    def _sub_agent_activity_text(*, event: AgentStreamEventDAO) -> Optional[str]:
        """Return a brief activity string for the fleet row from a content event.

        Extracts the most human-readable fragment from each content event kind
        so the fleet row always shows what the sub-agent is currently doing.
        Returns ``None`` for event kinds that carry no useful display text.

        Args:
            event (AgentStreamEventDAO): A sub-agent content event.

        Returns:
            Optional[str]: Activity text for the fleet row, or ``None``.
        """
        if event.kind in ("text_delta", "thinking_delta"):
            return event.delta or None
        if event.kind == "tool_call_end":
            # Show what tool the agent just dispatched and its primary argument.
            tool_name: str = event.tool_name or "tool"
            if not event.tool_input:
                return tool_name
            first_val: object = next(iter(event.tool_input.values()), None)
            if first_val is None:
                return tool_name
            preview: str = str(first_val)[:50].replace("\n", " ")
            return f"{tool_name}: {preview}"
        if event.kind == "tool_result":
            return f"✓ {event.tool_name or 'tool'}"
        return None

    async def _cleanup_sub_agent_state(self) -> None:
        """Reset the fleet panel at the end of a run.

        Called from ``_run_prompt``'s ``finally`` block after
        ``_unmount_spinner``. Hides and clears the fleet panel so the layout
        returns to the idle state and subsequent runs start cleanly.
        A no-op when no sub-agents were spawned in this run.
        """
        if self._fleet_panel is not None:
            await self._fleet_panel.reset()
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

    async def mount_user_message_block(self, *, text: str) -> UserMessageBlock:
        """Mount a fresh user message block into the transcript flow.

        Args:
            text (str): The raw user prompt text.

        Returns:
            UserMessageBlock: The mounted block.
        """
        block: UserMessageBlock = UserMessageBlock(text=text, force_expanded=self._global_expand_all)
        if self._transcript_content is not None:
            await self._transcript_content.mount(block)
        return block

    def mount_turn_separator_if_needed(self) -> None:
        """Mount and record a turn separator when prior content exists.

        Idempotent in effect: a no-op on the first turn (nothing to
        separate). Writing through ``_write_adapter_line`` both mounts the
        visible ``┈┈┈`` separator and records its logical line.
        """
        if self._adapter is None or not self._adapter.has_prior_turn_content():
            return
        self._write_adapter_line(content=_TranscriptAdapter.TURN_SEPARATOR, classes="turn-separator")

    async def mount_assistant_block(
        self,
        *,
        title_prefix: Optional[str] = None,
    ) -> AssistantStreamBlock:
        """Mount a fresh assistant streaming block into the transcript flow.

        Args:
            title_prefix (Optional[str]): Optional dim label shown above the
                block's reasoning and answer surfaces. Used by the sub-agent
                rendering path to tag child output with its task id.
                ``None`` (default) produces a label-free block identical to
                the pre-feature behaviour.

        Returns:
            AssistantStreamBlock: The mounted block.
        """
        block: AssistantStreamBlock = AssistantStreamBlock(
            title_prefix=title_prefix,
            force_expanded=self._global_expand_all,
        )
        if self._transcript_content is not None:
            await self._transcript_content.mount(block)
        return block

    async def mount_tool_execution_block(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
    ) -> ToolExecutionBlock:
        """Mount a fresh tool execution block above the prompt input.

        Args:
            tool_call_id (str): Stable tool call id.
            tool_name (str): Tool name.

        Returns:
            ToolExecutionBlock: The mounted block.
        """
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            force_expanded=self._global_expand_all,
        )
        if self._transcript_content is not None:
            await self._transcript_content.mount(block)
        self._set_active_expandable_tool_block(block=block)
        return block

    def _set_active_expandable_tool_block(self, *, block: ToolExecutionBlock) -> None:
        """Mark ``block`` as the active expandable tool block.

        Args:
            block (ToolExecutionBlock): Newly active tool block.
        """
        if self._active_expandable_tool_block is block:
            return
        if self._active_expandable_tool_block is not None:
            self._active_expandable_tool_block.set_active(active=False)
        self._active_expandable_tool_block = block
        self._active_expandable_tool_block.set_active(active=True)

    def write_transcript_line(self, *, content: str, classes: str) -> None:
        """Write and record an append-only transcript line.

        Args:
            content (str): Transcript line content.
            classes (str): Semantic transcript class.
        """
        self._write_adapter_line(content=content, classes=classes)

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        """Record a logical transcript line without rendering a duplicate.

        Args:
            content (str): Logical transcript content.
            classes (str): Semantic transcript class.
        """
        if self._adapter is None:
            return
        self._adapter.record(content=content, classes=classes)

    async def _run_prompt(self, *, text: str) -> None:
        """Drain ``session.invoke`` to completion.

        Args:
            text (str): The user prompt.
        """
        self._projector.reset_for_new_run()
        await self._mount_spinner()
        saw_failed_event: bool = False
        try:
            async for event in self._session.invoke(text=text):
                if event.kind in {"run_failed", "recovery_exhausted"}:
                    saw_failed_event = True
        except asyncio.CancelledError:
            # Hard-cancel escalation from /abort or ^C landed on a run that
            # would not wind down cooperatively (e.g. a hung tool call).
            self._write_adapter_line(content="(aborted)", classes="assistant-aborted")
        except ValueError as exc:
            self._write_adapter_line(
                content=f"(configuration error: {exc})",
                classes="tool-result",
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the user
            if not saw_failed_event:
                self._render_run_error(exc=exc)
        finally:
            self._session.refresh_usage_snapshot()
            self._refresh_usage_status_bar()
            await self._unmount_spinner()
            await self._cleanup_sub_agent_state()
            self._in_flight_task = None

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
        self._write_adapter_line(
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
        if event.sub_agent_id is not None:
            await self._route_sub_agent_event(event=event)
            return
        if event.kind == "steering_applied":
            # The queued steer has now been folded into the model context —
            # drop its pending block and render it as a regular user message
            # in its place.
            follow_snapshot: bool = self._capture_follow_snapshot()
            await self._consume_pending_steer_block()
            await self._projector.project_user_turn(text=event.content or "")
            self._restore_follow_after_mutation(follow_snapshot=follow_snapshot)
            return
        follow_snapshot = self._capture_follow_snapshot()
        await self._projector.project(event=event)
        self._restore_follow_after_mutation(follow_snapshot=follow_snapshot)
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
                self._spinner.set_override_status(text="Compaction failed.")

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

    async def _echo_user_line(self, *, text: str) -> None:
        """Echo one user turn into the transcript as a dedicated component.

        Delegates to the projector, which mounts a ``UserMessageBlock`` and
        records the ``> text`` logical line (with a turn separator ahead of
        it when prior content exists).

        Args:
            text (str): The user prompt text to echo.
        """
        follow_snapshot: bool = self._capture_follow_snapshot()
        await self._projector.project_user_turn(text=text)
        self._restore_follow_after_mutation(follow_snapshot=follow_snapshot)

    def _render_busy_line(self) -> None:
        """Render the busy reply when the input arrives during a run."""
        self._write_adapter_line(
            content="(prompt in flight — wait, or steer with `/steer <msg>`)",
            classes="tool-result",
        )

    def _write_adapter_line(self, *, content: str, classes: str) -> None:
        """Funnel non-event transcript writes through the adapter.

        The adapter is the single test seam — every line that lands in the
        transcript also lands in ``self._adapter.lines``. Slash output, the
        ``> <text>`` echo, the busy reply, and the ``(aborting…)`` marker all
        go through here; the streaming event path goes through
        ``EventRenderer.render`` and reaches the same adapter on its own.

        Args:
            content (str): The line content.
            classes (str): The semantic render class.
        """
        if self._adapter is None:
            self._transcript_write(line=content, style_class=classes)
            return
        self._adapter.write(content=content, classes=classes)

    def _selected_prompt_text(self) -> str:
        """Return the selected prompt text, or ``""`` when nothing is selected."""
        if self._input is None:
            return ""
        return self._input.selected_text or ""

    def _copyable_transcript_text(self) -> str:
        """Return the transcript as plain text suitable for clipboard copy."""
        if self._adapter is None:
            return ""
        return "\n".join(content for content, classes in self._adapter.lines if classes != "turn-separator")

    def _capture_follow_snapshot(self) -> bool:
        """Snapshot whether the transcript is currently following the bottom.

        Returns:
            bool: True when the transcript viewport was already at the bottom.
        """
        return self._transcript_is_at_bottom()

    def _transcript_is_at_bottom(self) -> bool:
        """Return True when the transcript viewport is effectively at bottom.

        Returns:
            bool: True when the scroll position is within one line of the bottom.
        """
        if self._transcript_scroll is None:
            return True
        return (self._transcript_scroll.max_scroll_y - self._transcript_scroll.scroll_y) <= 1.0

    def _restore_follow_after_mutation(self, *, follow_snapshot: bool) -> None:
        """Restore follow mode after a transcript mutation when appropriate.

        Args:
            follow_snapshot (bool): Pre-mutation follow state.
        """
        if not follow_snapshot:
            return
        self._scroll_transcript_to_end()

    def _scroll_transcript_to_end(self) -> None:
        """Keep the transcript viewport pinned to the latest content."""
        if self._transcript_scroll is None:
            return
        self.call_after_refresh(self._transcript_scroll.scroll_end, animate=False)

    def _transcript_write(self, *, line: str, style_class: str) -> None:
        """Append one visible line widget to the transcript container.

        Args:
            line (str): The line to write.
            style_class (str): Semantic render class from the TUI renderer.
        """
        if self._transcript_content is None:
            return
        follow_snapshot: bool = self._capture_follow_snapshot()
        widget: Static
        if style_class == "assistant-final":
            widget = Static(Markdown(line), classes=style_class)
        else:
            widget = Static(line, classes=style_class)
        self._transcript_content.mount(widget)
        self._restore_follow_after_mutation(follow_snapshot=follow_snapshot)


class _TranscriptAdapter:
    """Transcript shim that records logical lines and appends visible widgets.

    ``EventRenderer`` and the slash-command path both speak in
    ``(content, classes)`` pairs. This adapter preserves that single
    semantic seam for tests/copy/replay while delegating visible writes
    to the widget-based transcript container.

    For readability in a compact transcript, each new user turn after the
    first gets a subtle separator line inserted ahead of it. That separator
    is now driven by ``SloTUI.mount_turn_separator_if_needed`` (called from
    the projector's user-turn path) rather than implicitly inside ``write``,
    because user turns are mounted as ``UserMessageBlock`` components and no
    longer flow through ``write`` as ``user-line`` entries.
    """

    TURN_SEPARATOR: str = "┈" * 18

    def __init__(self, *, tui: SloTUI) -> None:
        """Wrap the owning ``SloTUI``.

        Args:
            tui (SloTUI): The app whose transcript surface we write into.
        """
        self._tui: SloTUI = tui
        self.lines: list[tuple[str, str]] = []

    def write(self, content: str, classes: str = "") -> None:
        """Record the line and delegate to the visible transcript writer.

        Args:
            content (str): The text to append.
            classes (str): The semantic render class (default ``""``).
        """
        self._append_line(content=content, classes=classes)

    def _append_line(self, *, content: str, classes: str) -> None:
        """Persist one transcript line and write it to the transcript surface."""
        self.lines.append((content, classes))
        self._tui._transcript_write(line=content, style_class=classes)

    def record(self, *, content: str, classes: str) -> None:
        """Persist one logical transcript line without rendering it again.

        Args:
            content (str): Logical transcript content.
            classes (str): Semantic transcript class.
        """
        self.lines.append((content, classes))

    def has_prior_turn_content(self) -> bool:
        """Return True when a user turn separator should be inserted.

        Returns:
            bool: True when any non-separator line has already been recorded.
        """
        return any(classes != "turn-separator" for _content, classes in self.lines)
