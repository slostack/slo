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
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller, ChannelDisplaySink
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO, TurnRunner
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
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=second.id)
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
                    await gateway.get(message_id=row.id) for row in rows
                ]
                replies: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
                return (
                    all(stored is not None and stored.accepted_at is not None for stored in stored_rows)
                    and len(replies) == 3
                )

            deadline: float = asyncio.get_event_loop().time() + 10.0
            while not await _all_accepted_and_answered():
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError("rows were not all accepted and answered in time")
                await asyncio.sleep(0.02)

            replies: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
            assert {reply.in_reply_to_id for reply in replies} == {row.id for row in rows}
            for row in rows:
                stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
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
            outbound: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
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
                stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=request.id)
                return stored is not None and stored.accepted_at is not None

            async def _reply_present() -> bool:
                return bool(await gateway.pending_outbound(recipient_ids=[user.id]))

            async def _done() -> bool:
                return await _request_accepted() and await _reply_present()

            deadline: float = asyncio.get_event_loop().time() + 15.0
            while not await _done():
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError("poller did not accept and answer the row in time")
                await asyncio.sleep(0.02)

            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=request.id)
            assert stored is not None and stored.accepted_at is not None

            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            user_events = [event for event in events if event.kind == "user_message"]
            assert [event.payload.content for event in user_events] == ["hello"]
            assert user_events[0].payload.metadata.get("channel_message_id") == str(request.id)

            outbound: list[ChannelMessageDAO] = await gateway.pending_outbound(recipient_ids=[user.id])
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
    async def test_idle_note_is_displayed_recorded_and_accepted_without_a_run(
        self, tmp_path: Path
    ) -> None:
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
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner, display=display)
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
                    stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
                    if stored is not None and stored.accepted_at is not None:
                        break
                    await asyncio.sleep(0.02)
            assert [row.id for row in display.shown] == [note.id]
            assert runner.ran == []
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            workflow_updates = [event for event in events if event.kind == "workflow_update"]
            assert [event.payload.content for event in workflow_updates] == [
                "[workflow wf-ab] phase 1 done"
            ]
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
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner, display=display)
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
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
            assert stored is not None and stored.accepted_at is None and stored.cancelled_at is None
            assert runner.ran == [  # the note never started a run
                runner.ran[0]
            ]
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=str(session_id))
            assert [event for event in events if event.kind == "workflow_update"] == []
        finally:
            release.set()
            await poller.stop(reason="test_done")
            await gateway.close()

    async def test_notice_is_displayed_and_accepted_without_entering_context(
        self, tmp_path: Path
    ) -> None:
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
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner, display=display)
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
                    stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=notice.id)
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

    async def test_a_pending_prompt_is_never_displayed_as_a_note_or_notice(
        self, tmp_path: Path
    ) -> None:
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
        poller: ChannelPoller = _build_poller(gateway=gateway, session=session, runner=runner, display=display)
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
    async def test_auto_run_false_never_starts_runs_but_keeps_the_boundary_live(
        self, tmp_path: Path
    ) -> None:
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
