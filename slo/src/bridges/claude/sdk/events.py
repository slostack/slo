"""Correlated response events independent of host frameworks."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .dao import ClaudeToolCallDAO


class ClaudeResponseEventDAO(BaseModel):
    """One ordered event bound to exactly one native invocation and response."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: str = Field(min_length=1, max_length=256)
    invocation_id: str = Field(min_length=1, max_length=256)
    response_id: str = Field(min_length=1, max_length=256)
    sequence: int = Field(gt=0)


class ClaudeTextEventDAO(ClaudeResponseEventDAO):
    """Ordered answer fragment; thinking and partial calls are never answer text."""

    kind: Literal["text_delta"] = "text_delta"
    text: str


class ClaudeResponseCompletedDAO(ClaudeResponseEventDAO):
    """Validated response boundary; terminal success additionally requires cleanup."""

    kind: Literal["response_completed"] = "response_completed"
    stop_reason: Literal["stop", "length", "tool_calls"]
    tool_calls: tuple[ClaudeToolCallDAO, ...] = ()

    @model_validator(mode="after")
    def validate_call_reason(self) -> "ClaudeResponseCompletedDAO":
        """Keep executable calls and their completion reason inseparable."""
        if bool(self.tool_calls) != (self.stop_reason == "tool_calls"):
            raise ValueError("Tool completion requires exactly a nonempty call set.")
        return self


ClaudeBridgeEvent = ClaudeTextEventDAO | ClaudeResponseCompletedDAO
