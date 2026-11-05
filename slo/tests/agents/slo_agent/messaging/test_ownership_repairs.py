"""Real-file ownership regressions for the Change2 cancellation and path contract."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import MessageStoreError
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership


async def _turns() -> None:
    """Let submitted lifecycle operations reach their shielded worker wait."""
    for _ in range(10):
        await asyncio.sleep(0)


class TestOwnershipPathRepairs:
    async def test_session_symlink_is_refused_without_touching_destination(self, tmp_path: Path) -> None:
        """A UUID session directory link must not grant ownership outside that directory."""
        session_id = str(uuid4())
        destination = tmp_path / "untouched"
        destination.mkdir(mode=0o755)
        before = destination.stat().st_mode
        (tmp_path / session_id).symlink_to(destination, target_is_directory=True)
        ownership = None
        try:
            with pytest.raises(MessageStoreError):
                ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
            assert destination.stat().st_mode == before
            assert list(destination.iterdir()) == []
        finally:
            if ownership is not None:
                await ownership.release()

    async def test_hardlinked_lock_is_refused_without_changing_shared_inode(self, tmp_path: Path) -> None:
        """A regular file with another name is not a private ownership file."""
        import os

        session_id = str(uuid4())
        directory = tmp_path / session_id
        directory.mkdir()
        original = tmp_path / "shared"
        original.write_text("unchanged")
        before = original.stat().st_mode
        os.link(src=original, dst=directory / "execution-owner.v1.lock")
        ownership = None
        try:
            with pytest.raises(MessageStoreError):
                ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
            assert original.stat().st_mode == before
            assert original.read_text() == "unchanged"
        finally:
            if ownership is not None:
                await ownership.release()


class TestJoinedOwnershipCancellation:
    async def test_twice_cancelled_acquire_joins_and_releases_started_work(self, tmp_path: Path) -> None:
        """Cancellation cannot return while the dedicated acquisition worker is blocked."""
        session_id = str(uuid4())
        worker = ThreadPoolExecutor(max_workers=1)
        gate = Event()
        blocker = worker.submit(gate.wait, timeout=10)
        task = asyncio.create_task(
            SessionExecutionOwnership.acquire(
                root=tmp_path, session_id=session_id, executor_factory=lambda: worker
            )
        )
        try:
            await _turns()
            task.cancel()
            await _turns()
            task.cancel()
            await _turns()
            assert not task.done()
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), timeout=5)
            fresh = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
            await fresh.release()
        finally:
            gate.set()
            blocker.result(timeout=5)
            await asyncio.gather(task, return_exceptions=True)
            worker.shutdown(wait=True)

    @pytest.mark.parametrize("persistent", [False, True])
    async def test_twice_cancelled_release_and_concurrent_release_join_one_cleanup(
        self, tmp_path: Path, persistent: bool
    ) -> None:
        """Every release waiter joins cleanup, including ephemeral exclusion removal."""
        session_id = str(uuid4())
        worker = ThreadPoolExecutor(max_workers=1)
        root = tmp_path if persistent else None
        ownership = await SessionExecutionOwnership.acquire(
            root=root, session_id=session_id, executor_factory=lambda: worker
        )
        gate = Event()
        blocker = worker.submit(gate.wait, timeout=10)
        first = asyncio.create_task(ownership.release())
        second = asyncio.create_task(ownership.release())
        try:
            await _turns()
            first.cancel()
            await _turns()
            first.cancel()
            await _turns()
            assert not first.done()
            assert not second.done()
            gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(first), timeout=5)
            await asyncio.wait_for(second, timeout=5)
            await ownership.release()
            fresh = await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
            await fresh.release()
        finally:
            gate.set()
            blocker.result(timeout=5)
            await asyncio.gather(first, second, return_exceptions=True)
            worker.shutdown(wait=True)
