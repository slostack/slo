"""Tests for session-level rate-limit waiting and retries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS, SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel


def _session() -> SloAgentSession:
    """Build a prebuilt session for rate-limit tests.

    Returns:
        SloAgentSession: Session wrapping a faux agent.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestSessionRateLimitResilience:
    """Local waits and bounded retries in ``invoke``."""

    @pytest.mark.asyncio
    async def test_relays_agent_iteration_retry_events(self) -> None:
        """The session relays the agent's per-iteration ``run_retrying`` then ``run_completed``.

        Retry is now the agent's responsibility (37.a.5): the session injects the
        iteration retry policy and relays whatever the agent emits — it no longer
        re-runs the whole stream itself.
        """
        session: SloAgentSession = _session()

        async def _invoke(**_kwargs):
            yield AgentStreamEventDAO(
                kind="run_retrying",
                content="retrying",
                metadata={"wait_seconds": 1},
                iteration=0,
            )
            yield AgentStreamEventDAO(kind="run_completed", content="done", iteration=0)

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        with patch("src.agents.slo_agent.sessions.service.asyncio.sleep", new=AsyncMock()):
            events: list[AgentStreamEventDAO] = [
                event async for event in session.invoke(text="hello")
            ]

        assert [event.kind for event in events] == ["run_retrying", "run_completed"]
        assert events[1].content == "done"
        # The cooldown surface is cleared once the terminal (non-retry) event arrives.
        assert session._cooldown_seconds_remaining is None

    @pytest.mark.asyncio
    async def test_injects_iteration_retry_policy_into_agent(self) -> None:
        """``invoke`` passes an ``iteration_retry_policy`` to the agent."""
        session: SloAgentSession = _session()
        captured: dict = {}

        async def _invoke(**kwargs):
            captured.update(kwargs)
            yield AgentStreamEventDAO(kind="run_completed", content="done", iteration=0)

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        _ = [event async for event in session.invoke(text="hello")]

        assert captured.get("iteration_retry_policy") is not None

    @pytest.mark.asyncio
    async def test_rate_limit_after_visible_output_does_not_retry(self) -> None:
        """Visible output blocks silent automatic replay on later rate limits."""
        session: SloAgentSession = _session()
        attempt_count: int = 0

        async def _invoke(**_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            yield AgentStreamEventDAO(kind="text_delta", delta="hello", iteration=0)
            raise RuntimeError("429 rate limit reached")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        events: list[AgentStreamEventDAO] = []
        with patch("src.agents.slo_agent.sessions.service.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(RuntimeError, match="429"):
                async for event in session.invoke(text="hello"):
                    events.append(event)

        assert events[0].kind == "text_delta"
        assert attempt_count == 1

    @pytest.mark.asyncio
    async def test_preflight_local_rate_wait_yields_retrying_status(self) -> None:
        """A saturated local request window yields a waiting status before the attempt."""
        session: SloAgentSession = _session()
        session._recent_request_times.extend([0.0] * 30)
        session._recent_request_token_estimates.extend((0.0, 10) for _ in range(30))

        async def _invoke(**_kwargs):
            yield AgentStreamEventDAO(kind="run_completed", content="done")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        with patch("src.agents.slo_agent.sessions.service.time.monotonic", return_value=1.0):
            with patch("src.agents.slo_agent.sessions.service.asyncio.sleep", new=AsyncMock()):
                events: list[AgentStreamEventDAO] = [
                    event async for event in session.invoke(text="hello")
                ]

        assert events[0].kind == "run_retrying"
        assert "local rate window" in (events[0].content or "")
        assert events[1].kind == "run_completed"


def test_request_token_estimate_uses_realistic_output_not_ceiling() -> None:
    """The local TPM estimate must reflect a realistic per-turn output, not the hard ceiling.

    Spec 02 raised ``max_tokens`` to the model's real output ceiling (64K/128K). The
    local rate-limit estimator must NOT track that ceiling, or it would assume every
    turn emits the full cap and inject artificial waits after a few back-to-back
    turns. This locks the estimate to ``input + _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS``.
    """
    session: SloAgentSession = _session()
    text: str = "x" * 400  # ~100 estimated input tokens

    estimate: int = session._estimated_request_tokens(text=text)

    assert estimate == (len(text) // 4) + _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS
    # Guard against re-coupling to the raised hard ceiling.
    assert _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS < 64_000
