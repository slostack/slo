"""One-shot end and misfire tests (111.a.4 A4/A5, T4.3)."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase, format_instant
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.channel_delivery import ScheduleChannelSender

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


def _one_shot_input(*, session_reference: str | None = None) -> NewScheduleDAO:
    """Build a one-shot schedule due in one hour."""
    return NewScheduleDAO(
        name="One shot",
        prompt="one shot prompt",
        trigger=OneShotTriggerDAO(run_at=_utc_now() + timedelta(hours=1)),
        session_mode="continuous",
        session_reference=session_reference if session_reference is not None else _SESSION_ID,
    )


class ExplodingScheduleService(ScheduleService):
    """A service double whose ``complete_occurrence`` always raises."""

    async def complete_occurrence(self, *, schedule_id: UUID, now: datetime, transaction: object) -> None:
        """Raise inside the caller's open transaction (forced rollback)."""
        raise RuntimeError("forced schedule write failure")


class ScriptedFreshRunner:
    """Records start calls and returns a completed result for run decisions."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def start(
        self, *, prompt: str, cwd: str | None, model: str | None, session_id: str
    ) -> FreshRunResultDAO:
        """Record one start call and return a completed result."""
        self.calls.append({"prompt": prompt, "cwd": cwd, "model": model, "session_id": session_id})
        return FreshRunResultDAO(session_id=session_id, exit_code=0, status="completed")


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
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
    built: dict[str, object] = {
        "schedules_db": schedules_db,
        "gateway": gateway,
        "service": service,
        "deliver": deliver,
    }
    yield built
    await gateway.close()
    await schedules_db.close()


async def _schedule_and_trigger(
    harness: dict[str, object],
    *,
    service: ScheduleService | None = None,
    now: datetime | None = None,
) -> tuple[UUID, ScheduleInvocationDAO]:
    """Create the one-shot schedule, trigger it and return (schedule id, invocation)."""
    resolved_service: ScheduleService = service if service is not None else harness["service"]  # type: ignore[assignment]
    now = now or _utc_now()
    created = await resolved_service.create(new_schedule=_one_shot_input(), now=now)
    invocation = await resolved_service.trigger_now(reference=str(created.id), now=now)
    return created.id, invocation


async def test_one_shot_disabled_only_with_its_delivery_commit(
    harness: dict[str, object],
) -> None:
    """A4: one-shot delivery and the schedule disable commit together."""
    schedules_db: ScheduleDatabase = harness["schedules_db"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    now = _utc_now()
    schedule_id, invocation = await _schedule_and_trigger(harness, now=now)

    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "delivered"
    row = await service.show(reference=str(schedule_id))
    assert row.enabled is False
    assert row.next_due_at is None


async def test_one_shot_disabled_in_the_same_commit_as_misfire(
    harness: dict[str, object],
) -> None:
    """A5 (deliver-side): a late pending invocation is skipped/misfire and the
    one-shot is disabled in the same commit; no channel row."""
    schedules_db: ScheduleDatabase = harness["schedules_db"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    now = _utc_now().replace(microsecond=0)
    schedule_id, invocation = await _schedule_and_trigger(harness, now=now)

    # Simulate lateness: backdate the invocation's due_at beyond the grace window.
    async with schedules_db.transaction() as transaction:
        await transaction.execute(
            sql="UPDATE schedule_invocations SET due_at = ? WHERE id = ?",
            parameters=(format_instant(value=now - timedelta(seconds=600)), str(invocation.id)),
        )
        await transaction.execute(
            sql="UPDATE schedules SET misfire_grace_seconds = 300 WHERE id = ?",
            parameters=(str(schedule_id),),
        )

    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "skipped"
    assert delivered.skip_reason == "misfire"
    assert delivered.due_at == now - timedelta(seconds=600)
    row = await service.show(reference=str(schedule_id))
    assert row.enabled is False
    assert row.next_due_at is None


async def test_failed_one_shot_is_disabled_with_its_failure(
    harness: dict[str, object],
) -> None:
    """A12 (D19): a failed one-shot delivery disables the schedule in the same
    commit as the failure write."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    now = _utc_now()
    created = await service.create(new_schedule=_one_shot_input(session_reference="has space!"), now=now)
    invocation = await service.trigger_now(reference=str(created.id), now=now)

    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "failed"
    assert delivered.failure_reason == "unknown_session_reference"
    row = await service.show(reference=str(created.id))
    assert row.enabled is False
    assert row.next_due_at is None


async def test_pending_invocation_delayed_beyond_grace_is_skipped(
    harness: dict[str, object],
) -> None:
    """GRD-A2: a pending invocation later than the grace is skipped/misfire;
    no channel row is written and it is never sent."""
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    schedules_db: ScheduleDatabase = harness["schedules_db"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    now = _utc_now()
    created = await service.create(
        new_schedule=NewScheduleDAO(
            name="Late queue target",
            prompt="late queue prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
            session_reference=_SESSION_ID,
        ),
        now=now,
    )
    invocation = await service.trigger_now(reference=str(created.id), now=now)
    async with schedules_db.transaction() as transaction:
        await transaction.execute(
            sql="UPDATE schedule_invocations SET due_at = ? WHERE id = ?",
            parameters=(format_instant(value=now - timedelta(seconds=600)), str(invocation.id)),
        )

    delivered = await deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "skipped"
    assert delivered.skip_reason == "misfire"
    assert await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID)) == []


@pytest.mark.parametrize("late", [False, True])
async def test_forced_schedule_write_failure_rolls_back_the_delivery(
    harness: dict[str, object], *, late: bool
) -> None:
    """GRD-A4/A5: a forced failure of the one-shot end inside the delivery
    transaction rolls the invocation status back too; nothing was sent."""
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    schedules_db: ScheduleDatabase = harness["schedules_db"]  # type: ignore[assignment]
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    now = _utc_now()
    exploding = ExplodingScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    deliver = DeliverScheduleInvocationAppService(
        database=schedules_db,
        schedules=exploding,
        invocations=ScheduleInvocationRepository(),
        sender=ScheduleChannelSender(gateway=gateway),
        fresh_runs=ScriptedFreshRunner(),
        now_provider=_utc_now,
    )
    created = await service.create(new_schedule=_one_shot_input(), now=now)
    invocation = await service.trigger_now(reference=str(created.id), now=now)
    if late:
        async with schedules_db.transaction() as transaction:
            await transaction.execute(
                sql="UPDATE schedule_invocations SET due_at = ? WHERE id = ?",
                parameters=(format_instant(value=now - timedelta(seconds=600)), str(invocation.id)),
            )

    with pytest.raises(RuntimeError, match="forced schedule write failure"):
        await deliver.invoke(invocation_id=invocation.id, now=now)

    async with schedules_db.transaction() as transaction:
        row = await ScheduleInvocationRepository().get(invocation_id=invocation.id, transaction=transaction)
    assert row is not None
    assert row.status == "pending"
    stored = await service.show(reference=str(created.id))
    assert stored.enabled is True
    # The channel write is its own commit: the on-time variant already sent
    # (crash-recovery replays it without a second send); the misfire variant
    # never sends.
    pending_rows = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
    assert len(pending_rows) == (0 if late else 1)
