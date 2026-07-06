"""Tests for ``OrchestratorSessionBootstrap`` (sub-spec 53.a.3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_session(
    *,
    agent=None,
    sub_agent_pool=None,
    session_id: str = "sess-001",
    active_model_name: str = "claude-sonnet-4-6",
    assembled_system_prompt: str = "child-system-prompt",
) -> MagicMock:
    """Build a minimal ``SloAgentSession`` mock.

    Args:
        agent: Value to return from ``_agent`` attribute (None = not yet built).
        sub_agent_pool: Value to return from ``_sub_agent_pool`` attribute.
        session_id (str): Session id for the mock.
        active_model_name (str): Active model name for the mock.
        assembled_system_prompt (str): Value returned by ``_assembled_system_prompt``.

    Returns:
        MagicMock: A session mock with the requested attribute state.
    """
    session: MagicMock = MagicMock()
    session._agent = agent
    session._sub_agent_pool = sub_agent_pool
    session.session_id = session_id
    session.active_model_name = active_model_name
    session.event_relay = MagicMock()
    session._assembled_system_prompt = MagicMock(return_value=assembled_system_prompt)
    return session


# ── tests ─────────────────────────────────────────────────────────────────────


class TestOrchestratorSessionBootstrapAttach:
    """``OrchestratorSessionBootstrap.attach`` promotes sessions to orchestrator mode."""

    def test_attach_calls_session_attach_sub_agent_pool(self) -> None:
        """Successful attach calls ``session.attach_sub_agent_pool``."""
        session: MagicMock = _make_session()

        with (
            patch(
                "src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"
            ) as MockPool,
            patch(
                "src.agents.slo_agent.orchestrator.bootstrap.SpawnSubAgentsTool"
            ) as MockTool,
        ):
            mock_pool = MagicMock()
            MockPool.return_value = mock_pool
            mock_spawn_tool = MagicMock()
            MockTool.build.return_value = mock_spawn_tool

            OrchestratorSessionBootstrap.attach(session=session)

        session.attach_sub_agent_pool.assert_called_once_with(
            pool=mock_pool,
            spawn_tool=mock_spawn_tool,
        )

    def test_attach_builds_pool_with_session_identity(self) -> None:
        """Pool is constructed with the session id, model, and event relay."""
        session: MagicMock = _make_session(
            session_id="my-session",
            active_model_name="gpt-5.4",
        )

        with (
            patch(
                "src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"
            ) as MockPool,
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

        with patch(
            "src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"
        ) as MockPool:
            OrchestratorSessionBootstrap.attach(session=session)

        MockPool.assert_not_called()
        session.attach_sub_agent_pool.assert_not_called()

    def test_attach_is_noop_when_pool_already_attached(self) -> None:
        """No pool is built when ``_sub_agent_pool`` is already set."""
        existing_pool: MagicMock = MagicMock()
        session: MagicMock = _make_session(sub_agent_pool=existing_pool)

        with patch(
            "src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"
        ) as MockPool:
            OrchestratorSessionBootstrap.attach(session=session)

        MockPool.assert_not_called()
        session.attach_sub_agent_pool.assert_not_called()

    def test_attach_builds_spawn_tool_from_pool(self) -> None:
        """``SpawnSubAgentsTool.build`` is called with the freshly created pool."""
        session: MagicMock = _make_session()

        with (
            patch(
                "src.agents.slo_agent.orchestrator.bootstrap.SubAgentPool"
            ) as MockPool,
            patch(
                "src.agents.slo_agent.orchestrator.bootstrap.SpawnSubAgentsTool"
            ) as MockTool,
        ):
            mock_pool = MagicMock()
            MockPool.return_value = mock_pool

            OrchestratorSessionBootstrap.attach(session=session)

        MockTool.build.assert_called_once_with(pool=mock_pool)


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
