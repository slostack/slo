"""Trigger journey tests (111.a.2 A5, T2.4) on real SQLite."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.schedules.dao import IntervalTriggerDAO, NewScheduleDAO, ScheduleInvocationDAO
from src.schedules.database import ScheduleDatabase
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.exceptions import ScheduleInvalidError, ScheduleNotFoundError
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.channel_delivery import ScheduleChannelSender
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class ScriptedFreshRunner:
    """Records start calls and returns a completed result for run decisions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def start(
        self,
        *,
        prompt: str,
        cwd: str | None,
        model: str | None,
        session_id: str,
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


def _utc() -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=12, minute=0, tzinfo=timezone.utc)


def _interval_input(name: str = "Daily Summary") -> NewScheduleDAO:
    """Build a valid continuous interval schedule input."""
    return NewScheduleDAO(
        name=name,
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
    )


class RecordingInvocationQueue:
    """Engine seam stub: records every enqueue the tick hands over (spec §6.2)."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[UUID, UUID]] = []

    async def enqueue_delivery(self, *, invocation_id: UUID, schedule_id: UUID) -> None:
        """Record one enqueue call.

        Args:
            invocation_id (UUID): The pending invocation handed to the engine.
            schedule_id (UUID): Its schedule.
        """
        self.calls.append((invocation_id, schedule_id))


class TriggerHarnessDAO(BaseModel):
    """The typed collaborator set one trigger test owns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    database: ScheduleDatabase = Field(description="The real tmp schedules database.")
    service: ScheduleService = Field(description="The schedule service over the tmp database.")
    invocations: ScheduleInvocationRepository = Field(
        description="The invocation repository the services share."
    )

    async def close(self) -> None:
        """Close the schedules database."""
        await self.database.close()


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[TriggerHarnessDAO]:
    """Build a real service on a tmp_path database."""
    database: ScheduleDatabase = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    invocations: ScheduleInvocationRepository = ScheduleInvocationRepository()
    built: TriggerHarnessDAO = TriggerHarnessDAO(
        database=database,
        service=ScheduleService(
            database=database,
            schedules=ScheduleRepository(),
            invocations=invocations,
            session_history=None,
        ),
        invocations=invocations,
    )
    yield built
    await built.close()


async def test_trigger_creates_one_pending_invocation_at_now(
    harness: TriggerHarnessDAO,
) -> None:
    """A5: trigger_now inserts one pending row with due_at = now truncated to ms."""
    service: ScheduleService = harness.service
    invocations: ScheduleInvocationRepository = harness.invocations
    database: ScheduleDatabase = harness.database
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    result = await service.trigger_now(reference=str(created.id), now=now)

    assert result.status == "pending"
    assert result.due_at == now
    assert result.schedule_id == created.id
    async with database.transaction() as transaction:
        row = await invocations.get(invocation_id=result.id, transaction=transaction)
    assert row is not None
    assert row.status == "pending"


async def test_trigger_of_a_disabled_schedule_raises_without_a_write(
    harness: TriggerHarnessDAO,
) -> None:
    """A5: a disabled schedule raises ScheduleInvalidError; no invocation row."""
    service: ScheduleService = harness.service
    invocations: ScheduleInvocationRepository = harness.invocations
    database: ScheduleDatabase = harness.database
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    await service.stop(reference=str(created.id), now=now)

    with pytest.raises(ScheduleInvalidError):
        await service.trigger_now(reference=str(created.id), now=now)

    async with database.transaction() as transaction:
        rows: list[ScheduleInvocationDAO] = await invocations.list_pending(limit=10, transaction=transaction)
    assert rows == []


async def test_cli_trigger_of_a_disabled_schedule_prints_a_safe_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A5: the mounted CLI trigger of a disabled schedule exits 1 with a safe
    diagnostic and writes no invocation row (FRR111-05)."""
    from typer.testing import CliRunner

    from src.cli.app import app

    monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
    runner = CliRunner()
    add = await asyncio.to_thread(
        runner.invoke,
        app,
        [
            "schedule",
            "add",
            "--name",
            "Disabled trigger",
            "--prompt",
            "Summarise the repo",
            "--interval-seconds",
            "60",
        ],
    )
    assert add.exit_code == 0, add.output
    stop = await asyncio.to_thread(runner.invoke, app, ["schedule", "stop", "--schedule", "Disabled trigger"])
    assert stop.exit_code == 0, stop.output

    trigger = await asyncio.to_thread(
        runner.invoke, app, ["schedule", "trigger", "--schedule", "Disabled trigger"]
    )

    assert trigger.exit_code == 1, trigger.output
    assert isinstance(trigger.exception, SystemExit), "a domain refusal, not an uncaught error"
    assert trigger.output.strip() != "", "the diagnostic must be printed"
    assert "disabled" in trigger.output.lower()
    assert "Traceback" not in trigger.output
    assert "ScheduleInvalidError" not in trigger.output

    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    async with database.transaction() as transaction:
        rows: list[ScheduleInvocationDAO] = await ScheduleInvocationRepository().list_pending(
            limit=10, transaction=transaction
        )
    await database.close()
    assert rows == [], "no invocation row is written"


async def test_trigger_of_an_unknown_reference_raises(
    harness: TriggerHarnessDAO,
) -> None:
    """A5: an unknown reference raises ScheduleNotFoundError."""
    service: ScheduleService = harness.service
    now: datetime = _utc()
    with pytest.raises(ScheduleNotFoundError):
        await service.trigger_now(reference="ghost", now=now)


async def test_trigger_conflict_returns_the_existing_row(
    harness: TriggerHarnessDAO,
) -> None:
    """A5: a tick row at the same millisecond is returned, not a second row."""
    service: ScheduleService = harness.service
    invocations: ScheduleInvocationRepository = harness.invocations
    database: ScheduleDatabase = harness.database
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    first = await service.trigger_now(reference=str(created.id), now=now)

    second = await service.trigger_now(reference=str(created.id), now=now)

    assert second.id == first.id
    async with database.transaction() as transaction:
        rows: list[ScheduleInvocationDAO] = await invocations.list_pending(limit=10, transaction=transaction)
    assert len(rows) == 1


async def test_trigger_works_without_the_engine(
    harness: TriggerHarnessDAO,
) -> None:
    """A5: trigger_now does not enqueue; the next tick picks the row up."""
    service: ScheduleService = harness.service
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)

    result = await service.trigger_now(reference=str(created.id), now=now)

    assert isinstance(result.id, UUID)
    assert result.status == "pending"


async def test_trigger_then_tick_delivers_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A5 / B9: the mounted CLI trigger of a far-future interval schedule stores
    one pending row at now; the tick hands exactly that row to the recording
    queue; delivery stores exactly one channel row with that id; a repeat
    trigger in the same millisecond returns the same row."""
    from typer.testing import CliRunner

    from src.cli.app import app
    from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
    from src.schedules.tick_app_service import ScheduleTickAppService

    session_id: str = "9f0e8d7c-6b5a-4f3e-2d1c-0b9a8f7e6d5c"
    schedules_db: ScheduleDatabase = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    schedules: ScheduleRepository = ScheduleRepository()
    invocations: ScheduleInvocationRepository = ScheduleInvocationRepository()
    service: ScheduleService = ScheduleService(
        database=schedules_db,
        schedules=schedules,
        invocations=invocations,
        session_history=None,
    )
    gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(session_id), name="slo target", durable_inbox=True)
    queue: RecordingInvocationQueue = RecordingInvocationQueue()
    try:
        created = await service.create(
            new_schedule=NewScheduleDAO(
                name="Journey Summary",
                prompt="Summarise the repo",
                trigger=IntervalTriggerDAO(every_seconds=86400),
                session_mode="continuous",
                session_reference=session_id,
            ),
            now=datetime.now(timezone.utc),
        )
        monkeypatch.setenv("SLO_SCHEDULES_DIR", str(tmp_path))
        trigger = await asyncio.to_thread(
            CliRunner().invoke, app, ["schedule", "trigger", "--schedule", "Journey Summary"]
        )
        assert trigger.exit_code == 0, trigger.output
        invocation_id: UUID = UUID(trigger.output.strip().splitlines()[-1])

        async with schedules_db.transaction() as transaction:
            pending: list[ScheduleInvocationDAO] = await invocations.list_pending(
                limit=10, transaction=transaction
            )
        assert [row.id for row in pending] == [invocation_id]
        invocation: ScheduleInvocationDAO = pending[0]
        assert invocation.schedule_id == created.id
        repeat: ScheduleInvocationDAO = await service.trigger_now(
            reference=str(created.id), now=invocation.due_at
        )
        assert repeat.id == invocation_id, "same millisecond returns the stored row"

        tick: ScheduleTickAppService = ScheduleTickAppService(
            database=schedules_db,
            schedules=schedules,
            schedule_service=service,
            invocations=invocations,
            queue=queue,
            reconciler=InvocationOutcomeReconciler(
                database=schedules_db, gateway=gateway, invocations=invocations
            ),
        )
        tick_result = await tick.invoke(now=invocation.due_at, batch_limit=10)
        assert tick_result.created_count == 0, "the far-future schedule is not due"
        assert queue.calls == [(invocation_id, created.id)]

        deliver: DeliverScheduleInvocationAppService = DeliverScheduleInvocationAppService(
            database=schedules_db,
            schedules=service,
            invocations=invocations,
            sender=ScheduleChannelSender(gateway=gateway),
            fresh_runs=ScriptedFreshRunner(),
            now_provider=_utc,
        )
        for queued_invocation_id, _ in queue.calls:
            delivered: ScheduleInvocationDAO = await deliver.invoke(
                invocation_id=queued_invocation_id, now=invocation.due_at
            )
            assert delivered.status == "delivered"
            assert delivered.channel_message_id == invocation_id
        rows = await gateway.pending_inbound(
            recipient_id=channel_participant_id_for_session(session_id=session_id)
        )
        assert [row.id for row in rows] == [invocation_id]
    finally:
        await gateway.close()
        await schedules_db.close()
