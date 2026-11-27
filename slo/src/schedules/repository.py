"""SQL for the `schedules` table; every method runs on the caller's transaction."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional
from uuid import UUID

from src.schedules.dao import (
    CronTriggerDAO,
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleDAO,
    ScheduleStateFilter,
    TriggerDAO,
)
from src.schedules.database import ScheduleTransaction, format_instant, parse_instant
from src.schedules.exceptions import ScheduleNameTakenError, ScheduleNotFoundError

__all__ = ["ScheduleRepository"]

_SCHEDULE_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "name_key",
    "prompt",
    "trigger_kind",
    "run_at",
    "every_seconds",
    "interval_anchor_at",
    "cron_expression",
    "timezone",
    "session_mode",
    "session_reference",
    "coalescing_mode",
    "coalescing_key",
    "cwd",
    "model",
    "misfire_grace_seconds",
    "enabled",
    "next_due_at",
    "created_at",
    "updated_at",
    "deleted_at",
)


def _optional_instant(*, value: Optional[datetime]) -> Optional[str]:
    """Render an optional timestamp column value.

    Args:
        value (Optional[datetime]): The instant, or None.

    Returns:
        Optional[str]: The fixed-width text, or None.
    """
    return None if value is None else format_instant(value=value)


def _trigger_to_columns(*, trigger: TriggerDAO) -> dict[str, Optional[object]]:
    """Flatten one trigger union into its table columns.

    Args:
        trigger (TriggerDAO): The trigger to flatten.

    Returns:
        dict[str, Optional[object]]: The trigger columns for one trigger kind.
    """
    if isinstance(trigger, OneShotTriggerDAO):
        return {
            "trigger_kind": "one_shot",
            "run_at": format_instant(value=trigger.run_at),
            "every_seconds": None,
            "interval_anchor_at": None,
            "cron_expression": None,
            "timezone": None,
        }
    if isinstance(trigger, IntervalTriggerDAO):
        return {
            "trigger_kind": "interval",
            "run_at": None,
            "every_seconds": trigger.every_seconds,
            "interval_anchor_at": _optional_instant(value=trigger.anchor),
            "cron_expression": None,
            "timezone": None,
        }
    return {
        "trigger_kind": "cron",
        "run_at": None,
        "every_seconds": None,
        "interval_anchor_at": None,
        "cron_expression": trigger.expression,
        "timezone": trigger.tz,
    }


def _row_to_trigger(row: sqlite3.Row) -> TriggerDAO:
    """Rebuild the trigger union from one row's trigger columns.

    Args:
        row (sqlite3.Row): The schedules row.

    Returns:
        TriggerDAO: The trigger for the row's trigger kind.
    """
    kind: str = str(row["trigger_kind"])
    if kind == "one_shot":
        return OneShotTriggerDAO(run_at=parse_instant(text=str(row["run_at"])))
    if kind == "interval":
        anchor_text: Optional[str] = row["interval_anchor_at"]
        return IntervalTriggerDAO(
            every_seconds=int(row["every_seconds"]),
            anchor=None if anchor_text is None else parse_instant(text=anchor_text),
        )
    return CronTriggerDAO(expression=str(row["cron_expression"]), tz=str(row["timezone"]))


def _row_to_schedule(row: sqlite3.Row) -> ScheduleDAO:
    """Rebuild one schedule row into its DAO.

    Args:
        row (sqlite3.Row): The schedules row.

    Returns:
        ScheduleDAO: The typed schedule.
    """
    deleted_at: Optional[str] = row["deleted_at"]
    next_due_at: Optional[str] = row["next_due_at"]
    return ScheduleDAO(
        id=UUID(str(row["id"])),
        name=str(row["name"]),
        name_key=str(row["name_key"]),
        prompt=str(row["prompt"]),
        trigger=_row_to_trigger(row=row),
        session_mode=str(row["session_mode"]),  # type: ignore[arg-type]
        session_reference=row["session_reference"],
        coalescing_mode=str(row["coalescing_mode"]),  # type: ignore[arg-type]
        coalescing_key=row["coalescing_key"],
        cwd=row["cwd"],
        model=row["model"],
        misfire_grace_seconds=int(row["misfire_grace_seconds"]),
        enabled=bool(row["enabled"]),
        next_due_at=None if next_due_at is None else parse_instant(text=next_due_at),
        created_at=parse_instant(text=str(row["created_at"])),
        updated_at=parse_instant(text=str(row["updated_at"])),
        deleted_at=None if deleted_at is None else parse_instant(text=deleted_at),
    )


class ScheduleRepository:
    """Reads and writes `schedules` rows; never opens a transaction itself."""

    async def insert(self, *, schedule: ScheduleDAO, transaction: ScheduleTransaction) -> None:
        """Insert one schedule row.

        Args:
            schedule (ScheduleDAO): The schedule to insert.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            ScheduleNameTakenError: When an active row already holds the name key.
        """
        columns: dict[str, object] = {
            "id": str(schedule.id),
            "name": schedule.name,
            "name_key": schedule.name_key,
            "prompt": schedule.prompt,
            "session_mode": schedule.session_mode,
            "session_reference": schedule.session_reference,
            "coalescing_mode": schedule.coalescing_mode,
            "coalescing_key": schedule.coalescing_key,
            "cwd": schedule.cwd,
            "model": schedule.model,
            "misfire_grace_seconds": schedule.misfire_grace_seconds,
            "enabled": int(schedule.enabled),
            "next_due_at": _optional_instant(value=schedule.next_due_at),
            "created_at": format_instant(value=schedule.created_at),
            "updated_at": format_instant(value=schedule.updated_at),
            "deleted_at": _optional_instant(value=schedule.deleted_at),
            **_trigger_to_columns(trigger=schedule.trigger),
        }
        column_names: str = ", ".join(columns)
        placeholders: str = ", ".join("?" for _ in columns)
        try:
            await transaction.execute(
                sql=f"INSERT INTO schedules ({column_names}) VALUES ({placeholders})",
                parameters=tuple(columns[name] for name in columns),
            )
        except sqlite3.IntegrityError as error:
            if "schedules_active_name" in str(error):
                raise ScheduleNameTakenError(name_key=schedule.name_key) from error
            raise

    async def get_by_reference(
        self, *, reference: str, transaction: ScheduleTransaction
    ) -> Optional[ScheduleDAO]:
        """Resolve one active schedule by id or name.

        Args:
            reference (str): The schedule id or name.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleDAO]: The active schedule, or None when nothing matches.
        """
        as_uuid: Optional[UUID] = None
        try:
            as_uuid = UUID(reference)
        except ValueError:
            pass
        if as_uuid is not None:
            row: Optional[sqlite3.Row] = await transaction.fetch_one(
                sql="SELECT * FROM schedules WHERE id = ? AND deleted_at IS NULL",
                parameters=(str(as_uuid),),
            )
            if row is not None:
                return _row_to_schedule(row=row)
        return await self._get_active_by_name_key(
            name_key=NewScheduleDAO.normalize_name_key(name=reference),
            transaction=transaction,
        )

    async def get_active_by_name_key(
        self, *, name_key: str, transaction: ScheduleTransaction
    ) -> Optional[ScheduleDAO]:
        """Find one active row by its normalised name key.

        Args:
            name_key (str): The normalised name key.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleDAO]: The active schedule, or None.
        """
        return await self._get_active_by_name_key(name_key=name_key, transaction=transaction)

    async def list_by_state(
        self, *, state: ScheduleStateFilter, transaction: ScheduleTransaction
    ) -> list[ScheduleDAO]:
        """List schedules in one state, ordered by name key then creation time.

        Args:
            state (ScheduleStateFilter): ``active`` or ``disabled``.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleDAO]: The matching rows in deterministic order.
        """
        enabled_value: int = 1 if state == "active" else 0
        rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT * FROM schedules WHERE enabled = ? AND deleted_at IS NULL"
                " ORDER BY name_key ASC, created_at ASC"
            ),
            parameters=(enabled_value,),
        )
        return [_row_to_schedule(row=row) for row in rows]

    async def update(self, *, schedule: ScheduleDAO, transaction: ScheduleTransaction) -> None:
        """Update one active schedule row.

        Args:
            schedule (ScheduleDAO): The full row to write.
            transaction (ScheduleTransaction): The caller's open transaction.

        Raises:
            ScheduleNotFoundError: When the row is deleted or missing.
        """
        columns: dict[str, object] = {
            "name": schedule.name,
            "name_key": schedule.name_key,
            "prompt": schedule.prompt,
            "session_mode": schedule.session_mode,
            "session_reference": schedule.session_reference,
            "coalescing_mode": schedule.coalescing_mode,
            "coalescing_key": schedule.coalescing_key,
            "cwd": schedule.cwd,
            "model": schedule.model,
            "misfire_grace_seconds": schedule.misfire_grace_seconds,
            "enabled": int(schedule.enabled),
            "next_due_at": _optional_instant(value=schedule.next_due_at),
            "deleted_at": _optional_instant(value=schedule.deleted_at),
            "updated_at": format_instant(value=schedule.updated_at),
            **_trigger_to_columns(trigger=schedule.trigger),
        }
        assignments: str = ", ".join(f"{name} = ?" for name in columns)
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=f"UPDATE schedules SET {assignments} WHERE id = ? AND deleted_at IS NULL",
            parameters=(*tuple(columns[name] for name in columns), str(schedule.id)),
        )
        if cursor.rowcount == 0:
            raise ScheduleNotFoundError(reference=str(schedule.id))

    async def list_due(
        self, *, now: datetime, limit: int, transaction: ScheduleTransaction
    ) -> list[ScheduleDAO]:
        """List enabled, non-deleted schedules whose next due time has passed.

        Args:
            now (datetime): The boundary instant; rows with ``next_due_at <= now`` match.
            limit (int): Maximum rows to return.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            list[ScheduleDAO]: The due rows, oldest ``next_due_at`` first.
        """
        rows: list[sqlite3.Row] = await transaction.fetch_all(
            sql=(
                "SELECT * FROM schedules WHERE enabled = 1 AND deleted_at IS NULL"
                " AND next_due_at IS NOT NULL AND next_due_at <= ?"
                " ORDER BY next_due_at ASC LIMIT ?"
            ),
            parameters=(format_instant(value=now), limit),
        )
        return [_row_to_schedule(row=row) for row in rows]

    async def purge_deleted_before(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        transaction: ScheduleTransaction,
    ) -> int:
        """Delete at most ``batch_size`` soft-deleted schedules with no rows left.

        Args:
            cutoff (datetime): Rows soft-deleted at or before this instant are
                candidates.
            batch_size (int): Maximum rows to delete in this batch.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            int: The number of schedule rows deleted in this batch.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "DELETE FROM schedules WHERE id IN ("
                " SELECT id FROM schedules WHERE deleted_at <= ?"
                " AND NOT EXISTS (SELECT 1 FROM schedule_invocations"
                "                 WHERE schedule_invocations.schedule_id = schedules.id)"
                " LIMIT ?)"
            ),
            parameters=(format_instant(value=cutoff), batch_size),
        )
        return cursor.rowcount

    async def get_by_id(
        self,
        *,
        schedule_id: UUID,
        include_deleted: bool,
        transaction: ScheduleTransaction,
    ) -> Optional[ScheduleDAO]:
        """Load one schedule by id, optionally including soft-deleted rows.

        Args:
            schedule_id (UUID): The schedule to load.
            include_deleted (bool): True also returns rows whose ``deleted_at`` is set.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleDAO]: The row, or None when missing (or deleted and
                ``include_deleted`` is False).
        """
        sql: str = "SELECT * FROM schedules WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row: Optional[sqlite3.Row] = await transaction.fetch_one(sql=sql, parameters=(str(schedule_id),))
        return None if row is None else _row_to_schedule(row=row)

    async def set_next_due(
        self,
        *,
        schedule_id: UUID,
        expected_due_at: datetime,
        next_due_at: Optional[datetime],
        transaction: ScheduleTransaction,
    ) -> bool:
        """Advance one enabled schedule's next due time, guarded on the expected value.

        Args:
            schedule_id (UUID): The schedule to advance.
            expected_due_at (datetime): The due time the tick handled; the update
                matches only when ``next_due_at`` still holds it.
            next_due_at (Optional[datetime]): The new due time, or None to clear it
                (a one-shot stays enabled until its invocation is final).
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            bool: True when the update matched; False when the schedule was stopped,
                edited or deleted since selection.
        """
        cursor: sqlite3.Cursor = await transaction.execute(
            sql=(
                "UPDATE schedules SET next_due_at = ? WHERE id = ? AND enabled = 1"
                " AND deleted_at IS NULL AND next_due_at = ?"
            ),
            parameters=(
                _optional_instant(value=next_due_at),
                str(schedule_id),
                format_instant(value=expected_due_at),
            ),
        )
        return cursor.rowcount == 1

    async def _get_active_by_name_key(
        self, *, name_key: str, transaction: ScheduleTransaction
    ) -> Optional[ScheduleDAO]:
        """Find one active row by name key.

        Args:
            name_key (str): The normalised name key.
            transaction (ScheduleTransaction): The caller's open transaction.

        Returns:
            Optional[ScheduleDAO]: The active schedule, or None.
        """
        row: Optional[sqlite3.Row] = await transaction.fetch_one(
            sql="SELECT * FROM schedules WHERE name_key = ? AND deleted_at IS NULL",
            parameters=(name_key,),
        )
        return None if row is None else _row_to_schedule(row=row)
