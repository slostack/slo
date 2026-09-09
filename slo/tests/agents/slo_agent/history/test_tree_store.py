"""Tests for ``TreeBasedFilesystemSessionHistoryStore`` (sub-spec 01.a.4)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_id() -> str:
    return str(uuid4())


def _make_event(
    *,
    session_id: str,
    kind: str = "user_message",
    content: str = "hello",
) -> SessionHistoryEventDAO:
    """Build a minimal event for testing.

    Args:
        session_id (str): Owning session.
        kind (str): Event kind.
        content (str): Payload content.

    Returns:
        SessionHistoryEventDAO: A test event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(content=content),
    )


def _make_tool_call_event(*, session_id: str, tool_call_id: str) -> SessionHistoryEventDAO:
    """Build a tool_call event.

    Args:
        session_id (str): Owning session.
        tool_call_id (str): Tool call identifier.

    Returns:
        SessionHistoryEventDAO: A tool_call test event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind="tool_call",
        payload=SessionHistoryEventPayloadDAO(tool_call_id=tool_call_id),
    )


def _make_tool_result_event(*, session_id: str, tool_call_id: str) -> SessionHistoryEventDAO:
    """Build a tool_result event.

    Args:
        session_id (str): Owning session.
        tool_call_id (str): Tool call identifier to close.

    Returns:
        SessionHistoryEventDAO: A tool_result test event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind="tool_result",
        payload=SessionHistoryEventPayloadDAO(tool_call_id=tool_call_id),
    )


async def _ensured_store(*, tmp_path: Path) -> tuple[TreeBasedFilesystemSessionHistoryStore, str]:
    """Return a store with one ensured session.

    Args:
        tmp_path (Path): Pytest tmp_path fixture.

    Returns:
        tuple: (store, session_id)
    """
    store = TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
    session_id = _make_session_id()
    await store.ensure_session(
        session_id=session_id,
        workdir=tmp_path,
        model_name="test-model",
    )
    return store, session_id


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Tree store satisfies ``SessionHistoryStoreProtocol``."""

    def test_satisfies_protocol(self, tmp_path: Path) -> None:
        store = TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        assert isinstance(store, SessionHistoryStoreProtocol)


# ---------------------------------------------------------------------------
# Entry-id / parent-entry-id threading
# ---------------------------------------------------------------------------


class TestTreeMetadata:
    """Tree metadata is threaded correctly into every appended event."""

    async def test_root_event_has_none_parent(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        event = _make_event(session_id=session_id)
        persisted = await store.append_event(event=event)
        assert persisted.payload.metadata["parent_entry_id"] is None

    async def test_entry_id_matches_event_id(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        event = _make_event(session_id=session_id)
        persisted = await store.append_event(event=event)
        assert persisted.payload.metadata["entry_id"] == persisted.event_id

    async def test_events_chain_parent_entry_ids(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        e1 = await store.append_event(event=_make_event(session_id=session_id, content="a"))
        e2 = await store.append_event(event=_make_event(session_id=session_id, content="b"))
        e3 = await store.append_event(event=_make_event(session_id=session_id, content="c"))

        events = await store.load_events(session_id=session_id)
        assert events[0].payload.metadata["parent_entry_id"] is None
        assert events[1].payload.metadata["parent_entry_id"] == e1.event_id
        assert events[2].payload.metadata["parent_entry_id"] == e2.event_id
        # Suppress unused-variable warnings; we loaded from disk to verify persistence.
        _ = e3

    async def test_tool_result_points_to_tool_call(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        tool_call_id = "call-abc"
        tc = await store.append_event(
            event=_make_tool_call_event(session_id=session_id, tool_call_id=tool_call_id)
        )
        tr = await store.append_event(
            event=_make_tool_result_event(session_id=session_id, tool_call_id=tool_call_id)
        )
        assert tr.payload.metadata["parent_entry_id"] == tc.event_id

    async def test_event_after_tool_result_points_to_tool_result(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        tool_call_id = "call-xyz"
        await store.append_event(
            event=_make_tool_call_event(session_id=session_id, tool_call_id=tool_call_id)
        )
        tr = await store.append_event(
            event=_make_tool_result_event(session_id=session_id, tool_call_id=tool_call_id)
        )
        next_event = await store.append_event(
            event=_make_event(session_id=session_id, kind="assistant_message", content="done")
        )
        assert next_event.payload.metadata["parent_entry_id"] == tr.event_id

    async def test_parallel_tool_calls_resolve_independently(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        tc1 = await store.append_event(
            event=_make_tool_call_event(session_id=session_id, tool_call_id="tc-1")
        )
        tc2 = await store.append_event(
            event=_make_tool_call_event(session_id=session_id, tool_call_id="tc-2")
        )
        tr1 = await store.append_event(
            event=_make_tool_result_event(session_id=session_id, tool_call_id="tc-1")
        )
        tr2 = await store.append_event(
            event=_make_tool_result_event(session_id=session_id, tool_call_id="tc-2")
        )
        assert tr1.payload.metadata["parent_entry_id"] == tc1.event_id
        assert tr2.payload.metadata["parent_entry_id"] == tc2.event_id

    async def test_append_compaction_summary_threads_parent(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        msg = await store.append_event(
            event=_make_event(session_id=session_id, kind="user_message", content="hi")
        )
        compaction = await store.append_compaction_summary(
            session_id=session_id,
            summary="The user said hi.",
            first_kept_entry_id="entry-kept",
            cut_point_entry_id="entry-cut",
            tokens_before=100,
            tokens_after=5,
        )
        assert compaction.payload.metadata["parent_entry_id"] == msg.event_id


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Events written by the tree store are readable by the flat store."""

    async def test_events_readable_by_flat_store(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        for i in range(3):
            await store.append_event(event=_make_event(session_id=session_id, content=f"msg-{i}"))

        flat = FilesystemSessionHistoryStore(root=tmp_path)
        events = await flat.load_events(session_id=session_id)
        assert len(events) == 3


# ---------------------------------------------------------------------------
# seed_last_entry_id
# ---------------------------------------------------------------------------


class TestSeedLastEntryId:
    """``seed_last_entry_id`` enables correct continuation after resume."""

    async def test_seed_last_entry_id_enables_continuation(self, tmp_path: Path) -> None:
        store, session_id = await _ensured_store(tmp_path=tmp_path)
        await store.append_event(event=_make_event(session_id=session_id, content="first"))
        events = await store.load_events(session_id=session_id)

        fresh_store = TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        fresh_store.seed_last_entry_id(entry_id=events[-1].event_id)

        next_event = await fresh_store.append_event(
            event=_make_event(session_id=session_id, content="second")
        )
        assert next_event.payload.metadata["parent_entry_id"] == events[-1].event_id
