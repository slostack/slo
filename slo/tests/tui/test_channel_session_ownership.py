"""Two TUIs on one session: only the lease owner runs the queue (108.1 §6, 1081-R01).

Journey: two real ``SloTUI`` apps mount the same history-backed session id,
each with its own ``SloAgentSession``, its own gateway connection to one real
SQLite WAL database and its own lease store over the shared history root (as
two processes would). Exactly one acquires the exclusive ``owner.json`` lease
and starts a poller; a shared prompt row runs once, through one provider call,
with one history turn and one reply. Doubles: ``FauxChatModel`` at the
provider boundary only.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.ownership import SessionOwnershipLeaseStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent


def _build_session(*, tmp_path: Path, session_id: str, model: FauxChatModel) -> SloAgentSession:
    """Build one real history-backed session over the shared history root."""
    return SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one more real connection to the shared channels database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


def _transcript_contents(*, app: SloTUI) -> list[str]:
    """Return the recorded transcript line contents of one app."""
    transcript: ChatTranscriptComponent = app.query_one(ChatTranscriptComponent)
    assert transcript._adapter is not None
    return [content for content, _classes in transcript._adapter.lines]


class TestOnlyTheLeaseOwnerRunsTheQueue:
    async def test_two_tuis_on_one_session_run_a_shared_prompt_exactly_once(self, tmp_path: Path) -> None:
        session_id: str = str(uuid4())
        model_a: FauxChatModel = FauxChatModel(responses=[AIMessage(content="answer from A")])
        model_b: FauxChatModel = FauxChatModel(responses=[AIMessage(content="answer from B")])
        session_a: SloAgentSession = _build_session(tmp_path=tmp_path, session_id=session_id, model=model_a)
        session_b: SloAgentSession = _build_session(tmp_path=tmp_path, session_id=session_id, model=model_b)
        gateway_a: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        gateway_b: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        sender_gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app_a: SloTUI = SloTUI(
            session=session_a,
            channel_gateway=gateway_a,
            lease_store=SessionOwnershipLeaseStore(history_root=tmp_path / "history"),
        )
        app_b: SloTUI = SloTUI(
            session=session_b,
            channel_gateway=gateway_b,
            lease_store=SessionOwnershipLeaseStore(history_root=tmp_path / "history"),
        )
        agent_id: UUID = channel_participant_id_for_session(session_id=session_id)
        try:
            async with app_a.run_test() as pilot_a:
                await pilot_a.pause()
                assert session_a.channel_poller is not None
                async with app_b.run_test() as pilot_b:
                    await pilot_b.pause()
                    poller_b_started: bool = session_b.channel_poller is not None
                    b_notices: list[str] = _transcript_contents(app=app_b)

                    channel: ChannelDAO = await sender_gateway.register_channel(kind="cli", name="cli@test")
                    user: ParticipantDAO = await sender_gateway.register_user(
                        channel_id=channel.id, name="tester (cli)"
                    )
                    request: ChannelMessageDAO = await sender_gateway.send(
                        new=NewMessageDAO(
                            sender_id=user.id,
                            recipient_id=agent_id,
                            message_contents="shared prompt",
                            channel_id=channel.id,
                        )
                    )
                    async with asyncio.timeout(20.0):
                        while not await sender_gateway.list_pending_outbound_messages(
                            recipient_ids=[user.id]
                        ):
                            await pilot_a.pause(0.02)
                    # Give a second (wrong) owner every chance to run the row too.
                    for _ in range(25):
                        await pilot_b.pause(0.02)
                    replies: list[ChannelMessageDAO] = await sender_gateway.list_pending_outbound_messages(
                        recipient_ids=[user.id]
                    )
                    stored: Optional[ChannelMessageDAO] = await sender_gateway.find_message(
                        message_id=request.id
                    )
        finally:
            await sender_gateway.close()

        assert poller_b_started is False
        assert any("open in another TUI" in line for line in b_notices)
        assert [(reply.in_reply_to_id, reply.message_contents) for reply in replies] == [
            (request.id, "answer from A")
        ]
        assert stored is not None and stored.accepted_at is not None
        assert len(model_a.queue) == 0 and len(model_b.queue) == 1
        events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id=session_id
        )
        user_turns = [event for event in events if event.kind == "user_message"]
        assert [event.payload.content for event in user_turns] == ["shared prompt"]
        assert user_turns[0].payload.metadata.get("channel_message_id") == str(request.id)
