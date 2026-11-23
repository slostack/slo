"""Tests for ``SessionOwnershipLeaseStore`` (moved to ``sessions/ownership.py`` in 108.6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore


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


_RACE_SCRIPT: str = """
import asyncio, sys, time
from pathlib import Path
from src.agents.slo_agent.sessions.ownership import SessionOwnedElsewhereError, SessionOwnershipLeaseStore

history_root, owner_id, go_file = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
while not go_file.exists():
    time.sleep(0.005)

async def _claim() -> int:
    store = SessionOwnershipLeaseStore(history_root=history_root)
    try:
        await store.acquire(session_id="shared-session", owner_id=owner_id, ttl_seconds=60.0)
    except SessionOwnedElsewhereError:
        return 3
    return 0

sys.exit(asyncio.run(_claim()))
"""


class TestExclusiveOwnership:
    """Only one live owner may hold a session (1081-R01)."""

    async def test_a_second_live_owner_is_refused_and_the_lease_is_untouched(self, tmp_path: Path) -> None:
        from src.agents.slo_agent.sessions.ownership import SessionOwnedElsewhereError
        import pytest

        first_store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        second_store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        lease = await first_store.acquire(session_id="session-1", owner_id="tui-a", ttl_seconds=30.0)

        with pytest.raises(SessionOwnedElsewhereError):
            await second_store.acquire(session_id="session-1", owner_id="tui-b", ttl_seconds=30.0)
        with pytest.raises(SessionOwnedElsewhereError):
            await second_store.renew(session_id="session-1", owner_id="tui-b", ttl_seconds=30.0)

        assert await first_store.read(session_id="session-1") == lease

    async def test_an_expired_lease_hands_over_and_the_old_owner_cannot_renew_it_back(
        self, tmp_path: Path
    ) -> None:
        from src.agents.slo_agent.sessions.ownership import SessionOwnedElsewhereError
        import asyncio
        import pytest

        store: SessionOwnershipLeaseStore = _build_store(tmp_path=tmp_path)
        await store.acquire(session_id="session-1", owner_id="tui-a", ttl_seconds=0.05)
        await asyncio.sleep(0.1)

        taken = await store.acquire(session_id="session-1", owner_id="tui-b", ttl_seconds=30.0)

        assert taken.owner_id == "tui-b"
        with pytest.raises(SessionOwnedElsewhereError):
            await store.renew(session_id="session-1", owner_id="tui-a", ttl_seconds=30.0)

    async def test_four_processes_racing_for_one_session_produce_exactly_one_owner(
        self, tmp_path: Path
    ) -> None:
        import asyncio
        import os
        import sys

        history_root: Path = tmp_path / "history"
        go_file: Path = tmp_path / "go"
        env: dict[str, str] = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        processes: list[asyncio.subprocess.Process] = [
            await asyncio.create_subprocess_exec(
                sys.executable, "-c", _RACE_SCRIPT, str(history_root), f"tui-{index}", str(go_file), env=env
            )
            for index in range(4)
        ]
        await asyncio.sleep(1.0)
        go_file.touch()
        exit_codes: list[int] = [await asyncio.wait_for(process.wait(), timeout=60) for process in processes]

        assert sorted(exit_codes) == [0, 3, 3, 3]
        winner: str = f"tui-{exit_codes.index(0)}"
        lease = await _build_store(tmp_path=tmp_path).read(session_id="shared-session")
        assert lease is not None and lease.owner_id == winner
