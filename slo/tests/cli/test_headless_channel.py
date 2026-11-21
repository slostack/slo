"""Headless workflow channel lifecycle tests (108.3 O4/O5/O7).

Journey: a workflow-mode ``HeadlessRunner`` registers its orchestrator
participant, keeps the boundary inbox live through an ``auto_run=False``
poller, drains queued normal prompts as follow-up turns, and closes the
participant atomically. Real SQLite, real sessions with ``FauxChatModel`` at
the provider boundary; recording stubs are injected through constructors.
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
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.cli.headless import HeadlessRunner


class _RecordingNotifier:
    """Notifier stub recording every lifecycle call (injected, not a mock)."""

    def __init__(self) -> None:
        """Start with an empty call log."""
        self.calls: list[tuple[str, dict]] = []

    async def started(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("started", kwargs))

    async def phase_update(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("phase_update", kwargs))

    async def fleet_update(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("fleet_update", kwargs))

    async def completed(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("completed", kwargs))

    async def failed(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("failed", kwargs))

    async def aborted(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.calls.append(("aborted", kwargs))


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one real gateway on a fresh temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


class _RecordingTurnRunner:
    """TurnRunner stub reporting completed outcomes for every run."""

    def __init__(self) -> None:
        """Start with an empty run log."""
        self.ran: list[UUID] = []

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Record the row, accept it, and report completion."""
        self.ran.append(message.id)
        await on_started()
        return TurnOutcomeDAO(status="completed", final_text=f"done:{message.message_contents}")


def _build_session(
    *,
    tmp_path: Path,
    session_id: str,
    responses: list[AIMessage],
) -> SloAgentSession:
    """Build a real session with the faux provider and a real history store."""
    history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(
        root=tmp_path / "history"
    )
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id,
        history_store=history_store,
        enable_history=True,
    )


def _session_preparer(
    session: SloAgentSession,
) -> Callable[[object], Awaitable[SloAgentSession]]:
    """Return an async preparer yielding the prebuilt session.

    Args:
        session (SloAgentSession): The session to hand back.

    Returns:
        Callable: Async preparer matching the runner's seam.
    """

    async def _prepare(config: object) -> SloAgentSession:
        del config
        return session

    return _prepare


class TestWorkflowModeFollowUps:
    """O4: a normal message to W during its final turn runs as a follow-up."""

    async def test_normal_prompt_runs_as_follow_up_and_replies_to_its_sender(
        self, tmp_path: Path
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(
                channel_id=channel.id, name="tester (tui)"
            )
            orchestrator_session_id: str = str(uuid4())
            agent: ParticipantDAO = await gateway.register_agent(
                session_id=UUID(orchestrator_session_id), name="slo orchestrator"
            )
            session: SloAgentSession = _build_session(
                tmp_path=tmp_path,
                session_id=orchestrator_session_id,
                responses=[AIMessage(content="main answer"), AIMessage(content="follow-up answer")],
            )
            notifier: _RecordingNotifier = _RecordingNotifier()
            from src.agents.slo_agent.sessions.dao import SessionConfigDAO

            config: SessionConfigDAO = SessionConfigDAO(
                workdir=tmp_path,
                model_name="faux",
                enable_history=False,
                session_id=orchestrator_session_id,
            )
            runner: HeadlessRunner = HeadlessRunner(
                config=config,
                notify_session_id="tui-owner",
                notifier=notifier,  # type: ignore[arg-type]
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
            )
            # The operator's prompt is already queued while W runs its main turn.
            prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="what happened?",
                    channel_id=channel.id,
                )
            )
            exit_code: int = await runner.invoke(prompt="do the workflow")

            assert exit_code == 0
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=prompt.id)
            assert stored is not None and stored.accepted_at is not None
            replies: list[ChannelMessageDAO] = await gateway.pending_outbound(
                recipient_ids=[user.id]
            )
            assert len(replies) == 1
            reply: ChannelMessageDAO = replies[0]
            assert reply.message_type == "reply"
            assert reply.in_reply_to_id == prompt.id
            assert reply.message_contents == "follow-up answer"
            assert reply.sender_id == agent.id
            # W is closed and its pending rows are gone once the follow-ups ran.
            closed = await gateway.get_participant(participant_id=agent.id)
            assert closed is not None and closed.status == "closed"
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
            # The terminal notification used the LAST run's final text.
            assert [name for name, _kwargs in notifier.calls] == ["started", "completed"]
            assert notifier.calls[-1][1]["synthesis"] == "follow-up answer"
        finally:
            await gateway.close()


class TestNonWorkflowHeadless:
    """O7: headless runs not in workflow mode register no participant."""

    async def test_plain_headless_run_touches_no_queue_participant(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            from src.agents.slo_agent.sessions.dao import SessionConfigDAO

            config: SessionConfigDAO = SessionConfigDAO(
                workdir=tmp_path, model_name="faux", enable_history=False
            )
            session = _build_session(
                tmp_path=tmp_path,
                session_id=str(uuid4()),
                responses=[AIMessage(content="plain answer")],
            )
            runner: HeadlessRunner = HeadlessRunner(
                config=config,
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
            )
            exit_code: int = await runner.invoke(prompt="plain run")
            assert exit_code == 0
            assert await gateway.repository_count_participants() == 0
        finally:
            await gateway.close()


class TestSendCloseRace:
    """O5: a send racing W's close is accepted or cancelled, never left pending."""

    async def test_hundred_send_close_iterations_leave_no_pending_rows(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(
                channel_id=channel.id, name="tester (tui)"
            )
            runner_stub: _RecordingTurnRunner = _RecordingTurnRunner()
            for _iteration in range(100):
                session_id: UUID = uuid4()
                session: SloAgentSession = _build_session(
                    tmp_path=tmp_path,
                    session_id=str(session_id),
                    responses=[AIMessage(content="unused")],
                )
                poller: ChannelPoller = ChannelPoller(
                    gateway=gateway,
                    session=session,
                    runner=runner_stub,
                    replies=ReplyWriter(gateway=gateway),
                    boundary_inbox=ChannelBoundaryInbox(gateway=gateway, agent_id=session_id),
                    interval=0.001,
                )
                await poller.start()
                row: ChannelMessageDAO = await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id,
                        recipient_id=session_id,
                        message_contents="late prompt",
                        channel_id=channel.id,
                    )
                )
                stop_reason: str = "recipient_closed"
                close_task: asyncio.Task[int] = asyncio.create_task(
                    gateway.close_agent(session_id=session_id, reason=stop_reason)
                )
                await close_task
                # Give the poller a tick to accept the row when it won the race.
                await asyncio.sleep(0.02)
                await poller.stop(reason=stop_reason)
                stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
                assert stored is not None
                assert (
                    stored.accepted_at is not None
                    or (
                        stored.cancelled_at is not None
                        and stored.cancel_reason == stop_reason
                    )
                ), f"iteration {_iteration}: row left pending"
        finally:
            await gateway.close()
