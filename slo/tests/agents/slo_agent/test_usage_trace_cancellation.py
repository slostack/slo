"""Completed-node usage remains owned across cancellable trace observers."""

import asyncio
from pathlib import Path
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession


async def test_agent_usage_when_trace_is_externally_cancelled(tmp_path: Path) -> None:
    """Cancel the public consumer while its completed-message observer is pending."""
    entered = asyncio.Event()
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
        """Signal completed-message arrival, then remain pending until cancellation."""
        observed.append(event.kind)
        if event.kind == "assistant_message":
            entered.set()
            await asyncio.Event().wait()

    async def consume() -> list[str]:
        """Drive the real Faux graph through the public agent gateway."""
        return [event.kind async for event in agent.invoke(query="hello", runtime_handler=trace)]

    task = asyncio.create_task(coro=consume())
    try:
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(fut=task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert observed.count("assistant_message") == 1
    assert observed.count("run_completed") == 0
    assert agent.usage_capture_version == 1
    assert agent.last_usage_totals.total_tokens == 3
    assert agent.consume_completed_usage().total_tokens == 3
    assert agent.consume_completed_usage().total_tokens is None


@pytest.mark.parametrize(argnames="message_count", argvalues=[1, 2])
async def test_completed_delta_usage_when_trace_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message_count: int
) -> None:
    """Even eventless/multiple completions are captured before the first failing trace."""
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))
    messages = [
        AIMessage(
            id=str(index),
            content="",
            usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        )
        for index in range(message_count)
    ]
    advances = 0
    observed: list[str] = []
    failure = RuntimeError("trace failure")

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Deliver one completed node delta without messages-mode output."""
        nonlocal advances
        advances += 1
        yield ("updates", {"agent": {"messages": messages}})

    async def trace(event: AgentRuntimeEventDAO) -> None:
        """Fail only the first completed-message observation, preserving exception identity."""
        observed.append(event.kind)
        if event.kind == "assistant_message":
            raise failure

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    with pytest.raises(RuntimeError) as raised:
        async for _ in agent.invoke(query="hello", runtime_handler=trace):
            pass
    assert raised.value is failure
    assert advances == observed.count("assistant_message") == observed.count("run_failed") == 1
    assert observed.count("run_completed") == 0
    assert agent.usage_capture_version == 1
    assert agent.consume_completed_usage().total_tokens == 3 * message_count
    assert agent.consume_completed_usage().total_tokens is None


@pytest.mark.parametrize(argnames="persist_first", argvalues=[False, True])
async def test_session_usage_when_append_is_externally_cancelled(tmp_path: Path, persist_first: bool) -> None:
    """Cancel before/after real append; final session accounting must retain completion."""
    entered = asyncio.Event()

    class InterruptedStore(FilesystemSessionHistoryStore):
        """Expose the exact completed-message append boundary to the test consumer."""

        async def append_event(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
            """Delegate durable writes, holding only the selected assistant append."""
            if event.kind != "assistant_message":
                return await super().append_event(event=event)
            if persist_first:
                await super().append_event(event=event)
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancellation barrier unexpectedly returned")

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
        """Drive the public session; its existing cancellation policy returns aborted."""
        return [event.kind async for event in session.invoke(text="hello")]

    task = asyncio.create_task(coro=consume())
    try:
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        task.cancel()
        events = await asyncio.wait_for(fut=task, timeout=5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    persisted = await store.load_events(session_id=session.session_id)
    kinds = [event.kind for event in persisted]
    assert kinds.count("assistant_message") == int(persist_first)
    assert kinds.count("user_message") == kinds.count("run_started") == kinds.count("run_aborted") == 1
    assert kinds.count("run_completed") == kinds.count("run_failed") == 0
    assert events.count("run_aborted") == 1
    assert not set(events) & {"run_completed", "run_retrying", "recovery_started"}
    assert agent.usage_capture_version == 1
    assert agent.last_usage_totals.total_tokens == 3
    for _ in range(2):
        assert session.refresh_usage_snapshot().session_totals.total_tokens == 3
    assert agent.consume_completed_usage().total_tokens is None
