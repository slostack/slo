"""SQLite repository for the channel queue (108.1).

One ``sqlite3`` connection per process, used through a single worker thread
(``asyncio.to_thread`` with a ``threading.Lock``) so blocking database work
never touches the UI loop. PRAGMAs: ``journal_mode=WAL``,
``synchronous=NORMAL``, ``foreign_keys=ON``, ``busy_timeout=5000``.

Index allocation uses ``BEGIN IMMEDIATE`` so concurrent writers across
processes serialize the ``MAX+1`` computation and the UNIQUE constraint on
``(agent_session_id, message_index)`` stays gapless.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar
from uuid import UUID

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO, utc_now
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.channels.schema import migrate

__all__ = ["ChannelRepository"]

_T = TypeVar("_T")

_BUSY_TIMEOUT_MS: int = 5000
_RETENTION_DAYS: int = 30


class ChannelRepository:
    """Owns the process-local connection to the shared channels database."""

    def __init__(self, *, db_path: Path) -> None:
        """Prepare (not open) a repository bound to one database file.

        Args:
            db_path (Path): Path of the SQLite database file. Its parent is
                created mode 0700 and the file mode 0600 on open.
        """
        self._db_path: Path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock: threading.Lock = threading.Lock()
        self._worker: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="channel-repository",
        )

    @property
    def db_path(self) -> Path:
        """Return the database file path (composition seam for adapters).

        Returns:
            Path: The path this repository was constructed with.
        """
        return self._db_path

    async def open(self) -> None:
        """Create the directory/file, open the connection, migrate, prune.

        Creates the parent directory (0700) and database file (0600) when
        missing, applies schema migrations, then deletes accepted or
        cancelled rows older than the retention window. Re-opening after
        ``close`` recreates the worker thread.
        """
        if self._connection is not None:
            return
        self._worker = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="channel-repository",
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path=self._db_path.parent, mode=0o700)
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        await loop.run_in_executor(self._worker, self._open_sync)
        await self._prune()

    async def close(self) -> None:
        """Close the connection; further calls re-open lazily.

        Idempotent: closing an already-closed repository is a no-op.
        """
        if self._connection is None:
            return

        def _close(connection: sqlite3.Connection) -> None:
            connection.close()

        await self._run(_close)
        self._connection = None
        self._worker.shutdown(wait=True)

    async def table_names(self) -> set[str]:
        """Return the names of user tables in the database (test support).

        Returns:
            set[str]: Table names from ``sqlite_master``.
        """

        def _query(connection: sqlite3.Connection) -> set[str]:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {str(row[0]) for row in rows}

        return await self._run(_query)

    async def user_version(self) -> int:
        """Return ``PRAGMA user_version`` (test support).

        Returns:
            int: The current schema version stamp.
        """

        def _query(connection: sqlite3.Connection) -> int:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

        return await self._run(_query)

    async def journal_mode(self) -> str:
        """Return the active journal mode (test support).

        Returns:
            str: Journal mode reported by SQLite, e.g. ``wal``.
        """

        def _query(connection: sqlite3.Connection) -> str:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])

        return await self._run(_query)

    async def upsert_channel(self, *, channel: ChannelDAO) -> ChannelDAO:
        """Insert or refresh one channel row.

        Args:
            channel (ChannelDAO): Channel to persist; ``last_seen_at`` is updated.

        Returns:
            ChannelDAO: The stored channel.
        """

        def _write(connection: sqlite3.Connection) -> ChannelDAO:
            connection.execute(
                """
                INSERT INTO channels(id, kind, name, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    name = excluded.name,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    str(channel.id),
                    channel.kind,
                    channel.name,
                    _stamp(channel.created_at),
                    _stamp(channel.last_seen_at),
                ),
            )
            connection.commit()
            return channel

        return await self._run(_write)

    async def upsert_participant(self, *, participant: ParticipantDAO) -> ParticipantDAO:
        """Insert or refresh one participant row.

        Args:
            participant (ParticipantDAO): Participant to persist;
                ``last_seen_at`` is updated.

        Returns:
            ParticipantDAO: The stored participant.
        """

        def _write(connection: sqlite3.Connection) -> ParticipantDAO:
            connection.execute(
                """
                INSERT INTO participants(
                    id, kind, name, channel_id, external_ref, status, last_seen_at, created_at,
                    durable_inbox
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    name = excluded.name,
                    channel_id = excluded.channel_id,
                    external_ref = excluded.external_ref,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    durable_inbox = excluded.durable_inbox
                """,
                (
                    str(participant.id),
                    participant.kind,
                    participant.name,
                    str(participant.channel_id) if participant.channel_id is not None else None,
                    participant.external_ref,
                    participant.status,
                    _stamp(participant.last_seen_at),
                    _stamp(participant.created_at),
                    1 if participant.durable_inbox else 0,
                ),
            )
            connection.commit()
            return participant

        return await self._run(_write)

    async def get_participant(self, *, participant_id: UUID) -> Optional[ParticipantDAO]:
        """Return one participant by id.

        Args:
            participant_id (UUID): Id to look up.

        Returns:
            Optional[ParticipantDAO]: The stored row, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ParticipantDAO]:
            row = connection.execute(
                """
                SELECT id, kind, name, channel_id, external_ref, status, last_seen_at, created_at, durable_inbox
                FROM participants WHERE id = ?
                """,
                (str(participant_id),),
            ).fetchone()
            return _participant_from_row(row=row) if row is not None else None

        return await self._run(_query)

    async def participant_by_external_ref(
        self, *, channel_id: UUID, external_ref: str
    ) -> Optional[ParticipantDAO]:
        """Return the participant occupying a channel's external-ref slot.

        Args:
            channel_id (UUID): Channel to search.
            external_ref (str): Platform-side identity slot.

        Returns:
            Optional[ParticipantDAO]: The occupant, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ParticipantDAO]:
            row = connection.execute(
                """
                SELECT id, kind, name, channel_id, external_ref, status, last_seen_at, created_at, durable_inbox
                FROM participants WHERE channel_id = ? AND external_ref = ?
                """,
                (str(channel_id), external_ref),
            ).fetchone()
            return _participant_from_row(row=row) if row is not None else None

        return await self._run(_query)

    async def set_participant_status(self, *, participant_id: UUID, status: str) -> None:
        """Set a participant's ``status`` column.

        Args:
            participant_id (UUID): Participant to update.
            status (str): New status, ``open`` or ``closed``.
        """

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE participants SET status = ? WHERE id = ?",
                (status, str(participant_id)),
            )
            connection.commit()

        await self._run(_write)

    async def heartbeat(self, *, participant_id: UUID) -> None:
        """Refresh a participant's ``last_seen_at`` (poller heartbeat).

        Args:
            participant_id (UUID): Participant to stamp.
        """

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE participants SET last_seen_at = ? WHERE id = ?",
                (_stamp(utc_now()), str(participant_id)),
            )
            connection.commit()

        await self._run(_write)

    async def insert_message(self, *, new: NewMessageDAO) -> ChannelMessageDAO:
        """Insert one message row with the next gapless index.

        Runs inside ``BEGIN IMMEDIATE`` so concurrent writers serialize. A
        second insert with an existing id returns the already-stored row
        (idempotent retry). ``agent_session_id`` is the receiving agent when
        there is one, otherwise the sending agent (overview §2.4). The index
        is ``MAX+1`` for the conversation.

        Args:
            new (NewMessageDAO): Sender-supplied message data.

        Returns:
            ChannelMessageDAO: The stored row.

        Raises:
            UnknownParticipantError: The recipient (or sender) is unknown.
            RecipientClosedError: The recipient is a closed agent without a
                durable inbox (a finished workflow or child). A closed
                interactive session keeps its durable inbox (108.3 §6).
        """

        def _write(connection: sqlite3.Connection) -> ChannelMessageDAO:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT 1 FROM messages WHERE id = ?", (str(new.id),)
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    return self._get_sync(connection=connection, message_id=new.id)  # type: ignore[return-value]
                sender = self._get_participant_sync(connection=connection, participant_id=new.sender_id)
                if sender is None:
                    raise UnknownParticipantError(participant_id=new.sender_id)
                recipient = self._get_participant_sync(connection=connection, participant_id=new.recipient_id)
                if recipient is None:
                    raise UnknownParticipantError(participant_id=new.recipient_id)
                if recipient.kind == "agent" and recipient.status == "closed" and not recipient.durable_inbox:
                    raise RecipientClosedError(participant_id=new.recipient_id)
                agent_session_id: UUID = (
                    recipient.id
                    if recipient.kind == "agent"
                    else sender.id if sender.kind == "agent" else recipient.id
                )
                next_index: int = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(message_index), 0) + 1 FROM messages WHERE agent_session_id = ?",
                        (str(agent_session_id),),
                    ).fetchone()[0]
                )
                now: datetime = utc_now()
                # Coalesce (108.3 §4): a newer pending row with the same
                # recipient, sender and key cancels the older pending one as
                # ``superseded`` inside this same transaction, so a burst of
                # fleet notices leaves only the newest pending row.
                if new.coalesce_key is not None:
                    connection.execute(
                        """
                        UPDATE messages
                        SET cancelled_at = ?, cancel_reason = 'superseded'
                        WHERE recipient_id = ? AND sender_id = ? AND coalesce_key = ?
                          AND accepted_at IS NULL AND cancelled_at IS NULL
                        """,
                        (
                            _stamp(now),
                            str(recipient.id),
                            str(sender.id),
                            new.coalesce_key,
                        ),
                    )
                stored: ChannelMessageDAO = ChannelMessageDAO(
                    id=new.id,
                    agent_session_id=agent_session_id,
                    sender_id=sender.id,
                    sender_name=sender.name,
                    recipient_id=recipient.id,
                    recipient_name=recipient.name,
                    sent_at=new.sent_at,
                    accepted_at=None,
                    message_contents=new.message_contents,
                    created_at=now,
                    message_index=next_index,
                    forced_at=now if new.force else None,
                    message_type=new.message_type,
                    in_reply_to_id=new.in_reply_to_id,
                    channel_id=new.channel_id,
                    cancelled_at=None,
                    cancel_reason=None,
                    coalesce_key=new.coalesce_key,
                )
                connection.execute(
                    """
                    INSERT INTO messages(
                        id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                        sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                        message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                        coalesce_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(stored.id),
                        str(stored.agent_session_id),
                        str(stored.sender_id),
                        stored.sender_name,
                        str(stored.recipient_id),
                        stored.recipient_name,
                        _stamp(stored.sent_at),
                        None,
                        stored.message_contents,
                        _stamp(stored.created_at),
                        stored.message_index,
                        _stamp(stored.forced_at) if stored.forced_at is not None else None,
                        stored.message_type,
                        str(stored.in_reply_to_id) if stored.in_reply_to_id is not None else None,
                        str(stored.channel_id) if stored.channel_id is not None else None,
                        None,
                        None,
                        stored.coalesce_key,
                    ),
                )
                connection.commit()
                return stored
            except BaseException:
                connection.rollback()
                raise

        return await self._run(_write)

    async def pending_inbound(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Return unaccepted, uncancelled rows for one recipient (108.2 §4 ordering).

        Forced rows come first, then normal rows; each class stays FIFO by
        ``message_index`` (``ORDER BY (forced_at IS NULL), message_index``).

        Args:
            recipient_id (UUID): Participant whose inbox to read.

        Returns:
            list[ChannelMessageDAO]: Pending rows, forced first.
        """

        def _query(connection: sqlite3.Connection) -> list[ChannelMessageDAO]:
            rows = connection.execute(
                """
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE recipient_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                ORDER BY (forced_at IS NULL) ASC, message_index ASC
                """,
                (str(recipient_id),),
            ).fetchall()
            return [_message_from_row(row=row) for row in rows]

        return await self._run(_query)

    async def pending_outbound(self, *, recipient_ids: list[UUID]) -> list[ChannelMessageDAO]:
        """Return unaccepted, uncancelled rows addressed to any of the recipients.

        Args:
            recipient_ids (list[UUID]): Recipients (channel users) to check.

        Returns:
            list[ChannelMessageDAO]: Pending outbound rows in ``message_index`` order.
        """
        if not recipient_ids:
            return []

        def _query(connection: sqlite3.Connection) -> list[ChannelMessageDAO]:
            placeholders: str = ", ".join("?" for _ in recipient_ids)
            rows = connection.execute(
                f"""
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE recipient_id IN ({placeholders})
                  AND accepted_at IS NULL AND cancelled_at IS NULL
                ORDER BY agent_session_id ASC, message_index ASC
                """,
                tuple(str(recipient_id) for recipient_id in recipient_ids),
            ).fetchall()
            return [_message_from_row(row=row) for row in rows]

        return await self._run(_query)

    async def accept(self, *, message_id: UUID) -> bool:
        """Stamp ``accepted_at`` exactly once.

        Args:
            message_id (UUID): Message to accept.

        Returns:
            bool: ``True`` when this call performed the acceptance;
                ``False`` when the row was already accepted or cancelled, or
                does not exist.
        """

        def _write(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                """
                UPDATE messages SET accepted_at = ?
                WHERE id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), str(message_id)),
            )
            connection.commit()
            return cursor.rowcount == 1

        return await self._run(_write)

    async def cancel(self, *, message_id: UUID, reason: str) -> bool:
        """Cancel a row that has not been accepted yet.

        Args:
            message_id (UUID): Message to cancel.
            reason (str): Why it was cancelled, e.g. ``operator``,
                ``recipient_closed``, ``superseded``, ``start_failed``.

        Returns:
            bool: ``True`` when this call cancelled the row; ``False`` when
                it was already accepted or cancelled, or does not exist.
        """

        def _write(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                """
                UPDATE messages SET cancelled_at = ?, cancel_reason = ?
                WHERE id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), reason, str(message_id)),
            )
            connection.commit()
            return cursor.rowcount == 1

        return await self._run(_write)

    async def force(self, *, message_id: UUID) -> bool:
        """Stamp ``forced_at`` on a pending row (108.2).

        Only rows that are still pending and not already forced change; a
        second call on the same forced row is a no-op success so retries and
        repeated ``/queue force`` never fail.

        Args:
            message_id (UUID): Message to force.

        Returns:
            bool: ``True`` when the row is (or already was) forced and still
                pending; ``False`` when it was accepted, cancelled, or does
                not exist.
        """

        def _write(connection: sqlite3.Connection) -> bool:
            row = connection.execute(
                "SELECT accepted_at, cancelled_at, forced_at FROM messages WHERE id = ?",
                (str(message_id),),
            ).fetchone()
            if row is None or row[0] is not None or row[1] is not None:
                return False
            if row[2] is None:
                connection.execute(
                    "UPDATE messages SET forced_at = ? WHERE id = ?",
                    (_stamp(utc_now()), str(message_id)),
                )
                connection.commit()
            return True

        return await self._run(_write)

    async def get(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return one message row by id.

        Args:
            message_id (UUID): Message to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored row, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ChannelMessageDAO]:
            return self._get_sync(connection=connection, message_id=message_id)

        return await self._run(_query)

    async def conversation(
        self,
        *,
        agent_session_id: UUID,
        after_index: int = 0,
        limit: int = 200,
    ) -> list[ChannelMessageDAO]:
        """Return one conversation's rows after an index, in order.

        Args:
            agent_session_id (UUID): Conversation to read.
            after_index (int): Only rows with ``message_index`` greater than this.
            limit (int): Maximum rows to return.

        Returns:
            list[ChannelMessageDAO]: Rows in ``message_index`` order.
        """

        def _query(connection: sqlite3.Connection) -> list[ChannelMessageDAO]:
            rows = connection.execute(
                """
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE agent_session_id = ? AND message_index > ?
                ORDER BY message_index ASC
                LIMIT ?
                """,
                (str(agent_session_id), after_index, limit),
            ).fetchall()
            return [_message_from_row(row=row) for row in rows]

        return await self._run(_query)

    async def close_agent_atomic(self, *, participant_id: UUID, reason: str) -> int:
        """Close one agent participant and cancel its pending inbound rows atomically.

        Both writes happen in one ``BEGIN IMMEDIATE`` transaction (108.3 §2):
        the participant flips to ``closed`` and every unaccepted, uncancelled
        inbound row gains ``cancel_reason`` in the same commit, so a send
        racing the close either inserts against the open participant or hits
        the closed one — never lands after the listener stopped.

        A participant with a durable inbox (an interactive session, 108.3 §6)
        cancels only rows its users sent; rows from other agents and systems
        stay pending for the session's next opening.

        Args:
            participant_id (UUID): Agent participant to close.
            reason (str): Cancellation reason for pending rows, e.g.
                ``recipient_closed`` or ``session_closed``.

        Returns:
            int: Number of pending inbound rows cancelled.
        """

        def _write(connection: sqlite3.Connection) -> int:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE participants SET status = 'closed' WHERE id = ?",
                    (str(participant_id),),
                )
                cursor = connection.execute(
                    """
                    UPDATE messages SET cancelled_at = ?, cancel_reason = ?
                    WHERE recipient_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                      AND (
                        (SELECT durable_inbox FROM participants WHERE id = ?) = 0
                        OR sender_id IN (SELECT id FROM participants WHERE kind = 'user')
                      )
                    """,
                    (_stamp(utc_now()), reason, str(participant_id), str(participant_id)),
                )
                cancelled: int = int(cursor.rowcount)
                connection.commit()
                return cancelled
            except BaseException:
                connection.rollback()
                raise

        return await self._run(_write)

    async def count_participants(self) -> int:
        """Count stored participants.

        Returns:
            int: Number of participant rows.
        """

        def _query(connection: sqlite3.Connection) -> int:
            return int(connection.execute("SELECT COUNT(*) FROM participants").fetchone()[0])

        return await self._run(_query)

    async def column_names(self, *, table: str) -> list[tuple[str, str]]:
        """Return ``(name, declared_type)`` for one table's columns (test support).

        Args:
            table (str): Table to inspect.

        Returns:
            list[tuple[str, str]]: Column name and declared type pairs.
        """

        def _query(connection: sqlite3.Connection) -> list[tuple[str, str]]:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            return [(str(row[1]), str(row[2])) for row in rows]

        return await self._run(_query)

    async def index_names(self) -> set[str]:
        """Return the names of indexes in the database (test support).

        Returns:
            set[str]: Index names from ``sqlite_master``.
        """

        def _query(connection: sqlite3.Connection) -> set[str]:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            return {str(row[0]) for row in rows}

        return await self._run(_query)

    async def recent_sent_messages(
        self,
        *,
        sender_id: UUID,
        recipient_id: UUID,
        limit: int = 5,
    ) -> list[ChannelMessageDAO]:
        """Return the newest rows one participant sent to another, newest first.

        Used by the agent composer to list what the operator sent to one
        target agent (108.3 §4).

        Args:
            sender_id (UUID): The sending participant (the channel's user).
            recipient_id (UUID): The target agent participant.
            limit (int): Maximum rows to return. Defaults to 5.

        Returns:
            list[ChannelMessageDAO]: Rows newest first.
        """

        def _query(connection: sqlite3.Connection) -> list[ChannelMessageDAO]:
            rows = connection.execute(
                """
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE sender_id = ? AND recipient_id = ?
                ORDER BY message_index DESC
                LIMIT ?
                """,
                (str(sender_id), str(recipient_id), limit),
            ).fetchall()
            return [_message_from_row(row=row) for row in rows]

        return await self._run(_query)

    async def recent_notes_to(self, *, recipient_id: UUID, limit: int = 5) -> list[ChannelMessageDAO]:
        """Return the newest ``note`` rows addressed to one participant, newest first.

        The workflow modal shows these for the agent it views (108.4 C3), for
        example a child's question to its parent, whether or not the parent
        has taken them into its context yet.

        Args:
            recipient_id (UUID): The viewed agent participant.
            limit (int): Maximum rows to return. Defaults to 5.

        Returns:
            list[ChannelMessageDAO]: Note rows newest first, cancelled ones excluded.
        """

        def _query(connection: sqlite3.Connection) -> list[ChannelMessageDAO]:
            rows = connection.execute(
                """
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE recipient_id = ? AND message_type = 'note' AND cancelled_at IS NULL
                ORDER BY message_index DESC
                LIMIT ?
                """,
                (str(recipient_id), limit),
            ).fetchall()
            return [_message_from_row(row=row) for row in rows]

        return await self._run(_query)

    async def reply_for(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return the accepted reply row answering one message, or ``None``.

        Args:
            message_id (UUID): The message the reply must answer.

        Returns:
            Optional[ChannelMessageDAO]: The reply row, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ChannelMessageDAO]:
            row = connection.execute(
                """
                SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                       sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                       message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                       coalesce_key
                FROM messages
                WHERE in_reply_to_id = ? AND message_type = 'reply'
                ORDER BY message_index ASC
                LIMIT 1
                """,
                (str(message_id),),
            ).fetchone()
            return _message_from_row(row=row) if row is not None else None

        return await self._run(_query)

    async def cancel_pending_inbound(self, *, recipient_id: UUID, reason: str) -> int:
        """Cancel every unaccepted, uncancelled inbound row for a recipient.

        Used by ``close_agent`` so closing a session never strands pending rows.

        Args:
            recipient_id (UUID): Agent whose pending inbound rows are cancelled.
            reason (str): Cancellation reason, e.g. ``session_closed``.

        Returns:
            int: Number of rows cancelled.
        """

        def _write(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE messages SET cancelled_at = ?, cancel_reason = ?
                WHERE recipient_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), reason, str(recipient_id)),
            )
            connection.commit()
            return int(cursor.rowcount)

        return await self._run(_write)

    # ---- internal ---------------------------------------------------------

    async def _prune(self) -> None:
        """Delete accepted or cancelled rows older than the retention window."""

        def _write(connection: sqlite3.Connection) -> None:
            from datetime import timedelta

            cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
            connection.execute(
                """
                DELETE FROM messages
                WHERE (accepted_at IS NOT NULL OR cancelled_at IS NOT NULL)
                  AND created_at < ?
                """,
                (_stamp(cutoff),),
            )
            connection.commit()

        await self._run(_write)

    def _open_sync(self) -> None:
        """Open and configure the connection on the worker thread."""
        self._db_path.touch(mode=0o600, exist_ok=True)
        os.chmod(path=self._db_path, mode=0o600)
        opened: sqlite3.Connection = sqlite3.connect(
            database=str(self._db_path),
            timeout=_BUSY_TIMEOUT_MS / 1000.0,
            isolation_level=None,
        )
        opened.execute("PRAGMA journal_mode=WAL")
        opened.execute("PRAGMA synchronous=NORMAL")
        opened.execute("PRAGMA foreign_keys=ON")
        opened.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        migrate(connection=opened)
        self._connection = opened

    def _get_sync(self, *, connection: sqlite3.Connection, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Read one message row on the worker thread (caller holds the lock).

        Args:
            connection (sqlite3.Connection): Open connection.
            message_id (UUID): Message to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored row, or ``None``.
        """
        row = connection.execute(
            """
            SELECT id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name,
                   sent_at, accepted_at, message_contents, created_at, message_index, forced_at,
                   message_type, in_reply_to_id, channel_id, cancelled_at, cancel_reason,
                   coalesce_key
            FROM messages WHERE id = ?
            """,
            (str(message_id),),
        ).fetchone()
        return _message_from_row(row=row) if row is not None else None

    def _get_participant_sync(
        self, *, connection: sqlite3.Connection, participant_id: UUID
    ) -> Optional[ParticipantDAO]:
        """Read one participant row on the worker thread (caller holds the lock).

        Args:
            connection (sqlite3.Connection): Open connection.
            participant_id (UUID): Participant to look up.

        Returns:
            Optional[ParticipantDAO]: The stored row, or ``None``.
        """
        row = connection.execute(
            """
            SELECT id, kind, name, channel_id, external_ref, status, last_seen_at, created_at, durable_inbox
            FROM participants WHERE id = ?
            """,
            (str(participant_id),),
        ).fetchone()
        return _participant_from_row(row=row) if row is not None else None

    async def _run(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        """Run one blocking database operation on the worker thread.

        Serializes access through a ``threading.Lock`` so the single
        connection is never used concurrently.

        Args:
            operation (callable[[sqlite3.Connection], _T]): Work to run with
                the open connection.

        Returns:
            _T: The operation's result.

        Raises:
            RuntimeError: The repository is not open.
        """

        def _locked() -> _T:
            with self._lock:
                if self._connection is None:
                    raise RuntimeError("ChannelRepository is not open.")
                return operation(self._connection)

        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, _locked)


def _stamp(value: datetime) -> str:
    """Format a UTC timestamp for storage.

    Args:
        value (datetime): Timestamp to format.

    Returns:
        str: ISO-8601 text in UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    """Parse a stored ISO-8601 timestamp back to UTC.

    Args:
        value (str): Stored timestamp text.

    Returns:
        datetime: Timezone-aware UTC datetime.
    """
    parsed: datetime = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _participant_from_row(*, row: tuple) -> ParticipantDAO:
    """Build a participant DAO from a raw row tuple.

    Args:
        row (tuple): Row in the SELECT order used by this module.

    Returns:
        ParticipantDAO: The typed row.
    """
    return ParticipantDAO(
        id=UUID(row[0]),
        kind=row[1],
        name=row[2],
        channel_id=UUID(row[3]) if row[3] is not None else None,
        external_ref=row[4],
        status=row[5],
        last_seen_at=_parse(row[6]),
        created_at=_parse(row[7]),
        durable_inbox=bool(row[8]),
    )


def _message_from_row(*, row: tuple) -> ChannelMessageDAO:
    """Build a message DAO from a raw row tuple.

    Args:
        row (tuple): Row in the SELECT order used by this module.

    Returns:
        ChannelMessageDAO: The typed row.
    """
    return ChannelMessageDAO(
        id=UUID(row[0]),
        agent_session_id=UUID(row[1]),
        sender_id=UUID(row[2]),
        sender_name=row[3],
        recipient_id=UUID(row[4]),
        recipient_name=row[5],
        sent_at=_parse(row[6]),
        accepted_at=_parse(row[7]) if row[7] is not None else None,
        message_contents=row[8],
        created_at=_parse(row[9]),
        message_index=int(row[10]),
        forced_at=_parse(row[11]) if row[11] is not None else None,
        message_type=row[12],
        in_reply_to_id=UUID(row[13]) if row[13] is not None else None,
        channel_id=UUID(row[14]) if row[14] is not None else None,
        cancelled_at=_parse(row[15]) if row[15] is not None else None,
        cancel_reason=row[16],
        coalesce_key=row[17],
    )
