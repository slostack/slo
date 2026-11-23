"""R1 / O2 journey: a note never revives a stopping run through a stale forced snapshot.

A run's stop decision reads the boundary inbox's cached forced-row snapshot.
When that cached forced row is cancelled and a note is pending instead, the
revive boundary must take nothing (no extra provider call). The note stays
pending and reaches the next naturally continuing model call exactly once; a
genuine forced prompt still revives the run. Real SQLite queue, real session
with a real filesystem history store; ``FauxChatModel`` at the provider
boundary only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class GatedRecordingFauxChatModel(FauxChatModel):
    """Provider-boundary double: holds the first call, records every call's texts."""

    first_call_release: asyncio.Event = Field(description="Set by the test to release the first call.")
    first_call_entered: asyncio.Event = Field(description="Set once the first call has started.")
    recorded_contexts: list[list[str]] = Field(
        default_factory=list,
        description="Texts of the messages passed to each model call, in call order.",
    )
    _held_call_done: bool = PrivateAttr(default=False)

    def __init__(self, *, responses: Sequence[AIMessage], **data: object) -> None:
        """Queue the scripted responses; the remaining fields pass through to pydantic."""
        super().__init__(responses=responses, **data)  # type: ignore[arg-type]

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "GatedRecordingFauxChatModel":
        """Clone preserving the gate, the recorder and the remaining script."""
        clone: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
            responses=list(self.queue),
            first_call_release=self.first_call_release,
            first_call_entered=self.first_call_entered,
        )
        # Assigned after construction: validation would copy the list.
        clone.recorded_contexts = self.recorded_contexts
        clone.bound_tools = list(tools)
        clone._held_call_done = self._held_call_done
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Hold the very first call until released; record every call's texts."""
        self.recorded_contexts.append([str(message.content) for message in messages])
        if not self._held_call_done:
            self.first_call_entered.set()
            await self.first_call_release.wait()
            self._held_call_done = True
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


async def _open_world(
    *, tmp_path: Path, session_id: UUID
) -> tuple[ChannelGateway, ParticipantDAO, ParticipantDAO]:
    """Open a real queue and register the operator and the agent participant."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(session_id=session_id, name="slo agent")
    return gateway, user, agent


async def _drain(*, session: SloAgentSession, text: str) -> list[str]:
    """Run one turn through the real session and return its event kinds."""
    return [event.kind async for event in session.invoke(text=text)]


async def test_cancelled_cached_forced_row_with_pending_note_makes_no_extra_provider_call(
    tmp_path: Path,
) -> None:
    """A stale forced snapshot plus a pending note stops the run; the note waits for the next call."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    model: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
        responses=[AIMessage(content="first answer"), AIMessage(content="second answer")],
        first_call_release=asyncio.Event(),
        first_call_entered=asyncio.Event(),
    )
    history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[], boundary_inbox=inbox),
        workdir=tmp_path,
        session_id=str(session_id),
        history_store=history_store,
        enable_history=True,
    )
    try:
        first_run: asyncio.Task[list[str]] = asyncio.create_task(_drain(session=session, text="start"))
        await asyncio.wait_for(model.first_call_entered.wait(), timeout=10.0)
        forced: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="forced", force=True)
        )
        await inbox.refresh()
        assert inbox.has_forced() is True
        # The forced row is withdrawn and a note arrives; the cached snapshot
        # is not refreshed before the run's stop decision.
        await gateway.cancel(message_id=forced.id, reason="operator")
        note: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="fyi note", message_type="note"
            )
        )
        model.first_call_release.set()
        first_kinds: list[str] = await asyncio.wait_for(first_run, timeout=10.0)

        assert "run_completed" in first_kinds
        assert "steering_applied" not in first_kinds
        assert len(model.recorded_contexts) == 1
        pending_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
        assert pending_note is not None and pending_note.accepted_at is None

        # The next naturally continuing call carries the note exactly once.
        await asyncio.wait_for(_drain(session=session, text="next"), timeout=10.0)
        assert len(model.recorded_contexts) == 2
        assert model.recorded_contexts[1].count("fyi note") == 1
        accepted_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
        assert accepted_note is not None and accepted_note.accepted_at is not None
    finally:
        await gateway.close()


async def test_genuine_forced_prompt_still_revives_a_stopping_run(tmp_path: Path) -> None:
    """A pending forced prompt at the stop decision gives the run one more provider call."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    model: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
        responses=[AIMessage(content="first answer"), AIMessage(content="revived answer")],
        first_call_release=asyncio.Event(),
        first_call_entered=asyncio.Event(),
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[], boundary_inbox=inbox),
        workdir=tmp_path,
        session_id=str(session_id),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    try:
        run: asyncio.Task[list[str]] = asyncio.create_task(_drain(session=session, text="start"))
        await asyncio.wait_for(model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id,
                recipient_id=agent.id,
                message_contents="ride-along note",
                message_type="note",
            )
        )
        forced: ChannelMessageDAO = await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="also do X", force=True
            )
        )
        await inbox.refresh()
        model.first_call_release.set()
        kinds: list[str] = await asyncio.wait_for(run, timeout=10.0)

        assert kinds.count("steering_applied") == 2
        assert len(model.recorded_contexts) == 2
        revived_context: list[str] = model.recorded_contexts[1]
        assert revived_context.count("also do X") == 1
        assert revived_context.index("ride-along note") < revived_context.index("also do X")
        for row_id in (note.id, forced.id):
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row_id)
            assert stored is not None and stored.accepted_at is not None
    finally:
        await gateway.close()


async def test_taken_deliveries_carry_their_kind(tmp_path: Path) -> None:
    """The boundary delivery keeps whether it is a note or a forced prompt."""
    session_id: UUID = uuid4()
    gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
    inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
    try:
        await gateway.send(
            new=NewMessageDAO(
                sender_id=user.id, recipient_id=agent.id, message_contents="n", message_type="note"
            )
        )
        assert await inbox.take(iteration=1, require_forced_prompt=True) == []
        await gateway.send(
            new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="f", force=True)
        )
        deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=2, require_forced_prompt=True)
        assert [delivery.kind for delivery in deliveries] == ["note", "forced_prompt"]
    finally:
        await gateway.close()


class _RecordingDisplay:
    """Display-sink seam (injected): records every row offered to it and every row it rendered."""

    def __init__(self) -> None:
        """Record nothing yet."""
        self.offered: list[UUID] = []
        self.shown: list[UUID] = []

    async def show(self, *, message: ChannelMessageDAO) -> None:
        """Record the offer, render, then record the row as shown."""
        self.offered.append(message.id)
        await self._render(message=message)
        self.shown.append(message.id)

    async def _render(self, *, message: ChannelMessageDAO) -> None:
        """Render at once; the gated and failing sinks below override this."""
        del message


class _GatedDisplay(_RecordingDisplay):
    """A sink whose first render is held until the test releases it."""

    def __init__(self) -> None:
        """Start with the render gate closed."""
        super().__init__()
        self.entered: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()
        self.retired: list[UUID] = []

    async def _render(self, *, message: ChannelMessageDAO) -> None:
        """Signal entry and hold until released; record a render cancelled while held."""
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.retired.append(message.id)
            raise


class _FailingOnceDisplay(_RecordingDisplay):
    """A sink that is unavailable for its first render only."""

    async def _render(self, *, message: ChannelMessageDAO) -> None:
        """Fail the very first offer; render every later one."""
        del message
        if len(self.offered) == 1:
            raise RuntimeError("display sink unavailable")


class _UnusedRunner:
    """Turn-runner seam: ``auto_run=False`` never starts poller-owned runs."""

    async def run(self, *, message: ChannelMessageDAO, on_started: object) -> object:
        """Fail loudly if the poller ever starts a run."""
        raise AssertionError("auto_run=False never starts runs")


def _noop_tool() -> BaseTool:
    """Return one real tool so the run passes a safe boundary after tools finish."""
    from langchain_core.tools import tool

    @tool
    def noop() -> str:
        """Do nothing and report done."""
        return "done"

    return noop


class _ToolTurnWorld:
    """A real session whose first model call is a held tool call, with a live poller and sender.

    The poller is started through the session wiring, so the poller and the
    agent's boundary share the session's channel delivery exactly as in
    production. The note is sent from a second connection (another process's
    view of the same database), so it never wakes this poller locally.
    """

    def __init__(
        self,
        *,
        gateway: ChannelGateway,
        sender_gateway: ChannelGateway,
        user: ParticipantDAO,
        agent: ParticipantDAO,
        model: GatedRecordingFauxChatModel,
        session: SloAgentSession,
        poller: ChannelPoller,
    ) -> None:
        """Hold the opened collaborators."""
        self.gateway: ChannelGateway = gateway
        self.sender_gateway: ChannelGateway = sender_gateway
        self.user: ParticipantDAO = user
        self.agent: ParticipantDAO = agent
        self.model: GatedRecordingFauxChatModel = model
        self.session: SloAgentSession = session
        self.poller: ChannelPoller = poller

    @classmethod
    async def open(
        cls, *, tmp_path: Path, display: _RecordingDisplay, poll_interval: float
    ) -> _ToolTurnWorld:
        """Open the queue, the session and its poller (``auto_run=False``)."""
        session_id: UUID = uuid4()
        gateway, user, agent = await _open_world(tmp_path=tmp_path, session_id=session_id)
        sender_repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        await sender_repository.open()
        model: GatedRecordingFauxChatModel = GatedRecordingFauxChatModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": "noop", "args": {}, "id": "call-1"}]),
                AIMessage(content="final answer"),
                AIMessage(content="next answer"),
            ],
            first_call_release=asyncio.Event(),
            first_call_entered=asyncio.Event(),
        )
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[_noop_tool()]),
            workdir=tmp_path,
            session_id=str(session_id),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        poller: ChannelPoller = await session.start_channel_delivery(
            gateway=gateway,
            runner=_UnusedRunner(),  # type: ignore[arg-type]
            interval=poll_interval,
            display=display,
            auto_run=False,
        )
        return cls(
            gateway=gateway,
            sender_gateway=ChannelGateway(repository=sender_repository),
            user=user,
            agent=agent,
            model=model,
            session=session,
            poller=poller,
        )

    def start_turn(self, *, text: str, events: list[AgentStreamEventDAO]) -> asyncio.Task[None]:
        """Start one turn in the background, collecting its events into ``events``."""

        async def _drain_turn() -> None:
            async for event in self.session.invoke(text=text):
                events.append(event)

        return asyncio.create_task(_drain_turn())

    async def send_note(self) -> ChannelMessageDAO:
        """Send one ``fyi note`` from the operator over the second connection."""
        return await self.sender_gateway.send(
            new=NewMessageDAO(
                sender_id=self.user.id,
                recipient_id=self.agent.id,
                message_contents="fyi note",
                message_type="note",
            )
        )

    async def complete_one_poller_tick(self) -> None:
        """Wake the poller and wait until a tick has ended (each tick clears the wake)."""
        wake: asyncio.Event = self.gateway.local_wake(recipient_id=self.agent.id)
        wake.set()
        async with asyncio.timeout(10.0):
            while wake.is_set():
                await asyncio.sleep(0.01)

    async def close(self) -> None:
        """Release the model, stop the poller and close both connections."""
        self.model.first_call_release.set()
        await self.poller.stop(reason="test_done")
        await self.sender_gateway.close()
        await self.gateway.close()


async def _wait_until_shown(*, display: _RecordingDisplay, expected: list[UUID]) -> None:
    """Wait until the sink has rendered exactly ``expected``."""
    async with asyncio.timeout(10.0):
        while display.shown != expected:
            await asyncio.sleep(0.01)


def _steering_deliveries(*, events: list[AgentStreamEventDAO]) -> list[tuple[Optional[UUID], Optional[str]]]:
    """Return ``(channel_message_id, delivery_kind)`` for every ``steering_applied`` event."""
    return [
        (event.channel_message_id, event.delivery_kind)
        for event in events
        if event.kind == "steering_applied"
    ]


async def _run_tool_turn_with_note(
    *, tmp_path: Path, poller_sees_first: bool
) -> tuple[list[UUID], list[AgentStreamEventDAO], list[list[str]], Optional[ChannelMessageDAO], UUID]:
    """Run one tool-calling turn while a note arrives; return display, events, contexts, note row, note id.

    The first provider call (a tool call) is held while the note is sent from
    another process-like connection. ``poller_sees_first`` decides who meets
    the note first: a fast poller displays it before the tool boundary, a
    poller that never ticks leaves the tool boundary to take it first.
    """
    display: _RecordingDisplay = _RecordingDisplay()
    world: _ToolTurnWorld = await _ToolTurnWorld.open(
        tmp_path=tmp_path, display=display, poll_interval=0.02 if poller_sees_first else 3600.0
    )
    events: list[AgentStreamEventDAO] = []
    try:
        run: asyncio.Task[None] = world.start_turn(text="start", events=events)
        await asyncio.wait_for(world.model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await world.send_note()
        if poller_sees_first:
            await _wait_until_shown(display=display, expected=[note.id])
        world.model.first_call_release.set()
        await asyncio.wait_for(run, timeout=20.0)
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=note.id)
    finally:
        await world.close()
    return display.shown, events, world.model.recorded_contexts, stored, note.id


async def test_a_note_the_poller_shows_first_is_shown_once_and_enters_context_once(tmp_path: Path) -> None:
    """Poller first: the boundary still applies the note once, and does not show it again."""
    shown, events, contexts, stored, note_id = await _run_tool_turn_with_note(
        tmp_path=tmp_path, poller_sees_first=True
    )
    assert shown == [note_id]
    assert len(contexts) == 2 and contexts[1].count("fyi note") == 1
    assert stored is not None and stored.accepted_at is not None
    assert _steering_deliveries(events=events) == [(note_id, "note")]


async def test_a_note_the_boundary_takes_first_is_still_shown_exactly_once(tmp_path: Path) -> None:
    """Boundary first: a note the poller never saw pending is shown by the boundary, once."""
    shown, events, contexts, stored, note_id = await _run_tool_turn_with_note(
        tmp_path=tmp_path, poller_sees_first=False
    )
    assert shown == [note_id]
    assert len(contexts) == 2 and contexts[1].count("fyi note") == 1
    assert stored is not None and stored.accepted_at is not None
    assert _steering_deliveries(events=events) == [(note_id, "note")]


async def test_a_display_in_flight_neither_blocks_the_boundary_nor_repeats_the_note(tmp_path: Path) -> None:
    """The poller is mid-render when the boundary takes the note: one render, one context entry."""
    display: _GatedDisplay = _GatedDisplay()
    world: _ToolTurnWorld = await _ToolTurnWorld.open(tmp_path=tmp_path, display=display, poll_interval=0.02)
    events: list[AgentStreamEventDAO] = []
    try:
        run: asyncio.Task[None] = world.start_turn(text="start", events=events)
        await asyncio.wait_for(world.model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await world.send_note()
        await asyncio.wait_for(display.entered.wait(), timeout=10.0)
        world.model.first_call_release.set()
        # The run finishes while the poller is still rendering the note.
        await asyncio.wait_for(run, timeout=20.0)
        assert display.shown == []
        display.release.set()
        await _wait_until_shown(display=display, expected=[note.id])
        # The released tick must not record the (now accepted) note into history again.
        await world.complete_one_poller_tick()
        await asyncio.wait_for(world.start_turn(text="next", events=[]), timeout=20.0)
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=note.id)
    finally:
        display.release.set()
        await world.close()
    assert display.offered == [note.id]
    contexts: list[list[str]] = world.model.recorded_contexts
    assert len(contexts) == 3
    # Substring counts: a second recording would arrive as a differently framed workflow update.
    assert sum("fyi note" in text for text in contexts[1]) == 1
    assert sum("fyi note" in text for text in contexts[2]) == 1
    assert stored is not None and stored.accepted_at is not None
    assert _steering_deliveries(events=events) == [(note.id, "note")]


async def test_a_failed_boundary_display_is_retried_by_the_poller_without_repeating_context(
    tmp_path: Path,
) -> None:
    """A sink failure never breaks the run or loses the note: the next poller tick shows it once."""
    display: _FailingOnceDisplay = _FailingOnceDisplay()
    world: _ToolTurnWorld = await _ToolTurnWorld.open(
        tmp_path=tmp_path, display=display, poll_interval=3600.0
    )
    events: list[AgentStreamEventDAO] = []
    try:
        run: asyncio.Task[None] = world.start_turn(text="start", events=events)
        await asyncio.wait_for(world.model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await world.send_note()
        world.model.first_call_release.set()
        await asyncio.wait_for(run, timeout=20.0)
        assert display.offered == [note.id] and display.shown == []
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=note.id)
        assert stored is not None and stored.accepted_at is not None
        await world.complete_one_poller_tick()
        await _wait_until_shown(display=display, expected=[note.id])
        await world.complete_one_poller_tick()
    finally:
        await world.close()
    assert display.offered == [note.id, note.id]
    contexts: list[list[str]] = world.model.recorded_contexts
    assert len(contexts) == 2 and contexts[1].count("fyi note") == 1
    assert _steering_deliveries(events=events) == [(note.id, "note")]


async def _stop_during_a_held_note_render(*, tmp_path: Path) -> tuple[_ToolTurnWorld, _GatedDisplay, UUID]:
    """Hold a poller-tick note render, then stop the session's channel delivery.

    The poller tick is the render's caller; stopping delivery cancels that
    tick. Returns the world, its gated sink and the note id after
    ``stop_channel_delivery`` returned.
    """
    display: _GatedDisplay = _GatedDisplay()
    world: _ToolTurnWorld = await _ToolTurnWorld.open(tmp_path=tmp_path, display=display, poll_interval=0.02)
    note: ChannelMessageDAO = await world.send_note()
    await asyncio.wait_for(display.entered.wait(), timeout=10.0)
    await world.session.stop_channel_delivery(reason="session_closed")
    return world, display, note.id


async def test_stopping_delivery_retires_a_held_note_render_before_stop_returns(tmp_path: Path) -> None:
    """Session stop owns the render lifetime: no shielded render survives the stopped delivery."""
    world, display, note_id = await _stop_during_a_held_note_render(tmp_path=tmp_path)
    try:
        assert display.retired == [note_id]
        display.release.set()
        await asyncio.sleep(0.1)
        assert display.shown == []
    finally:
        display.release.set()
        await world.close()


async def test_a_replaced_session_never_publishes_its_held_note_render_late(tmp_path: Path) -> None:
    """Replacement: after the old delivery stops and a successor starts, the old render never lands."""
    world, display, note_id = await _stop_during_a_held_note_render(tmp_path=tmp_path)
    successor_display: _RecordingDisplay = _RecordingDisplay()
    successor: SloAgentSession = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), cwd=str(tmp_path), tools=[]
        ),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    successor_poller: ChannelPoller = await successor.start_channel_delivery(
        gateway=world.gateway,
        runner=_UnusedRunner(),  # type: ignore[arg-type]
        interval=0.02,
        display=successor_display,
        auto_run=False,
    )
    try:
        successor_note: ChannelMessageDAO = await world.sender_gateway.send(
            new=NewMessageDAO(
                sender_id=world.user.id,
                recipient_id=successor_poller.participant_id,
                message_contents="successor note",
                message_type="note",
            )
        )
        display.release.set()
        await _wait_until_shown(display=successor_display, expected=[successor_note.id])
        await asyncio.sleep(0.1)
        assert display.shown == []
        assert display.retired == [note_id]
        assert successor_display.offered == [successor_note.id]
    finally:
        display.release.set()
        await successor.stop_channel_delivery(reason="test_done")
        await world.close()


async def test_a_run_cancelled_during_the_boundary_display_keeps_the_note_for_the_next_call(
    tmp_path: Path,
) -> None:
    """Hard-cancelled mid-display: the render completes once, the note stays pending, then applies once."""
    display: _GatedDisplay = _GatedDisplay()
    world: _ToolTurnWorld = await _ToolTurnWorld.open(
        tmp_path=tmp_path, display=display, poll_interval=3600.0
    )
    next_events: list[AgentStreamEventDAO] = []
    try:
        run: asyncio.Task[None] = world.start_turn(text="start", events=[])
        await asyncio.wait_for(world.model.first_call_entered.wait(), timeout=10.0)
        note: ChannelMessageDAO = await world.send_note()
        world.model.first_call_release.set()
        await asyncio.wait_for(display.entered.wait(), timeout=10.0)
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)
        display.release.set()
        await _wait_until_shown(display=display, expected=[note.id])
        pending: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=note.id)
        assert pending is not None and pending.accepted_at is None and pending.cancelled_at is None
        await asyncio.wait_for(world.start_turn(text="next", events=next_events), timeout=20.0)
        stored: Optional[ChannelMessageDAO] = await world.gateway.get(message_id=note.id)
    finally:
        display.release.set()
        await world.close()
    assert display.offered == [note.id]
    contexts: list[list[str]] = world.model.recorded_contexts
    assert len(contexts) == 2 and contexts[1].count("fyi note") == 1
    assert stored is not None and stored.accepted_at is not None
    assert _steering_deliveries(events=next_events) == [(note.id, "note")]
