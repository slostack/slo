"""Tests for FilesystemSessionHistoryStore compaction extensions (sub-spec 01.a.3)."""
from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.compaction.token_estimator import TokenEstimator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    session_id: str = "sess-1",
    kind: str = "user_message",
    sequence: int,
    token_usage: int = 100,
    content: str = "msg",
) -> SessionHistoryEventDAO:
    """Build a minimal persisted-looking event with a known event_id.

    Args:
        session_id (str): Session owner.
        kind (str): Event kind.
        sequence (int): Store-assigned sequence number.
        token_usage (int): Pre-stamped token weight.
        content (str): Payload content.

    Returns:
        SessionHistoryEventDAO: Fully populated minimal event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind=kind,
        sequence=sequence,
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            token_usage=token_usage,
        ),
    )


def _make_summary_event(
    *,
    session_id: str = "sess-1",
    sequence: int,
    first_kept_entry_id: str,
) -> SessionHistoryEventDAO:
    """Build a compaction_summary event for use in truncation tests.

    Args:
        session_id (str): Session owner.
        sequence (int): Store-assigned sequence.
        first_kept_entry_id (str): Boundary pointer stored in metadata.

    Returns:
        SessionHistoryEventDAO: Compaction summary event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind="compaction_summary",
        sequence=sequence,
        payload=SessionHistoryEventPayloadDAO(
            content="Summary of prior turns.",
            token_usage=50,
            metadata={"first_kept_entry_id": first_kept_entry_id},
        ),
    )


@pytest.fixture()
async def store(tmp_path: Path) -> FilesystemSessionHistoryStore:
    """Return a store with one ensured session.

    Args:
        tmp_path (Path): Pytest tmp_path fixture.

    Returns:
        FilesystemSessionHistoryStore: Store backed by tmp_path.
    """
    s = FilesystemSessionHistoryStore(root=tmp_path)
    await s.ensure_session(
        session_id="sess-1",
        workdir=tmp_path,
        model_name="claude-3-5-sonnet",
        workspace_file=None,
    )
    return s


async def test_append_event_stamps_token_usage(
    store: FilesystemSessionHistoryStore,
) -> None:
    raw = SessionHistoryEventDAO(
        session_id="sess-1",
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content="hello world"),
    )
    persisted = await store.append_event(event=raw)
    assert persisted.payload.token_usage is not None
    assert persisted.payload.token_usage == TokenEstimator.estimate(event=raw)


async def test_append_event_preserves_caller_token_usage(
    store: FilesystemSessionHistoryStore,
) -> None:
    raw = SessionHistoryEventDAO(
        session_id="sess-1",
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content="hi", token_usage=42),
    )
    persisted = await store.append_event(event=raw)
    assert persisted.payload.token_usage == 42


async def test_append_compaction_summary_writes_correct_kind(
    store: FilesystemSessionHistoryStore,
) -> None:
    summary = "The assistant read foo.py and edited bar.py."
    event = await store.append_compaction_summary(
        session_id="sess-1",
        summary=summary,
        first_kept_entry_id="entry-abc",
        cut_point_entry_id="entry-xyz",
        tokens_before=45_000,
        tokens_after=12,
    )
    assert event.kind == "compaction_summary"
    events = await store.load_events(session_id="sess-1")
    assert events[-1].kind == "compaction_summary"


async def test_append_compaction_summary_content(
    store: FilesystemSessionHistoryStore,
) -> None:
    summary = "The assistant helped with a coding task."
    event = await store.append_compaction_summary(
        session_id="sess-1",
        summary=summary,
        first_kept_entry_id="e1",
        cut_point_entry_id="e0",
        tokens_before=1000,
        tokens_after=8,
    )
    assert event.payload.content == summary


async def test_append_compaction_summary_metadata_fields(
    store: FilesystemSessionHistoryStore,
) -> None:
    event = await store.append_compaction_summary(
        session_id="sess-1",
        summary="summary text",
        first_kept_entry_id="entry-first",
        cut_point_entry_id="entry-cut",
        tokens_before=5000,
        tokens_after=3,
    )
    assert event.payload.metadata["first_kept_entry_id"] == "entry-first"
    assert event.payload.metadata["cut_point_entry_id"] == "entry-cut"
    assert event.payload.metadata["tokens_before"] == 5000
    assert event.payload.metadata["tokens_after"] == 3


async def test_append_compaction_summary_token_usage(
    store: FilesystemSessionHistoryStore,
) -> None:
    summary = "Summary text of known length."
    event = await store.append_compaction_summary(
        session_id="sess-1",
        summary=summary,
        first_kept_entry_id="e1",
        cut_point_entry_id="e0",
        tokens_before=1000,
        tokens_after=8,
    )
    assert event.payload.token_usage == math.ceil(len(summary) / 4)


async def test_existing_events_without_token_usage_parse_cleanly(
    tmp_path: Path,
) -> None:
    """JSONL lines written before the token_usage field parse with token_usage=None."""
    import json

    session_id = "legacy-sess"
    store = FilesystemSessionHistoryStore(root=tmp_path)
    await store.ensure_session(
        session_id=session_id,
        workdir=tmp_path,
        model_name=None,
        workspace_file=None,
    )
    events_path = tmp_path / session_id / "events.jsonl"
    legacy_line = json.dumps({
        "schema_version": 1,
        "event_id": "old-event-id",
        "session_id": session_id,
        "sequence": 1,
        "kind": "user_message",
        "iteration": 0,
        "recorded_at": "2024-01-01T00:00:00+00:00",
        "payload": {"content": "legacy message"},
    })
    with events_path.open("a", encoding="utf-8") as f:
        f.write(legacy_line + "\n")

    session_meta_path = tmp_path / session_id / "session.json"
    meta = json.loads(session_meta_path.read_text(encoding="utf-8"))
    meta["latest_sequence"] = 1
    session_meta_path.write_text(json.dumps(meta), encoding="utf-8")

    events = await store.load_events(session_id=session_id)
    assert len(events) == 1
    assert events[0].payload.token_usage is None


# ---------------------------------------------------------------------------
# Tests: truncate_to_compaction_boundary
# ---------------------------------------------------------------------------


class TestTruncateToCompactionBoundary:
    """FilesystemSessionHistoryStore.truncate_to_compaction_boundary."""

    async def test_load_events_returns_only_retained_tail_and_summary(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """After truncation, load_events returns only the active events."""
        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"e{i}"))
            for i in range(5)
        ]
        first_kept: SessionHistoryEventDAO = pre_events[3]
        summary: SessionHistoryEventDAO = _make_summary_event(
            sequence=pre_events[-1].sequence + 1,
            first_kept_entry_id=first_kept.event_id,
        )

        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=pre_events,
            first_kept_entry_id=first_kept.event_id,
            summary_event=summary,
        )

        loaded: list[SessionHistoryEventDAO] = await store.load_events(session_id="sess-1")
        loaded_ids: set[str] = {e.event_id for e in loaded}
        assert first_kept.event_id in loaded_ids
        assert pre_events[4].event_id in loaded_ids
        assert summary.event_id in loaded_ids
        assert pre_events[0].event_id not in loaded_ids
        assert pre_events[1].event_id not in loaded_ids
        assert pre_events[2].event_id not in loaded_ids

    async def test_load_events_count_after_truncation(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """After truncation the file contains retained_tail + summary only."""
        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"e{i}"))
            for i in range(6)
        ]
        first_kept: SessionHistoryEventDAO = pre_events[4]
        summary: SessionHistoryEventDAO = _make_summary_event(
            sequence=pre_events[-1].sequence + 1,
            first_kept_entry_id=first_kept.event_id,
        )

        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=pre_events,
            first_kept_entry_id=first_kept.event_id,
            summary_event=summary,
        )

        loaded: list[SessionHistoryEventDAO] = await store.load_events(session_id="sess-1")
        assert len(loaded) == 3  # events[4], events[5], summary

    async def test_archive_file_is_created(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """truncate_to_compaction_boundary creates exactly one archive file."""
        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"e{i}"))
            for i in range(4)
        ]
        first_kept: SessionHistoryEventDAO = pre_events[2]
        summary: SessionHistoryEventDAO = _make_summary_event(
            sequence=pre_events[-1].sequence + 1,
            first_kept_entry_id=first_kept.event_id,
        )

        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=pre_events,
            first_kept_entry_id=first_kept.event_id,
            summary_event=summary,
        )

        session_dir: Path = tmp_path / "sess-1"
        archives: list[Path] = sorted(session_dir.glob("events.pre-*.jsonl"))
        assert len(archives) == 1

    async def test_archive_file_contains_full_pre_compaction_history(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """The archive file preserves all pre-compaction events."""
        import json

        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"e{i}"))
            for i in range(4)
        ]
        first_kept: SessionHistoryEventDAO = pre_events[2]
        summary: SessionHistoryEventDAO = _make_summary_event(
            sequence=pre_events[-1].sequence + 1,
            first_kept_entry_id=first_kept.event_id,
        )

        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=pre_events,
            first_kept_entry_id=first_kept.event_id,
            summary_event=summary,
        )

        session_dir: Path = tmp_path / "sess-1"
        archive: Path = next(session_dir.glob("events.pre-*.jsonl"))
        archive_ids: set[str] = {
            json.loads(line)["event_id"]
            for line in archive.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        for event in pre_events:
            assert event.event_id in archive_ids

    async def test_second_truncation_creates_second_archive_file(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """Each compaction cycle produces its own archive file."""
        import time

        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"e{i}"))
            for i in range(4)
        ]
        first_kept_1: SessionHistoryEventDAO = pre_events[2]
        summary_1: SessionHistoryEventDAO = _make_summary_event(
            sequence=pre_events[-1].sequence + 1,
            first_kept_entry_id=first_kept_1.event_id,
        )
        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=pre_events,
            first_kept_entry_id=first_kept_1.event_id,
            summary_event=summary_1,
        )

        # Ensure distinct timestamps (1-second resolution in archive name).
        time.sleep(1.05)

        # Simulate new events arriving after first truncation.
        new_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content=f"new{i}"))
            for i in range(3)
        ]
        all_active: list[SessionHistoryEventDAO] = await store.load_events(session_id="sess-1")
        first_kept_2: SessionHistoryEventDAO = new_events[1]
        summary_2: SessionHistoryEventDAO = _make_summary_event(
            sequence=all_active[-1].sequence + 1,
            first_kept_entry_id=first_kept_2.event_id,
        )
        await store.truncate_to_compaction_boundary(
            session_id="sess-1",
            events=all_active,
            first_kept_entry_id=first_kept_2.event_id,
            summary_event=summary_2,
        )

        session_dir: Path = tmp_path / "sess-1"
        archives: list[Path] = sorted(session_dir.glob("events.pre-*.jsonl"))
        assert len(archives) == 2

    async def test_raises_when_first_kept_entry_id_not_in_events(
        self,
        store: FilesystemSessionHistoryStore,
        tmp_path: Path,
    ) -> None:
        """ValueError is raised when first_kept_entry_id resolves to nothing."""
        pre_events: list[SessionHistoryEventDAO] = [
            await store.append_event(event=_make_event(sequence=0, content="x"))
        ]
        summary: SessionHistoryEventDAO = _make_summary_event(
            sequence=99,
            first_kept_entry_id="no-such-id",
        )

        with pytest.raises(ValueError, match="first_kept_entry_id"):
            await store.truncate_to_compaction_boundary(
                session_id="sess-1",
                events=pre_events,
                first_kept_entry_id="no-such-id",
                summary_event=summary,
            )

    async def test_raises_when_events_jsonl_does_not_exist(
        self,
        tmp_path: Path,
    ) -> None:
        """FileNotFoundError when events.jsonl is absent for the session."""
        store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
        dummy_event: SessionHistoryEventDAO = _make_event(session_id="ghost", sequence=1)
        summary: SessionHistoryEventDAO = _make_summary_event(
            session_id="ghost",
            sequence=2,
            first_kept_entry_id=dummy_event.event_id,
        )

        with pytest.raises(FileNotFoundError):
            await store.truncate_to_compaction_boundary(
                session_id="ghost",
                events=[dummy_event],
                first_kept_entry_id=dummy_event.event_id,
                summary_event=summary,
            )
