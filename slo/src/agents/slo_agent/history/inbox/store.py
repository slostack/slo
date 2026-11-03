"""Filesystem-backed per-session inbox queue."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError
from src.agents.slo_agent.messaging.dao import _require_uuid

from src.agents.slo_agent.history.inbox.dao import (
    InboxEnqueueResultDAO,
    SessionInboxMessageDAO,
)

__all__ = ["SessionInboxStore", "SessionInboxClaimReadError"]


_DIR_MODE: int = 0o700
_FILE_MODE: int = 0o600


class SessionInboxClaimReadError(Exception):
    """Unreadable claimed item with a filename-derived safe paging cursor."""

    def __init__(self, *, message_id: str) -> None:
        """Keep content and filesystem errors private; expose only the canonical UUID."""
        self.message_id: str = message_id
        super().__init__("Inbox claim unreadable")


class SessionInboxStore:
    """Maildir-style queue colocated with session history."""

    def __init__(self, *, history_root: Path) -> None:
        """Bind the inbox store to a session-history root.

        Args:
            history_root (Path): Root directory containing per-session folders.
        """
        self._history_root: Path = history_root.expanduser().resolve()
        self._lock: asyncio.Lock = asyncio.Lock()

    async def ensure_session_inbox(self, *, session_id: str) -> Path:
        """Create the inbox directory structure for ``session_id``.

        Args:
            session_id (str): Target session identifier.

        Returns:
            Path: The session's inbox root.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._ensure_session_inbox_sync,
                session_id=session_id,
            )

    async def enqueue(self, *, message: SessionInboxMessageDAO) -> InboxEnqueueResultDAO:
        """Append or coalesce one pending inbox item.

        Args:
            message (SessionInboxMessageDAO): Message to queue.

        Returns:
            InboxEnqueueResultDAO: Queue outcome.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._enqueue_sync,
                message=message,
            )

    async def list_pending(self, *, session_id: str) -> list[SessionInboxMessageDAO]:
        """Return every pending item for ``session_id`` oldest-first.

        Args:
            session_id (str): Target session identifier.

        Returns:
            list[SessionInboxMessageDAO]: Parsed pending messages.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._list_messages_sync,
                directory=self._pending_dir(session_id=session_id),
            )

    async def claim_next(self, *, session_id: str) -> Optional[SessionInboxMessageDAO]:
        """Atomically move the oldest pending item into ``claimed/``.

        Args:
            session_id (str): Target session identifier.

        Returns:
            Optional[SessionInboxMessageDAO]: Claimed item, or ``None`` when empty.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._claim_next_sync,
                session_id=session_id,
            )

    async def read_claimed(
        self, *, session_id: str, after_message_id: Optional[str] = None, limit: int = 16
    ) -> tuple[SessionInboxMessageDAO, ...]:
        """Read at most sixteen claims in UUID order without moving or admitting them.

        Args:
            session_id: Owning Inbox session.
            after_message_id: Exclusive canonical UUID cursor, or None to start.
            limit: Integer page size from one through sixteen.

        Returns:
            Valid prefix before the first corrupt selected item.

        Raises:
            ValueError: Invalid cursor or limit, before filesystem I/O.
            SessionInboxClaimReadError: First selected file cannot be validated.
        """
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Invalid Inbox claim page limit")
        if after_message_id is not None:
            if not isinstance(after_message_id, str):
                raise ValueError("Invalid Inbox claim cursor")
            _require_uuid(value=after_message_id, field="after_message_id")
        async with self._lock:
            return await asyncio.to_thread(
                self._read_claimed_sync,
                session_id=session_id,
                after_message_id=after_message_id,
                limit=limit,
            )

    def _read_claimed_sync(
        self, *, session_id: str, after_message_id: Optional[str], limit: int
    ) -> tuple[SessionInboxMessageDAO, ...]:
        """Select filename UUIDs before reading bounded content; surface corrupt cursors."""
        candidates: list[tuple[str, Path]] = []
        for path in self._claimed_dir(session_id=session_id).glob("*.json"):
            message_id = path.stem[-36:]
            try:
                _require_uuid(value=message_id, field="filename")
            except ValueError:
                continue
            if len(path.stem) < 38 or path.stem[-37] != "-":
                continue
            if after_message_id is None or message_id > after_message_id:
                candidates.append((message_id, path))
        messages: list[SessionInboxMessageDAO] = []
        for message_id, path in sorted(candidates)[:limit]:
            message = self._read_message_file(path=path)
            if message is None or message.message_id != message_id or message.session_id != session_id:
                if messages:
                    break
                raise SessionInboxClaimReadError(message_id=message_id)
            messages.append(message)
        return tuple(messages)

    async def ack(self, *, session_id: str, message_id: str) -> bool:
        """Move a claimed item into ``done/``.

        Args:
            session_id (str): Target session identifier.
            message_id (str): Claimed message identifier.

        Returns:
            bool: True when the claimed file was acknowledged.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._ack_sync,
                session_id=session_id,
                message_id=message_id,
            )

    async def list_done(self, *, session_id: str) -> list[SessionInboxMessageDAO]:
        """Return every done item for ``session_id`` oldest-first.

        Args:
            session_id (str): Target session identifier.

        Returns:
            list[SessionInboxMessageDAO]: Parsed done messages.
        """
        async with self._lock:
            return await asyncio.to_thread(
                self._list_messages_sync,
                directory=self._done_dir(session_id=session_id),
            )

    def _session_dir(self, *, session_id: str) -> Path:
        """Return the owning session directory.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: ``<history_root>/<session_id>``.
        """
        return self._history_root / session_id

    def _inbox_dir(self, *, session_id: str) -> Path:
        """Return the inbox root for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: ``<history_root>/<session_id>/inbox``.
        """
        return self._session_dir(session_id=session_id) / "inbox"

    def _tmp_dir(self, *, session_id: str) -> Path:
        """Return the temporary lane for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Temp directory path.
        """
        return self._inbox_dir(session_id=session_id) / "tmp"

    def _pending_dir(self, *, session_id: str) -> Path:
        """Return the pending lane for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Pending directory path.
        """
        return self._inbox_dir(session_id=session_id) / "pending"

    def _claimed_dir(self, *, session_id: str) -> Path:
        """Return the claimed lane for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Claimed directory path.
        """
        return self._inbox_dir(session_id=session_id) / "claimed"

    def _done_dir(self, *, session_id: str) -> Path:
        """Return the done lane for ``session_id``.

        Args:
            session_id (str): Session identifier.

        Returns:
            Path: Done directory path.
        """
        return self._inbox_dir(session_id=session_id) / "done"

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

    def _ensure_session_inbox_sync(self, *, session_id: str) -> Path:
        """Synchronously create the inbox lane directories.

        Args:
            session_id (str): Target session identifier.

        Returns:
            Path: Inbox root path.
        """
        session_dir: Path = self._session_dir(session_id=session_id)
        self._ensure_dir(path=session_dir)
        inbox_dir: Path = self._inbox_dir(session_id=session_id)
        self._ensure_dir(path=inbox_dir)
        self._ensure_dir(path=self._tmp_dir(session_id=session_id))
        self._ensure_dir(path=self._pending_dir(session_id=session_id))
        self._ensure_dir(path=self._claimed_dir(session_id=session_id))
        self._ensure_dir(path=self._done_dir(session_id=session_id))
        return inbox_dir

    @classmethod
    def _message_filename(cls, *, message: SessionInboxMessageDAO) -> str:
        """Return the sortable filename for ``message``.

        Args:
            message (SessionInboxMessageDAO): Message under serialization.

        Returns:
            str: Sort-friendly message filename.
        """
        timestamp_prefix: str = message.created_at.strftime("%Y%m%dT%H%M%S.%fZ")
        return f"{timestamp_prefix}-{message.message_id}.json"

    @classmethod
    def _atomic_write_json(cls, *, path: Path, payload: dict) -> None:
        """Atomically persist one JSON payload.

        Args:
            path (Path): Destination file path.
            payload (dict): JSON payload to write.
        """
        cls._ensure_dir(path=path.parent)
        tmp_path: Path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.chmod(_FILE_MODE)
        tmp_path.replace(path)

    @classmethod
    def _read_message_file(cls, *, path: Path) -> Optional[SessionInboxMessageDAO]:
        """Parse one inbox file into a DAO.

        Args:
            path (Path): File to parse.

        Returns:
            Optional[SessionInboxMessageDAO]: Parsed message or ``None``.
        """
        try:
            payload: str = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        try:
            return SessionInboxMessageDAO.model_validate_json(payload)
        except ValidationError:
            return None

    def _enqueue_sync(self, *, message: SessionInboxMessageDAO) -> InboxEnqueueResultDAO:
        """Synchronously queue or coalesce one message.

        Args:
            message (SessionInboxMessageDAO): Message to persist.

        Returns:
            InboxEnqueueResultDAO: Queue outcome.
        """
        self._ensure_session_inbox_sync(session_id=message.session_id)
        if message.coalesce_key is not None:
            coalesced: InboxEnqueueResultDAO | None = self._coalesce_pending_if_present(
                message=message,
            )
            if coalesced is not None:
                return coalesced

        pending_path: Path = self._pending_dir(session_id=message.session_id) / self._message_filename(
            message=message,
        )
        self._atomic_write_json(
            path=pending_path,
            payload=message.model_dump(mode="json"),
        )
        return InboxEnqueueResultDAO(result="queued", message=message, replaced_message_id=None)

    def _coalesce_pending_if_present(
        self,
        *,
        message: SessionInboxMessageDAO,
    ) -> Optional[InboxEnqueueResultDAO]:
        """Replace an older pending item with matching coalesce key.

        Args:
            message (SessionInboxMessageDAO): Newer message being queued.

        Returns:
            Optional[InboxEnqueueResultDAO]: Coalesce result when a match existed.
        """
        pending_dir: Path = self._pending_dir(session_id=message.session_id)
        for candidate_path in sorted(pending_dir.glob("*.json")):
            candidate: Optional[SessionInboxMessageDAO] = self._read_message_file(path=candidate_path)
            if candidate is None:
                continue
            if candidate.coalesce_key != message.coalesce_key:
                continue
            replacement_path: Path = pending_dir / self._message_filename(message=message)
            self._atomic_write_json(
                path=replacement_path,
                payload=message.model_dump(mode="json"),
            )
            if candidate_path != replacement_path and candidate_path.exists():
                candidate_path.unlink()
            return InboxEnqueueResultDAO(
                result="coalesced",
                message=message,
                replaced_message_id=candidate.message_id,
            )
        return None

    def _list_messages_sync(self, *, directory: Path) -> list[SessionInboxMessageDAO]:
        """Synchronously read every parseable message in ``directory``.

        Args:
            directory (Path): Inbox lane directory.

        Returns:
            list[SessionInboxMessageDAO]: Parsed messages in sorted filename order.
        """
        if not directory.exists():
            return []
        messages: list[SessionInboxMessageDAO] = []
        for path in sorted(directory.glob("*.json")):
            message: Optional[SessionInboxMessageDAO] = self._read_message_file(path=path)
            if message is not None:
                messages.append(message)
        return messages

    def _claim_next_sync(self, *, session_id: str) -> Optional[SessionInboxMessageDAO]:
        """Synchronously move the oldest pending message into ``claimed/``.

        Args:
            session_id (str): Target session identifier.

        Returns:
            Optional[SessionInboxMessageDAO]: Claimed message or ``None``.
        """
        self._ensure_session_inbox_sync(session_id=session_id)
        pending_dir: Path = self._pending_dir(session_id=session_id)
        for path in sorted(pending_dir.glob("*.json")):
            claimed_path: Path = self._claimed_dir(session_id=session_id) / path.name
            try:
                path.replace(claimed_path)
            except FileNotFoundError:
                continue
            return self._read_message_file(path=claimed_path)
        return None

    def _move_between_lanes_sync(self, *, source: Path, destination: Path) -> bool:
        """Synchronously move one lane file to another lane.

        Args:
            source (Path): Current file path.
            destination (Path): Desired file path.

        Returns:
            bool: True when the move succeeded.
        """
        if not source.exists():
            return False
        self._ensure_dir(path=destination.parent)
        source.replace(destination)
        return True

    def _ack_sync(self, *, session_id: str, message_id: str) -> bool:
        """Synchronously acknowledge one claimed message by id.

        Args:
            session_id (str): Target session identifier.
            message_id (str): Claimed message identifier.

        Returns:
            bool: True when a matching claimed file was moved to ``done/``.
        """
        claimed_dir: Path = self._claimed_dir(session_id=session_id)
        for source in sorted(claimed_dir.glob("*.json")):
            message: Optional[SessionInboxMessageDAO] = self._read_message_file(path=source)
            if message is None:
                continue
            if message.message_id != message_id:
                continue
            destination: Path = self._done_dir(session_id=session_id) / source.name
            return self._move_between_lanes_sync(
                source=source,
                destination=destination,
            )
        return False
