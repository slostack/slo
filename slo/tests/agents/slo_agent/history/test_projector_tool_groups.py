"""Raw marked tool-group validation before context selection or healing (96.a.2 §6.3).

The proofs write through both real history adapters, read raw pages back through
``application_evidence`` and only then project. Malformed raw records are written
through the ordinary append path so the validator—not the cooperative admission
port—is the component under test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.message_contract_reconciler import (
    UnsettledToolGroupError,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO

Store = FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore


def _store(*, tmp_path: Path, tree: bool) -> Store:
    """Build one real adapter under the test-owned temporary root."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )


async def _ensure_session(*, store: Store, session_id: str, tmp_path: Path) -> None:
    """Create the real session directory and metadata."""
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)


def _group(*, attempt_turn_id: str, iteration: int, call_ids: tuple[str, ...]) -> ToolGroupMetadataDAO:
    """Build validated opening metadata for one attempt iteration."""
    return ToolGroupMetadataDAO(
        group_id=str(uuid5(namespace=UUID(attempt_turn_id), name="tool-group:" + str(iteration))),
        attempt_turn_id=attempt_turn_id,
        iteration=iteration,
        tool_call_ids=call_ids,
        opened_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    )


def _call(*, call_id: str, name: str = "read", args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build one complete canonical call entry in source order."""
    return {
        "id": call_id,
        "name": name,
        "args": dict(args if args is not None else {"path": call_id}),
        "type": "tool_call",
    }


def _opening(
    *,
    session_id: str,
    group: ToolGroupMetadataDAO,
    call_id: str,
    content: str = "Calling tool.",
    calls: Optional[list[dict[str, Any]]] = None,
    event_id: Optional[str] = None,
) -> SessionHistoryEventDAO:
    """Build one complete marked opening event."""
    ordered_calls: list[dict[str, Any]] = calls or [_call(call_id=item) for item in group.tool_call_ids]
    selected: dict[str, Any] = next(call for call in ordered_calls if call["id"] == call_id)
    return SessionHistoryEventDAO(
        event_id=event_id or str(uuid5(namespace=UUID(group.group_id), name="call:" + call_id)),
        session_id=session_id,
        turn_id=group.attempt_turn_id,
        iteration=group.iteration,
        kind="tool_call",
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            tool_call_id=call_id,
            tool_name=selected["name"],
            tool_input=dict(selected["args"]),
            tool_calls=ordered_calls,
            metadata={"tool_group_v1": group.model_dump(mode="json")},
        ),
    )


def _result(
    *,
    session_id: str,
    group: ToolGroupMetadataDAO,
    call_id: str,
    status: str = "success",
    output: str = "ok",
    event_id: Optional[str] = None,
) -> SessionHistoryEventDAO:
    """Build one marked result event with its actual core status."""
    metadata: dict[str, object] = group.model_dump(mode="json")
    metadata["tool_result_status"] = status
    return SessionHistoryEventDAO(
        event_id=event_id or str(uuid5(namespace=UUID(group.group_id), name="result:" + call_id)),
        session_id=session_id,
        turn_id=group.attempt_turn_id,
        iteration=group.iteration,
        kind="tool_result",
        payload=SessionHistoryEventPayloadDAO(
            tool_call_id=call_id,
            tool_name="read",
            tool_output=output,
            metadata={"tool_group_v1": metadata},
        ),
    )


def _no_start(*, session_id: str, group: ToolGroupMetadataDAO) -> SessionHistoryEventDAO:
    """Build the affirmative no-start marker for one group."""
    metadata: dict[str, object] = group.model_dump(mode="json")
    metadata["disposition"] = "not_started"
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(group.group_id), name="not-started")),
        session_id=session_id,
        turn_id=group.attempt_turn_id,
        iteration=group.iteration,
        kind="run_retrying",
        payload=SessionHistoryEventPayloadDAO(
            metadata={"tool_group_v1": metadata, "reason": "cooperative_yield"}
        ),
    )


def _user_message(*, session_id: str, turn_id: str, content: str) -> SessionHistoryEventDAO:
    """Build an ordinary user message for the same attempt."""
    return SessionHistoryEventDAO(
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content=content),
    )


def _terminal(*, session_id: str, turn_id: str) -> SessionHistoryEventDAO:
    """Build the terminal event that would otherwise select the turn for context."""
    return SessionHistoryEventDAO(
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        kind="run_completed",
    )


async def _read_all_raw_pages(*, store: Store, session_id: str, limit: int) -> list[SessionHistoryEventDAO]:
    """Read every raw evidence page and carry groups across page boundaries."""
    events: list[SessionHistoryEventDAO] = []
    cursor: int = 0
    while True:
        page = await store.application_evidence(session_id=session_id, after_sequence=cursor, limit=limit)
        events.extend(page.events)
        if page.next_sequence is None:
            return events
        cursor = page.next_sequence


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
@pytest.mark.parametrize("page_limit", [1, 2, 256])
async def test_settled_group_replays_exact_paired_messages(
    *, tmp_path: Path, tree: bool, page_limit: int
) -> None:
    """A settled two-call group survives paged raw read and projects one pair per call."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=3, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="b"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=page_limit
    )
    SessionHistoryProjector.validate_tool_groups(events=raw)
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    assert [type(message) for message in messages] == [HumanMessage, AIMessage, ToolMessage, ToolMessage]
    assert isinstance(messages[1], AIMessage)
    assert messages[1].tool_calls == [_call(call_id="a"), _call(call_id="b")]
    results = messages[2:]
    assert all(isinstance(message, ToolMessage) for message in results)
    assert [message.tool_call_id for message in results if isinstance(message, ToolMessage)] == ["a", "b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_no_start_excludes_only_its_openings_and_keeps_other_group(
    *, tmp_path: Path, tree: bool
) -> None:
    """First full anchor plus marker excludes that group only; partial siblings are allowed."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    disposed: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("x", "y"))
    settled: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=2, call_ids=("z",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=disposed, call_id="x")
    )
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=disposed))
    await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=settled, call_id="z")
    )
    await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=settled, call_id="z")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(store=store, session_id=session_id, limit=2)
    validated: list[SessionHistoryEventDAO] = SessionHistoryProjector.validate_tool_groups(events=raw)
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    assert [type(message) for message in messages] == [HumanMessage, AIMessage, ToolMessage]
    ai_message = messages[1]
    tool_message = messages[2]
    assert isinstance(ai_message, AIMessage)
    assert isinstance(tool_message, ToolMessage)
    assert ai_message.tool_calls == [_call(call_id="z")]
    assert (tool_message.tool_call_id, tool_message.status, tool_message.content) == (
        "z",
        "success",
        "ok",
    )
    excluded_opening_id: str = _opening(session_id=session_id, group=disposed, call_id="x").event_id
    assert all(event.event_id != excluded_opening_id for event in validated)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_missing_result_without_marker_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """An opening with no exact result and no affirmative disposition blocks projection."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_marker_with_actual_result_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """A no-start marker may never coexist with a real result for the group."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=group))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_marker_without_full_anchor_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """A marker with no complete opening anchor is unresolved, never inferred from absence."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=group))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_conflicting_opening_arguments_fail_closed(*, tmp_path: Path, tree: bool) -> None:
    """Two openings for one group must agree on the complete ordered call array."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    conflicting_calls: list[dict[str, Any]] = [
        _call(call_id="a"),
        _call(call_id="b", args={"path": "different"}),
    ]
    await store.append_event(
        event=_opening(session_id=session_id, group=group, call_id="b", calls=conflicting_calls)
    )

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_result_before_its_opening_fails_before_context_selection(
    *, tmp_path: Path, tree: bool
) -> None:
    """A result appended before its opening blocks both context consumers, not healing."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_event(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.context_events(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.context_events(events=raw, excluded_turn_ids={turn_id})
    with pytest.raises(UnsettledToolGroupError):
        await SessionHistoryProjector.build_message_history(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_sibling_result_before_projection_anchor_fails_before_context_selection(
    *, tmp_path: Path, tree: bool
) -> None:
    """A sibling actual result may not precede the first-call projection anchor.

    ``opening(b) -> result(b) -> opening(a) -> result(a)`` has every result after
    its own opening, but only the first call's opening projects the ``AIMessage``.
    Result(b) would therefore be dropped and historically healed, so the complete
    anchor must already be present before any actual result is admitted.
    """
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_event(
        event=_result(session_id=session_id, group=group, call_id="b", status="success", output="b-real")
    )
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(
        event=_result(session_id=session_id, group=group, call_id="a", status="error", output="a-real")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.context_events(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.context_events(events=raw, excluded_turn_ids={turn_id})
    with pytest.raises(UnsettledToolGroupError):
        await SessionHistoryProjector.build_message_history(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_settled_two_call_group_preserves_exact_content_and_status(
    *, tmp_path: Path, tree: bool
) -> None:
    """A valid two-call group replays its real results without healing or invented records."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=2, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="a", status="success", output="a-real")
    )
    await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="b", status="error", output="b-real")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    assert [type(message) for message in messages] == [HumanMessage, AIMessage, ToolMessage, ToolMessage]
    ai_message = messages[1]
    assert isinstance(ai_message, AIMessage)
    assert ai_message.tool_calls == [_call(call_id="a"), _call(call_id="b")]
    first_result = messages[2]
    second_result = messages[3]
    assert isinstance(first_result, ToolMessage)
    assert isinstance(second_result, ToolMessage)
    assert (first_result.tool_call_id, first_result.status, first_result.content) == (
        "a",
        "success",
        "a-real",
    )
    assert (second_result.tool_call_id, second_result.status, second_result.content) == (
        "b",
        "error",
        "b-real",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_first_anchor_opening_after_marker_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """A marker before the required first-call anchor is not a valid disposition."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_event(event=_no_start(session_id=session_id, group=group))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.context_events(events=raw)
    with pytest.raises(UnsettledToolGroupError):
        await SessionHistoryProjector.build_message_history(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_marker_after_full_anchor_allows_missing_sibling(*, tmp_path: Path, tree: bool) -> None:
    """A full first-call anchor plus marker stays valid when sibling writes are partial."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_no_start(session_id=session_id, group=group))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    validated: list[SessionHistoryEventDAO] = SessionHistoryProjector.validate_tool_groups(events=raw)
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    anchor_id: str = _opening(session_id=session_id, group=group, call_id="a").event_id
    assert all(event.event_id != anchor_id for event in validated)
    assert [type(message) for message in messages] == [HumanMessage]


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_duplicate_opening_for_one_call_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """A repeated opening call identity is duplicate evidence, not a second anchor."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(
        event=_opening(session_id=session_id, group=group, call_id="a", event_id=str(uuid4()))
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_extra_result_and_unknown_version_fail_closed(*, tmp_path: Path, tree: bool) -> None:
    """Results outside the declared call set and unknown schemas are rejected."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_result(session_id=session_id, group=group, call_id="a"))
    extra_metadata: dict[str, object] = group.model_dump(mode="json")
    extra_metadata["tool_result_status"] = "success"
    extra_result: SessionHistoryEventDAO = SessionHistoryEventDAO(
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        iteration=1,
        kind="tool_result",
        payload=SessionHistoryEventPayloadDAO(
            tool_call_id="extra",
            tool_name="read",
            tool_output="not declared",
            metadata={"tool_group_v1": extra_metadata},
        ),
    )
    await store.append_event(event=extra_result)

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)

    unknown_metadata: dict[str, object] = group.model_dump(mode="json")
    unknown_metadata["schema_version"] = 2
    unknown: SessionHistoryEventDAO = _opening(session_id=session_id, group=group, call_id="a")
    unknown = unknown.model_copy(
        update={
            "payload": unknown.payload.model_copy(update={"metadata": {"tool_group_v1": unknown_metadata}})
        }
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=[unknown])


@pytest.mark.asyncio
async def test_legacy_unmarked_history_keeps_healing() -> None:
    """Unmarked legacy tool calls still use the existing historical repair path."""
    session_id: str = str(uuid4())
    legacy_call: SessionHistoryEventDAO = SessionHistoryEventDAO(
        session_id=session_id,
        turn_id="legacy",
        kind="tool_call",
        payload=SessionHistoryEventPayloadDAO(
            tool_name="bash",
            tool_call_id="legacy-call",
            tool_input={"command": "true"},
        ),
    )
    terminal: SessionHistoryEventDAO = SessionHistoryEventDAO(
        session_id=session_id, turn_id="legacy", kind="run_completed"
    )

    validated: list[SessionHistoryEventDAO] = SessionHistoryProjector.validate_tool_groups(
        events=[legacy_call, terminal]
    )
    messages = await SessionHistoryProjector.build_message_history(events=validated)

    assert isinstance(messages[0], AIMessage)
    assert isinstance(messages[1], ToolMessage)
    assert messages[1].tool_call_id == "legacy-call"


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_no_start_without_anchor_opening_fails_closed(*, tmp_path: Path, tree: bool) -> None:
    """A partial sibling cannot stand in for the first full group anchor."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=group))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    with pytest.raises(UnsettledToolGroupError):
        SessionHistoryProjector.validate_tool_groups(events=raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_marked_error_result_replays_actual_status(*, tmp_path: Path, tree: bool) -> None:
    """A marked error result must replay with its durable status, not the default success."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="a", status="error", output="boom")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    assert [type(message) for message in messages] == [HumanMessage, AIMessage, ToolMessage]
    assert isinstance(messages[2], ToolMessage)
    assert messages[2].status == "error"
    assert messages[2].tool_call_id == "a"
    assert messages[2].name == "read"
    assert messages[2].content == "boom"


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_marked_success_result_replays_success_status(*, tmp_path: Path, tree: bool) -> None:
    """Normal marked success results keep replaying with success."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="a", status="success")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    raw: list[SessionHistoryEventDAO] = await _read_all_raw_pages(
        store=store, session_id=session_id, limit=256
    )
    messages = await SessionHistoryProjector.build_message_history(events=raw)

    assert isinstance(messages[2], ToolMessage)
    assert messages[2].status == "success"
    assert messages[2].tool_call_id == "a"


@pytest.mark.asyncio
async def test_legacy_unmarked_result_keeps_default_status() -> None:
    """Legacy results without tool_group_v1 metadata retain the prior default behavior."""
    session_id: str = str(uuid4())
    turn_id: str = str(uuid4())
    events: list[SessionHistoryEventDAO] = [
        SessionHistoryEventDAO(
            session_id=session_id,
            turn_id=turn_id,
            kind="tool_call",
            payload=SessionHistoryEventPayloadDAO(
                tool_name="bash",
                tool_call_id="legacy-call",
                tool_input={"command": "true"},
            ),
        ),
        SessionHistoryEventDAO(
            session_id=session_id,
            turn_id=turn_id,
            kind="tool_result",
            payload=SessionHistoryEventPayloadDAO(
                tool_name="bash",
                tool_call_id="legacy-call",
                tool_output="done",
            ),
        ),
        SessionHistoryEventDAO(session_id=session_id, turn_id=turn_id, kind="run_completed"),
    ]

    messages = await SessionHistoryProjector.build_message_history(events=events)

    assert [type(message) for message in messages] == [AIMessage, ToolMessage]
    assert isinstance(messages[1], ToolMessage)
    assert messages[1].status == "success"
    assert messages[1].content == "done"
