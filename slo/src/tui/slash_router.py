"""Slash-command dispatch for ``SloTUI`` (sub-spec 02.a.2)."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Protocol
from unittest.mock import Mock

from pydantic import BaseModel, model_validator

from src.agents.slo_agent.preferences.dao import UserPreferencesDAO, UserPreferencesStoreCorruptError
from src.agents.slo_agent.preferences.service import UserPreferencesStore
from src.agents.slo_agent.sessions.dao import (
    ContextWindowSnapshotDAO,
    ManualCompactionResultDAO,
    ManualCompactionStatus,
)
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.auth.credential_resolver import CredentialResolver
from src.auth.provider_for_model import provider_for_model
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.model_catalog.service import ModelCatalogService
from src.auth.credential_dao import ProviderName
from src.agents.reasoning_capabilities import (
    ModelReasoningCapabilityDAO,
    ReasoningLevel,
    capability_for_model,
    default_reasoning_level_for_model,
    highest_supported_reasoning_level,
    parse_reasoning_level,
    resolve_reasoning_config,
)
from src.tui.model_catalog import (
    ModelSuggestionEntryDAO,
    model_suggestion_entries,
    supported_models_by_provider,
)
from src.agents.slo_agent.history.tree_builder import SessionTreeBuilder
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowCommandResultDAO,
    WorkflowCommandService,
    WorkflowHandleStore,
)
from src.tui.tree_export_format import TreeExportFormat
from src.tui.slash_command_registry import (
    SlashCommandRegistry,
    SlashCommandSpecDAO,
    build_default_registry,
)

__all__ = ["SlashCommandResultDAO", "SlashRouter"]


SlashHandler = Callable[..., Awaitable["SlashCommandResultDAO"]]


class ManualCompactionFormatter(Protocol):
    """Keyword-only renderer for one Manual Compaction result."""

    def __call__(self, *, result: ManualCompactionResultDAO) -> str:
        """Render one typed terminal result."""


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
        refresh_context_window (bool): Re-measure and repaint the Context Window Snapshot.
        refresh_usage_status (bool): Repaint a cached usage status without measuring.
        git_diff_path (Optional[str]): Raw path the operator asked to diff; the
            TUI loads it and pushes GitDiffScreen.
        dismissed_workflow_id (Optional[str]): Workflow whose durable dismissal
            succeeded; the TUI suppresses its observation group in memory.
        resumed_workflow_id (Optional[str]): Workflow whose relaunch was
            confirmed; the TUI clears any observation suppression for it.
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
    refresh_context_window: bool = False
    refresh_usage_status: bool = False
    git_diff_path: Optional[str] = None
    dismissed_workflow_id: Optional[str] = None
    resumed_workflow_id: Optional[str] = None

    @model_validator(mode="after")
    def _reject_duplicate_context_refresh(self) -> "SlashCommandResultDAO":
        """Reject conflicting measurement and cached-repaint requests.

        Returns:
            SlashCommandResultDAO: Validated result.

        Raises:
            ValueError: When both context refresh flags are enabled.
        """
        if self.refresh_context_window and self.refresh_usage_status:
            raise ValueError("only one context refresh mode may be selected")
        return self


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
        plugin_handler = cls._plugin_handler_for_session(
            session=session,
            command_name=command.name,
        )
        if plugin_handler is not None:
            return await cls._dispatch_plugin_handler(
                handler=plugin_handler,
                rest=rest,
                session=session,
            )
        handler: SlashHandler = cls._handler_for(command_name=command.name)
        return await handler(rest=rest, session=session)

    @classmethod
    def requires_activity(cls, *, line: str) -> bool:
        """Return whether the command on ``line`` runs long enough to show a loader.

        Reads the registry's ``shows_activity`` flag. Called by
        ``SloTUI._dispatch_slash_command`` before dispatch so a long-running
        command mounts the fixed activity spinner instead of leaving the screen
        blank while it works. Unknown commands are not long-running.

        Args:
            line (str): The full input line including the leading slash.

        Returns:
            bool: ``True`` only for a known command flagged ``shows_activity``.
        """
        command_token: str
        _rest: str
        command_token, _rest = cls._parse_line(line=line)
        command: Optional[SlashCommandSpecDAO] = cls._REGISTRY.resolve(token=command_token)
        return command is not None and command.shows_activity

    @staticmethod
    def _plugin_handler_for_session(
        *,
        session: SloAgentSession,
        command_name: str,
    ) -> Callable[..., Any] | None:
        """Resolve a plugin handler only from an actual session-owned registry.

        Args:
            session (SloAgentSession): Active runtime session or a legacy test stub.
            command_name (str): Canonical command token.

        Returns:
            Callable[..., Any] | None: Accepted plugin handler, or ``None`` for
            built-ins and legacy session stubs.
        """
        registry = getattr(session, "_plugin_registry", None)
        if registry is None or isinstance(registry, Mock):
            return None
        return session.plugin_command_handler(command_name=command_name)

    @staticmethod
    async def _dispatch_plugin_handler(
        *,
        handler: Callable[..., Any],
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Run one validated plugin command through the session-owned runtime seam.

        Args:
            handler (Callable[..., Any]): Registered plugin command callback.
            rest (str): Raw trailing command text.
            session (SloAgentSession): Active session supplied to the plugin.

        Returns:
            SlashCommandResultDAO: Typed plugin result, rendered string, or an
            isolated failure diagnostic.
        """
        try:
            outcome: Any = handler(rest=rest, session=session)
            if hasattr(outcome, "__await__"):
                outcome = await outcome
        except Exception as exc:  # noqa: BLE001 -- plugin commands cannot break the TUI
            return SlashCommandResultDAO(rendered=f"plugin command failed: {exc}")
        if isinstance(outcome, SlashCommandResultDAO):
            return outcome
        if outcome is None:
            return SlashCommandResultDAO()
        return SlashCommandResultDAO(rendered=str(outcome))

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
            "context-window": cls._handle_context_window,
            "new": cls._handle_new,
            "compact": cls._handle_compact,
            "diff": cls._handle_diff,
            "rename": cls._handle_rename,
            "preferences": cls._handle_preferences,
            "plugins": cls._handle_plugins,
            "workflows": cls._handle_workflows,
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
    async def _handle_diff(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Return the requested Git diff path as a typed TUI intent.

        WHAT: Leaves path validation to GitDiffContentService, the feature's
        filesystem safety boundary.
        WHO: SlashRouter.dispatch calls this for the ``/diff`` command.
        WHEN: Runs before SloTUI loads content and pushes GitDiffScreen.

        Args:
            rest (str): Raw operator-supplied path argument.
            session (SloAgentSession): Active session, retained for handler consistency.

        Returns:
            SlashCommandResultDAO: A diff intent or the command usage message.
        """
        del session
        repository_relative_path: str = rest.strip()
        if not repository_relative_path:
            return SlashCommandResultDAO(
                rendered="/diff requires a file path. Usage: /diff <repository-relative-path>"
            )
        return SlashCommandResultDAO(git_diff_path=repository_relative_path)

    @classmethod
    async def _handle_context_window(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Render the active Context Window Snapshot.

        Args:
            rest (str): Trailing arguments, which are not permitted.
            session (SloAgentSession): Session to measure.

        Returns:
            SlashCommandResultDAO: Detailed rendering and measurement refresh request.
        """
        if rest.strip():
            return SlashCommandResultDAO(rendered="usage: /context-window")
        refreshed_usage: SessionUsageSnapshotDAO = await session.refresh_context_window_snapshot()
        snapshot: Optional[ContextWindowSnapshotDAO] = refreshed_usage.context_window_snapshot
        if not isinstance(snapshot, ContextWindowSnapshotDAO) or not snapshot.estimate_available:
            return SlashCommandResultDAO(rendered="context-window snapshot unavailable")
        return SlashCommandResultDAO(
            rendered=cls._format_context_window(snapshot=snapshot),
            refresh_context_window=True,
        )

    @staticmethod
    def _format_context_window(*, snapshot: ContextWindowSnapshotDAO) -> str:
        """Format one Context Window Snapshot for the transcript.

        Args:
            snapshot (ContextWindowSnapshotDAO): Session-owned snapshot.

        Returns:
            str: Operator-facing context-window line.
        """
        if not snapshot.estimate_available:
            return (
                f"context window ({snapshot.model_name}): {snapshot.context_window_tokens:,} tok total"
                " · usage unavailable (session history is disabled or empty)"
            )
        return (
            f"context window ({snapshot.model_name}): {snapshot.context_window_tokens:,} tok total"
            f" · {snapshot.estimated_used_tokens:,} tok used"
            f" · {snapshot.available_tokens:,} tok available"
            f" · {snapshot.consumed_percent:.1f}% used"
        )

    @classmethod
    async def _handle_compact(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Request one Manual Compaction from the session layer.

        Args:
            rest (str): Trailing arguments, which are not permitted.
            session (SloAgentSession): Session to compact.

        Returns:
            SlashCommandResultDAO: Result rendering and cached-footer repaint request.
        """
        if rest.strip():
            return SlashCommandResultDAO(rendered="usage: /compact")
        result: ManualCompactionResultDAO = await session.compact_context()
        return SlashCommandResultDAO(
            rendered=cls._format_manual_compaction(result=result),
            refresh_usage_status=True,
        )

    @classmethod
    def _format_manual_compaction(cls, *, result: ManualCompactionResultDAO) -> str:
        """Render a typed Manual Compaction result.

        Args:
            result (ManualCompactionResultDAO): Terminal session outcome.

        Returns:
            str: Operator-facing terminal line.
        """
        formatter: ManualCompactionFormatter = cls._manual_compaction_formatters()[result.status]
        return formatter(result=result)

    @staticmethod
    def _manual_compaction_formatters() -> dict[ManualCompactionStatus, ManualCompactionFormatter]:
        """Return the exhaustive Manual Compaction status formatter table.

        Returns:
            dict[ManualCompactionStatus, ManualCompactionFormatter]: Status renderers.
        """
        return {
            "compacted": SlashRouter._format_compaction_success,
            "nothing_to_compact": SlashRouter._format_compaction_noop,
            "unavailable": SlashRouter._format_compaction_unavailable,
            "failed": SlashRouter._format_compaction_failure,
        }

    @staticmethod
    def _format_compaction_success(*, result: ManualCompactionResultDAO) -> str:
        """Render a completed Manual Compaction.

        Args:
            result (ManualCompactionResultDAO): Successful result.

        Returns:
            str: Success line including refreshed usage when available.
        """
        snapshot: Optional[ContextWindowSnapshotDAO] = result.context_window_snapshot
        if snapshot is None or not snapshot.estimate_available:
            return "compaction complete"
        return (
            "compaction complete"
            f" · {snapshot.estimated_used_tokens:,} tok used"
            f" · {snapshot.consumed_percent:.1f}% of context window"
        )

    @staticmethod
    def _format_compaction_noop(*, result: ManualCompactionResultDAO) -> str:
        """Render a successful Manual Compaction no-op.

        Args:
            result (ManualCompactionResultDAO): No-op result.

        Returns:
            str: Fixed no-op copy.
        """
        del result
        return "nothing to compact"

    @staticmethod
    def _format_compaction_unavailable(*, result: ManualCompactionResultDAO) -> str:
        """Render a Manual Compaction rejection with its stable fallback.

        Args:
            result (ManualCompactionResultDAO): Unavailable operation result.

        Returns:
            str: Session detail or the unavailable fallback.
        """
        return result.detail or "compaction is unavailable"

    @staticmethod
    def _format_compaction_failure(*, result: ManualCompactionResultDAO) -> str:
        """Render a Manual Compaction failure without leaking exception detail.

        Args:
            result (ManualCompactionResultDAO): Failed operation result.

        Returns:
            str: Session detail or the failure fallback.
        """
        return result.detail or "compaction failed"

    @classmethod
    async def _handle_plugins(cls, *, rest: str, session: SloAgentSession) -> SlashCommandResultDAO:
        """Render plugin health or apply one explicit plugin operator action.

        WHAT: Routes `/plugins`, `/plugins trust`, and `/plugins reload` to session APIs.
        WHO: The slash router invokes it after resolving the plugins command.
        WHEN: An operator inspects or changes plugin runtime state in the TUI.
        """
        command: str = rest.strip()
        if command == "trust":
            await session.trust_project_plugins()
            return SlashCommandResultDAO(
                rendered=cls._plugin_health_text(session=session, prefix="trusted project")
            )
        if command == "reload":
            await session.reload_plugins()
            return SlashCommandResultDAO(
                rendered=cls._plugin_health_text(session=session, prefix="plugins reloaded")
            )
        if command:
            return SlashCommandResultDAO(rendered="usage: /plugins [trust|reload]")
        return SlashCommandResultDAO(rendered=cls._plugin_health_text(session=session))

    @staticmethod
    def _plugin_health_text(*, session: SloAgentSession, prefix: str = "") -> str:
        """Format the session's plugin health records for one slash response.

        WHAT: Builds concise operator-visible health lines from registry records.
        WHO: The plugins slash command calls it after inspection or mutation.
        WHEN: A user requests plugin health, trust, or reload information.
        """
        reports = session.plugin_health_reports()
        if not reports:
            return f"{prefix}: no plugins loaded".strip(": ")
        lines: list[str] = [prefix] if prefix else []
        lines.extend(f"{report.plugin_id}: {report.status.value}" for report in reports)
        return "\n".join(lines)

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
        if requested_model_name == "refresh":
            return await cls._refresh_model_catalog(session=session)
        return await cls._switch_model(requested_model_name=requested_model_name, session=session)

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
        result: str = await session.prepare_model_selection(model_name=requested_model_name)
        return SlashCommandResultDAO(
            rendered=result,
            refresh_title=result.startswith("active model switched"),
        )

    @classmethod
    async def _refresh_model_catalog(cls, *, session: SloAgentSession) -> SlashCommandResultDAO:
        """Delegate one manual catalog refresh to the session preparation owner.

        Args:
            session (SloAgentSession): Session that owns catalog adoption state.

        Returns:
            SlashCommandResultDAO: Safe refresh outcome for the transcript.
        """
        return SlashCommandResultDAO(rendered=await session.refresh_model_catalog())

    @classmethod
    def _render_model_catalog(cls, *, session: SloAgentSession) -> str:
        """Render the grouped supported-model catalog.

        Args:
            session (SloAgentSession): Session whose current model is marked.

        Returns:
            str: Human-readable model catalog.
        """
        lines: list[str] = ["models:"]
        entries: list[ModelSuggestionEntryDAO] = model_suggestion_entries(
            active_model_name=session.active_model_name,
        )
        entries.sort(
            key=lambda entry: (not entry.is_active, bool(entry.support_tier_label), entry.model_name)
        )
        for entry in entries[:5]:
            marker = "*" if entry.is_active else " "
            status = entry.status_summary or "authentication not checked"
            lines.append(f"{marker} {entry.model_name} ({status})")
        lines.append(f"Showing {min(5, len(entries))} of {len(entries)} — type /model <search> to narrow")
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

        return cls._switch_idle_reasoning(requested_token=requested_token, session=session)

    @classmethod
    def _require_reasoning_change_controls(
        cls,
        *,
        requested_token: str,
        model_name: str,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> None:
        """Validate advertised controls before idle parsing or mutation.

        Args:
            requested_token: Operator's token, including explicit off.
            model_name: Selected route.
            snapshot: Session-owned catalog view.

        Raises:
            ValueError: Unknown, unsupported or unpermitted disable controls.
        """
        unknown = cls._provider_default_reasoning_note(model_name=model_name, snapshot=snapshot)
        if unknown:
            raise ValueError(f"{model_name}: {unknown}")
        capability = capability_for_model(model_name=model_name, snapshot=snapshot)
        if cls._is_reasoning_unsupported(capability=capability):
            raise ValueError(f"reasoning unsupported for {model_name}")
        if cls._is_unpermitted_openrouter_disable(requested_token=requested_token, capability=capability):
            raise ValueError(f"reasoning disable unavailable for {model_name}; provider default applies")

    @classmethod
    def _switch_idle_reasoning(
        cls,
        *,
        requested_token: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """Validate idle input before committing outside the validation catch.

        Args:
            requested_token: Operator token.
            session: Idle session owning the policy and selected state.

        Returns:
            Safe validation feedback or the committed selection result.
        """
        snapshot = session.catalog_snapshot
        try:
            cls._require_reasoning_change_controls(
                requested_token=requested_token,
                model_name=session.active_model_name,
                snapshot=snapshot,
            )
            requested_level: ReasoningLevel = cls._requested_reasoning_level(
                requested_token=requested_token,
                session=session,
            )
        except ValueError as exc:
            return SlashCommandResultDAO(rendered=str(exc))

        return cls._apply_reasoning_selection(
            requested=requested_level,
            requested_token=requested_token,
            session=session,
            snapshot=snapshot,
        )

    @classmethod
    def _apply_reasoning_selection(
        cls,
        *,
        requested: ReasoningLevel,
        requested_token: str,
        session: SloAgentSession,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> SlashCommandResultDAO:
        """Choose no-op or mutation after validation without catching commit errors.

        Args:
            requested: Valid canonical level.
            requested_token: Original feedback token.
            session: Idle state owner.
            snapshot: View captured for validation.

        Returns:
            No-op feedback or changed result.
        """
        previous_level = session.active_reasoning_level
        if requested == previous_level:
            return cls._unchanged_reasoning_result(session=session, snapshot=snapshot)

        return cls._commit_reasoning_selection(
            previous=previous_level,
            requested=requested,
            requested_token=requested_token,
            session=session,
            snapshot=snapshot,
        )

    @classmethod
    def _unchanged_reasoning_result(
        cls,
        *,
        session: SloAgentSession,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> SlashCommandResultDAO:
        """Render unchanged selection without writing preferences or refreshing title.

        Args:
            session: Unchanged state owner.
            snapshot: Pinned rendering view.

        Returns:
            No-op feedback including effective provider semantics.
        """
        note = cls._effective_reasoning_note(
            model_name=session.active_model_name,
            active_level=session.active_reasoning_level,
            snapshot=snapshot,
        )
        return SlashCommandResultDAO(
            rendered="\n".join(filter(None, (f"reasoning already {session.active_reasoning_level}", note)))
        )

    @classmethod
    def _commit_reasoning_selection(
        cls,
        *,
        previous: ReasoningLevel,
        requested: ReasoningLevel,
        requested_token: str,
        session: SloAgentSession,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> SlashCommandResultDAO:
        """Mutate, persist and render an idle selection outside the validation catch.

        Args:
            previous: Prior canonical level.
            requested: Valid canonical level.
            requested_token: Original token for feedback.
            session: Mutation owner.
            snapshot: Pinned rendering view.

        Returns:
            Changed result requesting title refresh.

        Raises:
            RuntimeError: Session mutation rejected.
            OSError: Preference persistence failed after mutation.
        """
        active_level = session.switch_reasoning_level(reasoning_level=requested)
        UserPreferencesStore.upsert(reasoning_level=active_level)
        return cls._reasoning_change_result(
            previous_level=previous,
            requested_level=requested,
            active_level=active_level,
            requested_token=requested_token,
            model_name=session.active_model_name,
            snapshot=snapshot,
        )

    @staticmethod
    def _is_reasoning_unsupported(*, capability: ModelReasoningCapabilityDAO) -> bool:
        """Identify profiles with neither an enabled control nor explicit disable permission.

        Args:
            capability (ModelReasoningCapabilityDAO): Canonical capability for the active route.

        Returns:
            bool: Whether the route cannot accept a reasoning slash command.
        """
        return capability.supported_levels == ["off"] and not capability.reasoning_disable_available

    @staticmethod
    def _is_unpermitted_openrouter_disable(
        *, requested_token: str, capability: ModelReasoningCapabilityDAO
    ) -> bool:
        """Reject compatibility off where OpenRouter did not advertise explicit disable control.

        Args:
            requested_token (str): User-entered canonical reasoning token.
            capability (ModelReasoningCapabilityDAO): Canonical capability for the active route.

        Returns:
            bool: Whether the request would falsely promise provider-side disable.
        """
        return (
            requested_token == "off"
            and not capability.reasoning_disable_available
            and capability.reasoning_controls_available
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
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> SlashCommandResultDAO:
        """Build the result for a reasoning-level change.

        Args:
            previous_level (ReasoningLevel): Previously active level.
            requested_level (ReasoningLevel): Requested canonical level.
            active_level (ReasoningLevel): Final active level after clamping.
            requested_token (str): User-facing requested token.
            model_name (str): Active model name.
            snapshot: Session view used for validation and mutation.

        Returns:
            SlashCommandResultDAO: Render-ready reasoning change result.
        """
        text = f"reasoning changed {previous_level} -> {active_level}"
        if active_level != requested_level:
            text += f" (requested {requested_token}; clamped for {model_name})"
        note = cls._effective_reasoning_note(
            model_name=model_name, active_level=active_level, snapshot=snapshot
        )
        return SlashCommandResultDAO(rendered="\n".join(filter(None, (text, note))), refresh_title=True)

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
            return default_reasoning_level_for_model(
                model_name=session.active_model_name, snapshot=session.catalog_snapshot
            )
        if requested_token == "max":
            return highest_supported_reasoning_level(
                model_name=session.active_model_name, snapshot=session.catalog_snapshot
            )
        try:
            return parse_reasoning_level(token=requested_token)
        except ValueError as exc:
            usage: str = "usage: /reasoning <on|off|minimal|low|medium|high|xhigh|max>"
            raise ValueError(f"{exc}\n{usage}") from exc

    @staticmethod
    def _provider_default_reasoning_note(
        *, model_name: str, snapshot: Optional[ModelCatalogSnapshotDAO] = None
    ) -> str:
        """Describe unknown gateway controls from the pinned record.

        Args:
            model_name: Selected canonical route.
            snapshot: Session-owned view.

        Returns:
            Provider-default guidance only when both control kinds are unavailable.
        """
        entry = ModelCatalogService.entry_for_model(model_name=model_name, snapshot=snapshot)
        if entry.provider is not ProviderName.OPENROUTER or entry.capabilities is None:
            return ""
        if entry.capabilities.reasoning_controls_available or entry.capabilities.reasoning_disable_available:
            return ""
        return "provider default; controls unavailable"

    @staticmethod
    def _effective_reasoning_note(
        *,
        model_name: str,
        active_level: ReasoningLevel,
        snapshot: Optional[ModelCatalogSnapshotDAO] = None,
    ) -> str:
        """Explain explicit off using session policy, not a newer publication.

        Args:
            model_name: Active canonical model.
            active_level: Operator-selected level.
            snapshot: Pinned session view.

        Returns:
            Effective effort note, or empty for ordinary enabled/legacy states.
        """
        if active_level != "off":
            return ""
        resolved = resolve_reasoning_config(
            model_name=model_name, requested_level=active_level, snapshot=snapshot
        )
        if resolved.provider_effort is None:
            return ""
        label = "reasoning required" if resolved.enabled else "disabled"
        return f"effective provider effort: {resolved.provider_effort} ({label})"

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
            snapshot=session.catalog_snapshot,
        )
        supported_levels = cls._provider_default_reasoning_note(
            model_name=session.active_model_name, snapshot=session.catalog_snapshot
        ) or cls._render_supported_reasoning_levels(capability=capability)
        note = cls._effective_reasoning_note(
            model_name=session.active_model_name,
            active_level=session.active_reasoning_level,
            snapshot=session.catalog_snapshot,
        )
        text = (
            f"model: {session.active_model_name}\n"
            f"reasoning: {session.active_reasoning_level}\n"
            f"supported: {supported_levels}"
        )
        return "\n".join(filter(None, (text, note)))

    @staticmethod
    def _render_supported_reasoning_levels(*, capability: ModelReasoningCapabilityDAO) -> str:
        """Render the supported-levels line for one model capability.

        Args:
            capability (ModelReasoningCapabilityDAO): Capability to render.

        Returns:
            str: Human-readable supported-levels value.
        """
        if capability.reasoning_disable_available and capability.supported_levels == ["off"]:
            return "off (reasoning disable supported)"
        if capability.reasoning_controls_available and not capability.reasoning_disable_available:
            levels = ", ".join(level for level in capability.supported_levels if level != "off")
            return f"{levels} (provider default; disable unavailable)"
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
        reasoning_line: str = f"  reasoning: {prefs.default_reasoning_level or '(none — uses model default)'}"
        return SlashCommandResultDAO(
            rendered=f"Saved preferences:\n{model_line}\n{reasoning_line}",
        )

    @classmethod
    async def _handle_workflows(
        cls,
        *,
        rest: str,
        session: SloAgentSession,
    ) -> SlashCommandResultDAO:
        """List, abort, dismiss, or resume detached workflows.

        Deliberately does NOT self-guard on ``session.is_running`` — listing
        and aborting while the main lane is busy is a primary use case. Every
        outcome (including unknown ids and illegal transitions) is rendered as
        transcript text; nothing raises to the dispatcher.

        Args:
            rest (str): Trailing argument text — empty for list, or
                ``abort <workflow-id>``, ``dismiss <workflow-id>``, or
                ``resume <workflow-id>``.
            session (SloAgentSession): Session whose workflows are managed.

        Returns:
            SlashCommandResultDAO: Result with the listing, a confirmation,
                or an error/usage line.
        """
        if session.history_root is None:
            return SlashCommandResultDAO(
                rendered="workflows unavailable — history is disabled for this session",
            )
        service: WorkflowCommandService = WorkflowCommandService(
            store=WorkflowHandleStore(history_root=session.history_root),
            owner_session_id=session.session_id,
        )
        subcommand, _, workflow_id = rest.strip().partition(" ")
        workflow_id = workflow_id.strip()
        if not subcommand:
            return SlashCommandResultDAO(rendered=await service.list_text())
        if subcommand == "abort" and workflow_id:
            return SlashCommandResultDAO(rendered=await service.abort(workflow_id=workflow_id))
        if subcommand == "dismiss" and workflow_id:
            return cls._workflow_command_result(result=await service.dismiss_result(workflow_id=workflow_id))
        if subcommand == "resume" and workflow_id:
            return cls._workflow_command_result(result=await service.resume_result(workflow_id=workflow_id))
        return SlashCommandResultDAO(
            rendered="usage: /workflows [abort <workflow-id> | dismiss <workflow-id> | resume <workflow-id>]",
        )

    @staticmethod
    def _workflow_command_result(*, result: WorkflowCommandResultDAO) -> SlashCommandResultDAO:
        """Carry a typed dismiss/resume outcome to the TUI without parsing its text.

        Args:
            result (WorkflowCommandResultDAO): Command service outcome.

        Returns:
            SlashCommandResultDAO: Transcript text plus the typed observation signal.
        """
        return SlashCommandResultDAO(
            rendered=result.rendered,
            dismissed_workflow_id=result.dismissed_workflow_id,
            resumed_workflow_id=result.resumed_workflow_id,
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
