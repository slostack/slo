"""Unit tests for TreeMigrator and MigrationResult.

All tests use a tmp_path fixture. All tests are synchronous.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.migration.tree_migrator import (
    MigrationResult,
    TreeMigrator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    session_id: str,
    kind: str = "user_message",
    sequence: int = 1,
    content: str = "hello",
    tool_call_id: str | None = None,
    tool_calls: list | None = None,
    turn_id: str | None = None,
) -> SessionHistoryEventDAO:
    """Construct a minimal SessionHistoryEventDAO for testing.

    Args:
        session_id (str): Session identifier.
        kind (str): Event kind.
        sequence (int): Sequence number.
        content (str): Payload content.
        tool_call_id (str | None): Payload tool_call_id.
        tool_calls (list | None): Payload tool_calls.
        turn_id (str | None): Turn identifier.

    Returns:
        SessionHistoryEventDAO: Minimal test event.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind=kind,
        sequence=sequence,
        turn_id=turn_id,
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
        ),
    )


def _write_flat_session(
    root: Path,
    session_id: str,
    events: list[SessionHistoryEventDAO],
) -> None:
    """Write a flat session directory with events.jsonl and session.json.

    Args:
        root (Path): History root.
        session_id (str): Session identifier.
        events (list[SessionHistoryEventDAO]): Events to write.
    """
    session_dir = root / session_id
    session_dir.mkdir(parents=True)
    events_path = session_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(event.model_dump_json())
            fh.write("\n")
    metadata = SessionHistoryMetadataDAO(session_id=session_id, workdir=Path("/tmp"))
    (session_dir / "session.json").write_text(metadata.model_dump_json(), encoding="utf-8")


def _load_migrated_events(root: Path, session_id: str) -> list[dict]:
    """Load the migrated events.jsonl as raw dicts.

    Args:
        root (Path): Tree store root.
        session_id (str): Session identifier.

    Returns:
        list[dict]: Parsed events in file order.
    """
    path = root / session_id / "events.jsonl"
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# MigrationResult
# ---------------------------------------------------------------------------


def test_migration_result_is_frozen() -> None:
    """MigrationResult instances are immutable."""
    result = MigrationResult(
        session_id="s",
        events_migrated=5,
        tool_links_resolved=2,
        unresolved_tool_results=0,
    )
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        result.events_migrated = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# migrate_session — basic tree structure
# ---------------------------------------------------------------------------


def test_migrate_session_root_event_has_none_parent(tmp_path: Path) -> None:
    """The first event in the migrated output has parent_entry_id=None."""
    sid = "s-root"
    events = [_make_event(session_id=sid, kind="session_started", sequence=1)]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    assert dicts[0]["payload"]["metadata"]["parent_entry_id"] is None


def test_migrate_session_entry_id_matches_event_id(tmp_path: Path) -> None:
    """entry_id in payload.metadata equals event_id on every migrated event."""
    sid = "s-eid"
    events = [_make_event(session_id=sid, sequence=i, content=f"msg {i}") for i in range(1, 4)]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    for d in dicts:
        assert d["payload"]["metadata"]["entry_id"] == d["event_id"]


def test_migrate_session_linear_chain_parent_links(tmp_path: Path) -> None:
    """Non-tool events chain: each event's parent is the preceding event."""
    sid = "s-chain"
    events = [
        _make_event(session_id=sid, sequence=1, content="first"),
        _make_event(session_id=sid, sequence=2, content="second"),
        _make_event(session_id=sid, sequence=3, content="third"),
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    assert dicts[0]["payload"]["metadata"]["parent_entry_id"] is None
    assert dicts[1]["payload"]["metadata"]["parent_entry_id"] == dicts[0]["event_id"]
    assert dicts[2]["payload"]["metadata"]["parent_entry_id"] == dicts[1]["event_id"]


# ---------------------------------------------------------------------------
# migrate_session — tool_call / tool_result linking
# ---------------------------------------------------------------------------


def test_migrate_session_tool_result_points_to_tool_call(tmp_path: Path) -> None:
    """A tool_result event's parent_entry_id is the matching tool_call's event_id."""
    sid = "s-toollink"
    tc_id = "call-001"
    tc_event = _make_event(
        session_id=sid,
        sequence=2,
        kind="tool_call",
        tool_call_id=tc_id,
        tool_calls=[{"id": tc_id, "name": "bash", "args": {}}],
    )
    tr_event = _make_event(
        session_id=sid,
        sequence=3,
        kind="tool_result",
        tool_call_id=tc_id,
    )
    events = [
        _make_event(session_id=sid, sequence=1, kind="session_started"),
        tc_event,
        tr_event,
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    result = migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    tool_call_event_id = dicts[1]["event_id"]
    tool_result_parent = dicts[2]["payload"]["metadata"]["parent_entry_id"]

    assert tool_result_parent == tool_call_event_id
    assert result.tool_links_resolved == 1
    assert result.unresolved_tool_results == 0


def test_migrate_session_unresolved_tool_result_uses_linear_parent(tmp_path: Path) -> None:
    """A tool_result with no matching tool_call falls back to linear parent."""
    sid = "s-unresolved"
    events = [
        _make_event(session_id=sid, sequence=1, content="msg"),
        _make_event(session_id=sid, sequence=2, kind="tool_result", tool_call_id="orphan-id"),
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    result = migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    assert dicts[1]["payload"]["metadata"]["parent_entry_id"] == dicts[0]["event_id"]
    assert result.unresolved_tool_results == 1
    assert result.tool_links_resolved == 0


def test_migrate_session_parallel_tool_calls_resolve_independently(tmp_path: Path) -> None:
    """Parallel tool_calls each resolve to their own tool_result correctly."""
    sid = "s-parallel"
    tc_id_1 = "call-aaa"
    tc_id_2 = "call-bbb"
    tc1 = _make_event(session_id=sid, sequence=2, kind="tool_call", tool_call_id=tc_id_1)
    tc2 = _make_event(session_id=sid, sequence=3, kind="tool_call", tool_call_id=tc_id_2)
    tr1 = _make_event(session_id=sid, sequence=4, kind="tool_result", tool_call_id=tc_id_1)
    tr2 = _make_event(session_id=sid, sequence=5, kind="tool_result", tool_call_id=tc_id_2)
    events = [
        _make_event(session_id=sid, sequence=1, kind="session_started"),
        tc1,
        tc2,
        tr1,
        tr2,
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    result = migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    tc1_event_id = dicts[1]["event_id"]
    tc2_event_id = dicts[2]["event_id"]
    tr1_parent = dicts[3]["payload"]["metadata"]["parent_entry_id"]
    tr2_parent = dicts[4]["payload"]["metadata"]["parent_entry_id"]

    assert tr1_parent == tc1_event_id
    assert tr2_parent == tc2_event_id
    assert result.tool_links_resolved == 2
    assert result.unresolved_tool_results == 0


def test_migrate_session_tool_call_links_to_preceding_assistant_message(
    tmp_path: Path,
) -> None:
    """A tool_call event's parent is the preceding assistant_message in the same turn."""
    sid = "s-toolcall-parent"
    turn_id = "turn-1"
    events = [
        _make_event(session_id=sid, sequence=1, kind="user_message", turn_id=turn_id),
        _make_event(session_id=sid, sequence=2, kind="assistant_message", turn_id=turn_id),
        _make_event(
            session_id=sid,
            sequence=3,
            kind="tool_call",
            turn_id=turn_id,
            tool_calls=[{"id": "tc-x", "name": "bash", "args": {}}],
        ),
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    assistant_event_id = dicts[1]["event_id"]
    tool_call_parent = dicts[2]["payload"]["metadata"]["parent_entry_id"]

    assert tool_call_parent == assistant_event_id


# ---------------------------------------------------------------------------
# migrate_session — MigrationResult accuracy
# ---------------------------------------------------------------------------


def test_migrate_session_returns_correct_migration_result(tmp_path: Path) -> None:
    """MigrationResult fields are accurate for a simple session."""
    sid = "s-result"
    events = [
        _make_event(session_id=sid, sequence=1, kind="session_started"),
        _make_event(session_id=sid, sequence=2, kind="user_message"),
        _make_event(session_id=sid, sequence=3, kind="assistant_message"),
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    result = migrator.migrate_session(session_id=sid)

    assert result.session_id == sid
    assert result.events_migrated == 3
    assert result.tool_links_resolved == 0
    assert result.unresolved_tool_results == 0


# ---------------------------------------------------------------------------
# migrate_session — filesystem / error cases
# ---------------------------------------------------------------------------


def test_migrate_session_source_not_found_raises(tmp_path: Path) -> None:
    """Raises FileNotFoundError when the source events.jsonl does not exist."""
    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    with pytest.raises(FileNotFoundError, match="Source events.jsonl not found"):
        migrator.migrate_session(session_id="ghost-session")


def test_migrate_session_output_file_permissions(tmp_path: Path) -> None:
    """The output events.jsonl has mode 0o600."""
    sid = "s-perms"
    events = [_make_event(session_id=sid, sequence=1)]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    stat = (tmp_path / sid / "events.jsonl").stat()
    assert oct(stat.st_mode & 0o777) == oct(0o600)


def test_migrate_session_no_tmp_file_left_after_success(tmp_path: Path) -> None:
    """No stale .tmp file remains after a successful migration."""
    sid = "s-notmp"
    events = [_make_event(session_id=sid, sequence=1)]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    assert not (tmp_path / sid / "events.jsonl.tmp").exists()


def test_migrate_session_separate_tree_root_copies_session_json(tmp_path: Path) -> None:
    """When tree_root != flat_root, session.json is copied to the tree root."""
    flat_root = tmp_path / "flat"
    tree_root = tmp_path / "tree"
    flat_root.mkdir()
    tree_root.mkdir()

    sid = "s-copy"
    events = [_make_event(session_id=sid, sequence=1)]
    _write_flat_session(root=flat_root, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=flat_root, tree_root=tree_root)
    migrator.migrate_session(session_id=sid)

    assert (tree_root / sid / "session.json").exists()
    assert (flat_root / sid / "events.jsonl").exists()  # source untouched


def test_migrate_session_existing_metadata_keys_preserved(tmp_path: Path) -> None:
    """Pre-existing keys in payload.metadata survive the migration."""
    sid = "s-meta"
    events = [
        SessionHistoryEventDAO(
            session_id=sid,
            kind="user_message",
            sequence=1,
            payload=SessionHistoryEventPayloadDAO(
                content="hi",
                metadata={"custom_key": "custom_value"},
            ),
        )
    ]
    _write_flat_session(root=tmp_path, session_id=sid, events=events)

    migrator = TreeMigrator(flat_root=tmp_path, tree_root=tmp_path)
    migrator.migrate_session(session_id=sid)

    dicts = _load_migrated_events(root=tmp_path, session_id=sid)
    metadata = dicts[0]["payload"]["metadata"]
    assert metadata["custom_key"] == "custom_value"
    assert "entry_id" in metadata
    assert "parent_entry_id" in metadata
