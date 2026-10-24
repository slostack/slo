"""Tests for session-level rate-limit waiting and retries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.credit_exhaustion_policy import ProviderErrorKind
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.dao import PreflightDecisionDAO, SessionConfigDAO
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
            events: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="hello")]

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

    def test_build_preflight_decision_records_one_estimate(self) -> None:
        """A successful preflight computes the request estimate once."""
        session: SloAgentSession = _session()
        policy = session._resolve_attempt_policy()

        with patch.object(session, "_estimated_request_tokens", return_value=123) as estimate:
            decision = session._build_preflight_decision(
                text="hello",
                message_history=[],
                policy=policy,
            )

        assert estimate.call_count == 1
        assert decision.estimated_tokens == 123
        assert decision.bypass is None

    @pytest.mark.asyncio
    async def test_degraded_preflight_continues_without_local_attempt(self) -> None:
        """A local preflight defect does not stop the provider lane."""
        session: SloAgentSession = _session()
        invoked: int = 0

        async def _invoke(**_kwargs):
            nonlocal invoked
            invoked += 1
            yield AgentStreamEventDAO(kind="run_completed", content="done")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]
        with patch.object(session, "_build_preflight_decision", side_effect=IndexError("local defect")):
            events: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="hello")]

        assert [event.kind for event in events] == ["run_completed"]
        assert invoked == 1
        assert not session._recent_request_times
        assert not session._recent_request_token_estimates

    def test_build_preflight_decision_bypasses_empty_oversized_token_window(self) -> None:
        """An impossible local TPM wait is a zero-wait diagnostic, not a veto."""
        session: SloAgentSession = _session()
        policy = session._resolve_attempt_policy().model_copy(update={"tokens_per_minute": 100})

        with patch.object(session, "_estimated_request_tokens", return_value=101):
            decision = session._build_preflight_decision(
                text="hello",
                message_history=[],
                policy=policy,
            )

        assert decision.wait_seconds == 0
        assert decision.bypass is not None
        assert decision.bypass.reason == "empty_token_window_oversized_request"
        assert decision.bypass.estimated_tokens == 101
        assert decision.bypass.tokens_per_minute == 100

    @pytest.mark.asyncio
    async def test_preflight_bypass_emits_audit_before_provider_call(self) -> None:
        """An oversized empty TPM window is audited and still sent to the provider."""
        session: SloAgentSession = _session()
        policy = session._resolve_attempt_policy().model_copy(update={"tokens_per_minute": 100})
        invoked: int = 0

        async def _invoke(**_kwargs):
            nonlocal invoked
            invoked += 1
            yield AgentStreamEventDAO(kind="run_completed", content="done")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]
        with patch.object(session, "_resolve_attempt_policy", return_value=policy):
            with patch.object(session, "_estimated_request_tokens", return_value=101):
                events: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="hello")]

        assert [event.kind for event in events] == ["preflight_bypassed", "run_completed"]
        assert events[0].metadata == {
            "reason": "empty_token_window_oversized_request",
            "estimated_tokens": 101,
            "tokens_per_minute": 100,
        }
        assert invoked == 1

    @pytest.mark.asyncio
    async def test_preflight_local_rate_wait_yields_retrying_status(self) -> None:
        """A saturated local request window yields a waiting status before the attempt."""
        # This scenario saturates the catalog's 30-RPM policy, not the host default.
        session: SloAgentSession = _single_model_session(model_name="gpt-5.4")
        session._recent_request_times.extend([0.0] * 30)
        session._recent_request_token_estimates.extend((0.0, 10) for _ in range(30))

        async def _invoke(**_kwargs):
            yield AgentStreamEventDAO(kind="run_completed", content="done")

        session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]

        with patch("src.agents.slo_agent.sessions.service.time.monotonic", return_value=1.0):
            with patch("src.agents.slo_agent.sessions.service.asyncio.sleep", new=AsyncMock()):
                events: list[AgentStreamEventDAO] = [event async for event in session.invoke(text="hello")]

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


@pytest.mark.asyncio
async def test_history_disabled_bypass_is_live_without_history_write() -> None:
    """The bypass reaches live consumers while the disabled store remains untouched."""
    session = _session()
    session._enable_history = False
    session._history_store = None
    policy = session._resolve_attempt_policy().model_copy(update={"tokens_per_minute": 100})

    async def _invoke(**_kwargs):
        yield AgentStreamEventDAO(kind="run_completed", content="done")

    session.agent.invoke = _invoke  # type: ignore[method-assign,assignment]
    with (
        patch.object(session, "_resolve_attempt_policy", return_value=policy),
        patch.object(session, "_estimated_request_tokens", return_value=101),
        patch.object(session, "_persist_preflight_bypassed_event", new_callable=AsyncMock) as persist_bypass,
    ):
        events = [event async for event in session.invoke(text="hello")]

    assert [event.kind for event in events] == ["preflight_bypassed", "run_completed"]
    persist_bypass.assert_not_awaited()


def test_provider_observation_builder_uses_exact_decision_estimate() -> None:
    """Provider observation never infers an estimate from a mutable deque."""
    from src.agents.providers.credit_exhaustion_policy import ProviderErrorSignalDAO
    from src.agents.providers.credit_exhaustion_policy import ProviderLimitObservationDAO

    session = _single_model_session()
    session._recent_request_token_estimates.append((1.0, 999))
    decision = PreflightDecisionDAO(estimated_tokens=123, now_seconds=1.0, wait_seconds=0)

    observation: ProviderLimitObservationDAO = session._build_provider_limit_observation(
        provider=ProviderName.OPENAI,
        model_name="gpt-5.6-terra",
        signal=ProviderErrorSignalDAO(kind=ProviderErrorKind.RATE_LIMITED),
        decision=decision,
    )

    assert observation.estimated_request_tokens == 123
