"""Behavior tests for SessionExecutionOwnership (feature 96, sub-spec A.1, Change 2).

Uses real POSIX flock on tmp_path lock files and one real independent
subprocess for cross-process exclusion. No internal monkeypatching.
"""

from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

import fcntl

from src.agents.slo_agent.messaging.dao import (
    MessageAdmissionError,
    MessageStoreError,
    SessionAlreadyOwnedError,
)
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership


def _lock_path(*, root: Path, session_id: str) -> Path:
    """Return the execution-owner lock path for one session."""
    return root / session_id / "execution-owner.v1.lock"


class TestAcquireRelease:
    """Single-owner flock acquisition with private permissions."""

    async def test_acquire_creates_private_lock(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        try:
            lock_path = _lock_path(root=tmp_path, session_id=session_id)
            assert lock_path.exists()
            assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(lock_path.parent.stat().st_mode) == 0o700
        finally:
            await ownership.release()

    async def test_second_live_owner_is_refused(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        first = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        with pytest.raises(SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await first.release()

    async def test_release_permits_fresh_owner(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        first = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await first.release()
        second = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await second.release()

    async def test_release_is_idempotent(self, tmp_path: Path) -> None:
        ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=str(uuid4()))
        await ownership.release()
        await ownership.release()

    async def test_stale_lock_file_is_never_deleted(self, tmp_path: Path) -> None:
        """A leftover lock file from a dead owner stays; it is never removed."""
        session_id = str(uuid4())
        lock_path = _lock_path(root=tmp_path, session_id=session_id)
        lock_path.parent.mkdir(parents=True)
        lock_path.write_bytes(b"stale")
        ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await ownership.release()
        assert lock_path.exists()
        assert lock_path.read_bytes() == b"stale"


class TestAcquireValidation:
    """Unsafe inputs are refused before any lock is touched."""

    async def test_non_uuid_session_id_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises((MessageStoreError, ValueError)):
            await SessionExecutionOwnership.acquire(root=tmp_path, session_id="not-a-uuid")

    async def test_symlinked_ancestry_is_refused(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "linked"
        link_dir.symlink_to(real_dir)
        with pytest.raises(MessageStoreError) as exc_info:
            await SessionExecutionOwnership.acquire(root=link_dir, session_id=str(uuid4()))
        assert str(exc_info.value) == "storage_unavailable"

    async def test_symlinked_lock_file_is_refused(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        session_dir = tmp_path / session_id
        session_dir.mkdir()
        elsewhere = tmp_path / "elsewhere.lock"
        elsewhere.write_bytes(b"")
        _lock_path(root=tmp_path, session_id=session_id).symlink_to(elsewhere)
        with pytest.raises(MessageStoreError):
            await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)

    async def test_error_text_is_safe(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_dir = tmp_path / "linked"
        link_dir.symlink_to(real_dir)
        with pytest.raises(MessageStoreError) as exc_info:
            await SessionExecutionOwnership.acquire(root=link_dir, session_id=str(uuid4()))
        assert str(exc_info.value) == "storage_unavailable"
        assert str(link_dir) not in str(exc_info.value)


class TestEphemeralOwnership:
    """root=None selects explicit process-local exclusive ownership."""

    async def test_ephemeral_acquire_and_release(self) -> None:
        ownership = await SessionExecutionOwnership.acquire(root=None, session_id=str(uuid4()))
        await ownership.release()

    async def test_ephemeral_excludes_within_process(self) -> None:
        session_id = str(uuid4())
        first = await SessionExecutionOwnership.acquire(root=None, session_id=session_id)
        with pytest.raises(SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=None, session_id=session_id)
        await first.release()
        second = await SessionExecutionOwnership.acquire(root=None, session_id=session_id)
        await second.release()

    async def test_ephemeral_does_not_conflict_with_persistent(self, tmp_path: Path) -> None:
        """Ephemeral and persistent ownership are separate namespaces."""
        session_id = str(uuid4())
        ephemeral = await SessionExecutionOwnership.acquire(root=None, session_id=session_id)
        persistent = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await ephemeral.release()
        await persistent.release()


class TestExclusiveWhileHeld:
    """The held descriptor excludes any other flock acquirer, in-process or not."""

    async def test_raw_flock_is_refused_while_held(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        lock_path = _lock_path(root=tmp_path, session_id=session_id)
        descriptor = os.open(lock_path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        await ownership.release()


class TestTwoProcessesOneOwner:
    """A second real process is refused while the first owner lives."""

    _CHILD_PROGRAM = (
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership\n"
        "from src.agents.slo_agent.messaging.dao import SessionAlreadyOwnedError\n"
        "async def main() -> None:\n"
        "    try:\n"
        "        ownership = await SessionExecutionOwnership.acquire(\n"
        "            root=Path(sys.argv[1]), session_id=sys.argv[2])\n"
        "    except SessionAlreadyOwnedError:\n"
        "        print('refused', flush=True)\n"
        "        return\n"
        "    print('acquired', flush=True)\n"
        "    await ownership.release()\n"
        "asyncio.run(main())\n"
    )

    def _run_child(self, *, root: Path, session_id: str) -> str:
        """Run the acquisition child process and return its stdout verdict."""
        result = subprocess.run(
            [sys.executable, "-c", self._CHILD_PROGRAM, str(root), session_id],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).resolve().parents[4],
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    async def test_second_process_is_refused_while_held(self, tmp_path: Path) -> None:
        """A second real process cannot acquire while this owner lives."""
        session_id = str(uuid4())
        ownership = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        assert await asyncio.to_thread(self._run_child, root=tmp_path, session_id=session_id) == "refused"
        await ownership.release()

    def test_fresh_process_acquires_uncontended_lock(self, tmp_path: Path) -> None:
        """An unheld lock is acquirable by a fresh real process."""
        assert self._run_child(root=tmp_path, session_id=str(uuid4())) == "acquired"

    def test_crash_of_owner_permits_fresh_owner(self, tmp_path: Path) -> None:
        """A process killed while holding the lock frees it (flock semantics)."""
        session_id = str(uuid4())
        holder_program = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "root = Path(sys.argv[1]); session_id = sys.argv[2]\n"
            "directory = root / session_id\n"
            "directory.mkdir(parents=True, exist_ok=True)\n"
            "fd = os.open(directory / 'execution-owner.v1.lock', os.O_RDWR | os.O_CREAT, 0o600)\n"
            "import fcntl\n"
            "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "print('held', flush=True)\n"
            "import time\n"
            "time.sleep(60)\n"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_program, str(tmp_path), session_id],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            assert self._run_child(root=tmp_path, session_id=session_id) == "refused"
        finally:
            holder.kill()
            holder.wait(timeout=30)
        assert self._run_child(root=tmp_path, session_id=session_id) == "acquired"


class TestCancellationJoinsAcquisition:
    """A cancelled waiter still joins the started acquisition."""

    async def test_cancelled_acquire_leaves_no_leaked_owner(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        task = asyncio.create_task(SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        fresh = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await fresh.release()

    async def test_failed_acquire_leaves_no_leaked_owner(self, tmp_path: Path) -> None:
        session_id = str(uuid4())
        first = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        with pytest.raises(SessionAlreadyOwnedError):
            await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await first.release()
        fresh = await SessionExecutionOwnership.acquire(root=tmp_path, session_id=session_id)
        await fresh.release()
