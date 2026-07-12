"""Tests for ``SessionInboxStore``."""

from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore


def _build_store(*, tmp_path: Path) -> SessionInboxStore:
    """Build an inbox store rooted under ``tmp_path``.

    Args:
        tmp_path (Path): Pytest tmp path.

    Returns:
        SessionInboxStore: Test-scoped inbox store.
    """
    return SessionInboxStore(history_root=tmp_path / "history")


def _build_message(
    *,
    session_id: str,
    run_id: str = "run-1",
    message_id: str = "message-1",
    coalesce_key: str | None = None,
    text: str = "CI still running.",
) -> SessionInboxMessageDAO:
    """Build one deterministic inbox message.

    Args:
        session_id (str): Target session id.
        run_id (str, optional): Schedule-fire id. Defaults to ``"run-1"``.
        message_id (str, optional): Message id. Defaults to ``"message-1"``.
        coalesce_key (str | None, optional): Optional coalescing key.
        text (str, optional): Body text. Defaults to ``"CI still running."``.

    Returns:
        SessionInboxMessageDAO: Deterministic message fixture.
    """
    return SessionInboxMessageDAO(
        message_id=message_id,
        session_id=session_id,
        schedule_id="schedule-1",
        run_id=run_id,
        kind="monitor_update",
        delivery_mode="ui_notice",
        coalesce_key=coalesce_key,
        created_at=datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc),
        title="CI monitor",
        text=text,
    )


class TestSessionInboxStore:
    """SessionInbox queue semantics."""

    async def test_ensure_session_inbox_creates_private_directory_structure(self, tmp_path: Path) -> None:
        """Each session inbox uses the expected tmp/pending/claimed/done layout."""
        store: SessionInboxStore = _build_store(tmp_path=tmp_path)

        inbox_dir: Path = await store.ensure_session_inbox(session_id="session-1")

        assert inbox_dir.is_dir()
        assert (inbox_dir / "tmp").is_dir()
        assert (inbox_dir / "pending").is_dir()
        assert (inbox_dir / "claimed").is_dir()
        assert (inbox_dir / "done").is_dir()
        assert stat.S_IMODE(inbox_dir.stat().st_mode) == 0o700

    async def test_enqueue_creates_pending_file(self, tmp_path: Path) -> None:
        """Queued inbox items land under ``pending/`` and round-trip."""
        store: SessionInboxStore = _build_store(tmp_path=tmp_path)
        message: SessionInboxMessageDAO = _build_message(session_id="session-1")

        result = await store.enqueue(message=message)
        pending_messages: list[SessionInboxMessageDAO] = await store.list_pending(session_id="session-1")

        assert result.result == "queued"
        assert result.replaced_message_id is None
        assert pending_messages == [message]

    async def test_claim_next_moves_pending_item_to_claimed(self, tmp_path: Path) -> None:
        """Claiming removes the oldest pending item and returns it."""
        store: SessionInboxStore = _build_store(tmp_path=tmp_path)
        message: SessionInboxMessageDAO = _build_message(session_id="session-1")
        await store.enqueue(message=message)

        claimed: SessionInboxMessageDAO | None = await store.claim_next(session_id="session-1")
        pending_messages: list[SessionInboxMessageDAO] = await store.list_pending(session_id="session-1")

        assert claimed == message
        assert pending_messages == []

    async def test_ack_moves_claimed_item_to_done(self, tmp_path: Path) -> None:
        """Acknowledged claimed items move into ``done/``."""
        store: SessionInboxStore = _build_store(tmp_path=tmp_path)
        message: SessionInboxMessageDAO = _build_message(session_id="session-1")
        await store.enqueue(message=message)
        await store.claim_next(session_id="session-1")

        acknowledged: bool = await store.ack(session_id="session-1", message_id=message.message_id)
        done_messages: list[SessionInboxMessageDAO] = await store.list_done(session_id="session-1")

        assert acknowledged is True
        assert done_messages == [message]

    async def test_enqueue_coalesces_pending_item_with_matching_key(self, tmp_path: Path) -> None:
        """`latest_by_key` behavior replaces the older pending item."""
        store: SessionInboxStore = _build_store(tmp_path=tmp_path)
        first: SessionInboxMessageDAO = _build_message(
            session_id="session-1",
            run_id="run-1",
            message_id="message-1",
            coalesce_key="repo-watch",
            text="CI still running.",
        )
        second: SessionInboxMessageDAO = _build_message(
            session_id="session-1",
            run_id="run-2",
            message_id="message-2",
            coalesce_key="repo-watch",
            text="CI failed on step 9.",
        )

        await store.enqueue(message=first)
        result = await store.enqueue(message=second)
        pending_messages: list[SessionInboxMessageDAO] = await store.list_pending(session_id="session-1")

        assert result.result == "coalesced"
        assert result.replaced_message_id == "message-1"
        assert pending_messages == [second]
