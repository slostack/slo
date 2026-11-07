"""Injected-agent messaging activation journeys (96 revised 01.1 acceptance rows A1-A3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from langchain_core.messages import HumanMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAdmissionError,
    MessageErrorDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.integration.test_session_messaging import read_closed_message_rows


def _build_injected_session(
    *, tmp_path: Path, model: FauxChatModel, session_id: str | None = None, agent: SloAgent | None = None
) -> SloAgentSession:
    """Build a real session around a pre-built agent, with contained real history.

    Args:
        tmp_path: Test-owned filesystem root.
        model: Scripted third-party model boundary for the injected agent.

    Returns:
        SloAgentSession: Session whose only replaced collaborator is the provider.
    """
    history_root: Path = tmp_path / "history"
    assert history_root.resolve().is_relative_to(tmp_path.resolve())
    return SloAgentSession(
        agent=agent if agent is not None else SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id or str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=history_root),
        enable_history=True,
    )


async def test_preactivation_subscriber_keeps_worker_through_idle_activation_and_close(
    tmp_path: Path,
) -> None:
    """Activation changes publication, not ownership of an already held legacy callback."""
    session = _build_injected_session(tmp_path=tmp_path, model=FauxChatModel(responses=[]))
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    callbacks: list[tuple[str, asyncio.Task[object] | None]] = []
    delivered = asyncio.Event()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Hold the first callback while later activated publications queue behind it."""
        callbacks.append((event.content or "", asyncio.current_task()))
        if event.content == "legacy":
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
        else:
            delivered.set()

    session.subscribe(handler=observe)

    async def relay_legacy() -> None:
        """Await the public relay through a coroutine owned by this test."""
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="legacy"))

    legacy: asyncio.Task[None] = asyncio.create_task(coro=relay_legacy())
    closing: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(delay=5):
            await entered.wait()
            assert not legacy.done()
            await session.start_messaging()
            assert session.is_messaging_ready and not session.is_running
            await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="messaging"))
            assert not legacy.done() and not delivered.is_set()
            release.set()
            await legacy
            await delivered.wait()
            assert [content for content, _ in callbacks] == ["legacy", "messaging"]
            assert callbacks[0][1] is callbacks[1][1]
            assert not cancelled.is_set()
            store = FilesystemSessionHistoryStore(root=tmp_path / "history")
            await store.ensure_session(session_id=session.session_id, workdir=tmp_path, model_name=None)
            await session.event_relay(AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child"))
            history = await store.load_events(session_id=session.session_id)
            assert sum(event.kind == "sub_agent_spawned" for event in history) == 1
            closing = asyncio.create_task(coro=session.close_messaging())
            await closing
            assert not session.is_running
    finally:
        release.set()
        await asyncio.gather(
            *(task for task in (legacy, closing) if task is not None), return_exceptions=True
        )
        await session.join_unsubscribed(handler=observe)
        await session.close_messaging()


async def test_legacy_relay_cancellation_joins_suppressing_subscriber(tmp_path: Path) -> None:
    """A cancelled legacy caller cannot leave its callback running after delivery exits."""
    session = _build_injected_session(tmp_path=tmp_path, model=FauxChatModel(responses=[]))
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def observe(event: AgentStreamEventDAO) -> None:
        """Retain callback work after the first cancellation until explicitly released."""
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()

    session.subscribe(handler=observe)

    async def relay_legacy() -> None:
        """Await the public relay through a coroutine owned by this test."""
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="legacy"))

    delivery: asyncio.Task[None] = asyncio.create_task(coro=relay_legacy())
    try:
        async with asyncio.timeout(delay=2):
            await entered.wait()
            delivery.cancel()
            await cancelled.wait()
            delivery.cancel()
            await asyncio.sleep(delay=0)
            assert not delivery.done()
            release.set()
            result = await asyncio.gather(delivery, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)
            assert not session.is_running
    finally:
        release.set()
        await asyncio.gather(delivery, return_exceptions=True)
        await session.join_unsubscribed(handler=observe)
        await session.close_messaging()


async def test_legacy_callback_cancellation_stops_relay_after_callback_termination(
    tmp_path: Path,
) -> None:
    """Callback-origin cancellation reaches the legacy caller before later observers."""
    session: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=FauxChatModel(responses=[]))
    entered, release, terminated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    recorded: list[AgentStreamEventDAO] = []

    async def cancel_callback(event: AgentStreamEventDAO) -> None:
        """Raise cancellation independently of any caller or owner cancellation."""
        entered.set()
        try:
            await release.wait()
            raise asyncio.CancelledError()
        finally:
            terminated.set()

    async def record_callback(event: AgentStreamEventDAO) -> None:
        """Record forbidden delivery to the later legacy subscriber."""
        recorded.append(event)

    session.subscribe(handler=cancel_callback)
    session.subscribe(handler=record_callback)

    async def relay_legacy() -> None:
        """Await the public relay through a coroutine owned by this test."""
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", content="legacy"))

    delivery: asyncio.Task[None] = asyncio.create_task(coro=relay_legacy())
    try:
        async with asyncio.timeout(delay=2):
            await entered.wait()
            assert not delivery.done()
            assert not terminated.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await delivery
            assert terminated.is_set()
            assert recorded == []
    finally:
        release.set()
        await asyncio.gather(delivery, return_exceptions=True)
        await session.join_unsubscribed(handler=cancel_callback)
        await session.join_unsubscribed(handler=record_callback)
        await session.close_messaging()


async def test_injected_agent_binds_session_source_and_delivers_once(tmp_path: Path) -> None:
    """A1: explicit start binds the injected agent and one admitted input executes once."""
    model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="scripted answer")]
    )
    model.release.set()
    session: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=model)
    injected: SloAgent | None = session.agent
    assert injected is not None
    await session.start_messaging()
    assert session.agent is injected
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session, target=session.messaging_target, principal=session.messaging_owner_principal
    )
    submission: MessageSubmissionDAO = MessageSubmissionDAO(
        message_id=str(uuid4()),
        target=session.messaging_target,
        kind="agent_input",
        text="hello durable",
    )
    try:
        admission: MessageReceiptDAO | MessageErrorDAO = await client.submit(submission=submission)
        assert isinstance(admission, MessageReceiptDAO)
        assert admission.message_id == submission.message_id
        assert admission.state == "accepted"
        assert session.is_messaging_ready is True
        async with asyncio.timeout(delay=5):
            while not model.requests:
                await asyncio.sleep(delay=0.01)
            while session.is_running:
                await asyncio.sleep(delay=0.01)
    finally:
        await client.close()
        await session.close_messaging()
    # The scripted response was consumed exactly once and the application is durable.
    assert len(model.requests) == 1
    human_texts: list[str] = [
        str(message.content) for message in model.requests[0] if isinstance(message, HumanMessage)
    ]
    assert human_texts == [submission.text]
    assert session.history_store is not None
    events: list[SessionHistoryEventDAO] = await session.history_store.load_events(
        session_id=session.session_id
    )
    messaging_updates: list[SessionHistoryEventDAO] = [
        event for event in events if "messaging_v1" in event.payload.metadata
    ]
    assert len(messaging_updates) == 1
    assert messaging_updates[0].payload.content == "hello durable"
    assert session.is_messaging_ready is False
    # The session, not the client, owns close; the client only detaches.
    assert await client.get_receipt(message_id=submission.message_id) == MessageErrorDAO(
        code="completing", message_id=submission.message_id
    )
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
        read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
    )
    assert rows == ((submission.message_id, 0, "applied"),)
    # A fresh adapter over the closed database confirms the durable applied record.
    store: MessageStore = await MessageStore.open(
        path=database_path,
        limits=session.messaging_limits,
        target=session._messaging_target,
    )
    try:
        receipt: MessageReceiptDAO | None = await store.get_receipt(
            message_id=submission.message_id, principal=session._messaging_owner_principal
        )
        assert receipt is not None
        assert receipt.state == "applied"
        assert receipt.retained_for_recovery is False
    finally:
        await store.close()


async def test_injected_agent_refusal_releases_store_and_lease(tmp_path: Path) -> None:
    """A2: a busy or foreign-bound agent refuses startup and leaves the session acquirable."""
    model: RecordingModel = RecordingModel(responses=[])
    foreign_source: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=model)
    injected: SloAgent = SloAgent(llm=model, cwd=str(tmp_path), tools=[], message_source=foreign_source)
    session: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=model, agent=injected)
    database_path: Path = tmp_path / "history" / session.session_id / "messaging.v1.sqlite3"
    assert database_path.resolve().is_relative_to(tmp_path.resolve())
    with pytest.raises(MessageAdmissionError) as captured:
        await session.start_messaging()
    assert captured.value.error == MessageErrorDAO(code="unsupported")
    assert session.is_messaging_ready is False
    # Unapplied content is never durable after a failed start, file or not.
    if database_path.exists():
        rows: tuple[tuple[str, int, str], ...] = await asyncio.to_thread(
            read_closed_message_rows, database_path=database_path, temporary_root=tmp_path
        )
        assert rows == ()
    # The released lease lets a second session own the same session_id immediately.
    other: SloAgentSession = _build_injected_session(
        tmp_path=tmp_path,
        model=model,
        session_id=session.session_id,
    )
    try:
        await other.start_messaging()
        assert other.is_messaging_ready
        assert model.requests == []
    finally:
        await other.close_messaging()


async def test_bind_message_source_is_idle_and_idempotent(tmp_path: Path) -> None:
    """A3: binding accepts one idle source, repeats harmlessly, and rejects anything else."""
    model: FauxChatModel = FauxChatModel(responses=[FauxChatModel.assistant_message(content="binder")])
    session: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=model)
    agent: SloAgent | None = session.agent
    assert agent is not None
    other_session: SloAgentSession = _build_injected_session(tmp_path=tmp_path, model=model)

    agent.bind_message_source(message_source=session)
    agent.bind_message_source(message_source=session)

    with pytest.raises(RuntimeError, match="bound to another message source"):
        agent.bind_message_source(message_source=other_session)

    # A real provider request holds the running lifecycle; no private flag fabrication.
    running_model: RecordingModel = RecordingModel(
        responses=[FauxChatModel.assistant_message(content="running answer")]
    )
    running_agent: SloAgent = SloAgent(llm=running_model, cwd=str(tmp_path), tools=[])

    async def consume_run() -> None:
        """Drain the real agent gateway until the held provider completes."""
        async for _event in running_agent.invoke(query="held invocation"):
            pass

    run: asyncio.Task[None] = asyncio.create_task(coro=consume_run())
    try:
        async with asyncio.timeout(delay=5):
            await running_model.entered.wait()
        with pytest.raises(RuntimeError, match="bind before a messaging run"):
            running_agent.bind_message_source(message_source=session)
        assert len(running_model.requests) == 1
    finally:
        running_model.release.set()
        await run
    # Once the real run exits, the same previously refused binding is legal.
    running_agent.bind_message_source(message_source=session)
