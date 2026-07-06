"""Unit tests for TokenUsageBackfiller.

All tests use a tmp_path fixture for the store root so no real sessions
are touched. All tests are synchronous — TokenUsageBackfiller has no async
surface.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.migration.token_usage_backfiller import (
    TokenUsageBackfiller,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_session(
    root: Path,
    session_id: str,
    events: list[SessionHistoryEventDAO],
    updated_at: datetime | None = None,
) -> None:
    """Write a session directory with events.jsonl and session.json.

    Args:
        root (Path): History root directory.
        session_id (str): Session identifier.
        events (list[SessionHistoryEventDAO]): Events to write.
        updated_at (datetime | None): Override updated_at on session metadata.
    """
    session_dir: Path = root / session_id
    session_dir.mkdir(parents=True)

    events_path: Path = session_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(event.model_dump_json())
            fh.write("\n")

    metadata = SessionHistoryMetadataDAO(
        session_id=session_id,
        workdir=Path("/tmp"),
        updated_at=updated_at or datetime.now(timezone.utc),
    )
    (session_dir / "session.json").write_text(
        metadata.model_dump_json(), encoding="utf-8"
    )


def _make_event(
    session_id: str,
    kind: str = "user_message",
    content: str = "hello",
    sequence: int = 1,
    token_usage: int | None = None,
) -> SessionHistoryEventDAO:
    """Build a minimal SessionHistoryEventDAO for testing.

    Args:
        session_id (str): Session identifier.
        kind (str): Event kind.
        content (str): Payload content field.
        sequence (int): Sequence number.
        token_usage (int | None): Existing token_usage value (None = needs backfill).

    Returns:
        SessionHistoryEventDAO: The constructed event.
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


# ---------------------------------------------------------------------------
# backfill_session
# ---------------------------------------------------------------------------


def test_backfill_session_fills_none_token_usage(tmp_path: Path) -> None:
    """Events with token_usage=None receive a computed value after backfill."""
    session_id = "s-fill"
    content = "hello world"  # 11 chars -> ceil(11/4) = 3
    events = [_make_event(session_id=session_id, content=content, token_usage=None)]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    count = backfiller.backfill_session(session_id=session_id)

    assert count == 1
    events_path = tmp_path / session_id / "events.jsonl"
    lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    raw = json.loads(lines[0])
    assert raw["payload"]["token_usage"] == math.ceil(11 / 4)


def test_backfill_session_skips_already_stamped_events(tmp_path: Path) -> None:
    """Events with token_usage already set are left unchanged."""
    session_id = "s-skip"
    events = [_make_event(session_id=session_id, content="x" * 40, token_usage=999)]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    count = backfiller.backfill_session(session_id=session_id)

    assert count == 0
    events_path = tmp_path / session_id / "events.jsonl"
    lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
    raw = json.loads(lines[0])
    assert raw["payload"]["token_usage"] == 999


def test_backfill_session_mixed_events(tmp_path: Path) -> None:
    """A mix of stamped and unstamped events: only the None ones are updated."""
    session_id = "s-mixed"
    events = [
        _make_event(session_id=session_id, content="abc", sequence=1, token_usage=7),
        _make_event(session_id=session_id, content="abcd", sequence=2, token_usage=None),
        _make_event(session_id=session_id, content="abcde", sequence=3, token_usage=None),
    ]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    count = backfiller.backfill_session(session_id=session_id)

    assert count == 2
    events_path = tmp_path / session_id / "events.jsonl"
    lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
    assert json.loads(lines[0])["payload"]["token_usage"] == 7
    assert json.loads(lines[1])["payload"]["token_usage"] == math.ceil(4 / 4)
    assert json.loads(lines[2])["payload"]["token_usage"] == math.ceil(5 / 4)


def test_backfill_session_atomic_rewrite_preserves_event_count(tmp_path: Path) -> None:
    """After backfill the line count in events.jsonl is unchanged."""
    session_id = "s-count"
    events = [
        _make_event(session_id=session_id, content=f"msg {i}", sequence=i)
        for i in range(1, 6)
    ]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    backfiller.backfill_session(session_id=session_id)

    events_path = tmp_path / session_id / "events.jsonl"
    lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 5


def test_backfill_session_file_not_found_raises(tmp_path: Path) -> None:
    """Raises FileNotFoundError when the session has no events.jsonl."""
    backfiller = TokenUsageBackfiller(root=tmp_path)
    with pytest.raises(FileNotFoundError, match="events.jsonl not found"):
        backfiller.backfill_session(session_id="no-such-session")


def test_backfill_session_skips_malformed_json_lines(tmp_path: Path) -> None:
    """Malformed JSON lines are preserved unchanged and not counted."""
    session_id = "s-malformed"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    events_path = session_dir / "events.jsonl"
    valid_line = json.dumps({
        "session_id": session_id,
        "kind": "user_message",
        "event_id": "evt-x",
        "sequence": 1,
        "iteration": 0,
        "recorded_at": "2026-06-01T00:00:00+00:00",
        "schema_version": 1,
        "payload": {"content": "hi", "token_usage": None, "metadata": {}},
    })
    events_path.write_text(f"NOT_JSON\n{valid_line}\n", encoding="utf-8")
    metadata = SessionHistoryMetadataDAO(session_id=session_id, workdir=Path("/tmp"))
    (session_dir / "session.json").write_text(
        metadata.model_dump_json(), encoding="utf-8"
    )

    backfiller = TokenUsageBackfiller(root=tmp_path)
    count = backfiller.backfill_session(session_id=session_id)

    # Only the valid JSON line should be updated.
    assert count == 1
    output_lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]
    assert output_lines[0] == "NOT_JSON"
    assert json.loads(output_lines[1])["payload"]["token_usage"] is not None


def test_backfill_session_output_file_permissions(tmp_path: Path) -> None:
    """After backfill, events.jsonl has mode 0o600."""
    session_id = "s-perms"
    events = [_make_event(session_id=session_id)]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    backfiller.backfill_session(session_id=session_id)

    events_path = tmp_path / session_id / "events.jsonl"
    stat = events_path.stat()
    assert oct(stat.st_mode & 0o777) == oct(0o600)


def test_backfill_session_no_tmp_file_left_after_success(tmp_path: Path) -> None:
    """No stale .tmp file is left after a successful backfill."""
    session_id = "s-notmp"
    events = [_make_event(session_id=session_id)]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    backfiller.backfill_session(session_id=session_id)

    tmp_candidate = tmp_path / session_id / "events.jsonl.tmp"
    assert not tmp_candidate.exists()


# ---------------------------------------------------------------------------
# backfill_last_n_sessions
# ---------------------------------------------------------------------------


def test_backfill_last_n_sessions_selects_most_recent(tmp_path: Path) -> None:
    """Only the N most recently updated sessions are processed."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    sessions = {
        "s-old": base_time,
        "s-mid": base_time + timedelta(hours=1),
        "s-new": base_time + timedelta(hours=2),
    }
    for sid, ts in sessions.items():
        events = [_make_event(session_id=sid, content="x" * 20, token_usage=None)]
        _write_session(root=tmp_path, session_id=sid, events=events, updated_at=ts)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    results = backfiller.backfill_last_n_sessions(n=2)

    assert set(results.keys()) == {"s-new", "s-mid"}
    assert "s-old" not in results


def test_backfill_last_n_sessions_returns_update_counts(tmp_path: Path) -> None:
    """Return dict maps session_id to the count of updated events."""
    session_id = "s-counts"
    events = [
        _make_event(session_id=session_id, content="ab", sequence=1, token_usage=None),
        _make_event(session_id=session_id, content="cd", sequence=2, token_usage=None),
    ]
    _write_session(root=tmp_path, session_id=session_id, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    results = backfiller.backfill_last_n_sessions(n=1)

    assert results[session_id] == 2


def test_backfill_last_n_sessions_empty_root_returns_empty(tmp_path: Path) -> None:
    """Returns an empty dict when the history root is empty."""
    backfiller = TokenUsageBackfiller(root=tmp_path)
    results = backfiller.backfill_last_n_sessions(n=3)
    assert results == {}


def test_backfill_last_n_sessions_invalid_n_raises(tmp_path: Path) -> None:
    """Raises ValueError when n < 1."""
    backfiller = TokenUsageBackfiller(root=tmp_path)
    with pytest.raises(ValueError, match="n must be >= 1"):
        backfiller.backfill_last_n_sessions(n=0)


def test_backfill_last_n_sessions_n_larger_than_session_count(tmp_path: Path) -> None:
    """When n > available sessions, all sessions are processed."""
    for i in range(2):
        sid = f"s-{i}"
        events = [_make_event(session_id=sid, token_usage=None)]
        _write_session(root=tmp_path, session_id=sid, events=events)

    backfiller = TokenUsageBackfiller(root=tmp_path)
    results = backfiller.backfill_last_n_sessions(n=10)

    assert len(results) == 2


def test_backfill_last_n_sessions_default_n_is_3(tmp_path: Path) -> None:
    """Default n=3 processes only 3 most recent sessions from 5."""
    base_time = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        sid = f"s-{i}"
        events = [_make_event(session_id=sid, token_usage=None)]
        _write_session(
            root=tmp_path,
            session_id=sid,
            events=events,
            updated_at=base_time + timedelta(hours=i),
        )

    backfiller = TokenUsageBackfiller(root=tmp_path)
    results = backfiller.backfill_last_n_sessions()

    assert len(results) == 3
    # The three most recent are s-4, s-3, s-2.
    assert set(results.keys()) == {"s-4", "s-3", "s-2"}
