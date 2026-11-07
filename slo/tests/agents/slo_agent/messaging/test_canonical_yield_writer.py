"""Trusted producer conflict detection through real history adapters."""

from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO, AgentRuntimePayloadDAO
from src.agents.slo_agent.history.dao import SessionHistoryMetadataDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl
from tests.agents.slo_agent.tool_execution.test_yield_control import RecordingMessageSource, _delivery


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="changed", argvalues=["content", "arguments", "status"])
async def test_canonical_writer_rejects_changed_duplicate(tmp_path: Path, tree: bool, changed: str) -> None:
    """A deterministic ID cannot silently bless a changed incoming payload."""
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id, turn_id = str(uuid4()), str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    control = ToolExecutionControl(
        source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
    )
    control.enter_provider(delivery=_delivery(), attempt_turn_id=turn_id, iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    writer = CooperativeHistoryWriter(session_id=session_id, turn_id=turn_id, control=control, store=store)
    opening = AgentRuntimeEventDAO(
        kind="tool_call",
        payload=AgentRuntimePayloadDAO(
            content="Calling",
            tool_name="read",
            tool_call_id="call",
            tool_calls=[{"id": "call", "name": "read", "args": {"path": "original"}}],
            tool_input={"path": "original"},
        ),
    )
    await writer.persist(event=opening)
    if changed == "status":
        event = AgentRuntimeEventDAO(
            kind="tool_result",
            payload=AgentRuntimePayloadDAO(
                tool_name="read",
                tool_call_id="call",
                tool_output="actual",
                metadata={"core_tool_result_status": "success"},
            ),
        )
        await writer.persist(event=event)
        changed_payload = event.payload.model_copy(update={"metadata": {"core_tool_result_status": "error"}})
    else:
        event = opening
        changed_payload = opening.payload.model_copy(
            update=(
                {"content": "Changed"}
                if changed == "content"
                else {"tool_calls": [{"id": "call", "name": "read", "args": {"path": "changed"}}]}
            )
        )
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.persist(event=event.model_copy(update={"payload": changed_payload}))
    events = await store.load_events(session_id=session_id)
    assert len(events) == (2 if changed == "status" else 1)


async def test_transient_writer_validates_complete_pairing_without_storage() -> None:
    """History-disabled control uses exact groups, not a durability fallback."""
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter

    control = ToolExecutionControl(
        source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
    )
    turn_id = str(uuid4())
    control.enter_provider(delivery=_delivery(), attempt_turn_id=turn_id, iteration=0)
    control.enter_tools(tool_call_ids=("call",))
    writer = CooperativeHistoryWriter(session_id=str(uuid4()), turn_id=turn_id, control=control, store=None)
    await writer.persist(
        event=AgentRuntimeEventDAO(
            kind="tool_call",
            payload=AgentRuntimePayloadDAO(
                tool_name="read",
                tool_call_id="call",
                tool_input={},
                tool_calls=[{"id": "call", "name": "read", "args": {}}],
            ),
        )
    )
    with pytest.raises(CooperativeYieldSettlementError):
        writer.require_settled()
    await writer.persist(
        event=AgentRuntimeEventDAO(
            kind="tool_result",
            payload=AgentRuntimePayloadDAO(
                tool_name="read",
                tool_call_id="call",
                tool_output="actual",
                metadata={"core_tool_result_status": "error"},
            ),
        )
    )
    writer.require_settled()


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_writer_unknown_reply_retains_exact_diagnostic(tmp_path: Path, tree: bool) -> None:
    """An unknown reply never reconstructs audit time or accepts changed correlation."""
    from datetime import timedelta
    from src.agents.slo_agent.history.dao import CooperativeYieldMetadataDAO
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter
    from tests.agents.slo_agent.messaging.test_history_cooperative_append import (
        _LostReplyFlatStore,
        _LostReplyTreeStore,
        _ScriptedFileCertification,
    )

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    certification = _ScriptedFileCertification()
    store = (
        _LostReplyTreeStore(root=root, file_certification=certification)
        if tree
        else _LostReplyFlatStore(root=root, file_certification=certification)
    )
    session_id, turn_id = str(uuid4()), str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    control = ToolExecutionControl(
        source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
    )
    writer = CooperativeHistoryWriter(session_id=session_id, turn_id=turn_id, control=control, store=store)
    diagnostic = CooperativeYieldMetadataDAO(
        run_id=str(uuid4()),
        boundary_index=0,
        attempt_turn_id=turn_id,
        iteration=0,
        urgent_high_water=0,
        reason="provider",
        disposition="requested",
    )
    event = AgentRuntimeEventDAO(
        kind="run_retrying",
        payload=AgentRuntimePayloadDAO(metadata={"cooperative_yield_v1": diagnostic.model_dump(mode="json")}),
    )
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.persist(event=event)
    await writer.persist(
        event=event.model_copy(update={"recorded_at": event.recorded_at + timedelta(seconds=1)})
    )
    persisted = await store.load_events(session_id=session_id)
    assert len(persisted) == 1 and persisted[0].recorded_at == event.recorded_at
    changed = diagnostic.model_copy(update={"urgent_high_water": 1})
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.persist(
            event=event.model_copy(
                update={
                    "payload": AgentRuntimePayloadDAO(
                        metadata={"cooperative_yield_v1": changed.model_dump(mode="json")}
                    )
                }
            )
        )


async def test_transient_writer_detaches_first_opening_from_mutable_source() -> None:
    """Frozen outer records must not let a caller mutate retained argument evidence."""
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter

    control = ToolExecutionControl(
        source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
    )
    writer = CooperativeHistoryWriter(
        session_id=str(uuid4()), turn_id=str(uuid4()), control=control, store=None
    )
    event = AgentRuntimeEventDAO(
        kind="tool_call",
        payload=AgentRuntimePayloadDAO(
            tool_name="read",
            tool_call_id="call",
            tool_input={"path": "original"},
            tool_calls=[{"id": "call", "name": "read", "args": {"path": "original"}}],
        ),
    )
    await writer.persist(event=event)
    assert event.payload.tool_calls is not None
    event.payload.tool_calls[0]["args"]["path"] = "mutated"
    assert event.payload.tool_input is not None
    event.payload.tool_input["path"] = "mutated"
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.persist(event=event)


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
@pytest.mark.parametrize(argnames="missing", argvalues=[False, True, "changed_truth"])
async def test_writer_settlement_rechecks_actual_raw_evidence(
    tmp_path: Path, tree: bool, missing: bool | str
) -> None:
    """A changed raw record after successful append blocks the live continuation barrier."""
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter
    import json

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = (
        TreeBasedFilesystemSessionHistoryStore(root=root)
        if tree
        else FilesystemSessionHistoryStore(root=root)
    )
    session_id, turn_id = str(uuid4()), str(uuid4())
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    control = ToolExecutionControl(
        source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
    )
    writer = CooperativeHistoryWriter(session_id=session_id, turn_id=turn_id, control=control, store=store)
    await writer.persist(
        event=AgentRuntimeEventDAO(
            kind="tool_call",
            payload=AgentRuntimePayloadDAO(
                tool_name="read",
                tool_call_id="call",
                tool_input={},
                tool_calls=[{"id": "call", "name": "read", "args": {}}],
            ),
        )
    )
    await writer.persist(
        event=AgentRuntimeEventDAO(
            kind="tool_result",
            payload=AgentRuntimePayloadDAO(
                tool_name="read",
                tool_call_id="call",
                tool_output="actual",
                metadata={"core_tool_result_status": "error"},
            ),
        )
    )
    path = root / session_id / "events.jsonl"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if missing == "changed_truth":
        rows[1]["payload"]["tool_output"] = "forged"
    elif missing:
        rows.clear()
    else:
        rows[1]["payload"]["tool_call_id"] = "foreign"
    path.write_text(data="\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.certify_settlement()


async def test_writer_identical_payload_reordered_keys_reuses_first_timestamp() -> None:
    """Canonical JSON identity ignores object key order, never bool-versus-number truth."""
    from src.agents.slo_agent.sessions.cooperative_history import CooperativeHistoryWriter
    from datetime import timedelta

    writer = CooperativeHistoryWriter(
        session_id=str(uuid4()),
        turn_id=str(uuid4()),
        control=ToolExecutionControl(
            source=RecordingMessageSource(urgent_high_water=0), on_deferred=lambda _: None
        ),
        store=None,
    )
    event = AgentRuntimeEventDAO(
        kind="tool_call",
        payload=AgentRuntimePayloadDAO(
            tool_name="read",
            tool_call_id="call",
            tool_input={"a": 1, "b": 2},
            tool_calls=[{"id": "call", "name": "read", "args": {"a": 1, "b": 2}}],
        ),
    )
    await writer.persist(event=event)
    reordered = event.model_copy(
        update={
            "recorded_at": event.recorded_at + timedelta(seconds=1),
            "payload": event.payload.model_copy(
                update={
                    "tool_input": {"b": 2, "a": 1},
                    "tool_calls": [{"name": "read", "id": "call", "args": {"b": 2, "a": 1}}],
                }
            ),
        }
    )
    assert await writer.persist(event=reordered)
    changed = reordered.model_copy(
        update={
            "payload": reordered.payload.model_copy(
                update={
                    "tool_input": {"a": True, "b": 2},
                    "tool_calls": [{"id": "call", "name": "read", "args": {"a": True, "b": 2}}],
                }
            )
        }
    )
    with pytest.raises(CooperativeYieldSettlementError):
        await writer.persist(event=changed)
