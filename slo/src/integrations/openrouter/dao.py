"""Private typed values crossing the fixed OpenRouter GET boundary."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OpenRouterKeyVerificationDAO(BaseModel):
    """Private evidence that one captured credential passed ``GET /key``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_fingerprint: str = Field(repr=False)
    verified_at: datetime


class OpenRouterModelsResponseDAO(BaseModel):
    """Validated models envelope retained only for the catalog converter."""

    model_config = ConfigDict(extra="ignore")

    data: list[dict[str, object]] = Field(description="Authenticated user-model records.")
    total_count: Optional[int] = Field(
        default=None,
        strict=True,
        ge=0,
        le=10_000,
        description="Optional total number of records in the complete list.",
    )
    next: Optional[str] = Field(default=None, description="Opaque provider pagination indication.")


def credential_fingerprint(*, access_token: str) -> str:
    """Create private non-secret provenance for one effective OpenRouter key.

    Args:
        access_token (str): Exact captured bearer credential.

    Returns:
        str: SHA-256 digest used only for private cache provenance.
    """
    payload: bytes = b"slo-openrouter-v1\0" + access_token.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verification_now() -> datetime:
    """Return the UTC instant used to bind successful key verification."""
    return datetime.now(tz=timezone.utc)
