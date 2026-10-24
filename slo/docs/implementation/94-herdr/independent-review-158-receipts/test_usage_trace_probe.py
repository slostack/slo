"""Independent regression probe for completed usage before trace cancellation."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO


async def test_completed_usage_survives_trace_cancellation(tmp_path: Path) -> None:
    """A completed provider response must remain chargeable after trace cancellation."""
    observed: list[str] = []
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                AIMessage(
                    content="done", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
                )
            ]
        ),
        tools=[],
        cwd=str(tmp_path),
    )

    async def trace(event: AgentRuntimeEventDAO) -> None:
        """Interrupt at the real completed-message history callback boundary."""
        observed.append(event.kind)
        if event.kind == "assistant_message":
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        async for _ in agent.invoke(query="hello", runtime_handler=trace):
            pass
    assert "assistant_message" in observed
    assert agent.consume_completed_usage().total_tokens == 3


async def test_session_completed_usage_survives_history_append_cancellation(tmp_path: Path) -> None:
    """Exercise the actual session trace handler and durable append before interruption."""
    from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
    from src.agents.slo_agent.sessions.service import SloAgentSession

    appended = asyncio.Event()

    class InterruptedStore(FilesystemSessionHistoryStore):
        """Cancel after the real completed-assistant append, not before provider completion."""

        async def append_event(self, *, event: SessionHistoryEventDAO) -> None:
            """Persist real history and expose the cancellation window at callback return."""
            await super().append_event(event=event)
            if event.kind == "assistant_message":
                appended.set()
                await asyncio.Future()

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = InterruptedStore(root=root)
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                AIMessage(
                    content="done", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
                )
            ]
        ),
        tools=[],
        cwd=str(tmp_path),
    )
    session = SloAgentSession(
        agent=agent, workdir=tmp_path, session_id="trace-usage", history_store=store, enable_history=True
    )

    async def consume() -> list[str]:
        """Drive the public session while retaining the real prompt task."""
        return [event.kind async for event in session.invoke(text="hello")]

    task = asyncio.create_task(coro=consume())
    try:
        await asyncio.wait_for(fut=appended.wait(), timeout=5)
        task.cancel()
        events = await asyncio.wait_for(fut=task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    persisted = await store.load_events(session_id=session.session_id)
    assert sum(event.kind == "assistant_message" for event in persisted) == 1
    assert sum(event.kind == "run_aborted" for event in persisted) == 1
    assert "run_completed" not in events
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 3
