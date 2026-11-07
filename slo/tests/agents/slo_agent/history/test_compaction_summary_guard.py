"""Compaction validates raw groups before any summary request (96.a.2 §6.3.1/3/5, A8/A12).

Every proof drives the real session compaction entry (manual ``compact_context``
and automatic ``_run_compaction_if_needed``) over a real flat or tree history
adapter, with an injected external summary provider that captures its request.
No store is mocked and no private collaborator is patched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.compaction.compacter import Compacter
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO
from src.agents.slo_agent.agent import SloAgent

Store = FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore
_HEAVY_TOKENS = 10_000


class CapturingSummaryProvider(FauxChatModel):
    """External summary provider double that records every request it receives."""

    captured: list[list[BaseMessage]] = Field(
        default_factory=list, description="Requests received by this provider double."
    )

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Retain the explicit provider script interface for static and runtime consumers."""
        super().__init__(responses=responses)

    async def _agenerate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        """Record the request, then return the scripted summary response."""
        self.captured.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self._next())])


def _store(*, tmp_path: Path, tree: bool) -> Store:
    """Build one real adapter under the test-owned temporary root."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )


def _group(*, attempt_turn_id: str, call_ids: tuple[str, ...]) -> ToolGroupMetadataDAO:
    """Build validated opening metadata for one attempt iteration."""
    return ToolGroupMetadataDAO(
        group_id=str(uuid5(namespace=UUID(attempt_turn_id), name="tool-group:1")),
        attempt_turn_id=attempt_turn_id,
        iteration=1,
        tool_call_ids=call_ids,
        opened_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    )


def _opening(
    *, session_id: str, group: ToolGroupMetadataDAO, call_id: str, tokens: int = _HEAVY_TOKENS
) -> SessionHistoryEventDAO:
    """Build one complete marked opening event whose arguments are secret."""
    calls: list[dict[str, Any]] = [
        {"id": item, "name": "read", "args": {"path": f"disposed-{item}.txt"}, "type": "tool_call"}
        for item in group.tool_call_ids
    ]
    selected: dict[str, Any] = next(call for call in calls if call["id"] == call_id)
    return SessionHistoryEventDAO(
        event_id=str(uuid5(namespace=UUID(group.group_id), name="call:" + call_id)),
        session_id=session_id,
        turn_id=group.attempt_turn_id,
        iteration=group.iteration,
        kind="tool_call",
        payload=SessionHistoryEventPayloadDAO(
            content="Calling tool.",
            token_usage=tokens,
            tool_call_id=call_id,
            tool_name=selected["name"],
            tool_input=dict(selected["args"]),
            tool_calls=calls,
            metadata={"tool_group_v1": group.model_dump(mode="json")},
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
            token_usage=_HEAVY_TOKENS,
            metadata={"tool_group_v1": metadata, "reason": "cooperative_yield"},
        ),
    )


def _event(
    *,
    session_id: str,
    turn_id: str,
    kind: HistoryEventKind,
    content: Optional[str] = None,
    tokens: int = _HEAVY_TOKENS,
) -> SessionHistoryEventDAO:
    """Build an ordinary settled history event with a heavy token count."""
    return SessionHistoryEventDAO(
        event_id=str(uuid4()),
        session_id=session_id,
        turn_id=turn_id,
        kind=kind,
        payload=SessionHistoryEventPayloadDAO(content=content, token_usage=tokens),
    )


def _build_session(
    *,
    tmp_path: Path,
    tree: bool,
    provider: CapturingSummaryProvider,
    session_id: str,
) -> SloAgentSession:
    """Compose a real session over a real history adapter and the injected provider."""
    return SloAgentSession(
        session_id=session_id,
        workdir=tmp_path,
        enable_history=True,
        history_store=_store(tmp_path=tmp_path, tree=tree),
        agent=SloAgent(llm=provider, cwd=str(tmp_path), tools=[]),
    )


def _log_bytes(*, tmp_path: Path, session_id: str) -> bytes:
    """Read the active log bytes without normalization."""
    return (tmp_path / session_id / "events.jsonl").read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_manual_compaction_refuses_unresolved_raw_without_summary(
    *, tmp_path: Path, tree: bool
) -> None:
    """An unresolved opening blocks manual compaction with zero summary requests."""
    session_id: str = str(uuid4())
    provider = CapturingSummaryProvider(responses=[AIMessage(content="must not be used")])
    session = _build_session(tmp_path=tmp_path, tree=tree, provider=provider, session_id=session_id)
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, call_ids=("a",))
    await store.append_event(
        event=_event(session_id=session_id, turn_id=turn_id, kind="user_message", content="go")
    )
    opening = await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="a")
    )
    await store.append_event(
        event=_event(session_id=session_id, turn_id="t2", kind="user_message", content="later")
    )
    await store.append_event(
        event=_event(session_id=session_id, turn_id="t2", kind="assistant_message", content="ok")
    )
    before: bytes = _log_bytes(tmp_path=tmp_path, session_id=session_id)

    outcome = await session.compact_context()

    assert outcome.status == "failed"
    assert provider.captured == []
    assert _log_bytes(tmp_path=tmp_path, session_id=session_id) == before
    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    assert opening.event_id in {event.event_id for event in persisted}
    assert not any(event.kind == "compaction_summary" for event in persisted)


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_automatic_compaction_refuses_unresolved_raw_without_summary(
    *, tmp_path: Path, tree: bool
) -> None:
    """Automatic compaction raises before the provider and writes nothing."""
    session_id: str = str(uuid4())
    provider = CapturingSummaryProvider(responses=[AIMessage(content="must not be used")])
    session = _build_session(tmp_path=tmp_path, tree=tree, provider=provider, session_id=session_id)
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, call_ids=("a",))
    await store.append_event(
        event=_event(
            session_id=session_id, turn_id=turn_id, kind="user_message", content="go", tokens=200_000
        )
    )
    await store.append_cooperative_event_once(
        event=_opening(session_id=session_id, group=group, call_id="a", tokens=200_000)
    )
    for turn in ("t2", "t3", "t4"):
        await store.append_event(
            event=_event(
                session_id=session_id, turn_id=turn, kind="user_message", content="filler", tokens=200_000
            )
        )
    before: bytes = _log_bytes(tmp_path=tmp_path, session_id=session_id)

    with pytest.raises(UnsettledToolGroupError):
        await session._run_compaction_if_needed(turn_id="auto", force=False)

    assert provider.captured == []
    assert _log_bytes(tmp_path=tmp_path, session_id=session_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_disposed_group_is_omitted_from_summary_but_identities_stay_pinned(
    *, tmp_path: Path, tree: bool
) -> None:
    """A proven no-start group never reaches the summary request; cut ids stay raw."""
    session_id: str = str(uuid4())
    provider = CapturingSummaryProvider(responses=[AIMessage(content="durable summary")])
    session = _build_session(tmp_path=tmp_path, tree=tree, provider=provider, session_id=session_id)
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, call_ids=("a",))
    await store.append_event(
        event=_event(session_id=session_id, turn_id=turn_id, kind="user_message", content="inspect disposed")
    )
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=group))
    await store.append_event(
        event=_event(
            session_id=session_id, turn_id=turn_id, kind="assistant_message", content="settled answer"
        )
    )
    for turn in ("t2", "t3", "t4"):
        await store.append_event(
            event=_event(session_id=session_id, turn_id=turn, kind="user_message", content=f"later {turn}")
        )
        await store.append_event(
            event=_event(session_id=session_id, turn_id=turn, kind="run_completed", tokens=0)
        )
    raw: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    opening_ids: set[str] = {event.event_id for event in raw if event.kind in ("tool_call", "run_retrying")}

    outcome = await session.compact_context()

    assert outcome.status == "compacted"
    assert len(provider.captured) == 1
    request_text: str = str(provider.captured[0][-1].content)
    assert "disposed-a.txt" not in request_text
    assert "tool_call [read]" not in request_text
    assert "inspect disposed" in request_text
    assert "settled answer" in request_text
    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    summary: SessionHistoryEventDAO = next(e for e in persisted if e.kind == "compaction_summary")
    metadata = summary.payload.metadata
    persisted_ids: set[str] = {event.event_id for event in persisted}
    assert opening_ids.isdisjoint(persisted_ids)
    assert metadata["first_kept_entry_id"] in {event.event_id for event in raw}
    assert raw[-2].event_id in persisted_ids
    messages = await SessionHistoryProjector.build_message_history(events=persisted)
    joined: str = " ".join(str(message.content) for message in messages)
    assert "disposed-a.txt" not in joined
    assert "later t4" in joined


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_compacter_validates_before_cut_selection(*, tmp_path: Path, tree: bool) -> None:
    """The compacter itself refuses unresolved raw before choosing a cut."""
    session_id: str = str(uuid4())
    provider = CapturingSummaryProvider(responses=[AIMessage(content="must not be used")])
    store: Store = _store(tmp_path=tmp_path, tree=tree)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name=None)
    turn_id: str = str(uuid4())
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=turn_id, call_ids=("a",))
    await store.append_event(
        event=_event(session_id=session_id, turn_id=turn_id, kind="user_message", content="go")
    )
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    for turn in ("t2", "t3", "t4"):
        await store.append_event(
            event=_event(session_id=session_id, turn_id=turn, kind="user_message", content="filler")
        )
    events: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)

    with pytest.raises(UnsettledToolGroupError):
        await Compacter.compact(events=events, model_name="faux", llm=provider)

    assert provider.captured == []
    assert Compacter.has_viable_cut_point(events=events) is False
