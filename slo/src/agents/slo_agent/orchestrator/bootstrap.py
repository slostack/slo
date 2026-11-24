"""OrchestratorSessionBootstrap — shared session promotion to orchestrator mode.

Extracted from ``SloTUI._attach_pool_to_session`` so both the TUI and the
headless ``slo run --orchestrator`` path share the identical promotion logic.

Call sites:

- ``SloTUI._attach_pool_to_session()`` (TUI startup and ``/new`` flows)
- ``HeadlessRunner.invoke()`` when ``orchestrator_mode=True``

Sub-spec 53.a.3.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from langchain_core.tools import BaseTool

import config.cfg as cfg_module
from src.agents.slo_agent.channel_delivery.policy import MessagingPolicy
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.channel_delivery.send_tool import SendMessageTool
from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.spawn_tool import PendingChannelNotes, SpawnSubAgentsTool

if TYPE_CHECKING:
    from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.channels.gateway import ChannelGateway

__all__ = ["OrchestratorSessionBootstrap"]


class OrchestratorSessionBootstrap:
    """Promote a ``SloAgentSession`` to orchestrator mode.

    Builds a ``SubAgentPool``, wraps it in the ``spawn_sub_agents`` LangChain
    tool, adds the detached-workflow tools (``launch_workflow`` /
    ``workflow_status``, spec 57) unless the ``SLO_DETACHED_WORKFLOWS`` kill
    switch is off, adds ``send_message`` (108.4) when a channel gateway is
    supplied, and calls ``session.attach_sub_agent_pool(pool=pool,
    spawn_tools=[…])``.

    The caller must hold the session in a pre-prompt state — the underlying
    ``attach_sub_agent_pool`` method raises ``RuntimeError`` if the lazy agent
    has already been built.
    """

    @classmethod
    def attach(  # type: ignore[name-defined]
        cls,
        *,
        session: "SloAgentSession",
        headless: bool = False,
        owner_session_id: Optional[str] = None,
        channel_gateway: Optional["ChannelGateway"] = None,
    ) -> None:
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
            owner_session_id (Optional[str]): Owner identity bound into the pool.
                Headless runs pass the notifier launch owner; None resolves to the
                session's own id (normal TUI path). Never taken from a request.
            channel_gateway (Optional[ChannelGateway]): Shared channel queue
                (108.4), owned and opened by the caller. When given, the pool
                closes children that die without closing, ``spawn_sub_agents``
                reports ``channel_notes_pending`` and ``send_message`` is bound
                to this session. ``None`` keeps the pre-108.4 tool bundle.
        """
        if cls._already_has_agent(session=session):
            return
        if cls._already_has_pool(session=session):
            return
        session_id: str = session.session_id
        permitted: bool = session._begin_standard_orchestrator_attachment()
        policy_sources = session._snapshot_herdr_policy_sources() if permitted else None
        pool: SubAgentPool = cls._build_pool(
            session=session,
            owner_session_id=owner_session_id or session.session_id,
            channel_gateway=channel_gateway,
        )
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(
            pool=pool,
            channel_notes=(
                PendingChannelNotes(gateway=channel_gateway, recipient_session_id=session.session_id)
                if channel_gateway is not None
                else None
            ),
        )
        extra_tools: list[BaseTool] = (
            [spawn_tool]
            + cls._build_workflow_tools(session=session, headless=headless)
            + cls._build_messaging_tools(
                session=session,
                pool=pool,
                channel_gateway=channel_gateway,
                headless=headless,
            )
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
    def _build_handle_store(cls, *, headless: bool) -> Optional["WorkflowHandleStore"]:
        """Return the detached-workflow handle store when the workflow tools are enabled.

        Args:
            headless (bool): True for a headless orchestrator, which never gets
                the detached-workflow tools so it can never recurse.

        Returns:
            Optional[WorkflowHandleStore]: A store on the default history root,
                or ``None`` when headless or ``SLO_DETACHED_WORKFLOWS`` is off.
        """
        if headless or not cfg_module.DETACHED_WORKFLOWS:
            return None
        # Resolved at call time from its source module (tests redirect it there).
        from src.agents.slo_agent.history import filesystem_store  # noqa: PLC0415
        from src.agents.slo_agent.orchestrator.workflow_registry import (  # noqa: PLC0415
            WorkflowHandleStore,
        )

        return WorkflowHandleStore(history_root=filesystem_store.default_history_root())

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
                active model and reasoning snapshots. Later setting changes or
                pending preparation do not refresh the bound launch defaults.
            headless (bool): True when promoting a headless ``slo run
                --orchestrator`` session; withholds the detached-workflow tools
                so a detached orchestrator can never recurse.

        Returns:
            list[BaseTool]: ``[launch_workflow, workflow_status]`` when
                ``SLO_DETACHED_WORKFLOWS`` is enabled and ``headless`` is
                ``False``, else an empty list.
        """
        store: Optional["WorkflowHandleStore"] = cls._build_handle_store(headless=headless)
        if store is None:
            return []
        from src.agents.slo_agent.orchestrator.launch_tool import (  # noqa: PLC0415
            LaunchWorkflowTool,
        )
        from src.agents.slo_agent.orchestrator.workflow_registry import (  # noqa: PLC0415
            WorkflowStatusTool,
        )

        return [
            LaunchWorkflowTool.build(
                owner_session_id=session.session_id,
                default_model=session.active_model_name,
                default_reasoning_level=session.active_reasoning_level,
                handle_store=store,
            ),
            WorkflowStatusTool.build(owner_session_id=session.session_id, store=store),
        ]

    @classmethod
    def _build_messaging_tools(
        cls,
        *,
        session: "SloAgentSession",
        pool: SubAgentPool,
        channel_gateway: Optional["ChannelGateway"],
        headless: bool,
    ) -> list[BaseTool]:
        """Build ``send_message`` for an orchestrator session (108.4 §5).

        The orchestrator may message its own children (task-id aliases from
        the pool's child directory) and, in the TUI, the workflows it launched
        (read from the same handle files the workflow tools write).

        Args:
            session (SloAgentSession): The orchestrator session (the sender).
            pool (SubAgentPool): The session's pool, source of the child directory.
            channel_gateway (Optional[ChannelGateway]): Shared queue, or ``None``.
            headless (bool): True for a headless orchestrator, which launches
                no workflows.

        Returns:
            list[BaseTool]: ``[send_message]``, or an empty list without a gateway.
        """
        if channel_gateway is None:
            return []
        self_id: UUID = channel_participant_id_for_session(session_id=session.session_id)
        policy: MessagingPolicy = MessagingPolicy(
            self_id=self_id,
            parent_id=None,
            children=pool.child_directory,
            launched_workflows=cls._launched_workflows_reader(
                handle_store=cls._build_handle_store(headless=headless),
                owner_session_id=session.session_id,
            ),
        )
        return [SendMessageTool.build(gateway=channel_gateway, policy=policy, self_id=self_id)]

    @staticmethod
    def _launched_workflows_reader(
        *,
        handle_store: Optional["WorkflowHandleStore"],
        owner_session_id: str,
    ) -> Callable[[], list[UUID]]:
        """Return a reader of the orchestrator participant ids this session launched.

        Args:
            handle_store (Optional[WorkflowHandleStore]): Launched-workflow handles.
            owner_session_id (str): The launching session.

        Returns:
            Callable[[], list[UUID]]: Reads the handles on every call; always
                empty without a store.
        """
        if handle_store is None:
            return lambda: []
        store: "WorkflowHandleStore" = handle_store
        return lambda: [
            channel_participant_id_for_session(session_id=orchestrator_session_id)
            for orchestrator_session_id in store.launched_orchestrator_session_ids(
                owner_session_id=owner_session_id
            )
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
    def _build_pool(
        cls,
        *,
        session: SloAgentSession,
        owner_session_id: str,
        channel_gateway: Optional["ChannelGateway"] = None,
    ) -> SubAgentPool:
        """Build a ``SubAgentPool`` bound to ``session`` and its immutable identities.

        WHAT: The sole normal pool composition owner. Resolves the owner, a fresh
            run UUID (new on every composition, including a resumed runner) and the
            session's history root (default root when history is disabled).
        WHO: Called only by ``attach``.
        WHEN: Once per session promotion to orchestrator mode.

        Args:
            session (SloAgentSession): The orchestrator session; provides its id,
                active model, event relay, history root and assembled system prompt.
            owner_session_id (str): Resolved owner identity for this composition.
            channel_gateway (Optional[ChannelGateway]): Shared queue the pool
                uses to close children that died without closing (108.4 C5).

        Returns:
            SubAgentPool: A fresh pool for this session.
        """
        history_root: Optional[Path] = session.history_root
        return SubAgentPool(
            orchestrator_session_id=session.session_id,
            default_model=session.active_model_name,
            relay=session.event_relay,
            owner_session_id=owner_session_id,
            run_id=str(uuid4()),
            history_root=history_root if history_root is not None else default_history_root(),
            child_system_prompt=session._assembled_system_prompt(),
            channel_gateway=channel_gateway,
        )
