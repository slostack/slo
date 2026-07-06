"""Full-fidelity runtime trace events — canonical location. See runtime_event_dao.py for legacy import path.

The render-facing ``ProgressEventDAO`` stream is intentionally lossy:
tool outputs are truncated and assistant tool-call messages are
normalised into short status lines. This module defines a second,
parallel event stream — ``AgentRuntimeEventDAO`` — that preserves the
raw detail required for canonical persistence and deterministic replay.

The agent emits trace events through a caller-supplied
``AgentRuntimeHandler``. Trace-handler exceptions intentionally
**propagate** (unlike the render-subscriber path which swallows them);
history capture is a correctness seam, not best-effort telemetry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TraceEventKind",
    "AgentRuntimePayloadDAO",
    "AgentRuntimeEventDAO",
    "AgentRuntimeHandler",
]


TraceEventKind = Literal[
    "run_started",
    "steering_message",
    "assistant_message",
    "assistant_delta",
    "tool_call",
    "tool_result",
    "run_completed",
    "run_aborted",
    "run_failed",
]


class AgentRuntimePayloadDAO(BaseModel):
    """Full-fidelity runtime payload for one trace event.

    Each ``TraceEventKind`` uses a different subset of fields.
    ``assistant_delta`` events use the delta-related fields added here.
    """

    model_config = ConfigDict(extra="ignore")

    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_output: Optional[str] = None
    error_message: Optional[str] = None
    delta_kind: Optional[str] = None
    block_id: Optional[str] = None
    delta: Optional[str] = None
    redacted: Optional[bool] = None
    tool_arguments_delta: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeEventDAO(BaseModel):
    """One runtime trace event emitted from ``SloAgent.invoke``."""

    model_config = ConfigDict(extra="ignore")

    kind: TraceEventKind
    iteration: int = 0
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: AgentRuntimePayloadDAO = Field(default_factory=AgentRuntimePayloadDAO)


AgentRuntimeHandler = Callable[[AgentRuntimeEventDAO], Awaitable[None]]
"""Async callback receiving full-fidelity runtime trace events.

Failures propagate — the caller (typically ``SloAgentSession``) is
expected to treat history capture as part of the prompt contract.
"""
