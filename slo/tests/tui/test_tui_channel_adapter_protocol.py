"""TuiChannelAdapter conforms to the full channel protocol (108.5 §7 Edit row).

Level: the real adapter over a real SQLite queue under ``tmp_path``. The app
is a narrow stand-in exposing only what the adapter reads (the session and an
unmounted transcript), so no Textual app is booted; mounted TUI delivery is
covered by ``tests/tui/test_channel_adapter.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.protocol import ChannelAdapter
from src.channels.repository import ChannelRepository
from src.tui.channel.adapter import TuiChannelAdapter


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
