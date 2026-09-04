"""Tests for ``src.agents.providers.credit_exhaustion_policy`` (spec 28.a.2)."""
from __future__ import annotations

import httpx
import pytest
from unittest.mock import MagicMock

from src.agents.providers.credit_exhaustion_policy import (
    AllModelsExhaustedError,
    CreditExhaustedError,
    CreditExhaustionPolicy,
    ProviderErrorClassifier,
    ProviderErrorKind,
    should_switch,
)
from src.auth.credential_dao import ProviderName


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_error(*, status_code: int) -> MagicMock:
    """Build a mock exception with a ``status_code`` attribute.

    Args:
        status_code (int): The HTTP status code to attach.

    Returns:
        MagicMock: A mock exception with ``status_code`` and ``code`` set.
    """
    err: MagicMock = MagicMock(spec=Exception)
    err.status_code = status_code
    err.code = None
    # Pin str(error): a bare MagicMock stringifies with its random id, whose
    # digits can accidentally contain the policy's "429" rate-limit text
    # marker and flake the classification under test (~0.2% per run).
    err.configure_mock(**{"__str__.return_value": f"HTTP error {status_code}"})
    return err


def _coded_error(*, code: str) -> MagicMock:
    """Build a mock exception with an ``error.code`` attribute and no status.

    Args:
        code (str): The OpenAI error code to attach.

    Returns:
        MagicMock: A mock exception with ``code`` set and ``status_code`` None.
    """
    err: MagicMock = MagicMock(spec=Exception)
    err.status_code = None
    err.code = code
    return err


# ---------------------------------------------------------------------------
# CreditExhaustedError
# ---------------------------------------------------------------------------


class TestCreditExhaustedError:
    def test_message_includes_provider_and_model(self) -> None:
        """Error message contains provider value and model name."""
        err: CreditExhaustedError = CreditExhaustedError(
            provider=ProviderName.KIMI_FOR_CODING,
            model_name="kimi-for-coding",
        )
        assert "kimi_for_coding" in str(err)
        assert "kimi-for-coding" in str(err)

    def test_attributes_accessible(self) -> None:
        """Provider and model_name attributes are set on the exception."""
        err: CreditExhaustedError = CreditExhaustedError(
            provider=ProviderName.OPENAI,
            model_name="gpt-4o",
        )
        assert err.provider == ProviderName.OPENAI
        assert err.model_name == "gpt-4o"


# ---------------------------------------------------------------------------
# AllModelsExhaustedError
# ---------------------------------------------------------------------------


class TestAllModelsExhaustedError:
    def test_cooled_models_accessible(self) -> None:
        """cooled_models list is exposed as an attribute."""
        err: AllModelsExhaustedError = AllModelsExhaustedError(
            cooled_models=["kimi-latest", "claude-sonnet-4-6"]
        )
        assert "kimi-latest" in err.cooled_models

    def test_message_lists_cooled_models(self) -> None:
        """Error message contains the names of all cooled models."""
        err: AllModelsExhaustedError = AllModelsExhaustedError(
            cooled_models=["model-a", "model-b"]
        )
        assert "model-a" in str(err)
        assert "model-b" in str(err)


# ---------------------------------------------------------------------------
# Moonshot classifier
# ---------------------------------------------------------------------------


class TestCreditExhaustionPolicyKimiForCoding:
    def test_402_is_credit_exhausted(self) -> None:
        """HTTP 402 from Kimi For Coding → CREDIT_EXHAUSTED."""
        kind: ProviderErrorKind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=402),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind == ProviderErrorKind.CREDIT_EXHAUSTED

    def test_429_is_rate_limited(self) -> None:
        """HTTP 429 from Kimi For Coding → RATE_LIMITED."""
        kind: ProviderErrorKind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=429),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind == ProviderErrorKind.RATE_LIMITED

    def test_500_is_transient_provider_failure(self) -> None:
        """HTTP 500 from Kimi For Coding → TRANSIENT_PROVIDER_FAILURE (short cooldown)."""
        kind: ProviderErrorKind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=500),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind == ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE


# ---------------------------------------------------------------------------
# Anthropic classifier
# ---------------------------------------------------------------------------


class TestCreditExhaustionPolicyAnthropic:
    def test_402_is_credit_exhausted(self) -> None:
        """HTTP 402 from Anthropic → CREDIT_EXHAUSTED."""
        assert CreditExhaustionPolicy.classify(
            error=_status_error(status_code=402),
            provider=ProviderName.ANTHROPIC,
        ) == ProviderErrorKind.CREDIT_EXHAUSTED

    def test_credit_balance_body_is_credit_exhausted(self) -> None:
        """Error message mentioning credit balance → CREDIT_EXHAUSTED."""
        err: MagicMock = MagicMock()
        err.status_code = None
        err.__str__ = lambda s: "Your credit balance is too low to make this request"
        assert CreditExhaustionPolicy.classify(
            error=err,
            provider=ProviderName.ANTHROPIC,
        ) == ProviderErrorKind.CREDIT_EXHAUSTED

    def test_429_is_rate_limited(self) -> None:
        """HTTP 429 from Anthropic → RATE_LIMITED."""
        assert CreditExhaustionPolicy.classify(
            error=_status_error(status_code=429),
            provider=ProviderName.ANTHROPIC,
        ) == ProviderErrorKind.RATE_LIMITED

    def test_529_is_transient_provider_failure(self) -> None:
        """HTTP 529 (Anthropic overload) → TRANSIENT_PROVIDER_FAILURE (short cooldown)."""
        assert CreditExhaustionPolicy.classify(
            error=_status_error(status_code=529),
            provider=ProviderName.ANTHROPIC,
        ) == ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE


# ---------------------------------------------------------------------------
# OpenAI classifier
# ---------------------------------------------------------------------------


class TestCreditExhaustionPolicyOpenAI:
    def test_insufficient_quota_code_is_credit_exhausted(self) -> None:
        """error.code == 'insufficient_quota' → CREDIT_EXHAUSTED regardless of status."""
        err: MagicMock = MagicMock()
        err.code = "insufficient_quota"
        err.status_code = 429
        assert CreditExhaustionPolicy.classify(
            error=err,
            provider=ProviderName.OPENAI,
        ) == ProviderErrorKind.CREDIT_EXHAUSTED

    def test_billing_hard_limit_code_is_credit_exhausted(self) -> None:
        """error.code == 'billing_hard_limit_reached' → CREDIT_EXHAUSTED."""
        err: MagicMock = MagicMock()
        err.code = "billing_hard_limit_reached"
        err.status_code = 429
        assert CreditExhaustionPolicy.classify(
            error=err,
            provider=ProviderName.OPENAI,
        ) == ProviderErrorKind.CREDIT_EXHAUSTED

    def test_plain_429_without_quota_code_is_rate_limited(self) -> None:
        """HTTP 429 with generic rate_limit code → RATE_LIMITED (not credit exhausted)."""
        err: MagicMock = MagicMock()
        err.code = "rate_limit_exceeded"
        err.status_code = 429
        assert CreditExhaustionPolicy.classify(
            error=err,
            provider=ProviderName.OPENAI,
        ) == ProviderErrorKind.RATE_LIMITED


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------


class TestCreditExhaustionPolicyUnknownProvider:
    def test_unknown_provider_is_other(self) -> None:
        """An unrecognised provider value → OTHER."""
        assert CreditExhaustionPolicy.classify(
            error=RuntimeError("something"),
            provider=MagicMock(),  # unrecognised ProviderName variant
        ) == ProviderErrorKind.OTHER


# ---------------------------------------------------------------------------
# should_switch predicate (37.a.1)
# ---------------------------------------------------------------------------


class TestStreamDisconnectionClassification:
    @pytest.mark.parametrize(
        "provider",
        (ProviderName.ANTHROPIC, ProviderName.OPENAI, ProviderName.KIMI_FOR_CODING),
    )
    def test_classify_returns_stream_disconnected_for_every_provider(
        self, provider: ProviderName
    ) -> None:
        """Transport classification is identical for every provider label."""
        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=httpx.RemoteProtocolError("peer closed"),
            provider=provider,
        )

        assert kind is ProviderErrorKind.STREAM_DISCONNECTED


class TestShouldSwitch:
    def test_switches_on_credit_exhausted(self) -> None:
        """CREDIT_EXHAUSTED is switchable."""
        assert should_switch(kind=ProviderErrorKind.CREDIT_EXHAUSTED) is True

    def test_switches_on_rate_limited(self) -> None:
        """RATE_LIMITED is switchable."""
        assert should_switch(kind=ProviderErrorKind.RATE_LIMITED) is True

    def test_switches_on_transient_provider_failure(self) -> None:
        """TRANSIENT_PROVIDER_FAILURE is switchable."""
        assert should_switch(kind=ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE) is True

    def test_switches_on_stream_disconnected(self) -> None:
        """STREAM_DISCONNECTED is switchable before a streamed chunk."""
        assert should_switch(kind=ProviderErrorKind.STREAM_DISCONNECTED) is True

    def test_does_not_switch_on_other(self) -> None:
        """OTHER is the only non-switchable kind."""
        assert should_switch(kind=ProviderErrorKind.OTHER) is False


# ---------------------------------------------------------------------------
# Transient-provider-failure classification (37.a.1)
# ---------------------------------------------------------------------------


class TestClassifyOpenAITransient:
    def test_overload_message_classifies_as_transient_provider_failure(self) -> None:
        """The generic OpenAI overload message is retryable without a status code."""
        error: RuntimeError = RuntimeError(
            "APIError: Our servers are currently overloaded. Please try again later."
        )

        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=error,
            provider=ProviderName.OPENAI,
        )

        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE

    def test_503_classifies_as_transient_provider_failure(self) -> None:
        """OpenAI 503 → TRANSIENT_PROVIDER_FAILURE (previously OTHER, did not switch)."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=503),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE

    def test_500_classifies_as_transient_provider_failure(self) -> None:
        """OpenAI 500 → TRANSIENT_PROVIDER_FAILURE."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=500),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE

    def test_502_classifies_as_transient_provider_failure(self) -> None:
        """OpenAI 502 → TRANSIENT_PROVIDER_FAILURE."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=502),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE

    def test_429_still_classifies_as_rate_limited(self) -> None:
        """OpenAI 429 remains RATE_LIMITED."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=429),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.RATE_LIMITED

    def test_insufficient_quota_still_classifies_as_credit_exhausted(self) -> None:
        """OpenAI insufficient_quota remains CREDIT_EXHAUSTED."""
        kind = CreditExhaustionPolicy.classify(
            error=_coded_error(code="insufficient_quota"),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.CREDIT_EXHAUSTED

    def test_400_still_classifies_as_other(self) -> None:
        """OpenAI 400 (bad request) remains OTHER — must not switch."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=400),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.OTHER


class TestClassifyAnthropicTransient:
    def test_529_overloaded_classifies_as_transient_provider_failure(self) -> None:
        """Anthropic 529 (overloaded) → TRANSIENT_PROVIDER_FAILURE."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=529),
            provider=ProviderName.ANTHROPIC,
        )
        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE


class TestClassifyKimiForCodingTransient:
    def test_500_classifies_as_transient_provider_failure(self) -> None:
        """KFC 500 → TRANSIENT_PROVIDER_FAILURE."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=500),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind is ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE

    def test_402_still_classifies_as_credit_exhausted(self) -> None:
        """KFC 402 remains CREDIT_EXHAUSTED."""
        kind = CreditExhaustionPolicy.classify(
            error=_status_error(status_code=402),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind is ProviderErrorKind.CREDIT_EXHAUSTED


class TestClassifyMessageTextFallback:
    """The shared text fallback for status-less provider errors."""

    def test_text_only_429_is_rate_limited(self) -> None:
        """A status-less error whose message names 429 → RATE_LIMITED."""
        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=RuntimeError("429 rate limit reached"),
            provider=ProviderName.OPENAI,
        )
        assert kind is ProviderErrorKind.RATE_LIMITED

    def test_text_only_rate_limit_phrase_is_rate_limited(self) -> None:
        """A status-less error whose message names a rate limit → RATE_LIMITED."""
        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=RuntimeError("Rate limit exceeded for this model"),
            provider=ProviderName.ANTHROPIC,
        )
        assert kind is ProviderErrorKind.RATE_LIMITED

    def test_unrelated_text_without_status_is_other(self) -> None:
        """A status-less error with no known marker stays OTHER — must not switch."""
        kind: ProviderErrorKind = ProviderErrorClassifier.classify(
            error=RuntimeError("connection reset by peer"),
            provider=ProviderName.KIMI_FOR_CODING,
        )
        assert kind is ProviderErrorKind.OTHER
