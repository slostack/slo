"""Canonical events → LangChain ``BaseMessage`` history (sub-spec 05.d).

Pure projection. Reads ``SessionHistoryEventDAO``s and produces a
``list[BaseMessage]`` for the next agent turn. Lifecycle-only events
(``session_started``, ``run_started``, ``run_completed``, ...) do not
become LangChain messages — the agent re-emits its own start/end
events at runtime.

Incomplete-turn policy:

- completed turns (terminating in ``run_completed``, ``run_aborted``,
  or ``run_failed``) are included in next-turn context,
- incomplete turns are excluded from next-turn context,
- incomplete turns remain visible in replay (see
  ``ReplayEntryProjector``).
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.message_contract_reconciler import (
    MessageContractReconciler,
)

__all__ = ["SessionHistoryProjector"]


_TERMINAL_KINDS: frozenset[str] = frozenset({"run_completed", "run_aborted", "run_failed"})

_SELF_TERMINAL_KINDS: frozenset[str] = frozenset({"workflow_update"})
"""Kinds whose turn is a synthetic completed turn — terminal by construction.

A ``workflow_update`` event (spec 57.a.4) is persisted between runs as a
one-event turn with a fresh ``turn_id`` and no ``run_started``/``run_completed``
envelope, so its own presence marks the turn complete."""


class SessionHistoryProjector:
    """Project canonical events into ``BaseMessage`` model context."""

    @classmethod
    async def build_message_history(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        excluded_turn_ids: Optional[set[str]] = None,
    ) -> list[BaseMessage]:
        """Rebuild prior conversational messages from completed turns.

        Completed turns are those that ended with a terminal event:
        ``run_completed``, ``run_aborted``, or ``run_failed``. Incomplete
        turns are always excluded.

        When ``excluded_turn_ids`` is supplied, those completed turn ids are
        additionally omitted from this rebuild only. The durable event log is
        not modified; the exclusion is local to this one call. This is used
        when retrying a prompt after compaction so the just-failed turn is not
        immediately replayed into the retry context.

        When a ``compaction_summary`` event is present, the summary is emitted
        first as a ``HumanMessage`` header, followed by the retained tail —
        every completed-turn event from the first kept entry onward. Pre-cut
        events (everything older than the first kept entry) are excluded.

        The retain boundary is the ``payload.metadata["first_kept_entry_id"]``
        the ``Compacter``/``CompactedSessionUpdater`` recorded: the store is
        append-only, so the ``compaction_summary`` event lands at the *end* of
        the log (a higher sequence than the retained tail it precedes
        logically). Cutting on the summary's own sequence would therefore
        discard the very tail the Compacter worked to preserve; cutting on the
        first-kept entry's sequence keeps it. When that pointer is missing or
        does not resolve to a known event the boundary falls back to the
        summary's own sequence (the pre-append-aware behaviour).

        The system prompt is not included — ``SloAgent._build_initial_messages``
        prepends its own. Tool-call ``AIMessage``s preserve their
        ``tool_calls`` arrays so the model sees the same shape it
        originally emitted, and ``ToolMessage`` results carry their
        ``tool_call_id``/``name`` envelope intact.

        Args:
            events (list[SessionHistoryEventDAO]): Canonical events in
                append order.
            excluded_turn_ids (Optional[set[str]]): Optional set of completed
                turn ids to omit from this one history rebuild. Defaults to
                ``None``, which is treated as an empty set.

        Returns:
            list[BaseMessage]: Ordered ``BaseMessage`` history suitable
                for ``SloAgent.invoke(message_history=...)``.
        """
        context_events: list[SessionHistoryEventDAO] = cls._context_event_slice(
            events=events,
            excluded_turn_ids=excluded_turn_ids,
        )
        return MessageContractReconciler.reconcile(messages=cls._to_messages(events=context_events))

    @classmethod
    def context_events(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        excluded_turn_ids: Optional[set[str]] = None,
    ) -> list[SessionHistoryEventDAO]:
        """Return pre-reconciliation durable events selected for model context.

        Args:
            events (list[SessionHistoryEventDAO]): Canonical events in append order.
            excluded_turn_ids (Optional[set[str]]): Completed turns omitted for
                this projection. Defaults to ``None``.

        Returns:
            list[SessionHistoryEventDAO]: Summary-first selected message events.
        """
        return [
            event
            for event in cls._context_event_slice(events=events, excluded_turn_ids=excluded_turn_ids)
            if cls._event_to_message(event=event) is not None
        ]

    @classmethod
    def _context_event_slice(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        excluded_turn_ids: Optional[set[str]],
    ) -> list[SessionHistoryEventDAO]:
        """Select summary plus completed retained events using one replay rule.

        Args:
            events (list[SessionHistoryEventDAO]): Canonical events in append order.
            excluded_turn_ids (Optional[set[str]]): Completed turns to omit.

        Returns:
            list[SessionHistoryEventDAO]: Events before message conversion.
        """
        completed_turn_ids: set[str] = cls._completed_turn_ids(events=events)
        completed_turn_ids.difference_update(excluded_turn_ids or set())
        summary_event: Optional[SessionHistoryEventDAO] = cls._find_last_compaction_summary_event(
            events=events
        )
        if summary_event is None:
            return cls._completed_turn_events(events=events, completed_turn_ids=completed_turn_ids)
        return [summary_event] + cls._retained_tail_events(
            events=events,
            completed_turn_ids=completed_turn_ids,
            keep_from_sequence=cls._resolve_retain_boundary_sequence(
                summary_event=summary_event,
                events=events,
            ),
            summary_event_id=summary_event.event_id,
        )

    @staticmethod
    def _completed_turn_events(
        *,
        events: list[SessionHistoryEventDAO],
        completed_turn_ids: set[str],
    ) -> list[SessionHistoryEventDAO]:
        """Return events in completed turns or events without a turn id.

        Args:
            events (list[SessionHistoryEventDAO]): Events in append order.
            completed_turn_ids (set[str]): Terminal turn ids.

        Returns:
            list[SessionHistoryEventDAO]: Events selected before message filtering.
        """
        return [event for event in events if event.turn_id is None or event.turn_id in completed_turn_ids]

    @staticmethod
    def _retained_tail_events(
        *,
        events: list[SessionHistoryEventDAO],
        completed_turn_ids: set[str],
        keep_from_sequence: int,
        summary_event_id: str,
    ) -> list[SessionHistoryEventDAO]:
        """Return retained events after a compaction boundary.

        Args:
            events (list[SessionHistoryEventDAO]): Events in append order.
            completed_turn_ids (set[str]): Terminal turn ids.
            keep_from_sequence (int): First retained sequence.
            summary_event_id (str): Header summary to omit from the tail.

        Returns:
            list[SessionHistoryEventDAO]: Retained events before message filtering.
        """
        return [
            event
            for event in events
            if event.event_id != summary_event_id
            and event.sequence >= keep_from_sequence
            and (event.turn_id is None or event.turn_id in completed_turn_ids)
        ]

    @classmethod
    def _to_messages(cls, *, events: list[SessionHistoryEventDAO]) -> list[BaseMessage]:
        """Convert selected durable events into unreconciled LangChain messages.

        Args:
            events (list[SessionHistoryEventDAO]): Selected durable event slice.

        Returns:
            list[BaseMessage]: Projected messages in durable order.
        """
        messages: list[BaseMessage] = []
        for event in events:
            message: BaseMessage | None = cls._event_to_message(event=event)
            if message is not None:
                messages.append(message)
        return messages

    @classmethod
    def _resolve_retain_boundary_sequence(
        cls,
        *,
        summary_event: SessionHistoryEventDAO,
        events: list[SessionHistoryEventDAO],
    ) -> int:
        """Return the sequence of the first event to retain after compaction.

        Prefers the ``first_kept_entry_id`` pointer written into the summary's
        ``payload.metadata`` (resolved to that event's sequence). Falls back to
        the summary's own sequence when the pointer is absent or does not
        resolve to a known event — preserving the pre-append-aware behaviour
        for synthetic event lists that place the summary in-line.

        Args:
            summary_event (SessionHistoryEventDAO): The active compaction
                summary event.
            events (list[SessionHistoryEventDAO]): All events in append order.

        Returns:
            int: Sequence of the first retained event.
        """
        first_kept_entry_id: object = summary_event.payload.metadata.get(
            "first_kept_entry_id",
        )
        if isinstance(first_kept_entry_id, str) and first_kept_entry_id:
            for event in events:
                if event.event_id == first_kept_entry_id:
                    return event.sequence
        return summary_event.sequence

    # ---- Private helpers --------------------------------------------------

    @classmethod
    def _completed_turn_ids(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> set[str]:
        """Return the set of turn ids with a terminal lifecycle event.

        Turns are completed by a terminal run event (``run_completed``,
        ``run_aborted``, ``run_failed``) or by containing a self-terminal
        synthetic-turn kind (``workflow_update``, spec 57.a.4).
        """
        completed: set[str] = set()
        for event in events:
            if event.turn_id is None:
                continue
            if event.kind in _TERMINAL_KINDS or event.kind in _SELF_TERMINAL_KINDS:
                completed.add(event.turn_id)
        return completed

    @classmethod
    def _find_last_compaction_sequence(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> Optional[int]:
        """Return the sequence of the most recent compaction_summary event, or None.

        Scans in reverse so the first match found is the chronologically last
        compaction. Returns ``None`` when no compaction has occurred in this
        session, which preserves the pre-compaction projection behaviour.

        Args:
            events (list[SessionHistoryEventDAO]): All events in append order.

        Returns:
            Optional[int]: Sequence of the last compaction_summary event, or
                ``None`` if no compaction has occurred in this session.
        """
        event: Optional[SessionHistoryEventDAO] = cls._find_last_compaction_summary_event(
            events=events,
        )
        return event.sequence if event is not None else None

    @classmethod
    def _find_last_compaction_summary_event(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> Optional[SessionHistoryEventDAO]:
        """Return the most recent compaction_summary event, or None.

        Scans in reverse so the first match found is the chronologically last
        compaction.

        Args:
            events (list[SessionHistoryEventDAO]): All events in append order.

        Returns:
            Optional[SessionHistoryEventDAO]: The last compaction_summary
                event, or ``None`` if no compaction has occurred.
        """
        for event in reversed(events):
            if event.kind == "compaction_summary":
                return event
        return None

    @classmethod
    def _event_to_message(
        cls,
        *,
        event: SessionHistoryEventDAO,
    ) -> BaseMessage | None:
        """Map one canonical event to a LangChain message (or ``None``).

        For parallel tool-call groups, only the anchor event — the one whose
        ``tool_call_id`` matches ``tool_calls[0]["id"]`` — produces an
        ``AIMessage``. Secondary events in the same group return ``None`` to
        prevent duplicate ``tool_use`` block IDs, which the Anthropic API
        rejects with a 400 ``invalid_request_error``.

        ``run_retrying``, ``route_switched``, ``stream_reconnecting``, and ``run_recovering`` are
        diagnostic/audit events (37.a.6, feature 50): they are explicitly
        excluded so audit volume never inflates the next request's context
        (which would defeat the history-aware estimation goal).
        ``assistant_delta`` and every other lifecycle kind also project to
        ``None``.

        ``recovery_observation`` (feature 50) is a synthetic observation
        injected by the recovery loop; it is included in model context as a
        ``HumanMessage`` so the model can reason about the previous failure.

        ``workflow_update`` (spec 57.a.4) is a detached-workflow phase note
        persisted as its own synthetic completed turn; it is included as a
        bracketed ``HumanMessage`` so the agent can answer workflow questions
        from context without an LLM call at delivery time.

        ``compaction_summary`` events are emitted as a ``HumanMessage`` that
        the model reads as the boundary between compacted history and the
        retained tail.
        """
        payload = event.payload
        if event.kind in (
            "run_retrying",
            "route_switched",
            "stream_reconnecting",
            "run_recovering",
            "tool_output_update",
        ):
            return None
        if event.kind == "user_message":
            return HumanMessage(content=payload.content or "")
        if event.kind == "steering_message":
            return HumanMessage(content=payload.content or "")
        if event.kind == "recovery_observation":
            return HumanMessage(content=payload.content or "")
        if event.kind == "workflow_update":
            return HumanMessage(content=f"[workflow update] {payload.content or ''}")
        if event.kind == "assistant_message":
            return AIMessage(content=payload.content or "")
        if event.kind == "tool_call":
            tool_calls: list[dict[str, Any]] = payload.tool_calls or cls._tool_calls_fallback(
                payload=payload,
            )
            if payload.tool_calls and payload.tool_call_id != tool_calls[0]["id"]:
                return None
            return AIMessage(
                content=payload.content or "",
                tool_calls=tool_calls,
            )
        if event.kind == "tool_result":
            return ToolMessage(
                content=payload.tool_output or "",
                name=payload.tool_name or "",
                tool_call_id=payload.tool_call_id or "",
            )
        if event.kind == "assistant_delta":
            return None
        if event.kind == "compaction_summary":
            return HumanMessage(
                content=f"[Previous conversation summary]\n\n{payload.content or ''}",
            )
        return None

    @classmethod
    def _tool_calls_fallback(
        cls,
        *,
        payload: Any,
    ) -> list[dict[str, Any]]:
        """Reconstruct a single tool_call dict when ``payload.tool_calls`` is absent."""
        if payload.tool_name is None and payload.tool_call_id is None:
            return []
        return [
            {
                "name": payload.tool_name or "",
                "args": dict(payload.tool_input or {}),
                "id": payload.tool_call_id or "",
                "type": "tool_call",
            }
        ]
