"""Filesystem durability tests for the spec-62 compaction transaction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.compaction.compacter import CompactionResult
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    HistoryCompactionRecoveryError,
)
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore

_SESSION_ID: str = "transaction-session"


def _event(*, event_id: str, sequence: int, content: str = "event") -> SessionHistoryEventDAO:
    """Build one persisted event with stable IDs for transactional assertions.

    Args:
        event_id (str): Fixed durable event identifier.
        sequence (int): Expected assigned sequence.
        content (str): Event text.

    Returns:
        SessionHistoryEventDAO: Completed-turn event fixture.
    """
    return SessionHistoryEventDAO(
        event_id=event_id,
        session_id=_SESSION_ID,
        turn_id="turn-1",
        sequence=sequence,
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content=content, token_usage=10),
    )


def _result(*, first_kept_entry_id: str) -> CompactionResult:
    """Build a deterministic compaction result.

    Args:
        first_kept_entry_id (str): First retained durable event ID.

    Returns:
        CompactionResult: Summary transaction input.
    """
    return CompactionResult(
        summary_text="durable summary",
        first_kept_entry_id=first_kept_entry_id,
        cut_point_entry_id="first",
        tokens_before=10,
        tokens_after=4,
    )


async def _seed(
    *, store: FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore, tmp_path: Path
) -> list[SessionHistoryEventDAO]:
    """Ensure a session and append a compactable retained-tail fixture.

    Args:
        store (FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore): Store under test.
        tmp_path (Path): Isolated workdir used in metadata.

    Returns:
        list[SessionHistoryEventDAO]: Store-assigned source events.
    """
    await store.ensure_session(session_id=_SESSION_ID, workdir=tmp_path, model_name="unknown")
    first: SessionHistoryEventDAO = await store.append_event(event=_event(event_id="first", sequence=0))
    second: SessionHistoryEventDAO = await store.append_event(event=_event(event_id="second", sequence=0))
    return [first, second]


def _durable_bytes(*, root: Path) -> tuple[bytes, bytes]:
    """Read active event and metadata bytes without normalizing them.

    Args:
        root (Path): History root.

    Returns:
        tuple[bytes, bytes]: Active log and metadata bytes.
    """
    session_dir: Path = root / _SESSION_ID
    return (
        session_dir.joinpath("events.jsonl").read_bytes(),
        session_dir.joinpath("session.json").read_bytes(),
    )


@pytest.mark.asyncio
async def test_flat_transaction_retains_tail_assigns_summary_and_advances_next_append(tmp_path: Path) -> None:
    """The flat transaction atomically leaves tail plus summary and monotonic sequence."""
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    events: list[SessionHistoryEventDAO] = await _seed(store=store, tmp_path=tmp_path)

    summary: SessionHistoryEventDAO = await store.compact_to_boundary(
        session_id=_SESSION_ID,
        events=events,
        result=_result(first_kept_entry_id=events[1].event_id),
        turn_id="manual-turn",
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=_SESSION_ID)
    metadata = await store.read_metadata(session_id=_SESSION_ID)
    appended: SessionHistoryEventDAO = await store.append_event(event=_event(event_id="third", sequence=0))

    assert [event.event_id for event in persisted] == [events[1].event_id, summary.event_id]
    assert summary.sequence == 3
    assert summary.payload.metadata["first_kept_entry_id"] == events[1].event_id
    assert list((tmp_path / _SESSION_ID).glob("events.pre-compaction-*.jsonl"))
    assert metadata.latest_sequence == summary.sequence
    assert appended.sequence == summary.sequence + 1


@pytest.mark.asyncio
async def test_tree_transaction_has_same_flat_durable_behavior(tmp_path: Path) -> None:
    """Tree storage delegates the exact transaction contract to its flat writer."""
    store: TreeBasedFilesystemSessionHistoryStore = TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
    events: list[SessionHistoryEventDAO] = await _seed(store=store, tmp_path=tmp_path)

    summary: SessionHistoryEventDAO = await store.compact_to_boundary(
        session_id=_SESSION_ID,
        events=events,
        result=_result(first_kept_entry_id=events[1].event_id),
        turn_id="manual-turn",
    )

    persisted: list[SessionHistoryEventDAO] = await store.load_events(session_id=_SESSION_ID)
    assert [event.event_id for event in persisted] == [events[1].event_id, summary.event_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_step", ["candidate", "archive", "activation", "metadata"])
async def test_transaction_failure_preserves_active_and_metadata_bytes(
    tmp_path: Path,
    failure_step: str,
) -> None:
    """Every recoverable transaction failure restores exact active durable bytes.

    Args:
        tmp_path (Path): Isolated history root.
        failure_step (str): Candidate, archive, activation, or metadata failure seam.
    """
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    events: list[SessionHistoryEventDAO] = await _seed(store=store, tmp_path=tmp_path)
    before: tuple[bytes, bytes] = _durable_bytes(root=tmp_path)
    original_write_events = store._write_events_to_path
    original_replace = Path.replace
    original_write_metadata = store._write_metadata_sync

    def _write_events(*, path: Path, events: list[SessionHistoryEventDAO]) -> None:
        """Raise only at candidate creation when configured."""
        if failure_step == "candidate":
            raise OSError("candidate write failed")
        original_write_events(path=path, events=events)

    def _replace(self: Path, target: Path) -> Path:
        """Raise at the configured archive or candidate activation rename."""
        if failure_step == "archive" and self.name == "events.jsonl":
            raise OSError("archive rename failed")
        if failure_step == "activation" and self.name.endswith(".compaction-candidate"):
            raise OSError("activation rename failed")
        return original_replace(self, target)

    def _write_metadata(*, metadata) -> None:
        """Raise after activation when configured."""
        if failure_step == "metadata":
            raise OSError("metadata write failed")
        original_write_metadata(metadata=metadata)

    with (
        patch.object(store, "_write_events_to_path", side_effect=_write_events),
        patch.object(Path, "replace", new=_replace),
        patch.object(store, "_write_metadata_sync", side_effect=_write_metadata),
    ):
        with pytest.raises(OSError):
            await store.compact_to_boundary(
                session_id=_SESSION_ID,
                events=events,
                result=_result(first_kept_entry_id=events[1].event_id),
                turn_id="manual-turn",
            )

    assert _durable_bytes(root=tmp_path) == before


@pytest.mark.asyncio
async def test_reader_recovers_deterministic_archive_after_restore_failure(tmp_path: Path) -> None:
    """A typed double-failure leaves a deterministic archive readers restore first."""
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    events: list[SessionHistoryEventDAO] = await _seed(store=store, tmp_path=tmp_path)
    original_replace = Path.replace

    def _replace(self: Path, target: Path) -> Path:
        """Fail activation then the immediate archive-to-active restoration."""
        if self.name.endswith(".compaction-candidate"):
            raise OSError("activation failed")
        if self.name.startswith("events.pre-compaction-") and target.name == "events.jsonl":
            raise OSError("restore failed")
        return original_replace(self, target)

    with patch.object(Path, "replace", new=_replace):
        with pytest.raises(HistoryCompactionRecoveryError) as raised:
            await store.compact_to_boundary(
                session_id=_SESSION_ID,
                events=events,
                result=_result(first_kept_entry_id=events[1].event_id),
                turn_id="manual-turn",
            )

    assert raised.value.active_path.name == "events.jsonl"
    assert raised.value.archive_path.exists()
    recovered: list[SessionHistoryEventDAO] = await store.load_events(session_id=_SESSION_ID)
    assert [event.event_id for event in recovered] == [event.event_id for event in events]
