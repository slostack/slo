"""Compaction never slices a marked tool group (96.a.2 §6.3.5, A8/A12).

Every proof seeds real JSONL through both history adapters, reads the raw
snapshot back, and drives the real compaction command. Failures assert the
active log and metadata are byte-identical and no compaction artifact exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.slo_agent.compaction.compacter import CompactionResult
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
from src.agents.slo_agent.messaging.dao import MessageStoreError
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
) -> SessionHistoryEventDAO:
    """Build one complete marked opening event."""
    ordered_calls: list[dict[str, Any]] = [_call(call_id=item) for item in group.tool_call_ids]
    selected: dict[str, Any] = next(call for call in ordered_calls if call["id"] == call_id)
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(group.group_id), name="call:" + call_id)),
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
) -> SessionHistoryEventDAO:
    """Build one marked result event with its actual core status."""
    metadata: dict[str, object] = group.model_dump(mode="json")
    metadata["tool_result_status"] = status
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(group.group_id), name="result:" + call_id)),
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
    """Build the terminal event that completes a turn."""
    return SessionHistoryEventDAO(
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        kind="run_completed",
    )


def _result_at(*, first_kept_entry_id: str) -> CompactionResult:
    """Build the compact command value for one requested retain boundary."""
    return CompactionResult(
        summary_text="durable summary",
        first_kept_entry_id=first_kept_entry_id,
        cut_point_entry_id=first_kept_entry_id,
        tokens_before=10,
        tokens_after=4,
    )


def _summary(*, session_id: str, first_kept_entry_id: str, sequence: int) -> SessionHistoryEventDAO:
    """Build the compatibility truncation summary for one requested boundary."""
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind="compaction_summary",
        sequence=sequence,
        payload=SessionHistoryEventPayloadDAO(
            content="durable summary",
            token_usage=4,
            metadata={"first_kept_entry_id": first_kept_entry_id},
        ),
    )


def _durable_bytes(*, root: Path, session_id: str) -> tuple[bytes, bytes]:
    """Read active log and metadata bytes without normalization."""
    session_dir: Path = root / session_id
    return (
        session_dir.joinpath("events.jsonl").read_bytes(),
        session_dir.joinpath("session.json").read_bytes(),
    )


def _compaction_artifacts(*, root: Path, session_id: str) -> list[Path]:
    """Return any archive or candidate files left by a compaction attempt."""
    session_dir: Path = root / session_id
    return sorted(
        [
            *session_dir.glob("events.pre-*.jsonl"),
            *session_dir.glob("events.jsonl.compaction-candidate"),
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_boundary_inside_settled_group_keeps_the_whole_group(*, tmp_path: Path, tree: bool) -> None:
    """A cut through a settled group pins to its first event instead of slicing it."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=2, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    opening_a: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="a")
    )
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    result_b: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="b")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))
    source: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    selection = await store.select_message_compaction(
        session_id=session_id, events=source, result=_result_at(first_kept_entry_id=result_b.event_id)
    )
    summary: SessionHistoryEventDAO = await store.compact_to_boundary(
        session_id=session_id,
        events=source,
        result=_result_at(first_kept_entry_id=result_b.event_id),
        turn_id="manual-turn",
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    persisted_ids: list[str] = [event.event_id for event in persisted]
    group_ids: set[str] = {
        _opening(session_id=session_id, group=group, call_id="a").event_id,
        _opening(session_id=session_id, group=group, call_id="b").event_id,
        _result(session_id=session_id, group=group, call_id="a").event_id,
        result_b.event_id,
    }
    assert selection.message_ids == ()
    assert group_ids.issubset(set(persisted_ids))
    assert summary.payload.metadata["first_kept_entry_id"] == opening_a.event_id
    assert persisted[-1].event_id == summary.event_id

    SessionHistoryProjector.validate_tool_groups(events=persisted)
    messages = await SessionHistoryProjector.build_message_history(events=persisted)
    assert [type(message) for message in messages] == [HumanMessage, AIMessage, ToolMessage, ToolMessage]
    assert isinstance(messages[1], AIMessage)
    assert messages[1].tool_calls == [_call(call_id="a"), _call(call_id="b")]
    results = messages[2:]
    assert all(isinstance(message, ToolMessage) for message in results)
    assert [message.tool_call_id for message in results if isinstance(message, ToolMessage)] == ["a", "b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_boundary_inside_disposed_group_keeps_the_whole_group(*, tmp_path: Path, tree: bool) -> None:
    """A no-start group is retained whole and still excluded from model context."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("x",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    opening_x: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="x")
    )
    marker: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_no_start(session_id=session_id, group=group)
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))
    following_turn: str = str(uuid4())
    await store.append_event(
        event=_user_message(session_id=session_id, turn_id=following_turn, content="after")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=following_turn))
    source: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    summary: SessionHistoryEventDAO = await store.compact_to_boundary(
        session_id=session_id,
        events=source,
        result=_result_at(first_kept_entry_id=marker.event_id),
        turn_id="manual-turn",
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    persisted_ids: set[str] = {event.event_id for event in persisted}
    assert {opening_x.event_id, marker.event_id}.issubset(persisted_ids)
    assert summary.payload.metadata["first_kept_entry_id"] == opening_x.event_id

    SessionHistoryProjector.validate_tool_groups(events=persisted)
    messages = await SessionHistoryProjector.build_message_history(events=persisted)
    contents: str = " ".join(str(message.content) for message in messages)
    assert "after" in contents
    assert not any(isinstance(message, ToolMessage) for message in messages)
    assert not any(isinstance(message, AIMessage) and message.tool_calls for message in messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_boundary_before_group_removes_the_whole_group(*, tmp_path: Path, tree: bool) -> None:
    """A cut after the group removes every member together, never a partial slice."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    opening: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="a")
    )
    result: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="a")
    )
    terminal: SessionHistoryEventDAO = await store.append_event(
        event=_terminal(session_id=session_id, turn_id=turn_id)
    )
    source: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    await store.compact_to_boundary(
        session_id=session_id,
        events=source,
        result=_result_at(first_kept_entry_id=terminal.event_id),
        turn_id="manual-turn",
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    persisted_ids: set[str] = {event.event_id for event in persisted}
    assert opening.event_id not in persisted_ids
    assert result.event_id not in persisted_ids
    assert terminal.event_id in persisted_ids
    SessionHistoryProjector.validate_tool_groups(events=persisted)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_unresolved_group_in_excluded_turn_fails_before_select_or_write(
    *, tmp_path: Path, tree: bool
) -> None:
    """An incomplete turn's unresolved group still blocks selection and every write."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    unresolved: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="b")
    )
    source: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    before: tuple[bytes, bytes] = _durable_bytes(root=tmp_path, session_id=session_id)

    with pytest.raises(MessageStoreError):
        await store.select_message_compaction(
            session_id=session_id, events=source, result=_result_at(first_kept_entry_id=unresolved.event_id)
        )
    with pytest.raises(UnsettledToolGroupError):
        await store.compact_to_boundary(
            session_id=session_id,
            events=source,
            result=_result_at(first_kept_entry_id=unresolved.event_id),
            turn_id="manual-turn",
        )

    assert _durable_bytes(root=tmp_path, session_id=session_id) == before
    assert _compaction_artifacts(root=tmp_path, session_id=session_id) == []
    surviving: set[str] = {event.event_id for event in await store.load_events(session_id=session_id)}
    assert unresolved.event_id in surviving


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
@pytest.mark.parametrize("api", ["compact", "truncate"])
async def test_rewrite_refuses_stale_source_after_new_marked_group(
    *, tmp_path: Path, tree: bool, api: str
) -> None:
    """A snapshot captured before a new marked group cannot rewrite current history."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))
    snapshot: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    late_turn: str = str(uuid4())
    late_group: ToolGroupMetadataDAO = _group(attempt_turn_id=late_turn, iteration=1, call_ids=("late",))
    late_opening: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=late_group, call_id="late", content="late call")
    )
    late_result: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=late_group, call_id="late")
    )
    before: tuple[bytes, bytes] = _durable_bytes(root=tmp_path, session_id=session_id)

    with pytest.raises(MessageStoreError):
        if api == "compact":
            await store.compact_to_boundary(
                session_id=session_id,
                events=snapshot,
                result=_result_at(first_kept_entry_id=snapshot[0].event_id),
                turn_id="manual-turn",
            )
        else:
            await store.truncate_to_compaction_boundary(
                session_id=session_id,
                events=snapshot,
                first_kept_entry_id=snapshot[0].event_id,
                summary_event=_summary(
                    session_id=session_id,
                    first_kept_entry_id=snapshot[0].event_id,
                    sequence=snapshot[-1].sequence + 1,
                ),
            )

    assert _durable_bytes(root=tmp_path, session_id=session_id) == before
    assert _compaction_artifacts(root=tmp_path, session_id=session_id) == []
    surviving: set[str] = {event.event_id for event in await store.load_events(session_id=session_id)}
    assert {late_opening.event_id, late_result.event_id}.issubset(surviving)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
@pytest.mark.parametrize("api", ["compact", "truncate"])
@pytest.mark.parametrize("scenario", ["stale", "current"])
async def test_rewrite_refuses_unresolved_opening_before_any_effect(
    *, tmp_path: Path, tree: bool, api: str, scenario: str
) -> None:
    """Both rewrite entries reject an unresolved opening by type, not digest alone.

    ``stale`` passes a previously valid snapshot after a new unresolved opening
    was appended. ``current`` passes the matching current source that itself
    contains the unresolved opening. In both cases raw group validation must win
    over the snapshot digest check, so the exception is
    ``UnsettledToolGroupError`` rather than ``MessageStoreError``.
    """
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))
    snapshot: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    late_turn: str = str(uuid4())
    late_group: ToolGroupMetadataDAO = _group(attempt_turn_id=late_turn, iteration=1, call_ids=("late",))
    unresolved: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=late_group, call_id="late", content="late call")
    )
    source: list[SessionHistoryEventDAO] = (
        snapshot if scenario == "stale" else await store.load_events(session_id=session_id)
    )
    first_kept_entry_id: str = source[0].event_id
    before: tuple[bytes, bytes] = _durable_bytes(root=tmp_path, session_id=session_id)

    with pytest.raises(UnsettledToolGroupError):
        if api == "compact":
            await store.compact_to_boundary(
                session_id=session_id,
                events=source,
                result=_result_at(first_kept_entry_id=first_kept_entry_id),
                turn_id="manual-turn",
            )
        else:
            await store.truncate_to_compaction_boundary(
                session_id=session_id,
                events=source,
                first_kept_entry_id=first_kept_entry_id,
                summary_event=_summary(
                    session_id=session_id,
                    first_kept_entry_id=first_kept_entry_id,
                    sequence=source[-1].sequence + 1,
                ),
            )

    assert _durable_bytes(root=tmp_path, session_id=session_id) == before
    assert _compaction_artifacts(root=tmp_path, session_id=session_id) == []
    surviving: set[str] = {event.event_id for event in await store.load_events(session_id=session_id)}
    assert unresolved.event_id in surviving


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_compatibility_truncation_pins_cut_inside_group_and_keeps_it_whole(
    *, tmp_path: Path, tree: bool
) -> None:
    """A compatibility rewrite succeeds and retains a group whose cut lands inside it."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = str(uuid4())
    await _ensure_session(store=store, session_id=session_id, tmp_path=tmp_path)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, iteration=2, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    opening_a: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="a")
    )
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    result_b: SessionHistoryEventDAO = await store.append_cooperative_event_once(
        event=_result(session_id=session_id, group=group, call_id="b")
    )
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))
    source: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    await store.truncate_to_compaction_boundary(
        session_id=session_id,
        events=source,
        first_kept_entry_id=result_b.event_id,
        summary_event=_summary(
            session_id=session_id,
            first_kept_entry_id=result_b.event_id,
            sequence=source[-1].sequence + 1,
        ),
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    persisted_ids: set[str] = {event.event_id for event in persisted}
    assert {opening_a.event_id, result_b.event_id}.issubset(persisted_ids)
    assert persisted[-1].kind == "compaction_summary"
    assert persisted[-1].payload.metadata["first_kept_entry_id"] == opening_a.event_id
    SessionHistoryProjector.validate_tool_groups(events=persisted)
