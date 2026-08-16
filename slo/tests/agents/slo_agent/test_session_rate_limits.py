"""Tests for session-level rate-limit waiting and retries."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.rate_limit.dao import ModelRateLimitPolicyDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import _RATE_LIMIT_OUTPUT_ESTIMATE_TOKENS, SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.auth.credential_dao import ProviderName


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


def _single_model_session(*, model_name: str = "gpt-5.6-terra") -> SloAgentSession:
    """Build a pre-built single-model session with a known provider identity.

    Args:
        model_name (str, optional): The configured single-model route. Defaults to
            "gpt-5.6-terra".

    Returns:
        SloAgentSession: Session whose active model resolves through provider_for_model.
    """
    workdir: Path = Path(".").resolve()
    config: SessionConfigDAO = SessionConfigDAO(workdir=workdir, model_name=model_name)
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        config=config,
        workdir=workdir,
        session_id=str(uuid4()),
        enable_history=False,
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

    def test_classifies_openai_overload_as_iteration_retryable_for_single_model(self) -> None:
        """OpenAI overload retries through the configured single-model provider lane."""
        session: SloAgentSession = _single_model_session()
        error: RuntimeError = RuntimeError(
            "APIError: Our servers are currently overloaded. Please try again later."
        )

        assert session._resolve_active_provider() is ProviderName.OPENAI
        assert session._is_iteration_retryable_error(exc=error) is True

    def test_openai_overload_after_visible_output_does_not_retry(self) -> None:
        """Visible transcript output prevents replaying a later OpenAI overload failure."""
        session: SloAgentSession = _single_model_session()
        retry_policy = session._build_iteration_retry_policy(policy=session._resolve_attempt_policy())
        error: RuntimeError = RuntimeError(
            "APIError: Our servers are currently overloaded. Please try again later."
        )

        plan = session.agent._decide_iteration_retry(
            iteration_retry_policy=retry_policy,
            exc=error,
            saw_visible_output_this_iteration=True,
            attempt_number=1,
        )

        assert plan.retryable is False

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


def _tpm_policy(*, tokens_per_minute: Optional[int] = 200_000) -> ModelRateLimitPolicyDAO:
    """Build a rate policy carrying only a TPM ceiling.

    Args:
        tokens_per_minute (Optional[int], optional): TPM ceiling, or None when
            uncapped. Defaults to 200_000 (the Kimi family ceiling).

    Returns:
        ModelRateLimitPolicyDAO: Policy for token-window tests.
    """
    return ModelRateLimitPolicyDAO(
        model_name="kimi-k3",
        requests_per_minute=None,
        tokens_per_minute=tokens_per_minute,
        automatic_retry_attempts=3,
        local_retry_wait_cap_seconds=30,
    )


class TestTokenWindowWaitSeconds:
    """Local TPM wait computation, including the un-schedulable request case."""

    def test_returns_zero_when_window_is_empty_and_estimate_exceeds_budget(self) -> None:
        """An oversized request against an empty window proceeds instead of raising.

        Regression for ``IndexError: deque index out of range``. When one request's
        estimate exceeds the entire per-minute budget on its own — the case for a
        model whose context window (262_144) is larger than its TPM ceiling
        (200_000) — the fit check fails while no prior request is recorded. Reading
        the oldest window entry then indexed an empty deque and killed the turn in
        pre-flight, before any provider call. There is nothing to wait for, so the
        attempt must proceed and let the provider's 429 handling decide.
        """
        session: SloAgentSession = _session()

        assert not session._recent_request_token_estimates

        wait_seconds: int = session._token_window_wait_seconds(
            policy=_tpm_policy(),
            estimated_tokens=208_000,
            now_seconds=1.0,
        )

        assert wait_seconds == 0

    def test_returns_zero_when_window_is_empty_and_estimate_fits(self) -> None:
        """A normal first request against an empty window never waits."""
        session: SloAgentSession = _session()

        wait_seconds: int = session._token_window_wait_seconds(
            policy=_tpm_policy(),
            estimated_tokens=10_000,
            now_seconds=1.0,
        )

        assert wait_seconds == 0

    def test_waits_for_oldest_entry_to_age_out_when_window_is_saturated(self) -> None:
        """A saturated window waits until the oldest recorded request leaves it."""
        session: SloAgentSession = _session()
        session._recent_request_token_estimates.append((10.0, 195_000))

        wait_seconds: int = session._token_window_wait_seconds(
            policy=_tpm_policy(),
            estimated_tokens=10_000,
            now_seconds=30.0,
        )

        assert wait_seconds == 40  # (10.0 + 60.0) - 30.0

    def test_returns_zero_when_policy_has_no_token_ceiling(self) -> None:
        """An uncapped model never incurs a local TPM wait."""
        session: SloAgentSession = _session()

        wait_seconds: int = session._token_window_wait_seconds(
            policy=_tpm_policy(tokens_per_minute=None),
            estimated_tokens=5_000_000,
            now_seconds=1.0,
        )

        assert wait_seconds == 0

    @pytest.mark.asyncio
    async def test_invoke_survives_request_larger_than_full_token_budget(self) -> None:
        """``invoke`` completes the turn instead of failing pre-flight on an oversized request.

        End-to-end guard for the session 82089eae crash: every turn died with
        ``IndexError`` roughly a millisecond after ``run_started``, because a single
        oversized transcript made the estimate exceed the whole TPM budget on a
        fresh window. The failure never recorded an attempt, so the window stayed
        empty and the next turn failed identically.
        """
        session: SloAgentSession = _session()

        async def _invoke(**_kwargs):
            yield AgentStreamEventDAO(kind="run_completed", content="done")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        oversized_prompt: str = "x" * 4_000_000  # ~1M estimated tokens

        with patch("src.agents.slo_agent.sessions.service.asyncio.sleep", new=AsyncMock()):
            events: list[AgentStreamEventDAO] = [
                event async for event in session.invoke(text=oversized_prompt)
            ]

        assert [event.kind for event in events] == ["run_completed"]
