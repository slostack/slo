"""Tests for session-owned usage snapshots."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.providers.faux import FauxChatModel


def _prebuilt_session(*, response: AIMessage) -> SloAgentSession:
    """Build a prebuilt-agent session for usage tests.

    Args:
        response (AIMessage): Faux assistant response.

    Returns:
        SloAgentSession: Session wrapping the faux agent.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[response])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestSessionUsageSnapshot:
    """Usage snapshot seeding, accumulation, and runtime refresh."""

    def test_usage_snapshot_seeds_from_active_model_and_reasoning(self, tmp_path: Path) -> None:
        """A lazy-built session exposes model and reasoning fields immediately."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="high",
            enable_history=False,
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        snapshot = session.usage_snapshot()

        assert snapshot.active_model_name == "gpt-5.4"
        assert snapshot.active_reasoning_level == "high"
        assert snapshot.output_cap_tokens == 8192
        assert snapshot.provider_effort == "high"

    @pytest.mark.asyncio
    async def test_refresh_usage_snapshot_accumulates_completed_turn_totals(self) -> None:
        """Completed-turn usage rolls into session totals after a prompt finishes."""
        session: SloAgentSession = _prebuilt_session(
            response=AIMessage(
                content="hi",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )
        )

        async for _event in session.invoke(text="hello"):
            pass
        snapshot = session.refresh_usage_snapshot()

        assert snapshot.usage_available is True
        assert snapshot.latest_turn.total_tokens == 15
        assert snapshot.session_totals.total_tokens == 15

    def test_usage_snapshot_handles_missing_provider_usage_honestly(self) -> None:
        """Missing provider usage keeps the snapshot truthful."""
        session: SloAgentSession = _prebuilt_session(
            response=AIMessage(content="hi"),
        )

        snapshot = session.usage_snapshot()

        assert snapshot.usage_available is False
        assert snapshot.latest_turn.total_tokens is None
        assert snapshot.session_totals.total_tokens is None

    def test_switch_model_rebuilds_usage_snapshot_static_fields(self, tmp_path: Path) -> None:
        """Model switching updates the snapshot's static model fields."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=False,
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        session.switch_model(model_name="claude-sonnet-4-6")
        snapshot = session.usage_snapshot()

        assert snapshot.active_model_name == "claude-sonnet-4-6"
        assert snapshot.provider_effort == "high"
        assert snapshot.provider_budget_tokens is None
