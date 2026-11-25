"""108.4 C2/C3 journeys: an orchestrator and its running child message each other.

The orchestrator W is a real session (``FauxChatModel`` at the provider
boundary) with channel delivery and the tool bundle bootstrap composes for a
channel-bound orchestrator: ``spawn_sub_agents`` over a real ``SubAgentPool``
with the pending-notes counter, and ``send_message`` over the pool's child
directory. The child process is an injected spawn stub that acts as a
channel-aware child: it registers its participant and uses its own real
``send_message`` tool (parent-only policy). The queue is real SQLite under
``tmp_path``. The child exits normally, so no process is ever signalled.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.policy import MessagingPolicy
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.channel_delivery.send_tool import SendMessageTool
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
from src.agents.slo_agent.orchestrator.dao import OrchestratorResultDAO, SubAgentTaskDAO
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.spawn_tool import PendingChannelNotes, SpawnSubAgentsTool
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.tui.channel.adapter import TuiChannelAdapter
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess, terminal_line
from tests.agents.slo_agent.orchestrator.test_child_channel_messaging import (  # noqa: F401 — fixture
    _process_factory,
    channel_gateway,
)

_RUN_ID: str = "5c4b3a29-1807-4f6e-9d5c-4b3a29180716"
_CHILD_QUESTION: str = "question: is src/tui/widgets in scope?"


class MessagingChildSpawn:
    """Process-boundary stub acting as a running, channel-aware child.

    On spawn it registers the child participant and, through its own real
    ``send_message`` tool, asks the parent a question. It stays running until
    the test calls ``finish``; then it prints its terminal line and exits.
    """

    def __init__(self, *, gateway: ChannelGateway, parent_id: UUID) -> None:
        """Bind the queue and the parent identity."""
        self.child_ids: list[UUID] = []
        self.send_results: list[dict[str, object]] = []
        self.spawned: asyncio.Event = asyncio.Event()
        self._children: list[FakeChildProcess] = []
        self._gateway: ChannelGateway = gateway
        self._parent_id: UUID = parent_id

    async def __call__(
        self,
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: Optional[str],
        env: dict[str, str],
    ) -> FakeChildProcess:
        """Register the child, send its note to the parent, keep it running."""
        child_id: UUID = channel_participant_id_for_session(session_id=argv[argv.index("--session-id") + 1])
        await self._gateway.register_agent(session_id=child_id, name="review-1 (child)")
        child_tool: BaseTool = SendMessageTool.build(
            gateway=self._gateway,
            policy=MessagingPolicy(
                self_id=child_id,
                parent_id=self._parent_id,
                children=lambda: [],
                launched_workflows=lambda: [],
            ),
            self_id=child_id,
        )
        self.send_results.append(
            json.loads(await child_tool.ainvoke({"to": "parent", "text": _CHILD_QUESTION}))
        )
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="review done")], exit_code=0)
        self.child_ids.append(child_id)
        self._children.append(child)
        self.spawned.set()
        return child

    def finish(self) -> None:
        """Let every spawned child exit normally."""
        for child in self._children:
            child.exit()


class _UnusedTurnRunner:
    """TurnRunner stub for an ``auto_run=False`` poller; it is never asked to run."""

    async def run(self, *, message: ChannelMessageDAO, on_started: object) -> TurnOutcomeDAO:
        """Fail loudly if the poller ever starts a run itself."""
        raise AssertionError("auto_run=False poller started a run")


async def _ignore_event(event: AgentStreamEventDAO) -> None:
    """Relay stub that drops child events."""
    return


def _orchestrator_tools(
    *, gateway: ChannelGateway, pool: SubAgentPool, orchestrator_session_id: str
) -> list[BaseTool]:
    """Compose the channel-bound orchestrator bundle the way bootstrap does."""
    self_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
    return [
        SpawnSubAgentsTool.build(
            pool=pool,
            channel_notes=PendingChannelNotes(gateway=gateway, recipient_session_id=orchestrator_session_id),
        ),
        SendMessageTool.build(
            gateway=gateway,
            policy=MessagingPolicy(
                self_id=self_id, parent_id=None, children=pool.child_directory, launched_workflows=lambda: []
            ),
            self_id=self_id,
        ),
    ]


def _spawn_call(*, task_id: str) -> AIMessage:
    """Return W's scripted ``spawn_sub_agents`` call for one task."""
    return FauxChatModel.assistant_message(
        tool_calls=[
            FauxChatModel.tool_call_dict(
                name="spawn_sub_agents",
                args={
                    "mode": "single",
                    "tasks": [
                        {"task_id": task_id, "task_summary": "Review the slice", "prompt": "review it"}
                    ],
                },
            )
        ]
    )


async def test_child_note_is_visible_during_the_dispatch_and_in_context_after_it(
    tmp_path: Path, channel_gateway: ChannelGateway
) -> None:
    """C3: the note shows in W's modal before the dispatch returns and enters W's context after."""
    orchestrator_session_id: str = str(uuid4())
    parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
    spawn: MessagingChildSpawn = MessagingChildSpawn(gateway=channel_gateway, parent_id=parent_id)
    pool: SubAgentPool = SubAgentPool(
        orchestrator_session_id=orchestrator_session_id,
        default_model=None,
        relay=_ignore_event,
        owner_session_id=orchestrator_session_id,
        run_id=_RUN_ID,
        history_root=tmp_path / "history",
        process_factory=_process_factory(spawn=spawn),  # type: ignore[arg-type]
        channel_gateway=channel_gateway,
    )
    model: FauxChatModel = FauxChatModel(
        responses=[_spawn_call(task_id="review-1"), AIMessage(content="widgets are out of scope")]
    )
    session: SloAgentSession = SloAgentSession(
        agent=SloAgent(
            llm=model,
            cwd=str(tmp_path),
            tools=_orchestrator_tools(
                gateway=channel_gateway, pool=pool, orchestrator_session_id=orchestrator_session_id
            ),
        ),
        workdir=tmp_path,
        session_id=orchestrator_session_id,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )
    await session.start_channel_delivery(
        gateway=channel_gateway, runner=_UnusedTurnRunner(), interval=0.02, auto_run=False
    )
    # Only the adapter's queue reads are used, so it needs no running app.
    viewer: TuiChannelAdapter = TuiChannelAdapter(app=None, gateway=channel_gateway)  # type: ignore[arg-type]
    try:
        run: asyncio.Task[list[AgentStreamEventDAO]] = asyncio.create_task(
            _collect(session=session, text="dispatch the review")
        )
        await asyncio.wait_for(spawn.spawned.wait(), timeout=10.0)
        assert spawn.send_results == [
            {
                "status": "sent",
                "message_id": spawn.send_results[0]["message_id"],
                "recipient_name": "slo " + str(parent_id)[:8],
            }
        ]
        # Shown at once to whoever views W, while W is still inside the dispatch.
        visible: list[ChannelMessageDAO] = await viewer.notes_to_agent(session_id=orchestrator_session_id)
        assert [(note.sender_name, note.message_contents) for note in visible] == [
            ("review-1 (child)", _CHILD_QUESTION)
        ]
        assert not run.done()
        spawn.finish()
        events: list[AgentStreamEventDAO] = await asyncio.wait_for(run, timeout=10.0)

        spawn_results: list[dict[str, object]] = [
            json.loads(event.content or "{}")
            for event in events
            if event.kind == "tool_result" and event.tool_name == "spawn_sub_agents"
        ]
        assert [result["channel_notes_pending"] for result in spawn_results] == [1]
        applied: list[AgentStreamEventDAO] = [event for event in events if event.kind == "steering_applied"]
        assert [event.content for event in applied] == [_CHILD_QUESTION]
        note_id: UUID = UUID(str(spawn.send_results[0]["message_id"]))
        stored: Optional[ChannelMessageDAO] = await channel_gateway.find_message(message_id=note_id)
        assert stored is not None and stored.accepted_at is not None
    finally:
        await session.stop_channel_delivery(reason="test_done")


async def test_orchestrator_send_message_by_task_id_reaches_the_running_child(
    tmp_path: Path, channel_gateway: ChannelGateway
) -> None:
    """C2: ``send_message(to=task_id)`` resolves through the pool to the running child and is applied."""
    orchestrator_session_id: str = str(uuid4())
    parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
    await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
    spawn: MessagingChildSpawn = MessagingChildSpawn(gateway=channel_gateway, parent_id=parent_id)
    pool: SubAgentPool = SubAgentPool(
        orchestrator_session_id=orchestrator_session_id,
        default_model=None,
        relay=_ignore_event,
        owner_session_id=orchestrator_session_id,
        run_id=_RUN_ID,
        history_root=tmp_path / "history",
        process_factory=_process_factory(spawn=spawn),  # type: ignore[arg-type]
        channel_gateway=channel_gateway,
    )
    send_tool: BaseTool = _orchestrator_tools(
        gateway=channel_gateway, pool=pool, orchestrator_session_id=orchestrator_session_id
    )[1]
    dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
        pool.dispatch(mode="single", tasks=[_spawn_task(task_id="review-1")])
    )
    try:
        await asyncio.wait_for(spawn.spawned.wait(), timeout=10.0)
        result: dict[str, object] = json.loads(
            await send_tool.ainvoke({"to": "review-1", "text": "only review src/tui"})
        )
        assert result["status"] == "sent"
        child_inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(
            gateway=channel_gateway, agent_id=spawn.child_ids[0]
        )
        await child_inbox.refresh()
        assert child_inbox.has_forced() is True
        deliveries: list[BoundaryDeliveryDAO] = await child_inbox.take(iteration=1)
        assert [(delivery.text, delivery.kind) for delivery in deliveries] == [
            ("only review src/tui", "forced_prompt")
        ]
        await child_inbox.confirm(deliveries=deliveries)
        stored: Optional[ChannelMessageDAO] = await channel_gateway.find_message(
            message_id=UUID(str(result["message_id"]))
        )
        assert stored is not None and stored.accepted_at is not None and stored.forced_at is not None
        assert stored.recipient_id == spawn.child_ids[0]
    finally:
        spawn.finish()
        await asyncio.wait_for(dispatch, timeout=10.0)
    # After the dispatch the child is finished: the alias reports recipient_closed.
    after: dict[str, object] = json.loads(await send_tool.ainvoke({"to": "review-1", "text": "too late"}))
    assert after["status"] == "recipient_closed"


def test_bootstrap_binds_send_message_and_the_notes_counter_when_a_gateway_is_given(
    tmp_path: Path,
) -> None:
    """Bootstrap adds ``send_message`` only for a channel-bound orchestrator."""
    bound: SloAgentSession = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", enable_history=False, history_root=tmp_path
        )
    )
    unbound: SloAgentSession = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", enable_history=False, history_root=tmp_path
        )
    )
    gateway: ChannelGateway = ChannelGateway.at_default_path()
    OrchestratorSessionBootstrap.attach(session=bound, headless=True, channel_gateway=gateway)
    OrchestratorSessionBootstrap.attach(session=unbound, headless=True)
    assert [tool.name for tool in bound.orchestration_tools] == ["spawn_sub_agents", "send_message"]
    assert [tool.name for tool in unbound.orchestration_tools] == ["spawn_sub_agents"]


def _spawn_task(*, task_id: str) -> SubAgentTaskDAO:
    """Build one child task for a direct pool dispatch."""
    return SubAgentTaskDAO(task_summary="Review the slice", task_id=task_id, prompt="review it")


async def _collect(*, session: SloAgentSession, text: str) -> list[AgentStreamEventDAO]:
    """Run one turn and return all its events."""
    return [event async for event in session.invoke(text=text)]
