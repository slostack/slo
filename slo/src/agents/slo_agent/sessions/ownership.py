"""Session ownership lease: which TUI process currently owns a session (108.6).

The lease is a small ``owner.json`` file inside the session's history
directory. It moved here from the retired file-inbox package: the scheduler
still uses it to choose between "queue for the open TUI" (a channel prompt)
and "run fresh headless", and the TUI still renews it while mounted.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = ["SessionOwnedElsewhereError", "SessionOwnershipLeaseDAO", "SessionOwnershipLeaseStore"]


_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600


class SessionOwnedElsewhereError(RuntimeError):
    """Raised when another live owner already holds a session's lease (108.1 §6)."""

    def __init__(self, *, session_id: str, owner_id: str) -> None:
        """Name the session and the live owner that holds it.

        Args:
            session_id (str): Session whose lease was refused.
            owner_id (str): Owner currently holding the unexpired lease.
        """
        super().__init__(f"Session {session_id} is owned by another live TUI ({owner_id}).")
        self.session_id: str = session_id
        self.owner_id: str = owner_id


class SessionOwnershipLeaseDAO(BaseModel):
    """Renewable ownership record for one active TUI session."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(description="Session currently owned by the TUI.")
    owner_kind: Literal["tui"] = Field(default="tui", description="The only supported owner kind in v1.")
    owner_id: str = Field(description="Stable owner identifier for this TUI process.")
    pid: int = Field(description="Owning process id.")
    host: str = Field(description="Owning hostname.")
    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time when the lease was first acquired.",
    )
    heartbeat_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC time of the most recent lease heartbeat.",
    )
    expires_at: datetime = Field(description="UTC time after which the lease is stale.")


class SessionOwnershipLeaseStore:
    """Durable owner/lease records colocated with session history.

    WHAT: a *lease* is a small ``owner.json`` file inside a session's history
        directory naming the single TUI process currently entitled to own
        that session: the one TUI that runs its channel poller (108.1 §6) and
        receives scheduled prompts through the channel queue (108.6).
    WHO: the mounted ``SloTUI`` acquires the lease at startup, renews it on a
        heartbeat interval for the life of the app, and releases it on
        shutdown. The scheduler uses ``is_active`` to choose between queueing
        a channel prompt for the open TUI and running a fresh headless turn.
    WHEN/EXPIRY: each lease carries an ``expires_at`` (now + TTL). A TUI that
        crashes without releasing simply stops heartbeating, so its lease
        goes stale and expires — at which point another TUI may acquire the
        session. That expiry is the handoff mechanism: ownership is never
        permanently lost to a dead process.
    """

    def __init__(self, *, history_root: Path) -> None:
        """Bind the store to a session-history root.

        Args:
            history_root (Path): Root directory containing per-session folders.
        """
        self._history_root: Path = history_root.expanduser().resolve()
        self._lock: asyncio.Lock = asyncio.Lock()

    @staticmethod
    def default_owner_id() -> str:
        """Return a stable-ish owner id for the current process lifetime.

        Returns:
            str: A process-scoped owner identifier.
        """
        return f"tui-{uuid4()}"

    async def acquire(
        self,
        *,
        session_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> SessionOwnershipLeaseDAO:
        """Acquire (or refresh) the exclusive lease for ``session_id``.

        The read-decide-write runs under an exclusive ``flock`` on the
        session's ``owner.lock``, so concurrent processes serialize: a lease
        that is missing, expired or already held by ``owner_id`` is written;
        an unexpired lease of a different owner is left untouched and refused.

        Args:
            session_id (str): Session the TUI is actively owning.
            owner_id (str): Stable owner identifier for the TUI process.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: The persisted lease.

        Raises:
            SessionOwnedElsewhereError: Another owner holds an unexpired lease.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._acquire_sync,
                session_id=session_id,
                owner_id=owner_id,
                ttl_seconds=ttl_seconds,
            )

    async def renew(
        self,
        *,
        session_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> SessionOwnershipLeaseDAO:
        """Refresh an existing lease, or acquire it if missing or expired.

        Args:
            session_id (str): Session the TUI is actively owning.
            owner_id (str): Stable owner identifier for the TUI process.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: The renewed lease.

        Raises:
            SessionOwnedElsewhereError: Another owner took the session over
                after this owner's lease expired.
        """
        return await self.acquire(
            session_id=session_id,
            owner_id=owner_id,
            ttl_seconds=ttl_seconds,
        )

    async def read(self, *, session_id: str) -> Optional[SessionOwnershipLeaseDAO]:
        """Return the lease for ``session_id`` when present and parseable.

        Args:
            session_id (str): Session whose lease should be read.

        Returns:
            Optional[SessionOwnershipLeaseDAO]: Lease or ``None``.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._read_sync,
                session_id=session_id,
            )

    async def is_active(self, *, session_id: str, now: Optional[datetime] = None) -> bool:
        """Return whether ``session_id`` currently has a valid lease.

        Args:
            session_id (str): Session under inspection.
            now (Optional[datetime]): Override clock for tests.

        Returns:
            bool: True when a non-expired lease exists.
        """
        lease: Optional[SessionOwnershipLeaseDAO] = await self.read(session_id=session_id)
        if lease is None:
            return False
        reference_time: datetime = now or datetime.now(timezone.utc)
        return lease.expires_at > reference_time

    async def release(self, *, session_id: str, owner_id: Optional[str] = None) -> bool:
        """Delete the current lease file when present.

        Args:
            session_id (str): Session whose lease should be cleared.
            owner_id (Optional[str]): Optional owner check. When provided, a
                mismatched lease is preserved.

        Returns:
            bool: True when the lease file was removed.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._release_sync,
                session_id=session_id,
                owner_id=owner_id,
            )

    def _session_dir(self, *, session_id: str) -> Path:
        """Return the owning session directory.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: ``<history_root>/<session_id>``.
        """
        return self._history_root / session_id

    def _lease_path(self, *, session_id: str) -> Path:
        """Return the lease-file path for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: ``owner.json`` inside the session directory.
        """
        return self._session_dir(session_id=session_id) / "owner.json"

    @classmethod
    def _ensure_dir(cls, *, path: Path) -> None:
        """Create or chmod a private directory.

        Args:
            path (Path): Directory to ensure.
        """
        # ``exist_ok``: concurrent owners racing for one session create it together.
        path.mkdir(parents=True, mode=_DIR_MODE, exist_ok=True)
        path.chmod(_DIR_MODE)

    @classmethod
    def _atomic_write_json(cls, *, path: Path, payload: dict) -> None:
        """Write ``payload`` atomically with private file permissions.

        Args:
            path (Path): Destination file path.
            payload (dict): JSON payload to persist.
        """
        cls._ensure_dir(path=path.parent)
        tmp_path: Path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(_FILE_MODE)
        tmp_path.replace(path)

    def _acquire_sync(
        self,
        *,
        session_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> SessionOwnershipLeaseDAO:
        """Synchronously create or refresh a lease under the cross-process lock.

        Args:
            session_id (str): Session the TUI owns.
            owner_id (str): Stable owner identifier.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: Persisted lease.

        Raises:
            SessionOwnedElsewhereError: Another owner holds an unexpired lease.
        """
        session_dir: Path = self._session_dir(session_id=session_id)
        self._ensure_dir(path=session_dir)
        lock_fd: int = os.open(session_dir / "owner.lock", os.O_RDWR | os.O_CREAT, _FILE_MODE)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            return self._write_exclusive_lease_sync(
                session_id=session_id, owner_id=owner_id, ttl_seconds=ttl_seconds
            )
        finally:
            os.close(lock_fd)

    def _write_exclusive_lease_sync(
        self,
        *,
        session_id: str,
        owner_id: str,
        ttl_seconds: float,
    ) -> SessionOwnershipLeaseDAO:
        """Write the lease unless a different live owner holds it (caller holds ``owner.lock``).

        Args:
            session_id (str): Session the TUI owns.
            owner_id (str): Stable owner identifier.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: Persisted lease.

        Raises:
            SessionOwnedElsewhereError: Another owner holds an unexpired lease.
        """
        current_time: datetime = datetime.now(timezone.utc)
        current_lease: Optional[SessionOwnershipLeaseDAO] = self._read_sync(session_id=session_id)
        if (
            current_lease is not None
            and current_lease.owner_id != owner_id
            and current_lease.expires_at > current_time
        ):
            raise SessionOwnedElsewhereError(session_id=session_id, owner_id=current_lease.owner_id)
        acquired_at: datetime = (
            current_lease.acquired_at
            if current_lease is not None and current_lease.owner_id == owner_id
            else current_time
        )
        lease: SessionOwnershipLeaseDAO = SessionOwnershipLeaseDAO(
            session_id=session_id,
            owner_id=owner_id,
            pid=os.getpid(),
            host=socket.gethostname(),
            acquired_at=acquired_at,
            heartbeat_at=current_time,
            expires_at=current_time + timedelta(seconds=ttl_seconds),
        )
        self._atomic_write_json(
            path=self._lease_path(session_id=session_id),
            payload=lease.model_dump(mode="json"),
        )
        return lease

    def _read_sync(self, *, session_id: str) -> Optional[SessionOwnershipLeaseDAO]:
        """Synchronously read a lease file.

        Args:
            session_id (str): Session under inspection.

        Returns:
            Optional[SessionOwnershipLeaseDAO]: Parsed lease or ``None``.
        """
        path: Path = self._lease_path(session_id=session_id)
        if not path.exists():
            return None
        try:
            payload: str = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            return SessionOwnershipLeaseDAO.model_validate_json(payload)
        except ValidationError:
            return None

    def _release_sync(self, *, session_id: str, owner_id: Optional[str]) -> bool:
        """Synchronously delete a lease if it matches the optional owner.

        Args:
            session_id (str): Session whose lease should be removed.
            owner_id (Optional[str]): Optional owner check.

        Returns:
            bool: True when a lease was deleted.
        """
        session_dir: Path = self._session_dir(session_id=session_id)
        if not session_dir.is_dir():
            return False
        lock_fd: int = os.open(session_dir / "owner.lock", os.O_RDWR | os.O_CREAT, _FILE_MODE)
        try:
            # Same lock as acquisition: a successor's fresh lease written after
            # this owner's expiry is never unlinked by this owner's release.
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            lease: Optional[SessionOwnershipLeaseDAO] = self._read_sync(session_id=session_id)
            if lease is None:
                return False
            if owner_id is not None and lease.owner_id != owner_id:
                return False
            try:
                self._lease_path(session_id=session_id).unlink()
            except FileNotFoundError:
                return False
            return True
        finally:
            os.close(lock_fd)
