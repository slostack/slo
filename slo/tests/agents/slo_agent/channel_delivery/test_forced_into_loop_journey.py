"""F2 journey: a forced row beats queued normal rows and joins the current run.

Journey (108.2 §8 F2): a run is in flight (provider held at the boundary);
two normal rows and one forced row are queued behind it; the forced row is
applied at the current run's next boundary (before the two normal rows ever
start), the two normal rows then run FIFO, and every row is accepted exactly
once. Real SQLite, real session, real poller; ``FauxChatModel`` held at the
LLM provider boundary only.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional, Sequence
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

import httpx

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class HeldRecordingFauxChatModel(FauxChatModel):
    """Provider-boundary double: holds the first call, records every context.

    The first ``_astream`` call awaits the release event (the run stays in
    flight while the test queues rows); every call's message texts are
    recorded, shared across ``bind_tools`` clones.
    """

    first_call_release: asyncio.Event = Field(
        description="Event the test sets to release the held first model call.",
    )
    recorded_contexts: list[list[str]] = Field(
        default_factory=list,
        description="Texts of the messages passed to each model call, in call order.",
    )
    _held_call_done: bool = PrivateAttr(default=False)

    def __init__(
        self,
        *,
        responses: Sequence[AIMessage],
        first_call_release: asyncio.Event,
    ) -> None:
        """Store the scripted responses and the first-call release event.

        Args:
            responses (Sequence[AIMessage]): Scripted responses consumed in order.
            first_call_release (asyncio.Event): Set by the test to release the
                held first model call.
        """
        super().__init__(responses=responses, first_call_release=first_call_release)

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "HeldRecordingFauxChatModel":
        """Clone preserving the gate, the recorder and the script."""
        clone: HeldRecordingFauxChatModel = HeldRecordingFauxChatModel(
            responses=list(self.queue),
            first_call_release=self.first_call_release,
        )
        clone.bound_tools = list(tools)
        clone._held_call_done = self._held_call_done
        clone.recorded_contexts = self.recorded_contexts
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list,
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ):
        """Hold the first call until released; record every call's context."""
        self.recorded_contexts.append([str(message.content) for message in messages])
        if not self._held_call_done:
            await self.first_call_release.wait()
            self._held_call_done = True
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class CancelAtSteeringRunner:
    """Runs one row through the real session and closes the invoke generator
    exactly at the ``steering_applied`` event (108.2 B1).

    The close throws ``GeneratorExit`` into the agent's boundary generator at
    the yield point; the confirm-before-yield contract must have already
    accepted the row, so a live-process resume never reapplies it.
    """

    def __init__(self, *, session: SloAgentSession) -> None:
        """Bind the runner to one session."""
        self._session: SloAgentSession = session
        self.ran: list[UUID] = []
        self.cancelled_at_steering: bool = False

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started,
    ) -> TurnOutcomeDAO:
        """Consume the run and close the invoke generator at the steering event."""
        self.ran.append(message.id)
        started: bool = False
        status: str = "not_started"
        final_text: str = ""
        invoke = self._session.invoke(
            text=message.message_contents,
            channel_message_id=message.id,
        )
        try:
            async for event in invoke:
                if not started:
                    started = True
                    await on_started()
                if event.kind == "steering_applied":
                    self.cancelled_at_steering = True
                    break
                if event.kind == "run_completed":
                    status = "completed"
                    final_text = event.content or ""
                elif event.kind == "run_aborted":
                    status = "aborted"
                elif event.kind == "run_failed":
                    status = "failed"
        finally:
            await invoke.aclose()
        return TurnOutcomeDAO(status=status, final_text=final_text)  # type: ignore[arg-type]


class HeldThenFailingFauxChatModel(FauxChatModel):
    """Provider-boundary double: holds the first call, fails the post-boundary call.

    The first ``_astream`` call awaits the release event (the run stays in
    flight while the test queues the forced row); the first post-held call
    raises ``httpx.RemoteProtocolError`` (a pre-commit stream disconnection
    the session reconnects with). Every call's message texts are recorded,
    shared across ``bind_tools`` clones.
    """

    first_call_release: asyncio.Event = Field(
        description="Event the test sets to release the held first model call.",
    )
    recorded_contexts: list[list[str]] = Field(
        default_factory=list,
        description="Texts of the messages passed to each model call, in call order.",
    )
    _held_call_done: bool = PrivateAttr(default=False)
    _post_held_calls: int = PrivateAttr(default=0)

    def __init__(
        self,
        *,
        responses: Sequence[AIMessage],
        first_call_release: asyncio.Event,
    ) -> None:
        """Store the scripted responses and the first-call release event.

        Args:
            responses (Sequence[AIMessage]): Scripted responses consumed in order.
            first_call_release (asyncio.Event): Set by the test to release the
                held first model call.
        """
        super().__init__(responses=responses, first_call_release=first_call_release)

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "HeldThenFailingFauxChatModel":
        """Clone preserving the gate, the recorder and the script."""
        clone: HeldThenFailingFauxChatModel = HeldThenFailingFauxChatModel(
            responses=list(self.queue),
            first_call_release=self.first_call_release,
        )
        clone.bound_tools = list(tools)
        clone._held_call_done = self._held_call_done
        clone._post_held_calls = self._post_held_calls
        clone.recorded_contexts = self.recorded_contexts
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list,
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ):
        """Hold the first call until released; fail the first post-held call."""
        self.recorded_contexts.append([str(message.content) for message in messages])
        if not self._held_call_done:
            await self.first_call_release.wait()
            self._held_call_done = True
        else:
            self._post_held_calls += 1
            if self._post_held_calls == 1:
                raise httpx.RemoteProtocolError("provider stream disconnected")
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class RecordingSessionTurnRunner:
    """Runs prompt rows through the real session and records the run order."""

    def __init__(self, *, session: SloAgentSession) -> None:
        """Bind the runner to one session."""
        self._session: SloAgentSession = session
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started,
    ) -> TurnOutcomeDAO:
        """Run the row through the session and map the terminal outcome."""
        self.ran.append(message.id)
        started: bool = False
        final_text: str = ""
        status: str = "not_started"
        async for event in self._session.invoke(
            text=message.message_contents,
            channel_message_id=message.id,
        ):
            if not started:
                started = True
                await on_started()
            if event.kind == "run_completed":
                status = "completed"
                final_text = event.content or ""
            elif event.kind == "run_aborted":
                status = "aborted"
            elif event.kind == "run_failed":
                status = "failed"
        return TurnOutcomeDAO(status=status, final_text=final_text)  # type: ignore[arg-type]


async def _wait_until(*, predicate, timeout_seconds: float = 10.0) -> None:
    """Poll a predicate until it holds or the timeout expires.

    Async predicates are awaited; a bare coroutine object is never treated as
    a truthy result (108.2 T1).
    """
    async with asyncio.timeout(timeout_seconds):
        while True:
            result: object = predicate()
            if inspect.isawaitable(result):
                result = await result
            if result:
                return
            await asyncio.sleep(0.01)


async def test_forced_row_joins_the_current_run_ahead_of_queued_normal_rows(tmp_path: Path) -> None:
    """F2: forced first at the boundary; the two normal rows run FIFO afterwards."""
    release: asyncio.Event = asyncio.Event()
    model: HeldRecordingFauxChatModel = HeldRecordingFauxChatModel(
        responses=[
            AIMessage(content="first answer"),
            AIMessage(content="steered answer"),
            AIMessage(content="second answer"),
            AIMessage(content="third answer"),
        ],
        first_call_release=release,
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(
        session_id=UUID(session.session_id), name="slo abc12345"
    )

    runner: RecordingSessionTurnRunner = RecordingSessionTurnRunner(session=session)
    from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
    from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter

    poller: ChannelPoller = await session.start_channel_delivery(
        gateway=gateway,
        runner=runner,
        interval=0.02,
    )
    assert isinstance(poller.boundary_inbox, ChannelBoundaryInbox)
    try:
        running_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="start", channel_id=channel.id
            )
        )
        await _wait_until(predicate=lambda: model._held_call_done or model.recorded_contexts)
        # The run is in flight (provider held). Queue two normal rows and one
        # forced row behind it.
        normal_one: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="normal one", channel_id=channel.id
            )
        )
        normal_two: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="normal two", channel_id=channel.id
            )
        )
        forced_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents="use pytest -x",
                channel_id=channel.id,
                force=True,
            )
        )

        # The forced row must first be visible in the boundary inbox snapshot
        # (the poller refreshed it while the run is in flight), then the held
        # model call is released so the run reaches its next safe boundary.
        # Boundary apply and every acceptance happen after that release.
        await asyncio.wait_for(
            _wait_until(predicate=lambda: poller.boundary_inbox.has_forced()),
            timeout=10.0,
        )
        release.set()

        async def _forced_accepted() -> bool:
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced_row.id)
            return stored is not None and stored.accepted_at is not None

        await asyncio.wait_for(_wait_until(predicate=_forced_accepted), timeout=10.0)

        await _wait_until(predicate=lambda: len(runner.ran) == 3)
        # The forced row joined the current run; the two normal rows follow FIFO.
        assert runner.ran == [running_row.id, normal_one.id, normal_two.id]
        # The forced text reached the next model call of the running turn and
        # appears exactly once within that call (later calls may replay it
        # through history, which is not a second boundary application).
        boundary_call_index: int = model.recorded_contexts.index(
            next(context for context in model.recorded_contexts if "use pytest -x" in context)
        )
        assert boundary_call_index == 1
        assert model.recorded_contexts[1].count("use pytest -x") == 1
        # The run's own prompt is the only user text in the first call.
        assert "start" in model.recorded_contexts[0]
        assert "use pytest -x" not in model.recorded_contexts[0]
        assert "use pytest -x" in model.recorded_contexts[1]

        # Every row accepted exactly once.
        async def _all_accepted() -> bool:
            stored_rows: list[Optional[ChannelMessageDAO]] = [
                await gateway.get(message_id=row.id)
                for row in (running_row, normal_one, normal_two, forced_row)
            ]
            return all(row is not None and row.accepted_at is not None for row in stored_rows)

        await asyncio.wait_for(_wait_until(predicate=_all_accepted), timeout=10.0)
        # The run's reply carries the steered answer.
        outbound: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
        reply_for_running: list[ChannelMessageDAO] = [
            row for row in outbound if row.in_reply_to_id == running_row.id
        ]
        assert [row.message_contents for row in reply_for_running] == ["steered answer"]
        # The persisted steering record carries the channel id (the F4
        # crash-recovery key), and recovery finds it in history.
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        steering_records = [
            event
            for event in events
            if event.kind == "steering_message" and "channel_message_id" in event.payload.metadata
        ]
        assert [event.payload.metadata["channel_message_id"] for event in steering_records] == [
            str(forced_row.id)
        ]
        known: set[str] = await session.channel_message_ids_in_history()
        assert str(forced_row.id) in known
    finally:
        await session.stop_channel_delivery(reason="test_done")
        await gateway.close()


async def test_accepted_steering_survives_session_level_reconnect_retry(tmp_path: Path) -> None:
    """B2: the confirmed steering delivery survives a session-level retry context.

    A forced row is applied at the boundary, the history record is written, and
    the row is accepted. The next model call fails with a pre-commit stream
    disconnection; the session reconnects and rebuilds the context from history
    excluding the failed turn. The confirmed steering delivery must be present
    exactly once in the retried context without being accepted again.
    """
    release: asyncio.Event = asyncio.Event()
    model: HeldThenFailingFauxChatModel = HeldThenFailingFauxChatModel(
        responses=[
            AIMessage(content="first answer"),
            AIMessage(content="recovered answer"),
        ],
        first_call_release=release,
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent_participant: ParticipantDAO = await gateway.register_agent(
        session_id=UUID(session.session_id), name="slo abc12345"
    )

    runner: RecordingSessionTurnRunner = RecordingSessionTurnRunner(session=session)
    poller: ChannelPoller = await session.start_channel_delivery(
        gateway=gateway,
        runner=runner,
        interval=0.02,
    )
    try:
        running_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent_participant.id,
                message_contents="start",
                channel_id=channel.id,
            )
        )
        await _wait_until(predicate=lambda: model._held_call_done or model.recorded_contexts)
        forced_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent_participant.id,
                message_contents="use pytest -x",
                channel_id=channel.id,
                force=True,
            )
        )
        await asyncio.wait_for(
            _wait_until(predicate=lambda: poller.boundary_inbox.has_forced()),
            timeout=10.0,
        )
        release.set()

        async def _steered_row_accepted() -> bool:
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced_row.id)
            return stored is not None and stored.accepted_at is not None

        await asyncio.wait_for(_wait_until(predicate=_steered_row_accepted), timeout=10.0)
        # The boundary applied the forced row; the next model call failed and
        # the session reconnected. Wait for the retried model call's context.
        async def _retried_context_recorded() -> bool:
            return len(model.recorded_contexts) >= 3

        await asyncio.wait_for(_wait_until(predicate=_retried_context_recorded), timeout=30.0)
        # The retried context (call 3) carries the confirmed steering delivery
        # exactly once, even though the failed turn that applied it is excluded
        # from the retry context.
        retried_context: list[str] = model.recorded_contexts[2]
        assert retried_context.count("use pytest -x") == 1
        # The accepted row is not re-accepted: the poller's snapshot no longer
        # holds it and the queue keeps it accepted.
        stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced_row.id)
        assert stored is not None and stored.accepted_at is not None
        assert poller.boundary_inbox.has_forced() is False
        # The run's own prompt is the first call's only user text.
        assert "start" in model.recorded_contexts[0]
        assert "use pytest -x" not in model.recorded_contexts[0]
    finally:
        await session.stop_channel_delivery(reason="test_done")
        await gateway.close()


async def test_cancel_at_steering_applied_event_leaves_row_accepted(tmp_path: Path) -> None:
    """B1: closing the invoke generator at the ``steering_applied`` event
    leaves the row accepted, so a live-process resume never reapplies it.

    Real session, real poller, real gateway; the held provider boundary keeps
    the run in flight while the forced row is queued. The boundary takes the
    row, confirms it (accept) before yielding, and the runner closes the
    invoke generator exactly at the ``steering_applied`` yield.
    """
    release: asyncio.Event = asyncio.Event()
    model: HeldRecordingFauxChatModel = HeldRecordingFauxChatModel(
        responses=[
            AIMessage(content="first answer"),
            AIMessage(content="steered answer"),
        ],
        first_call_release=release,
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(
        session_id=UUID(session.session_id), name="slo abc12345"
    )

    runner: CancelAtSteeringRunner = CancelAtSteeringRunner(session=session)
    poller: ChannelPoller = await session.start_channel_delivery(
        gateway=gateway,
        runner=runner,
        interval=0.02,
    )
    try:
        running_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="start", channel_id=channel.id
            )
        )
        await _wait_until(predicate=lambda: model._held_call_done or model.recorded_contexts)
        forced_row: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents="use pytest -x",
                channel_id=channel.id,
                force=True,
            )
        )
        await _wait_until(predicate=lambda: poller.boundary_inbox.has_forced())
        release.set()

        async def _runner_cancelled() -> bool:
            return runner.cancelled_at_steering

        await asyncio.wait_for(_wait_until(predicate=_runner_cancelled), timeout=10.0)

        async def _forced_accepted() -> bool:
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced_row.id)
            return stored is not None and stored.accepted_at is not None

        await asyncio.wait_for(_wait_until(predicate=_forced_accepted), timeout=10.0)

        # The row is accepted at the boundary confirm — before the
        # ``steering_applied`` yield that the runner closed the generator on.
        stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced_row.id)
        assert stored is not None and stored.accepted_at is not None

        # No rerun: the poller never starts a run for the accepted row, and the
        # row leaves the forced snapshot so a live-process resume cannot revive
        # it.
        await asyncio.sleep(0.2)
        assert runner.ran == [running_row.id]
        assert poller.boundary_inbox.has_forced() is False
    finally:
        await session.stop_channel_delivery(reason="test_done")
        await gateway.close()
