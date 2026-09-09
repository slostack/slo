"""Unit tests for CompactedSessionUpdater.

All tests use a lightweight in-memory mock store. No filesystem I/O, no LLM
calls. CompactionResult is constructed inline; the test does not import from
compacter.py to avoid a dependency on the LLM layer.
"""

from __future__ import annotations

import pytest

from src.agents.slo_agent.compaction.compacted_session_updater import (
    CompactedSessionUpdater,
)
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)

# ---------------------------------------------------------------------------
# Minimal CompactionResult stand-in (avoids importing the LLM-dependent compacter)
# ---------------------------------------------------------------------------


class _CompactionResult:
    """Minimal stand-in for CompactionResult used in tests."""

    def __init__(
        self,
        *,
        summary_text: str,
        first_kept_entry_id: str,
        cut_point_entry_id: str,
        tokens_before: int,
        tokens_after: int,
    ) -> None:
        self.summary_text = summary_text
        self.first_kept_entry_id = first_kept_entry_id
        self.cut_point_entry_id = cut_point_entry_id
        self.tokens_before = tokens_before
        self.tokens_after = tokens_after


# ---------------------------------------------------------------------------
# Minimal async mock store
# ---------------------------------------------------------------------------


class _InMemoryStore:
    """Minimal async mock store accumulating events in a list.

    Structurally satisfies SessionHistoryStoreProtocol for the subset of
    methods used by CompactedSessionUpdater (only append_event).
    """

    def __init__(self) -> None:
        self.appended: list[SessionHistoryEventDAO] = []
        self._seq: int = 0

    async def append_event(
        self,
        *,
        event: SessionHistoryEventDAO,
    ) -> SessionHistoryEventDAO:
        """Stamp event with a monotonically increasing sequence and accumulate it."""
        self._seq += 1
        stamped: SessionHistoryEventDAO = event.model_copy(
            update={"sequence": self._seq},
        )
        self.appended.append(stamped)
        return stamped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    *,
    summary_text: str = "Summary of the compacted history.",
    first_kept_entry_id: str = "evt-first-kept",
    cut_point_entry_id: str = "evt-cut-point",
    tokens_before: int = 8000,
    tokens_after: int = 300,
) -> _CompactionResult:
    """Return a ``_CompactionResult`` with sensible defaults."""
    return _CompactionResult(
        summary_text=summary_text,
        first_kept_entry_id=first_kept_entry_id,
        cut_point_entry_id=cut_point_entry_id,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_appends_exactly_one_event() -> None:
    """update() calls store.append_event exactly once."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert len(store.appended) == 1


@pytest.mark.asyncio
async def test_update_event_has_compaction_summary_kind() -> None:
    """The appended event has kind='compaction_summary'."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert store.appended[0].kind == "compaction_summary"


@pytest.mark.asyncio
async def test_update_event_carries_session_id() -> None:
    """The appended event carries the caller-provided session_id."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-xyz",
        result=result,
        store=store,
    )

    assert store.appended[0].session_id == "session-xyz"


@pytest.mark.asyncio
async def test_update_payload_content_is_summary_text() -> None:
    """payload.content is set to result.summary_text."""
    store = _InMemoryStore()
    summary = "Detailed conversation summary spanning multiple topics."
    result = _make_result(summary_text=summary)

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert store.appended[0].payload.content == summary


@pytest.mark.asyncio
async def test_update_payload_metadata_contains_all_four_keys() -> None:
    """payload.metadata has first_kept_entry_id, cut_point_entry_id, tokens_before, tokens_after."""
    store = _InMemoryStore()
    result = _make_result(
        first_kept_entry_id="evt-kept-001",
        cut_point_entry_id="evt-cut-099",
        tokens_before=7500,
        tokens_after=250,
    )

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    metadata = store.appended[0].payload.metadata
    assert metadata["first_kept_entry_id"] == "evt-kept-001"
    assert metadata["cut_point_entry_id"] == "evt-cut-099"
    assert metadata["tokens_before"] == 7500
    assert metadata["tokens_after"] == 250


@pytest.mark.asyncio
async def test_update_propagates_turn_id_when_provided() -> None:
    """turn_id is set on the event when the caller provides it."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
        turn_id="turn-007",
    )

    assert store.appended[0].turn_id == "turn-007"


@pytest.mark.asyncio
async def test_update_turn_id_none_when_omitted() -> None:
    """turn_id is None when not provided by the caller."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert store.appended[0].turn_id is None


@pytest.mark.asyncio
async def test_update_iteration_is_zero() -> None:
    """Compaction events carry iteration=0 (not part of a ReAct iteration)."""
    store = _InMemoryStore()
    result = _make_result()

    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert store.appended[0].iteration == 0


@pytest.mark.asyncio
async def test_update_returns_stamped_event_with_store_assigned_sequence() -> None:
    """update() returns the stamped event with the sequence assigned by the store."""
    store = _InMemoryStore()
    result = _make_result()

    stamped: SessionHistoryEventDAO = await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert stamped.sequence == 1  # _InMemoryStore starts at 1
    assert stamped is store.appended[0]


@pytest.mark.asyncio
async def test_update_sequence_increments_across_multiple_calls() -> None:
    """Each update() call increments the sequence monotonically."""
    store = _InMemoryStore()
    result = _make_result()

    first = await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )
    second = await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert first.sequence == 1
    assert second.sequence == 2


@pytest.mark.asyncio
async def test_update_does_not_mutate_existing_store_events() -> None:
    """update() does not delete or modify any events already in the store."""
    store = _InMemoryStore()

    # Seed the store with a pre-existing event via direct append
    seed_event = SessionHistoryEventDAO(
        session_id="session-abc",
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content="Hello"),
    )
    await store.append_event(event=seed_event)
    original_count = len(store.appended)
    original_first_id = store.appended[0].event_id

    result = _make_result()
    await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    # Store has grown by exactly one; existing event is intact.
    assert len(store.appended) == original_count + 1
    assert store.appended[0].event_id == original_first_id


@pytest.mark.asyncio
async def test_update_event_has_nonempty_event_id() -> None:
    """The returned event has a non-empty event_id (UUID4 assigned by DAO default)."""
    store = _InMemoryStore()
    result = _make_result()

    stamped = await CompactedSessionUpdater.update(
        session_id="session-abc",
        result=result,
        store=store,
    )

    assert stamped.event_id
    assert len(stamped.event_id) > 0


@pytest.mark.asyncio
async def test_build_payload_metadata_keys_are_complete() -> None:
    """_build_payload produces metadata with exactly the four expected keys."""
    result = _make_result(
        summary_text="short",
        first_kept_entry_id="a",
        cut_point_entry_id="b",
        tokens_before=100,
        tokens_after=10,
    )

    payload: SessionHistoryEventPayloadDAO = CompactedSessionUpdater._build_payload(
        result=result,
    )

    expected_keys = {
        "first_kept_entry_id",
        "cut_point_entry_id",
        "tokens_before",
        "tokens_after",
    }
    assert set(payload.metadata.keys()) == expected_keys
