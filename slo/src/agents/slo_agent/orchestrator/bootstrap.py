"""OrchestratorSessionBootstrap — shared session promotion to orchestrator mode.

Extracted from ``SloTUI._attach_pool_to_session`` so both the TUI and the
headless ``slo run --orchestrator`` path share the identical promotion logic.

Call sites:

- ``SloTUI._attach_pool_to_session()`` (TUI startup and ``/new`` flows)
- ``HeadlessRunner.invoke()`` when ``orchestrator_mode=True``

Sub-spec 53.a.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__ = ["OrchestratorSessionBootstrap"]


class OrchestratorSessionBootstrap:
    """Promote a ``SloAgentSession`` to orchestrator mode.

    Builds a ``SubAgentPool``, wraps it in the ``spawn_sub_agents`` LangChain
    tool, and calls ``session.attach_sub_agent_pool(pool=pool, spawn_tool=spawn_tool)``.

    The caller must hold the session in a pre-prompt state — the underlying
    ``attach_sub_agent_pool`` method raises ``RuntimeError`` if the lazy agent
    has already been built.
    """

    @classmethod
    def attach(cls, *, session: "SloAgentSession") -> None:  # type: ignore[name-defined]
        """Attach a ``SubAgentPool`` and the ``spawn_sub_agents`` tool to ``session``.

        No-ops when the session already has a built agent (e.g. a test session
        constructed with a ``FauxChatModel`` injected directly) or already has a
        pool attached, so the method is safe to call unconditionally at startup.

        Args:
            session: Session to promote to orchestrator mode. Must be in a
                pre-prompt state — i.e. the lazy agent must not have been
                built yet.
        """
        if cls._already_has_agent(session=session):
            return
        if cls._already_has_pool(session=session):
            return
        pool: SubAgentPool = cls._build_pool(session=session)
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        session.attach_sub_agent_pool(pool=pool, spawn_tool=spawn_tool)

    # ── private helpers ──────────────────────────────────────────────────────

    @classmethod
    def _already_has_agent(cls, *, session: SloAgentSession) -> bool:
        """Return ``True`` when the session's lazy agent has already been built.

        Sessions with a pre-built agent cannot accept pool attachment after
        construction — attaching would be a no-op because the tool list was
        already baked into the agent at build time.

        Args:
            session (SloAgentSession): Session to inspect.

        Returns:
            bool: ``True`` if the session's ``_agent`` attribute is not ``None``.
        """
        return getattr(session, "_agent", None) is not None

    @classmethod
    def _already_has_pool(cls, *, session: SloAgentSession) -> bool:
        """Return ``True`` when the session already has a ``SubAgentPool`` attached.

        Prevents double-attachment when ``attach()`` is called more than once on
        the same session (e.g. from both TUI boot and ``_start_new_session``).

        Args:
            session (SloAgentSession): Session to inspect.

        Returns:
            bool: ``True`` if the session's ``_sub_agent_pool`` attribute is not
                ``None``.
        """
        return getattr(session, "_sub_agent_pool", None) is not None

    @classmethod
    def _build_pool(cls, *, session: SloAgentSession) -> SubAgentPool:
        """Build a ``SubAgentPool`` bound to ``session``.

        Args:
            session (SloAgentSession): The orchestrator session; provides its id,
                active model, event relay, and assembled system prompt to the pool.

        Returns:
            SubAgentPool: A fresh pool for this session.
        """
        return SubAgentPool(
            orchestrator_session_id=session.session_id,
            default_model=session.active_model_name,
            relay=session.event_relay,
            child_system_prompt=session._assembled_system_prompt(),
        )
