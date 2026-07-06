"""Per-turn completed-state accumulator for the dual-stream Slo loop."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agents.slo_agent.message_text import assistant_message_text

__all__ = ["TurnStreamAccumulator"]


class TurnStreamAccumulator:
    """Collect completed state from one outer-loop turn.

    The ``messages`` stream emits user-visible deltas. The ``updates``
    stream emits completed node outputs. This helper stores only the
    completed truth needed for final-answer correctness and stop-hook
    evaluation.
    """

    def __init__(self) -> None:
        """Seed empty completed-turn state."""
        self.completed_assistant_message: AIMessage | None = None
        self.completed_tool_messages: list[ToolMessage] = []
        self.completed_messages: list[BaseMessage] = []
        self.final_assistant_text: str = ""

    def absorb_messages(self, *, messages: list[BaseMessage]) -> None:
        """Absorb completed messages from one ``updates`` chunk.

        Args:
            messages (list[BaseMessage]): Messages extracted from one
                LangGraph updates chunk.
        """
        for message in messages:
            self.completed_messages.append(message)
            if isinstance(message, AIMessage):
                self.completed_assistant_message = message
                self.final_assistant_text = assistant_message_text(message=message)
                continue
            if isinstance(message, ToolMessage):
                self.completed_tool_messages.append(message)
