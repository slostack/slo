"""Child-process messaging infrastructure for sub-agents (108.4).

Covers the orchestrator side of 108.4: the parent's channel identity reaching
each child's environment, the pool's child directory, closing participants of
children that died without closing (C5), and ``channel_notes_pending`` in the
``spawn_sub_agents`` result.

Doubles: the OS process boundary is an injected ``spawn`` stub returning the
shared ``FakeChildProcess``; the channel queue is a real SQLite database under
``tmp_path``. Nothing is patched.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncIterator, Callable, Optional
from uuid import UUID, uuid4

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_STATUSES,
    ChildDirectoryEntryDAO,
    OrchestratorResultDAO,
    SubAgentMode,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry
from src.agents.slo_agent.orchestrator.spawn_env import (
    CHANNEL_PARENT_ID_ENV,
    AgentLaunchPolicy,
    build_headless_child_env,
)
from src.agents.slo_agent.orchestrator.spawn_tool import (
    PendingChannelNotes,
    SpawnSubAgentsTool,
)
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import RecipientClosedError
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from tests.agents.slo_agent.orchestrator.fake_child import (
    FakeChildProcess,
    terminal_line,
)

_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"


# ── injected boundary stubs ──────────────────────────────────────────────────


class RecordingChildSpawn:
    """Process-boundary stub: records each child environment and returns an exited child."""

    def __init__(self, *, exit_code: int = 0, emits_terminal_line: bool = True) -> None:
        """Configure how every spawned child ends.

        Args:
            exit_code (int): Exit code of every spawned child.
            emits_terminal_line (bool): Whether the child prints a ``run_completed`` line.
        """
        self.environments: list[dict[str, str]] = []
        self._exit_code: int = exit_code
        self._emits_terminal_line: bool = emits_terminal_line

    async def __call__(
        self,
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: Optional[str],
        env: dict[str, str],
    ) -> FakeChildProcess:
        """Record ``env`` and return a child whose exit is already observable."""
        self.environments.append(env)
        lines: list[bytes] = [terminal_line(content="done")] if self._emits_terminal_line else []
        child: FakeChildProcess = FakeChildProcess(lines=lines, exit_code=self._exit_code)
        child.exit()
        return child


class HeldChildSpawn:
    """Process-boundary stub: children keep running until the test exits them."""

    def __init__(self) -> None:
        """Start with no spawned children."""
        self.children: list[FakeChildProcess] = []
        self.children_by_session_id: dict[str, FakeChildProcess] = {}

    async def __call__(
        self,
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: Optional[str],
        env: dict[str, str],
    ) -> FakeChildProcess:
        """Return a child that runs until ``exit`` is called on it."""
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="done")], exit_code=0)
        self.children.append(child)
        self.children_by_session_id[argv[argv.index("--session-id") + 1]] = child
        return child

    async def wait_for_children(self, *, count: int) -> None:
        """Wait, with a bound, until ``count`` children have been spawned."""
        async with asyncio.timeout(5.0):
            while len(self.children) < count:
                await asyncio.sleep(0.01)


def _process_factory(*, spawn: object) -> Callable[..., SubAgentProcess]:
    """Return a pool process factory that builds real wrappers over ``spawn``.

    ``spawn`` is an OS-process boundary stub; it returns a fake or a
    test-owned process rather than the production ``asyncio`` process type.
    """

    def build(
        *,
        task: SubAgentTaskDAO,
        session_id: str,
        model: Optional[str],
        relay: AgentEventSubscriber,
        registry: ProcessRegistry,
        execution_id: str,
        system_prompt: str,
        parent_session_id: str,
        history_root: Path,
    ) -> SubAgentProcess:
        return SubAgentProcess(
            task=task,
            session_id=session_id,
            model=model,
            relay=relay,
            registry=registry,
            execution_id=execution_id,
            system_prompt=system_prompt,
            parent_session_id=parent_session_id,
            history_root=history_root,
            spawn=spawn,  # type: ignore[arg-type]
        )

    return build


async def _ignore_event(event: AgentStreamEventDAO) -> None:
    """Relay stub that drops child events."""
    return


def _task(*, task_id: str, session_id: Optional[str] = None) -> SubAgentTaskDAO:
    """Build one child task, optionally with a fixed child session id."""
    return SubAgentTaskDAO(
        task_summary="Review the channel messaging slice",
        task_id=task_id,
        prompt="review it",
        session_id=session_id,
    )


def _pool(
    *,
    tmp_path: Path,
    orchestrator_session_id: str,
    spawn: RecordingChildSpawn | HeldChildSpawn,
) -> SubAgentPool:
    """Build a pool whose children are real wrappers over the recording spawn stub."""
    return SubAgentPool(
        orchestrator_session_id=orchestrator_session_id,
        default_model=None,
        relay=_ignore_event,
        owner_session_id=orchestrator_session_id,
        run_id=_RUN_ID,
        history_root=tmp_path / "history",
        process_factory=_process_factory(spawn=spawn),
    )


# ── SLO_CHANNEL_PARENT_ID propagation ───────────────────────────────────────


class TestChildEnvironmentCarriesParentChannelId:
    """Every pool child learns its parent's channel participant id from its environment."""

    @pytest.mark.parametrize(
        "orchestrator_session_id", ["5f0c8a5e-3c1d-4b8e-9a51-2f7d6c4b3a10", "orch-named-session"]
    )
    async def test_dispatched_child_env_names_parent_participant_when_pool_dispatches(
        self, tmp_path: Path, orchestrator_session_id: str
    ) -> None:
        spawn: RecordingChildSpawn = RecordingChildSpawn()
        pool: SubAgentPool = _pool(
            tmp_path=tmp_path, orchestrator_session_id=orchestrator_session_id, spawn=spawn
        )

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1")])

        expected_parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        assert [environment[CHANNEL_PARENT_ID_ENV] for environment in spawn.environments] == [
            str(expected_parent_id)
        ]

    async def test_dispatched_child_env_disables_headless_follow_up_turns(self, tmp_path: Path) -> None:
        spawn: RecordingChildSpawn = RecordingChildSpawn()
        pool: SubAgentPool = _pool(tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=spawn)

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1")])

        assert spawn.environments[0]["SLO_HEADLESS_FOLLOWUP_TURNS"] == "0"

    async def test_child_without_parent_session_gets_no_parent_channel_id(self, tmp_path: Path) -> None:
        spawn: RecordingChildSpawn = RecordingChildSpawn()
        registry: ProcessRegistry = ProcessRegistry()
        dispatch_id: str = str(uuid4())
        registry.begin_dispatch(dispatch_id=dispatch_id)
        execution_id: str = registry.register(
            dispatch_id=dispatch_id, task_id="review-1", session_id="child-1", task=_task(task_id="review-1")
        )
        process: SubAgentProcess = SubAgentProcess(
            task=_task(task_id="review-1"),
            session_id="child-1",
            model=None,
            relay=_ignore_event,
            registry=registry,
            execution_id=execution_id,
            spawn=spawn,  # type: ignore[arg-type]
        )

        await process.run()

        assert CHANNEL_PARENT_ID_ENV not in spawn.environments[0]


class TestParentChannelIdIsNeverInherited:
    """A stale parent id in the launching process never leaks into another launch."""

    def test_headless_child_env_drops_inherited_parent_channel_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CHANNEL_PARENT_ID_ENV, str(uuid4()))

        assert CHANNEL_PARENT_ID_ENV not in build_headless_child_env(workflow_id="wf-1")

    def test_launch_policy_sets_parent_channel_id_only_when_supplied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CHANNEL_PARENT_ID_ENV, str(uuid4()))
        parent_id: str = str(uuid4())
        policy: AgentLaunchPolicy = AgentLaunchPolicy()

        detached_environment: dict[str, str] = policy.build_environment(workflow_id="wf-1")
        child_environment: dict[str, str] = policy.build_environment(extra={CHANNEL_PARENT_ID_ENV: parent_id})

        assert CHANNEL_PARENT_ID_ENV not in detached_environment
        assert child_environment[CHANNEL_PARENT_ID_ENV] == parent_id


# ── ChildDirectory ───────────────────────────────────────────────────────────


async def _wait_until_terminal(*, pool: SubAgentPool, session_id: str) -> None:
    """Wait, with a bound, until the registry holds a terminal winner for ``session_id``."""
    async with asyncio.timeout(5.0):
        while True:
            status = pool.registry.get(session_id=session_id)
            if status is not None and status.status in TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.01)


class TestPoolChildDirectory:
    """The pool lists its children by task id, participant id and liveness."""

    def test_directory_is_empty_before_any_dispatch(self, tmp_path: Path) -> None:
        pool: SubAgentPool = _pool(
            tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=HeldChildSpawn()
        )

        assert pool.child_directory() == []

    async def test_child_is_running_during_dispatch_and_finished_after_it(self, tmp_path: Path) -> None:
        spawn: HeldChildSpawn = HeldChildSpawn()
        pool: SubAgentPool = _pool(tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=spawn)
        child_session_id: str = str(uuid4())

        dispatch: asyncio.Task = asyncio.create_task(
            pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])
        )
        await spawn.wait_for_children(count=1)
        running: list[ChildDirectoryEntryDAO] = pool.child_directory()
        spawn.children[0].exit()
        await asyncio.wait_for(dispatch, timeout=5.0)

        assert running == [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=UUID(child_session_id), state="running")
        ]
        assert pool.child_directory() == [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=UUID(child_session_id), state="finished")
        ]

    async def test_retry_lists_a_new_child_beside_the_finished_attempt(self, tmp_path: Path) -> None:
        spawn: RecordingChildSpawn = RecordingChildSpawn(exit_code=1, emits_terminal_line=False)
        pool: SubAgentPool = _pool(tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=spawn)
        first_session_id: str = str(uuid4())
        retry_session_id: str = str(uuid4())

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=first_session_id)])
        await pool.dispatch(
            mode="single", tasks=[_task(task_id="review-1-retry-1", session_id=retry_session_id)]
        )

        assert pool.child_directory() == [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=UUID(first_session_id), state="finished"),
            ChildDirectoryEntryDAO(
                task_id="review-1-retry-1", session_id=UUID(retry_session_id), state="finished"
            ),
        ]

    async def test_reused_task_id_lists_only_the_newer_child_when_both_finished(self, tmp_path: Path) -> None:
        spawn: RecordingChildSpawn = RecordingChildSpawn()
        pool: SubAgentPool = _pool(tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=spawn)
        newer_session_id: str = str(uuid4())

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=str(uuid4()))])
        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=newer_session_id)])

        assert pool.child_directory() == [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=UUID(newer_session_id), state="finished")
        ]

    async def test_reused_task_id_lists_the_running_child_over_a_finished_one(self, tmp_path: Path) -> None:
        spawn: HeldChildSpawn = HeldChildSpawn()
        pool: SubAgentPool = _pool(tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=spawn)
        earlier_session_id: str = str(uuid4())
        later_session_id: str = str(uuid4())

        dispatch: asyncio.Task = asyncio.create_task(
            pool.dispatch(
                mode="parallel",
                tasks=[
                    _task(task_id="review-1", session_id=earlier_session_id),
                    _task(task_id="review-1", session_id=later_session_id),
                ],
            )
        )
        await spawn.wait_for_children(count=2)
        spawn.children_by_session_id[later_session_id].exit()
        await _wait_until_terminal(pool=pool, session_id=later_session_id)
        listed: list[ChildDirectoryEntryDAO] = pool.child_directory()
        for child in spawn.children:
            child.exit()
        await asyncio.wait_for(dispatch, timeout=5.0)

        assert listed == [
            ChildDirectoryEntryDAO(task_id="review-1", session_id=UUID(earlier_session_id), state="running")
        ]

    async def test_named_child_session_is_listed_under_its_participant_id(self, tmp_path: Path) -> None:
        pool: SubAgentPool = _pool(
            tmp_path=tmp_path, orchestrator_session_id=str(uuid4()), spawn=RecordingChildSpawn()
        )

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id="child-named")])

        assert [entry.session_id for entry in pool.child_directory()] == [
            channel_participant_id_for_session(session_id="child-named")
        ]


# ── Closing children that died without closing (C5) ─────────────────────────


@pytest.fixture
async def channel_gateway(tmp_path: Path) -> AsyncIterator[ChannelGateway]:
    """Open a real channel queue database under ``tmp_path``."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels" / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    yield gateway
    await gateway.close()


class ChannelChildSpawn:
    """Process-boundary stub acting as a channel-aware child process.

    On spawn the "child" registers its participant (as the child bootstrap does)
    and the parent queues a normal prompt for it. The child then exits with
    ``exit_code``; it closes its own participant only when ``closes_itself``.
    """

    def __init__(
        self, *, gateway: ChannelGateway, parent_id: UUID, exit_code: int, closes_itself: bool
    ) -> None:
        """Configure the child's channel behaviour and exit."""
        self.queued_message_ids: list[UUID] = []
        self._gateway: ChannelGateway = gateway
        self._parent_id: UUID = parent_id
        self._exit_code: int = exit_code
        self._closes_itself: bool = closes_itself

    async def __call__(
        self,
        *argv: str,
        stdout: int,
        stderr: int,
        limit: int,
        cwd: Optional[str],
        env: dict[str, str],
    ) -> FakeChildProcess:
        """Register the child participant, queue one prompt to it, return an exited child."""
        child_id: UUID = channel_participant_id_for_session(session_id=argv[argv.index("--session-id") + 1])
        await self._gateway.register_agent(session_id=child_id, name="review-1 (child)")
        queued: ChannelMessageDAO = await self._gateway.send(
            new=NewMessageDAO(
                sender_id=self._parent_id, recipient_id=child_id, message_contents="also check tests"
            )
        )
        self.queued_message_ids.append(queued.id)
        if self._closes_itself:
            await self._gateway.close_agent(session_id=child_id, reason="recipient_closed")
        lines: list[bytes] = [terminal_line(content="done")] if self._exit_code == 0 else []
        child: FakeChildProcess = FakeChildProcess(lines=lines, exit_code=self._exit_code)
        child.exit()
        return child


class UnreachableChannelGateway:
    """Channel stub whose database is unreachable: every call raises ``OSError``."""

    async def close_agent(self, *, session_id: UUID, reason: str) -> int:
        """Fail like a broken shared database."""
        raise OSError("channels.db unreachable")


def _channel_pool(
    *,
    tmp_path: Path,
    orchestrator_session_id: str,
    spawn: ChannelChildSpawn | RecordingChildSpawn,
    channel_gateway: ChannelGateway | UnreachableChannelGateway,
) -> SubAgentPool:
    """Build a pool bound to a channel gateway, over the given spawn stub."""
    return SubAgentPool(
        orchestrator_session_id=orchestrator_session_id,
        default_model=None,
        relay=_ignore_event,
        owner_session_id=orchestrator_session_id,
        run_id=_RUN_ID,
        history_root=tmp_path / "history",
        process_factory=_process_factory(spawn=spawn),
        channel_gateway=channel_gateway,
    )


class TestChildThatDiedWithoutClosingIsClosed:
    """C5: the pool closes the participant of a child that ended without closing."""

    @pytest.mark.parametrize("exit_code", [0, 1])
    async def test_open_child_participant_is_closed_and_pending_rows_cancelled_when_child_ends(
        self, tmp_path: Path, channel_gateway: ChannelGateway, exit_code: int
    ) -> None:
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: ChannelChildSpawn = ChannelChildSpawn(
            gateway=channel_gateway, parent_id=parent_id, exit_code=exit_code, closes_itself=False
        )
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,
            channel_gateway=channel_gateway,
        )
        child_session_id: str = str(uuid4())

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])

        child_participant: Optional[ParticipantDAO] = await channel_gateway.find_participant(
            participant_id=UUID(child_session_id)
        )
        queued: Optional[ChannelMessageDAO] = await channel_gateway.find_message(
            message_id=spawn.queued_message_ids[0]
        )
        assert child_participant is not None and child_participant.status == "closed"
        assert queued is not None
        assert (queued.accepted_at, queued.cancel_reason) == (None, "aborted")
        with pytest.raises(RecipientClosedError):
            await channel_gateway.send(
                new=NewMessageDAO(
                    sender_id=parent_id, recipient_id=UUID(child_session_id), message_contents="too late"
                )
            )

    async def test_child_that_closed_itself_keeps_its_own_cancel_reason(
        self, tmp_path: Path, channel_gateway: ChannelGateway
    ) -> None:
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: ChannelChildSpawn = ChannelChildSpawn(
            gateway=channel_gateway, parent_id=parent_id, exit_code=0, closes_itself=True
        )
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,
            channel_gateway=channel_gateway,
        )

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=str(uuid4()))])

        queued: Optional[ChannelMessageDAO] = await channel_gateway.find_message(
            message_id=spawn.queued_message_ids[0]
        )
        assert queued is not None and queued.cancel_reason == "recipient_closed"

    async def test_child_that_never_registered_gets_no_participant(
        self, tmp_path: Path, channel_gateway: ChannelGateway
    ) -> None:
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=str(uuid4()),
            spawn=RecordingChildSpawn(exit_code=1, emits_terminal_line=False),
            channel_gateway=channel_gateway,
        )
        child_session_id: str = str(uuid4())

        await pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])

        assert await channel_gateway.find_participant(participant_id=UUID(child_session_id)) is None

    async def test_unreachable_channel_database_never_changes_the_child_result(self, tmp_path: Path) -> None:
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=str(uuid4()),
            spawn=RecordingChildSpawn(),
            channel_gateway=UnreachableChannelGateway(),
        )

        result: OrchestratorResultDAO = await pool.dispatch(
            mode="single", tasks=[_task(task_id="review-1", session_id=str(uuid4()))]
        )

        assert [(child.status, child.answer) for child in result.results] == [("completed", "done")]


# ── channel_notes_pending in the spawn_sub_agents result ────────────────────


class NoteSendingDispatcher:
    """Dispatcher stub: while "children run", a child sends notes and prompts to the parent."""

    def __init__(self, *, gateway: ChannelGateway, child_id: UUID, parent_id: UUID) -> None:
        """Bind the child and parent participants the stub messages between."""
        self._gateway: ChannelGateway = gateway
        self._child_id: UUID = child_id
        self._parent_id: UUID = parent_id

    async def dispatch(self, *, mode: SubAgentMode, tasks: list[SubAgentTaskDAO]) -> OrchestratorResultDAO:
        """Send two notes (one later accepted) and one prompt to the parent, then finish."""
        for text in ("question: is src/tui/widgets in scope?", "found a second issue"):
            await self._send(text=text, message_type="note")
        await self._send(text="please decide", message_type="prompt")
        accepted: list[ChannelMessageDAO] = await self._gateway.list_pending_inbound_messages(
            recipient_id=self._parent_id
        )
        await self._gateway.accept(message_id=accepted[0].id)
        return OrchestratorResultDAO(mode=mode)

    async def _send(self, *, text: str, message_type: str) -> None:
        """Queue one child → parent message."""
        await self._gateway.send(
            new=NewMessageDAO(
                sender_id=self._child_id,
                recipient_id=self._parent_id,
                message_contents=text,
                message_type=message_type,  # type: ignore[arg-type]
            )
        )


class FixedResultDispatcher:
    """Dispatcher stub returning an empty successful batch."""

    async def dispatch(self, *, mode: SubAgentMode, tasks: list[SubAgentTaskDAO]) -> OrchestratorResultDAO:
        """Return an empty result for ``mode``."""
        return OrchestratorResultDAO(mode=mode)


class UnreachableInbox:
    """Channel stub whose database is unreachable."""

    async def list_pending_inbound_messages(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Fail like a broken shared database."""
        raise OSError("channels.db unreachable")


_SPAWN_ARGUMENTS: dict[str, object] = {
    "mode": "single",
    "tasks": [{"task_id": "review-1", "task_summary": "Review the channel slice", "prompt": "review it"}],
}


class TestSpawnResultCountsPendingChannelNotes:
    """C3 (orchestrator side): the dispatch result tells the model notes are waiting."""

    async def test_result_counts_notes_still_pending_for_the_orchestrator(
        self, channel_gateway: ChannelGateway
    ) -> None:
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        child_id: UUID = uuid4()
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        await channel_gateway.register_agent(session_id=child_id, name="review-1 (child)")
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(
            pool=NoteSendingDispatcher(gateway=channel_gateway, child_id=child_id, parent_id=parent_id),
            channel_notes=PendingChannelNotes(
                gateway=channel_gateway, recipient_session_id=orchestrator_session_id
            ),
        )

        output: dict[str, object] = json.loads(await spawn_tool.ainvoke(_SPAWN_ARGUMENTS))

        assert output["channel_notes_pending"] == 1

    async def test_result_reports_zero_notes_without_a_channel_binding(self) -> None:
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(pool=FixedResultDispatcher())

        output: dict[str, object] = json.loads(await spawn_tool.ainvoke(_SPAWN_ARGUMENTS))

        assert output["channel_notes_pending"] == 0

    async def test_unreachable_channel_database_reports_zero_notes_and_keeps_the_result(self) -> None:
        spawn_tool: BaseTool = SpawnSubAgentsTool.build(
            pool=FixedResultDispatcher(),
            channel_notes=PendingChannelNotes(gateway=UnreachableInbox(), recipient_session_id="orch-1"),
        )

        output: dict[str, object] = json.loads(await spawn_tool.ainvoke(_SPAWN_ARGUMENTS))

        assert (output["mode"], output["channel_notes_pending"]) == ("single", 0)


class OwnedSleeperChildSpawn:
    """Process-boundary stub that starts a real, test-owned sleeping child.

    The child is a real ``python -c 'sleep'`` process whose argv carries the
    pool's ``--session-id`` so the reaper's identity check matches it, and any
    signal the pool sends reaches only this test's own process. On spawn it
    registers the child participant and the parent queues one prompt to it, as
    a channel-aware child would; the child never closes its participant.
    """

    def __init__(self, *, gateway: ChannelGateway, parent_id: UUID) -> None:
        """Bind the queue and the parent identity."""
        self.processes: list[asyncio.subprocess.Process] = []
        self.queued_message_ids: list[UUID] = []
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
    ) -> asyncio.subprocess.Process:
        """Start the owned sleeper, register its participant and queue one prompt."""
        session_id: str = argv[argv.index("--session-id") + 1]
        process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "--session-id",
            session_id,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
        )
        self.processes.append(process)
        child_id: UUID = channel_participant_id_for_session(session_id=session_id)
        await self._gateway.register_agent(session_id=child_id, name="review-1 (child)")
        queued: ChannelMessageDAO = await self._gateway.send(
            new=NewMessageDAO(
                sender_id=self._parent_id, recipient_id=child_id, message_contents="also check tests"
            )
        )
        self.queued_message_ids.append(queued.id)
        return process

    async def wait_for_spawn(self) -> None:
        """Wait, with a bound, until the child is running and queued."""
        async with asyncio.timeout(10.0):
            while not self.queued_message_ids:
                await asyncio.sleep(0.01)

    async def kill_leftovers(self) -> None:
        """Kill and reap any owned child the pool did not terminate."""
        for process in self.processes:
            if process.returncode is None:
                process.kill()
                await process.wait()


class TestChildAbortAndCancellationClosesItsParticipant:
    """C5: aborting or cancelling a dispatch never leaves a child participant open."""

    async def _assert_child_closed(
        self, *, channel_gateway: ChannelGateway, child_session_id: str, queued_message_id: UUID
    ) -> None:
        """Assert the child participant is closed and its pending prompt cancelled."""
        child_participant: Optional[ParticipantDAO] = await channel_gateway.find_participant(
            participant_id=UUID(child_session_id)
        )
        queued: Optional[ChannelMessageDAO] = await channel_gateway.find_message(message_id=queued_message_id)
        assert child_participant is not None and child_participant.status == "closed"
        assert queued is not None and (queued.accepted_at, queued.cancel_reason) == (None, "aborted")

    async def test_pool_abort_reaps_the_owned_child_and_closes_its_participant(
        self, tmp_path: Path, channel_gateway: ChannelGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_SUBAGENT_TERMINATE_GRACE_SECONDS", "2")
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: OwnedSleeperChildSpawn = OwnedSleeperChildSpawn(gateway=channel_gateway, parent_id=parent_id)
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,  # type: ignore[arg-type]
            channel_gateway=channel_gateway,
        )
        child_session_id: str = str(uuid4())
        try:
            dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])
            )
            await spawn.wait_for_spawn()
            await asyncio.wait_for(pool.abort_dispatches(), timeout=20.0)
            result: OrchestratorResultDAO = await asyncio.wait_for(dispatch, timeout=20.0)

            assert result.all_completed is False
            assert spawn.processes[0].returncode is not None
            await self._assert_child_closed(
                channel_gateway=channel_gateway,
                child_session_id=child_session_id,
                queued_message_id=spawn.queued_message_ids[0],
            )
        finally:
            await spawn.kill_leftovers()

    async def test_cancelled_dispatch_without_a_winner_closes_the_child_participant(
        self, tmp_path: Path, channel_gateway: ChannelGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_SUBAGENT_TERMINATE_GRACE_SECONDS", "2")
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: OwnedSleeperChildSpawn = OwnedSleeperChildSpawn(gateway=channel_gateway, parent_id=parent_id)
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,  # type: ignore[arg-type]
            channel_gateway=channel_gateway,
        )
        child_session_id: str = str(uuid4())
        try:
            dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])
            )
            await spawn.wait_for_spawn()
            dispatch.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(dispatch, timeout=20.0)

            await self._assert_child_closed(
                channel_gateway=channel_gateway,
                child_session_id=child_session_id,
                queued_message_id=spawn.queued_message_ids[0],
            )
        finally:
            await spawn.kill_leftovers()


class HeldCloseChannelGateway:
    """The pool's channel boundary over a real SQLite gateway, with a test-held close.

    ``close_agent`` signals that it started, waits for the test's release, then
    closes through the real gateway and records whether the dispatch had already
    finished at that moment.
    """

    def __init__(self, *, gateway: ChannelGateway) -> None:
        """Wrap the real gateway; the close gate starts closed."""
        self._gateway: ChannelGateway = gateway
        self.close_started: asyncio.Event = asyncio.Event()
        self.release: asyncio.Event = asyncio.Event()
        self.dispatch: Optional[asyncio.Task[OrchestratorResultDAO]] = None
        self.dispatch_done_when_closed: list[bool] = []

    async def close_agent(self, *, session_id: UUID, reason: str) -> int:
        """Hold until released, then close through the real queue.

        Args:
            session_id (UUID): Child participant to close.
            reason (str): Cancellation reason for its pending rows.

        Returns:
            int: Pending rows the real gateway cancelled.
        """
        self.close_started.set()
        await self.release.wait()
        cancelled: int = await self._gateway.close_agent(session_id=session_id, reason=reason)
        self.dispatch_done_when_closed.append(self.dispatch is not None and self.dispatch.done())
        return cancelled


class TestCancellationDuringParticipantCloseIsJoined:
    """R8: participant closure is a joined lifecycle obligation, with or without a winner."""

    async def test_cancel_while_closing_after_the_winner_still_closes_before_dispatch_ends(
        self, tmp_path: Path, channel_gateway: ChannelGateway
    ) -> None:
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: ChannelChildSpawn = ChannelChildSpawn(
            gateway=channel_gateway, parent_id=parent_id, exit_code=0, closes_itself=False
        )
        held: HeldCloseChannelGateway = HeldCloseChannelGateway(gateway=channel_gateway)
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,
            channel_gateway=held,  # type: ignore[arg-type]
        )
        child_session_id: str = str(uuid4())
        dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
            pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])
        )
        held.dispatch = dispatch
        await asyncio.wait_for(held.close_started.wait(), timeout=10.0)
        winner = pool.registry.get(session_id=child_session_id)
        assert winner is not None and winner.status == "completed"

        dispatch.cancel()
        for _ in range(20):
            await asyncio.sleep(0)
        assert dispatch.done() is False
        held.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(dispatch, timeout=10.0)

        assert held.dispatch_done_when_closed == [False]
        child_participant: Optional[ParticipantDAO] = await channel_gateway.find_participant(
            participant_id=UUID(child_session_id)
        )
        queued: Optional[ChannelMessageDAO] = await channel_gateway.find_message(
            message_id=spawn.queued_message_ids[0]
        )
        assert child_participant is not None and child_participant.status == "closed"
        assert queued is not None and (queued.accepted_at, queued.cancel_reason) == (None, "aborted")
        # The child's terminal result survives the dispatch cancellation unchanged.
        final = pool.registry.get(session_id=child_session_id)
        assert final is not None and final.status == "completed"

    async def test_cancel_while_closing_without_a_winner_closes_before_dispatch_ends(
        self, tmp_path: Path, channel_gateway: ChannelGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_SUBAGENT_TERMINATE_GRACE_SECONDS", "2")
        orchestrator_session_id: str = str(uuid4())
        parent_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        await channel_gateway.register_agent(session_id=parent_id, name="orchestrator W")
        spawn: OwnedSleeperChildSpawn = OwnedSleeperChildSpawn(gateway=channel_gateway, parent_id=parent_id)
        held: HeldCloseChannelGateway = HeldCloseChannelGateway(gateway=channel_gateway)
        pool: SubAgentPool = _channel_pool(
            tmp_path=tmp_path,
            orchestrator_session_id=orchestrator_session_id,
            spawn=spawn,  # type: ignore[arg-type]
            channel_gateway=held,  # type: ignore[arg-type]
        )
        child_session_id: str = str(uuid4())
        try:
            dispatch: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="review-1", session_id=child_session_id)])
            )
            held.dispatch = dispatch
            await spawn.wait_for_spawn()
            dispatch.cancel()
            await asyncio.wait_for(held.close_started.wait(), timeout=20.0)
            dispatch.cancel()
            for _ in range(20):
                await asyncio.sleep(0)
            assert dispatch.done() is False
            held.release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(dispatch, timeout=20.0)

            assert held.dispatch_done_when_closed == [False]
            child_participant: Optional[ParticipantDAO] = await channel_gateway.find_participant(
                participant_id=UUID(child_session_id)
            )
            queued: Optional[ChannelMessageDAO] = await channel_gateway.find_message(
                message_id=spawn.queued_message_ids[0]
            )
            assert child_participant is not None and child_participant.status == "closed"
            assert queued is not None and (queued.accepted_at, queued.cancel_reason) == (None, "aborted")
        finally:
            await spawn.kill_leftovers()
