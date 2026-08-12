"""Tests for RecoveryPolicy classification (Feature 50, sub-spec 50.a.1)."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.agents.providers.credit_exhaustion_policy import AllModelsExhaustedError, ProviderErrorKind
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.agents.slo_agent.recovery.service import RecoveryPolicy
from src.auth.credential_dao import ProviderName


class TestRecoveryPolicyFatalCases:
    """Exceptions that must never be demoted into a recovery observation."""

    def test_classify_returns_fatal_for_cancelled_error(self) -> None:
        """asyncio.CancelledError is always FATAL regardless of provider."""
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=asyncio.CancelledError())

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_classify_returns_fatal_for_all_models_exhausted(self) -> None:
        """AllModelsExhaustedError is always FATAL — no pool member to retry on."""
        exc = AllModelsExhaustedError(cooled_models=["kimi-k2"])
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_classify_returns_fatal_for_credential_value_error(self) -> None:
        """ValueError mentioning 'credential' is always FATAL (misconfiguration)."""
        exc = ValueError("no credential for provider")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_fatal_reason_names_the_exception_type(self) -> None:
        """The reason field for a fatal decision includes the exception class name."""
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=asyncio.CancelledError())

        assert "CancelledError" in decision.reason


class TestRecoveryPolicyMechanical:
    """Exceptions that the rate-limit / route-switch layers own."""

    def test_classify_returns_mechanical_for_openai_overload_message(self) -> None:
        """The generic OpenAI overload message never becomes an LLM recovery prompt."""
        exc: RuntimeError = RuntimeError(
            "APIError: Our servers are currently overloaded. Please try again later."
        )

        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(
            exc=exc,
            provider=ProviderName.OPENAI,
        )

        assert decision.recovery_class is RecoveryClass.MECHANICAL

    def test_classify_returns_mechanical_for_switchable_provider_error(self) -> None:
        """An error classified as RATE_LIMITED with a known provider → MECHANICAL."""
        # Patch CreditExhaustionPolicy.classify to return RATE_LIMITED so that
        # should_switch returns True, simulating a rate-limit HTTP 429 from Anthropic.
        with patch(
            "src.agents.slo_agent.recovery.service.ProviderErrorClassifier.classify",
            return_value=ProviderErrorKind.RATE_LIMITED,
        ):
            exc = RuntimeError("rate limit 429")
            decision: RecoveryDecisionDAO = RecoveryPolicy.classify(
                exc=exc,
                provider=ProviderName.ANTHROPIC,
            )

        assert decision.recovery_class == RecoveryClass.MECHANICAL

    def test_mechanical_reason_mentions_rate_limit_layers(self) -> None:
        """The reason for a MECHANICAL decision references the owning layers."""
        with patch(
            "src.agents.slo_agent.recovery.service.ProviderErrorClassifier.classify",
            return_value=ProviderErrorKind.CREDIT_EXHAUSTED,
        ):
            exc = RuntimeError("billing hard limit")
            decision: RecoveryDecisionDAO = RecoveryPolicy.classify(
                exc=exc,
                provider=ProviderName.OPENAI,
            )

        assert decision.recovery_class == RecoveryClass.MECHANICAL
        assert "rate-limit" in decision.reason or "route-switch" in decision.reason


class TestRecoveryPolicyLLMRecoverable:
    """Exceptions the model is invited to recover from."""

    def test_classify_returns_llm_recoverable_for_timeout_error_no_provider(self) -> None:
        """TimeoutError with no provider → LLM_RECOVERABLE with a hint."""
        exc = TimeoutError("hung")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc, provider=None)

        assert decision.recovery_class == RecoveryClass.LLM_RECOVERABLE
        assert decision.observation_hint is not None
        assert "timed out" in decision.observation_hint.lower()

    def test_classify_returns_llm_recoverable_when_provider_is_none(self) -> None:
        """Generic RuntimeError with no provider falls through to LLM_RECOVERABLE."""
        exc = RuntimeError("something unexpected happened")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.LLM_RECOVERABLE

    def test_classify_returns_llm_recoverable_for_generic_error_with_provider(self) -> None:
        """RuntimeError classified as OTHER by the provider policy → LLM_RECOVERABLE."""
        # CreditExhaustionPolicy returns OTHER for an unknown error, so should_switch
        # returns False, and the exception falls through to LLM_RECOVERABLE.
        with patch(
            "src.agents.slo_agent.recovery.service.ProviderErrorClassifier.classify",
            return_value=ProviderErrorKind.OTHER,
        ):
            exc = RuntimeError("unexpected internal error")
            decision: RecoveryDecisionDAO = RecoveryPolicy.classify(
                exc=exc,
                provider=ProviderName.ANTHROPIC,
            )

        assert decision.recovery_class == RecoveryClass.LLM_RECOVERABLE

    def test_llm_recoverable_reason_names_exception_type(self) -> None:
        """The reason for LLM_RECOVERABLE includes the exception class name."""
        exc = RuntimeError("oops")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert "RuntimeError" in decision.reason

    def test_no_observation_hint_for_non_timeout_error(self) -> None:
        """A plain RuntimeError produces no observation hint."""
        exc = RuntimeError("generic problem")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.observation_hint is None

    def test_asyncio_timeout_error_also_gets_hint(self) -> None:
        """asyncio.TimeoutError (subclass of TimeoutError) also receives a hint."""
        exc = asyncio.TimeoutError()
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.LLM_RECOVERABLE
        assert decision.observation_hint is not None


class TestRecoveryPolicyContextOverflow:
    """Context-window overflow must be classified FATAL, not LLM_RECOVERABLE.

    Appending a recovery observation to an already-overflowed context makes it
    larger, guaranteeing a second failure. The session-layer compaction path
    handles recovery instead, so the agent loop must treat overflow as terminal.
    """

    @pytest.mark.parametrize(
        "error_phrase",
        [
            "prompt is too long",
            "context_length_exceeded",
            "maximum context length",
            "too_many_tokens",
            "prompt_too_long",
            "input too long",
            "your request exceeded model token limit",
            # OpenAI / Codex responses-API phrases added by this fix:
            "your input exceeds the context window",
            "exceeds the context window of this model",
        ],
    )
    def test_classify_returns_fatal_for_context_overflow_markers(
        self, error_phrase: str
    ) -> None:
        """Every known overflow phrase must produce FATAL, not LLM_RECOVERABLE."""
        exc = RuntimeError(error_phrase)
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_classify_context_overflow_is_case_insensitive(self) -> None:
        """Overflow detection must ignore case so mixed-case messages are caught."""
        exc = RuntimeError("Your Input Exceeds The Context Window Of This Model.")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_classify_context_overflow_reason_mentions_compaction(self) -> None:
        """The FATAL reason for overflow must reference session-layer compaction."""
        exc = RuntimeError("your input exceeds the context window")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.FATAL
        assert "compaction" in decision.reason.lower()

    def test_classify_context_overflow_takes_priority_over_provider_check(self) -> None:
        """Overflow is classified FATAL before the provider / MECHANICAL guard runs."""
        with patch(
            "src.agents.slo_agent.recovery.service.ProviderErrorClassifier.classify",
            return_value=ProviderErrorKind.RATE_LIMITED,
        ):
            exc = RuntimeError("prompt is too long (context_length_exceeded)")
            decision: RecoveryDecisionDAO = RecoveryPolicy.classify(
                exc=exc,
                provider=ProviderName.OPENAI,
            )

        assert decision.recovery_class == RecoveryClass.FATAL

    def test_non_overflow_runtime_error_is_still_llm_recoverable(self) -> None:
        """An ordinary RuntimeError unrelated to overflow falls through to LLM_RECOVERABLE."""
        exc = RuntimeError("some unrelated tool failure")
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=exc)

        assert decision.recovery_class == RecoveryClass.LLM_RECOVERABLE


class TestRecoveryDecisionDAOImmutability:
    """RecoveryDecisionDAO is frozen and must reject mutation."""

    def test_decision_dao_is_frozen(self) -> None:
        """Mutating recovery_class on a returned decision raises ValidationError."""
        decision: RecoveryDecisionDAO = RecoveryPolicy.classify(exc=RuntimeError("x"))

        with pytest.raises((ValidationError, TypeError)):
            decision.recovery_class = RecoveryClass.FATAL  # type: ignore[misc]
