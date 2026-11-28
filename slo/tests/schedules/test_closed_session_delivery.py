"""Closed-session delivery tests (111.a.3 A1–A2, A7; FIR111-09 replacements).

A1 now closes the participant through the real channel API, delivers into the
durable inbox, remounts the session, and lets a real ``ChannelPoller`` accept
and run the row — the poller/open journey, not a bare ``gateway.accept``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import (
    ChannelPoller,
    channel_participant_id_for_session,
)
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO, TurnRunner
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.schedules.dao import (
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
from src.schedules.channel_delivery import ScheduleChannelSender

_SESSION_ID = "01234567-89ab-cdef-0123-456789abcdef"


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


class RecordingTurnRunner:
    """TurnRunner stub: records accepted rows and reports completion."""

    def __init__(self) -> None:
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Record the message, call ``on_started`` once, report completion.

        Args:
            message (ChannelMessageDAO): The accepted prompt row.
            on_started (Callable[[], Awaitable[None]]): Acceptance callback.

        Returns:
            TurnOutcomeDAO: A completed outcome.
        """
        self.ran.append(message.id)
        await on_started()
        return TurnOutcomeDAO(status="completed", final_text=f"done:{message.message_contents}")


class ClosedSessionHarnessDAO(BaseModel):
    """The typed collaborator set one closed-session test owns."""

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


def _utc_now() -> datetime:
    """Return the current UTC instant."""
    return datetime.now(timezone.utc)


def _continuous_input(name: str = "Closed target") -> NewScheduleDAO:
    """Build a continuous schedule bound to one session id."""
    return NewScheduleDAO(
        name=name,
        prompt="closed session prompt",
        trigger=IntervalTriggerDAO(every_seconds=3600),
        session_mode="continuous",
        session_reference=_SESSION_ID,
    )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[ClosedSessionHarnessDAO]:
    """Real service, gateway and sender on tmp databases; the target session
    starts closed, the way the durable-inbox journey finds it."""
    schedules_db = ScheduleDatabase(db_path=tmp_path / "schedules.db")
    gateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    await gateway.close_agent(session_id=UUID(_SESSION_ID), reason="session_closed")
    sender = ScheduleChannelSender(gateway=gateway)
    fresh_runs = ScriptedFreshRunner()
    service = ScheduleService(
        database=schedules_db,
        schedules=ScheduleRepository(),
        invocations=ScheduleInvocationRepository(),
        session_history=None,
    )
    deliver = DeliverScheduleInvocationAppService(
        database=schedules_db,
        schedules=service,
        invocations=ScheduleInvocationRepository(),
        sender=sender,
        fresh_runs=fresh_runs,
        now_provider=_utc_now,
    )
    built = ClosedSessionHarnessDAO(
        schedules_db=schedules_db,
        gateway=gateway,
        service=service,
        deliver=deliver,
        fresh_runs=fresh_runs,
    )
    yield built
    await built.close()


async def _wait_until(*, predicate: Callable[[], bool], timeout_seconds: float = 10.0) -> None:
    """Poll a predicate until it holds or the timeout expires."""
    async with asyncio.timeout(timeout_seconds):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_closed_interactive_session_keeps_scheduled_prompt_until_it_opens(
    harness: ClosedSessionHarnessDAO, tmp_path: Path
) -> None:
    """A1: the closed durable participant keeps the row; a real poller on the
    remounted session accepts and runs it."""
    gateway = harness.gateway
    now = _utc_now()
    created = await harness.service.create(new_schedule=_continuous_input(), now=now)
    invocation = await harness.service.trigger_now(reference=str(created.id), now=now)
    delivered = await harness.deliver.invoke(invocation_id=invocation.id, now=now)

    participant = channel_participant_id_for_session(session_id=_SESSION_ID)
    pending = await gateway.list_pending_inbound_messages(recipient_id=participant)
    assert len(pending) == 1
    assert pending[0].id == delivered.id
    assert pending[0].accepted_at is None
    assert delivered.status == "delivered"
    assert delivered.recipient_session_id == _SESSION_ID

    # Remount the session: the participant reopens and a real poller serves it.
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo target", durable_inbox=True)
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
        ),
        workdir=tmp_path,
        session_id=_SESSION_ID,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    runner: RecordingTurnRunner = RecordingTurnRunner()
    poller = ChannelPoller(
        gateway=gateway,
        session=session,
        runner=runner,
        replies=ReplyWriter(gateway=gateway),
        boundary_inbox=_boundary_inbox(gateway=gateway, session_id=_SESSION_ID),
        interval=0.02,
    )
    await poller.start()
    try:
        await _wait_until(predicate=lambda: len(runner.ran) == 1)
    finally:
        await poller.stop(reason="test finished")

    pending_after = await gateway.list_pending_inbound_messages(recipient_id=participant)
    assert len(pending_after) == 0
    stored = await gateway.find_message(message_id=delivered.id)
    assert stored is not None
    assert stored.accepted_at is not None


def _boundary_inbox(*, gateway: ChannelGateway, session_id: str) -> ChannelBoundaryInbox:
    """Build the boundary inbox the poller shares with its session."""
    return ChannelBoundaryInbox(
        gateway=gateway,
        agent_id=channel_participant_id_for_session(session_id=session_id),
    )


async def test_closed_session_never_starts_headless_run(
    harness: ClosedSessionHarnessDAO,
) -> None:
    """A2: a closed continuous session never resumes headlessly; the prompt
    waits, exactly one row is stored and no fresh run starts."""
    now = _utc_now()
    created = await harness.service.create(new_schedule=_continuous_input(), now=now)
    invocation = await harness.service.trigger_now(reference=str(created.id), now=now)

    delivered = await harness.deliver.invoke(invocation_id=invocation.id, now=now)

    assert delivered.status == "delivered"
    assert delivered.skip_reason is None
    assert harness.fresh_runs.calls == [], "no headless run for a closed continuous session"
    waiting = await harness.gateway.list_pending_inbound_messages(
        recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
    )
    assert [row.id for row in waiting] == [invocation.id], "exactly one row waits for the session"
    assert waiting[0].accepted_at is None, "nothing accepted the row while the session is closed"


async def test_continuous_without_reference_runs_fresh(
    harness: ClosedSessionHarnessDAO,
) -> None:
    """A7: two fires of ONE continuous schedule with no reference are two fresh
    headless runs with new session ids; no channel row and no seeded wait."""
    fresh_runs = harness.fresh_runs
    gateway = harness.gateway
    now = _utc_now()
    created = await harness.service.create(
        new_schedule=NewScheduleDAO(
            name="No reference",
            prompt="no reference prompt",
            trigger=IntervalTriggerDAO(every_seconds=3600),
            session_mode="continuous",
        ),
        now=now,
    )
    first_invocation = await harness.service.trigger_now(reference=str(created.id), now=now)
    second_invocation = await harness.service.trigger_now(
        reference=str(created.id), now=now + timedelta(milliseconds=1)
    )
    assert first_invocation.id != second_invocation.id

    first = await harness.deliver.invoke(invocation_id=first_invocation.id, now=now)
    second = await harness.deliver.invoke(invocation_id=second_invocation.id, now=now)

    assert first.status == "completed"
    assert second.status == "completed"
    assert len(fresh_runs.calls) == 2
    first_session = fresh_runs.calls[0]["session_id"]
    second_session = fresh_runs.calls[1]["session_id"]
    assert first_session != second_session, "each fire mints a new session id"
    assert first.recipient_session_id == first_session
    assert second.recipient_session_id == second_session
    assert (
        await gateway.list_pending_inbound_messages(
            recipient_id=channel_participant_id_for_session(session_id=_SESSION_ID)
        )
        == []
    )
