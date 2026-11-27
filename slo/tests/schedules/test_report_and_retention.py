"""Report and retention tests (111.a.5 A1–A6, A8, A9; FIR111-05, FIR111-09)."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.channels.dao import NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.channel_delivery import SCHEDULER_CHANNEL_ID, ScheduleChannelSender
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase, format_instant
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.exceptions import ScheduleNotFoundError
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from pydantic import BaseModel, ConfigDict, Field

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


class ScriptedFreshRunner:
    """Records start calls and returns a completed result for run decisions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def start(
        self, *, prompt: str, cwd: str | None, model: str | None, session_id: str
    ) -> FreshRunResultDAO:
        """Record one start call and return a completed result.

        Args:
            prompt (str): The schedule prompt.
            cwd (str | None): The schedule's working directory override.
            model (str | None): The schedule's model override.
            session_id (str): The minted run session id.

        Returns:
            FreshRunResultDAO: A completed run with exit code 0.
        """
        self.calls.append({"prompt": prompt, "cwd": cwd, "model": model, "session_id": session_id})
        return FreshRunResultDAO(session_id=session_id, exit_code=0, status="completed")


class ReportHarnessDAO(BaseModel):
    """The typed collaborator set one report or retention test owns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    schedules_db: ScheduleDatabase = Field(description="The real tmp schedules database.")
    gateway: ChannelGateway = Field(description="The opened real channel gateway on a tmp store.")
    service: ScheduleService = Field(description="The schedule service over the tmp database.")
    deliver: DeliverScheduleInvocationAppService = Field(description="The deliver service under test.")
    fresh_runs: ScriptedFreshRunner = Field(
        description="The scripted fresh-run starter the deliver service uses."
    )

    async def close(self) -> None:
        """Close the gateway and the database in order."""
        await self.gateway.close()
        await self.schedules_db.close()


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[ReportHarnessDAO]:
    """Real service, gateway and deliver service on tmp databases."""
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    sender = ScheduleChannelSender(gateway=gateway)
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    fresh_runs = ScriptedFreshRunner()
    deliver = DeliverScheduleInvocationAppService(
        database=schedules_db,
        schedules=service,
        invocations=ScheduleInvocationRepository(),
        sender=sender,
        fresh_runs=fresh_runs,
        now_provider=_utc_now,
    )
    built = ReportHarnessDAO(
        schedules_db=schedules_db,
        gateway=gateway,
        service=service,
        deliver=deliver,
        fresh_runs=fresh_runs,
    )
    yield built
    await built.close()


async def _seed_report_matrix(harness: ReportHarnessDAO, *, now: datetime) -> UUID:
    """Seed the seven in-window rows and one outside row; return the schedule id.

    The channel-backed rows go through the real sender; the reconciler copies
    their outcomes before the channel rows are deleted, proving the report
    reads the snapshot only.
    """
    schedules_db = harness.schedules_db
    gateway = harness.gateway
    sender = ScheduleChannelSender(gateway=gateway)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Reported",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    schedule = await harness.service.show(reference=str(created.id))
    repository = ScheduleInvocationRepository()

    async def seed_pending(*, minutes_ago: int) -> UUID:
        """Insert one pending invocation ``minutes_ago`` before ``now``."""
        invocation_id = uuid4()
        async with schedules_db.transaction() as transaction:
            await repository.insert_pending(
                invocation=ScheduleInvocationDAO(
                    id=invocation_id,
                    schedule_id=created.id,
                    due_at=now - timedelta(minutes=minutes_ago),
                    status="pending",
                    created_at=now,
                ),
                transaction=transaction,
            )
        return invocation_id

    accepted = await seed_pending(minutes_ago=60)
    superseded = await seed_pending(minutes_ago=55)
    replied = await seed_pending(minutes_ago=50)
    unreconciled = await seed_pending(minutes_ago=30)
    for invocation_id in (accepted, superseded, replied, unreconciled):
        await sender.send(
            schedule=schedule,
            invocation_id=invocation_id,
            recipient_session_id=_SESSION_ID,
        )
    skipped = await seed_pending(minutes_ago=45)
    failed = await seed_pending(minutes_ago=40)
    pending_row = await seed_pending(minutes_ago=35)
    outside = await seed_pending(minutes_ago=60 * 48)

    # The four channel-backed rows were stored before a crash: mark them
    # delivered (the crash-recovery state) so the copy has rows to refresh.
    async with schedules_db.transaction() as transaction:
        for invocation_id in (accepted, superseded, replied, unreconciled):
            await transaction.execute(
                sql=(
                    "UPDATE schedule_invocations SET status = 'delivered',"
                    " channel_message_id = id, delivered_at = ? WHERE id = ?"
                ),
                parameters=(format_instant(value=now), str(invocation_id)),
            )

    await gateway.accept(message_id=accepted)
    assert await gateway.cancel(message_id=superseded, reason="superseded") is True
    await gateway.send(
        new=NewMessageDAO(
            sender_id=UUID(_SESSION_ID),
            recipient_id=UUID(_SESSION_ID),
            message_contents="schedule reply",
            message_type="reply",
            channel_id=SCHEDULER_CHANNEL_ID,
            in_reply_to_id=replied,
        )
    )

    reconciler = InvocationOutcomeReconciler(
        database=schedules_db,
        gateway=gateway,
        invocations=repository,
    )
    await reconciler.reconcile(now=now, limit=50)

    async with schedules_db.transaction() as transaction:
        await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'skipped', skip_reason = 'misfire'" " WHERE id = ?"
            ),
            parameters=(str(skipped),),
        )
        await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'failed', failure_reason ="
                " 'unknown_recipient' WHERE id = ?"
            ),
            parameters=(str(failed),),
        )

    # Delete every channel row: the report must read the snapshot only (D11/D18).
    with sqlite3.connect(str(schedules_db.db_path.parent / "channels.db")) as connection:
        connection.execute("DELETE FROM messages")
        connection.commit()
    return created.id


def _row_counts(db_path: Path, table: str) -> int:
    """Count the rows of one table through a read-only connection."""
    connection: sqlite3.Connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_report_verb_registered_and_legacy_report_verbs_removed() -> None:
    """A8: `report` is registered on the single schedule group; `reports`,
    `show-report` and `cleanup` are not."""
    from typer.testing import CliRunner

    from src.cli.app import app

    runner: CliRunner = CliRunner()
    for verb in ("report",):
        result = runner.invoke(app, ["schedule", verb, "--help"])
        assert result.exit_code == 0, f"{verb} must be registered"
    for verb in ("reports", "show-report", "cleanup"):
        result = runner.invoke(app, ["schedule", verb, "--help"])
        assert result.exit_code != 0, f"{verb} must be removed"


async def test_report_counts_match_window_and_writes_nothing(
    harness: ReportHarnessDAO, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1: counts match the rows in the window; outside rows excluded; the
    text shows every status and reason; the report writes nothing."""
    from typer.testing import CliRunner

    from src.cli.app import app

    now = _utc_now().replace(microsecond=0)
    created_id = await _seed_report_matrix(harness, now=now)
    schedules_before = _row_counts(db_path=tmp_path / "schedules.db", table="schedule_invocations")
    channels_before = _row_counts(db_path=tmp_path / "channels.db", table="messages")

    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
    # The dispatch owns asyncio.run, so the CLI runs on a worker thread's loop.
    result = await asyncio.to_thread(
        CliRunner().invoke, app, ["schedule", "report", "--schedule", str(created_id), "--days", "1"]
    )

    assert result.exit_code == 0, result.output
    text = result.output
    assert "total=7" in text
    assert "pending=1" in text
    assert "delivered=4" in text
    assert "skipped=1" in text
    assert "failed=1" in text
    assert "accepted=1" in text
    assert "cancelled=1" in text
    assert "superseded=1" in text
    assert "replied=1" in text
    assert "pending_outcome=0" in text
    assert "running=0" in text
    assert "completed=0" in text
    assert "run_failed=0" in text
    for fragment in ("skipped misfire", "failed unknown_recipient", "superseded"):
        assert fragment in text, fragment
    assert _row_counts(db_path=tmp_path / "schedules.db", table="schedule_invocations") == (schedules_before)
    assert _row_counts(db_path=tmp_path / "channels.db", table="messages") == channels_before


async def test_report_resolves_names_case_insensitively_and_spaced(
    harness: ReportHarnessDAO, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIR111-05: a report reference resolves by name with any case or extra
    spacing, like every other `--schedule` reference."""
    from typer.testing import CliRunner

    from src.cli.app import app

    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Daily Summary",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
    runner = CliRunner()
    for reference in ("Daily Summary", "daily summary", "  Daily   Summary "):
        result = await asyncio.to_thread(
            runner.invoke,
            app,
            ["schedule", "report", "--schedule", reference, "--days", "1"],
        )
        assert result.exit_code == 0, f"{reference!r}: {result.output}"
        assert "Daily Summary |" in result.output
    assert created.id is not None


async def test_report_resolves_uuid_shaped_names_and_keeps_id_precedence(
    harness: ReportHarnessDAO,
) -> None:
    """FRR111-04: a UUID-shaped reference resolves by id first; when no id
    matches, it falls back to the active-name lookup; a deleted schedule with
    a UUID-shaped name is never reportable by name."""
    from src.schedules.report import ScheduleReportService

    schedules_db = harness.schedules_db
    report = ScheduleReportService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    uuid_name = "01234567-89ab-cdef-0123-456789abcdef"
    now = _utc_now().replace(microsecond=0)

    id_target = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Id wins",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    assert id_target.id is not None
    name_target = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name=str(id_target.id),
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    # The id matches a row: the id wins over the UUID-shaped name.
    by_id = await report.build(
        reference=str(id_target.id),
        window_start=now - timedelta(hours=1),
        window_end=now,
    )
    assert by_id.schedule_id == id_target.id
    assert by_id.name == "Id wins"
    # No row carries the reference as an id: the active-name lookup runs.
    uuid_target = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name=uuid_name,
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    by_name = await report.build(
        reference=uuid_name,
        window_start=now - timedelta(hours=1),
        window_end=now,
    )
    assert by_name.schedule_id == uuid_target.id
    # A deleted schedule with a UUID-shaped name stays unreportable by name:
    # no row carries the reference as an id and the name only matches active rows.
    await harness.service.delete(reference=str(uuid_target.id), now=now)
    with pytest.raises(ScheduleNotFoundError):
        await report.build(
            reference=uuid_name,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    # Deleted id versus active name: once the id target is deleted, its id
    # still wins over the active schedule whose name is that same UUID text.
    await harness.service.delete(reference=str(id_target.id), now=now)
    deleted_by_id = await report.build(
        reference=str(id_target.id),
        window_start=now - timedelta(hours=1),
        window_end=now,
    )
    assert deleted_by_id.schedule_id == id_target.id
    assert deleted_by_id.schedule_id != name_target.id


async def test_cli_report_resolves_a_uuid_shaped_active_name(
    harness: ReportHarnessDAO, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FRR111-04 (mounted CLI): `report --schedule <uuid-shaped name>` exits 0
    with that schedule's report when no row carries the text as an id; after
    the schedule is deleted the same name exits 1."""
    from typer.testing import CliRunner

    from src.cli.app import app

    uuid_name: str = "89abcdef-0123-4567-89ab-cdef01234567"
    now: datetime = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name=uuid_name,
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
    runner: CliRunner = CliRunner()

    active = await asyncio.to_thread(
        runner.invoke, app, ["schedule", "report", "--schedule", uuid_name, "--days", "1"]
    )
    await harness.service.delete(reference=str(created.id), now=now)
    deleted = await asyncio.to_thread(
        runner.invoke, app, ["schedule", "report", "--schedule", uuid_name, "--days", "1"]
    )

    assert active.exit_code == 0, active.output
    assert f"{uuid_name} |" in active.output
    assert deleted.exit_code == 1, deleted.output
    assert "Traceback" not in deleted.output


async def test_report_rejects_zero_days_and_resolves_references(
    harness: ReportHarnessDAO, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2: `--days` 0 or 91 exit 2 without a read; unknown reference exits 1;
    a deleted schedule is reportable by id but never by name."""
    from typer.testing import CliRunner

    from src.cli.app import app

    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Deleted report target",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    await harness.service.delete(reference=str(created.id), now=now)
    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
    runner = CliRunner()

    for days in ("0", "91"):
        result = await asyncio.to_thread(
            runner.invoke, app, ["schedule", "report", "--schedule", "x", "--days", days]
        )
        assert result.exit_code == 2, days
    unknown = await asyncio.to_thread(
        runner.invoke, app, ["schedule", "report", "--schedule", "no-such-schedule"]
    )
    assert unknown.exit_code == 1
    by_id = await asyncio.to_thread(
        runner.invoke, app, ["schedule", "report", "--schedule", str(created.id), "--days", "1"]
    )
    assert by_id.exit_code == 0
    assert "Deleted report target |" in by_id.output
    by_name = await asyncio.to_thread(
        runner.invoke,
        app,
        ["schedule", "report", "--schedule", "Deleted report target", "--days", "1"],
    )
    assert by_name.exit_code == 1


async def test_report_lists_twenty_most_recent_invocations(
    harness: ReportHarnessDAO,
) -> None:
    """A3: 25 rows in the window; the report lists the last 20 by due_at."""
    from src.schedules.report import ScheduleReportService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Many rows",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    async with schedules_db.transaction() as transaction:
        for offset in range(25):
            await ScheduleInvocationRepository().insert_pending(
                invocation=ScheduleInvocationDAO(
                    id=uuid4(),
                    schedule_id=created.id,
                    due_at=now - timedelta(minutes=offset),
                    status="pending",
                    created_at=now,
                ),
                transaction=transaction,
            )

    report = ScheduleReportService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    result = await report.build(
        reference=str(created.id),
        window_start=now - timedelta(hours=1),
        window_end=now,
    )

    assert result.counts.total == 25
    assert len(result.recent_invocations) == 20
    due_times = [row.due_at for row in result.recent_invocations]
    assert due_times == sorted(due_times, reverse=True)
    assert due_times[0] == now


async def test_pruned_channel_row_reports_outcome_unavailable(
    harness: ReportHarnessDAO,
) -> None:
    """A9: a delivered row whose channel row was pruned before the outcome copy
    shows outcome_unavailable, not pending_outcome (D18)."""
    from src.schedules.report import ScheduleReportService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Pruned",
            prompt="report prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    invocation_id: UUID = uuid4()
    async with schedules_db.transaction() as transaction:
        await ScheduleInvocationRepository().insert_pending(
            invocation=ScheduleInvocationDAO(
                id=invocation_id,
                schedule_id=created.id,
                due_at=now,
                status="pending",
                created_at=now,
            ),
            transaction=transaction,
        )
        await transaction.execute(
            sql=(
                "UPDATE schedule_invocations SET status = 'delivered',"
                " channel_message_id = ?, delivered_at = ?, outcome_reconciled_at = ?,"
                " channel_row_gone_at = ?"
                " WHERE id = ?"
            ),
            parameters=(
                str(invocation_id),
                format_instant(value=now),
                format_instant(value=now),
                format_instant(value=now),
                str(invocation_id),
            ),
        )

    report = ScheduleReportService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    result = await report.build(
        reference=str(created.id),
        window_start=now - timedelta(hours=1),
        window_end=now,
    )

    assert result.counts.total == 1
    assert result.counts.delivered == 1
    assert result.counts.pending_outcome == 0
    assert result.counts.outcome_unavailable == 1


async def test_purge_deletes_rows_created_at_or_before_the_cutoff(
    harness: ReportHarnessDAO,
) -> None:
    """A4: rows created at or before the cutoff are deleted; 89-day rows stay;
    a second purge deletes nothing new."""
    from src.schedules.retention import ScheduleRetentionService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Purged",
            prompt="retention prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    repository = ScheduleInvocationRepository()
    async with schedules_db.transaction() as transaction:
        for age_days in (91, 90, 89):
            await repository.insert_pending(
                invocation=ScheduleInvocationDAO(
                    id=uuid4(),
                    schedule_id=created.id,
                    due_at=now - timedelta(days=age_days),
                    status="pending",
                    created_at=now - timedelta(days=age_days),
                ),
                transaction=transaction,
            )

    retention = ScheduleRetentionService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=repository,
    )
    result = await retention.purge(now=now)

    assert result.deleted_invocations == 2
    assert result.deleted_schedules == 0
    async with schedules_db.transaction() as transaction:
        remaining = await transaction.fetch_all(
            sql="SELECT created_at FROM schedule_invocations WHERE schedule_id = ?",
            parameters=(str(created.id),),
        )
    assert len(remaining) == 1
    from src.schedules.database import parse_instant

    assert parse_instant(text=str(remaining[0]["created_at"])) == now - timedelta(days=89)

    again = await retention.purge(now=now)
    assert again.deleted_invocations == 0
    assert again.deleted_schedules == 0


async def test_purge_removes_old_soft_deleted_schedules_without_rows(
    harness: ReportHarnessDAO,
) -> None:
    """A5: a soft-deleted schedule whose rows are all aged out is removed; one
    with rows left stays."""
    from src.schedules.retention import ScheduleRetentionService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    empty = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Empty deleted",
            prompt="retention prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    with_rows = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="With rows",
            prompt="retention prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    async with schedules_db.transaction() as transaction:
        for schedule_id in (empty.id, with_rows.id):
            await transaction.execute(
                sql="UPDATE schedules SET deleted_at = ? WHERE id = ?",
                parameters=(format_instant(value=now - timedelta(days=95)), str(schedule_id)),
            )
        await ScheduleInvocationRepository().insert_pending(
            invocation=ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=with_rows.id,
                due_at=now - timedelta(days=10),
                status="pending",
                created_at=now - timedelta(days=10),
            ),
            transaction=transaction,
        )

    retention = ScheduleRetentionService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    result = await retention.purge(now=now)

    assert result.deleted_invocations == 0
    assert result.deleted_schedules == 1
    async with schedules_db.transaction() as transaction:
        purged = await transaction.fetch_one(
            sql="SELECT id FROM schedules WHERE id = ?",
            parameters=(str(empty.id),),
        )
        kept = await transaction.fetch_one(
            sql="SELECT deleted_at FROM schedules WHERE id = ?",
            parameters=(str(with_rows.id),),
        )
    assert purged is None
    assert kept is not None
    assert kept["deleted_at"] is not None


async def test_purge_never_touches_channels_db(
    harness: ReportHarnessDAO,
) -> None:
    """A6: the purge deletes only schedules.db rows; the channel row count is
    unchanged and channels.db is never opened."""
    from src.schedules.retention import ScheduleRetentionService

    schedules_db = harness.schedules_db
    gateway = harness.gateway
    now = _utc_now()
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Purge only",
            prompt="purge prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    # A delivered channel row the purge must not touch. The send carries the
    # schedule's own prompt, so the row text comes from the stored schedule.
    sender = ScheduleChannelSender(gateway=gateway)
    await sender.send(
        schedule=created,
        invocation_id=uuid4(),
        recipient_session_id=_SESSION_ID,
    )
    async with schedules_db.transaction() as transaction:
        await ScheduleInvocationRepository().insert_pending(
            invocation=ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=created.id,
                due_at=now,
                status="pending",
                created_at=now - timedelta(days=91),
            ),
            transaction=transaction,
        )
    await harness.service.delete(reference=str(created.id), now=now - timedelta(days=91))
    channel_rows_before = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
    assert len(channel_rows_before) == 1

    retention = ScheduleRetentionService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    result = await retention.purge(now=now)

    assert result.deleted_invocations == 1
    channel_rows_after = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
    assert len(channel_rows_after) == 1


async def test_purge_loops_across_batches_until_done(harness: ReportHarnessDAO) -> None:
    """RPT-A4 (loop): more old rows than one batch forces the batch loop; every
    eligible row is deleted across batches and a second purge deletes none."""
    from src.schedules.retention import ScheduleRetentionService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Batch loop target",
            prompt="retention prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    repository = ScheduleInvocationRepository()
    old_rows: list[ScheduleInvocationDAO] = []
    for index in range(1005):
        old_rows.append(
            ScheduleInvocationDAO(
                id=uuid4(),
                schedule_id=created.id,
                due_at=now - timedelta(days=95, minutes=index),
                status="pending",
                created_at=now - timedelta(days=95),
            )
        )
    async with schedules_db.transaction() as transaction:
        for row in old_rows:
            await repository.insert_pending(invocation=row, transaction=transaction)

    retention = ScheduleRetentionService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=repository,
    )
    result = await retention.purge(now=now)

    assert result.deleted_invocations == 1005
    again = await retention.purge(now=now)
    assert again.deleted_invocations == 0


async def test_purge_keeps_recently_deleted_schedule(harness: ReportHarnessDAO) -> None:
    """RPT-A5 (third case): a schedule soft-deleted 89 days ago is kept even
    with no invocation rows left."""
    from src.schedules.retention import ScheduleRetentionService

    schedules_db = harness.schedules_db
    now = _utc_now().replace(microsecond=0)
    recent = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Recently deleted",
            prompt="retention prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    async with schedules_db.transaction() as transaction:
        await transaction.execute(
            sql="UPDATE schedules SET deleted_at = ? WHERE id = ?",
            parameters=(format_instant(value=now - timedelta(days=89)), str(recent.id)),
        )

    retention = ScheduleRetentionService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
    )
    result = await retention.purge(now=now)

    assert result.deleted_schedules == 0
    async with schedules_db.transaction() as transaction:
        kept = await transaction.fetch_one(
            sql="SELECT id FROM schedules WHERE id = ?", parameters=(str(recent.id),)
        )
    assert kept is not None
