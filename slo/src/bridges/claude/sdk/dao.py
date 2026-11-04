"""Portable values for the fresh text-only Claude SDK boundary."""

import base64
import binascii
from pathlib import Path
from typing import Literal, Optional

from pydantic import field_validator

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ClaudeInteractionBindingDAO(BaseModel):
    """Immutable host association for one native invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    invocation_id: str = Field(min_length=1, max_length=256)
    binding_version: int = Field(ge=0)


class ClaudeToolDefinitionDAO(BaseModel):
    """Raw host tool schema, without transport arguments or injected identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str
    input_schema: dict[str, JsonValue]


class ClaudeToolCallDAO(BaseModel):
    """One fully assembled call with the exact native identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call_id: str = Field(min_length=1, max_length=256)
    name: str
    arguments: dict[str, JsonValue]


class ClaudeTextDAO(BaseModel):
    """Live text returned by the host executor."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["text"] = "text"
    text: str


class ClaudeImageDAO(BaseModel):
    """Live image returned by read; never a durable transcript representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["image"] = "image"
    media_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
    data: str

    @field_validator("data")
    @classmethod
    def validate_image_bytes(cls, value: str) -> str:
        """Reject malformed or oversized live images before callback acceptance."""
        if len(value) > 4 * ((16 * 1024 * 1024 + 2) // 3):
            raise ValueError("Image exceeds decoded byte limit.")
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid image base64.") from None
        if len(decoded) > 16 * 1024 * 1024 or base64.b64encode(decoded).decode() != value:
            raise ValueError("Invalid or oversized image base64.")
        return value


class ClaudeToolResultDAO(BaseModel):
    """Terminal host output for one exact native call."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call_id: str = Field(min_length=1, max_length=256)
    content: tuple[ClaudeTextDAO | ClaudeImageDAO, ...]
    is_error: bool


class ClaudeToolResultBatchDAO(BaseModel):
    """Whole response result set, atomically accepted before callback release."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    response_id: str = Field(min_length=1, max_length=256)
    results: tuple[ClaudeToolResultDAO, ...]


class ClaudeToolResultSubmissionDAO(BaseModel):
    """A continuation command, not another user prompt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    invocation_id: str = Field(min_length=1, max_length=256)
    tool_result_batch: ClaudeToolResultBatchDAO


class ClaudeBridgeConfigurationDAO(BaseModel):
    """Trusted executable override; absent selects the SDK-bundled runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    executable: Optional[Path] = Field(default=None, description="Trusted absolute Claude executable.")

    @field_validator("executable")
    @classmethod
    def executable_is_absolute(cls, value: Optional[Path]) -> Optional[Path]:
        """Reject relative overrides before native work starts."""
        if value is not None and not value.is_absolute():
            raise ValueError("Claude executable must be absolute.")
        return value


class ClaudeAuthenticationStatusDAO(BaseModel):
    """Safe native-login observation, never a billing or entitlement guarantee."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    state: Literal["ready", "login_required", "unsupported", "conflict", "unavailable"] = Field(
        description="Observed native authentication availability."
    )
    safe_message: str = Field(max_length=300, description="Fixed safe guidance, without native output.")


class ClaudeSessionOptionsDAO(BaseModel):
    """Fixed native conversation configuration translated by the host bridge."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: str = Field(min_length=1, description="Host association, not a native resume ID.")
    model_id: str = Field(description="Validated exact qualified bridge route.")
    tools: tuple[ClaudeToolDefinitionDAO, ...] = ()

    @field_validator("model_id")
    @classmethod
    def model_id_is_qualified(cls, value: str) -> str:
        """Keep the host route and SDK model identity unambiguously separate."""
        if not value.startswith("claude-bridge:") or value == "claude-bridge:":
            raise ValueError("Claude bridge model must retain its claude-bridge: prefix.")
        return value

    working_directory: Path = Field(description="Absolute existing project directory.")
    instructions: str = Field(description="Final host instructions appended to the native preset.")
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = Field(
        default=None, description="Native effort; None explicitly disables extended thinking."
    )


class ClaudeInvocationOptionsDAO(BaseModel):
    """One new text submission, never a replay transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    invocation_id: str = Field(min_length=1, description="Unique submission correlation ID.")
    text: str = Field(min_length=1, max_length=32 * 1024 * 1024, description="New user text only.")
