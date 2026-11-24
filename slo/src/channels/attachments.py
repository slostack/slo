"""AttachmentStore — which agent each platform user talks to (108.5 §2 Attach).

A platform user talks to one agent at a time: ``/attach <session-prefix>``
picks it and ``/detach`` drops it. The choice is stored per user in one small
JSON file per channel, ``$SLO_HOME/channels/<channel id>.json`` (mode 0600),
so it survives an adapter restart. The file is named by channel id, not by
adapter name, so it never collides with an adapter's config file such as
``telegram.json``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.logger import log_warning

from src.channels.dao import AttachmentDAO, utc_now

__all__ = ["AttachmentStore"]


class _AttachmentFileDAO(BaseModel):
    """On-disk shape of one channel's attachment file."""

    model_config = ConfigDict(frozen=True)

    channel_id: UUID = Field(description="Channel whose users these attachments belong to.")
    attachments: list[AttachmentDAO] = Field(
        default_factory=list,
        description="One attachment per platform user who has used /attach or /detach.",
    )


class AttachmentStore:
    """Owns one channel's user → agent attachments and their private JSON file.

    The adapter host is the only writer; it runs in one asyncio loop and every
    method here is synchronous, so no two updates interleave.
    """

    def __init__(self, *, path: Path, channel_id: UUID) -> None:
        """Load the channel's attachments from ``path``.

        A missing file means nobody is attached. A file that cannot be parsed
        is renamed to ``<name>.corrupt-<UTC stamp>`` (kept for inspection) and
        the store starts empty.

        Args:
            path (Path): The channel's attachment file.
            channel_id (UUID): The channel these attachments belong to.
        """
        self._path: Path = path
        self._channel_id: UUID = channel_id
        self._attachments: dict[UUID, AttachmentDAO] = self._load()

    def get(self, *, participant_id: UUID) -> Optional[AttachmentDAO]:
        """Return one user's attachment, or ``None`` when they never attached.

        Args:
            participant_id (UUID): The platform user.

        Returns:
            Optional[AttachmentDAO]: The stored attachment (its ``agent_id``
                is ``None`` after ``/detach``).
        """
        return self._attachments.get(participant_id)

    def attach(self, *, participant_id: UUID, agent_id: UUID) -> AttachmentDAO:
        """Attach one user to one agent and persist the choice.

        Args:
            participant_id (UUID): The platform user.
            agent_id (UUID): The agent they will talk to.

        Returns:
            AttachmentDAO: The stored attachment.
        """
        return self._store(participant_id=participant_id, agent_id=agent_id)

    def detach(self, *, participant_id: UUID) -> AttachmentDAO:
        """Detach one user from whatever agent they talk to and persist it.

        Args:
            participant_id (UUID): The platform user.

        Returns:
            AttachmentDAO: The stored attachment with ``agent_id=None``.
        """
        return self._store(participant_id=participant_id, agent_id=None)

    def _store(self, *, participant_id: UUID, agent_id: Optional[UUID]) -> AttachmentDAO:
        """Record one attachment change in memory and on disk.

        Args:
            participant_id (UUID): The platform user.
            agent_id (Optional[UUID]): The new agent, or ``None`` to detach.

        Returns:
            AttachmentDAO: The stored attachment.
        """
        attachment: AttachmentDAO = AttachmentDAO(
            channel_id=self._channel_id,
            participant_id=participant_id,
            agent_id=agent_id,
            updated_at=utc_now(),
        )
        self._attachments[participant_id] = attachment
        self._write()
        return attachment

    def _load(self) -> dict[UUID, AttachmentDAO]:
        """Read the attachment file, setting a corrupt one aside.

        Returns:
            dict[UUID, AttachmentDAO]: Attachments keyed by participant id.
        """
        try:
            raw: str = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            stored: _AttachmentFileDAO = _AttachmentFileDAO.model_validate_json(raw)
        except ValidationError:
            self._set_corrupt_file_aside()
            return {}
        return {
            attachment.participant_id: attachment
            for attachment in stored.attachments
            if attachment.channel_id == self._channel_id
        }

    def _set_corrupt_file_aside(self) -> None:
        """Rename an unreadable attachment file so the next write starts clean."""
        stamp: str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        aside: Path = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
        os.replace(src=self._path, dst=aside)
        log_warning(msg=f"channel attachments file was unreadable; moved to {aside.name}")

    def _write(self) -> None:
        """Atomically replace the attachment file with mode 0600 (temp file + rename)."""
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        document: _AttachmentFileDAO = _AttachmentFileDAO(
            channel_id=self._channel_id,
            attachments=list(self._attachments.values()),
        )
        temporary: Path = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        descriptor: int = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(document.model_dump_json(indent=2))
        os.replace(src=temporary, dst=self._path)
