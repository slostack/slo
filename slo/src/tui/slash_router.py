"""Slash-command dispatch for ``SloTUI`` (sub-spec 02.a.2)."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel

from src.agents.slo_agent.preferences.dao import UserPreferencesDAO, UserPreferencesStoreCorruptError
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.reasoning_capabilities import (
    ModelReasoningCapabilityDAO,
    ReasoningLevel,
    capability_for_model,
    default_reasoning_level_for_model,
    highest_supported_reasoning_level,
    parse_reasoning_level,
)
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.tui.model_catalog import supported_models_by_provider
from src.agents.slo_agent.history.tree_builder import SessionTreeBuilder
from src.tui.tree_export_format import TreeExportFormat
from src.tui.slash_command_registry import (
    SlashCommandRegistry,
    SlashCommandSpecDAO,
    build_default_registry,
)

__all__ = ["SlashCommandResultDAO", "SlashRouter"]


SlashHandler = Callable[..., Awaitable["SlashCommandResultDAO"]]


class SlashCommandResultDAO(BaseModel):
    """Outcome of a slash command — what the TUI should do next.

    Fields:
        rendered (Optional[str]): Line to write to the transcript, or
            ``None`` to render nothing.
        should_exit (bool): True iff the TUI should call ``self.exit()``.
        should_clear (bool): True iff the TUI should clear the transcript.
        open_auth_modal (bool): True iff the TUI should push
            ``AuthenticationScreen`` (02.b.6).
        refresh_title (bool): True iff the TUI should refresh the
            top-bar title from session runtime state.
        toggle_theme (bool): True iff the TUI should toggle between the
            slo-default and slo-dark themes.
        abort_run (bool): True iff the TUI should escalate the cooperative
            abort to a hard cancel of the in-flight task when it does not
            wind down on its own (e.g. a tool call is hung).
        steer_pending_message (Optional[str]): When set, the verbatim
            steering text the TUI should render as a pending (not-yet-
            consumed) message while the queued steer awaits the next turn.
        render_tree (Optional[object]): When set, the TUI should
            render the session tree using the format in ``tree_format``.
        tree_format (Optional[str]): Format for tree rendering
            (TEXTUAL, MARKDOWN, HTML). Defaults to TEXTUAL.
    """

    rendered: Optional[str] = None
    should_exit: bool = False
    should_clear: bool = False
    open_auth_modal: bool = False
    refresh_title: bool = False
    replace_session: bool = False
    requested_session_name: Optional[str] = None
    rename_current_session_to: Optional[str] = None
    toggle_theme: bool = False
    abort_run: bool = False
    steer_pending_message: Optional[str] = None
    render_tree: Optional[object] = None
    tree_format: Optional[str] = None


class SlashRouter:
    """Dispatch ``/<cmd> [args...]`` lines from the TUI."""

    _REGISTRY: SlashCommandRegistry = build_default_registry()

    @classmethod
    async def dispatch(
        cls,
        *,
        line: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Route ``line`` (known to start with ``/``) to a handler.

        Args:
            line (str): The full input line including the leading slash.
            session (SloAgentSession): The session to apply commands to.

        Returns:
            SlashCommandResultDAO: The result the TUI should apply.
        """
        command_token: str
        rest: str
        command_token, rest = cls._parse_line(line=line)
        command: Optional[SlashCommandSpecDAO] = cls._REGISTRY.resolve(token=command_token)
        if command is None:
            return SlashCommandResultDAO(rendered=f"unknown command: /{command_token}")
        handler: SlashHandler = cls._handler_for(command_name=command.name)
        return await handler(rest=rest, session=session)

    @classmethod
    def registry(cls) -> SlashCommandRegistry:
        """Return the canonical slash-command registry.

        Returns:
            SlashCommandRegistry: Registry backing dispatch and help text.
        """
        return cls._REGISTRY

    @staticmethod
    def _parse_line(*, line: str) -> tuple[str, str]:
        """Split a slash-command line into token and trailing argument text.

        Args:
            line (str): Full input line including the leading slash.

        Returns:
            tuple[str, str]: Parsed ``(token, rest)`` pair.
        """
        token: str
        rest: str
        token, _, rest = line[1:].strip().partition(" ")
        return token, rest

    @classmethod
    def _handler_for(cls, *, command_name: str) -> SlashHandler:
        """Return the bound handler for one canonical command.

        Args:
            command_name (str): Canonical registry command name.

        Returns:
            SlashHandler: Bound async command handler.
        """
        handlers: dict[str, SlashHandler] = {
            "help": cls._handle_help,
            "clear": cls._handle_clear,
            "exit": cls._handle_exit,
            "cwd": cls._handle_cwd,
            "abort": cls._handle_abort,
            "steer": cls._handle_steer,
            "auth": cls._handle_auth,
            "model": cls._handle_model,
            "reasoning": cls._handle_reasoning,
            "theme": cls._handle_theme,
            "tree": cls._handle_tree,
            "new": cls._handle_new,
            "rename": cls._handle_rename,
            "preferences": cls._handle_preferences,
        }
        return handlers[command_name]

    # ---- Per-command handlers --------------------------------------------

    @classmethod
    async def _handle_help(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Render the slash-command help block.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: Result with the help text.
        """
        return SlashCommandResultDAO(rendered=cls._help_text())

    @classmethod
    async def _handle_clear(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Clear the transcript.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: Result with ``should_clear=True``.
        """
        return SlashCommandResultDAO(should_clear=True)

    @classmethod
    async def _handle_exit(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Quit the TUI.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: Result with ``should_exit=True``.
        """
        return SlashCommandResultDAO(should_exit=True)

    @classmethod
    async def _handle_cwd(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Echo the workdir.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session whose workdir is echoed.

        Returns:
            SlashCommandResultDAO: Result containing ``cwd: <workdir>``.
        """
        return SlashCommandResultDAO(rendered=f"cwd: {session.workdir}")

    @classmethod
    async def _handle_abort(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Request a graceful abort of the in-flight run.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Session whose run is aborted.

        Returns:
            SlashCommandResultDAO: Result with ``(aborting…)`` marker.
        """
        session.abort()
        return SlashCommandResultDAO(rendered="(aborting…)", abort_run=True)

    @classmethod
    async def _handle_steer(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Queue a steering message for the next turn.

        Empty steer arguments are rejected (no point queuing an empty
        message — the model has nothing to act on).

        Args:
            rest (str): The steering message body.
            session (SloAgentSession): Session to enqueue against.

        Returns:
            SlashCommandResultDAO: Either the usage line (when ``rest``
                is empty) or the queue-confirmed marker.
        """
        if not rest:
            return SlashCommandResultDAO(rendered="usage: /steer <message>")
        session.steer(message=rest)
        return SlashCommandResultDAO(steer_pending_message=rest)

    @classmethod
    async def _handle_auth(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Open the authentication modal (02.b.6).

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: With ``open_auth_modal=True``.
        """
        return SlashCommandResultDAO(open_auth_modal=True)

    @classmethod
    async def _handle_theme(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Toggle between the slo-default and slo-dark themes.

        Args:
            rest (str): Trailing argument text (unused).
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: With ``toggle_theme=True``.
        """
        del rest, session
        return SlashCommandResultDAO(toggle_theme=True)

    @classmethod
    async def _handle_tree(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Render the session history as a tree.

        Args:
            rest: Optional format argument (textual, markdown, html).
            session: Active session whose history is rendered.

        Returns:
            SlashCommandResultDAO: Result with the tree or usage error.
        """
        format_str = rest.strip().lower() or "textual"
        if format_str not in ("textual", "markdown", "html"):
            return SlashCommandResultDAO(rendered="usage: /tree [textual|markdown|html]")

        format_enum = TreeExportFormat(format_str)
        if session.history_store is None:
            return SlashCommandResultDAO(rendered="history is disabled for this session")
        events = await session.history_store.load_events(session_id=session.session_id)
        tree = SessionTreeBuilder.build(events=events)
        return SlashCommandResultDAO(
            render_tree=tree,
            tree_format=format_enum.value,
        )

    @classmethod
    async def _handle_new(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Request that the TUI replace the active session.

        Args:
            rest (str): Optional initial session name.
            session (SloAgentSession): Active session.

        Returns:
            SlashCommandResultDAO: Declarative replace-session intent or rejection.
        """
        if session.is_running:
            return SlashCommandResultDAO(
                rendered="cannot start a new session while a prompt is in flight; run /abort first",
            )
        requested_name: Optional[str] = rest.strip() or None
        return SlashCommandResultDAO(
            replace_session=True,
            requested_session_name=requested_name,
        )

    @classmethod
    async def _handle_rename(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Request that the active session be renamed.

        Args:
            rest (str): Requested session name.
            session (SloAgentSession): Active session.

        Returns:
            SlashCommandResultDAO: Declarative rename intent or usage error.
        """
        del session
        requested_name: str = rest.strip()
        if not requested_name:
            return SlashCommandResultDAO(rendered="usage: /rename <session name>")
        return SlashCommandResultDAO(
            rename_current_session_to=requested_name,
            refresh_title=True,
        )

    @classmethod
    async def _handle_model(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """List supported models or switch the active one.

        Args:
            rest (str): Optional requested model name.
            session (SloAgentSession): Session whose model state may change.

        Returns:
            SlashCommandResultDAO: Rendered list output or switch result.
        """
        requested_model_name: str = rest.strip()
        if not requested_model_name:
            return SlashCommandResultDAO(rendered=cls._render_model_catalog(session=session))
        return await cls._switch_model(
            requested_model_name=requested_model_name,
            session=session,
        )

    @classmethod
    async def _switch_model(
        cls,
        *,
        requested_model_name: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Validate and switch the active model when allowed.

        Args:
            requested_model_name (str): Supported model name to activate.
            session (SloAgentSession): Session whose model state may change.

        Returns:
            SlashCommandResultDAO: Confirmation or actionable error.
        """
        if not cls._is_supported_model(requested_model_name=requested_model_name):
            return SlashCommandResultDAO(rendered=f"unknown model: {requested_model_name}")

        provider = provider_for_model(model_name=requested_model_name)
        if CredentialResolver.resolve(provider=provider) is None:
            return SlashCommandResultDAO(
                rendered=f"model '{requested_model_name}' requires /auth for {provider.value}",
            )
        if session.is_running:
            return SlashCommandResultDAO(
                rendered="cannot switch models while a prompt is in flight",
            )

        session.switch_model(model_name=requested_model_name)

        UserPreferencesStore.upsert(model_name=requested_model_name)

        return SlashCommandResultDAO(
            rendered=f"active model switched to {requested_model_name}. Preference saved.",
            refresh_title=True,
        )

    @classmethod
    def _is_supported_model(cls, *, requested_model_name: str) -> bool:
        """Return True when ``requested_model_name`` is in Slo's catalog.

        Args:
            requested_model_name (str): Candidate model name.

        Returns:
            bool: True when the model is supported.
        """
        for model_names in supported_models_by_provider().values():
            if requested_model_name in model_names:
                return True
        return False

    @classmethod
    def _render_model_catalog(cls, *, session: SloAgentSession) -> str:
        """Render the grouped supported-model catalog.

        Args:
            session (SloAgentSession): Session whose current model is marked.

        Returns:
            str: Human-readable model catalog.
        """
        lines: list[str] = ["models:"]
        grouped_models: dict = supported_models_by_provider()
        for provider, model_names in grouped_models.items():
            lines.append(f"  {provider.value.title()}")
            provider_available: bool = CredentialResolver.resolve(provider=provider) is not None
            for model_name in model_names:
                marker: str = "*" if model_name == session.active_model_name else " "
                status: str = cls._provider_availability_status(provider_available=provider_available)
                lines.append(f"    {marker} {model_name}   ({status})")
        return "\n".join(lines)

    @staticmethod
    def _provider_availability_status(*, provider_available: bool) -> str:
        """Return the display label for provider availability.

        Args:
            provider_available (bool): True when credentials exist.

        Returns:
            str: Human-readable status label.
        """
        if provider_available:
            return "available"
        return "requires /auth"

    @classmethod
    async def _handle_reasoning(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """List supported reasoning levels or switch the active one.

        Args:
            rest (str): Optional requested reasoning token.
            session (SloAgentSession): Session whose reasoning state may change.

        Returns:
            SlashCommandResultDAO: Rendered list output or switch result.
        """
        requested_token: str = rest.strip().lower()
        if not requested_token:
            return SlashCommandResultDAO(rendered=cls._render_reasoning_state(session=session))
        return await cls._switch_reasoning(
            requested_token=requested_token,
            session=session,
        )

    @classmethod
    async def _switch_reasoning(
        cls,
        *,
        requested_token: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Switch the active reasoning level when allowed.

        Args:
            requested_token (str): User-facing reasoning token.
            session (SloAgentSession): Session whose reasoning state may change.

        Returns:
            SlashCommandResultDAO: Confirmation or actionable error.
        """
        if session.is_running:
            return SlashCommandResultDAO(rendered="cannot switch reasoning while a prompt is in flight")

        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name=session.active_model_name,
        )
        if capability.supported_levels == ["off"]:
            return SlashCommandResultDAO(
                rendered=f"reasoning unsupported for {session.active_model_name}",
            )

        try:
            requested_level: ReasoningLevel = cls._requested_reasoning_level(
                requested_token=requested_token,
                session=session,
            )
        except ValueError as exc:
            return SlashCommandResultDAO(rendered=str(exc))

        previous_level: ReasoningLevel = session.active_reasoning_level
        if requested_level == previous_level:
            return SlashCommandResultDAO(rendered=f"reasoning already {previous_level}")

        active_level: ReasoningLevel = session.switch_reasoning_level(reasoning_level=requested_level)

        UserPreferencesStore.upsert(reasoning_level=active_level)

        return cls._reasoning_change_result(
            previous_level=previous_level,
            requested_level=requested_level,
            active_level=active_level,
            requested_token=requested_token,
            model_name=session.active_model_name,
        )

    @classmethod
    def _reasoning_change_result(
        cls,
        *,
        previous_level: ReasoningLevel,
        requested_level: ReasoningLevel,
        active_level: ReasoningLevel,
        requested_token: str,
        model_name: str,
    ) -> SlashCommandResultDAO:
        """Build the result for a reasoning-level change.

        Args:
            previous_level (ReasoningLevel): Previously active level.
            requested_level (ReasoningLevel): Requested canonical level.
            active_level (ReasoningLevel): Final active level after clamping.
            requested_token (str): User-facing requested token.
            model_name (str): Active model name.

        Returns:
            SlashCommandResultDAO: Render-ready reasoning change result.
        """
        if active_level != requested_level:
            return SlashCommandResultDAO(
                rendered=(
                    f"reasoning changed {previous_level} -> {active_level} "
                    f"(requested {requested_token}; clamped for {model_name})"
                ),
                refresh_title=True,
            )
        return SlashCommandResultDAO(
            rendered=f"reasoning changed {previous_level} -> {active_level}",
            refresh_title=True,
        )

    @classmethod
    def _requested_reasoning_level(
        cls,
        *,
        requested_token: str,
        session: SloAgentSession,
    ) -> ReasoningLevel:
        """Resolve one user-facing reasoning token to a canonical level.

        Args:
            requested_token (str): User-facing reasoning token.
            session (SloAgentSession): Session whose active model defines
                the available reasoning levels.

        Returns:
            ReasoningLevel: Canonical requested level.

        Raises:
            ValueError: If the token is not supported by the parser.
        """
        if requested_token == "on":
            return default_reasoning_level_for_model(model_name=session.active_model_name)
        if requested_token == "max":
            return highest_supported_reasoning_level(model_name=session.active_model_name)
        try:
            return parse_reasoning_level(token=requested_token)
        except ValueError as exc:
            usage: str = "usage: /reasoning <on|off|minimal|low|medium|high|xhigh|max>"
            raise ValueError(f"{exc}\n{usage}") from exc

    @classmethod
    def _render_reasoning_state(cls, *, session: SloAgentSession) -> str:
        """Render the reasoning state for the active session model.

        Args:
            session (SloAgentSession): Session whose reasoning state is rendered.

        Returns:
            str: Human-readable reasoning state block.
        """
        capability: ModelReasoningCapabilityDAO = capability_for_model(
            model_name=session.active_model_name,
        )
        supported_levels: str = cls._render_supported_reasoning_levels(capability=capability)
        return (
            f"model: {session.active_model_name}\n"
            f"reasoning: {session.active_reasoning_level}\n"
            f"supported: {supported_levels}"
        )

    @staticmethod
    def _render_supported_reasoning_levels(*, capability: ModelReasoningCapabilityDAO) -> str:
        """Render the supported-levels line for one model capability.

        Args:
            capability (ModelReasoningCapabilityDAO): Capability to render.

        Returns:
            str: Human-readable supported-levels value.
        """
        if capability.supported_levels == ["off"]:
            return "off (reasoning unsupported for this model)"
        return ", ".join(capability.supported_levels)

    @classmethod
    async def _handle_preferences(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Display or clear saved user preferences (26.a.3).

        With no argument, renders the current saved preferences.
        With ``clear`` argument, deletes the preferences file.

        Args:
            rest (str): Optional subcommand — ``"clear"`` or empty.
            session (SloAgentSession): Active session (unused).

        Returns:
            SlashCommandResultDAO: Result with preferences text or clear confirmation.
        """
        del session

        if rest.strip().lower() == "clear":
            deleted: bool = UserPreferencesStore.clear()
            msg: str = (
                "Preferences cleared. Defaults will apply on next boot."
                if deleted
                else "No saved preferences to clear."
            )
            return SlashCommandResultDAO(rendered=msg)

        prefs: UserPreferencesDAO = UserPreferencesStore.load()
        model_line: str = f"  model:     {prefs.default_model_name or '(none — uses default)'}"
        reasoning_line: str = (
            f"  reasoning: {prefs.default_reasoning_level or '(none — uses model default)'}"
        )
        return SlashCommandResultDAO(
            rendered=f"Saved preferences:\n{model_line}\n{reasoning_line}",
        )

    @classmethod
    def _help_text(cls) -> str:
        """Return the human-readable slash-command help text.

        Returns:
            str: Multi-line slash-command help block.
        """
        lines: list[str] = ["slash commands:"]
        for command in cls.registry().ordered_commands():
            lines.append(cls._help_line(command=command))
        return "\n".join(lines)

    @staticmethod
    def _help_line(*, command: SlashCommandSpecDAO) -> str:
        """Render one help row from registry truth.

        Args:
            command (SlashCommandSpecDAO): Registry command metadata.

        Returns:
            str: One aligned help row.
        """
        label: str = SlashRouter._help_label(command=command)
        return f"  {label:<16} — {command.description}"

    @staticmethod
    def _help_label(*, command: SlashCommandSpecDAO) -> str:
        """Return the display label for one help row.

        Args:
            command (SlashCommandSpecDAO): Registry command metadata.

        Returns:
            str: Display label for the help surface.
        """
        if command.argument_mode != "none" and command.usage is not None:
            return command.usage
        return f"/{command.name}"


