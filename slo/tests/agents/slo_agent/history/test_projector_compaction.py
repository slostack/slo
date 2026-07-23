"""Unit tests for the projector compaction boundary (sub-spec 01.a.5)."""

from __future__ import annotations

import uuid
import pytest
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector


def _make_event(
    *,
    kind: str,
    sequence: int,
    turn_id: Optional[str] = None,
    content: Optional[str] = None,
    tool_output: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_calls: Optional[list[dict[str, Any]]] = None,
) -> SessionHistoryEventDAO:
    return SessionHistoryEventDAO(
        event_id=str(uuid.uuid4()),
        session_id="sess-test",
        turn_id=turn_id,
        sequence=sequence,
        kind=kind,
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            tool_output=tool_output,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_calls=tool_calls,
        ),
    )


def _make_completed_turn(
    *,
    turn_id: str,
    start_seq: int,
    user_content: str = "hello",
    assistant_content: str = "world",
) -> list[SessionHistoryEventDAO]:
    return [
        _make_event(kind="run_started", sequence=start_seq, turn_id=turn_id),
        _make_event(
            kind="user_message",
            sequence=start_seq + 1,
            turn_id=turn_id,
            content=user_content,
        ),
        _make_event(
            kind="assistant_message",
            sequence=start_seq + 2,
            turn_id=turn_id,
            content=assistant_content,
        ),
        _make_event(kind="run_completed", sequence=start_seq + 3, turn_id=turn_id),
    ]



@pytest.mark.asyncio
async def test_compaction_summary_emits_human_message() -> None:
    """compaction_summary → HumanMessage starting with '[Previous conversation summary]'."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="hello"),
        _make_event(kind="compaction_summary", sequence=5, content="The session so far: …"),
        *_make_completed_turn(turn_id="t2", start_seq=6, user_content="now do this"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    summary_msgs = [
        m
        for m in messages
        if isinstance(m, HumanMessage)
        and m.content.startswith("[Previous conversation summary]")
    ]
    assert len(summary_msgs) == 1
    assert "The session so far:" in summary_msgs[0].content



@pytest.mark.asyncio
async def test_pre_cut_events_excluded() -> None:
    """Events before compaction_summary.sequence are not in the projected list."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="old message"),
        _make_event(kind="compaction_summary", sequence=5, content="summary"),
        *_make_completed_turn(turn_id="t2", start_seq=6, user_content="new message"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    contents = [m.content for m in messages]
    assert not any("old message" in c for c in contents)



@pytest.mark.asyncio
async def test_tail_events_included() -> None:
    """Events after compaction_summary.sequence are projected normally."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="old message"),
        _make_event(kind="compaction_summary", sequence=5, content="summary"),
        *_make_completed_turn(turn_id="t2", start_seq=6, user_content="new message"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    contents = [m.content for m in messages]
    assert any("new message" in c for c in contents)



@pytest.mark.asyncio
async def test_no_compaction_projects_all() -> None:
    """Without a compaction_summary event, all completed-turn events are projected."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="first"),
        *_make_completed_turn(turn_id="t2", start_seq=5, user_content="second"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    contents = [m.content for m in messages]
    assert any("first" in c for c in contents)
    assert any("second" in c for c in contents)



@pytest.mark.asyncio
async def test_multiple_compactions_uses_last() -> None:
    """When two compaction_summary events exist, only the last sequence is the cut."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="oldest"),
        _make_event(kind="compaction_summary", sequence=5, content="first summary"),
        *_make_completed_turn(turn_id="t2", start_seq=6, user_content="middle"),
        _make_event(kind="compaction_summary", sequence=10, content="second summary"),
        *_make_completed_turn(turn_id="t3", start_seq=11, user_content="newest"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    contents = [m.content for m in messages]
    # oldest and middle are pre-cut
    assert not any("oldest" in c for c in contents)
    assert not any("middle" in c for c in contents)
    # first summary is also pre-cut (sequence 5 < 10)
    first_summaries = [
        m
        for m in messages
        if isinstance(m, HumanMessage) and "first summary" in m.content
    ]
    assert len(first_summaries) == 0
    # second summary is at cut boundary → emitted
    second_summaries = [
        m
        for m in messages
        if isinstance(m, HumanMessage) and "second summary" in m.content
    ]
    assert len(second_summaries) == 1
    # newest is in retained tail
    assert any("newest" in c for c in contents)



@pytest.mark.asyncio
async def test_heal_dangling_still_runs_on_compacted_tail() -> None:
    """MessageContractReconciler synthesises a placeholder for an unanswered tool_use in the retained tail."""
    tool_call_id = "tc-123"
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1),
        _make_event(kind="compaction_summary", sequence=5, content="summary"),
        _make_event(
            kind="run_started",
            sequence=6,
            turn_id="t2",
        ),
        _make_event(
            kind="tool_call",
            sequence=7,
            turn_id="t2",
            tool_call_id=tool_call_id,
            tool_name="bash",
            tool_calls=[
                {
                    "name": "bash",
                    "args": {"command": "ls"},
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ],
        ),
        # tool_result deliberately missing → dangling
        _make_event(kind="run_aborted", sequence=8, turn_id="t2"),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert any(m.tool_call_id == tool_call_id for m in tool_messages)



@pytest.mark.asyncio
async def test_find_last_compaction_sequence_no_compaction() -> None:
    """Returns None when no compaction_summary is present."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1),
    ]
    result = SessionHistoryProjector._find_last_compaction_sequence(events=events)
    assert result is None



@pytest.mark.asyncio
async def test_find_last_compaction_sequence_single() -> None:
    """Returns correct sequence for a single compaction_summary."""
    events = [
        _make_event(kind="user_message", sequence=1, turn_id="t1"),
        _make_event(kind="compaction_summary", sequence=5, content="s"),
    ]
    result = SessionHistoryProjector._find_last_compaction_sequence(events=events)
    assert result == 5



@pytest.mark.asyncio
async def test_append_only_summary_preserves_retained_tail() -> None:
    """Append-only reality: summary lands at the highest sequence, tail still kept.

    The store is append-only, so ``CompactedSessionUpdater`` appends the
    ``compaction_summary`` event *after* the retained tail (a higher
    sequence). The projector must use ``first_kept_entry_id`` — not the
    summary's own sequence — to find the cut, otherwise the retained tail
    (which has a lower sequence than the summary) is wrongly discarded.
    """
    # Pre-cut turn (compacted away).
    pre_cut = _make_completed_turn(turn_id="t1", start_seq=1, user_content="OLD message")
    # Retained turn — the first kept event is its run_started (sequence 5).
    retained = _make_completed_turn(turn_id="t2", start_seq=5, user_content="KEEP this message")
    first_kept_event = retained[0]
    # Summary appended LAST (sequence 9), pointing back at the first kept event.
    summary = _make_event(
        kind="compaction_summary",
        sequence=9,
        content="summary of the old turn",
    )
    summary = summary.model_copy(
        update={
            "payload": summary.payload.model_copy(
                update={"metadata": {"first_kept_entry_id": first_kept_event.event_id}}
            )
        }
    )
    events = [*pre_cut, *retained, summary]

    messages = await SessionHistoryProjector.build_message_history(events=events)
    contents = [m.content for m in messages]

    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content.startswith("[Previous conversation summary]")
    assert any("KEEP this message" in c for c in contents)
    assert not any("OLD message" in c for c in contents)



@pytest.mark.asyncio
async def test_orphaned_retained_tool_result_is_dropped_by_projector() -> None:
    """A legacy bad cut (first_kept points at a tool_result) loads without orphans.

    Safety net for sessions compacted before spec 41's clean-cut fix: when the
    retained tail begins with a tool_result whose tool_call was compacted into
    the summary, the projector (via MessageContractReconciler) drops the
    orphaned ToolMessage so the provider contract holds.
    """
    pre_cut_call = _make_event(
        kind="tool_call",
        sequence=3,
        turn_id="t1",
        tool_call_id="X",
        tool_name="bash",
        tool_calls=[{"name": "bash", "args": {}, "id": "X", "type": "tool_call"}],
    )
    pre_cut_completed = _make_event(kind="run_completed", sequence=4, turn_id="t1")
    retained_orphan_result = _make_event(
        kind="tool_result",
        sequence=6,
        turn_id="t2",
        tool_call_id="X",
        tool_name="bash",
        tool_output="stale tool output",
    )
    retained_assistant = _make_event(
        kind="assistant_message", sequence=7, turn_id="t2", content="fresh reply"
    )
    retained_completed = _make_event(kind="run_completed", sequence=8, turn_id="t2")
    summary = _make_event(kind="compaction_summary", sequence=9, content="summary")
    summary = summary.model_copy(
        update={
            "payload": summary.payload.model_copy(
                update={"metadata": {"first_kept_entry_id": retained_orphan_result.event_id}}
            )
        }
    )
    events = [
        _make_event(kind="run_started", sequence=1, turn_id="t1"),
        _make_event(kind="user_message", sequence=2, turn_id="t1", content="old"),
        pre_cut_call,
        pre_cut_completed,
        _make_event(kind="run_started", sequence=5, turn_id="t2"),
        retained_orphan_result,
        retained_assistant,
        retained_completed,
        summary,
    ]

    messages = await SessionHistoryProjector.build_message_history(events=events)

    # The orphaned tool_result (its tool_call was compacted) is dropped.
    assert not any(
        isinstance(m, ToolMessage) and m.tool_call_id == "X" for m in messages
    )
    contents = " ".join(
        m.content if isinstance(m.content, str) else str(m.content) for m in messages
    )
    assert "fresh reply" in contents
    assert "stale tool output" not in contents



@pytest.mark.asyncio
async def test_empty_assistant_message_event_is_not_replayed() -> None:
    """An empty final assistant_message (no content, no tool calls) is not projected.

    Regression for session bdb87367: a turn ending in an empty assistant_message
    would replay an empty AIMessage and the provider rejects it. The reconciler
    must drop it while keeping the tool pair and the next user message.
    """
    events = [
        _make_event(kind="run_started", sequence=1, turn_id="t1"),
        _make_event(kind="user_message", sequence=2, turn_id="t1", content="hi"),
        _make_event(
            kind="tool_call",
            sequence=3,
            turn_id="t1",
            tool_call_id="X",
            tool_name="bash",
            tool_calls=[{"name": "bash", "args": {}, "id": "X", "type": "tool_call"}],
        ),
        _make_event(
            kind="tool_result", sequence=4, turn_id="t1", tool_call_id="X", tool_output="done"
        ),
        _make_event(kind="assistant_message", sequence=5, turn_id="t1", content=""),  # empty
        _make_event(kind="run_completed", sequence=6, turn_id="t1"),
        _make_event(kind="run_started", sequence=7, turn_id="t2"),
        _make_event(kind="user_message", sequence=8, turn_id="t2", content="Are you done?"),
        _make_event(kind="run_completed", sequence=9, turn_id="t2"),
    ]

    messages = await SessionHistoryProjector.build_message_history(events=events)

    # No empty assistant message survives.
    assert not any(
        isinstance(m, AIMessage) and not m.tool_calls and not (m.content or "").strip()
        for m in messages
    )
    contents = [m.content for m in messages if isinstance(m.content, str)]
    assert any("hi" in c for c in contents)
    assert any("Are you done?" in c for c in contents)
    # The tool pair is intact.
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == "X" for m in messages)



@pytest.mark.asyncio
async def test_summary_content_is_preserved_verbatim() -> None:
    """The HumanMessage content includes the summary text verbatim after the header."""
    summary_text = "User asked about X. Assistant explained Y at length."
    events = [
        _make_event(kind="compaction_summary", sequence=1, content=summary_text),
        *_make_completed_turn(turn_id="t1", start_seq=2),
    ]
    messages = await SessionHistoryProjector.build_message_history(events=events)
    summary_msgs = [
        m
        for m in messages
        if isinstance(m, HumanMessage) and "[Previous conversation summary]" in m.content
    ]
    assert len(summary_msgs) == 1
    assert summary_text in summary_msgs[0].content


@pytest.mark.asyncio
async def test_workflow_update_in_retained_tail_survives_compaction() -> None:
    """A workflow_update note past the compaction boundary stays in context (spec 57.a.4)."""
    events = [
        *_make_completed_turn(turn_id="t1", start_seq=1, user_content="pre-cut turn"),
        _make_event(
            kind="workflow_update",
            sequence=5,
            turn_id="wf-turn-1",
            content="phase 1 done",
        ),
        *_make_completed_turn(turn_id="t2", start_seq=6, user_content="retained turn"),
        _make_event(kind="compaction_summary", sequence=10, content="The session so far: …"),
    ]
    # The boundary keeps everything from the workflow note onward.
    events[-1].payload.metadata["first_kept_entry_id"] = events[4].event_id

    messages = await SessionHistoryProjector.build_message_history(events=events)

    contents = [m.content for m in messages if isinstance(m.content, str)]
    assert "[workflow update] phase 1 done" in contents
    assert "retained turn" in contents
    assert "pre-cut turn" not in contents
