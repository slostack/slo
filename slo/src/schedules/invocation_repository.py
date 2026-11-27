"""SQL for the `schedule_invocations` table; every method runs on the caller's transaction."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from src.schedules.dao import (
    InvocationOutcomeDAO,
    InvocationStatus,
    ScheduleInvocationDAO,
    ScheduleReportCountsDAO,
    SkipReason,
)
from src.schedules.database import ScheduleTransaction, format_instant, parse_instant
from src.schedules.exceptions import InvocationNotPendingError, InvocationNotRunningError

__all__ = ["ScheduleInvocationRepository"]

_INVOCATION_COLUMNS: tuple[str, ...] = (
    "id",
    "schedule_id",
    "due_at",
    "status",
    "skip_reason",
    "failure_reason",
    "recipient_session_id",
    "channel_message_id",
    "accepted_at",
    "cancelled_at",
    "cancel_reason",
    "reply_message_id",
    "outcome_reconciled_at",
    "channel_row_gone_at",
    "created_at",
    "delivered_at",
)


def _optional_instant(*, value: Optional[datetime]) -> Optional[str]:
    """Render an optional timestamp column value.

    Args:
        value (Optional[datetime]): The instant, or None.

    Returns:
        Optional[str]: The fixed-width text, or None.
    """
    return None if value is None else format_instant(value=value)


def _row_to_invocation(row: sqlite3.Row) -> ScheduleInvocationDAO:
    """Rebuild one invocation row into its DAO.

    Args:
        row (sqlite3.Row): The `schedule_invocations` row.

    Returns:
        ScheduleInvocationDAO: The typed invocation.
    """
    return ScheduleInvocationDAO(
        id=UUID(str(row["id"])),
        schedule_id=UUID(str(row["schedule_id"])),
        due_at=parse_instant(text=str(row["due_at"])),
        status=str(row["status"]),  # type: ignore[arg-type]
        skip_reason=row["skip_reason"],  # type: ignore[arg-type]
        failure_reason=row["failure_reason"],
        recipient_session_id=row["recipient_session_id"],
        channel_message_id=(
            None if row["channel_message_id"] is None else UUID(str(row["channel_message_id"]))
        ),
        accepted_at=None if row["accepted_at"] is None else parse_instant(text=str(row["accepted_at"])),
        cancelled_at=None if row["cancelled_at"] is None else parse_instant(text=str(row["cancelled_at"])),
        cancel_reason=row["cancel_reason"],
        reply_message_id=None if row["reply_message_id"] is None else UUID(str(row["reply_message_id"])),
        outcome_reconciled_at=(
            None
            if row["outcome_reconciled_at"] is None
            else parse_instant(text=str(row["outcome_reconciled_at"]))
        ),
        channel_row_gone_at=(
            None
            if row["channel_row_gone_at"] is None
            else parse_instant(text=str(row["channel_row_gone_at"]))
        ),
        run_exit_code=row["run_exit_code"],
        created_at=parse_instant(text=str(row["created_at"])),
        delivered_at=None if row["delivered_at"] is None else parse_instant(text=str(row["delivered_at"])),
    )


class ScheduleInvocationRepository:
    """Reads and writes `schedule_invocations` rows; never opens a transaction itself."""

    async def insert_pending(
        self, *, invocation: ScheduleInvocationDAO, transaction: ScheduleTransaction
    ) -> bool:
        """Insert one pending invocation row.

        Args:
            invocation (ScheduleInvocationDAO): The row to insert; its status must
                be pending and its due_at the planned instant.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            bool: True when the row was inserted; False on a duplicate
                ``(schedule_id, due_at)`` (the due time is already covered).
        """
        columns: dict[str, object] = {
            "id": str(invocation.id),
            "schedule_id": str(invocation.schedule_id),
            "due_at": format_instant(value=invocation.due_at),
            "status": invocation.status,
            "created_at": format_instant(value=invocation.created_at),
        }
        column_names: str = ", ".join(columns)
        placeholders: str = ", ".join("?" for _ in columns)
        try:
            await transaction.execute(
                sql=f"INSERT INTO schedule_invocations ({column_names}) VALUES ({placeholders})",
                parameters=tuple(columns[name] for name in columns),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    async def insert_misfire(
        self, *, invocation: ScheduleInvocationDAO, transaction: ScheduleTransaction
    ) -> bool:
        """Insert one skipped/misfire invocation row.

        Args:
            invocation (ScheduleInvocationDAO): The row to insert; its status must
                be skipped, its skip_reason misfire and its due_at the missed
                instant.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            bool: True when the row was inserted; False on a duplicate
                ``(schedule_id, due_at)`` (the missed time is already recorded).
        """
        columns: dict[str, object] = {
            "id": str(invocation.id),
            "schedule_id": str(invocation.schedule_id),
            "due_at": format_instant(value=invocation.due_at),
            "status": invocation.status,
            "skip_reason": invocation.skip_reason,
            "created_at": format_instant(value=invocation.created_at),
        }
        column_names: str = ", ".join(columns)
        placeholders: str = ", ".join("?" for _ in columns)
        try:
            await transaction.execute(
                sql=f"INSERT INTO schedule_invocations ({column_names}) VALUES ({placeholders})",
                parameters=tuple(columns[name] for name in columns),
            )
        except sqlite3.IntegrityError:
            return False
        return True

    async def get(
        self, *, invocation_id: UUID, transaction: ScheduleTransaction
    ) -> Optional[ScheduleInvocationDAO]:
        """Load one invocation row.

        Args:
            invocation_id (UUID): The invocation to load.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleInvocationDAO]: The row, or None when missing.
        """
        row: Optional[sqlite3.Row] = await transaction.fetch_one(
            sql="SELECT * FROM schedule_invocations WHERE id = ?",
            parameters=(str(invocation_id),),
        )
        return None if row is None else _row_to_invocation(row=row)

    async def get_by_schedule_and_due(
        self,
        *,
        schedule_id: UUID,
        due_at: datetime,
        transaction: ScheduleTransaction,
    ) -> Optional[ScheduleInvocationDAO]:
        """Load the one invocation row for a schedule's due time.

        Args:
            schedule_id (UUID): The schedule the invocation belongs to.
            due_at (datetime): The planned due instant; unique per schedule.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleInvocationDAO]: The row, or None when missing.
        """
        row: Optional[sqlite3.Row] = await transaction.fetch_one(
            sql="SELECT * FROM schedule_invocations WHERE schedule_id = ? AND due_at = ?",
            parameters=(str(schedule_id), format_instant(value=due_at)),
        )
        return None if row is None else _row_to_invocation(row=row)

    async def list_for_schedule(
        self,
        *,
        schedule_id: UUID,
        since: datetime,
        until: datetime,
        limit: Optional[int],
        transaction: ScheduleTransaction,
    ) -> list[ScheduleInvocationDAO]:
        """List one schedule's invocations whose due time falls in a window.

        Args:
            schedule_id (UUID): The schedule whose rows to list.
            since (datetime): Window start; a row matches when ``due_at >= since``.
            until (datetime): Window end; a row matches when ``due_at <= until``.
            limit (Optional[int]): Maximum rows to return, or None for all.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleInvocationDAO]: The rows, newest due_at first.
        """
        sql: str = (
            "SELECT * FROM schedule_invocations"
            " WHERE schedule_id = ? AND due_at >= ? AND due_at <= ?"
            " ORDER BY due_at DESC"
        )
        parameters: list[object] = [
            str(schedule_id),
            format_instant(value=since),
            format_instant(value=until),
        ]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        rows: list[sqlite3.Row] = await transaction.fetch_all(sql=sql, parameters=tuple(parameters))
        return [_row_to_invocation(row=row) for row in rows]

    async def count_for_window(
        self,
        *,
        schedule_id: UUID,
        since: datetime,
        until: datetime,
        transaction: ScheduleTransaction,
    ) -> "ScheduleReportCountsDAO":
        """Count one schedule's invocations in a window by the report rules.

        One SQL query computes every count; no row is loaded into the process.

        Args:
            schedule_id (UUID): The schedule whose rows to count.
            since (datetime): Window start; a row matches when ``due_at >= since``.
            until (datetime): Window end; a row matches when ``due_at <= until``.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            ScheduleReportCountsDAO: The counts for the window.
        """
        sql: str = (
            "SELECT"
            " COUNT(*) AS total,"
            " SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,"
            " SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS delivered,"
            " SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,"
            " SUM(CASE WHEN status = 'skipped' AND skip_reason = 'misfire' THEN 1 ELSE 0 END)"
            "   AS skipped_misfire,"
            " SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,"
            " SUM(CASE WHEN status = 'delivered' AND accepted_at IS NOT NULL THEN 1 ELSE 0 END)"
            "   AS accepted,"
            " SUM(CASE WHEN status = 'delivered' AND cancelled_at IS NOT NULL THEN 1 ELSE 0 END)"
            "   AS cancelled,"
            " SUM(CASE WHEN status = 'delivered' AND cancelled_at IS NOT NULL"
            "   AND cancel_reason = 'superseded' THEN 1 ELSE 0 END) AS superseded,"
            " SUM(CASE WHEN reply_message_id IS NOT NULL THEN 1 ELSE 0 END) AS replied,"
            " SUM(CASE WHEN status = 'delivered' AND outcome_reconciled_at IS NULL"
            "   AND channel_row_gone_at IS NULL THEN 1 ELSE 0 END) AS pending_outcome,"
            " SUM(CASE WHEN status = 'delivered' AND channel_row_gone_at IS NOT NULL THEN 1 ELSE 0 END)"
            "   AS outcome_unavailable,"
            " SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running,"
            " SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,"
            " SUM(CASE WHEN status = 'run_failed' THEN 1 ELSE 0 END) AS run_failed"
            " FROM schedule_invocations"
            " WHERE schedule_id = ? AND due_at >= ? AND due_at <= ?"
        )
        row: Optional[sqlite3.Row] = await transaction.fetch_one(
            sql=sql,
            parameters=(
                str(schedule_id),
                format_instant(value=since),
                format_instant(value=until),
            ),
        )
        assert row is not None, "aggregate over the window always returns one row"
        return ScheduleReportCountsDAO(
            total=row["total"],
            pending=row["pending"] or 0,
            delivered=row["delivered"] or 0,
            skipped=row["skipped"] or 0,
            skipped_misfire=row["skipped_misfire"] or 0,
            failed=row["failed"] or 0,
            accepted=row["accepted"] or 0,
            cancelled=row["cancelled"] or 0,
            superseded=row["superseded"] or 0,
            replied=row["replied"] or 0,
            pending_outcome=row["pending_outcome"] or 0,
            outcome_unavailable=row["outcome_unavailable"] or 0,
            running=row["running"] or 0,
            completed=row["completed"] or 0,
            run_failed=row["run_failed"] or 0,
        )

    async def purge_created_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        transaction: ScheduleTransaction,
    ) -> int:
        """Delete at most ``batch_size`` invocation rows created at or before cutoff.

        Args:
            cutoff (datetime): Rows created at or before this instant are deleted.
            batch_size (int): Maximum rows to delete in this batch.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            int: The number of rows deleted in this batch.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "DELETE FROM schedule_invocations WHERE id IN ("
                " SELECT id FROM schedule_invocations WHERE created_at <= ? LIMIT ?)"
            ),
            parameters=(format_instant(value=cutoff), batch_size),
        )
        return cursor.rowcount

    async def list_pending(
        self, *, limit: int, transaction: ScheduleTransaction
    ) -> list[ScheduleInvocationDAO]:
        """List pending invocations, oldest due first.

        Args:
            limit (int): Maximum rows to return.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleInvocationDAO]: The pending rows.
        """
        rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT * FROM schedule_invocations WHERE status = 'pending'"
                " ORDER BY due_at ASC, created_at ASC LIMIT ?"
            ),
            parameters=(limit,),
        )
        return [_row_to_invocation(row=row) for row in rows]

    async def latest_status_by_schedule(
        self, *, schedule_ids: list[UUID], transaction: ScheduleTransaction
    ) -> dict[UUID, InvocationStatus]:
        """Return the newest invocation status per schedule.

        Args:
            schedule_ids (list[UUID]): The schedule ids to look up.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            dict[UUID, InvocationStatus]: One status per schedule id that has an
                invocation row; schedules without rows are absent.
        """
        if not schedule_ids:
            return {}
        placeholders: str = ", ".join("?" for _ in schedule_ids)
        rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT schedule_id, status FROM schedule_invocations"
                f" WHERE schedule_id IN ({placeholders})"
                " ORDER BY created_at DESC, due_at DESC"
            ),
            parameters=tuple(str(schedule_id) for schedule_id in schedule_ids),
        )
        statuses: dict[UUID, InvocationStatus] = {}
        for row in rows:
            schedule_id: UUID = UUID(str(row["schedule_id"]))
            if schedule_id not in statuses:
                statuses[schedule_id] = str(row["status"])  # type: ignore[assignment]
        return statuses

    async def latest_status(
        self, *, schedule_id: UUID, transaction: ScheduleTransaction
    ) -> Optional[InvocationStatus]:
        """Return the newest invocation status for one schedule.

        Args:
            schedule_id (UUID): The schedule id to look up.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[InvocationStatus]: The newest status, or None.
        """
        statuses: dict[UUID, InvocationStatus] = await self.latest_status_by_schedule(
            schedule_ids=[schedule_id],
            transaction=transaction,
        )
        return statuses.get(schedule_id)

    async def mark_delivered(
        self,
        *,
        invocation_id: UUID,
        channel_message_id: UUID,
        delivered_at: datetime,
        recipient_session_id: Optional[str],
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one pending invocation delivered.

        Args:
            invocation_id (UUID): The invocation to finalise.
            channel_message_id (UUID): The channel row id; the invocation id.
            delivered_at (datetime): The delivery instant.
            recipient_session_id (Optional[str]): The agent session that
                received the message, when it is known (111.a.2 A17).
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer pending.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'delivered',"
                " channel_message_id = ?, delivered_at = ?, recipient_session_id = ?"
                " WHERE id = ? AND status = 'pending'"
            ),
            parameters=(
                str(channel_message_id),
                format_instant(value=delivered_at),
                recipient_session_id,
                str(invocation_id),
            ),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)

    async def mark_running(
        self,
        *,
        invocation_id: UUID,
        recipient_session_id: str,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one pending invocation running with its fresh-run session id.

        The commit happens before the child process starts (111.a.3 §5.3 step 2).

        Args:
            invocation_id (UUID): The invocation to mark running.
            recipient_session_id (str): The minted session id the run will use.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer pending.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'running',"
                " recipient_session_id = ? WHERE id = ? AND status = 'pending'"
            ),
            parameters=(recipient_session_id, str(invocation_id)),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)

    async def mark_run_finished(
        self,
        *,
        invocation_id: UUID,
        status: Literal["completed", "run_failed"],
        run_exit_code: int,
        delivered_at: datetime,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one running invocation's fresh run finished.

        Args:
            invocation_id (UUID): The invocation whose run ended.
            status (Literal["completed", "run_failed"]): The run outcome.
            run_exit_code (int): The child's exit code.
            delivered_at (datetime): The time the run finished, UTC.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotRunningError: When the row is not running.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = ?, run_exit_code = ?,"
                " delivered_at = ? WHERE id = ? AND status = 'running'"
            ),
            parameters=(
                status,
                run_exit_code,
                format_instant(value=delivered_at),
                str(invocation_id),
            ),
        )
        if cursor.rowcount == 0:
            raise InvocationNotRunningError(invocation_id=invocation_id)

    async def mark_run_failed(
        self,
        *,
        invocation_id: UUID,
        failure_reason: str,
        delivered_at: datetime,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one running invocation run_failed without a child exit code.

        The child never produced an exit code (a launch failure or a restart
        recovery), so only the reason and the settlement instant are known.

        Args:
            invocation_id (UUID): The invocation to settle.
            failure_reason (str): Why the run ended without an exit code.
            delivered_at (datetime): The settlement instant, UTC.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotRunningError: When the row is not running.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'run_failed', failure_reason = ?,"
                " delivered_at = ? WHERE id = ? AND status = 'running'"
            ),
            parameters=(
                failure_reason,
                format_instant(value=delivered_at),
                str(invocation_id),
            ),
        )
        if cursor.rowcount == 0:
            raise InvocationNotRunningError(invocation_id=invocation_id)

    async def mark_stale_running_failed(
        self,
        *,
        older_than: datetime,
        failure_reason: str,
        recovered_at: datetime,
        transaction: ScheduleTransaction,
    ) -> list[UUID]:
        """Mark each running row older than the run timeout run_failed (D24).

        The occurrence is lost: the row is never re-run (111.a.3 §5.6). The
        recovery reason names the timeout (A8); the one-shot end runs on the
        schedules the caller returns this as.

        Args:
            older_than (datetime): Rows created before this instant are stale.
            failure_reason (str): The recovery reason recorded on each row.
            recovered_at (datetime): The settlement instant recorded as
                ``delivered_at`` (the time the lost occurrence was settled).
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[UUID]: The schedules whose stale rows were recovered, for the
                caller's one-shot end in the same transaction.
        """
        stale_rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT DISTINCT schedule_id FROM schedule_invocations"
                " WHERE status = 'running' AND created_at < ?"
            ),
            parameters=(format_instant(value=older_than),),
        )
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'run_failed', failure_reason = ?,"
                " delivered_at = ? WHERE status = 'running' AND created_at < ?"
            ),
            parameters=(failure_reason, format_instant(value=recovered_at), format_instant(value=older_than)),
        )
        if cursor.rowcount != len(stale_rows):
            raise RuntimeError("stale running rows changed between selection and recovery")
        return [UUID(str(stale_row["schedule_id"])) for stale_row in stale_rows]

    async def mark_skipped(
        self,
        *,
        invocation_id: UUID,
        skip_reason: SkipReason,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one pending invocation skipped.

        Args:
            invocation_id (UUID): The invocation to finalise.
            skip_reason (SkipReason): Why the invocation was skipped.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer pending.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'skipped', skip_reason = ?"
                " WHERE id = ? AND status = 'pending'"
            ),
            parameters=(skip_reason, str(invocation_id)),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)

    async def mark_failed(
        self,
        *,
        invocation_id: UUID,
        failure_reason: str,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark one pending invocation failed.

        Args:
            invocation_id (UUID): The invocation to finalise.
            failure_reason (str): Why delivery was refused.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer pending.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'failed', failure_reason = ?"
                " WHERE id = ? AND status = 'pending'"
            ),
            parameters=(failure_reason, str(invocation_id)),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)

    async def list_awaiting_outcome(
        self, *, limit: int, transaction: ScheduleTransaction
    ) -> list[ScheduleInvocationDAO]:
        """List delivered invocations whose outcome snapshot is incomplete.

        Selects ``status = 'delivered'`` rows with ``channel_row_gone_at`` unset,
        ``cancelled_at`` unset and either ``accepted_at`` or ``reply_message_id``
        unset, oldest reconciled first (NULL first).

        Args:
            limit (int): Maximum rows to return.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleInvocationDAO]: The rows whose outcome to refresh.
        """
        rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT * FROM schedule_invocations WHERE status = 'delivered'"
                " AND channel_row_gone_at IS NULL AND cancelled_at IS NULL"
                " AND (accepted_at IS NULL OR reply_message_id IS NULL)"
                " ORDER BY outcome_reconciled_at ASC LIMIT ?"
            ),
            parameters=(limit,),
        )
        return [_row_to_invocation(row=row) for row in rows]

    async def record_outcome(
        self,
        *,
        invocation_id: UUID,
        outcome: InvocationOutcomeDAO,
        reconciled_at: datetime,
        transaction: ScheduleTransaction,
    ) -> None:
        """Copy one channel outcome snapshot onto a delivered invocation.

        Args:
            invocation_id (UUID): The invocation to update.
            outcome (InvocationOutcomeDAO): The channel facts to copy.
            reconciled_at (datetime): The snapshot instant.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer delivered.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET accepted_at = COALESCE(?, accepted_at),"
                " cancelled_at = COALESCE(?, cancelled_at),"
                " cancel_reason = COALESCE(?, cancel_reason),"
                " reply_message_id = COALESCE(?, reply_message_id),"
                " outcome_reconciled_at = ?"
                " WHERE id = ? AND status = 'delivered' AND channel_row_gone_at IS NULL"
            ),
            parameters=(
                _optional_instant(value=outcome.accepted_at),
                _optional_instant(value=outcome.cancelled_at),
                outcome.cancel_reason,
                None if outcome.reply_message_id is None else str(outcome.reply_message_id),
                format_instant(value=reconciled_at),
                str(invocation_id),
            ),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)

    async def mark_channel_row_gone(
        self,
        *,
        invocation_id: UUID,
        reconciled_at: datetime,
        transaction: ScheduleTransaction,
    ) -> None:
        """Mark a delivered invocation whose channel row is gone.

        Sets ``channel_row_gone_at`` and ``outcome_reconciled_at``; the snapshot
        columns stay unchanged. The row is never selected again.

        Args:
            invocation_id (UUID): The invocation to stop reading.
            reconciled_at (datetime): The instant the channel row was found missing.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            InvocationNotPendingError: When the row is no longer delivered.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET channel_row_gone_at = ?,"
                " outcome_reconciled_at = ?"
                " WHERE id = ? AND status = 'delivered' AND channel_row_gone_at IS NULL"
            ),
            parameters=(
                format_instant(value=reconciled_at),
                format_instant(value=reconciled_at),
                str(invocation_id),
            ),
        )
        if cursor.rowcount == 0:
            raise InvocationNotPendingError(invocation_id=invocation_id)
