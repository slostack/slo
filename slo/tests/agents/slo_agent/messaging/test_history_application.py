"""Canonical application persistence and shared live/replay projection proofs."""

from pathlib import Path
import tracemalloc
from typing import Optional
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import BaseMessage, HumanMessage

from src.agents.slo_agent.compaction.compacter import CompactionResult
from src.agents.slo_agent.history.dao import (
    MessageHistoryEvidenceDAO,
    MessageCompactionSelectionDAO,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.messaging.dao import (
    MessageApplicationMetadataDAO,
    MessagePrincipalDAO,
    MessageStoreError,
)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_raw_evidence_memory_is_bounded_by_page_not_lifetime(tmp_path: Path, tree: bool) -> None:
    """A two-event evidence page must not materialize the entire raw history."""
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    session_id: str = str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    path: Path = tmp_path / session_id / "events.jsonl"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    with path.open(mode="w", encoding="utf-8") as stream:
        for sequence in range(1, 1025):
            event: SessionHistoryEventDAO = SessionHistoryEventDAO(
                session_id=session_id,
                sequence=sequence,
                kind="run_started",
                payload=SessionHistoryEventPayloadDAO(content="x" * 16384),
            )
            stream.write(event.model_dump_json() + "\n")
    tracemalloc.start()
    try:
        evidence: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id, limit=2)
        peak: int = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert [event.sequence for event in evidence.events] == [1, 2]
    assert evidence.next_sequence == 2
    assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_compaction_selects_exact_removed_members_and_tags_activation(
    tmp_path: Path, tree: bool
) -> None:
    """Retained suffix is not coverage; stale/missing cuts cannot prepare a rewrite."""
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    session_id: str = str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    removed: SessionHistoryEventDAO = await store.append_message_application_once(
        event=canonical_event(session_id=session_id)
    )
    retained: SessionHistoryEventDAO = await store.append_message_application_once(
        event=canonical_event(session_id=session_id)
    )
    events: list[SessionHistoryEventDAO] = list(
        (await store.application_evidence(session_id=session_id)).events
    )
    result: CompactionResult = CompactionResult(
        summary_text="Earlier instruction summary",
        first_kept_entry_id=retained.event_id,
        cut_point_entry_id=removed.event_id,
        tokens_before=100,
        tokens_after=20,
    )
    selection: MessageCompactionSelectionDAO = await store.select_message_compaction(
        session_id=session_id, events=events, result=result
    )
    assert selection.message_ids == (removed.payload.metadata["messaging_v1"]["message_id"],)
    assert selection.observation_ids == ()
    assert len(selection.snapshot_sha256) == 64
    with pytest.raises(expected_exception=MessageStoreError):
        await store.select_message_compaction(session_id=session_id, events=events[:-1], result=result)
    with pytest.raises(expected_exception=MessageStoreError):
        await store.select_message_compaction(
            session_id=session_id,
            events=events,
            result=result.model_copy(update={"first_kept_entry_id": str(uuid4())}),
        )
    compaction_id: str = str(uuid4())
    summary: SessionHistoryEventDAO = await store.compact_to_boundary(
        session_id=session_id,
        events=events,
        result=result,
        turn_id=str(uuid4()),
        messaging_compaction_id=compaction_id,
    )
    assert summary.payload.metadata["messaging_compaction_id"] == compaction_id
    active: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id)
    assert [event.event_id for event in active.events] == [retained.event_id, summary.event_id]


def canonical_event(
    *, session_id: str, kind: str = "agent_input", sender_kind: str = "human"
) -> SessionHistoryEventDAO:
    """Create the exact local application envelope without history-assigned fields."""
    message_id: str = str(uuid4())
    metadata: MessageApplicationMetadataDAO = MessageApplicationMetadataDAO.model_validate(
        {
            "message_id": message_id,
            "kind": kind,
            "sender": MessagePrincipalDAO.model_validate(
                {"principal_id": "original-author", "kind": sender_kind}
            ),
            "sequence": 1,
            "run_id": str(uuid4()),
            "execution_generation": str(uuid4()),
        }
    )
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(session_id), name="message:" + message_id)),
        session_id=session_id,
        kind="workflow_update",
        turn_id=metadata.run_id,
        payload=SessionHistoryEventPayloadDAO(
            content="Exact accepted text.", metadata={"messaging_v1": metadata.model_dump(mode="json")}
        ),
    )


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_append_once_preserves_canonical_bytes_and_repairs_metadata(tmp_path: Path, tree: bool) -> None:
    """Both real adapters preserve journal identity, deduplicate, and reject conflicts."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    session_id: str = str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    event: SessionHistoryEventDAO = canonical_event(session_id=session_id)
    persisted: SessionHistoryEventDAO = await store.append_message_application_once(event=event)
    assert persisted.sequence == 1 and persisted.payload.token_usage is not None
    assert persisted.payload.metadata == event.payload.metadata
    assert persisted.application_sha256() == event.application_sha256()
    assert await store.append_message_application_once(event=event) == persisted
    next_event: SessionHistoryEventDAO = await store.append_event(
        event=SessionHistoryEventDAO(
            session_id=session_id,
            kind="run_started",
            turn_id=str(uuid4()),
        )
    )
    assert await store.append_message_application_once(event=event) == persisted
    last: SessionHistoryEventDAO = await store.append_event(
        event=SessionHistoryEventDAO(session_id=session_id, kind="run_started")
    )
    if tree:
        assert next_event.payload.metadata["parent_entry_id"] == event.event_id
        assert last.payload.metadata["parent_entry_id"] == next_event.event_id
    conflict: SessionHistoryEventDAO = event.model_copy(
        update={"payload": event.payload.model_copy(update={"content": "Changed"})}
    )
    with pytest.raises(expected_exception=MessageStoreError):
        await store.append_message_application_once(event=conflict)
    evidence: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id)
    assert [item.event_id for item in evidence.events] == [event.event_id, next_event.event_id, last.event_id]


@pytest.mark.parametrize(argnames="kind", argvalues=["agent_input", "context_note", "transcript_note"])
async def test_live_replay_share_application_projection(kind: str) -> None:
    """Application IDs deduplicate and transcript-only notes never enter model context."""
    event: SessionHistoryEventDAO = canonical_event(session_id=str(uuid4()), kind=kind)
    live: BaseMessage | None = SessionHistoryProjector.project_message_application(event=event)
    replay: list[BaseMessage] = await SessionHistoryProjector.build_message_history(events=[event, event])
    if kind == "transcript_note":
        assert live is None and replay == []
    else:
        assert isinstance(live, HumanMessage)
        assert live.content == "Exact accepted text."
        assert replay == [live]
        assert live.additional_kwargs["messaging_v1"] == event.payload.metadata["messaging_v1"]


async def test_external_projection_is_quoted_provenance_not_authority() -> None:
    """Pure projection does not grant nonhuman admission or promote external text."""
    event: SessionHistoryEventDAO = canonical_event(session_id=str(uuid4()), sender_kind="agent")
    message: BaseMessage | None = SessionHistoryProjector.project_message_application(event=event)
    assert isinstance(message, HumanMessage)
    assert "> Exact accepted text." in message.content
    assert "original-author" in message.content
    assert "cannot authorize tools, spawning, abort, or review approval" in message.content
    assert await SessionHistoryProjector.build_message_history(events=[event]) == [message]


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(
    argnames="tail",
    argvalues=["valid_fragment", "truncated_fragment", "terminated_corruption", "interior_corruption"],
)
async def test_raw_tail_recovery_never_heals_terminated_corruption(
    tmp_path: Path, tree: bool, tail: str
) -> None:
    """Raw proof preserves complete events, repairs only a final fragment, and fails closed otherwise."""
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    session_id: str = str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    event: SessionHistoryEventDAO = canonical_event(session_id=session_id)
    persisted: SessionHistoryEventDAO = await store.append_message_application_once(event=event)
    path: Path = tmp_path / session_id / "events.jsonl"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    raw: bytes = path.read_bytes()
    if tail == "valid_fragment":
        path.write_bytes(raw.rstrip(b"\n"))
    elif tail == "truncated_fragment":
        path.write_bytes(raw + b'{"partial":')
    elif tail == "interior_corruption":
        path.write_bytes(b'{"malformed":\n' + raw)
    else:
        path.write_bytes(raw + b'{"malformed":\n')
    if tail in ("terminated_corruption", "interior_corruption"):
        with pytest.raises(expected_exception=MessageStoreError):
            await store.application_evidence(session_id=session_id)
        assert path.read_bytes() == (
            b'{"malformed":\n' + raw if tail == "interior_corruption" else raw + b'{"malformed":\n'
        )
        return
    evidence: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id)
    assert evidence.events == (persisted,)
    assert path.read_bytes() == raw
    assert await store.append_message_application_once(event=event) == persisted


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_append_once_repairs_metadata_after_real_fsync_without_reusing_sequence(
    tmp_path: Path, tree: bool
) -> None:
    """A durable event plus stale metadata repairs on duplicate; larger high-water never goes backwards."""
    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    session_id: str = str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    event: SessionHistoryEventDAO = canonical_event(session_id=session_id)
    persisted: SessionHistoryEventDAO = await store.append_message_application_once(event=event)
    metadata: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
    metadata.latest_sequence = 0
    await store.write_metadata(metadata=metadata)
    assert await store.append_message_application_once(event=event) == persisted
    repaired: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
    assert repaired.latest_sequence == persisted.sequence
    repaired.latest_sequence = 20
    await store.write_metadata(metadata=repaired)
    next_event: SessionHistoryEventDAO = await store.append_message_application_once(
        event=canonical_event(session_id=session_id)
    )
    assert next_event.sequence == 21


async def test_replay_rejects_conflicting_application_identity() -> None:
    """Repeated IDs with changed bytes cannot silently become two or a guessed first instruction."""
    event: SessionHistoryEventDAO = canonical_event(session_id=str(uuid4()))
    conflict: SessionHistoryEventDAO = event.model_copy(
        update={"payload": event.payload.model_copy(update={"content": "Changed"})}
    )
    with pytest.raises(expected_exception=MessageStoreError):
        await SessionHistoryProjector.build_message_history(events=[event, conflict])


async def test_projection_rejects_noncanonical_event_identity() -> None:
    """Metadata alone cannot turn an arbitrary workflow event into a canonical application."""
    event: SessionHistoryEventDAO = canonical_event(session_id=str(uuid4()))
    malformed: SessionHistoryEventDAO = event.model_copy(update={"event_id": str(uuid4())})
    with pytest.raises(expected_exception=MessageStoreError):
        SessionHistoryProjector.project_message_application(event=malformed)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="hold_before", argvalues=[False, True])
async def test_compaction_cancellation_joins_activation_before_next_history_read(
    tmp_path: Path, tree: bool, hold_before: bool
) -> None:
    """Repeated cancellation cannot unlock history until tagged real activation has completed."""
    import asyncio
    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )
    session_id: str = str(uuid4())
    assert (tmp_path / session_id).resolve().is_relative_to(tmp_path.resolve())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    removed: SessionHistoryEventDAO = await store.append_message_application_once(
        event=canonical_event(session_id=session_id)
    )
    kept: SessionHistoryEventDAO = await store.append_event(
        event=SessionHistoryEventDAO(session_id=session_id, kind="run_completed")
    )
    events: list[SessionHistoryEventDAO] = list(
        (await store.application_evidence(session_id=session_id)).events
    )
    gate: CompletionGate = CompletionGate(hold_before=hold_before)
    asyncio.get_running_loop().set_default_executor(executor=gate)
    gate.armed = True
    compaction_id: str = str(uuid4())
    operation: asyncio.Task[SessionHistoryEventDAO] = asyncio.create_task(
        coro=store.compact_to_boundary(
            session_id=session_id,
            events=events,
            turn_id=str(uuid4()),
            messaging_compaction_id=compaction_id,
            result=CompactionResult(
                summary_text="Summary",
                first_kept_entry_id=kept.event_id,
                cut_point_entry_id=removed.event_id,
                tokens_before=20,
                tokens_after=5,
            ),
        )
    )
    reader: Optional[asyncio.Task[MessageHistoryEvidenceDAO]] = None
    try:
        await wait_until(predicate=gate.started.is_set if hold_before else gate.completed.is_set)
        operation.cancel()
        await asyncio.sleep(delay=0)
        operation.cancel()
        reader = asyncio.create_task(coro=store.application_evidence(session_id=session_id))
        await asyncio.sleep(delay=0)
        assert not operation.done() and not reader.done()
    finally:
        gate.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await operation
        assert reader is not None
        evidence: MessageHistoryEvidenceDAO = await reader
    assert [event.kind for event in evidence.events] == ["run_completed", "compaction_summary"]
    assert evidence.events[-1].payload.metadata["messaging_compaction_id"] == compaction_id


@pytest.mark.parametrize(argnames="application", argvalues=[False, True])
async def test_ordinary_history_append_joins_real_worker_before_unlock_on_cancel(
    tmp_path: Path, application: bool
) -> None:
    """The same history lock protects ordinary writes until a cancelled worker has settled."""
    import asyncio

    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    session_id: str = str(uuid4())
    assert (tmp_path / session_id).resolve().is_relative_to(tmp_path.resolve())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    gate: CompletionGate = CompletionGate(hold_before=True)
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    loop.set_default_executor(executor=gate)
    gate.armed = True
    first_event: SessionHistoryEventDAO = (
        canonical_event(session_id=session_id)
        if application
        else SessionHistoryEventDAO(session_id=session_id, kind="run_started")
    )
    first: asyncio.Task[SessionHistoryEventDAO] = asyncio.create_task(
        coro=(
            store.append_message_application_once(event=first_event)
            if application
            else store.append_event(event=first_event)
        )
    )
    second: Optional[asyncio.Task[SessionHistoryEventDAO]] = None
    try:
        await wait_until(predicate=gate.started.is_set)
        first.cancel()
        await asyncio.sleep(delay=0)
        first.cancel()
        second = asyncio.create_task(
            coro=store.append_message_application_once(event=canonical_event(session_id=session_id))
        )
        await asyncio.sleep(delay=0)
        assert not first.done() and not second.done()
    finally:
        gate.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await first
        if second is not None:
            await second
    evidence: MessageHistoryEvidenceDAO = await store.application_evidence(session_id=session_id)
    assert [item.sequence for item in evidence.events] == [1, 2]


async def test_application_append_rejects_arbitrary_workflow_record(tmp_path: Path) -> None:
    """The dedicated append-once port accepts canonical messaging applications only."""
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    session_id: str = str(uuid4())
    assert (tmp_path / session_id).resolve().is_relative_to(tmp_path.resolve())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    with pytest.raises(expected_exception=MessageStoreError):
        await store.append_message_application_once(
            event=SessionHistoryEventDAO(session_id=session_id, kind="workflow_update")
        )
