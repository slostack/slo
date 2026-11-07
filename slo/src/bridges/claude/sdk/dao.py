"""Portable values for the fresh text-only Claude SDK boundary."""

import base64
import binascii
from pathlib import Path
from typing import Any, ClassVar, Literal, Optional

from pydantic import field_validator

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


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


class ClaudeUsageDAO(BaseModel):
    """Token counts Claude reported for one response; ``None`` means unknown, never zero."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    input_tokens: Optional[int] = Field(default=None, ge=0, description="Fresh input, cache excluded.")
    output_tokens: Optional[int] = Field(default=None, ge=0, description="Output, cumulative in a response.")
    cache_read_tokens: Optional[int] = Field(default=None, ge=0, description="cache_read_input_tokens.")
    cache_write_tokens: Optional[int] = Field(default=None, ge=0, description="cache_creation_input_tokens.")

    _NATIVE_KEYS: ClassVar[dict[str, str]] = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_read_input_tokens": "cache_read_tokens",
        "cache_creation_input_tokens": "cache_write_tokens",
    }

    @classmethod
    def from_native(cls, *, payload: object) -> "ClaudeUsageDAO":
        """Read native usage leniently: a missing or malformed value is unknown, never an error.

        Usage is telemetry and must not fail a coding task, so anything that is not
        a non-negative ``int`` (bools included) leaves that field ``None``.
        """
        return cls().overwritten_by_native(payload=payload)

    def overwritten_by_native(self, *, payload: object) -> "ClaudeUsageDAO":
        """Apply cumulative native counts: a present key replaces the field, an absent key keeps it.

        A present but malformed value makes the field unknown (``None``) rather than
        leaving a stale earlier count to be reported as real.
        """
        if not isinstance(payload, dict):
            return self
        return self.model_copy(
            update={
                field: self._valid_count(value=payload[native])
                for native, field in self._NATIVE_KEYS.items()
                if native in payload
            }
        )

    @staticmethod
    def _valid_count(*, value: object) -> Optional[int]:
        """Return ``value`` only when it is a non-negative int (bools excluded)."""
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


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


class ClaudeSubmissionPlanDAO(BaseModel):
    """The native session choice and ordered user content for one new prompt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    fresh_native_session: bool = Field(description="True when Claude has seen none of the history.")
    abandon_parked_round: bool = Field(
        default=False,
        description="True when a parked round must be cancelled before the fresh session starts.",
    )

    @model_validator(mode="after")
    def _abandon_implies_fresh(self) -> "ClaudeSubmissionPlanDAO":
        """Reject contradictory admission instructions before native work.

        Returns:
            ClaudeSubmissionPlanDAO: The consistent submission plan.

        Raises:
            ValueError: Abandon was requested without a fresh native session.
        """
        if self.abandon_parked_round and not self.fresh_native_session:
            raise ValueError("Abandoning a parked round requires a fresh native session.")
        return self

    content: tuple[ClaudeTextDAO | ClaudeImageDAO, ...] = Field(
        min_length=1, description="Ordered transcript blocks followed by the new prompt blocks."
    )


class ClaudeInvocationOptionsDAO(BaseModel):
    """One new user submission: plain text, or ordered text and image content."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    invocation_id: str = Field(min_length=1, description="Unique submission correlation ID.")
    text: str = Field(default="", max_length=32 * 1024 * 1024, description="Plain-text prompt.")
    content: tuple[ClaudeTextDAO | ClaudeImageDAO, ...] = Field(
        default=(), description="Ordered text and image prompt; used instead of text."
    )

    @model_validator(mode="after")
    def validate_single_prompt_form(self) -> "ClaudeInvocationOptionsDAO":
        """Require exactly one of plain text or ordered content."""
        if bool(self.text) == bool(self.content):
            raise ValueError("Provide exactly one of text or content.")
        return self

    def carries_prompt(self) -> bool:
        """Report whether the submission holds any non-blank text or an image."""
        if not self.content:
            return bool(self.text.strip())
        return any(isinstance(block, ClaudeImageDAO) or bool(block.text.strip()) for block in self.content)

    def native_prompt(self) -> str | list[dict[str, Any]]:
        """Return the SDK user-message content: a string, or ordered wire blocks."""
        if not self.content:
            return self.text
        return [
            (
                {"type": "text", "text": block.text}
                if isinstance(block, ClaudeTextDAO)
                else {
                    "type": "image",
                    "source": {"type": "base64", "media_type": block.media_type, "data": block.data},
                }
            )
            for block in self.content
        ]
