"""TuiChannelAdapter conforms to the full channel protocol (108.5 §7 Edit row).

Level: the real adapter over a real SQLite queue under ``tmp_path``. The app
is a narrow stand-in exposing only what the adapter reads (the session and an
unmounted transcript), so no Textual app is booted; mounted TUI delivery is
covered by ``tests/tui/test_channel_adapter.py``.
"""

from __future__ import annotations

import asyncio
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
import sqlite3


from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.protocol import ChannelAdapter
from src.channels.repository import ChannelRepository
from src.tui.channel.adapter import TuiChannelAdapter


class CloseUserLockedOnceGateway(ChannelGateway):
    """Fail the first presence write, then allow teardown to retry against SQLite."""

    close_failed: bool = False

    async def close_user(self, *, participant_id: UUID) -> None:
        """Refuse the initial close without mutating the stored participant."""
        if not self.close_failed:
            self.close_failed = True
            raise sqlite3.OperationalError("database is locked")
        await super().close_user(participant_id=participant_id)


class _AppStandIn:
    """Only the two attributes TuiChannelAdapter reads from SloTUI."""

    def __init__(self, *, session: SloAgentSession) -> None:
        self._session: SloAgentSession = session
        self._chat_transcript: Optional[object] = None


def _session(*, tmp_path: Path) -> SloAgentSession:
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=False,
    )


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


class TestTuiAdapterProtocol:
    async def test_tui_adapter_is_a_channel_adapter_with_kind_and_name(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: TuiChannelAdapter = TuiChannelAdapter(
            app=_AppStandIn(session=_session(tmp_path=tmp_path)), gateway=gateway  # type: ignore[arg-type]
        )
        try:
            assert isinstance(adapter, ChannelAdapter)
            assert adapter.kind == "tui"
            assert adapter.name.startswith("tui@")
        finally:
            await gateway.close()

    async def test_start_accepts_a_context_and_deliver_reports_true_after_accepting(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session: SloAgentSession = _session(tmp_path=tmp_path)
        adapter: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=session), gateway=gateway)  # type: ignore[arg-type]
        try:
            await adapter.start(ctx=None)
            agent: ParticipantDAO = await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=session.session_id), name="slo s"
            )
            notice: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=adapter.user_participant.id,
                    message_contents="heads up",
                    message_type="notice",
                )
            )

            delivered: bool = await adapter.deliver(message=notice, user=adapter.user_participant)

            assert delivered is True
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=notice.id)
            assert stored is not None and stored.accepted_at is not None
            assert adapter.channel.name == adapter.name
        finally:
            await adapter.stop()
            await gateway.close()

    async def test_other_session_outbound_inbox_never_sees_reply(self, tmp_path: Path) -> None:
        """Two TUI sessions share a channel, never an operator reply inbox (R1)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_a: SloAgentSession = _session(tmp_path=tmp_path)
        adapter_a: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=session_a), gateway=gateway)  # type: ignore[arg-type]
        adapter_b: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=_session(tmp_path=tmp_path)), gateway=gateway)  # type: ignore[arg-type]
        try:
            await adapter_a.start()
            await adapter_b.start()
            agent: ParticipantDAO = await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=session_a.session_id), name="agent A"
            )
            await adapter_a.stop()
            request: ChannelMessageDAO = await adapter_a.send_prompt(text="private prompt")
            reply: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id,
                    recipient_id=request.sender_id,
                    message_contents="private answer",
                    message_type="reply",
                    in_reply_to_id=request.id,
                    channel_id=request.channel_id,
                )
            )
            assert (
                await gateway.list_pending_outbound_messages(recipient_ids=[adapter_b.user_participant.id])
                == []
            )
            assert adapter_a.channel.id == adapter_b.channel.id
            assert adapter_a.user_participant.id != adapter_b.user_participant.id
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=reply.id)
            assert stored is not None and stored.accepted_at is None
        finally:
            await adapter_a.stop()
            await adapter_b.stop()
            await gateway.close()

    async def test_cross_agent_reply_is_displayed_once_only_by_sending_session(self, tmp_path: Path) -> None:
        """Real concurrent pollers route ReplyWriter output back to the sender (R2/R4)."""

        class Transcript:
            """Record the adapter's display boundary, without a Textual runtime."""

            def __init__(self) -> None:
                self.lines: list[TranscriptNoticeDAO] = []

            async def handle(self, *, command: TranscriptNoticeDAO) -> None:
                """Record one rendered line."""
                self.lines.append(command)

        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session_a: SloAgentSession = _session(tmp_path=tmp_path)
        session_b: SloAgentSession = _session(tmp_path=tmp_path)
        app_a: _AppStandIn = _AppStandIn(session=session_a)
        app_b: _AppStandIn = _AppStandIn(session=session_b)
        app_a._chat_transcript = Transcript()
        app_b._chat_transcript = Transcript()
        adapter_a: TuiChannelAdapter = TuiChannelAdapter(app=app_a, gateway=gateway)  # type: ignore[arg-type]
        adapter_b: TuiChannelAdapter = TuiChannelAdapter(app=app_b, gateway=gateway)  # type: ignore[arg-type]
        try:
            await adapter_a.start()
            await adapter_b.start()
            await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=session_b.session_id), name="agent B"
            )
            request: ChannelMessageDAO = await adapter_a.send_prompt_to_agent(
                session_id=session_b.session_id, text="help"
            )
            assert adapter_a.is_sent_by_operator(message=request)
            assert not adapter_b.is_sent_by_operator(message=request)
            assert not await gateway.force(message_id=request.id, by=adapter_b.user_participant.id)
            assert not await gateway.cancel(message_id=request.id, by=adapter_b.user_participant.id)
            assert len(await adapter_a.sent_to_agent(session_id=session_b.session_id)) == 1
            assert await adapter_b.sent_to_agent(session_id=session_b.session_id) == []

            own: ChannelMessageDAO = await adapter_b.send_prompt(text="own forced", force=True)
            assert await gateway.force(message_id=request.id, by=adapter_a.user_participant.id)
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(
                gateway=gateway,
                agent_id=own.recipient_id,
                operator_participant_id=adapter_b.user_participant.id,
            )
            labels: dict[UUID, str] = {
                row.message_id: row.sender_name for row in await inbox.take(iteration=1)
            }
            assert labels[own.id] == "you"
            assert labels[request.id] == adapter_a.user_participant.name
            note: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=adapter_a.user_participant.id,
                    recipient_id=own.recipient_id,
                    message_contents="note",
                    message_type="note",
                )
            )
            assert [row.id for row in await adapter_b.notes_to_agent(session_id=session_b.session_id)] == [
                note.id
            ]
            await ReplyWriter(gateway=gateway).write(
                request=request, outcome=TurnOutcomeDAO(status="completed", final_text="answer for A")
            )
            async with asyncio.timeout(3):
                while True:
                    reply: Optional[ChannelMessageDAO] = await gateway.find_reply(message_id=request.id)
                    if reply is not None and reply.accepted_at is not None:
                        break
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.6)
            assert len(app_a._chat_transcript.lines) == 1
            assert "answer for A" in app_a._chat_transcript.lines[0].content
            assert app_b._chat_transcript.lines == []
            assert not await gateway.accept(message_id=reply.id)
        finally:
            await adapter_a.stop()
            await adapter_b.stop()
            await gateway.close()

    async def test_restart_reclaims_operator_and_preserves_pending_reply(self, tmp_path: Path) -> None:
        """Same-session registration reclaims its durable operator slot (R3)."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        session: SloAgentSession = _session(tmp_path=tmp_path)
        adapter: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=session), gateway=gateway)  # type: ignore[arg-type]
        restarted: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=session), gateway=gateway)  # type: ignore[arg-type]
        try:
            await adapter.stop()  # Safe before registration.
            await adapter.start()
            user: ParticipantDAO = adapter.user_participant
            await adapter.stop()
            await adapter.stop()
            closed: Optional[ParticipantDAO] = await gateway.find_participant(participant_id=user.id)
            assert closed is not None and closed.status == "closed"
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="worker")
            reply: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent.id, recipient_id=user.id, message_contents="waiting", message_type="reply"
                )
            )
            await restarted.start()
            assert restarted.user_participant.id == user.id
            assert restarted.user_participant.status == "open"
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=reply.id)
            assert stored is not None and stored.cancelled_at is None
        finally:
            await adapter.stop()
            await restarted.stop()
            await gateway.close()

    async def test_repeated_stop_after_gateway_close_is_inert(self, tmp_path: Path) -> None:
        """Completed adapter teardown never touches a subsequently closed repository."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: TuiChannelAdapter = TuiChannelAdapter(app=_AppStandIn(session=_session(tmp_path=tmp_path)), gateway=gateway)  # type: ignore[arg-type]
        await adapter.start()
        await adapter.stop()
        await gateway.close()
        await adapter.stop()

    async def test_stop_retries_user_close_after_gateway_failure(self, tmp_path: Path) -> None:
        """Failed presence writes leave delivery stopped and retryable on later teardown."""
        gateway: CloseUserLockedOnceGateway = CloseUserLockedOnceGateway(
            repository=ChannelRepository(db_path=tmp_path / "channels.db")
        )
        await gateway.open()
        adapter: TuiChannelAdapter = TuiChannelAdapter(
            app=_AppStandIn(session=_session(tmp_path=tmp_path)), gateway=gateway  # type: ignore[arg-type]
        )

        try:
            await adapter.start()
            task: Optional[asyncio.Task[None]] = adapter._outbound_task
            assert task is not None
            await adapter.stop()
            assert task.done()
            assert adapter._outbound_task is None
            assert adapter._stopping
            assert adapter.user_participant.status == "open"
            await adapter.stop()
            stored: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=adapter.user_participant.id
            )
            assert stored is not None and stored.status == "closed"
        finally:
            await adapter.stop()
            await gateway.close()
