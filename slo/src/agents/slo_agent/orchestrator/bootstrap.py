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

import config.cfg as cfg_module
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__ = ["OrchestratorSessionBootstrap"]


class OrchestratorSessionBootstrap:
    """Promote a ``SloAgentSession`` to orchestrator mode.

    Builds a ``SubAgentPool``, wraps it in the ``spawn_sub_agents`` LangChain
    tool, adds the detached-workflow tools (``launch_workflow`` /
    ``workflow_status``, spec 57) unless the ``SLO_DETACHED_WORKFLOWS`` kill
    switch is off, and calls ``session.attach_sub_agent_pool(pool=pool,
    spawn_tools=[…])``.

    The caller must hold the session in a pre-prompt state — the underlying
    ``attach_sub_agent_pool`` method raises ``RuntimeError`` if the lazy agent
    has already been built.
    """

    @classmethod
    def attach(cls, *, session: "SloAgentSession", headless: bool = False) -> None:  # type: ignore[name-defined]
        """Attach a ``SubAgentPool`` and the orchestrator tools to ``session``.

        No-ops when the session already has a built agent (e.g. a test session
        constructed with a ``FauxChatModel`` injected directly) or already has a
        pool attached, so the method is safe to call unconditionally at startup.

        Args:
            session: Session to promote to orchestrator mode. Must be in a
                pre-prompt state — i.e. the lazy agent must not have been
                built yet.
            headless (bool): True when promoting a headless ``slo run
                --orchestrator`` session; withholds the detached-workflow tools
                so a detached orchestrator can never recurse. Defaults to
                ``False`` (TUI path — all three tools).
        """
        if cls._already_has_agent(session=session):
            return
        if cls._already_has_pool(session=session):
            return
        session_id: str = session.session_id
        permitted: bool = session._begin_standard_orchestrator_attachment()
        policy_sources = session._snapshot_herdr_policy_sources() if permitted else None
        pool: SubAgentPool = cls._build_pool(session=session)
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        extra_tools: list[BaseTool] = [spawn_tool] + cls._build_workflow_tools(
            session=session,
            headless=headless,
        )
        permitted = (
            permitted
            and session._begin_standard_orchestrator_attachment()
            and session._herdr_policy_sources_match(expected=policy_sources)
            and session.session_id == session_id
        )
        session._attach_sub_agent_pool(pool=pool, spawn_tools=extra_tools)
        session._finish_standard_orchestrator_attachment(
            permitted=(
                permitted
                and session._herdr_policy_sources_match(expected=policy_sources)
                and session.session_id == session_id
            ),
            expected_tools=tuple(extra_tools),
        )

    # ── private helpers ──────────────────────────────────────────────────────

    @classmethod
    def _build_workflow_tools(
        cls,
        *,
        session: "SloAgentSession",
        headless: bool = False,
    ) -> list[BaseTool]:
        """Build the detached-workflow tools when the kill switch allows them.

        Both tools share one ``WorkflowHandleStore`` bound to the default
        history root so the launch tool and the status tool always agree on
        handle state.

        Args:
            session (SloAgentSession): Owning session providing its id and
                active model.
            headless (bool): True when promoting a headless ``slo run
                --orchestrator`` session; withholds the detached-workflow tools
                so a detached orchestrator can never recurse.

        Returns:
            list[BaseTool]: ``[launch_workflow, workflow_status]`` when
                ``SLO_DETACHED_WORKFLOWS`` is enabled and ``headless`` is
                ``False``, else an empty list.
        """
        if headless:
            return []
        if not cfg_module.DETACHED_WORKFLOWS:
            return []
        from src.agents.slo_agent.history.filesystem_store import (  # noqa: PLC0415
            default_history_root,
        )
        from src.agents.slo_agent.orchestrator.launch_tool import (  # noqa: PLC0415
            LaunchWorkflowTool,
        )
        from src.agents.slo_agent.orchestrator.workflow_registry import (  # noqa: PLC0415
            WorkflowHandleStore,
            WorkflowStatusTool,
        )

        store: WorkflowHandleStore = WorkflowHandleStore(history_root=default_history_root())
        return [
            LaunchWorkflowTool.build(
                owner_session_id=session.session_id,
                default_model=session.active_model_name,
                handle_store=store,
            ),
            WorkflowStatusTool.build(owner_session_id=session.session_id, store=store),
        ]

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
