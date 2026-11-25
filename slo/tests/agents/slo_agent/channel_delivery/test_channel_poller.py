"""Journey tests for channel delivery into a real agent session (108.1 M1).

Journey: a prompt row inserted through ``ChannelGateway.send`` is picked up by
the session's ``ChannelPoller``, run through a real ``SloAgentSession`` with an
injected ``FauxChatModel`` provider, accepted exactly when ``invoke`` yields its
first event, persisted into ``events.jsonl`` with the channel message id, and
answered by exactly one ``reply`` row whose ``in_reply_to_id`` points at the
request (108.1 §9 A2/A8; journey half of A3).

Doubles policy: real SQLite, real filesystem history store; ``FauxChatModel``
at the LLM boundary; ``RecordingTurnRunner``/``DirectTurnRunner`` are injected
seams, not patched internals.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller, ChannelDisplaySink
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO, TurnRunner
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class RecordingTurnRunner:
    """TurnRunner stub: records the run order and reports scripted outcomes.

    Passed in through the poller's constructor (no patching). ``on_started``
    is called exactly as a real runner would call it after the first event.
    """

    def __init__(self) -> None:
        """Record no runs and report completion by default."""
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
            TurnOutcomeDAO: A completed outcome with a fixed final text.
        """
        self.ran.append(message.id)
        await on_started()
        return TurnOutcomeDAO(status="completed", final_text=f"done:{message.message_contents}")


class SessionTurnRunner:
    """Real turn runner over an injected session (the production seam).

    Drives ``SloAgentSession.invoke`` with the row's text and channel id,
    calling ``on_started`` after the first yielded event and mapping the
    terminal event to a ``TurnOutcomeDAO``.
    """

    def __init__(self, *, session: SloAgentSession) -> None:
        """Bind the runner to one session.

        Args:
            session (SloAgentSession): Session to invoke.
        """
        self._session: SloAgentSession = session

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Run the message through the session and map the terminal outcome.

        Args:
            message (ChannelMessageDAO): Accepted prompt row.
            on_started (Callable[[], Awaitable[None]]): Called after the first
                yielded event.

        Returns:
            TurnOutcomeDAO: How the run ended and its final text.
        """
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


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one real gateway on a fresh temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


async def _register_tui_participants(
    *, gateway: ChannelGateway, session_id: UUID
) -> tuple[ChannelDAO, ParticipantDAO, ParticipantDAO]:
    """Register a TUI channel, its user and the agent participant."""
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(session_id=session_id, name="slo abc12345")
    return channel, user, agent


def _build_session(*, tmp_path: Path, session_id: str, responses: list[AIMessage]) -> SloAgentSession:
    """Build a real session with the faux provider and a real history store."""
    history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id,
        history_store=history_store,
        enable_history=True,
    )


async def _wait_until(*, predicate: Callable[[], bool], timeout_seconds: float = 10.0) -> None:
    """Poll a predicate until it holds or the timeout expires."""
    async with asyncio.timeout(timeout_seconds):
        while not predicate():
            await asyncio.sleep(0.01)


class BlockingTurnRunner:
    """TurnRunner stub that blocks inside ``run`` until released.

    Simulates a long in-flight run (e.g. a tool call) so tests can send rows
    while the poller owns a run. Reports the outcome it was built with.
    """

    def __init__(self, *, release: asyncio.Event) -> None:
        """Bind the release event that unblocks the run."""
        self._release: asyncio.Event = release
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Record the message, call ``on_started``, then block until released."""
        self.ran.append(message.id)
        await on_started()
        await self._release.wait()
        return TurnOutcomeDAO(status="completed", final_text="unblocked")


def _build_poller(
    *,
    gateway: ChannelGateway,
    session: SloAgentSession,
    runner: TurnRunner,
    interval: float = 0.02,
    display: Optional[ChannelDisplaySink] = None,
    auto_run: bool = True,
) -> ChannelPoller:
    """Build a poller with its channel boundary inbox and reply writer."""
    from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
    from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session

    return ChannelPoller(
        gateway=gateway,
        session=session,
        runner=runner,
        replies=ReplyWriter(gateway=gateway),
        boundary_inbox=ChannelBoundaryInbox(
            gateway=gateway,
            agent_id=channel_participant_id_for_session(session_id=session.session_id),
        ),
        interval=interval,
        display=display,
        auto_run=auto_run,
    )


class TestPollerForcedRows:
    async def test_idle_poller_runs_a_forced_row_before_an_older_normal_row(self, tmp_path: Path) -> None:
        """F3 (idle): the forced row is picked first even though the normal row is older."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        try:
            await poller.start()
            normal: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="normal", channel_id=channel.id
                )
            )
            forced: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="use pytest -x",
                    channel_id=channel.id,
                    force=True,
                )
            )
            await _wait_until(predicate=lambda: len(runner.ran) == 2)
            assert runner.ran == [forced.id, normal.id]
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_poller_refreshes_the_forced_snapshot_while_a_run_is_in_flight(
        self, tmp_path: Path
    ) -> None:
        """A forced row sent mid-run becomes visible on the next tick (F5 precondition)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        release: asyncio.Event = asyncio.Event()
        runner: BlockingTurnRunner = BlockingTurnRunner(release=release)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        try:
            await poller.start()
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="long run",
                    channel_id=channel.id,
                )
            )
            await _wait_until(predicate=lambda: len(runner.ran) == 1)
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="use pytest -x",
                    channel_id=channel.id,
                    force=True,
                )
            )
            boundary_inbox = poller.boundary_inbox
            assert boundary_inbox is not None
            await _wait_until(predicate=lambda: boundary_inbox.has_forced())
        finally:
            release.set()
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_poller_exposes_pending_prompts_and_force_for_the_queue_slash_command(
        self, tmp_path: Path
    ) -> None:
        """The poller's queue surface lists pending prompts and forces one by id (F7)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        try:
            first: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="one", channel_id=channel.id
                )
            )
            second: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="two", channel_id=channel.id
                )
            )
            await poller.start()
            pending: list[ChannelMessageDAO] = await poller.pending_prompts()
            assert [row.id for row in pending] == [first.id, second.id]
            forced: bool = await poller.force(message_id=second.id)
            assert forced is True
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=second.id)
            assert stored is not None and stored.forced_at is not None
            pending_after: list[ChannelMessageDAO] = await poller.pending_prompts()
            assert pending_after[0].id == second.id
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()


class TestPollerRunsRowsInOrder:
    async def test_poller_runs_pending_rows_fifo_and_writes_replies(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        await poller.start()
        try:
            texts: list[str] = ["first", "second", "third"]
            rows: list[ChannelMessageDAO] = []
            for text in texts:
                rows.append(
                    await gateway.send(
                        new=NewMessageDAO(
                            sender_id=user.id,
                            recipient_id=agent.id,
                            message_contents=text,
                            channel_id=channel.id,
                        )
                    )
                )
            await _wait_until(predicate=lambda: len(runner.ran) == 3)
            assert runner.ran == [row.id for row in rows]

            async def _all_accepted_and_answered() -> bool:
                stored_rows: list[Optional[ChannelMessageDAO]] = [
                    await gateway.find_message(message_id=row.id) for row in rows
                ]
                replies: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                    recipient_ids=[user.id]
                )
                return (
                    all(stored is not None and stored.accepted_at is not None for stored in stored_rows)
                    and len(replies) == 3
                )

            deadline: float = asyncio.get_event_loop().time() + 10.0
            while not await _all_accepted_and_answered():
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError("rows were not all accepted and answered in time")
                await asyncio.sleep(0.02)

            replies: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
            assert {reply.in_reply_to_id for reply in replies} == {row.id for row in rows}
            for row in rows:
                stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=row.id)
                assert stored is not None and stored.accepted_at is not None
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_reply_writer_inserts_one_reply_pointing_at_the_request(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        try:
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="run tests",
                    channel_id=channel.id,
                )
            )
            writer: ReplyWriter = ReplyWriter(gateway=gateway)
            await writer.write(
                request=request,
                outcome=TurnOutcomeDAO(status="completed", final_text="all green"),
            )
            outbound: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
            assert len(outbound) == 1
            reply: ChannelMessageDAO = outbound[0]
            assert reply.message_type == "reply"
            assert reply.in_reply_to_id == request.id
            assert reply.sender_id == agent.id and reply.recipient_id == user.id
            assert reply.message_contents == "all green"
            assert reply.channel_id == channel.id
        finally:
            await gateway.close()


class TestPollerSessionJourney:
    async def test_prompt_row_runs_through_real_session_and_is_accepted_with_history_link(
        self, tmp_path: Path
    ) -> None:
        """Journey: gateway send → poller → real invoke → accepted → history carries the id → reply row."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="hi there")],
        )
        runner: SessionTurnRunner = SessionTurnRunner(session=session)
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        await poller.start()
        try:
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="hello",
                    channel_id=channel.id,
                )
            )

            async def _request_accepted() -> bool:
                stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=request.id)
                return stored is not None and stored.accepted_at is not None

            async def _reply_present() -> bool:
                return bool(await gateway.list_pending_outbound_messages(recipient_ids=[user.id]))

            async def _done() -> bool:
                return await _request_accepted() and await _reply_present()

            deadline: float = asyncio.get_event_loop().time() + 15.0
            while not await _done():
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError("poller did not accept and answer the row in time")
                await asyncio.sleep(0.02)

            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=request.id)
            assert stored is not None and stored.accepted_at is not None

            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            user_events = [event for event in events if event.kind == "user_message"]
            assert [event.payload.content for event in user_events] == ["hello"]
            assert user_events[0].payload.metadata.get("channel_message_id") == str(request.id)

            outbound: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
            assert len(outbound) == 1
            reply: ChannelMessageDAO = outbound[0]
            assert reply.message_type == "reply"
            assert reply.in_reply_to_id == request.id
            assert reply.message_contents == "hi there"
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()


class RecordingDisplaySink:
    """ChannelDisplaySink stub: records every shown row in order."""

    def __init__(self) -> None:
        """Start with an empty display log."""
        self.shown: list[ChannelMessageDAO] = []

    async def show(self, *, message: ChannelMessageDAO) -> None:
        """Record one shown message row.

        Args:
            message (ChannelMessageDAO): The row the poller handed over.
        """
        self.shown.append(message)


class TestPollerNotesAndNotices:
    async def test_idle_note_is_displayed_recorded_and_accepted_without_a_run(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        display: RecordingDisplaySink = RecordingDisplaySink()
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=runner, display=display
        )
        await poller.start()
        try:
            note: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=agent.id,
                    message_contents="[workflow wf-ab] phase 1 done",
                    message_type="note",
                    channel_id=channel.id,
                )
            )

            async with asyncio.timeout(10.0):
                while True:
                    stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=note.id)
                    if stored is not None and stored.accepted_at is not None:
                        break
                    await asyncio.sleep(0.02)
            assert [row.id for row in display.shown] == [note.id]
            assert runner.ran == []
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            workflow_updates = [event for event in events if event.kind == "workflow_update"]
            assert [event.payload.content for event in workflow_updates] == ["[workflow wf-ab] phase 1 done"]
            assert workflow_updates[0].payload.metadata.get("workflow_id") == "wf-ab"
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_busy_note_is_displayed_once_and_stays_pending_for_the_boundary(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        release: asyncio.Event = asyncio.Event()
        runner: BlockingTurnRunner = BlockingTurnRunner(release=release)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        display: RecordingDisplaySink = RecordingDisplaySink()
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=runner, display=display
        )
        await poller.start()
        try:
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="long run",
                    channel_id=channel.id,
                )
            )
            await _wait_until(predicate=lambda: len(runner.ran) == 1)
            note: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=agent.id,
                    message_contents="[workflow wf-ab] phase 1 done",
                    message_type="note",
                    channel_id=channel.id,
                )
            )
            await _wait_until(predicate=lambda: len(display.shown) == 1)
            await asyncio.sleep(0.1)
            assert len(display.shown) == 1
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=note.id)
            assert stored is not None and stored.accepted_at is None and stored.cancelled_at is None
            assert runner.ran == [runner.ran[0]]  # the note never started a run
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            assert [event for event in events if event.kind == "workflow_update"] == []
        finally:
            release.set()
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_notice_is_displayed_and_accepted_without_entering_context(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        display: RecordingDisplaySink = RecordingDisplaySink()
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=runner, display=display
        )
        await poller.start()
        try:
            notice: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=agent.id,
                    message_contents="fleet: 2 live",
                    message_type="notice",
                    channel_id=channel.id,
                )
            )

            async with asyncio.timeout(10.0):
                while True:
                    stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=notice.id)
                    if stored is not None and stored.accepted_at is not None:
                        break
                    await asyncio.sleep(0.02)
            assert [row.id for row in display.shown] == [notice.id]
            assert runner.ran == []
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            assert [event for event in events if event.kind == "workflow_update"] == []
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_a_pending_prompt_is_never_displayed_as_a_note_or_notice(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        display: RecordingDisplaySink = RecordingDisplaySink()
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=runner, display=display
        )
        await poller.start()
        try:
            prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="normal prompt",
                    channel_id=channel.id,
                )
            )
            await _wait_until(predicate=lambda: len(runner.ran) == 1)
            assert display.shown == []
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()


class TestPollerAutoRunDisabled:
    async def test_auto_run_false_never_starts_runs_but_keeps_the_boundary_live(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="unused")],
        )
        display: RecordingDisplaySink = RecordingDisplaySink()
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=runner, display=display, auto_run=False
        )
        await poller.start()
        try:
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="queued prompt",
                    channel_id=channel.id,
                )
            )
            await asyncio.sleep(0.15)
            assert runner.ran == []
            forced: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="use pytest -x",
                    channel_id=channel.id,
                    force=True,
                )
            )
            await _wait_until(predicate=lambda: poller.boundary_inbox.has_forced())
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=agent.id,
                    message_contents="[workflow wf-ab] fleet",
                    message_type="notice",
                    channel_id=channel.id,
                )
            )
            await _wait_until(predicate=lambda: len(display.shown) == 1)
            assert runner.ran == []
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()


class TestPollerDefersToARunItDoesNotOwn:
    async def test_row_sent_during_a_direct_invoke_waits_then_runs_once(self, tmp_path: Path) -> None:
        """EB1 (rehomed from the retired inbox run): one run owner at a time.

        While the session runs a turn the poller did not start (a direct
        ``invoke`` caller), a queued operator row stays pending — never started
        into the busy session and cancelled as ``start_failed`` — and runs once
        after the direct run ends.
        """
        from tests.conftest import GatedFauxChatModel

        release_direct_run: asyncio.Event = asyncio.Event()
        session_id: UUID = uuid4()
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=GatedFauxChatModel(
                    responses=[AIMessage(content="direct answer"), AIMessage(content="queued answer")],
                    first_call_release=release_direct_run,
                ),
                cwd=str(tmp_path),
                tools=[],
            ),
            workdir=tmp_path,
            session_id=str(session_id),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        poller: ChannelPoller = _build_poller(
            gateway=gateway, session=session, runner=SessionTurnRunner(session=session)
        )

        async def _drain_direct_run() -> None:
            async for _event in session.invoke(text="direct turn"):
                pass

        await poller.start()
        direct_run: asyncio.Task[None] = asyncio.create_task(_drain_direct_run())
        try:
            await _wait_until(predicate=lambda: session.is_running)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="queued", channel_id=channel.id
                )
            )
            await asyncio.sleep(0.2)
            while_busy: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=request.id)
            busy_poller: bool = poller.busy

            release_direct_run.set()
            await asyncio.wait_for(direct_run, timeout=10)
            async with asyncio.timeout(15.0):
                while not await gateway.list_pending_outbound_messages(recipient_ids=[user.id]):
                    await asyncio.sleep(0.02)
            answered: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=request.id)
            replies: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
        finally:
            release_direct_run.set()
            await poller.stop(reason="test_done")
            await gateway.close()

        assert while_busy is not None
        assert (while_busy.accepted_at, while_busy.cancelled_at) == (None, None)
        assert busy_poller is False
        assert answered is not None and answered.accepted_at is not None and answered.cancelled_at is None
        assert [(reply.in_reply_to_id, reply.message_contents) for reply in replies] == [
            (request.id, "queued answer")
        ]


class BlockingBeforeFirstEventRunner:
    """Hold the real session runner before its first yielded event."""

    def __init__(self, *, session: SloAgentSession) -> None:
        """Compose a real session runner behind an observable release gate."""
        self._session_runner: SessionTurnRunner = SessionTurnRunner(session=session)
        self.entered: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()
        self.started_message_ids: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Wait before first-event admission, then delegate to the real runner."""
        self.started_message_ids.append(message.id)
        self.entered.set()
        await self.release.wait()
        return await self._session_runner.run(message=message, on_started=on_started)


class TestPollerQueuedCancellation:
    async def test_reserved_prompt_cannot_be_cancelled_before_its_first_event(self, tmp_path: Path) -> None:
        """A blocked real runner leaves the reserved prompt durable and runs it once."""
        session_id: UUID = uuid4()
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(responses=[AIMessage(content="accepted after release")]),
                cwd=str(tmp_path),
                tools=[],
            ),
            workdir=tmp_path,
            session_id=str(session_id),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: BlockingBeforeFirstEventRunner = BlockingBeforeFirstEventRunner(session=session)
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        await poller.start()
        try:
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="hold before first event",
                    channel_id=channel.id,
                )
            )
            await asyncio.wait_for(runner.entered.wait(), timeout=10.0)
            assert poller.busy is True

            cancellation_result: bool = await poller.cancel_queued(message_id=request.id)
            stored_before_first_event: Optional[ChannelMessageDAO] = await gateway.find_message(
                message_id=request.id
            )
            assert cancellation_result is False
            assert stored_before_first_event is not None
            assert (stored_before_first_event.accepted_at, stored_before_first_event.cancelled_at) == (
                None,
                None,
            )

            runner.release.set()
            async with asyncio.timeout(10.0):
                while await gateway.find_reply(message_id=request.id) is None:
                    await asyncio.sleep(0.02)
            stored_after_completion: Optional[ChannelMessageDAO] = await gateway.find_message(
                message_id=request.id
            )
            replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway,
                user_id=user.id,
                request_id=request.id,
            )
        finally:
            runner.release.set()
            await poller.stop(reason="test_done")
            await gateway.close()

        assert stored_after_completion is not None
        assert stored_after_completion.accepted_at is not None
        assert stored_after_completion.cancelled_at is None
        assert [(reply.in_reply_to_id, reply.message_contents) for reply in replies] == [
            (request.id, "accepted after release")
        ]
        assert runner.started_message_ids == [request.id]


class CommitThenFailReplyWriter(ReplyWriter):
    """Injected reply writer whose first write commits the row and then raises.

    Models an uncertain write (the row is stored but the caller sees an
    error), so a settlement retry must neither lose nor duplicate the reply.
    """

    def __init__(self, *, gateway: ChannelGateway) -> None:
        """Bind the real writer and arm one failure."""
        super().__init__(gateway=gateway)
        self.attempts: int = 0

    async def write(self, *, request: ChannelMessageDAO, outcome: TurnOutcomeDAO) -> None:
        """Delegate to the real writer; raise after the first committed write."""
        self.attempts += 1
        await super().write(request=request, outcome=outcome)
        if self.attempts == 1:
            raise OSError("reply write outcome unknown")


class RaisingAfterStartTurnRunner:
    """TurnRunner stub that starts the turn and then raises an unexpected error."""

    def __init__(self) -> None:
        """Record no runs."""
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Accept the row, then fail on the first row only."""
        self.ran.append(message.id)
        await on_started()
        if len(self.ran) == 1:
            raise RuntimeError("runner crashed")
        return TurnOutcomeDAO(status="completed", final_text="second ok")


async def _replies_to(*, gateway: ChannelGateway, user_id: UUID, request_id: UUID) -> list[ChannelMessageDAO]:
    """Return every reply row (pending outbound) that answers one request."""
    outbound: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(recipient_ids=[user_id])
    return [row for row in outbound if row.in_reply_to_id == request_id]


class TestPollerSettlementIsRetained:
    """A finished run's settlement survives stop and write failure (1081-R05)."""

    async def test_stop_during_a_run_settles_it_with_exactly_one_reply(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        release: asyncio.Event = asyncio.Event()
        runner: BlockingTurnRunner = BlockingTurnRunner(release=release)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        try:
            await poller.start()
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="long", channel_id=channel.id
                )
            )
            await _wait_until(predicate=lambda: len(runner.ran) == 1)
            stopping: asyncio.Task[None] = asyncio.create_task(poller.stop(reason="session_closed"))
            await asyncio.sleep(0.1)
            release.set()
            await asyncio.wait_for(stopping, timeout=10)
            replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, user_id=user.id, request_id=request.id
            )
            assert [reply.message_contents for reply in replies] == ["unblocked"]
            assert runner.ran == [request.id]
        finally:
            release.set()
            await gateway.close()

    async def test_a_failed_reply_write_is_retried_without_rerunning_or_duplicating(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox

        writer: CommitThenFailReplyWriter = CommitThenFailReplyWriter(gateway=gateway)
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=writer,
            boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id),
            interval=0.02,
        )
        try:
            await poller.start()
            first: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="one", channel_id=channel.id
                )
            )
            second: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="two", channel_id=channel.id
                )
            )
            async with asyncio.timeout(10.0):
                while len(await _replies_to(gateway=gateway, user_id=user.id, request_id=second.id)) != 1:
                    await asyncio.sleep(0.02)
            first_replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, user_id=user.id, request_id=first.id
            )
            assert [reply.message_contents for reply in first_replies] == ["done:one"]
            assert runner.ran == [first.id, second.id]
            assert writer.attempts >= 3
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_a_runner_crash_after_start_replies_once_and_the_queue_continues(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        runner: RaisingAfterStartTurnRunner = RaisingAfterStartTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner)
        try:
            await poller.start()
            first: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="one", channel_id=channel.id
                )
            )
            second: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="two", channel_id=channel.id
                )
            )
            async with asyncio.timeout(10.0):
                while len(await _replies_to(gateway=gateway, user_id=user.id, request_id=second.id)) != 1:
                    await asyncio.sleep(0.02)
            first_replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, user_id=user.id, request_id=first.id
            )
            assert len(first_replies) == 1 and "runner crashed" in first_replies[0].message_contents
            assert runner.ran == [first.id, second.id]
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_writing_the_same_reply_twice_stores_one_row_with_a_stable_id(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        try:
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="q", channel_id=channel.id
                )
            )
            writer: ReplyWriter = ReplyWriter(gateway=gateway)
            outcome: TurnOutcomeDAO = TurnOutcomeDAO(status="completed", final_text="a")
            await writer.write(request=request, outcome=outcome)
            await writer.write(request=request, outcome=outcome)
            replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, user_id=user.id, request_id=request.id
            )
            assert len(replies) == 1
            assert replies[0].id == ReplyWriter.reply_id_for(request_id=request.id)
        finally:
            await gateway.close()


class TestPollerReplyToClosedSender:
    """A prompt whose sender closed before the reply settles terminally (closed-reply fix)."""

    async def test_prompt_from_a_closed_workflow_settles_without_a_reply_and_the_next_prompt_runs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Journey: workflow W sends P and closes; S runs P once, drops the refused reply, then runs Q.

        Real SQLite gateway and participants, real ``SloAgentSession`` driven by the
        production-shaped ``SessionTurnRunner``, ``FauxChatModel`` at the provider
        boundary, real ``ChannelBoundaryInbox``; the poller loop is the entry point.
        """
        caplog.set_level(logging.WARNING, logger="slo")
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            session_id=str(session_id),
            responses=[AIMessage(content="answer for W"), AIMessage(content="unblocked")],
        )
        boundary_inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=SessionTurnRunner(session=session),
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=boundary_inbox,
            interval=0.02,
            durable_inbox=True,
        )
        try:
            await poller.start()
            # Hold the queue while W sends P and closes, so P is still queued when W is gone.
            poller.pause(reason="test_hold")
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id,
                    recipient_id=agent.id,
                    message_contents="report from W",
                    message_type="prompt",
                )
            )
            await gateway.close_agent(session_id=workflow.id, reason="recipient_closed")
            closed_workflow: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=workflow.id
            )
            assert closed_workflow is not None and closed_workflow.status == "closed"
            follow_up: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="next", channel_id=channel.id
                )
            )
            poller.resume()

            async with asyncio.timeout(10.0):
                while len(await _replies_to(gateway=gateway, user_id=user.id, request_id=follow_up.id)) != 1:
                    await asyncio.sleep(0.02)
            await _wait_until(predicate=lambda: poller.current_run_task is None)

            follow_up_replies: list[ChannelMessageDAO] = await _replies_to(
                gateway=gateway, user_id=user.id, request_id=follow_up.id
            )
            assert [reply.message_contents for reply in follow_up_replies] == ["unblocked"]
            stored_request: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=request.id)
            assert stored_request is not None
            assert stored_request.accepted_at is not None and stored_request.cancelled_at is None
            assert await gateway.find_message(message_id=ReplyWriter.reply_id_for(request_id=request.id)) is None
            assert await gateway.list_pending_outbound_messages(recipient_ids=[workflow.id]) == []
            history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
            events: list[SessionHistoryEventDAO] = await history.load_events(session_id=str(session_id))
            assert [
                event.payload.metadata.get("channel_message_id")
                for event in events
                if event.kind == "user_message"
            ] == [str(request.id), str(follow_up.id)]
            assert poller.busy is False and poller.paused is None
            assert await poller.pending_prompts() == []
            # The inbox exposes no reader for reservations, and an accepted row is
            # never pending again, so a leaked reservation has no behavioral
            # symptom; read the set directly (read-only) to prove release.
            assert request.id not in boundary_inbox._reserved_ids
            refused_diagnostics: list[logging.LogRecord] = [
                record
                for record in caplog.records
                if record.levelno == logging.WARNING
                and str(request.id) in record.getMessage()
                and str(workflow.id) in record.getMessage()
            ]
            assert len(refused_diagnostics) == 1
            assert not [
                record
                for record in caplog.records
                if "channel poller run settlement failed" in record.getMessage()
            ]
        finally:
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_closed_sender_reply_settles_when_the_diagnostic_log_fails(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A raising log handler on ``slo`` cannot keep the refused run from settling (CR-7)."""
        caplog.set_level(logging.WARNING, logger="slo")
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
        runner: RecordingTurnRunner = RecordingTurnRunner()
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        boundary_inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=boundary_inbox,
            interval=0.02,
            durable_inbox=True,
        )
        slo_logger: logging.Logger = logging.getLogger("slo")
        failing_handler: Optional[RaisingLogHandler] = None
        try:
            await poller.start()
            poller.pause(reason="test_hold")
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id,
                    recipient_id=agent.id,
                    message_contents="report from W",
                    message_type="prompt",
                )
            )
            await gateway.close_agent(session_id=workflow.id, reason="recipient_closed")
            follow_up: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="next", channel_id=channel.id
                )
            )
            failing_handler = RaisingLogHandler(fragment=str(request.id))
            slo_logger.addHandler(failing_handler)
            poller.resume()

            async with asyncio.timeout(10.0):
                while len(await _replies_to(gateway=gateway, user_id=user.id, request_id=follow_up.id)) != 1:
                    await asyncio.sleep(0.02)
            await _wait_until(predicate=lambda: poller.current_run_task is None)

            assert failing_handler.raised == 1
            assert runner.ran == [request.id, follow_up.id]
            assert await gateway.find_message(message_id=ReplyWriter.reply_id_for(request_id=request.id)) is None
            assert poller.busy is False and poller.paused is None
            # Read-only: the inbox has no public reservation reader (see the first journey).
            assert request.id not in boundary_inbox._reserved_ids
            assert not [
                record
                for record in caplog.records
                if "channel poller run settlement failed" in record.getMessage()
            ]
        finally:
            if failing_handler is not None:
                slo_logger.removeHandler(failing_handler)
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_aborted_turn_for_a_closed_sender_settles_paused_without_a_reply(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An aborted run whose sender closed mid-run settles, stays paused, and Q waits for resume (CR-10)."""
        caplog.set_level(logging.WARNING, logger="slo")
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        channel, user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
        release: asyncio.Event = asyncio.Event()
        runner: AbortsFirstRunTurnRunner = AbortsFirstRunTurnRunner(release=release)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        boundary_inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=boundary_inbox,
            interval=0.02,
            durable_inbox=True,
        )
        try:
            await poller.start()
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id,
                    recipient_id=agent.id,
                    message_contents="report from W",
                    message_type="prompt",
                )
            )
            await _wait_until(predicate=lambda: runner.ran == [request.id])
            await gateway.close_agent(session_id=workflow.id, reason="recipient_closed")
            follow_up: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="next", channel_id=channel.id
                )
            )
            release.set()
            await _wait_until(predicate=lambda: poller.current_run_task is None)

            assert poller.paused == "aborted" and poller.busy is False
            assert await gateway.find_message(message_id=ReplyWriter.reply_id_for(request_id=request.id)) is None
            assert await gateway.list_pending_outbound_messages(recipient_ids=[workflow.id]) == []
            assert request.id not in boundary_inbox._reserved_ids
            # The aborted pause holds Q across several poll intervals.
            await asyncio.sleep(0.2)
            assert runner.ran == [request.id]
            queued_follow_up: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=follow_up.id)
            assert queued_follow_up is not None and queued_follow_up.accepted_at is None
            assert poller.paused == "aborted"

            poller.resume()
            async with asyncio.timeout(10.0):
                while len(await _replies_to(gateway=gateway, user_id=user.id, request_id=follow_up.id)) != 1:
                    await asyncio.sleep(0.02)
            assert runner.ran == [request.id, follow_up.id]
            refused_diagnostics: list[logging.LogRecord] = [
                record
                for record in caplog.records
                if record.levelno == logging.WARNING and str(request.id) in record.getMessage()
            ]
            assert len(refused_diagnostics) == 1
            assert not [
                record
                for record in caplog.records
                if "channel poller run settlement failed" in record.getMessage()
            ]
        finally:
            release.set()
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_stop_settles_a_run_for_a_closed_sender_without_a_settlement_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``stop`` owns P's unfinished run, W closes mid-run, and stop settles it cleanly (CR-11)."""
        caplog.set_level(logging.WARNING, logger="slo")
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_id: UUID = uuid4()
        _channel, _user, agent = await _register_tui_participants(gateway=gateway, session_id=session_id)
        workflow: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
        release: asyncio.Event = asyncio.Event()
        runner: BlockingTurnRunner = BlockingTurnRunner(release=release)
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=str(session_id), responses=[AIMessage(content="unused")]
        )
        boundary_inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
        poller: ChannelPoller = ChannelPoller(
            gateway=gateway,
            session=session,
            runner=runner,
            replies=ReplyWriter(gateway=gateway),
            boundary_inbox=boundary_inbox,
            interval=0.02,
            durable_inbox=True,
        )
        try:
            await poller.start()
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=workflow.id,
                    recipient_id=agent.id,
                    message_contents="report from W",
                    message_type="prompt",
                )
            )
            await _wait_until(predicate=lambda: runner.ran == [request.id])
            await gateway.close_agent(session_id=workflow.id, reason="recipient_closed")
            stopping: asyncio.Task[None] = asyncio.create_task(poller.stop(reason="session_closed"))
            # Read-only coordination: once stop has cancelled and joined the loop
            # (``_task`` cleared), only stop can settle the run, so releasing the
            # runner now proves stop owns the settlement. No public reader exists.
            await _wait_until(predicate=lambda: poller._task is None)
            assert poller.busy is True
            release.set()
            await asyncio.wait_for(stopping, timeout=10)

            assert runner.ran == [request.id]
            assert poller.current_run_task is None and poller.busy is False
            assert request.id not in boundary_inbox._reserved_ids
            assert await gateway.find_message(message_id=ReplyWriter.reply_id_for(request_id=request.id)) is None
            assert await gateway.list_pending_outbound_messages(recipient_ids=[workflow.id]) == []
            closed_session: Optional[ParticipantDAO] = await gateway.find_participant(participant_id=agent.id)
            assert closed_session is not None and closed_session.status == "closed"
            refused_diagnostics: list[logging.LogRecord] = [
                record
                for record in caplog.records
                if record.levelno == logging.WARNING and str(request.id) in record.getMessage()
            ]
            assert len(refused_diagnostics) == 1
            assert not [
                record
                for record in caplog.records
                if "could not settle its last run on stop" in record.getMessage()
                or "channel poller run settlement failed" in record.getMessage()
            ]
        finally:
            release.set()
            await gateway.close()


class RaisingLogHandler(logging.Handler):
    """Injected log handler that raises for records naming one fragment (CR-7).

    Added through the public ``logging.getLogger("slo").addHandler``; counts
    each raise so the test proves the diagnostic really failed.
    """

    def __init__(self, *, fragment: str) -> None:
        """Arm the handler for records whose message contains ``fragment``."""
        super().__init__(level=logging.WARNING)
        self._fragment: str = fragment
        self.raised: int = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Raise for a matching record; ignore every other record."""
        if self._fragment not in record.getMessage():
            return
        self.raised += 1
        raise RuntimeError("diagnostic sink unavailable")


class AbortsFirstRunTurnRunner:
    """TurnRunner stub: the first run blocks until released and reports ``aborted``; later runs complete."""

    def __init__(self, *, release: asyncio.Event) -> None:
        """Bind the release event that ends the first run."""
        self._release: asyncio.Event = release
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Accept the row; abort the first run after release, complete the rest."""
        self.ran.append(message.id)
        await on_started()
        if len(self.ran) > 1:
            return TurnOutcomeDAO(status="completed", final_text="after resume")
        await self._release.wait()
        return TurnOutcomeDAO(status="aborted")
