"""Safe exceptions shared by OpenRouter discovery and inference boundaries."""

from __future__ import annotations

from typing import Optional

_ALLOWED_ERROR_TYPES: frozenset[str] = frozenset(
    {
        "authentication",
        "content_policy_violation",
        "context_length_exceeded",
        "invalid_request",
        "model_not_found",
        "not_found",
        "permission_denied",
        "refusal",
        "server_error",
        "provider_overloaded",
        "provider_unavailable",
        "rate_limit_exceeded",
        "timeout",
    }
)


class OpenRouterAPIError(RuntimeError):
    """A sanitized OpenRouter operation failure without response-body data."""

    safe_message: str = "OpenRouter request failed. Retry later or check /auth."

    def __init__(
        self,
        *,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
        limit_source: Optional[str] = None,
        retry_after_seconds: Optional[int] = None,
        partial_output_committed: bool = False,
    ) -> None:
        """Record only allowlisted response facts.

        Args:
            partial_output_committed (bool): Whether this invocation yielded an SDK chunk.
            status_code (Optional[int]): HTTP status when the transport supplied one.
            error_type (Optional[str]): Validated provider error classification.
            limit_source (Optional[str]): Validated temporary-budget source.
            retry_after_seconds (Optional[int]): Validated bounded retry advice.
        """
        super().__init__(self.safe_message)
        self.partial_output_committed: bool = partial_output_committed
        self.status_code: Optional[int] = status_code
        self.error_type: Optional[str] = error_type if error_type in _ALLOWED_ERROR_TYPES else None
        self.limit_source: Optional[str] = (
            limit_source if limit_source == "openrouter_in_flight_budget" else None
        )
        self.retry_after_seconds: Optional[int] = (
            retry_after_seconds if retry_after_seconds is not None and retry_after_seconds > 0 else None
        )

    def __repr__(self) -> str:
        """Return fixed copy rather than response details."""
        return f"{self.__class__.__name__}({self.safe_message!r})"


class OpenRouterAuthenticationError(OpenRouterAPIError):
    """A sanitized authentication rejection from OpenRouter."""

    safe_message: str = "OpenRouter authentication failed. Check /auth or SLO_OPENROUTER_API_KEY."


class OpenRouterTimeoutError(OpenRouterAPIError):
    """A sanitized OpenRouter transport or operation deadline failure."""

    safe_message: str = "OpenRouter request timed out. Retry authentication later."


class OpenRouterProtocolError(OpenRouterAPIError):
    """A sanitized invalid or incomplete OpenRouter response."""

    safe_message: str = "OpenRouter returned an invalid response. Retry later."


class OpenRouterDiscoveryIncompleteError(OpenRouterAPIError):
    """A sanitized incomplete paginated discovery response."""

    safe_message: str = "OpenRouter model discovery was incomplete. Retry /model refresh."
