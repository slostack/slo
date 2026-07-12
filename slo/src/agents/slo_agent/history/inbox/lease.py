"""Filesystem-backed session-ownership lease helpers."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import ValidationError

from src.agents.slo_agent.history.inbox.dao import SessionOwnershipLeaseDAO

__all__ = ["SessionOwnershipLeaseStore"]


_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600


class SessionOwnershipLeaseStore:
    """Durable owner/lease records colocated with session history."""

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
        """Create or overwrite the active lease for ``session_id``.

        Args:
            session_id (str): Session the TUI is actively owning.
            owner_id (str): Stable owner identifier for the TUI process.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: The persisted lease.
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
        """Refresh an existing lease, or acquire it if missing.

        Args:
            session_id (str): Session the TUI is actively owning.
            owner_id (str): Stable owner identifier for the TUI process.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: The renewed lease.
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
        if not path.exists():
            path.mkdir(parents=True, mode=_DIR_MODE)
            return
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
        """Synchronously create or refresh a lease.

        Args:
            session_id (str): Session the TUI owns.
            owner_id (str): Stable owner identifier.
            ttl_seconds (float): Lease time-to-live in seconds.

        Returns:
            SessionOwnershipLeaseDAO: Persisted lease.
        """
        session_dir: Path = self._session_dir(session_id=session_id)
        self._ensure_dir(path=session_dir)
        current_time: datetime = datetime.now(timezone.utc)
        current_lease: Optional[SessionOwnershipLeaseDAO] = self._read_sync(session_id=session_id)
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
        lease: Optional[SessionOwnershipLeaseDAO] = self._read_sync(session_id=session_id)
        if lease is None:
            return False
        if owner_id is not None and lease.owner_id != owner_id:
            return False
        path: Path = self._lease_path(session_id=session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
