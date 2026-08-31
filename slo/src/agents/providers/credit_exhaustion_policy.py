"""Classify provider exceptions as credit-exhaustion, rate-limited, or other (28.a.2)."""
from __future__ import annotations

from enum import auto, Enum
from typing import Optional

from src.agents.providers.stream_recovery.service import StreamRecoveryService
from src.auth.credential_dao import ProviderName

__all__ = [
    "AllModelsExhaustedError",
    "CreditExhaustedError",
    "CreditExhaustionPolicy",
    "ProviderErrorClassifier",
    "ProviderErrorKind",
    "should_switch",
]


class ProviderErrorKind(Enum):
    """Semantic classification of a provider exception.

    Members:
        CREDIT_EXHAUSTED: The account has run out of credits or quota.
        RATE_LIMITED: Transient rate limit (HTTP 429).
        TRANSIENT_PROVIDER_FAILURE: Transient server-side failure (HTTP 500/502/
            503/529) — the provider lane is unhealthy but the request is valid.
        STREAM_DISCONNECTED: A controlled provider transport-stream failure.
        OTHER: Any other error; propagated to the caller unchanged.
    """

    CREDIT_EXHAUSTED = auto()
    RATE_LIMITED = auto()
    TRANSIENT_PROVIDER_FAILURE = auto()
    STREAM_DISCONNECTED = auto()
    OTHER = auto()


_SWITCHABLE_KINDS: frozenset[ProviderErrorKind] = frozenset(
    {
        ProviderErrorKind.CREDIT_EXHAUSTED,
        ProviderErrorKind.RATE_LIMITED,
        ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE,
        ProviderErrorKind.STREAM_DISCONNECTED,
    }
)
"""The kinds for which ModelPool should cool the current member and switch.

``OTHER`` is intentionally excluded: switching providers on a malformed request
or a local bug would repeat the same invalid call and mask the defect.
"""


_TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 529})
"""HTTP status codes treated as transient provider failures across providers.

529 is Anthropic's "overloaded" code; 500/502/503 are generic upstream/server
failures. All are server-side and switch-eligible without being quota errors.
"""

_OPENAI_OVERLOAD_MARKER: str = "our servers are currently overloaded"
"""Stable OpenAI API message accepted when the SDK exposes no HTTP status."""

_RATE_LIMIT_TEXT_MARKERS: tuple[str, ...] = ("rate limit", "429")
"""Message fragments that signal a rate limit when no HTTP status is exposed.

LangChain provider exceptions do not always carry a ``status_code``; the
session retry path historically matched these fragments so a text-only rate
limit still waited and retried. The shared classifier owns that heuristic now
so every consumer (single-model retry, ModelPool, recovery) agrees.
"""


def should_switch(*, kind: ProviderErrorKind) -> bool:
    """Return whether ModelPool should switch routes for ``kind``.

    Called by ``ModelPool._agenerate`` / ``ModelPool._astream`` immediately
    after ``CreditExhaustionPolicy.classify`` to decide between cooling the
    current member and re-raising. The single source of truth for "switchable".

    Args:
        kind (ProviderErrorKind): The classified provider-error kind.

    Returns:
        bool: ``True`` for CREDIT_EXHAUSTED / RATE_LIMITED /
            TRANSIENT_PROVIDER_FAILURE; ``False`` for OTHER.
    """
    return kind in _SWITCHABLE_KINDS


class CreditExhaustedError(RuntimeError):
    """Raised by ModelPool when a model rejects the call due to credit exhaustion.

    Attributes:
        provider (ProviderName): The provider whose account is exhausted.
        model_name (str): The model that triggered the credit exhaustion.
    """

    def __init__(self, *, provider: ProviderName, model_name: str) -> None:
        """Initialise with provider and model context.

        Args:
            provider (ProviderName): The exhausted provider.
            model_name (str): The specific model that was called.
        """
        super().__init__(f"{provider.value}/{model_name}: credit balance exhausted")
        self.provider: ProviderName = provider
        self.model_name: str = model_name


class AllModelsExhaustedError(RuntimeError):
    """Raised by ModelPool when every pool entry is simultaneously cooling down.

    Attributes:
        cooled_models (list[str]): Names of all cooled-down models.
    """

    def __init__(self, *, cooled_models: list[str]) -> None:
        """Initialise with the list of cooled models.

        Args:
            cooled_models (list[str]): All models that are in cooldown.
        """
        names: str = ", ".join(cooled_models)
        super().__init__(f"All models in pool are in cooldown: {names}")
        self.cooled_models: list[str] = cooled_models


class ProviderErrorClassifier:
    """Classify provider exceptions into one shared provider-error taxonomy.

    Each provider uses different HTTP status codes and error body patterns for
    credit exhaustion. This class centralises those mappings so ModelPool
    stays provider-agnostic.
    """

    @classmethod
    def classify(
        cls,
        *,
        error: BaseException,
        provider: ProviderName,
    ) -> ProviderErrorKind:
        """Return the semantic kind of ``error`` for the given ``provider``.

        Args:
            error (BaseException): The raw exception from the LangChain provider.
            provider (ProviderName): Which provider raised the error.

        Returns:
            ProviderErrorKind: The classified kind of the error.
        """
        if StreamRecoveryService.is_stream_disconnection(exc=error):
            return ProviderErrorKind.STREAM_DISCONNECTED
        if provider == ProviderName.KIMI_FOR_CODING:
            return cls._classify_kimi_for_coding(error=error)
        if provider == ProviderName.ANTHROPIC:
            return cls._classify_anthropic(error=error)
        if provider == ProviderName.OPENAI:
            return cls._classify_openai(error=error)
        return ProviderErrorKind.OTHER

    # ------------------------------------------------------------------
    # Per-provider classifiers
    # ------------------------------------------------------------------

    @classmethod
    def _classify_kimi_for_coding(cls, *, error: BaseException) -> ProviderErrorKind:
        """Classify a Kimi For Coding API error.

        KFC returns 402 for credit exhaustion, 429 for rate limiting, and 500
        for transient server errors. 500 now classifies as
        TRANSIENT_PROVIDER_FAILURE (was RATE_LIMITED) so the pool cools it on
        the short transient window.

        Args:
            error (BaseException): The exception from ChatOpenAI targeting KFC.

        Returns:
            ProviderErrorKind: Classification result.
        """
        status: Optional[int] = _extract_status_code(error=error)
        if status == 402:
            return ProviderErrorKind.CREDIT_EXHAUSTED
        if status == 429:
            return ProviderErrorKind.RATE_LIMITED
        if status in _TRANSIENT_STATUS_CODES:
            return ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE
        return cls._classify_by_message_text(error=error)

    @classmethod
    def _classify_anthropic(cls, *, error: BaseException) -> ProviderErrorKind:
        """Classify an Anthropic API error.

        Anthropic uses HTTP 402 for credit exhaustion. Some error responses
        include a body mentioning "credit balance" — this handles both forms.
        429 is a rate limit; 529 (overloaded) is now a transient provider
        failure (was RATE_LIMITED) so the pool cools it on the short window.

        Args:
            error (BaseException): The exception from ChatAnthropic.

        Returns:
            ProviderErrorKind: Classification result.
        """
        status: Optional[int] = _extract_status_code(error=error)
        if status == 402:
            return ProviderErrorKind.CREDIT_EXHAUSTED
        message: str = str(error).lower()
        if "credit balance" in message or "billing" in message:
            return ProviderErrorKind.CREDIT_EXHAUSTED
        if status == 429:
            return ProviderErrorKind.RATE_LIMITED
        if status in _TRANSIENT_STATUS_CODES:  # 529 (overloaded) now lands here
            return ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE
        return cls._classify_by_message_text(error=error)

    @classmethod
    def _classify_openai(cls, *, error: BaseException) -> ProviderErrorKind:
        """Classify an OpenAI / ChatGPT-backend API error.

        Quota exhaustion is identified by ``error.code``; 429 is a rate limit;
        500/502/503 are transient provider failures. Generic ``APIError``
        instances can omit the HTTP status, so the stable overload message is
        also a narrow transient fallback.

        Args:
            error (BaseException): The exception from ChatOpenAI or ChatGPT backend.

        Returns:
            ProviderErrorKind: Classification result.
        """
        error_code: Optional[str] = getattr(error, "code", None)
        if error_code in ("insufficient_quota", "billing_hard_limit_reached"):
            return ProviderErrorKind.CREDIT_EXHAUSTED
        status: Optional[int] = _extract_status_code(error=error)
        if status == 429:
            return ProviderErrorKind.RATE_LIMITED
        if status in _TRANSIENT_STATUS_CODES:
            return ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE
        if _OPENAI_OVERLOAD_MARKER in str(error).lower():
            return ProviderErrorKind.TRANSIENT_PROVIDER_FAILURE
        return cls._classify_by_message_text(error=error)

    # ------------------------------------------------------------------
    # Shared message-text fallback
    # ------------------------------------------------------------------

    @classmethod
    def _classify_by_message_text(cls, *, error: BaseException) -> ProviderErrorKind:
        """Classify by message text when no HTTP status settled the kind.

        Provider SDKs sometimes raise exceptions that carry the rate-limit
        signal only in their message (no ``status_code``). This shared fallback
        preserves the former provider-agnostic ``"rate limit"`` / ``"429"``
        heuristic so a text-only rate limit still waits and retries.

        Args:
            error (BaseException): The exception left unclassified by status.

        Returns:
            ProviderErrorKind: ``RATE_LIMITED`` for a rate-limit marker, else
                ``OTHER``.
        """
        message: str = str(error).lower()
        if any(marker in message for marker in _RATE_LIMIT_TEXT_MARKERS):
            return ProviderErrorKind.RATE_LIMITED
        return ProviderErrorKind.OTHER


def _extract_status_code(*, error: BaseException) -> Optional[int]:
    """Extract an HTTP status code from an exception, if present.

    Checks ``status_code`` and ``http_status`` attributes (LangChain and
    httpx expose different names on different exception types).

    Args:
        error (BaseException): Any exception, possibly from an HTTP client.

    Returns:
        Optional[int]: The status code, or None if not found.
    """
    return getattr(error, "status_code", None) or getattr(error, "http_status", None)


CreditExhaustionPolicy = ProviderErrorClassifier
"""Backward-compatible alias for the former provider-error classifier name.

``ProviderErrorClassifier`` is the canonical name because the taxonomy owns
credit exhaustion, rate limits, and transient provider failures. Existing
callers may continue importing this alias until their import paths migrate.
"""
