"""Own one execution lease, not scheduling or generation allocation.

Acquire before store startup. The caller must join execution and history/store
writers before release; this component cannot infer that those writers settled.
Persistent lock files are never deleted and diagnostic PIDs are never signalled.
"""

from __future__ import annotations

import asyncio
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Callable, Optional, TypeVar

try:
    import fcntl
except ImportError:  # Non-POSIX hosts still support explicit ephemeral ownership.
    fcntl = None  # type: ignore[assignment]

from src.agents.slo_agent.messaging.dao import (
    MessageAdmissionError,
    MessageErrorDAO,
    MessageStoreError,
    SessionAlreadyOwnedError,
    _require_uuid,
)

__all__ = ["SessionExecutionOwnership"]

_LOCK_FILE_NAME = "execution-owner.v1.lock"
_EPHEMERAL_OWNERS: set[str] = set()
_EPHEMERAL_MUTEX = Lock()
_T = TypeVar("_T")


class SessionExecutionOwnership:
    """Hold a private nonblocking flock, or one process-local ephemeral lease."""

    def __init__(self, *, descriptor: Optional[int], session_id: str, executor: ThreadPoolExecutor) -> None:
        """Bind acquired resources; callers construct leases through acquire only."""
        self._descriptor = descriptor
        self._session_id = session_id
        self._executor = executor
        self._release_task: Optional[asyncio.Task[None]] = None

    @classmethod
    async def acquire(
        cls,
        *,
        root: Optional[Path],
        session_id: str,
        executor_factory: Optional[Callable[[], ThreadPoolExecutor]] = None,
    ) -> "SessionExecutionOwnership":
        """Acquire before readiness, joining startup even across repeated cancellation.

        Args:
            root: Resolved history root; None explicitly selects process-local exclusion.
            session_id: Canonical session UUID; this method never allocates a generation.
            executor_factory: Optional dedicated worker factory; ownership transfers to
                the lease, including shutdown on startup failure.

        Returns:
            The exclusive lease, released by the caller only after all writers join.

        Raises:
            SessionAlreadyOwnedError: A live owner already holds this session.
            MessageStoreError: Unsafe path or I/O failure, without raw diagnostics.
            MessageAdmissionError: Persistent no-follow locking is unsupported.
            asyncio.CancelledError: Startup settled and any acquired lease was released.
        """
        try:
            _require_uuid(value=session_id, field="session_id")
        except (ValueError, TypeError):
            raise MessageStoreError() from None
        operation = asyncio.create_task(
            cls._acquire_owned(root=root, session_id=session_id, executor_factory=executor_factory)
        )
        lease, cancelled = await cls._settle(future=operation)
        if cancelled:
            await lease.release()
            raise asyncio.CancelledError()
        return lease

    @classmethod
    async def _acquire_owned(
        cls,
        *,
        root: Optional[Path],
        session_id: str,
        executor_factory: Optional[Callable[[], ThreadPoolExecutor]],
    ) -> "SessionExecutionOwnership":
        """Own startup resources in a task never cancelled by an acquire waiter."""
        executor = (
            executor_factory()
            if executor_factory is not None
            else ThreadPoolExecutor(max_workers=1, thread_name_prefix="slo-msg-owner")
        )
        try:
            descriptor = await asyncio.get_running_loop().run_in_executor(
                executor, lambda: cls._acquire_sync(root=root, session_id=session_id)
            )
            return cls(descriptor=descriptor, session_id=session_id, executor=executor)
        except BaseException:
            executor.shutdown(wait=True)
            raise

    @classmethod
    def _acquire_sync(cls, *, root: Optional[Path], session_id: str) -> Optional[int]:
        """Acquire on the dedicated worker; unwind every partial resource on failure."""
        if root is not None:
            return cls._open_and_lock(root=root, session_id=session_id)
        with _EPHEMERAL_MUTEX:
            if session_id in _EPHEMERAL_OWNERS:
                raise SessionAlreadyOwnedError()
            _EPHEMERAL_OWNERS.add(session_id)
        return None

    @staticmethod
    async def _settle(future: asyncio.Future[_T]) -> tuple[_T, bool]:
        """Join a protected operation; remember cancellation without abandoning it."""
        cancelled = False
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                cancelled = True
        return future.result(), cancelled

    @classmethod
    def _open_directory(cls, *, directory: Path) -> int:
        """Walk from filesystem root with descriptor-relative no-follow opens.

        Missing directories are created privately; existing ancestors are never
        chmodded. The final session directory must belong to the current user.
        """
        descriptors = [os.open("/", os.O_RDONLY | os.O_DIRECTORY)]
        try:
            for component in directory.absolute().parts[1:]:
                if component in (".", ".."):
                    raise MessageStoreError()
                parent = descriptors[-1]
                try:
                    os.mkdir(component, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(descriptor)
            final = descriptors[-1]
            if os.fstat(final).st_uid != os.geteuid():
                raise MessageStoreError()
            os.fchmod(final, 0o700)
            return os.dup(final)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    @classmethod
    def _open_and_lock(cls, *, root: Path, session_id: str) -> int:
        """Acquire a private regular lock inode without following session/file links."""
        if fcntl is None or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise MessageAdmissionError(error=MessageErrorDAO(code="unsupported"))
        directory_fd: Optional[int] = None
        descriptor: Optional[int] = None
        try:
            directory_fd = cls._open_directory(directory=root / session_id)
            descriptor = os.open(
                _LOCK_FILE_NAME,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory_fd,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
            ):
                raise MessageStoreError()
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            held = descriptor
            descriptor = None
            return held
        except BlockingIOError:
            raise SessionAlreadyOwnedError() from None
        except OSError:
            raise MessageStoreError() from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)

    def _release_sync(self) -> None:
        """Drop the worker-owned descriptor or ephemeral entry exactly once."""
        if self._descriptor is None:
            with _EPHEMERAL_MUTEX:
                _EPHEMERAL_OWNERS.discard(self._session_id)
            return
        descriptor = self._descriptor
        self._descriptor = None
        try:
            assert fcntl is not None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        except OSError:
            raise MessageStoreError() from None

    async def _release_owned(self) -> None:
        """Keep cleanup alive until the worker settles, then shut down its executor."""
        try:
            await asyncio.get_running_loop().run_in_executor(self._executor, self._release_sync)
        finally:
            self._executor.shutdown(wait=True)

    async def release(self) -> None:
        """Join the one release operation, including concurrent/cancelled waiters.

        Caller precondition: all execution and history/store writers are joined.
        This method only owns its lock resources, never other session tasks.

        Raises:
            MessageStoreError: Descriptor cleanup failed; no false clean-release result.
            asyncio.CancelledError: Cancellation is propagated only after cleanup settles.
        """
        if self._release_task is None:
            self._release_task = asyncio.create_task(self._release_owned())
        _, cancelled = await self._settle(future=self._release_task)
        if cancelled:
            raise asyncio.CancelledError()
