"""Restricted cooperative append-once proofs for both real history adapters.

The dedicated port accepts only validated marked tool openings/results and
cooperative/no-start ``run_retrying`` diagnostics. It reuses the flat store's
private raw append machinery, so these tests exercise real files, real fsync
barriers, high-water repair and the joined shielded worker rather than a copy
of the application writer.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4, uuid5

import pytest

from src.agents.slo_agent.history.dao import (
    CooperativeYieldMetadataDAO,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import (
    FileCertification,
    FilesystemSessionHistoryStore,
)
from src.agents.slo_agent.history.message_contract_reconciler import (
    CooperativeYieldSettlementError,
)
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO

Store = FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore


class _ScriptedFileCertification(FileCertification):
    """Real storage barrier with a bounded count of injected fsync failures."""

    def __init__(self, *, failures: int = 0) -> None:
        self.failures: int = failures
        self.certified_paths: list[Path] = []

    def certify(self, *, path: Path) -> None:
        """Record the exact file and fail the first ``failures`` certifications."""
        self.certified_paths.append(path)
        if self.failures > 0:
            self.failures -= 1
            raise OSError("injected events.jsonl fsync failure")
        super().certify(path=path)


class _LostReplyFlatStore(FilesystemSessionHistoryStore):
    """Real flat persistence that withholds one successful append reply."""

    def __init__(self, *, root: Path, file_certification: FileCertification) -> None:
        super().__init__(root=root, file_certification=file_certification)
        self.lose_next_reply: bool = True

    async def append_cooperative_event_once(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Persist through the real owner, then drop the first reply."""
        persisted: SessionHistoryEventDAO = await super().append_cooperative_event_once(event=event)
        if self.lose_next_reply:
            self.lose_next_reply = False
            raise ConnectionError("injected unknown reply after durable append")
        return persisted


class _LostReplyTreeStore(TreeBasedFilesystemSessionHistoryStore):
    """Real tree delegation that withholds one successful append reply."""

    def __init__(self, *, root: Path, file_certification: FileCertification) -> None:
        super().__init__(root=root, file_certification=file_certification)
        self.lose_next_reply: bool = True

    async def append_cooperative_event_once(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Persist through the real tree owner, then drop the first reply."""
        persisted: SessionHistoryEventDAO = await super().append_cooperative_event_once(event=event)
        if self.lose_next_reply:
            self.lose_next_reply = False
            raise ConnectionError("injected unknown reply after durable append")
        return persisted


def _certifying_store(*, tmp_path: Path, tree: bool, certification: FileCertification) -> Store:
    """Build the real adapter with the injected storage-barrier collaborator."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path, file_certification=certification)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path, file_certification=certification)
    )


def _uuid() -> str:
    """Return a fresh canonical UUID."""
    return str(uuid4())


def _store(*, tmp_path: Path, tree: bool) -> Store:
    """Build the real adapter under the test-owned temporary root."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )


def _group(*, attempt_turn_id: str, iteration: int, call_ids: tuple[str, ...]) -> ToolGroupMetadataDAO:
    """Build validated opening metadata for one attempt iteration."""
    return ToolGroupMetadataDAO(
        group_id=str(uuid5(namespace=UUID(attempt_turn_id), name="tool-group:" + str(iteration))),
        attempt_turn_id=attempt_turn_id,
        iteration=iteration,
        tool_call_ids=call_ids,
        opened_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    )


def _tool_call(*, call_id: str) -> dict[str, Any]:
    """Build one complete canonical call entry in source order."""
    return {"id": call_id, "name": "read", "args": {"path": call_id}, "type": "tool_call"}


def _tool_event(
    *,
    session_id: str,
    group: ToolGroupMetadataDAO,
    kind: str,
    call_id: str,
    status: Optional[str] = None,
    content: str = "Calling tool.",
) -> SessionHistoryEventDAO:
    """Build a deterministic opening/result event for ``call_id``."""
    prefix: str = "call:" if kind == "tool_call" else "result:"
    metadata: dict[str, object] = group.model_dump(mode="json")
    if status is not None:
        metadata["tool_result_status"] = status
    calls: list[dict[str, Any]] = [_tool_call(call_id=item) for item in group.tool_call_ids]
    selected: dict[str, Any] = next(call for call in calls if call["id"] == call_id)
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(group.group_id), name=prefix + call_id)),
        session_id=session_id,
        turn_id=group.attempt_turn_id,
        iteration=group.iteration,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            tool_call_id=call_id,
            tool_name=selected["name"],
            tool_input=dict(selected["args"]) if kind == "tool_call" else None,
            tool_calls=calls if kind == "tool_call" else None,
            metadata={"tool_group_v1": metadata},
        ),
    )


def _no_start_event(*, session_id: str, group: ToolGroupMetadataDAO) -> SessionHistoryEventDAO:
    """Build the affirmative no-start ``run_retrying`` marker for a group."""
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


def _with_payload_fields(*, event: SessionHistoryEventDAO, **fields: Any) -> SessionHistoryEventDAO:
    """Return a copy carrying the supplied payload field overrides."""
    return event.model_copy(update={"payload": event.payload.model_copy(update=fields)})


def _diagnostic_event(
    *,
    session_id: str,
    attempt_turn_id: str,
    iteration: int,
    disposition: str = "interrupted",
) -> SessionHistoryEventDAO:
    """Build a validated cooperative diagnostic ``run_retrying`` record."""
    metadata: CooperativeYieldMetadataDAO = CooperativeYieldMetadataDAO(
        run_id=_uuid(),
        boundary_index=0,
        attempt_turn_id=attempt_turn_id,
        iteration=iteration,
        urgent_high_water=3,
        reason="provider",
        disposition=disposition,  # type: ignore[arg-type]
    )
    return SessionHistoryEventDAO(
        event_id=str(
            uuid5(
                namespace=UUID(attempt_turn_id),
                name="cooperative-yield:" + str(iteration) + ":" + disposition,
            )
        ),
        session_id=session_id,
        turn_id=attempt_turn_id,
        iteration=iteration,
        kind="run_retrying",
        payload=SessionHistoryEventPayloadDAO(
            metadata={"cooperative_yield_v1": metadata.model_dump(mode="json")}
        ),
    )


def _with_metadata_key(*, event: SessionHistoryEventDAO, key: str, value: object) -> SessionHistoryEventDAO:
    """Return a copy carrying one extra top-level payload metadata marker."""
    metadata: dict[str, object] = dict(event.payload.metadata)
    metadata[key] = value
    return event.model_copy(update={"payload": event.payload.model_copy(update={"metadata": metadata})})


def _without_metadata_key(*, event: SessionHistoryEventDAO, key: str) -> SessionHistoryEventDAO:
    """Return a copy with one top-level payload metadata key removed."""
    metadata: dict[str, object] = dict(event.payload.metadata)
    metadata.pop(key, None)
    return event.model_copy(update={"payload": event.payload.model_copy(update={"metadata": metadata})})


def _raw_lines(*, tmp_path: Path, session_id: str) -> list[str]:
    """Read the real JSONL bytes persisted by the flat owner."""
    path: Path = tmp_path / session_id / "events.jsonl"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line]


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_persists_exact_event_and_dedups(tmp_path: Path, tree: bool) -> None:
    """Equal identity plus digest returns the durable event without another raw line."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=2, call_ids=("call-a", "call-b"))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    assert persisted.sequence == 1
    assert persisted.payload.token_usage is not None
    assert persisted.payload.metadata == event.payload.metadata
    assert (
        persisted.payload.tool_calls
        == event.payload.tool_calls
        == [
            _tool_call(call_id="call-a"),
            _tool_call(call_id="call-b"),
        ]
    )
    assert persisted.payload.tool_input == {"path": "call-a"}
    assert persisted.application_sha256() == event.application_sha256()
    assert await store.append_cooperative_event_once(event=event) == persisted
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_rejects_incomplete_opening_call_array(
    tmp_path: Path, tree: bool
) -> None:
    """A validated opening must carry the full ordered calls and selected arguments."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=4, call_ids=("call-a", "call-b"))
    opening: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    calls: list[dict[str, Any]] = list(opening.payload.tool_calls or [])
    rejected: list[SessionHistoryEventDAO] = [
        _with_payload_fields(event=opening, tool_calls=None),
        _with_payload_fields(event=opening, tool_calls=[]),
        _with_payload_fields(event=opening, tool_calls=list(reversed(calls))),
        _with_payload_fields(event=opening, tool_calls=calls[:1]),
        _with_payload_fields(event=opening, tool_calls=[{"id": "call-a"}, calls[1]]),
        _with_payload_fields(
            event=opening, tool_calls=[{"id": "call-a", "name": "read", "args": []}, calls[1]]
        ),
        _with_payload_fields(event=opening, tool_calls=[{**calls[0], "name": ""}, calls[1]]),
        _with_payload_fields(event=opening, tool_input=None),
        _with_payload_fields(event=opening, tool_input={"path": "call-b"}),
        _with_payload_fields(event=opening, tool_name="write"),
    ]

    for candidate in rejected:
        with pytest.raises(expected_exception=CooperativeYieldSettlementError):
            await store.append_cooperative_event_once(event=candidate)
        assert _raw_lines(tmp_path=tmp_path, session_id=session_id) == []

    assert (await store.append_cooperative_event_once(event=opening)).sequence == 1
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_rejects_conflict_duplicate_and_unmarked_records(
    tmp_path: Path, tree: bool
) -> None:
    """Conflicting digests, duplicate IDs and unmarked/unknown records fail closed."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=1, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    await store.append_cooperative_event_once(event=event)

    conflict: SessionHistoryEventDAO = event.model_copy(
        update={"payload": event.payload.model_copy(update={"content": "Changed"})}
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=conflict)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    arbitrary: SessionHistoryEventDAO = SessionHistoryEventDAO(session_id=session_id, kind="run_started")
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=arbitrary)

    unmarked: SessionHistoryEventDAO = event.model_copy(
        update={
            "event_id": str(uuid4()),
            "payload": event.payload.model_copy(update={"metadata": {}}),
        }
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=unmarked)

    wrong_identity: SessionHistoryEventDAO = event.model_copy(update={"event_id": str(uuid4())})
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=wrong_identity)

    result_without_status: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_result", call_id="call-a"
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=result_without_status)

    unknown_version_metadata: dict[str, object] = group.model_dump(mode="json")
    unknown_version_metadata["schema_version"] = 2
    unknown_version: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    ).model_copy(
        update={
            "event_id": str(uuid5(namespace=UUID(group.group_id), name="call:call-a")),
            "payload": SessionHistoryEventPayloadDAO(
                content="Calling tool.",
                tool_call_id="call-a",
                tool_name="read",
                metadata={"tool_group_v1": unknown_version_metadata},
            ),
        }
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=unknown_version)

    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_rejects_misplaced_and_conflicting_markers(
    tmp_path: Path, tree: bool
) -> None:
    """Known markers on the wrong kind, including null/schema2 extras, never persist."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    attempt_turn_id: str = _uuid()
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=attempt_turn_id, iteration=1, call_ids=("call-a",))
    opening: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    result: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_result", call_id="call-a", status="error"
    )
    no_start: SessionHistoryEventDAO = _no_start_event(session_id=session_id, group=group)
    await store.append_cooperative_event_once(event=opening)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    rejected: list[SessionHistoryEventDAO] = [
        _with_metadata_key(event=opening, key="cooperative_yield_v1", value=None),
        _with_metadata_key(event=result, key="cooperative_yield_v1", value={"schema_version": 2}),
        _with_metadata_key(event=no_start, key="cooperative_yield_v1", value=None),
        _without_metadata_key(event=no_start, key="reason"),
        _with_metadata_key(event=no_start, key="reason", value="provider"),
    ]
    for candidate in rejected:
        with pytest.raises(expected_exception=CooperativeYieldSettlementError):
            await store.append_cooperative_event_once(event=candidate)
        assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    following: SessionHistoryEventDAO = _tool_event(
        session_id=session_id,
        group=_group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-b",)),
        kind="tool_call",
        call_id="call-b",
    )
    assert (await store.append_cooperative_event_once(event=following)).sequence == 2


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_fails_closed_on_duplicate_raw_identity_and_corruption(
    tmp_path: Path, tree: bool
) -> None:
    """Duplicate raw IDs and unreadable raw records block the write without a new line."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    path: Path = tmp_path / session_id / "events.jsonl"
    duplicate: dict[str, object] = json.loads(_raw_lines(tmp_path=tmp_path, session_id=session_id)[0])
    duplicate["sequence"] = 2
    with path.open(mode="a", encoding="utf-8") as stream:
        stream.write(json.dumps(obj=duplicate, sort_keys=True) + "\n")

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 2

    with path.open(mode="a", encoding="utf-8") as stream:
        stream.write("not-a-json-event\n")
    next_group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-b",))
    next_event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=next_group, kind="tool_call", call_id="call-b"
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=next_event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 3
    assert persisted.sequence == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_accepts_no_start_and_diagnostic_records(
    tmp_path: Path, tree: bool
) -> None:
    """Only the two spec-shaped ``run_retrying`` forms are accepted and deduplicated."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    attempt_turn_id: str = _uuid()
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=attempt_turn_id, iteration=3, call_ids=("call-a",))
    opening: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    result: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_result", call_id="call-a", status="error"
    )
    no_start: SessionHistoryEventDAO = _no_start_event(session_id=session_id, group=group)
    diagnostic: SessionHistoryEventDAO = _diagnostic_event(
        session_id=session_id, attempt_turn_id=attempt_turn_id, iteration=3
    )

    sequences: list[int] = [
        (await store.append_cooperative_event_once(event=item)).sequence
        for item in (opening, result, no_start, diagnostic)
    ]

    assert sequences == [1, 2, 3, 4]
    assert await store.append_cooperative_event_once(event=no_start) == (
        await store.append_cooperative_event_once(event=no_start)
    )
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 4

    invalid_no_start: SessionHistoryEventDAO = no_start.model_copy(
        update={
            "event_id": str(uuid4()),
        }
    )
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=invalid_no_start)

    invalid_diagnostic: SessionHistoryEventDAO = diagnostic.model_copy(update={"event_id": str(uuid4())})
    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=invalid_diagnostic)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_repairs_high_water_after_durable_line(
    tmp_path: Path, tree: bool
) -> None:
    """A durable line plus stale metadata repairs on retry without reusing a sequence."""
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    metadata: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
    metadata.latest_sequence = 0
    await store.write_metadata(metadata=metadata)
    assert await store.append_cooperative_event_once(event=event) == persisted
    repaired: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
    assert repaired.latest_sequence == persisted.sequence

    repaired.latest_sequence = 20
    await store.write_metadata(metadata=repaired)
    next_event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id,
        group=_group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-b",)),
        kind="tool_call",
        call_id="call-b",
    )
    assert (await store.append_cooperative_event_once(event=next_event)).sequence == 21


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_fails_closed_on_redaction_change(
    tmp_path: Path, tree: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redaction that would alter canonical evidence refuses the write."""
    credential: str = "cooperative-redaction-proof-token"
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", credential)
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-a",))
    leaking: SessionHistoryEventDAO = _tool_event(
        session_id=session_id,
        group=group,
        kind="tool_call",
        call_id="call-a",
        content="Calling with " + credential,
    )

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=leaking)
    assert _raw_lines(tmp_path=tmp_path, session_id=session_id) == []

    safe: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )
    assert (await store.append_cooperative_event_once(event=safe)).sequence == 1
    assert credential not in _raw_lines(tmp_path=tmp_path, session_id=session_id)[0]


async def test_cooperative_append_once_joins_cancelled_worker_before_lock_release(
    tmp_path: Path,
) -> None:
    """Repeated caller cancellation cannot release the history lock before the writer settles."""
    from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate, wait_until

    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    gate: CompletionGate = CompletionGate(hold_before=True)
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    loop.set_default_executor(executor=gate)
    gate.armed = True
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=0, call_ids=("call-a", "call-b"))
    first_event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id,
        group=group,
        kind="tool_call",
        call_id="call-a",
    )
    second_event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id,
        group=group,
        kind="tool_call",
        call_id="call-b",
    )
    operation: asyncio.Task[SessionHistoryEventDAO] = asyncio.create_task(
        coro=store.append_cooperative_event_once(event=first_event)
    )
    reader: Optional[asyncio.Task[SessionHistoryEventDAO]] = None
    try:
        await wait_until(predicate=gate.started.is_set)
        operation.cancel()
        await asyncio.sleep(delay=0)
        operation.cancel()
        reader = asyncio.create_task(coro=store.append_cooperative_event_once(event=second_event))
        await asyncio.sleep(delay=0)
        assert not operation.done() and not reader.done()
    finally:
        gate.release.set()
        with pytest.raises(expected_exception=asyncio.CancelledError):
            await operation
        assert reader is not None
        second_persisted: SessionHistoryEventDAO = await reader
    lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert len(lines) == 2
    assert second_persisted.sequence == 2
    assert json.loads(lines[0])["event_id"] == first_event.event_id
    assert json.loads(lines[1])["event_id"] == second_event.event_id


async def test_tree_cooperative_append_preserves_canonical_bytes_and_cursor(
    tmp_path: Path,
) -> None:
    """Tree delegation adds no enrichment and never regresses its persisted cursor."""
    store: TreeBasedFilesystemSessionHistoryStore = TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=1, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    assert "entry_id" not in persisted.payload.metadata
    assert "parent_entry_id" not in persisted.payload.metadata
    assert persisted.application_sha256() == event.application_sha256()
    assert await store.append_cooperative_event_once(event=event) == persisted
    following: SessionHistoryEventDAO = await store.append_event(
        event=SessionHistoryEventDAO(session_id=session_id, kind="run_started")
    )
    assert following.sequence == 2
    assert following.payload.metadata["parent_entry_id"] == persisted.event_id
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 2


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_recertifies_existing_event_before_success(
    tmp_path: Path, tree: bool
) -> None:
    """A complete first line whose fsync failed must be re-fsynced on exact retry."""
    certification: _ScriptedFileCertification = _ScriptedFileCertification(failures=2)
    store: Store = _certifying_store(tmp_path=tmp_path, tree=tree, certification=certification)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=2, call_ids=("call-a", "call-b"))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)

    lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert len(lines) == 1
    first_line: dict[str, object] = json.loads(lines[0])
    assert first_line["event_id"] == event.event_id
    assert first_line["sequence"] == 1
    persisted_first: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate_json(lines[0])
    assert persisted_first.recorded_at == event.recorded_at
    assert persisted_first.application_sha256() == event.application_sha256()
    assert certification.certified_paths[-1] == tmp_path / session_id / "events.jsonl"

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)
    assert persisted.event_id == event.event_id
    assert persisted.sequence == 1
    assert persisted.recorded_at == event.recorded_at
    assert persisted.application_sha256() == event.application_sha256()
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1
    repaired: SessionHistoryMetadataDAO = await store.read_metadata(session_id=session_id)
    assert repaired.latest_sequence == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_cooperative_append_once_recovers_lost_reply_after_successful_certification(
    tmp_path: Path, tree: bool
) -> None:
    """A withheld successful reply retries to the same certified event and single line."""
    certification: _ScriptedFileCertification = _ScriptedFileCertification()
    store: Store = (
        _LostReplyTreeStore(root=tmp_path, file_certification=certification)
        if tree
        else _LostReplyFlatStore(root=tmp_path, file_certification=certification)
    )
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=1, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    with pytest.raises(expected_exception=ConnectionError):
        await store.append_cooperative_event_once(event=event)

    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1
    persisted: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)
    assert persisted.event_id == event.event_id
    assert persisted.sequence == 1
    assert persisted.recorded_at == event.recorded_at
    assert persisted.application_sha256() == event.application_sha256()
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1
