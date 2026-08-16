"""Manual Compaction session-operation tests (spec 62.a.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.sessions.service import SloAgentSession


def _viable_events() -> list[SessionHistoryEventDAO]:
    """Build two turns whose older event lies outside the retained token tail.

    Returns:
        list[SessionHistoryEventDAO]: Events with one valid manual cut point.
    """
    return [
        SessionHistoryEventDAO(
            session_id="session",
            kind="user_message",
            turn_id="old",
            sequence=1,
            payload=SessionHistoryEventPayloadDAO(content="old", token_usage=25_000),
        ),
        SessionHistoryEventDAO(
            session_id="session",
            kind="user_message",
            turn_id="recent",
            sequence=2,
            payload=SessionHistoryEventPayloadDAO(content="recent", token_usage=25_000),
        ),
        SessionHistoryEventDAO(
            session_id="session",
            kind="run_completed",
            turn_id="recent",
            sequence=3,
            payload=SessionHistoryEventPayloadDAO(token_usage=0),
        ),
    ]


def _session(
    *, events: list[SessionHistoryEventDAO], enabled: bool = True
) -> tuple[SloAgentSession, MagicMock]:
    """Build a history-backed session test fixture.

    Args:
        events (list[SessionHistoryEventDAO]): Events returned by the store.
        enabled (bool): Whether session history is enabled.

    Returns:
        tuple[SloAgentSession, MagicMock]: Session and its store mock.
    """
    store: MagicMock = MagicMock()
    store.session_exists = AsyncMock(return_value=True)
    store.load_events = AsyncMock(return_value=events)
    store.compact_to_boundary = AsyncMock()
    store.ensure_session = AsyncMock(
        return_value=SessionHistoryMetadataDAO(session_id="session", workdir=Path("/tmp"))
    )
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="summary")]), tools=[])
    return (
        SloAgentSession(
            agent=agent,
            workdir=Path("/tmp"),
            session_id="session",
            history_store=store if enabled else None,
            enable_history=enabled,
        ),
        store,
    )


@pytest.mark.asyncio
async def test_compact_context_rejects_when_session_lock_is_held() -> None:
    """Manual Compaction rejects before touching the store while a prompt owns the lock."""
    session, store = _session(events=[])
    await session._lock.acquire()
    try:
        result = await session.compact_context()
    finally:
        session._lock.release()

    assert result.status == "unavailable"
    assert result.detail == "cannot compact while a prompt is in flight; run /abort first"
    store.session_exists.assert_not_awaited()
    store.load_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_returns_nothing_to_compact_for_empty_history() -> None:
    """An empty durable session is a successful no-op."""
    session, store = _session(events=[])

    result = await session.compact_context()

    assert result.status == "nothing_to_compact"
    store.compact_to_boundary.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_window_snapshot_reports_capacity_when_history_is_disabled() -> None:
    """Capacity remains visible when no durable estimate can be made."""
    session, _ = _session(events=[], enabled=False)

    snapshot = await session.context_window_snapshot()

    assert snapshot.estimate_available is False
    assert snapshot.context_window_tokens > 0


@pytest.mark.asyncio
async def test_compact_context_reports_exact_disabled_history_detail_without_io() -> None:
    """Disabled history is unavailable and never touches the injected store."""
    session, store = _session(events=[], enabled=False)

    result = await session.compact_context()

    assert result.status == "unavailable"
    assert result.detail == "session history is disabled; there is nothing to compact"
    store.session_exists.assert_not_awaited()
    store.load_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_returns_noop_for_absent_session_without_creating_history() -> None:
    """A brand-new session remains byte-free after Manual Compaction no-ops."""
    session, store = _session(events=[])
    store.session_exists = AsyncMock(return_value=False)

    result = await session.compact_context()

    assert result.status == "nothing_to_compact"
    store.load_events.assert_not_awaited()
    store.ensure_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_reports_unreadable_history_with_exact_detail() -> None:
    """Parse/load failure is an unavailable result before model preparation."""
    session, store = _session(events=[])
    store.load_events = AsyncMock(side_effect=OSError("broken log"))

    result = await session.compact_context()

    assert result.status == "unavailable"
    assert result.detail == "session history is unavailable; try again after repairing the session"


@pytest.mark.asyncio
async def test_compact_context_ensures_history_after_viable_cut_before_model_readiness() -> None:
    """The viable manual path establishes durable metadata before waking the model."""
    viable_events: list[SessionHistoryEventDAO] = _viable_events()
    session, store = _session(events=viable_events)
    calls: list[str] = []
    session._ensure_history_session = AsyncMock(side_effect=lambda: calls.append("history"))
    session._ensure_manual_compaction_agent_ready = AsyncMock(side_effect=lambda: calls.append("model"))
    session._run_manual_compaction = AsyncMock(return_value=MagicMock(status="compacted"))

    await session.compact_context()

    assert calls == ["history", "model"]


@pytest.mark.asyncio
async def test_compact_context_passes_validated_events_without_a_second_load() -> None:
    """The forced pipeline receives exactly the one measured durable event list."""
    viable_events: list[SessionHistoryEventDAO] = _viable_events()
    session, store = _session(events=viable_events)
    session._run_compaction_if_needed = AsyncMock()

    result = await session.compact_context()

    assert result.status == "compacted"
    kwargs = session._run_compaction_if_needed.await_args.kwargs
    assert kwargs["events"] is viable_events
    assert kwargs["force"] is True
    assert store.load_events.await_count == 2  # validated handoff plus one post-operation refresh
