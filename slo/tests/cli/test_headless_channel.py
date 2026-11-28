"""Headless workflow channel lifecycle tests (108.3 O4/O5/O7).

Journey: a workflow-mode ``HeadlessRunner`` registers its orchestrator
participant, keeps the boundary inbox live through an ``auto_run=False``
poller, drains queued normal prompts as follow-up turns, and closes the
participant atomically. Real SQLite, real sessions with ``FauxChatModel`` at
the provider boundary; recording stubs are injected through constructors.
"""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import BaseTool
from pydantic import Field

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import RecipientClosedError
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
    history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path / "history")
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

    async def test_normal_prompt_runs_as_follow_up_and_replies_to_its_sender(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
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
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=prompt.id)
            assert stored is not None and stored.accepted_at is not None
            replies: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
            assert len(replies) == 1
            reply: ChannelMessageDAO = replies[0]
            assert reply.message_type == "reply"
            assert reply.in_reply_to_id == prompt.id
            assert reply.message_contents == "follow-up answer"
            assert reply.sender_id == agent.id
            # W is closed and its pending rows are gone once the follow-ups ran.
            closed = await gateway.find_participant(participant_id=agent.id)
            assert closed is not None and closed.status == "closed"
            assert await gateway.list_pending_inbound_messages(recipient_id=agent.id) == []
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
            assert await gateway.count_participants() == 0
        finally:
            await gateway.close()


class TestSendCloseRace:
    """O5: a send racing W's close is accepted or cancelled, never left pending."""

    async def test_hundred_send_close_iterations_leave_no_pending_rows(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
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
                stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=row.id)
                assert stored is not None
                assert stored.accepted_at is not None or (
                    stored.cancelled_at is not None and stored.cancel_reason == stop_reason
                ), f"iteration {_iteration}: row left pending"
        finally:
            await gateway.close()


class TestSendCloseRaceAcrossConnections:
    """O5 (R6): a send and W's close race on independent SQLite connections."""

    async def test_hundred_concurrent_send_close_races_never_leave_a_pending_row(
        self, tmp_path: Path
    ) -> None:
        sender_side: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        closer_repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        await closer_repository.open()
        closer_side: ChannelGateway = ChannelGateway(repository=closer_repository)
        outcomes: dict[str, int] = {"refused": 0, "cancelled_by_close": 0}
        try:
            channel: ChannelDAO = await sender_side.register_channel(kind="tui", name="tui@testhost")
            user: ParticipantDAO = await sender_side.register_user(channel_id=channel.id, name="tester (tui)")
            for iteration in range(100):
                workflow_id: UUID = uuid4()
                await closer_side.register_agent(session_id=workflow_id, name="orchestrator W")
                # Even iterations let the send lead, odd ones the close, and
                # every fourth one starts both at once.
                send_delay: float = 0.0 if iteration % 2 == 0 or iteration % 4 == 3 else 0.005
                close_delay: float = 0.005 if iteration % 2 == 0 and iteration % 4 != 0 else 0.0

                async def _send() -> Optional[ChannelMessageDAO]:
                    await asyncio.sleep(send_delay)
                    try:
                        return await sender_side.send(
                            new=NewMessageDAO(
                                sender_id=user.id,
                                recipient_id=workflow_id,
                                message_contents="late prompt",
                                channel_id=channel.id,
                            )
                        )
                    except RecipientClosedError:
                        return None

                async def _close() -> int:
                    await asyncio.sleep(close_delay)
                    return await closer_side.close_agent(session_id=workflow_id, reason="recipient_closed")

                sent, _cancelled = await asyncio.gather(_send(), _close())
                if sent is None:
                    outcomes["refused"] += 1
                    continue
                stored: Optional[ChannelMessageDAO] = await sender_side.find_message(message_id=sent.id)
                assert stored is not None
                assert stored.accepted_at is not None or (
                    stored.cancelled_at is not None and stored.cancel_reason == "recipient_closed"
                ), f"iteration {iteration}: row left pending"
                outcomes["cancelled_by_close"] += 1
                assert await sender_side.list_pending_inbound_messages(recipient_id=workflow_id) == []
            assert sum(outcomes.values()) == 100
            assert outcomes["refused"] > 0 and outcomes["cancelled_by_close"] > 0, outcomes
        finally:
            await closer_side.close()
            await sender_side.close()


class BlockingAfterFirstCallFauxChatModel(FauxChatModel):
    """Provider-boundary double: answers the first call, then blocks every later call."""

    later_call_entered: asyncio.Event = Field(description="Set when a call after the first one starts.")

    def __init__(self, *, responses: Sequence[AIMessage], **data: object) -> None:
        """Queue the scripted responses; the remaining fields pass through to pydantic."""
        super().__init__(responses=responses, **data)  # type: ignore[arg-type]

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "BlockingAfterFirstCallFauxChatModel":
        """Clone preserving the script and the shared event."""
        clone: BlockingAfterFirstCallFauxChatModel = BlockingAfterFirstCallFauxChatModel(
            responses=list(self.queue), later_call_entered=self.later_call_entered
        )
        clone.bound_tools = list(tools)
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Serve the scripted first answer; block forever once the script is used up."""
        if not self.queue:
            self.later_call_entered.set()
            await asyncio.Event().wait()
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class FollowUpRefusingSession(SloAgentSession):
    """Session stub that refuses one follow-up text before yielding any event.

    Stands in for a session that cannot start a turn (for example a prompt
    already in flight); injected through the runner's session preparer seam.
    """

    refused_text: str = "refused follow-up"

    async def invoke(  # type: ignore[override]
        self, *, text: str, **kwargs: object
    ) -> AsyncIterator[AgentStreamEventDAO]:
        """Raise before the first event for the refused text; otherwise run normally."""
        if text == self.refused_text:
            raise RuntimeError("Another prompt is already running on this session.")
        async for event in super().invoke(text=text, **kwargs):  # type: ignore[arg-type]
            yield event


async def _workflow_world(
    *, tmp_path: Path
) -> tuple[ChannelGateway, ChannelDAO, ParticipantDAO, str, ParticipantDAO]:
    """Open a gateway with the operator and an open orchestrator participant W."""
    gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    orchestrator_session_id: str = str(uuid4())
    agent: ParticipantDAO = await gateway.register_agent(
        session_id=UUID(orchestrator_session_id), name="slo orchestrator"
    )
    return gateway, channel, user, orchestrator_session_id, agent


def _workflow_config(*, tmp_path: Path, session_id: str) -> SessionConfigDAO:
    """Return the runner config for one prebuilt workflow session."""
    return SessionConfigDAO(workdir=tmp_path, model_name="faux", enable_history=False, session_id=session_id)


async def _user_message_channel_ids(*, session: SloAgentSession) -> list[str]:
    """Return the channel ids recorded on persisted user messages, in order."""
    assert session.history_store is not None
    events: list[SessionHistoryEventDAO] = await session.history_store.load_events(
        session_id=session.session_id
    )
    return [
        str(event.payload.metadata["channel_message_id"])
        for event in events
        if event.kind == "user_message" and "channel_message_id" in event.payload.metadata
    ]


class TestFollowUpTurnIdentity:
    """R2: follow-up turns carry the row id into history and accept only after it is written."""

    async def test_successful_follow_up_records_its_row_id_before_accepting(self, tmp_path: Path) -> None:
        gateway, channel, user, session_id, agent = await _workflow_world(tmp_path=tmp_path)
        try:
            session: SloAgentSession = _build_session(
                tmp_path=tmp_path,
                session_id=session_id,
                responses=[AIMessage(content="main answer"), AIMessage(content="follow-up answer")],
            )
            prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="status?",
                    channel_id=channel.id,
                )
            )
            output: io.StringIO = io.StringIO()
            runner: HeadlessRunner = HeadlessRunner(
                config=_workflow_config(tmp_path=tmp_path, session_id=session_id),
                notify_session_id="tui-owner",
                notifier=_RecordingNotifier(),  # type: ignore[arg-type]
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
                output_stream=output,
            )
            assert await runner.invoke(prompt="do the workflow") == 0

            assert await _user_message_channel_ids(session=session) == [str(prompt.id)]
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=prompt.id)
            assert stored is not None and stored.accepted_at is not None
            lines: list[dict[str, object]] = [json.loads(line) for line in output.getvalue().splitlines()]
            marker_index: int = next(
                index for index, line in enumerate(lines) if line.get("kind") == "channel_turn"
            )
            assert lines[marker_index]["message_id"] == str(prompt.id)
            assert [line.get("kind") for line in lines[:marker_index]].count("run_completed") == 1
        finally:
            await gateway.close()

    async def test_failed_follow_up_is_accepted_and_answered_with_its_error(self, tmp_path: Path) -> None:
        gateway, channel, user, session_id, agent = await _workflow_world(tmp_path=tmp_path)
        try:
            # The script holds only the main answer: the follow-up's provider call fails.
            session: SloAgentSession = _build_session(
                tmp_path=tmp_path, session_id=session_id, responses=[AIMessage(content="main answer")]
            )
            prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="status?",
                    channel_id=channel.id,
                )
            )
            notifier: _RecordingNotifier = _RecordingNotifier()
            runner: HeadlessRunner = HeadlessRunner(
                config=_workflow_config(tmp_path=tmp_path, session_id=session_id),
                notify_session_id="tui-owner",
                notifier=notifier,  # type: ignore[arg-type]
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
                output_stream=io.StringIO(),
            )
            exit_code: int = await runner.invoke(prompt="do the workflow")

            assert exit_code == 1
            assert await _user_message_channel_ids(session=session) == [str(prompt.id)]
            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=prompt.id)
            assert stored is not None and stored.accepted_at is not None
            replies: list[ChannelMessageDAO] = await gateway.list_pending_outbound_messages(
                recipient_ids=[user.id]
            )
            assert [reply.in_reply_to_id for reply in replies] == [prompt.id]
            assert replies[0].message_contents not in ("", "(no response)")
            assert [name for name, _kwargs in notifier.calls] == ["started", "failed"]
        finally:
            await gateway.close()

    async def test_follow_up_that_never_starts_is_not_accepted(self, tmp_path: Path) -> None:
        gateway, channel, user, session_id, agent = await _workflow_world(tmp_path=tmp_path)
        try:
            session: FollowUpRefusingSession = FollowUpRefusingSession(
                agent=SloAgent(
                    llm=FauxChatModel(responses=[AIMessage(content="main answer")]),
                    cwd=str(tmp_path),
                    tools=[],
                ),
                workdir=tmp_path,
                session_id=session_id,
                history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
                enable_history=True,
            )
            prompt: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents=FollowUpRefusingSession.refused_text,
                    channel_id=channel.id,
                )
            )
            runner: HeadlessRunner = HeadlessRunner(
                config=_workflow_config(tmp_path=tmp_path, session_id=session_id),
                notify_session_id="tui-owner",
                notifier=_RecordingNotifier(),  # type: ignore[arg-type]
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
                output_stream=io.StringIO(),
            )
            assert await runner.invoke(prompt="do the workflow") == 0

            stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=prompt.id)
            assert stored is not None
            assert stored.accepted_at is None
            assert stored.cancel_reason == "start_failed"
            assert await _user_message_channel_ids(session=session) == []
            assert await gateway.list_pending_outbound_messages(recipient_ids=[user.id]) == []
        finally:
            await gateway.close()


class TestFollowUpSupervision:
    """R3: the watchdog and abort funnel stay live during follow-up turns."""

    async def test_abort_file_during_a_blocked_follow_up_aborts_within_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_WORKFLOW_ID", "wf-follow-up-abort")
        monkeypatch.setenv("SLO_HEADLESS_HEARTBEAT_SECONDS", "0.02")
        monkeypatch.delenv("SLO_PARENT_PID", raising=False)
        gateway, channel, user, session_id, agent = await _workflow_world(tmp_path=tmp_path)
        try:
            model: BlockingAfterFirstCallFauxChatModel = BlockingAfterFirstCallFauxChatModel(
                responses=[AIMessage(content="main answer")], later_call_entered=asyncio.Event()
            )
            session: SloAgentSession = SloAgentSession(
                agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
                workdir=tmp_path,
                session_id=session_id,
                history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
                enable_history=True,
            )
            blocked: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="long job",
                    channel_id=channel.id,
                )
            )
            queued_behind: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="next job",
                    channel_id=channel.id,
                )
            )
            history_root: Path = tmp_path / "workflow-history"
            notifier: _RecordingNotifier = _RecordingNotifier()
            runner: HeadlessRunner = HeadlessRunner(
                config=_workflow_config(tmp_path=tmp_path, session_id=session_id),
                notify_session_id="tui-owner",
                notifier=notifier,  # type: ignore[arg-type]
                channel_gateway=gateway,
                session_preparer=_session_preparer(session),
                output_stream=io.StringIO(),
                history_root=history_root,
                cooperative_abort_grace_seconds=0.05,
            )
            run: asyncio.Task[int] = asyncio.create_task(runner.invoke(prompt="do the workflow"))
            await asyncio.wait_for(model.later_call_entered.wait(), timeout=10.0)
            abort_path: Path = OrchestrationLayout.abort_request_path(
                history_root=history_root, orchestrator_session_id=session_id
            )
            assert abort_path.resolve().is_relative_to(tmp_path.resolve())
            abort_path.parent.mkdir(parents=True, exist_ok=True)
            abort_path.write_text("{}", encoding="utf-8")

            exit_code: int = await asyncio.wait_for(run, timeout=10.0)

            assert exit_code == 2
            stored_blocked: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=blocked.id)
            assert stored_blocked is not None and stored_blocked.accepted_at is not None
            stored_behind: Optional[ChannelMessageDAO] = await gateway.find_message(
                message_id=queued_behind.id
            )
            assert stored_behind is not None and stored_behind.cancel_reason == "aborted"
            closed: Optional[ParticipantDAO] = await gateway.find_participant(participant_id=agent.id)
            assert closed is not None and closed.status == "closed"
            assert [name for name, _kwargs in notifier.calls] == ["started", "aborted"]
            status: dict[str, object] = json.loads(
                (history_root / session_id / "orchestrator.json").read_text(encoding="utf-8")
            )
            assert status["state"] == "aborted"
        finally:
            await gateway.close()


class HeldOnSecondCallFauxChatModel(FauxChatModel):
    """Provider-boundary double: holds the second call until released; records every call."""

    second_call_entered: asyncio.Event = Field(description="Set when the second call starts.")
    second_call_release: asyncio.Event = Field(description="Set by the test to release the second call.")
    recorded_contexts: list[list[str]] = Field(
        default_factory=list, description="Texts of the messages passed to each call, in call order."
    )

    def __init__(self, *, responses: Sequence[AIMessage], **data: object) -> None:
        """Queue the scripted responses; the remaining fields pass through to pydantic."""
        super().__init__(responses=responses, **data)  # type: ignore[arg-type]

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "HeldOnSecondCallFauxChatModel":
        """Clone preserving the script, the gates and the recorder."""
        clone: HeldOnSecondCallFauxChatModel = HeldOnSecondCallFauxChatModel(
            responses=list(self.queue),
            second_call_entered=self.second_call_entered,
            second_call_release=self.second_call_release,
        )
        # Assigned after construction: validation would copy the list.
        clone.recorded_contexts = self.recorded_contexts
        clone.bound_tools = list(tools)
        return clone

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Record the call; hold the second one until the test releases it."""
        self.recorded_contexts.append([str(message.content) for message in messages])
        if len(self.recorded_contexts) == 2:
            self.second_call_entered.set()
            await self.second_call_release.wait()
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class TestPoolChildChannelMode:
    """108.4: a pool child registers, messages its parent, takes forced prompts, closes on exit."""

    async def test_child_run_messages_parent_takes_forced_prompt_and_closes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
            operator: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
            parent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="orchestrator W")
            child_session_id: str = str(uuid4())
            monkeypatch.setenv("SLO_CHANNEL_PARENT_ID", str(parent.id))
            monkeypatch.setenv("SLO_CHANNEL_PARTICIPANT_NAME", f"review-1 (child of {str(parent.id)[:8]})")
            monkeypatch.setenv("SLO_HEADLESS_FOLLOWUP_TURNS", "0")
            monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)
            model: HeldOnSecondCallFauxChatModel = HeldOnSecondCallFauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(
                        tool_calls=[
                            FauxChatModel.tool_call_dict(
                                name="send_message",
                                args={"to": "parent", "text": "question: is src/tui/widgets in scope?"},
                            )
                        ]
                    ),
                    AIMessage(content="review done"),
                    AIMessage(content="tests reviewed too"),
                ],
                second_call_entered=asyncio.Event(),
                second_call_release=asyncio.Event(),
            )

            async def _prepare(config: SessionConfigDAO) -> SloAgentSession:
                """Build the child session from the runner's config (its bound tools)."""
                return SloAgentSession(
                    agent=SloAgent(llm=model, cwd=str(tmp_path), tools=list(config.extra_tools or [])),
                    workdir=tmp_path,
                    session_id=child_session_id,
                    history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
                    enable_history=True,
                )

            runner: HeadlessRunner = HeadlessRunner(
                config=_workflow_config(tmp_path=tmp_path, session_id=child_session_id),
                channel_gateway=gateway,
                session_preparer=_prepare,
                output_stream=io.StringIO(),
            )
            run: asyncio.Task[int] = asyncio.create_task(runner.invoke(prompt="review the slice"))
            await asyncio.wait_for(model.second_call_entered.wait(), timeout=10.0)

            child: Optional[ParticipantDAO] = await gateway.find_participant(
                participant_id=UUID(child_session_id)
            )
            assert child is not None and child.status == "open"
            assert child.name == f"review-1 (child of {str(parent.id)[:8]})"
            notes: list[ChannelMessageDAO] = await gateway.list_pending_inbound_messages(
                recipient_id=parent.id
            )
            assert [(note.message_type, note.sender_name, note.message_contents) for note in notes] == [
                ("note", child.name, "question: is src/tui/widgets in scope?")
            ]
            forced: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=operator.id,
                    recipient_id=child.id,
                    message_contents="also check tests",
                    channel_id=channel.id,
                    force=True,
                )
            )
            late_normal: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=operator.id,
                    recipient_id=child.id,
                    message_contents="later",
                    channel_id=channel.id,
                )
            )

            async def _forced_in_snapshot() -> bool:
                session: Optional[SloAgentSession] = runner.wired_session
                poller: Optional[ChannelPoller] = session.channel_poller if session is not None else None
                return poller is not None and poller.boundary_inbox.has_forced()

            async with asyncio.timeout(10.0):
                while not await _forced_in_snapshot():
                    await asyncio.sleep(0.02)
            model.second_call_release.set()
            exit_code: int = await asyncio.wait_for(run, timeout=10.0)

            assert exit_code == 0
            assert len(model.recorded_contexts) == 3
            assert model.recorded_contexts[2].count("also check tests") == 1
            stored_forced: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=forced.id)
            assert stored_forced is not None and stored_forced.accepted_at is not None
            stored_late: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=late_normal.id)
            assert stored_late is not None and stored_late.cancel_reason == "recipient_closed"
            closed: Optional[ParticipantDAO] = await gateway.find_participant(participant_id=child.id)
            assert closed is not None and closed.status == "closed"
        finally:
            await gateway.close()
