"""Decision-point tests for Context Window Snapshot projection (spec 62.a.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.slo_agent.compaction.constants import DEFAULT_CONTEXT_WINDOW
from src.agents.slo_agent.compaction.context_window import ContextWindowSnapshotService
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.projector import SessionHistoryProjector


def _event(
    *, kind: str, token_usage: int, turn_id: str | None = None, sequence: int = 0
) -> SessionHistoryEventDAO:
    """Build one durable event with an explicit persisted token estimate.

    Args:
        kind (str): Canonical history event kind.
        token_usage (int): Persisted event estimate.
        turn_id (str | None): Optional owning turn.
        sequence (int): Durable append sequence.

    Returns:
        SessionHistoryEventDAO: Event for pure snapshot tests.
    """
    return SessionHistoryEventDAO(
        session_id="session",
        kind=kind,
        turn_id=turn_id,
        sequence=sequence,
        payload=SessionHistoryEventPayloadDAO(content="message", token_usage=token_usage),
    )


def test_build_sums_only_completed_message_producing_events() -> None:
    """The snapshot excludes deltas and incomplete-turn events from its estimate."""
    events: list[SessionHistoryEventDAO] = [
        _event(kind="user_message", token_usage=10, turn_id="complete", sequence=1),
        _event(kind="assistant_delta", token_usage=50, turn_id="complete", sequence=2),
        _event(kind="run_completed", token_usage=0, turn_id="complete", sequence=3),
        _event(kind="user_message", token_usage=30, turn_id="incomplete", sequence=4),
    ]

    snapshot = ContextWindowSnapshotService.build(events=events, model_name="not-a-real-model")

    assert snapshot.estimated_used_tokens == 10
    assert snapshot.context_window_tokens == DEFAULT_CONTEXT_WINDOW
    assert snapshot.estimate_available is True


def test_build_clamps_percent_without_clamping_used_tokens() -> None:
    """An over-cap estimate remains diagnosable while display values clamp."""
    events: list[SessionHistoryEventDAO] = [
        _event(kind="user_message", token_usage=300_000, turn_id="complete", sequence=1),
        _event(kind="run_completed", token_usage=0, turn_id="complete", sequence=2),
    ]

    snapshot = ContextWindowSnapshotService.build(events=events, model_name="not-a-real-model")

    assert snapshot.estimated_used_tokens == 300_000
    assert snapshot.available_tokens == 0
    assert snapshot.consumed_percent == 100.0


def test_without_history_returns_capacity_without_estimate() -> None:
    """The capacity-only form remains useful when durable history is unreadable."""
    snapshot = ContextWindowSnapshotService.without_history(model_name="not-a-real-model")

    assert snapshot.estimate_available is False
    assert snapshot.estimated_used_tokens == 0
    assert snapshot.available_tokens == DEFAULT_CONTEXT_WINDOW


def test_resolve_model_identity_preserves_unknown_model() -> None:
    """Unknown routed identifiers stay stable for cache comparisons."""
    assert ContextWindowSnapshotService.resolve_model_identity(model_name="unknown") == "unknown"


def test_build_resolves_catalog_capacity_and_alias_to_same_canonical_identity() -> None:
    """Canonical catalog names and aliases share capacity and snapshot identity."""
    canonical = ContextWindowSnapshotService.build(events=[], model_name="kimi-for-coding")
    alias = ContextWindowSnapshotService.build(events=[], model_name="kimi-k2")

    assert canonical.model_name == alias.model_name == "kimi-for-coding"
    assert canonical.context_window_tokens == alias.context_window_tokens


def test_context_events_match_projected_message_event_ids_for_complete_boundary_tail() -> None:
    """The load-bearing selection equivalence prevents projector/snapshot drift."""
    summary = _event(kind="compaction_summary", token_usage=7, sequence=5)
    kept_user = _event(kind="user_message", token_usage=11, turn_id="kept", sequence=3)
    kept_assistant = _event(kind="assistant_message", token_usage=13, turn_id="kept", sequence=4)
    terminal = _event(kind="run_completed", token_usage=0, turn_id="kept", sequence=6)
    summary = summary.model_copy(
        update={
            "payload": summary.payload.model_copy(
                update={"metadata": {"first_kept_entry_id": kept_user.event_id}}
            )
        }
    )
    events = [
        _event(kind="user_message", token_usage=99, turn_id="old", sequence=1),
        kept_user,
        kept_assistant,
        summary,
        terminal,
    ]

    selected = SessionHistoryProjector.context_events(events=events)
    messages = asyncio.run(SessionHistoryProjector.build_message_history(events=events))

    assert [event.event_id for event in selected] == [
        summary.event_id,
        kept_user.event_id,
        kept_assistant.event_id,
    ]
    assert len(messages) == len(selected)
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[-1], AIMessage)


def test_context_events_exclude_audit_delta_incomplete_and_parallel_secondary_events() -> None:
    """Only message-producing completed events contribute to durable use."""
    tool_calls = [{"name": "read", "args": {}, "id": "anchor", "type": "tool_call"}]
    anchor = _event(kind="tool_call", token_usage=10, turn_id="done", sequence=1).model_copy(
        update={
            "payload": SessionHistoryEventPayloadDAO(
                tool_calls=tool_calls, tool_call_id="anchor", token_usage=10
            )
        }
    )
    secondary = _event(kind="tool_call", token_usage=20, turn_id="done", sequence=2).model_copy(
        update={
            "payload": SessionHistoryEventPayloadDAO(
                tool_calls=tool_calls, tool_call_id="secondary", token_usage=20
            )
        }
    )
    events = [
        anchor,
        secondary,
        _event(kind="assistant_delta", token_usage=30, turn_id="done", sequence=3),
        _event(kind="run_retrying", token_usage=40, turn_id="done", sequence=4),
        _event(kind="run_completed", token_usage=0, turn_id="done", sequence=5),
        _event(kind="user_message", token_usage=50, turn_id="incomplete", sequence=6),
    ]

    snapshot = ContextWindowSnapshotService.build(events=events, model_name="unknown")

    assert snapshot.estimated_used_tokens == 10


def test_snapshot_pins_d1_divergence_from_auto_compaction_all_event_sum() -> None:
    """D1 intentionally excludes persisted deltas even though auto checks count them."""
    events = [
        _event(kind="user_message", token_usage=10, turn_id="done", sequence=1),
        _event(kind="assistant_delta", token_usage=90, turn_id="done", sequence=2),
        _event(kind="run_completed", token_usage=0, turn_id="done", sequence=3),
    ]

    snapshot = ContextWindowSnapshotService.build(events=events, model_name="unknown")

    assert snapshot.estimated_used_tokens == 10
    assert sum(event.payload.token_usage or 0 for event in events) == 100


def test_context_window_module_has_no_forbidden_runtime_dependencies() -> None:
    """The pure projection layer has no store, session, LLM, or Textual dependency."""
    source = Path("src/agents/slo_agent/compaction/context_window.py").read_text(encoding="utf-8")
    for forbidden in ("import asyncio", "pathlib", "textual", "slo_agent.sessions", "await "):
        assert forbidden not in source
