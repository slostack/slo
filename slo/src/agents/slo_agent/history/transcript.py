"""Replay projector — canonical events → completed transcript entries.

Presentation-only. Consumes ``SessionHistoryEventDAO``s and emits ordered
``TranscriptEntryDAO``s for the TUI to mount the same component widgets it
mounts live (sub-spec 13 components; feature 15 unification), plus an
optional derived markdown rendering for ``transcript.md``. Never writes
canonical events.

Where the former line-based projector produced flat ``(content, classes)``
lines, this one produces one completed entry per user turn, assistant turn,
and tool execution, so a resumed session renders identically to the live
session that produced it.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

__all__ = [
    "TranscriptEntryKind",
    "TranscriptEntryDAO",
    "ReplayEntryProjector",
]


TranscriptEntryKind = Literal["user", "assistant", "tool", "thinking"]
"""Which transcript component a replay entry maps to."""

_ABORTED_NOTE: str = "aborted"
"""Sentinel terminal note marking an aborted assistant turn."""


class TranscriptEntryDAO(BaseModel):
    """One completed transcript entry reconstructed from history.

    This is the replay-time counterpart to the live ``AgentStreamEventDAO``
    stream: where the live path streams token deltas, replay hands the TUI
    already-finished turns. ``extra="forbid"`` keeps raw history payloads
    from leaking through this projection contract.

    Attributes:
        kind (TranscriptEntryKind): Which component to mount.
        iteration (int): Owning ReAct iteration (assistant/tool entries).
        content (Optional[str]): User text for ``kind="user"``.
        reasoning (Optional[str]): Completed reasoning summary text.
        answer (Optional[str]): Completed assistant answer text.
        terminal_note (Optional[str]): ``"aborted"`` or an error string when
            the turn did not complete cleanly; ``None`` otherwise.
        tool_name (Optional[str]): Tool name for ``kind="tool"``.
        tool_input (dict[str, Any]): Parsed tool args for ``kind="tool"``.
        output (Optional[str]): Tool result output for ``kind="tool"``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: TranscriptEntryKind
    iteration: int = 0
    content: Optional[str] = None
    reasoning: Optional[str] = None
    answer: Optional[str] = None
    terminal_note: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    output: Optional[str] = None


class _AssistantTurnState(BaseModel):
    """Mutable accumulator for one in-progress assistant turn during folding.

    Owned exclusively by ``_ReplayEntryBuilder``. Collects the reasoning and
    answer text streamed across ``assistant_delta`` events plus any terminal
    disposition, so the builder can emit a single ``TranscriptEntryDAO`` when
    the turn closes.

    Attributes:
        iteration (int): The owning ReAct iteration.
        reasoning_text (str): Accumulated reasoning summary text.
        answer_text (str): Accumulated answer text.
        aborted (bool): True when the turn ended via ``run_aborted``.
        failed_message (Optional[str]): Error text when the turn failed.
    """

    iteration: int = Field(default=0, description="The owning ReAct iteration.")
    reasoning_text: str = Field(default="", description="Accumulated reasoning summary text.")
    answer_text: str = Field(default="", description="Accumulated answer text.")
    aborted: bool = Field(default=False, description="True when the turn ended via run_aborted.")
    failed_message: Optional[str] = Field(default=None, description="Error text when the turn failed.")

    def terminal_note(self) -> Optional[str]:
        """Return the terminal note for this turn, if any.

        Returns:
            Optional[str]: ``"aborted"`` when aborted, the error string when
                failed, or ``None`` for a cleanly completed turn.
        """
        if self.aborted:
            return _ABORTED_NOTE
        return self.failed_message

    def has_visible_content(self) -> bool:
        """Return whether this turn should produce an entry at all.

        A turn that only emitted tool calls (no reasoning, no answer, no
        terminal note) contributes only its tool entries, mirroring the
        live transcript where such a turn shows no assistant block text.

        Returns:
            bool: True when reasoning, answer, or a terminal note exists.
        """
        return bool(self.reasoning_text or self.answer_text or self.aborted or self.failed_message)


class _ReplayEntryBuilder:
    """Fold an ordered canonical event stream into completed entries.

    Stateful and single-use. Callers drive it by feeding events in append
    order to ``absorb`` and then reading ``finish``. The per-kind handlers
    are dispatched declaratively through ``_handlers`` rather than an
    if/elif ladder, so adding a new event kind is one table entry.
    """

    def __init__(self) -> None:
        """Seed empty folding state and the event-kind dispatch table."""
        self._entries: list[TranscriptEntryDAO] = []
        self._assistant: Optional[_AssistantTurnState] = None
        self._pending_tools: dict[str, TranscriptEntryDAO] = {}
        self._handlers: dict[str, Callable[..., None]] = {
            "user_message": self._absorb_user_message,
            "steering_message": self._absorb_steering_message,
            "assistant_delta": self._absorb_assistant_delta,
            "assistant_message": self._absorb_assistant_message,
            "tool_call": self._absorb_tool_call,
            "tool_result": self._absorb_tool_result,
            "run_aborted": self._absorb_run_aborted,
            "run_failed": self._absorb_run_failed,
        }

    def absorb(self, *, event: SessionHistoryEventDAO) -> None:
        """Fold one canonical event into the running entry list.

        Dispatches to the handler registered for ``event.kind`` and ignores
        kinds with no handler (envelope/terminal-success events carry no
        visible transcript content of their own).

        Args:
            event (SessionHistoryEventDAO): One canonical event in append order.
        """
        handler: Optional[Callable[..., None]] = self._handlers.get(event.kind)
        if handler is None:
            return
        handler(event=event)

    def finish(self) -> list[TranscriptEntryDAO]:
        """Flush any open assistant turn and return the ordered entries.

        Returns:
            list[TranscriptEntryDAO]: Completed entries in transcript order.
        """
        self._flush_assistant()
        return self._entries

    def _absorb_user_message(self, *, event: SessionHistoryEventDAO) -> None:
        """Close the active turn and append a user entry."""
        self._flush_assistant()
        self._entries.append(TranscriptEntryDAO(kind="user", content=event.payload.content or ""))

    def _absorb_steering_message(self, *, event: SessionHistoryEventDAO) -> None:
        """Append a steering message as a prefixed user entry."""
        self._flush_assistant()
        self._entries.append(
            TranscriptEntryDAO(kind="user", content=f"(steer) {event.payload.content or ''}")
        )

    def _absorb_assistant_delta(self, *, event: SessionHistoryEventDAO) -> None:
        """Accumulate one streamed reasoning or answer delta for the turn."""
        turn: _AssistantTurnState = self._ensure_assistant(iteration=event.iteration)
        delta: str = event.payload.delta or ""
        if event.payload.delta_kind == "thinking_delta":
            turn.reasoning_text += delta
            return
        if event.payload.delta_kind == "text_delta":
            turn.answer_text += delta

    def _absorb_assistant_message(self, *, event: SessionHistoryEventDAO) -> None:
        """Adopt the completed answer text and close the assistant turn."""
        turn: _AssistantTurnState = self._ensure_assistant(iteration=event.iteration)
        turn.answer_text = event.payload.content or turn.answer_text
        self._flush_assistant()

    def _absorb_tool_call(self, *, event: SessionHistoryEventDAO) -> None:
        """Close the active turn and append a (so-far resultless) tool entry."""
        self._flush_assistant()
        entry: TranscriptEntryDAO = TranscriptEntryDAO(
            kind="tool",
            iteration=event.iteration,
            tool_name=event.payload.tool_name or "tool",
            tool_input=event.payload.tool_input or {},
        )
        self._entries.append(entry)
        tool_call_id: Optional[str] = event.payload.tool_call_id
        if tool_call_id is not None:
            self._pending_tools[tool_call_id] = entry

    def _absorb_tool_result(self, *, event: SessionHistoryEventDAO) -> None:
        """Attach a tool result to its matching pending tool entry."""
        tool_call_id: Optional[str] = event.payload.tool_call_id
        entry: Optional[TranscriptEntryDAO] = (
            self._pending_tools.pop(tool_call_id, None) if tool_call_id is not None else None
        )
        if entry is None:
            return
        entry.output = event.payload.tool_output or ""

    def _absorb_run_aborted(self, *, event: SessionHistoryEventDAO) -> None:
        """Mark the active turn aborted and close it."""
        turn: _AssistantTurnState = self._ensure_assistant(iteration=event.iteration)
        turn.aborted = True
        self._flush_assistant()

    def _absorb_run_failed(self, *, event: SessionHistoryEventDAO) -> None:
        """Mark the active turn failed and close it."""
        turn: _AssistantTurnState = self._ensure_assistant(iteration=event.iteration)
        turn.failed_message = event.payload.error_message or "unknown error"
        self._flush_assistant()

    def _ensure_assistant(self, *, iteration: int) -> _AssistantTurnState:
        """Return the open assistant turn, creating it on first use.

        Args:
            iteration (int): The owning ReAct iteration.

        Returns:
            _AssistantTurnState: The active turn accumulator.
        """
        if self._assistant is None:
            self._assistant = _AssistantTurnState(iteration=iteration)
        return self._assistant

    def _flush_assistant(self) -> None:
        """Emit the open assistant turn as an entry, if it has content."""
        turn: Optional[_AssistantTurnState] = self._assistant
        self._assistant = None
        if turn is None or not turn.has_visible_content():
            return
        self._entries.append(
            TranscriptEntryDAO(
                kind="assistant",
                iteration=turn.iteration,
                reasoning=turn.reasoning_text or None,
                answer=turn.answer_text or None,
                terminal_note=turn.terminal_note(),
            )
        )


class ReplayEntryProjector:
    """Project canonical events into replay entries and derived markdown.

    Renamed from the former ``TranscriptProjector`` to remove the name
    collision with the live TUI ``TranscriptProjector``. ``build_entries``
    replaces the old flat ``build_transcript_lines``; ``render_markdown`` is
    unchanged and still backs the derived ``transcript.md`` export.
    """

    @classmethod
    def build_entries(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> list[TranscriptEntryDAO]:
        """Project canonical events into ordered completed transcript entries.

        Invoked by ``SloAgentSession.hydrate_transcript_entries`` when a
        session resumes; the TUI mounts one component per returned entry.

        Args:
            events (list[SessionHistoryEventDAO]): Canonical events in append
                order.

        Returns:
            list[TranscriptEntryDAO]: Completed entries in transcript order.
        """
        builder: _ReplayEntryBuilder = _ReplayEntryBuilder()
        for event in events:
            builder.absorb(event=event)
        return builder.finish()

    @classmethod
    def render_markdown(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> str:
        """Render a derived ``transcript.md`` body from canonical events.

        Args:
            events (list[SessionHistoryEventDAO]): Canonical events in append
                order.

        Returns:
            str: A markdown body. Empty when there is nothing to render.
        """
        sections: list[str] = []
        for event in events:
            block: Optional[str] = cls._event_to_markdown(event=event)
            if block is not None:
                sections.append(block)
        if not sections:
            return ""
        return "\n\n".join(sections) + "\n"

    @classmethod
    def _event_to_markdown(
        cls,
        *,
        event: SessionHistoryEventDAO,
    ) -> Optional[str]:
        """Map one canonical event to a markdown block, or ``None`` to skip it.

        Args:
            event (SessionHistoryEventDAO): One canonical event.

        Returns:
            Optional[str]: A markdown section, or ``None`` for non-rendered kinds.
        """
        payload = event.payload
        if event.kind == "user_message":
            return f"## User\n\n{payload.content or ''}"
        if event.kind == "steering_message":
            return f"## Steering\n\n{payload.content or ''}"
        if event.kind == "tool_call":
            tool_name: str = payload.tool_name or "tool"
            args_text: str = cls._format_args(tool_input=payload.tool_input or {})
            return f"### Tool call · `{tool_name}`\n\n```\n{tool_name}({args_text})\n```"
        if event.kind == "tool_result":
            tool_name = payload.tool_name or "tool"
            body: str = payload.tool_output or ""
            return f"### Tool result · `{tool_name}`\n\n```\n{body}\n```"
        if event.kind == "assistant_message":
            return f"## Assistant\n\n{payload.content or ''}"
        if event.kind == "run_aborted":
            return "## Aborted"
        if event.kind == "run_failed":
            return f"## Failed\n\n{payload.error_message or 'unknown error'}"
        return None

    @staticmethod
    def _format_args(*, tool_input: dict[str, Any]) -> str:
        """Render tool args as a compact ``key=value`` string for markdown.

        Args:
            tool_input (dict[str, Any]): Parsed tool arguments.

        Returns:
            str: Comma-separated ``key=value`` pairs; empty when no args.
        """
        return ", ".join(f"{key}={value!r}" for key, value in tool_input.items())
