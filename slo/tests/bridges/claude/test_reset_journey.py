"""Combined reset and child-drain journeys on the shared host lifecycle."""

import asyncio
from pathlib import Path
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.reaper import ReapOutcome
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.bridge import SloClaudeBridge
from tests.cli.test_claude_bridge import scripted_adapter_class
from tests.bridges.claude.test_steering import ReconnectingToolRoundTransport


async def test_abort_then_prompt_then_new_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A13: abort joins a parked owner, history hands off, mounted /new starts empty."""
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ReconnectingToolRoundTransport(path=tmp_path / "unused")
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="reset-old",
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    try:
        async with asyncio.timeout(15), app.run_test() as pilot:
            await pilot.pause()
            events: list[AgentStreamEventDAO] = []
            async for event in session.invoke(text="Read old target"):
                events.append(event)
                if event.kind == "tool_call_start":
                    session.abort()
            assert sum(event.kind == "run_aborted" for event in events) == 1
            model = session.agent.llm
            assert isinstance(model, SloClaudeBridge) and model.is_retired()
            assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
            runtime = model.bridge_adapter._runtime
            assert runtime._owner is not None and runtime._tool_bridge is not None
            assert runtime._owner.done() and not runtime._tool_bridge.pending_calls
            followup: list[AgentStreamEventDAO] = [
                event async for event in session.invoke(text="Resume from audit")
            ]
            assert followup[-1].kind == "run_completed"
            assert "Read old target" in str(transport.prompts[-1])
            app.query_one(PromptInputComponent).text = "/new"
            await pilot.press("enter")
            await pilot.pause()
            assert app._session is not session
            successor = app._session
            assert successor is not None and successor.session_id != session.session_id
            assert await successor._load_message_history() == []
            stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
                root=tmp_path / "history"
            ).load_events(session_id=session.session_id)
            assert sum(event.kind == "run_aborted" for event in stored) == 1
            assert sum(event.kind == "run_completed" for event in stored) == 1
            assert transport.closed and transport.close_calls == 2
    finally:
        await session.close_agent_resources()


async def test_abort_while_claude_children_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A14: host abort drains real pool ownership and native waiters before terminal."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool
    from src.agents.slo_agent.orchestrator.process import SubAgentProcess
    from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO
    from tests.bridges.claude.test_orchestrator_tools import DelegatingTransport

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    started = asyncio.Event()
    stopped = asyncio.Event()

    class RunningChild(SubAgentProcess):
        """Hold scripted child work until the pool requests cancellation."""

        async def run(self) -> SubAgentResultDAO:
            """Wait without a real subprocess and publish the canonical abort terminal."""
            started.set()
            await stopped.wait()
            return self._publish_terminal(
                candidate=SubAgentResultDAO(
                    task_id=self.task.task_id,
                    session_id=self.session_id,
                    execution_id=self.execution_id,
                    status="aborted",
                    answer="aborted",
                    exit_code=2,
                ),
                terminal_reason="operator_abort",
                terminated_by="abort",
            )

        async def cancel(self) -> ReapOutcome | None:
            """Stop the injected process boundary; no OS signal is issued."""
            stopped.set()
            return "killed"

    class RunningBootstrap(OrchestratorSessionBootstrap):
        """Inject only the child process factory into the existing real pool."""

        @classmethod
        def _build_pool(cls, *, session: SloAgentSession, owner_session_id: str) -> SubAgentPool:
            """Retain real pool registration, concurrency and drain behavior."""
            return SubAgentPool(
                orchestrator_session_id=session.session_id,
                default_model=session.active_model_name,
                relay=session.event_relay,
                owner_session_id=owner_session_id,
                run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
                history_root=tmp_path / "history",
                process_factory=RunningChild,
            )

    transport = DelegatingTransport(path=tmp_path / "unused")
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="child-abort",
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    RunningBootstrap.attach(session=session)
    events: list[AgentStreamEventDAO] = []

    async def consume() -> None:
        """Consume the real graph while child work remains active."""
        async for event in session.invoke(text="Delegate inspection"):
            events.append(event)

    run = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(10):
            await started.wait()
            session.abort()
            await run
            assert stopped.is_set()
            assert sum(event.kind == "run_aborted" for event in events) == 1
            assert not any(event.kind == "run_completed" for event in events)
            pool = session._sub_agent_pool
            assert pool is not None and not pool._active_by_session_id
            assert all(entry.status == "aborted" for entry in pool.registry.snapshot())
            model = session.agent.llm
            assert isinstance(model, SloClaudeBridge) and model.is_retired()
            assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
            runtime = model.bridge_adapter._runtime
            assert runtime._owner is not None and runtime._tool_bridge is not None
            assert runtime._owner.done() and not runtime._tool_bridge.pending_calls
            assert transport.closed
    finally:
        stopped.set()
        await asyncio.gather(run, return_exceptions=True)
        await session.close_agent_resources()
