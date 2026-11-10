"""Correlated response events independent of host frameworks."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .dao import ClaudeToolCallDAO, ClaudeUsageDAO


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


class ClaudeThinkingEventDAO(ClaudeResponseEventDAO):
    """Ordered Claude thinking fragment; never part of the answer text."""

    kind: Literal["thinking_delta"] = "thinking_delta"
    text: str
    block_index: int = Field(ge=0, description="Native block position, so interleaved blocks stay apart.")


class ClaudeResponseClosedDAO(ClaudeResponseEventDAO):
    """Validated native message closure, not a tool handoff or invocation completion.

    The invocation may produce more messages, including after a refused native
    built-in tool. Usage belongs to this message and must not be counted again
    when its terminal result arrives after SDK cleanup.
    """

    kind: Literal["response_closed"] = "response_closed"
    usage: Optional[ClaudeUsageDAO] = None


class ClaudeResponseCompletedDAO(ClaudeResponseEventDAO):
    """Host tool handoff or invocation completion after successful SDK cleanup."""

    kind: Literal["response_completed"] = "response_completed"
    stop_reason: Literal["stop", "length", "tool_calls"]
    tool_calls: tuple[ClaudeToolCallDAO, ...] = ()
    usage: Optional[ClaudeUsageDAO] = Field(
        default=None, description="Counts for this response; None when Claude reported none."
    )

    @model_validator(mode="after")
    def validate_call_reason(self) -> "ClaudeResponseCompletedDAO":
        """Keep executable calls and their completion reason inseparable."""
        if bool(self.tool_calls) != (self.stop_reason == "tool_calls"):
            raise ValueError("Tool completion requires exactly a nonempty call set.")
        return self


ClaudeBridgeEvent = (
    ClaudeTextEventDAO | ClaudeThinkingEventDAO | ClaudeResponseClosedDAO | ClaudeResponseCompletedDAO
)
