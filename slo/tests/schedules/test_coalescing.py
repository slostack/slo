"""Coalescing tests (111.a.4 A6/A7, T4.4) on real SQLite and channels."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.schedules.channel_delivery import ScheduleChannelSender
from src.schedules.deliver_app_service import DeliverScheduleInvocationAppService
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


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


def _interval_input(*, mode: str, key: str | None = None) -> NewScheduleDAO:
    """Build a continuous interval schedule with the requested coalescing mode."""
    return NewScheduleDAO(
        name="Coalescing Probe",
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
        session_mode="continuous",
        session_reference=_SESSION_ID,
        coalescing_mode=mode,  # type: ignore[arg-type]
        coalescing_key=key,
    )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    """Build the real deliver + reconciler stack on tmp_path databases."""
    database = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    schedules = ScheduleRepository()
    invocations = ScheduleInvocationRepository()
    service = ScheduleService(
        database=database,
        schedules=schedules,
        invocations=invocations,
        session_history=None,
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
    reconciler = InvocationOutcomeReconciler(
        database=database,
        gateway=gateway,
        invocations=invocations,
    )
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    built: dict[str, object] = {
        "database": database,
        "service": service,
        "invocations": invocations,
        "gateway": gateway,
        "deliver": deliver,
        "reconciler": reconciler,
    }
    yield built
    await gateway.close()
    await database.close()


async def _insert_pending(
    harness: dict[str, object], *, schedule_id: UUID, due_at: datetime, now: datetime
) -> UUID:
    """Insert one pending invocation row and return its id."""
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
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


async def test_newer_invocation_supersedes_older_pending_row_with_same_key(
    harness: dict[str, object],
) -> None:
    """A6: a newer pending row with the same key cancels the older one as superseded."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(mode="latest_by_key", key="nightly"), now=now)
    first_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    second_id: UUID = await _insert_pending(
        harness, schedule_id=created.id, due_at=now + timedelta(minutes=1), now=now
    )

    await deliver.invoke(invocation_id=first_id, now=now)
    await deliver.invoke(invocation_id=second_id, now=now)
    await reconciler.reconcile(now=now, limit=50)

    invocations_repo: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    async with harness["database"].transaction() as transaction:  # type: ignore[attr-defined]
        first = await invocations_repo.get(invocation_id=first_id, transaction=transaction)
        second = await invocations_repo.get(invocation_id=second_id, transaction=transaction)
    assert first is not None and second is not None
    assert first.status == "delivered"
    assert second.status == "delivered"
    assert first.cancelled_at is not None
    assert first.cancel_reason == "superseded"
    assert second.cancelled_at is None
    pending: list[ChannelMessageDAO] = await gateway.list_pending_inbound_messages(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 1


async def test_no_supersede_without_key_or_after_acceptance(
    harness: dict[str, object],
) -> None:
    """A7: no supersede without a key; an accepted row is never superseded."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(mode="none"), now=now)
    first_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    second_id: UUID = await _insert_pending(
        harness, schedule_id=created.id, due_at=now + timedelta(minutes=1), now=now
    )

    await deliver.invoke(invocation_id=first_id, now=now)
    await deliver.invoke(invocation_id=second_id, now=now)

    invocations_repo: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    async with harness["database"].transaction() as transaction:  # type: ignore[attr-defined]
        first = await invocations_repo.get(invocation_id=first_id, transaction=transaction)
        second = await invocations_repo.get(invocation_id=second_id, transaction=transaction)
    assert first is not None and second is not None
    assert first.status == "delivered"
    assert second.status == "delivered"
    assert first.cancelled_at is None
    assert second.cancelled_at is None
    pending: list[ChannelMessageDAO] = await gateway.list_pending_inbound_messages(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert len(pending) == 2


async def test_accepted_row_is_never_superseded_even_with_a_key(
    harness: dict[str, object],
) -> None:
    """A7: an accepted row is never superseded, even when a newer row has the same key."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    deliver: DeliverScheduleInvocationAppService = harness["deliver"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    now: datetime = _utc()
    created = await service.create(new_schedule=_interval_input(mode="latest_by_key", key="nightly"), now=now)
    first_id: UUID = await _insert_pending(harness, schedule_id=created.id, due_at=now, now=now)
    second_id: UUID = await _insert_pending(
        harness, schedule_id=created.id, due_at=now + timedelta(minutes=1), now=now
    )

    await deliver.invoke(invocation_id=first_id, now=now)
    # The channel row must be accepted before the second delivery.
    invocations_repo: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    async with harness["database"].transaction() as transaction:  # type: ignore[attr-defined]
        first = await invocations_repo.get(invocation_id=first_id, transaction=transaction)
    assert first is not None and first.channel_message_id is not None
    accepted: bool = await gateway.accept(message_id=first.channel_message_id)
    assert accepted is True
    await deliver.invoke(invocation_id=second_id, now=now)

    async with harness["database"].transaction() as transaction:  # type: ignore[attr-defined]
        first = await invocations_repo.get(invocation_id=first_id, transaction=transaction)
        second = await invocations_repo.get(invocation_id=second_id, transaction=transaction)
    assert first is not None and second is not None
    assert first.status == "delivered"
    assert second.status == "delivered"
    assert first.cancelled_at is None
    assert second.cancelled_at is None
