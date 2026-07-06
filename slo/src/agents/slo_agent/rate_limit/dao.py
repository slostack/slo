"""Rate-limit configuration and retry-plan DAOs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ModelRateLimitPolicyDAO",
    "RateLimitRetryPlanDAO",
]


class ModelRateLimitPolicyDAO(BaseModel):
    """Configured local rate metadata for one supported model."""

    model_config = ConfigDict(frozen=True)

    model_name: str = Field(description="The model this policy applies to.")
    requests_per_minute: Optional[int] = Field(
        default=None,
        description="Requests-per-minute cap, or None when uncapped.",
    )
    tokens_per_minute: Optional[int] = Field(
        default=None,
        description="Tokens-per-minute cap, or None when uncapped.",
    )
    automatic_retry_attempts: int = Field(
        description="Maximum automatic retry attempts on a rate-limit error.",
    )
    local_retry_wait_cap_seconds: int = Field(
        description="Maximum local wait duration in seconds between retries.",
    )


class RateLimitRetryPlanDAO(BaseModel):
    """Resolved retry plan for one caught rate-limit error."""

    model_config = ConfigDict(frozen=True)

    retryable: bool = Field(description="Whether the error is retryable.")
    wait_seconds: int = Field(description="Seconds to wait before retrying.")
    message: str = Field(description="Operator-facing retry status message.")
