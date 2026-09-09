"""Primary in-process stream event contract — canonical location. See stream_event_dao.py for legacy import path.

This module replaces ``ProgressEventDAO`` as the rich event vocabulary for
transcript-visible assistant streaming. The session, TUI, and replay-aware
history code should consume this shape instead of inspecting raw LangChain
chunks or LangGraph update dicts.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AgentStreamEventDAO",
    "StreamEventKind",
]


StreamEventKind = Literal[
    "thinking_start",
    "thinking_delta",
    "thinking_end",
    "text_start",
    "text_delta",
    "text_end",
    "tool_call_start",
    "tool_call_delta",
    "tool_call_end",
    "tool_output_update",
    "tool_result",
    "steering_applied",  # a queued /steer message was drained into model context
    "run_retrying",
    "stream_reconnecting",  # pre-commit provider stream reconnect audit (spec 70)
    # Compaction lifecycle — emitted by the session during overflow recovery:
    "compaction_started",  # session began a forced compaction pass
    "compaction_completed",  # forced compaction succeeded
    "compaction_failed",  # forced compaction failed; original error will surface
    "compaction_retrying",  # compaction succeeded; retry of original prompt starting
    # LLM-driven recovery lifecycle (feature 50) — runtime-only, never terminal:
    "recovery_started",  # loop began recovering from a recoverable failure
    "recovery_succeeded",  # a recovery iteration produced a completed turn
    "recovery_exhausted",  # recovery budget spent / declined; run_failed follows
    "run_completed",
    "run_aborted",
    "run_failed",
    # Sub-agent lifecycle (sub-spec 01-sub-agents 01.f):
    "sub_agent_spawned",  # pool created a child agent process
    "sub_agent_completed",  # child process finished successfully (exit 0)
    "sub_agent_failed",  # child process failed or crashed (non-zero, non-abort)
    "sub_agent_aborted",  # child process was cancelled by the orchestrator (exit 2)
    "sub_agent_reaped",  # child required SIGKILL during an ordered cleanup
]
"""Canonical streamed event kinds surfaced by Slo's interactive runtime."""


class AgentStreamEventDAO(BaseModel):
    """One normalized in-process stream event.

    Attributes:
        kind (StreamEventKind): Discriminator describing the event branch.
        iteration (int): Outer ReAct iteration number.
        block_id (Optional[str]): Stable identifier for one visible
            thinking, text, or streamed tool-call block.
        content_index (int): Provider content-block index within the
            chunk when known.
        delta (Optional[str]): Incremental visible text for ``*_delta`` events.
        content (Optional[str]): Full or terminal content for end/final events.
        tool_name (Optional[str]): Tool name for streamed tool-call or
            completed tool-result events.
        tool_call_id (Optional[str]): Stable tool call identifier.
        tool_input (Optional[dict[str, Any]]): Best-effort parsed tool
            args for finalized tool-call events.
        tool_arguments_delta (Optional[str]): Partial JSON/text fragment
            for streamed tool-call args.
        redacted (bool): True when the provider surfaced only a redacted
            marker and no visible reasoning text.
        metadata (dict[str, Any]): Small debug-only metadata bag. Raw
            provider payloads must not be stuffed here wholesale.
    """

    model_config = ConfigDict(extra="forbid")

    kind: StreamEventKind
    iteration: int = 0
    block_id: Optional[str] = None
    content_index: int = 0
    delta: Optional[str] = None
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_input: Optional[dict[str, Any]] = None
    tool_arguments_delta: Optional[str] = None
    redacted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Sub-agent routing fields (sub-spec 01-sub-agents 01.f):
    sub_agent_id: Optional[str] = None
    """Child session UUID when this event was relayed from a sub-agent process.
    ``None`` for all orchestrator-pane (normal) events."""
    task_id: Optional[str] = None
    """Originating task id when this is a sub-agent event.
    ``None`` for all orchestrator-pane (normal) events."""

    @property
    def is_terminal(self) -> bool:
        """Return True for terminal run events.

        Returns:
            bool: True when the event ends the run.
        """
        return self.kind in {"run_completed", "run_aborted", "run_failed"}

    @property
    def is_sub_agent_event(self) -> bool:
        """Return True when the event was relayed from a child sub-agent process.

        Returns:
            bool: True when ``sub_agent_id`` is non-``None``.
        """
        return self.sub_agent_id is not None

    @property
    def is_visible_delta(self) -> bool:
        """Return True when the event carries visible streaming text.

        Returns:
            bool: True for visible thinking/text delta events.
        """
        return self.kind in {"thinking_delta", "text_delta"}

    @property
    def is_block_boundary(self) -> bool:
        """Return True for start/end events.

        Returns:
            bool: True when the event opens or closes a visible block.
        """
        return self.kind.endswith("_start") or self.kind.endswith("_end")
