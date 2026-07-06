"""DAOs for the Slo agent (sub-spec 01.f §4.1).

Two transports (SSE router, A2A executor) consume these shapes — keep
them stable.

All DAOs are Pydantic ``BaseModel`` instances with the ``DAO`` suffix.
No ``TypedDict``, no ``@dataclass``.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


__all__ = [
    "StreamRequestDAO",
    "QueryDAO",
    "ProgressEventDAO",
]


class StreamRequestDAO(BaseModel):
    """Body shape for ``POST /agents/slo/stream`` (sub-spec 01.j)."""

    model_config = ConfigDict(
        title="StreamRequestDAO",
        extra="ignore",
        from_attributes=True,
    )

    query: str = Field(description="The user prompt to send to the agent.")
    history: Optional[list[dict]] = Field(
        default=None,
        description=(
            "Optional prior conversation as a list of "
            "``{'role': 'user'|'assistant', 'content': str}`` dicts."
        ),
    )
    tools: Optional[list[str]] = Field(
        default=None,
        description=(
            "Optional list of tool names to restrict the agent to. ``None`` "
            "means use the agent's default bundle."
        ),
    )


class QueryDAO(BaseModel):
    """A2A skill input shape — wraps the same payload as StreamRequestDAO.

    The A2A executor (sub-spec 01.h) parses an incoming ``DataPart`` into
    this DAO before delegating to ``SloAgent.invoke``.
    """

    model_config = ConfigDict(
        title="QueryDAO",
        extra="ignore",
        from_attributes=True,
    )

    query: str
    history: Optional[list[dict]] = None
    args: Optional[dict[str, Any]] = None


class ProgressEventDAO(BaseModel):
    """One streamed event from ``SloAgent.invoke``.

    Both the SSE router and the A2A executor consume this shape.

    Fields:
        is_final: True iff this is the last event for the run.
        iteration: Tool-batch counter (0 before any tool call;
            incremented once per turn by ``SloAgent``).
        message: Short human-readable status (e.g.
            ``"Calling tool: bash"``, ``"Tool bash returned"``,
            ``"done"``).
        response: The synthesized final response. Populated only when
            ``is_final`` is True.
        tool_name: Tool the most recent message touched, if any.
        tool_input: Args dict for the tool *call* this event describes
            — populated only on tool-call events; ``None`` otherwise.
        tool_output: Truncated stringified return value of the tool —
            populated only on tool-result events; ``None`` otherwise.
    """

    model_config = ConfigDict(title="ProgressEventDAO")

    is_final: bool = False
    iteration: int = 0
    message: str = ""
    response: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = Field(
        default=None,
        description="Args dict for the tool call this event describes; None for non-tool events.",
    )
    tool_output: Optional[str] = Field(
        default=None,
        description="Truncated stringified return value of the tool; None for non-tool events.",
    )
