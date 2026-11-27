"""Deliver tests (111.a.2 A4/A5/A17/A18, T2.3) on real SQLite and channels."""

import ast
import asyncio
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
    DeliveryDecisionDAO,
    IntervalTriggerDAO,
    NewScheduleDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.schedules.channel_delivery import SCHEDULER_CHANNEL_ID, ScheduleChannelSender

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


class ScriptedFreshRunner:
    """Records start calls and returns a configured exit code for run decisions."""

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


class DeliverHarnessDAO(BaseModel):
    """The typed collaborator set one deliver test owns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    database: ScheduleDatabase = Field(description="The real tmp schedules database.")
    service: ScheduleService = Field(description="The schedule service over the tmp database.")
    invocations: ScheduleInvocationRepository = Field(
        description="The invocation repository the services share."
    )
    gateway: ChannelGateway = Field(description="The opened real channel gateway on a tmp store.")
    sender: ScheduleChannelSender = Field(description="The real channel sender over the gateway.")
    fresh_runs: ScriptedFreshRunner = Field(
        description="The scripted fresh-run starter the deliver service uses."
    )
    deliver: DeliverScheduleInvocationAppService = Field(description="The deliver service under test.")
    channels_db_path: Path = Field(description="The tmp channels database file, for read-back.")

    async def close(self) -> None:
        """Close the gateway and the schedules database in order."""
        await self.gateway.close()
        await self.database.close()

    def channel_message_count(self) -> int:
        """Count every stored channel message row through a read-only connection.

        Returns:
            int: The number of rows in ``channels.db``'s ``messages`` table.
        """
        connection: sqlite3.Connection = sqlite3.connect(f"file:{self.channels_db_path}?mode=ro", uri=True)
        try:
            return int(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        finally:
            connection.close()


def _utc() -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=12, minute=0, tzinfo=timezone.utc)


def _interval_input(name: str = "Daily Summary") -> NewScheduleDAO:
    """Build a valid continuous interval schedule input."""
    return NewScheduleDAO(
        name=name,
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
        session_mode="continuous",
        session_reference=_SESSION_ID,
    )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[DeliverHarnessDAO]:
    """Build a real deliver service on tmp_path databases and session history."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    schedules = ScheduleRepository()
    invocations = ScheduleInvocationRepository()
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    service = ScheduleService(
        database=database,
        schedules=schedules,
        invocations=invocations,
        session_history=history,
    )
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    sender = ScheduleChannelSender(gateway=gateway)
    fresh_runs = ScriptedFreshRunner()
    deliver = DeliverScheduleInvocationAppService(
        database=database,
        schedules=service,
        invocations=invocations,
        sender=sender,
        fresh_runs=fresh_runs,
        now_provider=_utc,
    )
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    await history.ensure_session(
        session_id=_SESSION_ID,
        workdir=tmp_path,
        model_name=None,
    )
    await history.rename_session(session_id=_SESSION_ID, session_name="target")
    built: DeliverHarnessDAO = DeliverHarnessDAO(
        database=database,
        service=service,
        invocations=invocations,
        gateway=gateway,
        sender=sender,
        fresh_runs=fresh_runs,
        deliver=deliver,
        channels_db_path=tmp_path / "channels.db",
    )
    yield built
    await built.close()


async def _insert_pending(
    harness: DeliverHarnessDAO, *, schedule_id: UUID, due_at: datetime, now: datetime
) -> UUID:
    """Insert one pending invocation row and return its id."""
    invocations: ScheduleInvocationRepository = harness.invocations
    database: ScheduleDatabase = harness.database
    invocation_id: UUID = uuid4()
    async with database.transaction() as transaction:
        await invocations.insert_pending(
            invocation=ScheduleInvocationDAO(
                id=invocation_id,
                schedule_id=schedule_id,
                due_at=due_at,
                status="pending",
                created_at=now,
            ),
            transaction=transaction,
        )
    return invocation_id


def test_deliver_service_never_reads_the_wall_clock() -> None:
    """111.a.2 rule: the worker passes ``now`` into every call; the service never reads the clock."""
    source: str = Path("src/schedules/deliver_app_service.py").read_text(encoding="utf-8")
    module: ast.Module = ast.parse(source)
    calls: list[str] = [
        ast.unparse(call.func)
        for call in ast.walk(module)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]
    forbidden: set[str] = {"datetime.now", "datetime.utcnow", "datetime.today"}
    assert not forbidden.intersection(calls), f"clock reads found: {sorted(forbidden.intersection(calls))}"


async def test_deliver_sends_the_prompt_and_marks_delivered(
    harness: DeliverHarnessDAO,
) -> None:
    """A4: a resolved continuous reference sends one prompt row and marks delivered."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "delivered"
    assert result.channel_message_id == invocation_id
    assert result.delivered_at == now
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 1
    assert pending[0].id == invocation_id
    assert pending[0].message_contents == "Summarise the repo"


async def test_deliver_is_replayed_without_a_second_send(
    harness: DeliverHarnessDAO,
) -> None:
    """A4: a non-pending invocation returns the stored row and sends nothing."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    await deliver.invoke(invocation_id=invocation_id, now=now)

    replayed = await deliver.invoke(invocation_id=invocation_id, now=now + timedelta(seconds=1))

    assert replayed.status == "delivered"
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 1


async def test_crash_recovery_marks_delivered_without_a_second_send(
    harness: DeliverHarnessDAO,
) -> None:
    """A5: a channel row from an interrupted send marks the invocation delivered."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    sender: ScheduleChannelSender = harness.sender
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    # The send happened, but the mark did not: the channel row already exists.
    await sender.send(schedule=created, invocation_id=invocation_id, recipient_session_id=_SESSION_ID)

    result = await deliver.invoke(invocation_id=invocation_id, now=now + timedelta(seconds=1))

    assert result.status == "delivered"
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 1


async def test_disabled_schedule_is_skipped_without_a_channel_row(
    harness: DeliverHarnessDAO,
) -> None:
    """A4: a disabled schedule's invocation is skipped with schedule_disabled."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    await service.stop(reference=str(created.id), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "skipped"
    assert result.skip_reason == "schedule_disabled"
    assert result.channel_message_id is None
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 0


async def test_deleted_schedule_is_skipped_without_a_channel_row(
    harness: DeliverHarnessDAO,
) -> None:
    """A4: a deleted schedule's invocation is skipped with schedule_deleted."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    await service.delete(reference=str(created.id), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "skipped"
    assert result.skip_reason == "schedule_deleted"


async def test_fresh_session_mode_starts_a_fresh_run(
    harness: DeliverHarnessDAO,
) -> None:
    """A3: a fresh schedule's invocation starts one fresh headless run."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    fresh_runs: ScriptedFreshRunner = harness.fresh_runs
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Fresh Run",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            session_mode="fresh",
        ),
        now=now,
    )
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "completed"
    assert result.run_exit_code == 0
    assert len(fresh_runs.calls) == 1
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 0


async def test_continuous_without_reference_starts_a_fresh_run(
    harness: DeliverHarnessDAO,
) -> None:
    """A7: a continuous schedule with no session_reference is treated as fresh."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    fresh_runs: ScriptedFreshRunner = harness.fresh_runs
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="No Reference",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            session_mode="continuous",
        ),
        now=now,
    )
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "completed"
    assert len(fresh_runs.calls) == 1


async def test_unknown_session_reference_fails_without_a_channel_row(
    harness: DeliverHarnessDAO,
) -> None:
    """A4: a reference with a space fails with unknown_session_reference."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now: datetime = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Bad Reference",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            session_mode="continuous",
            session_reference="not a session",
        ),
        now=now,
    )
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "failed"
    assert result.failure_reason == "unknown_session_reference"
    pending = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 0


_REFUSED_SESSION: str = "fedcba98-7654-3210-fedc-ba9876543210"


async def _register_nothing(*, gateway: ChannelGateway) -> None:
    """Leave the recipient unregistered: it never joined the channel.

    Args:
        gateway (ChannelGateway): The real gateway (untouched).
    """
    return None


async def _register_closed_noninteractive(*, gateway: ChannelGateway) -> None:
    """Register the recipient as a non-durable (non-interactive) agent, then close it.

    Args:
        gateway (ChannelGateway): The real gateway.
    """
    await gateway.register_agent(
        session_id=UUID(_REFUSED_SESSION), name="finished child", durable_inbox=False
    )
    await gateway.close_agent(session_id=UUID(_REFUSED_SESSION), reason="session_closed")


@pytest.mark.parametrize(
    ("prepare_recipient", "expected_reason"),
    [
        (_register_nothing, "unknown_recipient"),
        (_register_closed_noninteractive, "recipient_closed"),
    ],
    ids=["unknown_recipient", "recipient_closed"],
)
async def test_refused_delivery_ends_failed_without_retry(
    harness: DeliverHarnessDAO,
    prepare_recipient: Callable[..., Awaitable[None]],
    expected_reason: str,
) -> None:
    """TDD-A4 (FRR111-05): a never-registered recipient and a closed
    non-interactive recipient each refuse the send. Invoked twice: the row is
    failed with that reason, no channel row is ever stored, and the second
    invoke neither resends nor changes the reason or any other column."""
    await prepare_recipient(gateway=harness.gateway)
    now: datetime = _utc()
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="Refused target",
            prompt="Summarise the repo",
            trigger=IntervalTriggerDAO(every_seconds=60),
            session_mode="continuous",
            session_reference=_REFUSED_SESSION,
        ),
        now=now,
    )
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    first: ScheduleInvocationDAO = await harness.deliver.invoke(invocation_id=invocation_id, now=now)
    messages_after_first: int = harness.channel_message_count()
    second: ScheduleInvocationDAO = await harness.deliver.invoke(
        invocation_id=invocation_id, now=now + timedelta(minutes=5)
    )

    assert first.status == "failed"
    assert first.failure_reason == expected_reason
    assert first.channel_message_id is None
    assert messages_after_first == 0, "a refused send stores no channel row"
    assert second == first, "the replay returns the stored row unchanged"
    assert harness.channel_message_count() == 0, "the replay does not resend"
    async with harness.database.transaction() as transaction:
        stored: ScheduleInvocationDAO | None = await harness.invocations.get(
            invocation_id=invocation_id, transaction=transaction
        )
    assert stored == first
    assert harness.fresh_runs.calls == [], "a refused continuous delivery never falls back to a fresh run"


class GatedScheduleService(ScheduleService):
    """ScheduleService double whose first decide_delivery call parks on a gate.

    The gate parks the race loser after its channel check and before its
    guarded status write, so the winner can finalise the row first — the exact
    interleaving the replay guard must survive.
    """

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleRepository,
        invocations: ScheduleInvocationRepository,
        session_history: FilesystemSessionHistoryStore,
    ) -> None:
        """Build the real service and the race gate.

        Args:
            database (ScheduleDatabase): The shared schedules database.
            schedules (ScheduleRepository): The schedule row repository.
            invocations (ScheduleInvocationRepository): The invocation repository.
            session_history (FilesystemSessionHistoryStore): The real history store.
        """
        super().__init__(
            database=database,
            schedules=schedules,
            invocations=invocations,
            session_history=session_history,
        )
        self.gate: asyncio.Event = asyncio.Event()
        self.decide_calls: int = 0

    async def decide_delivery(
        self, *, invocation: ScheduleInvocationDAO, now: datetime
    ) -> DeliveryDecisionDAO:
        """Park the first call on the gate, then decide as the real service does."""
        self.decide_calls += 1
        if self.decide_calls == 1:
            await self.gate.wait()
        return await super().decide_delivery(invocation=invocation, now=now)


class RaceHarnessDAO(BaseModel):
    """The typed collaborator set one delivery-race test owns."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    database: ScheduleDatabase = Field(description="The real tmp schedules database.")
    gateway: ChannelGateway = Field(description="The opened real channel gateway on a tmp store.")
    gated_service: GatedScheduleService = Field(
        description="The schedule service whose first decision waits on its gate."
    )
    plain_service: ScheduleService = Field(
        description="The ungated schedule service the winning delivery uses."
    )
    loser: DeliverScheduleInvocationAppService = Field(
        description="The deliver service parked on the gate; it loses the race."
    )
    winner: DeliverScheduleInvocationAppService = Field(
        description="The deliver service that settles the invocation first."
    )
    fresh_runs: ScriptedFreshRunner = Field(
        description="The scripted fresh-run starter the deliver service uses."
    )

    async def close(self) -> None:
        """Close the gateway and the schedules database in order."""
        await self.gateway.close()
        await self.database.close()


@pytest.fixture
async def race_harness(tmp_path: Path) -> AsyncIterator[RaceHarnessDAO]:
    """Two deliver services over one database: a gated loser and a free winner."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    invocations = ScheduleInvocationRepository()
    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    gated_service = GatedScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=invocations,
        session_history=history,
    )
    plain_service = ScheduleService(
        database=database,
        schedules=ScheduleRepository(),
        invocations=invocations,
        session_history=history,
    )
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    sender = ScheduleChannelSender(gateway=gateway)
    fresh_runs = ScriptedFreshRunner()
    loser = DeliverScheduleInvocationAppService(
        database=database,
        schedules=gated_service,
        invocations=invocations,
        sender=sender,
        fresh_runs=fresh_runs,
        now_provider=_utc,
    )
    winner = DeliverScheduleInvocationAppService(
        database=database,
        schedules=plain_service,
        invocations=invocations,
        sender=sender,
        fresh_runs=fresh_runs,
        now_provider=_utc,
    )
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    await history.ensure_session(session_id=_SESSION_ID, workdir=tmp_path, model_name=None)
    await history.rename_session(session_id=_SESSION_ID, session_name="target")
    built: RaceHarnessDAO = RaceHarnessDAO(
        database=database,
        gateway=gateway,
        gated_service=gated_service,
        plain_service=plain_service,
        loser=loser,
        winner=winner,
        fresh_runs=fresh_runs,
    )
    yield built
    await built.close()


async def _race_pending_invocation(
    race_harness: RaceHarnessDAO, *, session_reference: str | None = _SESSION_ID
) -> UUID:
    """Create one continuous schedule and pending invocation for the race."""
    plain_service: ScheduleService = race_harness.plain_service
    now = _utc()
    created = await plain_service.create(
        new_schedule=NewScheduleDAO(
            name="Race target",
            prompt="race prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=session_reference,
        ),
        now=now,
    )
    invocation = await plain_service.trigger_now(reference=str(created.id), now=now)
    return invocation.id


async def _run_delivery_race(
    race_harness: RaceHarnessDAO, *, invocation_id: UUID
) -> tuple[ScheduleInvocationDAO, ScheduleInvocationDAO]:
    """Run the gated loser against the free winner and return both rows."""
    loser: DeliverScheduleInvocationAppService = race_harness.loser
    winner: DeliverScheduleInvocationAppService = race_harness.winner
    gated_service: GatedScheduleService = race_harness.gated_service
    loser_task = asyncio.create_task(loser.invoke(invocation_id=invocation_id, now=_utc()))
    for _ in range(500):
        if gated_service.decide_calls == 1:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("the loser never reached its delivery decision")
    winner_row = await winner.invoke(invocation_id=invocation_id, now=_utc())
    gated_service.gate.set()
    loser_row = await asyncio.wait_for(loser_task, timeout=10)
    return loser_row, winner_row


@pytest.mark.parametrize(
    "session_reference",
    [_SESSION_ID, "disabled target", "unknown reference with spaces"],
)
async def test_race_loser_returns_the_stored_row_without_deadlock(
    race_harness: RaceHarnessDAO, *, session_reference: str
) -> None:
    """FIR111-02: the replay guard reads the stored row on the transaction it
    already owns; the loser finishes bounded and the database stays usable."""
    plain_service: ScheduleService = race_harness.plain_service
    database: ScheduleDatabase = race_harness.database
    invocation_id = await _race_pending_invocation(race_harness, session_reference=session_reference)
    if session_reference != _SESSION_ID:
        await plain_service.stop(reference="Race target", now=_utc())

    loser_row, winner_row = await _run_delivery_race(race_harness, invocation_id=invocation_id)

    assert winner_row.status in {"delivered", "skipped", "failed", "completed"}
    assert loser_row.id == winner_row.id
    assert loser_row.status == winner_row.status
    async with database.transaction() as transaction:
        reloaded = await ScheduleInvocationRepository().get(
            invocation_id=invocation_id, transaction=transaction
        )
    assert reloaded is not None and reloaded.status == winner_row.status


async def test_race_loser_of_a_run_decision_returns_the_stored_row(
    race_harness: RaceHarnessDAO,
) -> None:
    """FIR111-02 (running branch): the loser of a run replay returns the
    stored finished row; the child never starts a second time."""
    fresh_runs: ScriptedFreshRunner = race_harness.fresh_runs
    invocation_id = await _race_pending_invocation(race_harness, session_reference=None)

    loser_row, winner_row = await _run_delivery_race(race_harness, invocation_id=invocation_id)

    assert winner_row.status == "completed"
    assert loser_row.status == "completed"
    assert loser_row.id == winner_row.id
    assert len(fresh_runs.calls) == 1, "one run for the due time, not two"


async def test_session_name_resolves_to_session_id_before_send(
    harness: DeliverHarnessDAO,
) -> None:
    """TDD-A12 (2): a unique session name stored in the history store resolves
    to the session id and the send goes to the resolved session."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    now = _utc()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Name resolved target",
            prompt="name resolution prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference="target",
        ),
        now=now,
    )
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)

    result = await deliver.invoke(invocation_id=invocation_id, now=now)

    assert result.status == "delivered"
    assert result.recipient_session_id == _SESSION_ID
    rows = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(rows) == 1
    assert rows[0].message_contents == "name resolution prompt"


async def test_late_redelivery_after_crash_marks_delivered_not_misfire(
    harness: DeliverHarnessDAO,
) -> None:
    """TDD-A14 / GRD-A11: a send that stored the channel row before a crash is
    recorded delivered even when the clock has moved past the grace period."""
    service: ScheduleService = harness.service
    deliver: DeliverScheduleInvocationAppService = harness.deliver
    gateway: ChannelGateway = harness.gateway
    sender: ScheduleChannelSender = harness.sender
    now = _utc()
    created = await service.create(new_schedule=_interval_input(), now=now)
    invocation_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    await sender.send(schedule=created, invocation_id=invocation_id, recipient_session_id=_SESSION_ID)

    # The clock moves far past the grace period (300 s default) before redelivery.
    late_now = now + timedelta(seconds=600)
    result = await deliver.invoke(invocation_id=invocation_id, now=late_now)

    assert result.status == "delivered"
    assert result.skip_reason is None
    assert result.channel_message_id == invocation_id
    rows = await gateway.pending_inbound(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(rows) == 1, "no second channel row for the crashed send"


async def test_each_schedule_has_one_system_sender(harness: DeliverHarnessDAO) -> None:
    """TDD-A18: each schedule owns exactly one system participant with its own
    external_ref and name; a second send reuses it and adds none."""
    service: ScheduleService = harness.service
    sender: ScheduleChannelSender = harness.sender
    now = _utc()
    first = await service.create(
        new_schedule=NewScheduleDAO(
            name="First sender",
            prompt="first prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    second = await service.create(
        new_schedule=NewScheduleDAO(
            name="Second sender",
            prompt="second prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )

    await sender.send(schedule=first, invocation_id=uuid4(), recipient_session_id=_SESSION_ID)
    await sender.send(schedule=second, invocation_id=uuid4(), recipient_session_id=_SESSION_ID)
    await sender.send(schedule=first, invocation_id=uuid4(), recipient_session_id=_SESSION_ID)

    gateway: ChannelGateway = harness.gateway
    repository = gateway.repository
    first_participant = await repository.participant_by_external_ref(
        channel_id=SCHEDULER_CHANNEL_ID, external_ref=str(first.id)
    )
    second_participant = await repository.participant_by_external_ref(
        channel_id=SCHEDULER_CHANNEL_ID, external_ref=str(second.id)
    )
    assert first_participant is not None
    assert second_participant is not None
    assert first_participant.id != second_participant.id
    assert first_participant.name == "scheduler First sender"
    assert second_participant.name == "scheduler Second sender"
    assert first_participant.kind == "system"
