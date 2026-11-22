"""R4 journey (108.3 §6): a workflow that reports while its TUI session is closed is not lost.

The real ``WorkflowNotifier`` sends W's terminal prompt to session S after S
closed (``session_closed``). The row waits in the queue; when S opens again
its poller runs it exactly once, without the operator resuming a pause. A
finished workflow participant keeps refusing sends once closed. Real SQLite,
real sessions with a real filesystem history store; ``FauxChatModel`` at the
provider boundary only.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import RecipientClosedError
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


class SessionTurnRunner:
    """Runs each prompt row through the real session and records the row ids."""

    def __init__(self, *, session: SloAgentSession) -> None:
        """Bind the runner to one session."""
        self._session: SloAgentSession = session
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Run the row and accept it on the first event."""
        self.ran.append(message.id)
        started: bool = False
        final_text: str = ""
        async for event in self._session.invoke(text=message.message_contents, channel_message_id=message.id):
            if not started:
                started = True
                await on_started()
            if event.kind == "run_completed":
                final_text = event.content or ""
        return TurnOutcomeDAO(status="completed" if started else "not_started", final_text=final_text)


def _build_session(*, tmp_path: Path, session_id: str, responses: list[AIMessage]) -> SloAgentSession:
    """Build a real session over the shared temp history root."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


async def _wait_until(*, predicate: Callable[[], object], timeout_seconds: float = 10.0) -> None:
    """Poll a sync or async predicate until it holds."""
    async with asyncio.timeout(timeout_seconds):
        while True:
            result: object = predicate()
            if inspect.isawaitable(result):
                result = await result
            if result:
                return
            await asyncio.sleep(0.01)


async def test_workflow_report_to_a_closed_session_runs_once_when_it_reopens(tmp_path: Path) -> None:
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    session_id: str = str(uuid4())
    workflow_session_id: str = str(uuid4())
    try:
        channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
        operator: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
        first_session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=session_id, responses=[AIMessage(content="unused")]
        )
        first_runner: SessionTurnRunner = SessionTurnRunner(session=first_session)
        await first_session.start_channel_delivery(
            gateway=gateway, runner=first_runner, interval=0.02, durable_inbox=True
        )
        await first_session.stop_channel_delivery(reason="session_closed")

        notifier: WorkflowNotifier = WorkflowNotifier(
            gateway=gateway,
            target_session_id=session_id,
            orchestrator_session_id=workflow_session_id,
            workflow_id="wf-closed-s",
        )
        await notifier.completed(synthesis="all phases done", result_json="{}", cleanup_summary="")
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(session_id))
        assert len(pending) == 1 and pending[0].message_type == "prompt"
        workflow_row: ChannelMessageDAO = pending[0]

        reopened_session: SloAgentSession = _build_session(
            tmp_path=tmp_path, session_id=session_id, responses=[AIMessage(content="noted the workflow")]
        )
        reopened_runner: SessionTurnRunner = SessionTurnRunner(session=reopened_session)
        poller: ChannelPoller = await reopened_session.start_channel_delivery(
            gateway=gateway, runner=reopened_runner, interval=0.02, durable_inbox=True
        )
        try:
            assert poller.paused is None

            async def _accepted() -> bool:
                stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=workflow_row.id)
                return stored is not None and stored.accepted_at is not None

            await _wait_until(predicate=_accepted)
            await _wait_until(predicate=lambda: not poller.busy)
            await asyncio.sleep(0.1)
            assert reopened_runner.ran == [workflow_row.id]
            assert first_runner.ran == []
            # The reply goes back to W, so it belongs to W's conversation (§2.4).
            replies: list[ChannelMessageDAO] = await gateway.conversation(
                agent_session_id=UUID(workflow_session_id)
            )
            assert [row.message_contents for row in replies if row.in_reply_to_id == workflow_row.id] == [
                "noted the workflow"
            ]
        finally:
            await reopened_session.stop_channel_delivery(reason="session_closed")

        # A finished workflow participant still refuses sends once closed.
        await gateway.close_agent(session_id=UUID(workflow_session_id), reason="recipient_closed")
        with pytest.raises(RecipientClosedError):
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=operator.id, recipient_id=UUID(workflow_session_id), message_contents="late"
                )
            )
    finally:
        await gateway.close()
