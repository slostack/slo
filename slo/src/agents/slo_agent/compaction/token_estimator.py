"""Token-usage estimator for persisted session-history events (sub-spec 01.a.1).

Applies the ``ceil(chars / 4)`` heuristic to each event kind.
What "chars" measures differs by message type — see the table below.

┌──────────────────────────────────────────┬────────────────────────────────────────┐
│ Event kind                               │ What we count chars on                 │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ user_message / steering_message          │ payload.content                        │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ assistant_message (text only)            │ payload.content                        │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ assistant_message (with thinking)        │ content chars + thinking chars         │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ tool_call                                │ content chars + JSON(args) per call    │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ tool_result                              │ payload.tool_output                    │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ assistant_delta                          │ payload.delta                          │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ compaction_summary                       │ payload.content                        │
├──────────────────────────────────────────┼────────────────────────────────────────┤
│ run_started / run_completed / lifecycle  │ 0 (no model context contribution)     │
└──────────────────────────────────────────┴────────────────────────────────────────┘

The estimator is intentionally conservative: it counts serialised characters
rather than BPE tokens. Real token counts are approximately chars / 4 for
English prose; code and JSON serialisations are similarly dense.
"""

from __future__ import annotations

import json
import math

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

__all__ = ["TokenEstimator"]


class TokenEstimator:
    """Stateless estimator: one event → one integer token estimate."""

    @classmethod
    def estimate(cls, *, event: SessionHistoryEventDAO) -> int:
        """Return the estimated token count for ``event``.

        Uses ``ceil(chars / 4)`` where ``chars`` is the character count
        of the event's substantive text content. Lifecycle-only events
        (``run_started``, ``run_completed``, ``session_started``, etc.)
        return 0 because they carry no model-context content.

        Args:
            event (SessionHistoryEventDAO): The event to estimate.

        Returns:
            int: Non-negative estimated token count.
        """
        char_count: int = cls._count_chars(event=event)
        return math.ceil(char_count / 4) if char_count > 0 else 0

    # ---- Private helpers --------------------------------------------------

    @classmethod
    def _count_chars(cls, *, event: SessionHistoryEventDAO) -> int:
        """Return the raw character count for the event's text content.

        Args:
            event (SessionHistoryEventDAO): Source event.

        Returns:
            int: Total character count across all text fields that
                contribute to model context.
        """
        kind: str = event.kind
        if kind in ("user_message", "steering_message"):
            return len(event.payload.content or "")
        if kind == "assistant_message":
            return cls._count_assistant_message_chars(event=event)
        if kind == "tool_call":
            return cls._count_tool_call_chars(event=event)
        if kind == "tool_result":
            return len(event.payload.tool_output or "")
        if kind == "assistant_delta":
            return len(event.payload.delta or "")
        if kind == "compaction_summary":
            return len(event.payload.content or "")
        return 0

    @classmethod
    def _count_assistant_message_chars(cls, *, event: SessionHistoryEventDAO) -> int:
        """Count chars for an assistant_message event.

        Includes prose content and serialised tool-call arguments for
        iterations that called tools. Thinking block text is included via
        ``payload.metadata["thinking"]`` when present.

        Args:
            event (SessionHistoryEventDAO): An ``assistant_message`` event.

        Returns:
            int: Total char count.
        """
        total: int = len(event.payload.content or "")
        thinking_text: object = event.payload.metadata.get("thinking")
        if isinstance(thinking_text, str):
            total += len(thinking_text)
        total += cls._provider_extension_char_count(event=event)
        tool_calls: list[dict] = event.payload.tool_calls or []
        for call in tool_calls:
            args: object = call.get("args") or call.get("arguments") or {}
            total += len(json.dumps(args, ensure_ascii=False))
        return total

    @classmethod
    def _count_tool_call_chars(cls, *, event: SessionHistoryEventDAO) -> int:
        """Count chars for a tool_call event.

        Includes the serialised ``tool_calls`` argument payloads and any
        prose content attached to the event.

        Args:
            event (SessionHistoryEventDAO): A ``tool_call`` event.

        Returns:
            int: Total char count.
        """
        total: int = len(event.payload.content or "")
        total += cls._provider_extension_char_count(event=event)
        tool_calls: list[dict] = event.payload.tool_calls or []
        for call in tool_calls:
            args: object = call.get("args") or call.get("arguments") or {}
            total += len(json.dumps(args, ensure_ascii=False))
        if not tool_calls and event.payload.tool_input:
            total += len(json.dumps(event.payload.tool_input, ensure_ascii=False))
        return total

    @staticmethod
    def _provider_extension_char_count(*, event: SessionHistoryEventDAO) -> int:
        """Count one serialized private continuation extension when its anchor owns it.

        Args:
            event (SessionHistoryEventDAO): Assistant or anchor tool-call history event.

        Returns:
            int: Serialized extension length, or zero for legacy/non-anchor events.
        """
        extension = event.payload.provider_message_extension
        if extension is None:
            return 0
        return len(json.dumps(extension.model_dump(mode="json"), ensure_ascii=False))
