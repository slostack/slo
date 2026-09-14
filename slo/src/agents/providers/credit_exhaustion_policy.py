"""Classify provider exceptions as credit-exhaustion, rate-limited, or other (28.a.2)."""

from __future__ import annotations

from enum import auto, Enum
from math import ceil, isfinite
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.providers.stream_recovery.service import StreamRecoveryService
from src.auth.credential_dao import ProviderName

__all__ = [
    "AllModelsExhaustedError",
    "CreditExhaustedError",
    "CreditExhaustionPolicy",
    "ProviderErrorClassifier",
    "ProviderErrorKind",
    "ProviderErrorSignalDAO",
    "ProviderLimitObservationDAO",
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
    CONTEXT_OVERFLOW = auto()
    REQUEST_BODY_TOO_LARGE = auto()
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


class ProviderErrorSignalDAO(BaseModel):
    """Classify one provider rejection and retain only safe response facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProviderErrorKind
    status_code: int | None = None
    retry_after_seconds: int | None = Field(default=None, ge=1)
    request_limit: int | None = Field(default=None, ge=1)
    token_limit: int | None = Field(default=None, ge=1)


class ProviderLimitObservationDAO(BaseModel):
    """Persist one diagnostic provider limit signal without request content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName
    model_name: str
    signal: ProviderErrorSignalDAO
    estimated_request_tokens: int = Field(gt=0)
    rolling_request_count: int = Field(ge=0)
    rolling_token_estimate: int = Field(ge=0)


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
        return cls.inspect(error=error, provider=provider).kind

    @classmethod
    def inspect(
        cls,
        *,
        error: BaseException,
        provider: ProviderName,
    ) -> ProviderErrorSignalDAO:
        """Inspect one provider exception and retain only safe response facts.

        Args:
            error (BaseException): Raw provider exception.
            provider (ProviderName): Provider that raised the exception.

        Returns:
            ProviderErrorSignalDAO: Typed classification and parsed safe headers.
        """
        status_code: int | None = _extract_status_code(error=error)
        headers: Mapping[str, str] = _extract_headers(error=error)
        return ProviderErrorSignalDAO(
            kind=cls._inspect_kind(error=error, provider=provider, status_code=status_code),
            status_code=status_code,
            retry_after_seconds=_positive_retry_after(headers=headers),
            request_limit=_positive_header_value(headers=headers, key="x-ratelimit-limit-requests"),
            token_limit=_positive_header_value(headers=headers, key="x-ratelimit-limit-tokens"),
        )

    @classmethod
    def _inspect_kind(
        cls,
        *,
        error: BaseException,
        provider: ProviderName,
        status_code: int | None,
    ) -> ProviderErrorKind:
        """Return the sole provider-error kind for a response.

        Args:
            error (BaseException): Raw provider error.
            provider (ProviderName): Originating provider.
            status_code (int | None): Parsed status code when available.

        Returns:
            ProviderErrorKind: Provider-authoritative rejection category.
        """
        if StreamRecoveryService.is_stream_disconnection(exc=error):
            return ProviderErrorKind.STREAM_DISCONNECTED
        if status_code == 413:
            return ProviderErrorKind.REQUEST_BODY_TOO_LARGE
        if cls._has_context_overflow_marker(error=error):
            return ProviderErrorKind.CONTEXT_OVERFLOW
        if provider == ProviderName.KIMI_FOR_CODING:
            return cls._classify_kimi_for_coding(error=error)
        if provider == ProviderName.ANTHROPIC:
            return cls._classify_anthropic(error=error)
        if provider == ProviderName.OPENAI:
            return cls._classify_openai(error=error)
        return ProviderErrorKind.OTHER

    @staticmethod
    def _has_context_overflow_marker(*, error: BaseException) -> bool:
        """Return whether provider text confirms a context-window overflow."""
        markers: tuple[str, ...] = (
            "prompt is too long",
            "context_length_exceeded",
            "maximum context length",
            "too_many_tokens",
            "prompt_too_long",
            "input too long",
            "your request exceeded model token limit",
            "your input exceeds",
            "exceeds the context window",
        )
        message: str = str(error).lower()
        return any(marker in message for marker in markers)

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


def _extract_headers(*, error: BaseException) -> Mapping[str, str]:
    """Return response headers before fallback exception headers."""
    response: object | None = getattr(error, "response", None)
    response_headers: object | None = getattr(response, "headers", None)
    if isinstance(response_headers, Mapping):
        return response_headers
    headers: object | None = getattr(error, "headers", None)
    return headers if isinstance(headers, Mapping) else {}


def _positive_header_value(*, headers: Mapping[str, str], key: str) -> int | None:
    """Parse one positive integer provider header, or return ``None``."""
    value: object | None = next((value for name, value in headers.items() if name.lower() == key), None)
    if not isinstance(value, str) or not value.isdecimal():
        return None
    parsed: int = int(value)
    return parsed if parsed > 0 else None


def _positive_retry_after(*, headers: Mapping[str, str]) -> int | None:
    """Parse a positive decimal Retry-After value in seconds."""
    value: object | None = next(
        (value for name, value in headers.items() if name.lower() == "retry-after"), None
    )
    if not isinstance(value, str):
        return None
    try:
        parsed: float = float(value)
        if not isfinite(parsed) or parsed <= 0:
            return None
        return max(1, ceil(parsed))
    except (ValueError, OverflowError):
        return None


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
