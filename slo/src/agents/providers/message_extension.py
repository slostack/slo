"""Typed private continuation metadata for provider-specific assistant messages."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.auth.credential_dao import ProviderName

PROVIDER_MESSAGE_EXTENSION_KEY: str = "slo_provider_extension"
"""Private ``AIMessage.additional_kwargs`` key for replay-only metadata."""


class ProviderMessageExtensionDAO(BaseModel):
    """Opaque provider continuation metadata attached to one assistant message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ProviderName = Field(description="Provider that issued the opaque metadata.")
    source_model_name: str = Field(description="Exact canonical source route.")
    reasoning: Optional[str] = Field(default=None, description="Visible provider reasoning fallback.")
    reasoning_details: list[JsonValue] = Field(
        default_factory=list,
        description="Ordered opaque provider reasoning details retained for same-route continuation.",
    )
