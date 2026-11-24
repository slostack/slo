"""SQLite repository for the channel queue (108.1).

One ``sqlite3`` connection per process, used through one lazy dedicated
``ThreadPoolExecutor`` worker. Blocking database work stays off the event loop;
a connection lock serializes connection use and a lifecycle lock orders open,
close and operation admission. PRAGMAs: ``journal_mode=WAL``,
``synchronous=NORMAL``, ``foreign_keys=ON``, ``busy_timeout=5000``.

Index allocation uses ``BEGIN IMMEDIATE`` so concurrent writers across
processes serialize the ``MAX+1`` computation and the UNIQUE constraint on
``(agent_session_id, message_index)`` stays gapless. Cancelling a submitted
operation does not stop its SQLite work; writes may still commit. Close drains
admitted work and cancellation is re-raised only after owned resources retire.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sqlite3
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Callable, Optional, TypeVar
from uuid import UUID, uuid4

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO, utc_now
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.channels.schema import migrate

__all__ = ["ChannelRepository"]

_T = TypeVar("_T")

_BUSY_TIMEOUT_MS: int = 5000
_RETENTION_DAYS: int = 30
_PARTICIPANT_COLUMNS: str = (
    "id, kind, name, channel_id, external_ref, status, last_seen_at, created_at, durable_inbox"
)
_MESSAGE_COLUMNS: str = (
    "id, agent_session_id, sender_id, sender_name, recipient_id, recipient_name, sent_at, accepted_at, "
    "message_contents, created_at, message_index, forced_at, message_type, in_reply_to_id, channel_id, "
    "cancelled_at, cancel_reason, coalesce_key"
)
_VALID_TABLE_NAMES: frozenset[str] = frozenset({"channels", "participants", "messages"})


class _CorruptChannelDatabaseError(sqlite3.DatabaseError):
    """A completed SQLite integrity check found corruption in the queue file."""


def _is_sqlite_corruption(error: sqlite3.DatabaseError) -> bool:
    """Return whether SQLite identifies an error as database corruption."""
    if isinstance(error, _CorruptChannelDatabaseError):
        return True
    if error.sqlite_errorcode is None:
        return False
    return error.sqlite_errorcode & 0xFF in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}


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
        self._recovery_path: Optional[Path] = None
        self._lifecycle_lock: asyncio.Lock = asyncio.Lock()
        self._connection_lock: threading.Lock = threading.Lock()
        self._worker: Optional[ThreadPoolExecutor] = None

    @property
    def db_path(self) -> Path:
        """Return the database file path (composition seam for adapters).

        Returns:
            Path: The path this repository was constructed with.
        """
        return self._db_path

    @property
    def recovery_path(self) -> Optional[Path]:
        """Return the preserved corrupt database path from the last successful open.

        Returns:
            Optional[Path]: The recovery copy path, or ``None`` when opening did
                not recover a corrupt database.
        """
        return self._recovery_path

    async def open(self) -> None:
        """Create the directory/file, open the connection, migrate, prune.

        Creates the database parent directory with private permissions when
        needed and the database file (0600), applies schema migrations, then
        prunes expired settled rows without removing referenced messages. The
        parent directory's permissions are not changed if it already exists.
        The connection is published only after startup succeeds; cancellation
        joins and cleans up startup work before returning. Explicitly calling
        ``open`` after ``close`` creates a fresh worker.

        Raises:
            OSError: The database path or recovery lock is unsafe or unavailable.
            sqlite3.DatabaseError: SQLite cannot migrate or access the database.
            asyncio.CancelledError: Startup was cancelled; cleanup finishes first.
        """
        async with self._lifecycle_lock:
            if self._connection is not None:
                return
            self._recovery_path = None
            self._db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            worker: ThreadPoolExecutor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="channel-repository",
            )
            self._worker = worker
            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
            open_future: asyncio.Future[tuple[sqlite3.Connection, Optional[Path]]] = loop.run_in_executor(
                worker, self._open_sync
            )
            opened_connection: Optional[sqlite3.Connection] = None
            recovery_path: Optional[Path] = None
            try:
                opened_connection, recovery_path = await asyncio.shield(open_future)
                self._connection = opened_connection
                self._recovery_path = recovery_path
            except BaseException:
                self._connection = None
                await self._cleanup_open_attempt(
                    open_future=open_future,
                    opened_connection=opened_connection,
                    loop=loop,
                    worker=worker,
                )
                raise

    async def close(self) -> None:
        """Close the connection and worker after previously admitted operations finish.

        Calls admitted before close on the single worker finish first. Calls
        waiting on the lifecycle lock run after close and receive ``RuntimeError``
        until explicitly reopened. Cancellation is re-raised only after the
        connection is detached and its worker has shut down; concurrent ``open``
        waits until retirement completes.

        Raises:
            asyncio.CancelledError: The caller was cancelled; cleanup finishes first.
        """
        async with self._lifecycle_lock:
            connection: Optional[sqlite3.Connection] = self._connection
            worker: Optional[ThreadPoolExecutor] = self._worker
            if connection is None or worker is None:
                return

            loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
            close_future: asyncio.Future[None] = loop.run_in_executor(
                worker, partial(self._close_connection_sync, connection=connection)
            )
            cleanup_task: asyncio.Task[None] = asyncio.create_task(
                self._finish_close(close_future=close_future, worker=worker)
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                while not cleanup_task.done():
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        continue
                cleanup_task.result()
                raise

    async def table_names(self) -> set[str]:
        """Return the names of user tables in the database (test support).

        Returns:
            set[str]: Table names from ``sqlite_master``.
        """

        def _query(connection: sqlite3.Connection) -> set[str]:
            table_rows: list[sqlite3.Row] = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return {str(table_row["name"]) for table_row in table_rows}

        return await self._run(_query)

    async def user_version(self) -> int:
        """Return ``PRAGMA user_version`` (test support).

        Returns:
            int: The current schema version stamp.
        """

        def _query(connection: sqlite3.Connection) -> int:
            version_row: sqlite3.Row = connection.execute("PRAGMA user_version").fetchone()
            return int(version_row["user_version"])

        return await self._run(_query)

    async def journal_mode(self) -> str:
        """Return the active journal mode (test support).

        Returns:
            str: Journal mode reported by SQLite, e.g. ``wal``.
        """

        def _query(connection: sqlite3.Connection) -> str:
            journal_row: sqlite3.Row = connection.execute("PRAGMA journal_mode").fetchone()
            return str(journal_row["journal_mode"])

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
            participant_row: Optional[sqlite3.Row] = connection.execute(
                f"SELECT {_PARTICIPANT_COLUMNS} FROM participants WHERE id = ?",
                (str(participant_id),),
            ).fetchone()
            return _participant_from_row(row=participant_row) if participant_row is not None else None

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
            participant_row: Optional[sqlite3.Row] = connection.execute(
                f"""SELECT {_PARTICIPANT_COLUMNS}
                FROM participants WHERE channel_id = ? AND external_ref = ?""",
                (str(channel_id), external_ref),
            ).fetchone()
            return _participant_from_row(row=participant_row) if participant_row is not None else None

        return await self._run(_query)

    async def claim_system_slot(self, *, participant: ParticipantDAO) -> ParticipantDAO:
        """Store a system participant in its ``(channel_id, external_ref)`` slot, atomically.

        One ``INSERT … ON CONFLICT(channel_id, external_ref) DO UPDATE``
        statement, so concurrent processes racing on one empty slot agree on a
        single row. The slot's occupant keeps its id (rows it already sent
        keep their sender) and becomes an open ``system`` participant with the
        new name and heartbeat; a former ``user`` occupant converts in place.

        Args:
            participant (ParticipantDAO): System participant to store; its
                ``id`` is used only when the slot is empty.

        Returns:
            ParticipantDAO: The stored slot occupant.

        Raises:
            ValueError: ``channel_id`` or ``external_ref`` is missing; SQLite
                never treats a NULL slot as a conflict, so it would duplicate.
        """
        if participant.channel_id is None or participant.external_ref is None:
            raise ValueError("A system participant needs both channel_id and external_ref.")

        def _write(connection: sqlite3.Connection) -> ParticipantDAO:
            row = connection.execute(
                """
                INSERT INTO participants(
                    id, kind, name, channel_id, external_ref, status, last_seen_at, created_at,
                    durable_inbox
                )
                VALUES (?, 'system', ?, ?, ?, 'open', ?, ?, 0)
                ON CONFLICT(channel_id, external_ref) DO UPDATE SET
                    kind = 'system',
                    name = excluded.name,
                    status = 'open',
                    last_seen_at = excluded.last_seen_at,
                    durable_inbox = 0
                RETURNING id, kind, name, channel_id, external_ref, status, last_seen_at, created_at,
                          durable_inbox
                """,
                (
                    str(participant.id),
                    participant.name,
                    str(participant.channel_id),
                    participant.external_ref,
                    _stamp(participant.last_seen_at),
                    _stamp(participant.created_at),
                ),
            ).fetchone()
            connection.commit()
            return _participant_from_row(row=row)

        return await self._run(_write)

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
            RecipientClosedError: The recipient is a closed agent that does
                not admit this sender (``ParticipantDAO.admits_message_from``):
                a finished workflow or child refuses everyone; a closed
                interactive session refuses operators (users) and keeps its
                durable inbox for agents and systems (108.3 §6).
        """

        def _write(connection: sqlite3.Connection) -> ChannelMessageDAO:
            connection.execute("BEGIN IMMEDIATE")
            try:
                stored_message: Optional[ChannelMessageDAO] = self._get_sync(
                    connection=connection, message_id=new.id
                )
                if stored_message is not None:
                    connection.commit()
                    return stored_message

                sender: Optional[ParticipantDAO] = self._get_participant_sync(
                    connection=connection, participant_id=new.sender_id
                )
                if sender is None:
                    raise UnknownParticipantError(participant_id=new.sender_id)
                recipient: Optional[ParticipantDAO] = self._get_participant_sync(
                    connection=connection, participant_id=new.recipient_id
                )
                if recipient is None:
                    raise UnknownParticipantError(participant_id=new.recipient_id)
                if not recipient.admits_message_from(sender=sender):
                    raise RecipientClosedError(participant_id=new.recipient_id)

                agent_session_id: UUID = recipient.conversation_session_id(sender=sender)
                next_message_index: int = self._next_message_index(
                    connection=connection, agent_session_id=agent_session_id
                )
                created_at: datetime = utc_now()
                self._supersede_pending_message(
                    connection=connection,
                    new_message=new,
                    recipient=recipient,
                    sender=sender,
                    created_at=created_at,
                )
                channel_message: ChannelMessageDAO = ChannelMessageDAO(
                    id=new.id,
                    agent_session_id=agent_session_id,
                    sender_id=sender.id,
                    sender_name=sender.name,
                    recipient_id=recipient.id,
                    recipient_name=recipient.name,
                    sent_at=new.sent_at,
                    accepted_at=None,
                    message_contents=new.message_contents,
                    created_at=created_at,
                    message_index=next_message_index,
                    forced_at=created_at if new.force else None,
                    message_type=new.message_type,
                    in_reply_to_id=new.in_reply_to_id,
                    channel_id=new.channel_id,
                    cancelled_at=None,
                    cancel_reason=None,
                    coalesce_key=new.coalesce_key,
                )
                self._insert_message_row(connection=connection, channel_message=channel_message)
                connection.commit()
                return channel_message
            except BaseException:
                connection.rollback()
                raise

        return await self._run(_write)

    @staticmethod
    def _next_message_index(*, connection: sqlite3.Connection, agent_session_id: UUID) -> int:
        """Allocate the next conversation index while the caller holds BEGIN IMMEDIATE."""
        index_row: sqlite3.Row = connection.execute(
            "SELECT COALESCE(MAX(message_index), 0) + 1 AS next_index "
            "FROM messages WHERE agent_session_id = ?",
            (str(agent_session_id),),
        ).fetchone()
        return int(index_row["next_index"])

    @staticmethod
    def _supersede_pending_message(
        *,
        connection: sqlite3.Connection,
        new_message: NewMessageDAO,
        recipient: ParticipantDAO,
        sender: ParticipantDAO,
        created_at: datetime,
    ) -> None:
        """Cancel the matching pending row before inserting its coalesced replacement."""
        if new_message.coalesce_key is None:
            return
        connection.execute(
            """
            UPDATE messages
            SET cancelled_at = ?, cancel_reason = 'superseded'
            WHERE recipient_id = ? AND sender_id = ? AND coalesce_key = ?
              AND accepted_at IS NULL AND cancelled_at IS NULL
            """,
            (
                _stamp(created_at),
                str(recipient.id),
                str(sender.id),
                new_message.coalesce_key,
            ),
        )

    @staticmethod
    def _insert_message_row(
        *, connection: sqlite3.Connection, channel_message: ChannelMessageDAO
    ) -> None:
        """Insert one fully resolved channel message into SQLite."""
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
                str(channel_message.id),
                str(channel_message.agent_session_id),
                str(channel_message.sender_id),
                channel_message.sender_name,
                str(channel_message.recipient_id),
                channel_message.recipient_name,
                _stamp(channel_message.sent_at),
                None,
                channel_message.message_contents,
                _stamp(channel_message.created_at),
                channel_message.message_index,
                _stamp(channel_message.forced_at) if channel_message.forced_at is not None else None,
                channel_message.message_type,
                str(channel_message.in_reply_to_id) if channel_message.in_reply_to_id is not None else None,
                str(channel_message.channel_id) if channel_message.channel_id is not None else None,
                None,
                None,
                channel_message.coalesce_key,
            ),
        )

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
            message_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE recipient_id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                ORDER BY (forced_at IS NULL) ASC, message_index ASC""",
                (str(recipient_id),),
            ).fetchall()
            return [_message_from_row(row=message_row) for message_row in message_rows]

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
            message_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE recipient_id IN ({placeholders})
                  AND accepted_at IS NULL AND cancelled_at IS NULL
                ORDER BY agent_session_id ASC, message_index ASC""",
                tuple(str(recipient_id) for recipient_id in recipient_ids),
            ).fetchall()
            return [_message_from_row(row=message_row) for message_row in message_rows]

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
            update_cursor: sqlite3.Cursor = connection.execute(
                """
                UPDATE messages SET accepted_at = ?
                WHERE id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), str(message_id)),
            )
            connection.commit()
            return update_cursor.rowcount == 1

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
            update_cursor: sqlite3.Cursor = connection.execute(
                """
                UPDATE messages SET cancelled_at = ?, cancel_reason = ?
                WHERE id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), reason, str(message_id)),
            )
            connection.commit()
            return update_cursor.rowcount == 1

        return await self._run(_write)

    async def force(self, *, message_id: UUID) -> bool:
        """Stamp ``forced_at`` on a pending prompt row (108.2).

        One guarded ``UPDATE`` decides and writes atomically, so a row that
        another connection accepts or cancels concurrently is never forced.
        Only ``prompt`` rows are forceable (overview §3.2). Re-forcing a
        pending forced prompt is an idempotent success that keeps its first
        ``forced_at`` stamp.

        Args:
            message_id (UUID): Message to force.

        Returns:
            bool: ``True`` when the row is (or already was) a forced pending
                prompt; ``False`` when it was accepted, cancelled, is not a
                prompt, or does not exist.
        """

        def _write(connection: sqlite3.Connection) -> bool:
            update_cursor: sqlite3.Cursor = connection.execute(
                """
                UPDATE messages SET forced_at = COALESCE(forced_at, ?)
                WHERE id = ? AND message_type = 'prompt'
                  AND accepted_at IS NULL AND cancelled_at IS NULL
                """,
                (_stamp(utc_now()), str(message_id)),
            )
            connection.commit()
            return update_cursor.rowcount == 1

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
            message_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE agent_session_id = ? AND message_index > ?
                ORDER BY message_index ASC
                LIMIT ?""",
                (str(agent_session_id), after_index, limit),
            ).fetchall()
            return [_message_from_row(row=message_row) for message_row in message_rows]

        return await self._run(_query)

    async def close_agent_atomic(self, *, participant_id: UUID, reason: str) -> int:
        """Close one agent participant and cancel its pending inbound rows atomically.

        Both writes happen in one ``BEGIN IMMEDIATE`` transaction (108.3 §2):
        the participant flips to ``closed`` and every unaccepted, uncancelled
        inbound row gains ``cancel_reason`` in the same commit, so a send
        racing the close either inserts against the open participant or hits
        the closed one — never lands after the listener stopped.

        Survivors follow ``ParticipantDAO.admits_message_from`` for the now
        closed participant, the same rule admission applies: a durable inbox
        (an interactive session, 108.3 §6) cancels every operator (user) row
        and keeps rows from agents and systems for the session's next opening;
        any other agent cancels every pending row.

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
                closed_participant: Optional[ParticipantDAO] = self._get_participant_sync(
                    connection=connection, participant_id=participant_id
                )
                if closed_participant is None:
                    connection.commit()
                    return 0
                sender_rows: list[sqlite3.Row] = connection.execute(
                    """
                    SELECT m.id AS message_id, p.id, p.kind, p.name, p.channel_id, p.external_ref, p.status,
                           p.last_seen_at, p.created_at, p.durable_inbox
                    FROM messages AS m JOIN participants AS p ON p.id = m.sender_id
                    WHERE m.recipient_id = ? AND m.accepted_at IS NULL AND m.cancelled_at IS NULL
                    """,
                    (str(participant_id),),
                ).fetchall()
                cancellation_stamp: str = _stamp(utc_now())
                pending_cancellations: list[tuple[str, str, str]] = [
                    (cancellation_stamp, reason, str(sender_row["message_id"]))
                    for sender_row in sender_rows
                    if not closed_participant.admits_message_from(sender=_participant_from_row(row=sender_row))
                ]
                connection.executemany(
                    """
                    UPDATE messages SET cancelled_at = ?, cancel_reason = ?
                    WHERE id = ? AND accepted_at IS NULL AND cancelled_at IS NULL
                    """,
                    pending_cancellations,
                )
                connection.commit()
                return len(pending_cancellations)
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
            count_row: sqlite3.Row = connection.execute("SELECT COUNT(*) AS participant_count FROM participants").fetchone()
            return int(count_row["participant_count"])

        return await self._run(_query)

    async def list_agents(self, *, open_only: bool) -> list[ParticipantDAO]:
        """Return agent participants, most recently seen first (108.5 ``slo channel agents``).

        Args:
            open_only (bool): ``True`` keeps only agents whose status is ``open``.

        Returns:
            list[ParticipantDAO]: Agent participants ordered by ``last_seen_at``
                descending, then id for a stable order.
        """

        def _query(connection: sqlite3.Connection) -> list[ParticipantDAO]:
            participant_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_PARTICIPANT_COLUMNS}
                FROM participants
                WHERE kind = 'agent' AND (? = 0 OR status = 'open')
                ORDER BY last_seen_at DESC, created_at ASC, id ASC""",
                (1 if open_only else 0,),
            ).fetchall()
            return [_participant_from_row(row=participant_row) for participant_row in participant_rows]

        return await self._run(_query)

    async def agents_with_id_prefix(self, *, prefix: str) -> list[ParticipantDAO]:
        """Return every agent participant whose id text starts with ``prefix``.

        The caller validates ``prefix`` to lowercase hex digits and hyphens,
        so it never carries ``LIKE`` wildcards.

        Args:
            prefix (str): Lowercase id prefix, e.g. ``9b1e``.

        Returns:
            list[ParticipantDAO]: Matching agents, most recently seen first.
        """

        def _query(connection: sqlite3.Connection) -> list[ParticipantDAO]:
            participant_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_PARTICIPANT_COLUMNS}
                FROM participants
                WHERE kind = 'agent' AND substr(id, 1, ?) = ?
                ORDER BY last_seen_at DESC, id ASC""",
                (len(prefix), prefix),
            ).fetchall()
            return [_participant_from_row(row=participant_row) for participant_row in participant_rows]

        return await self._run(_query)

    async def channel_users(self, *, channel_id: UUID) -> list[ParticipantDAO]:
        """Return the user participants who talk through one channel.

        Args:
            channel_id (UUID): Channel whose users to list.

        Returns:
            list[ParticipantDAO]: User participants, oldest registration first.
        """

        def _query(connection: sqlite3.Connection) -> list[ParticipantDAO]:
            participant_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_PARTICIPANT_COLUMNS}
                FROM participants
                WHERE kind = 'user' AND channel_id = ?
                ORDER BY created_at ASC, id ASC""",
                (str(channel_id),),
            ).fetchall()
            return [_participant_from_row(row=participant_row) for participant_row in participant_rows]

        return await self._run(_query)

    async def get_channel(self, *, channel_id: UUID) -> Optional[ChannelDAO]:
        """Return one channel row by id.

        Args:
            channel_id (UUID): Channel to look up.

        Returns:
            Optional[ChannelDAO]: The stored channel, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ChannelDAO]:
            channel_row: Optional[sqlite3.Row] = connection.execute(
                "SELECT id, kind, name, created_at, last_seen_at FROM channels WHERE id = ?",
                (str(channel_id),),
            ).fetchone()
            if channel_row is None:
                return None
            return ChannelDAO(
                id=UUID(channel_row["id"]),
                kind=channel_row["kind"],
                name=channel_row["name"],
                created_at=_parse(channel_row["created_at"]),
                last_seen_at=_parse(channel_row["last_seen_at"]),
            )

        return await self._run(_query)

    async def last_message_index(self, *, agent_session_id: UUID) -> int:
        """Return the highest ``message_index`` of one conversation (0 when empty).

        Args:
            agent_session_id (UUID): Conversation to inspect.

        Returns:
            int: The newest index, or 0 for an empty conversation.
        """

        def _query(connection: sqlite3.Connection) -> int:
            message_index_row: sqlite3.Row = connection.execute(
                "SELECT COALESCE(MAX(message_index), 0) AS message_index "
                "FROM messages WHERE agent_session_id = ?",
                (str(agent_session_id),),
            ).fetchone()
            return int(message_index_row["message_index"])

        return await self._run(_query)

    async def heartbeat_channel(self, *, channel_id: UUID) -> None:
        """Refresh a channel's ``last_seen_at`` (adapter heartbeat, 108.5 host).

        Args:
            channel_id (UUID): Channel to stamp.
        """

        def _write(connection: sqlite3.Connection) -> None:
            connection.execute(
                "UPDATE channels SET last_seen_at = ? WHERE id = ?",
                (_stamp(utc_now()), str(channel_id)),
            )
            connection.commit()

        await self._run(_write)

    async def column_names(self, *, table: str) -> list[tuple[str, str]]:
        """Return ``(name, declared_type)`` for one table's columns (test support).

        Args:
            table (str): Table to inspect.

        Returns:
            list[tuple[str, str]]: Column name and declared type pairs.
        """

        if table not in _VALID_TABLE_NAMES:
            raise ValueError(f"Unsupported channel table: {table}")

        def _query(connection: sqlite3.Connection) -> list[tuple[str, str]]:
            column_rows: list[sqlite3.Row] = connection.execute(f"PRAGMA table_info({table})").fetchall()
            return [(str(column_row["name"]), str(column_row["type"])) for column_row in column_rows]

        return await self._run(_query)

    async def index_names(self) -> set[str]:
        """Return the names of indexes in the database (test support).

        Returns:
            set[str]: Index names from ``sqlite_master``.
        """

        def _query(connection: sqlite3.Connection) -> set[str]:
            index_rows: list[sqlite3.Row] = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            return {str(index_row["name"]) for index_row in index_rows}

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
            message_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE sender_id = ? AND recipient_id = ?
                ORDER BY message_index DESC
                LIMIT ?""",
                (str(sender_id), str(recipient_id), limit),
            ).fetchall()
            return [_message_from_row(row=message_row) for message_row in message_rows]

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
            message_rows: list[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE recipient_id = ? AND message_type = 'note' AND cancelled_at IS NULL
                ORDER BY message_index DESC
                LIMIT ?""",
                (str(recipient_id), limit),
            ).fetchall()
            return [_message_from_row(row=message_row) for message_row in message_rows]

        return await self._run(_query)

    async def reply_for(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Return the earliest reply row answering one message, regardless of delivery state.

        Pending replies are returned so ``wait_for_reply`` can deliver them;
        callers decide when a delivered reply is accepted.

        Args:
            message_id (UUID): The message the reply must answer.

        Returns:
            Optional[ChannelMessageDAO]: The reply row, or ``None``.
        """

        def _query(connection: sqlite3.Connection) -> Optional[ChannelMessageDAO]:
            reply_row: Optional[sqlite3.Row] = connection.execute(
                f"""SELECT {_MESSAGE_COLUMNS}
                FROM messages
                WHERE in_reply_to_id = ? AND message_type = 'reply'
                ORDER BY message_index ASC
                LIMIT 1""",
                (str(message_id),),
            ).fetchone()
            return _message_from_row(row=reply_row) if reply_row is not None else None

        return await self._run(_query)

    # ---- internal ---------------------------------------------------------

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        """Delete expired settled leaves while preserving references and pending rows.

        Repeating the leaf delete drains any acyclic or cyclic reply dependencies
        without assuming a maximum chain depth. A retained pending row is never
        removed, nor is any ancestor it still references.
        """
        cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        while True:
            delete_cursor: sqlite3.Cursor = connection.execute(
                """
                DELETE FROM messages
                WHERE (accepted_at IS NOT NULL OR cancelled_at IS NOT NULL)
                  AND created_at < ?
                  AND NOT EXISTS (
                      SELECT 1 FROM messages AS dependent
                      WHERE dependent.in_reply_to_id = messages.id
                  )
                """,
                (_stamp(cutoff),),
            )
            if delete_cursor.rowcount == 0:
                return

    def _open_sync(self) -> tuple[sqlite3.Connection, Optional[Path]]:
        """Open the database while serializing startup recovery across processes."""
        lock_path: Path = self._db_path.with_name(f"{self._db_path.name}.recovery.lock")
        lock_descriptor: int = os.open(
            path=str(lock_path),
            flags=os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            mode=0o600,
        )
        lock_acquired: bool = False
        try:
            if not stat.S_ISREG(os.fstat(lock_descriptor).st_mode):
                raise OSError(f"Channel recovery lock is not a regular file: {lock_path}")
            self._acquire_recovery_lock(lock_descriptor=lock_descriptor)
            lock_acquired = True
            return self._open_database_sync()
        finally:
            if lock_acquired:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

    def _acquire_recovery_lock(self, *, lock_descriptor: int) -> None:
        """Wait up to the SQLite busy timeout for exclusive recovery ownership."""
        deadline: float = time.monotonic() + (_BUSY_TIMEOUT_MS / 1000.0)
        while True:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise sqlite3.OperationalError("database is locked")
                time.sleep(0.01)

    def _open_database_sync(self) -> tuple[sqlite3.Connection, Optional[Path]]:
        """Open and validate a queue, preserving corrupt database files before replacement."""
        if not os.path.lexists(self._db_path):
            try:
                self._create_queue_file()
            except FileExistsError:
                pass
        self._ensure_regular_queue_file(path=self._db_path)
        original_database_mode: int = stat.S_IMODE(self._db_path.lstat().st_mode)
        recovery_path: Optional[Path] = None
        if not self._has_sqlite_database_header():
            recovery_path = self._set_corrupt_queue_files_aside()
            self._create_queue_file()
        for recovery_attempt in range(2):
            opened: sqlite3.Connection = sqlite3.connect(
                database=str(self._db_path),
                timeout=_BUSY_TIMEOUT_MS / 1000.0,
                isolation_level=None,
            )
            opened.row_factory = sqlite3.Row
            try:
                self._check_database_integrity(connection=opened)
                os.chmod(path=self._db_path, mode=0o600, follow_symlinks=False)
                self._configure_connection(connection=opened)
                migrate(connection=opened)
                self._prune(connection=opened)
            except sqlite3.DatabaseError as error:
                opened.close()
                if not _is_sqlite_corruption(error) or recovery_attempt > 0:
                    if recovery_path is None:
                        os.chmod(path=self._db_path, mode=original_database_mode, follow_symlinks=False)
                    raise
                os.chmod(path=self._db_path, mode=original_database_mode, follow_symlinks=False)
                recovery_path = self._set_corrupt_queue_files_aside()
                self._create_queue_file()
                continue
            except BaseException:
                opened.close()
                if recovery_path is None:
                    os.chmod(path=self._db_path, mode=original_database_mode, follow_symlinks=False)
                raise
            return opened, recovery_path
        raise RuntimeError("Channel database recovery did not produce an open database.")

    @staticmethod
    def _check_database_integrity(*, connection: sqlite3.Connection) -> None:
        """Reject corrupt pages before changing permissions, journal mode or schema."""
        integrity_results: list[str] = [
            str(integrity_row[0]) for integrity_row in connection.execute("PRAGMA quick_check").fetchall()
        ]
        if integrity_results != ["ok"]:
            raise _CorruptChannelDatabaseError("SQLite quick_check found corrupt channel data.")

    @staticmethod
    def _configure_connection(*, connection: sqlite3.Connection) -> None:
        """Configure SQLite's journal, sync and transaction settings."""
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")

    def _create_queue_file(self) -> None:
        """Create a fresh database file with private permissions without following links."""
        database_descriptor: int = os.open(
            path=str(self._db_path),
            flags=os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            mode=0o600,
        )
        os.close(database_descriptor)

    @staticmethod
    def _ensure_regular_queue_file(*, path: Path) -> None:
        """Reject a queue path that could redirect SQLite or file operations."""
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError(f"Channel database path is not a regular file: {path}")

    def _has_sqlite_database_header(self) -> bool:
        """Return whether the queue is empty or carries SQLite's stable file signature."""
        with self._db_path.open("rb") as database_file:
            header: bytes = database_file.read(16)
        return header == b"" or header == b"SQLite format 3\x00"

    def _set_corrupt_queue_files_aside(self) -> Path:
        """Preserve the database and SQLite sidecars under one collision-safe backup stem."""
        queue_files: list[Path] = [
            self._db_path,
            self._db_path.with_name(f"{self._db_path.name}-wal"),
            self._db_path.with_name(f"{self._db_path.name}-shm"),
            self._db_path.with_name(f"{self._db_path.name}-journal"),
        ]
        existing_queue_files: list[Path] = [path for path in queue_files if os.path.lexists(path)]
        for queue_file in existing_queue_files:
            self._ensure_regular_queue_file(path=queue_file)

        timestamp: str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_stem: str = f"{self._db_path.name}.corrupt-{timestamp}-{uuid4().hex}"
        backup_paths: list[Path] = [
            self._db_path.with_name(f"{backup_stem}{queue_file.name[len(self._db_path.name):]}")
            for queue_file in existing_queue_files
        ]
        for queue_file, backup_path in zip(existing_queue_files, backup_paths):
            os.link(src=queue_file, dst=backup_path, follow_symlinks=False)
        for queue_file in (*existing_queue_files[1:], existing_queue_files[0]):
            queue_file.unlink()
        return backup_paths[existing_queue_files.index(self._db_path)]

    def _close_connection_sync(self, *, connection: sqlite3.Connection) -> None:
        """Detach and close the published connection on its dedicated worker."""
        with self._connection_lock:
            if self._connection is not connection:
                return
            self._connection = None
            connection.close()

    async def _finish_close(
        self,
        *,
        close_future: asyncio.Future[None],
        worker: ThreadPoolExecutor,
    ) -> None:
        """Join the connection close and shut down its worker without blocking the loop."""
        try:
            await asyncio.shield(close_future)
        finally:
            await asyncio.to_thread(worker.shutdown, wait=True)
            if self._worker is worker:
                self._worker = None

    async def _cleanup_open_attempt(
        self,
        *,
        open_future: asyncio.Future[tuple[sqlite3.Connection, Optional[Path]]],
        opened_connection: Optional[sqlite3.Connection],
        loop: asyncio.AbstractEventLoop,
        worker: ThreadPoolExecutor,
    ) -> None:
        """Join startup work, close an unclaimed connection and stop its worker off-loop."""
        cleanup_task: asyncio.Task[None] = asyncio.create_task(
            self._finish_open_cleanup(
                open_future=open_future,
                opened_connection=opened_connection,
                loop=loop,
                worker=worker,
            )
        )
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                continue
        cleanup_task.result()

    async def _finish_open_cleanup(
        self,
        *,
        open_future: asyncio.Future[tuple[sqlite3.Connection, Optional[Path]]],
        opened_connection: Optional[sqlite3.Connection],
        loop: asyncio.AbstractEventLoop,
        worker: ThreadPoolExecutor,
    ) -> None:
        """Close a completed startup connection on its owner thread and shut down off-loop."""
        try:
            if opened_connection is None:
                try:
                    opened_connection, _recovery_path = await asyncio.shield(open_future)
                except BaseException:
                    opened_connection = None
            if opened_connection is not None:
                await loop.run_in_executor(worker, opened_connection.close)
        finally:
            await asyncio.to_thread(worker.shutdown, wait=True)
            if self._worker is worker:
                self._worker = None

    def _get_sync(self, *, connection: sqlite3.Connection, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Read one message row on the worker thread (caller holds the lock).

        Args:
            connection (sqlite3.Connection): Open connection.
            message_id (UUID): Message to look up.

        Returns:
            Optional[ChannelMessageDAO]: The stored row, or ``None``.
        """
        message_row: Optional[sqlite3.Row] = connection.execute(
            f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE id = ?",
            (str(message_id),),
        ).fetchone()
        return _message_from_row(row=message_row) if message_row is not None else None

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
        participant_row: Optional[sqlite3.Row] = connection.execute(
            f"SELECT {_PARTICIPANT_COLUMNS} FROM participants WHERE id = ?",
            (str(participant_id),),
        ).fetchone()
        return _participant_from_row(row=participant_row) if participant_row is not None else None

    async def _run(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        """Run one SQLite operation admitted before any concurrent close.

        The lifecycle lock orders operation submission against close: operations
        submitted first finish before connection retirement, while later calls
        receive ``RuntimeError`` until explicit reopen. Cancelling this await
        does not cancel SQLite work already submitted; that operation may
        still commit before its worker finishes.

        Args:
            operation (Callable[[sqlite3.Connection], _T]): Work to run with
                the open connection.

        Returns:
            _T: The operation's result.

        Raises:
            RuntimeError: The repository is closed or closing.
            sqlite3.OperationalError: SQLite remains busy beyond its timeout.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        async with self._lifecycle_lock:
            worker: Optional[ThreadPoolExecutor] = self._worker
            if self._connection is None or worker is None:
                raise RuntimeError("ChannelRepository is not open.")
            operation_future: asyncio.Future[_T] = loop.run_in_executor(
                worker, self._run_locked, operation
            )
        return await operation_future

    def _run_locked(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        """Run one submitted operation while owning the connection lock."""
        with self._connection_lock:
            connection: Optional[sqlite3.Connection] = self._connection
            if connection is None:
                raise RuntimeError("ChannelRepository is not open.")
            return operation(connection)


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


def _participant_from_row(*, row: sqlite3.Row) -> ParticipantDAO:
    """Build a participant DAO from a named SQLite row.

    Args:
        row (sqlite3.Row): Participant columns selected by this module.

    Returns:
        ParticipantDAO: The typed row.
    """
    return ParticipantDAO(
        id=UUID(row["id"]),
        kind=row["kind"],
        name=row["name"],
        channel_id=UUID(row["channel_id"]) if row["channel_id"] is not None else None,
        external_ref=row["external_ref"],
        status=row["status"],
        last_seen_at=_parse(row["last_seen_at"]),
        created_at=_parse(row["created_at"]),
        durable_inbox=bool(row["durable_inbox"]),
    )


def _message_from_row(*, row: sqlite3.Row) -> ChannelMessageDAO:
    """Build a message DAO from a named SQLite row.

    Args:
        row (sqlite3.Row): Message columns selected by this module.

    Returns:
        ChannelMessageDAO: The typed row.
    """
    return ChannelMessageDAO(
        id=UUID(row["id"]),
        agent_session_id=UUID(row["agent_session_id"]),
        sender_id=UUID(row["sender_id"]),
        sender_name=row["sender_name"],
        recipient_id=UUID(row["recipient_id"]),
        recipient_name=row["recipient_name"],
        sent_at=_parse(row["sent_at"]),
        accepted_at=_parse(row["accepted_at"]) if row["accepted_at"] is not None else None,
        message_contents=row["message_contents"],
        created_at=_parse(row["created_at"]),
        message_index=int(row["message_index"]),
        forced_at=_parse(row["forced_at"]) if row["forced_at"] is not None else None,
        message_type=row["message_type"],
        in_reply_to_id=UUID(row["in_reply_to_id"]) if row["in_reply_to_id"] is not None else None,
        channel_id=UUID(row["channel_id"]) if row["channel_id"] is not None else None,
        cancelled_at=_parse(row["cancelled_at"]) if row["cancelled_at"] is not None else None,
        cancel_reason=row["cancel_reason"],
        coalesce_key=row["coalesce_key"],
    )
