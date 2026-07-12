"""Tests for ``SessionOwnershipLeaseStore``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore


def _build_store(*, tmp_path: Path) -> SessionOwnershipLeaseStore:
    """Build a lease store rooted under ``tmp_path``.

    Args:
        tmp_path (Path): Pytest tmp path.

    Returns:
        SessionOwnershipLeaseStore: Test-scoped lease store.
    """
    return SessionOwnershipLeaseStore(history_root=tmp_path / "history")


class TestSessionOwnershipLeaseStore:
    """Owner/lease lifecycle semantics."""

    async def test_acquire_creates_lease_file(self, tmp_path: Path) -> None:
        """Acquiring a lease persists an active owner record."""
        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)

        lease = await store.acquire(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=30.0,
        )

        assert lease.session_id == "session-1"
        assert lease.owner_id == "tui-owner-1"
        assert await store.is_active(session_id="session-1") is True

    async def test_renew_preserves_acquired_at_for_same_owner(self, tmp_path: Path) -> None:
        """Renewal by the same owner keeps the original acquisition time."""
        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        first = await store.acquire(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=30.0,
        )

        renewed = await store.renew(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=30.0,
        )

        assert renewed.acquired_at == first.acquired_at
        assert renewed.heartbeat_at >= first.heartbeat_at

    async def test_is_active_returns_false_for_expired_lease(self, tmp_path: Path) -> None:
        """Expired leases are treated as inactive."""
        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        lease = await store.acquire(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=1.0,
        )

        is_active: bool = await store.is_active(
            session_id="session-1",
            now=lease.expires_at + timedelta(seconds=1),
        )

        assert is_active is False

    async def test_release_deletes_matching_lease(self, tmp_path: Path) -> None:
        """Explicit release removes the lease file."""
        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        await store.acquire(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=30.0,
        )

        released: bool = await store.release(session_id="session-1", owner_id="tui-owner-1")

        assert released is True
        assert await store.read(session_id="session-1") is None

    async def test_release_preserves_mismatched_owner_lease(self, tmp_path: Path) -> None:
        """A mismatched owner id must not clear another TUI's lease."""
        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        lease = await store.acquire(
            session_id="session-1",
            owner_id="tui-owner-1",
            ttl_seconds=30.0,
        )

        released: bool = await store.release(session_id="session-1", owner_id="tui-owner-2")

        assert released is False
        assert await store.read(session_id="session-1") == lease
