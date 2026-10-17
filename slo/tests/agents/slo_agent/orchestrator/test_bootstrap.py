"""Tests for ``OrchestratorSessionBootstrap`` (sub-spec 53.a.3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.reasoning_capabilities import ReasoningLevel

from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_session(
    *,
    agent=None,
    sub_agent_pool=None,
    session_id: str = "sess-001",
    active_model_name: str = "claude-sonnet-4-6",
    active_reasoning_level: ReasoningLevel = "off",
    assembled_system_prompt: str = "child-system-prompt",
) -> MagicMock:
    """Build a minimal ``SloAgentSession`` mock.

    Args:
        agent: Value to return from ``_agent`` attribute (None = not yet built).
        sub_agent_pool: Value to return from ``_sub_agent_pool`` attribute.
        session_id (str): Session id for the mock.
        active_model_name (str): Active model name for the mock.
        active_reasoning_level (ReasoningLevel): Concrete canonical snapshot.
        assembled_system_prompt (str): Value returned by ``_assembled_system_prompt``.

    Returns:
        MagicMock: A session mock with the requested attribute state.
    """
    session: MagicMock = MagicMock()
    session._agent = agent
    session._sub_agent_pool = sub_agent_pool
    session.session_id = session_id
    session.active_model_name = active_model_name
    session.active_reasoning_level = active_reasoning_level
    session.event_relay = MagicMock()
    session._assembled_system_prompt = MagicMock(return_value=assembled_system_prompt)
    return session


# ── tests ─────────────────────────────────────────────────────────────────────


async def test_pending_session_snapshot_is_not_effective_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline startup adoption does not replace a provisional launch snapshot."""
    from unittest.mock import AsyncMock
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.model_catalog.service import ModelCatalogService
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool

    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    route = "openrouter:author/cold"
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(update={"model_name": route})
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, route: entry}})
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name=route, enable_history=False),
        allow_pending_preparation=True,
    )
    assert session.active_reasoning_level == "off"
    OrchestratorSessionBootstrap.attach(session=session)
    launch = next(tool for tool in session.orchestration_tools if tool.name == "launch_workflow")
    with patch.object(ModelCatalogService, "prepare_models", new=AsyncMock(return_value=snapshot)) as prepare:
        await session.prepare_startup()
        assert session.preparation_status == "ready"
        prepare.assert_awaited_once()
        prepare.reset_mock()
        with patch.object(LaunchWorkflowTool, "_launch", new_callable=AsyncMock, return_value="{}") as invoke:
            await launch.ainvoke({"brief": "bounded"})
            assert invoke.call_args.kwargs["reasoning_level"] == "off"
            await launch.ainvoke({"brief": "bounded", "reasoning_level": "high"})
            assert invoke.call_args.kwargs["reasoning_level"] == "high"
        prepare.assert_not_called()
    assert session._config is not None and session._config.extra_tools is not None
    assert any(tool is launch for tool in session._config.extra_tools)
    assert session._sub_agent_pool is not None
    await session._sub_agent_pool.abort_and_drain()


async def test_reasoning_snapshot_survives_session_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real switching and lazy rebuilding retain the original tool object/defaults."""
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from unittest.mock import AsyncMock

    from src.auth.credential_store import CredentialStore
    from src.auth.credential_dao import CredentialDAO, ProviderName, AuthType

    for provider in (ProviderName.OPENAI, ProviderName.KIMI_FOR_CODING):
        CredentialStore().persist(
            cred=CredentialDAO(
                provider=provider, auth_type=AuthType.API_KEY, access_token="synthetic-test-key"
            )
        )
    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low", enable_history=False
        )
    )
    OrchestratorSessionBootstrap.attach(session=session)
    launch = next(tool for tool in session.orchestration_tools if tool.name == "launch_workflow")
    session.switch_reasoning_level(reasoning_level="high")
    session.switch_model(model_name="kimi-k3")
    with patch.object(LaunchWorkflowTool, "_launch", new_callable=AsyncMock, return_value="{}") as invoke:
        await launch.ainvoke({"brief": "bounded"})
        assert invoke.call_args.kwargs["model"] == "gpt-5.4"
        assert invoke.call_args.kwargs["reasoning_level"] == "low"
        await launch.ainvoke({"brief": "bounded", "model": "kimi-k3", "reasoning_level": "medium"})
        assert invoke.call_args.kwargs["model"] == "kimi-k3"
        assert invoke.call_args.kwargs["reasoning_level"] == "medium"
    with patch(
        "src.agents.slo_agent.graph.service.LLMFactory.create",
        return_value=LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False),
    ) as factory:
        await session._ensure_agent_ready()
    assert factory.call_args.kwargs["model_name"] == "kimi-k3"
    assert factory.call_args.kwargs["reasoning_level"] == "high"
    assert session._config is not None and session._config.extra_tools is not None
    assert any(tool is launch for tool in session._config.extra_tools)
    assert session._sub_agent_pool is not None
    await session._sub_agent_pool.abort_and_drain()


async def test_replacement_session_binds_new_reasoning_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual /new configuration path binds a new identity and active level."""
    from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.tui.app import SloTUI
    from unittest.mock import AsyncMock

    monkeypatch.setenv("SLO_PLUGINS_DISABLED", "1")
    old = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", reasoning_level="low", enable_history=False
        )
    )
    OrchestratorSessionBootstrap.attach(session=old)
    old.switch_reasoning_level(reasoning_level="high")
    new = SloAgentSession.build(config=SloTUI._build_replacement_session_config(old_session=old))
    OrchestratorSessionBootstrap.attach(session=new)
    launch = next(tool for tool in new.orchestration_tools if tool.name == "launch_workflow")
    assert new.session_id != old.session_id
    assert all(tool is not launch for tool in old.orchestration_tools)
    with patch.object(LaunchWorkflowTool, "_launch", new_callable=AsyncMock, return_value="{}") as invoke:
        await launch.ainvoke({"brief": "bounded"})
    assert invoke.call_args.kwargs["owner_session_id"] == new.session_id
    assert invoke.call_args.kwargs["reasoning_level"] == new.active_reasoning_level == "high"
    assert old._sub_agent_pool is not None and new._sub_agent_pool is not None
    await old._sub_agent_pool.abort_and_drain()
    await new._sub_agent_pool.abort_and_drain()


class TestOrchestratorSessionBootstrapAttach:
    """``OrchestratorSessionBootstrap.attach`` promotes sessions to orchestrator mode."""

    def test_attach_calls_session_attach_sub_agent_pool(self) -> None:
        """Successful attach calls ``session.attach_sub_agent_pool`` with the tool list."""
        session: MagicMock = _make_session()

        with (
            patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool") as MockPool,
            patch("src.agents.slo_agent.orchestrator.bootstrap.SpawnSubAgentsTool") as MockTool,
            patch.object(
                OrchestratorSessionBootstrap,
                "_build_workflow_tools",
                return_value=[],
            ),
        ):
            mock_pool = MagicMock()
            MockPool.return_value = mock_pool
            mock_spawn_tool = MagicMock()
            MockTool.build.return_value = mock_spawn_tool

            OrchestratorSessionBootstrap.attach(session=session)

        session.attach_sub_agent_pool.assert_called_once_with(
            pool=mock_pool,
            spawn_tools=[mock_spawn_tool],
        )

    def test_attach_builds_pool_with_session_identity(self) -> None:
        """Pool is constructed with the session id, model, and event relay."""
        session: MagicMock = _make_session(
            session_id="my-session",
            active_model_name="gpt-5.4",
        )

        with (
            patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool") as MockPool,
            patch("src.agents.slo_agent.orchestrator.bootstrap.SpawnSubAgentsTool"),
        ):
            OrchestratorSessionBootstrap.attach(session=session)

        MockPool.assert_called_once_with(
            orchestrator_session_id="my-session",
            default_model="gpt-5.4",
            relay=session.event_relay,
            child_system_prompt=session._assembled_system_prompt(),
        )

    def test_attach_is_noop_when_agent_already_built(self) -> None:
        """No pool is built when the session's lazy agent already exists."""
        agent_stub: MagicMock = MagicMock()
        session: MagicMock = _make_session(agent=agent_stub)

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool") as MockPool:
            OrchestratorSessionBootstrap.attach(session=session)

        MockPool.assert_not_called()
        session.attach_sub_agent_pool.assert_not_called()

    def test_attach_is_noop_when_pool_already_attached(self) -> None:
        """No pool is built when ``_sub_agent_pool`` is already set."""
        existing_pool: MagicMock = MagicMock()
        session: MagicMock = _make_session(sub_agent_pool=existing_pool)

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool") as MockPool:
            OrchestratorSessionBootstrap.attach(session=session)

        MockPool.assert_not_called()
        session.attach_sub_agent_pool.assert_not_called()

    def test_attach_builds_spawn_tool_from_pool(self) -> None:
        """``SpawnSubAgentsTool.build`` is called with the freshly created pool."""
        session: MagicMock = _make_session()

        with (
            patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool") as MockPool,
            patch("src.agents.slo_agent.orchestrator.bootstrap.SpawnSubAgentsTool") as MockTool,
        ):
            mock_pool = MagicMock()
            MockPool.return_value = mock_pool

            OrchestratorSessionBootstrap.attach(session=session)

        MockTool.build.assert_called_once_with(pool=mock_pool)


class TestOrchestratorSessionBootstrapWorkflowTools:
    """Detached-workflow tool registration and the kill switch (spec 57.a.2)."""

    def test_attach_registers_three_tools_when_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With detached workflows enabled the tool list is spawn + launch + status."""
        import config.cfg as cfg_module

        monkeypatch.setattr(cfg_module, "DETACHED_WORKFLOWS", True)
        session: MagicMock = _make_session()

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"):
            OrchestratorSessionBootstrap.attach(session=session)

        spawn_tools = session.attach_sub_agent_pool.call_args.kwargs["spawn_tools"]
        assert [tool.name for tool in spawn_tools] == [
            "spawn_sub_agents",
            "launch_workflow",
            "workflow_status",
        ]

    def test_attach_registers_only_spawn_tool_when_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``SLO_DETACHED_WORKFLOWS=0`` restores the spawn-only tool bundle."""
        import config.cfg as cfg_module

        monkeypatch.setattr(cfg_module, "DETACHED_WORKFLOWS", False)
        session: MagicMock = _make_session()

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"):
            OrchestratorSessionBootstrap.attach(session=session)

        spawn_tools = session.attach_sub_agent_pool.call_args.kwargs["spawn_tools"]
        assert [tool.name for tool in spawn_tools] == ["spawn_sub_agents"]

    def test_workflow_tools_bound_to_session_identity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The launch tool receives the session id and active model."""
        import config.cfg as cfg_module

        monkeypatch.setattr(cfg_module, "DETACHED_WORKFLOWS", True)
        session: MagicMock = _make_session(
            session_id="owner-1",
            active_model_name="gpt-5.4",
            active_reasoning_level="medium",
        )

        with (
            patch("src.agents.slo_agent.orchestrator.launch_tool.LaunchWorkflowTool.build") as mock_build,
            patch(
                "src.agents.slo_agent.orchestrator.workflow_registry.WorkflowStatusTool.build"
            ) as status_build,
        ):
            mock_build.return_value = MagicMock(name="launch_workflow")
            OrchestratorSessionBootstrap._build_workflow_tools(session=session)
        assert mock_build.call_args.kwargs["handle_store"] is status_build.call_args.kwargs["store"]

        assert mock_build.call_args.kwargs["owner_session_id"] == "owner-1"
        assert mock_build.call_args.kwargs["default_model"] == "gpt-5.4"
        assert mock_build.call_args.kwargs["default_reasoning_level"] == "medium"

    def test_attach_headless_registers_only_spawn_tool(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Headless promotion with DETACHED_WORKFLOWS=True yields exactly [spawn_sub_agents].

        The structural guard must withhold ``launch_workflow`` and
        ``workflow_status`` from a detached headless orchestrator even when the
        kill switch is on, so the orchestrator can never recurse.
        """
        import config.cfg as cfg_module

        monkeypatch.setattr(cfg_module, "DETACHED_WORKFLOWS", True)
        session: MagicMock = _make_session()

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"):
            OrchestratorSessionBootstrap.attach(session=session, headless=True)

        spawn_tools: list = session.attach_sub_agent_pool.call_args.kwargs["spawn_tools"]
        assert [tool.name for tool in spawn_tools] == ["spawn_sub_agents"]

    def test_attach_tui_default_keeps_three_tools(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """TUI promotion (headless omitted) still exposes all three orchestration tools.

        Guards the sync/TUI surface against regression: an unqualified
        ``attach(session=…)`` call must keep the full bundle of
        ``spawn_sub_agents``, ``launch_workflow``, and ``workflow_status``.
        """
        import config.cfg as cfg_module

        monkeypatch.setattr(cfg_module, "DETACHED_WORKFLOWS", True)
        session: MagicMock = _make_session()

        with patch("src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"):
            OrchestratorSessionBootstrap.attach(session=session)

        spawn_tools: list = session.attach_sub_agent_pool.call_args.kwargs["spawn_tools"]
        assert [tool.name for tool in spawn_tools] == [
            "spawn_sub_agents",
            "launch_workflow",
            "workflow_status",
        ]


class TestOrchestratorSessionBootstrapPrivateHelpers:
    """Private guards ``_already_has_agent`` and ``_already_has_pool``."""

    def test_already_has_agent_true_when_agent_is_set(self) -> None:
        """Returns ``True`` when the session's ``_agent`` attribute is not ``None``."""
        session: MagicMock = _make_session(agent=MagicMock())

        assert OrchestratorSessionBootstrap._already_has_agent(session=session) is True

    def test_already_has_agent_false_when_agent_is_none(self) -> None:
        """Returns ``False`` when the session's ``_agent`` attribute is ``None``."""
        session: MagicMock = _make_session(agent=None)

        assert OrchestratorSessionBootstrap._already_has_agent(session=session) is False

    def test_already_has_pool_true_when_pool_is_set(self) -> None:
        """Returns ``True`` when the session's ``_sub_agent_pool`` attribute is not ``None``."""
        session: MagicMock = _make_session(sub_agent_pool=MagicMock())

        assert OrchestratorSessionBootstrap._already_has_pool(session=session) is True

    def test_already_has_pool_false_when_pool_is_none(self) -> None:
        """Returns ``False`` when the session's ``_sub_agent_pool`` attribute is ``None``."""
        session: MagicMock = _make_session(sub_agent_pool=None)

        assert OrchestratorSessionBootstrap._already_has_pool(session=session) is False
