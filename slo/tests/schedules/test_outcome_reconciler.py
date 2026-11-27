"""Outcome reconciler tests (111.a.2 A9–A14, T2.5) on real SQLite and channels."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
    IntervalTriggerDAO,
    NewScheduleDAO,
    ScheduleInvocationDAO,
)
from src.schedules.database import ScheduleDatabase
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.outcome_reconciler import InvocationOutcomeReconciler
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.schedules.channel_delivery import SCHEDULER_CHANNEL_ID, ScheduleChannelSender

_SESSION_ID: str = "01234567-89ab-cdef-0123-456789abcdef"


def _utc() -> datetime:
    """Build a fixed aware UTC instant."""
    return datetime(2026, 1, 1, hour=12, tzinfo=timezone.utc)


def _interval_input() -> NewScheduleDAO:
    """Build a valid continuous interval schedule input."""
    return NewScheduleDAO(
        name="Daily Summary",
        prompt="Summarise the repo",
        trigger=IntervalTriggerDAO(every_seconds=60),
        session_mode="continuous",
        session_reference=_SESSION_ID,
    )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[dict[str, object]]:
    """Build a real reconciler on tmp_path databases with a registered session."""
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
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    sender = ScheduleChannelSender(gateway=gateway)
    reconciler = InvocationOutcomeReconciler(
        database=database,
        gateway=gateway,
        invocations=invocations,
    )
    built: dict[str, object] = {
        "database": database,
        "service": service,
        "invocations": invocations,
        "gateway": gateway,
        "sender": sender,
        "reconciler": reconciler,
    }
    yield built
    await gateway.close()
    await database.close()


async def _insert_delivered(
    harness: dict[str, object], *, now: datetime, send: bool = True
) -> ScheduleInvocationDAO:
    """Create one continuous schedule, deliver its invocation, and return the row."""
    service: ScheduleService = harness["service"]  # type: ignore[assignment]
    sender: ScheduleChannelSender = harness["sender"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    created = await service.create(new_schedule=_interval_input(), now=now)
    invocation_id: UUID = uuid4()
    async with database.transaction() as transaction:
        await invocations.insert_pending(
            invocation=ScheduleInvocationDAO(
                id=invocation_id,
                schedule_id=created.id,
                due_at=now,
                status="pending",
                created_at=now,
            ),
            transaction=transaction,
        )
    if send:
        await sender.send(
            schedule=created,
            invocation_id=invocation_id,
            recipient_session_id=_SESSION_ID,
        )
    async with database.transaction() as transaction:
        await invocations.mark_delivered(
            invocation_id=invocation_id,
            channel_message_id=invocation_id,
            delivered_at=now,
            recipient_session_id=_SESSION_ID,
            transaction=transaction,
        )
        row = await invocations.get(invocation_id=invocation_id, transaction=transaction)
    assert row is not None
    return row


async def test_acceptance_time_is_copied_onto_the_invocation_row(
    harness: dict[str, object],
) -> None:
    """A9: the reconciler copies accepted_at from the channel row onto the invocation."""
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    row = await _insert_delivered(harness, now=now)
    assert row.accepted_at is None
    accepted: bool = await gateway.accept(message_id=row.id)
    assert accepted is True

    reconciled: int = await reconciler.reconcile(now=now, limit=50)

    assert reconciled == 1
    async with database.transaction() as transaction:
        updated = await invocations.get(invocation_id=row.id, transaction=transaction)
    assert updated is not None
    assert updated.accepted_at is not None
    assert updated.outcome_reconciled_at is not None


async def test_reply_row_is_copied_onto_the_invocation_row(
    harness: dict[str, object],
) -> None:
    """A10: the reconciler copies the reply row id when the agent answers."""
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    row = await _insert_delivered(harness, now=now)
    agent_id: UUID = channel_participant_id_for_session(session_id=_SESSION_ID)
    original: ChannelMessageDAO | None = await gateway.get(message_id=row.id)
    assert original is not None
    reply_id: UUID = uuid4()
    stored: ChannelMessageDAO = await gateway.send(
        new=NewMessageDAO(
            id=reply_id,
            sender_id=agent_id,
            recipient_id=original.sender_id,
            message_contents="Done",
            message_type="reply",
            channel_id=SCHEDULER_CHANNEL_ID,
            in_reply_to_id=row.id,
        )
    )
    assert stored.id == reply_id

    reconciled: int = await reconciler.reconcile(now=now, limit=50)

    assert reconciled == 1
    async with database.transaction() as transaction:
        updated = await invocations.get(invocation_id=row.id, transaction=transaction)
    assert updated is not None
    assert updated.reply_message_id == reply_id


async def test_cancellation_facts_are_copied_onto_the_invocation_row(
    harness: dict[str, object],
) -> None:
    """A11: the reconciler copies cancelled_at and cancel_reason from the channel row."""
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    row = await _insert_delivered(harness, now=now)
    cancelled: bool = await gateway.cancel(message_id=row.id, reason="superseded")
    assert cancelled is True

    reconciled: int = await reconciler.reconcile(now=now, limit=50)

    assert reconciled == 1
    async with database.transaction() as transaction:
        updated = await invocations.get(invocation_id=row.id, transaction=transaction)
    assert updated is not None
    assert updated.cancelled_at is not None
    assert updated.cancel_reason == "superseded"


async def test_missing_channel_row_marks_the_invocation_gone_once(
    harness: dict[str, object],
) -> None:
    """A12: a missing channel row sets channel_row_gone_at once; the row is never read again."""
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    invocations: ScheduleInvocationRepository = harness["invocations"]  # type: ignore[assignment]
    database: ScheduleDatabase = harness["database"]  # type: ignore[assignment]
    now: datetime = _utc()
    # A delivered row whose channel row was pruned (or never stored): the mark
    # happened but the gateway holds no row with this id.
    row = await _insert_delivered(harness, now=now, send=False)

    reconciled: int = await reconciler.reconcile(now=now, limit=50)

    assert reconciled == 1
    async with database.transaction() as transaction:
        updated = await invocations.get(invocation_id=row.id, transaction=transaction)
    assert updated is not None
    assert updated.channel_row_gone_at is not None
    again: int = await reconciler.reconcile(now=now, limit=50)
    assert again == 0


async def test_settled_rows_are_not_selected_again(
    harness: dict[str, object],
) -> None:
    """A14: a delivered row with accepted and reply copied is not selected again."""
    reconciler: InvocationOutcomeReconciler = harness["reconciler"]  # type: ignore[assignment]
    gateway: ChannelGateway = harness["gateway"]  # type: ignore[assignment]
    now: datetime = _utc()
    row = await _insert_delivered(harness, now=now)
    await gateway.accept(message_id=row.id)
    agent_id: UUID = channel_participant_id_for_session(session_id=_SESSION_ID)
    original: ChannelMessageDAO | None = await gateway.get(message_id=row.id)
    assert original is not None
    await gateway.send(
        new=NewMessageDAO(
            id=uuid4(),
            sender_id=agent_id,
            recipient_id=original.sender_id,
            message_contents="Done",
            message_type="reply",
            channel_id=SCHEDULER_CHANNEL_ID,
            in_reply_to_id=row.id,
        )
    )
    first: int = await reconciler.reconcile(now=now, limit=50)
    assert first == 1

    second: int = await reconciler.reconcile(now=now, limit=50)

    assert second == 0
