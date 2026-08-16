"""Pydantic DAOs for ``SloAgentSession`` — sessions/dao.py.

Canonical location for ``SessionConfigDAO`` and the
``AgentEventSubscriber`` type alias. Moved from the top-level
``session_dao.py`` as part of the sessions/ submodule (spec 04).
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Literal, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.hooks import Hook, ShouldStopAfterTurnHook
from src.agents.providers.model_pool import ModelPoolDAO
from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.reasoning_capabilities import ReasoningLevel

__all__ = [
    "AgentEventSubscriber",
    "ContextWindowSnapshotDAO",
    "ManualCompactionResultDAO",
    "ManualCompactionStatus",
    "SessionConfigDAO",
]


AgentEventSubscriber = Callable[[AgentStreamEventDAO], Awaitable[None]]
"""Async callable invoked once per ``AgentStreamEventDAO`` the session yields."""

ManualCompactionStatus = Literal["compacted", "nothing_to_compact", "unavailable", "failed"]
"""Terminal states of one operator-requested Manual Compaction."""


class ManualCompactionResultDAO(BaseModel):
    """Typed operator outcome for one Manual Compaction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ManualCompactionStatus
    context_window_snapshot: Optional[ContextWindowSnapshotDAO] = None
    detail: Optional[str] = None


class SessionConfigDAO(BaseModel):
    """Caller-supplied config for ``SloAgentSession.build``.

    Fields:
        workdir (Path): Resolved absolute workdir the agent operates in.
        model_name (Optional[str]): Identifier forwarded to
            ``LLMFactory.create``. ``None`` falls back to
            ``cfg("DEFAULT_MODEL_NAME")`` at the call site.
        reasoning_level (Optional[ReasoningLevel]): Optional startup
            override for the seeded active reasoning level. ``None``
            uses the model's default seeded level.
        system_prompt (Optional[str]): Overrides the prompt builder when
            present. ``None`` uses the runtime ``SystemPromptBuilder``.
        should_stop_after_turn_hook (Optional[ShouldStopAfterTurnHook]):
            Custom stop hook. ``None`` falls back to
            ``Hook.should_stop_after_turn_hook`` (the never-stop default).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workdir: Path
    model_name: Optional[str] = None
    model_pool_dao: Optional["ModelPoolDAO"] = None
    """Optional priority-ordered model pool. When set, the session builds a
    ``ModelPool`` (multi-model fallback) instead of a single model. ``None``
    keeps the single-model path. The first entry's model name should match
    ``model_name`` so title/usage have a stable configured identity."""
    reasoning_level: Optional[ReasoningLevel] = None
    system_prompt: Optional[str] = None
    should_stop_after_turn_hook: Optional[ShouldStopAfterTurnHook] = Field(default=None)
    workspace_file: Optional[Path] = None
    """Optional VSCode ``.code-workspace`` file to load additive context from."""
    session_id: Optional[str] = None
    """Explicit session id for resume. ``None`` triggers a fresh UUID4."""
    history_root: Optional[Path] = None
    """Override root for persisted history. ``None`` resolves to
    ``~/.slo/sessions/history`` via ``default_history_root``."""
    enable_history: bool = True
    """Persistent session history is on by default (sub-spec 05.c)."""
    extra_tools: Optional[list[BaseTool]] = Field(default=None)
    """Optional additional tools merged into the agent's tool bundle at build time.

    Used to inject the ``spawn_sub_agents`` tool for orchestrator sessions.
    Any provided tools are appended after the standard extended bundle so the
    base 9-tool set is always available.
    """
    append_system_prompt: Optional[str] = None
    """Optional text appended to the base system prompt at agent build time.

    Set by ``SloAgentSession.attach_sub_agent_pool()`` to inject the
    orchestrator constraint addendum so the LLM only calls
    ``spawn_sub_agents`` on explicit user request.
    """
    fallback_notice: Optional[str] = None
    """Operator-visible notice when the requested model was invalid and a
    fallback model was selected. Rendered once by the TUI on startup.
    """

    @model_validator(mode="after")
    def _align_model_name_with_pool_primary(self) -> "SessionConfigDAO":
        """Force ``model_name`` to the pool's primary when a pool is configured.

        The configured identity, startup copy, and pool primary must agree (the
        ``model_pool_dao`` docstring's invariant). ``model_name`` is often
        resolved independently of the pool at the construction sites, so this
        validator makes the first pool entry authoritative whenever a pool is set.

        Returns:
            SessionConfigDAO: ``self``, with ``model_name`` aligned to the pool
                primary when ``model_pool_dao`` is present.
        """
        if self.model_pool_dao is not None and self.model_pool_dao.entries:
            self.model_name = self.model_pool_dao.entries[0].model_name
        return self

    def resolved_history_root(self) -> Path:
        """Return the configured history root or the default.

        Returns:
            Path: Resolved absolute history root directory.
        """
        return self.history_root or default_history_root()

    def history_enabled(self) -> bool:
        """Return whether persisted history is enabled for this session.

        Returns:
            bool: True when canonical on-disk history should be used.
        """
        return self.enable_history

    def resolved_stop_hook(self) -> ShouldStopAfterTurnHook:
        """Return the supplied hook, or the default if ``None``.

        Returns:
            ShouldStopAfterTurnHook: A non-``None`` hook callable.
        """
        return self.should_stop_after_turn_hook or Hook.should_stop_after_turn_hook
