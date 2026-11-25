"""Session channel-delivery surface tests (108.1 M1, 108.2 F4).

Journey: ``SloAgentSession.invoke(channel_message_id=…)`` stamps the channel id
onto the ``user_message`` history event; ``start_channel_delivery`` owns one
``ChannelPoller`` per session and rebinds the agent's boundary inbox; recovery
reads the ids already persisted (user messages and applied steering rows).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.boundary_inbox import BoundaryInbox, MemoryBoundaryInbox
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from tests.agents.slo_agent.channel_delivery.test_channel_poller import (
    RecordingTurnRunner,
    _wait_until,
)


def _build_session(*, tmp_path: Path, responses: list[AIMessage]) -> SloAgentSession:
    """Build a real session with the faux provider and a real history store."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


class TestInvokeChannelMessageId:
    async def test_user_message_event_carries_the_channel_message_id(self, tmp_path: Path) -> None:
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="hi")],
        )
        message_id = uuid4()
        async for _event in session.invoke(text="hello", channel_message_id=message_id):
            pass
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        user_events = [event for event in events if event.kind == "user_message"]
        assert len(user_events) == 1
        assert user_events[0].payload.metadata.get("channel_message_id") == str(message_id)

    async def test_invoke_without_channel_id_leaves_metadata_empty(self, tmp_path: Path) -> None:
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="hi")],
        )
        async for _event in session.invoke(text="hello"):
            pass
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        user_events = [event for event in events if event.kind == "user_message"]
        assert len(user_events) == 1
        assert "channel_message_id" not in user_events[0].payload.metadata

    async def test_channel_message_ids_in_history_reads_persisted_ids(self, tmp_path: Path) -> None:
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="one"), AIMessage(content="two")],
        )
        first, second = uuid4(), uuid4()
        async for _event in session.invoke(text="one", channel_message_id=first):
            pass
        async for _event in session.invoke(text="two", channel_message_id=second):
            pass
        known: set[str] = await session.channel_message_ids_in_history()
        assert known == {str(first), str(second)}


class TestStartChannelDelivery:
    async def test_start_and_stop_channel_delivery_own_one_poller(self, tmp_path: Path) -> None:
        from tests.agents.slo_agent.channel_delivery.test_channel_poller import RecordingTurnRunner

        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="unused")],
        )
        from src.channels.gateway import ChannelGateway
        from src.channels.repository import ChannelRepository

        repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        await repository.open()
        gateway: ChannelGateway = ChannelGateway(repository=repository)
        try:
            poller: ChannelPoller = await session.start_channel_delivery(
                gateway=gateway,
                runner=RecordingTurnRunner(),
                interval=0.02,
            )
            assert session.channel_poller is poller
            assert poller is not None
            await session.stop_channel_delivery(reason="test_done")
            assert session.channel_poller is None
        finally:
            await gateway.close()


class TestSessionBoundaryInbox:
    async def test_start_channel_delivery_rebinds_the_agent_inbox_to_the_channel(
        self, tmp_path: Path
    ) -> None:
        """Delivery start swaps the memory inbox for the channel adapter (both agent and session)."""
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="unused")],
        )
        repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        await repository.open()
        gateway: ChannelGateway = ChannelGateway(repository=repository)
        try:
            memory_inbox = session.boundary_inbox
            await session.start_channel_delivery(
                gateway=gateway,
                runner=RecordingTurnRunner(),
                interval=0.02,
            )
            poller: ChannelPoller = session.channel_poller  # type: ignore[assignment]
            channel_inbox = session.boundary_inbox
            assert isinstance(channel_inbox, ChannelBoundaryInbox)
            assert channel_inbox is not memory_inbox
            assert session.agent.boundary_inbox is channel_inbox
            assert poller.boundary_inbox is channel_inbox

            await session.stop_channel_delivery(reason="test_done")
            reverted = session.boundary_inbox
            assert isinstance(reverted, MemoryBoundaryInbox)
            assert session.agent.boundary_inbox is reverted
        finally:
            await gateway.close()


class TestForcedRowRecovery:
    """F4: a pending forced row is accepted on restart only when history has its id."""

    async def _open_world(
        self, *, tmp_path: Path
    ) -> tuple[ChannelGateway, SloAgentSession, RecordingTurnRunner]:
        """Open a gateway and a session with no poller running yet."""
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="unused")],
        )
        repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        await repository.open()
        gateway: ChannelGateway = ChannelGateway(repository=repository)
        runner: RecordingTurnRunner = RecordingTurnRunner()
        return gateway, session, runner

    async def _agent_participant_id(self, *, session: SloAgentSession, gateway: ChannelGateway) -> UUID:
        """Register and return the agent's queue participant id for one session id."""
        from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session

        participant_id: UUID = channel_participant_id_for_session(session_id=session.session_id)
        await gateway.register_agent(session_id=participant_id, name="slo abc12345")
        return participant_id

    async def test_pending_forced_row_in_history_is_accepted_and_never_rerun(self, tmp_path: Path) -> None:
        """A crash after the history record but before accept → restart accepts, never re-applies."""
        gateway, session, runner = await self._open_world(tmp_path=tmp_path)
        try:
            agent_participant: UUID = await self._agent_participant_id(session=session, gateway=gateway)
            forced_row: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=agent_participant,
                    recipient_id=agent_participant,
                    message_contents="use pytest -x",
                    force=True,
                )
            )
            # The crashed process took the row, wrote the steering record, and
            # died before accepting it (108.2 §2 order).
            assert session.history_store is not None
            await session.history_store.ensure_session(
                session_id=session.session_id,
                workdir=tmp_path,
                model_name=None,
            )
            await session.history_store.append_event(
                event=SessionHistoryEventDAO(
                    kind="steering_message",
                    session_id=session.session_id,
                    payload=SessionHistoryEventPayloadDAO(
                        content="use pytest -x",
                        metadata={"channel_message_id": str(forced_row.id)},
                    ),
                )
            )
            poller: ChannelPoller = await session.start_channel_delivery(
                gateway=gateway,
                runner=runner,
                interval=0.02,
            )
            try:
                await asyncio.sleep(0.15)
                stored: ChannelMessageDAO | None = await gateway.find_message(message_id=forced_row.id)
                assert stored is not None and stored.accepted_at is not None
                assert runner.ran == []
                assert poller.paused is None
            finally:
                await session.stop_channel_delivery(reason="test_done")
        finally:
            await gateway.close()

    async def test_pending_forced_row_without_history_stays_pending_then_reruns_after_resume(
        self, tmp_path: Path
    ) -> None:
        """A crash before the history record → the poller pauses; resume re-runs the row once."""
        gateway, session, runner = await self._open_world(tmp_path=tmp_path)
        try:
            agent_participant: UUID = await self._agent_participant_id(session=session, gateway=gateway)
            channel = await gateway.register_channel(kind="tui", name="tui@testhost")
            operator = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            forced_row: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=operator.id,
                    recipient_id=agent_participant,
                    message_contents="use pytest -x",
                    force=True,
                )
            )
            poller: ChannelPoller = await session.start_channel_delivery(
                gateway=gateway,
                runner=runner,
                interval=0.02,
            )
            try:
                await asyncio.sleep(0.15)
                assert poller.paused == "recovered"
                stored: ChannelMessageDAO | None = await gateway.find_message(message_id=forced_row.id)
                assert stored is not None and stored.accepted_at is None
                assert runner.ran == []

                poller.resume()
                await asyncio.wait_for(
                    _wait_until(predicate=lambda: len(runner.ran) == 1),
                    timeout=5.0,
                )
                assert runner.ran == [forced_row.id]
                stored_after: ChannelMessageDAO | None = await gateway.find_message(message_id=forced_row.id)
                assert stored_after is not None and stored_after.accepted_at is not None
            finally:
                await session.stop_channel_delivery(reason="test_done")
        finally:
            await gateway.close()
