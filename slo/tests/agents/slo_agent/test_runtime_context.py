"""Tests for the session-owned ``SloRuntimeContext`` seam."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO


def _build_session(*, workdir: Path) -> SloAgentSession:
    """Build a pre-wired session without provider credentials.

    Args:
        workdir (Path): Directory represented by the session context.

    Returns:
        SloAgentSession: Session exposing the runtime context seam.
    """
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(workdir))
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=str(uuid4()),
        enable_history=False,
    )


class TestSloRuntimeContext:
    """The sanctioned read-only context for session consumers."""

    def test_runtime_context_exposes_identity_and_excludes_callables(self, tmp_path: Path) -> None:
        """The context retains identity while its live accessors do not serialize."""
        session: SloAgentSession = _build_session(workdir=tmp_path)

        context = session.runtime_context

        assert context.session_id == session.session_id
        assert context.workdir == tmp_path.resolve()
        assert context.history_root == tmp_path.resolve()
        assert "usage_snapshot" not in context.model_dump()
        assert "tool_names" not in context.model_dump()

    def test_runtime_context_usage_accessor_returns_current_snapshot(self, tmp_path: Path) -> None:
        """The usage accessor reads the current session state rather than a copy."""
        session: SloAgentSession = _build_session(workdir=tmp_path)
        replacement: SessionUsageSnapshotDAO = session.usage_snapshot().model_copy(
            update={"active_model_name": "updated-model"}
        )
        session._usage_snapshot = replacement

        snapshot: SessionUsageSnapshotDAO = session.runtime_context.usage_snapshot()

        assert snapshot.active_model_name == "updated-model"

    def test_runtime_context_uses_empty_fleet_and_optional_stores_without_pool(self, tmp_path: Path) -> None:
        """An ordinary session has no orchestration stores or live child fleet."""
        session: SloAgentSession = _build_session(workdir=tmp_path)
        context = session.runtime_context

        assert context.fleet_store is None
        assert context.status_store is None
        assert context.handle_store is None
        assert context.live_fleet() == []

    def test_runtime_context_tool_names_reflects_built_agent_bundle(self, tmp_path: Path) -> None:
        """The lazy accessor reports the tools bound to the session agent."""
        session: SloAgentSession = _build_session(workdir=tmp_path)

        tool_names: list[str] = session.runtime_context.tool_names()

        assert "bash" in tool_names

    def test_runtime_context_falls_back_when_injected_history_mock_has_no_path_root(
        self, tmp_path: Path
    ) -> None:
        """An injected mock store does not weaken the runtime context's Path contract."""
        history_store: Mock = Mock(spec=[])
        agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path))

        session: SloAgentSession = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=history_store,
            enable_history=False,
        )

        assert session.runtime_context.history_root == tmp_path.resolve()
