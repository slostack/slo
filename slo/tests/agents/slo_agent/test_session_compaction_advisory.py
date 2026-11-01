"""Snapshot-boundary latency advisory tests for ``SloAgentSession`` (spec 85.a.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.compaction.compacter import Compacter
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel


def _snapshot(
    *,
    estimated_used_tokens: int,
    estimate_available: bool = True,
) -> ContextWindowSnapshotDAO:
    """Build a projector-faithful snapshot with the routed model identity.

    Args:
        estimated_used_tokens (int): Durable replay estimate.
        estimate_available (bool): Whether the estimate is readable.

    Returns:
        ContextWindowSnapshotDAO: Snapshot fixture for advisory tests.
    """
    return ContextWindowSnapshotDAO(
        model_name="gpt-5.4",
        context_window_tokens=1_000_000,
        estimated_used_tokens=estimated_used_tokens,
        available_tokens=1_000_000 - estimated_used_tokens,
        consumed_percent=estimated_used_tokens / 10_000.0,
        estimate_available=estimate_available,
    )


def _session(monkeypatch: pytest.MonkeyPatch) -> SloAgentSession:
    """Build a prebuilt-agent session with a faux model.

    Args:
        monkeypatch (pytest.MonkeyPatch): Environment mutator; pins the global
            default model so advisory model identity is deterministic.

    Returns:
        SloAgentSession: Session ready for snapshot-boundary evaluation.
    """
    # cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
    # is captured at config.cfg import, before this helper's patch.
    monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _subscribe(session: SloAgentSession) -> list[AgentStreamEventDAO]:
    """Capture every dispatched stream event on ``session``.

    Args:
        session (SloAgentSession): Session under test.

    Returns:
        list[AgentStreamEventDAO]: Mutable capture list in dispatch order.
    """
    captured: list[AgentStreamEventDAO] = []

    async def _capture(event: AgentStreamEventDAO) -> None:
        """Append one dispatched event."""
        captured.append(event)

    session.subscribe(handler=_capture)
    return captured


def _advised(captured: list[AgentStreamEventDAO]) -> list[AgentStreamEventDAO]:
    """Return only the advisory events from one capture list.

    Args:
        captured (list[AgentStreamEventDAO]): Dispatched events.

    Returns:
        list[AgentStreamEventDAO]: Events whose kind is ``compaction_advised``.
    """
    return [event for event in captured if event.kind == "compaction_advised"]


class TestCompactionAdvisoryEvaluation:
    """Threshold, one-shot, re-arm, and no-compaction behavior."""

    @pytest.mark.asyncio
    async def test_exact_threshold_emits_one_notice_without_compacting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """At exactly 256,000 tokens one advisory names /compact and help latency."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        captured: list[AgentStreamEventDAO] = _subscribe(session=session)
        with (
            patch.object(
                session,
                "context_window_snapshot",
                new=AsyncMock(return_value=_snapshot(estimated_used_tokens=256_000)),
            ),
            patch.object(Compacter, "compact", new=AsyncMock()) as mock_compact,
        ):
            await session.refresh_context_window_snapshot()

        advised: list[AgentStreamEventDAO] = _advised(captured=captured)
        assert len(advised) == 1
        assert "/compact" in (advised[0].content or "")
        assert "help latency" in (advised[0].content or "")
        assert advised[0].metadata["estimated_used_tokens"] == 256_000
        mock_compact.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_below_threshold_emits_nothing_and_stays_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 255,999 estimate emits no advisory and leaves the flag armed."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        captured: list[AgentStreamEventDAO] = _subscribe(session=session)
        with patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(return_value=_snapshot(estimated_used_tokens=255_999)),
        ):
            await session.refresh_context_window_snapshot()

        assert _advised(captured=captured) == []
        assert session._compaction_advisory_armed is True

    @pytest.mark.asyncio
    async def test_above_threshold_is_one_shot_until_rearmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two refreshes at/above threshold dispatch exactly one advisory."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        captured: list[AgentStreamEventDAO] = _subscribe(session=session)
        with patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(return_value=_snapshot(estimated_used_tokens=300_000)),
        ):
            await session.refresh_context_window_snapshot()
            await session.refresh_context_window_snapshot()

        assert len(_advised(captured=captured)) == 1

    @pytest.mark.asyncio
    async def test_below_threshold_rearms_for_the_next_advisory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Above, below, above yields exactly two advisories and none at the dip."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        captured: list[AgentStreamEventDAO] = _subscribe(session=session)
        sequences: list[ContextWindowSnapshotDAO] = [
            _snapshot(estimated_used_tokens=300_000),
            _snapshot(estimated_used_tokens=100_000),
            _snapshot(estimated_used_tokens=300_000),
        ]
        with patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(side_effect=sequences),
        ):
            await session.refresh_context_window_snapshot()
            await session.refresh_context_window_snapshot()
            await session.refresh_context_window_snapshot()

        assert len(_advised(captured=captured)) == 2

    @pytest.mark.asyncio
    async def test_unavailable_estimate_emits_nothing_and_keeps_disarmed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable estimate neither emits nor re-arms a disarmed session."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        session._compaction_advisory_armed = False
        captured: list[AgentStreamEventDAO] = _subscribe(session=session)
        with patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(return_value=_snapshot(estimated_used_tokens=0, estimate_available=False)),
        ):
            await session.refresh_context_window_snapshot()

        assert _advised(captured=captured) == []
        assert session._compaction_advisory_armed is False

    @pytest.mark.asyncio
    async def test_reuses_existing_snapshot_publication_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The refreshed snapshot is republished through the existing usage field."""
        session: SloAgentSession = _session(monkeypatch=monkeypatch)
        expected: ContextWindowSnapshotDAO = _snapshot(estimated_used_tokens=256_000)
        with patch.object(
            session,
            "context_window_snapshot",
            new=AsyncMock(return_value=expected),
        ):
            refreshed = await session.refresh_context_window_snapshot()

        assert refreshed.context_window_snapshot == expected
        assert session.usage_snapshot().context_window_snapshot == expected


class TestCompactionAdvisoryThresholdConfiguration:
    """Environment resolution through ``positive_int_env``."""

    def test_environment_override_is_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A positive ``SLO_COMPACTION_ADVISORY_TOKENS`` replaces the default."""
        monkeypatch.setenv("SLO_COMPACTION_ADVISORY_TOKENS", "500")
        assert SloAgentSession._compaction_advisory_threshold_tokens() == 500

    @pytest.mark.parametrize("configured", [None, "invalid", "0", "-1"])
    def test_absent_or_invalid_configuration_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        configured: str | None,
    ) -> None:
        """Absent or invalid configuration resolves to 256,000.

        Args:
            monkeypatch (pytest.MonkeyPatch): Environment mutator.
            configured (str | None): Raw environment value or ``None`` to unset.
        """
        if configured is None:
            monkeypatch.delenv("SLO_COMPACTION_ADVISORY_TOKENS", raising=False)
        else:
            monkeypatch.setenv("SLO_COMPACTION_ADVISORY_TOKENS", configured)
        assert SloAgentSession._compaction_advisory_threshold_tokens() == 256_000
