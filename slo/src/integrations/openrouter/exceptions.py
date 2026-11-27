"""Safe exceptions shared by OpenRouter discovery and inference boundaries."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

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


class OpenRouterReasoningConflictDAO(BaseModel):
    """Content-free structural evidence for one rejected reasoning detail merge."""

    model_config = ConfigDict(frozen=True)
    field: Literal["id", "type", "format", "signature", "index", "other"]
    existing_value_type: Literal["null", "boolean", "integer", "number", "string", "array", "object", "other"]
    incoming_value_type: Literal["null", "boolean", "integer", "number", "string", "array", "object", "other"]
    existing_index: Optional[int] = None
    incoming_index: Optional[int] = None
    existing_detail_type: Literal["reasoning.text", "reasoning.summary", "reasoning.encrypted", "other"]
    incoming_detail_type: Literal["reasoning.text", "reasoning.summary", "reasoning.encrypted", "other"]

    @classmethod
    def build(
        cls, *, field: str, existing: dict[str, object], incoming: dict[str, object]
    ) -> "OpenRouterReasoningConflictDAO":
        """Project untrusted detail objects into allowlisted structural facts only.

        Args:
            field: Conflicting key; unknown names become ``other``.
            existing: Accumulated detail, never retained by this projection.
            incoming: Incoming detail, never retained by this projection.

        Returns:
            OpenRouterReasoningConflictDAO: Safe diagnostic with no payload or IDs.
        """
        facts: dict[str, object] = {
            "field": field if field in {"id", "type", "format", "signature", "index"} else "other"
        }
        names: dict[type, str] = {
            type(None): "null",
            bool: "boolean",
            int: "integer",
            float: "number",
            str: "string",
            list: "array",
            dict: "object",
        }
        for prefix, detail in (("existing", existing), ("incoming", incoming)):
            facts[f"{prefix}_value_type"] = names.get(type(detail.get(field)), "other")
            index = detail.get("index")
            facts[f"{prefix}_index"] = index if type(index) is int and 0 <= index <= 2147483647 else None
            detail_type = detail.get("type")
            facts[f"{prefix}_detail_type"] = (
                detail_type
                if isinstance(detail_type, str)
                and detail_type in {"reasoning.text", "reasoning.summary", "reasoning.encrypted"}
                else "other"
            )
        return cls.model_validate(facts)


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
        diagnostic_reason: Optional[str] = None,
        reasoning_conflict: Optional[OpenRouterReasoningConflictDAO] = None,
    ) -> None:
        """Record only allowlisted response facts.

        Args:
            diagnostic_reason (Optional[str]): Allowlisted local validation failure reason.
            reasoning_conflict: Content-free structural facts for a rejected merge.
            partial_output_committed (bool): Whether this invocation yielded an SDK chunk.
            status_code (Optional[int]): HTTP status when the transport supplied one.
            error_type (Optional[str]): Validated provider error classification.
            limit_source (Optional[str]): Validated temporary-budget source.
            retry_after_seconds (Optional[int]): Validated bounded retry advice.
        """
        super().__init__(self.safe_message)
        self.diagnostic_reason = (
            diagnostic_reason
            if diagnostic_reason
            in {
                "reasoning_invalid_index",
                "reasoning_invalid_detail",
                "reasoning_invalid_fragment",
                "reasoning_field_conflict",
                "reasoning_invalid_json",
                "reasoning_metadata_too_large",
            }
            else None
        )
        self.reasoning_conflict = reasoning_conflict
        self.diagnostic_id: Optional[str] = None
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
