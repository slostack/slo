"""Real session consumer/correlation failures retain the public invocation join barrier."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import aclosing
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO, AgentRuntimeHandler
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO
from src.agents.slo_agent.messaging.delivery import AgentMessageSource
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.integration.test_messaging_yield import isolated_journey_tasks
from tests.integration.test_session_messaging import read_closed_message_rows
from tests.tui.test_durable_composer import _wait_until


class HeldLiveProvider(RecordingModel):
    """Emit live output, then hold cleanup independently of the request gate."""

    closing: asyncio.Event = Field(default_factory=asyncio.Event, description="Cleanup entered.")
    joined: asyncio.Event = Field(default_factory=asyncio.Event, description="Cleanup terminated.")
    cleanup_release: asyncio.Event = Field(default_factory=asyncio.Event, description="Allow cleanup.")
    closes: int = Field(default=0, description="Exact provider cleanup count.")

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Keep explicit external provider script construction."""
        super().__init__(responses=responses)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Expose a real live chunk while retaining independently held provider ownership."""
        self.requests.append(list(messages))
        self.entered.set()
        try:
            await self.release.wait()
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
            await asyncio.Event().wait()
        finally:
            self.closes += 1
            self.closing.set()
            await self.cleanup_release.wait()
            self.joined.set()


class ConsumerFailureHistory(FilesystemSessionHistoryStore):
    """Fail at the session consumer's actual public-event persistence boundary."""

    async def append_event(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Retain all real history except the deliberately rejected child audit event."""
        if event.kind == "sub_agent_spawned":
            raise OSError("controlled consumer write failure")
        return await super().append_event(event=event)


class ContractProbeAgent(SloAgent):
    """Inject faults at public agent interfaces without replacing graph or session behavior."""

    def __init__(
        self, *, model: HeldLiveProvider, source: AgentMessageSource, workdir: Path, mismatch: bool
    ) -> None:
        """Borrow the real source and external provider, retaining one real compiled graph."""
        super().__init__(llm=model, tools=[], cwd=str(workdir), message_source=source)
        self.mismatch = mismatch
        self.releases: list[bool] = []
        self.model = model
        self.public_joined = False

    async def invoke(
        self, *, runtime_handler: Optional[AgentRuntimeHandler] = None, **kwargs: Any
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Wrap the public contract, forwarding framework invoke kwargs unchanged.

        The consumer case converts one actual live event into an ordinary child
        audit publication so the *session*, outside agent.invoke, fails persistence.
        The mismatch case changes only runtime metadata presented to the injected
        real session handler. Neither fault replaces persistence, graph or joins.
        """

        async def trace(event: AgentRuntimeEventDAO) -> None:
            """Present contradictory correlation at the existing runtime-handler seam."""
            if self.mismatch and event.kind == "assistant_delta":
                event = event.model_copy(
                    update={
                        "payload": event.payload.model_copy(
                            update={"metadata": {**event.payload.metadata, "attempt_turn_id": str(uuid4())}}
                        )
                    }
                )
            if runtime_handler is not None:
                await runtime_handler(event)

        async with aclosing(super().invoke(runtime_handler=trace, **kwargs)) as stream:
            async for event in stream:
                if not self.mismatch and event.kind == "text_delta":
                    yield event.model_copy(update={"kind": "sub_agent_spawned", "sub_agent_id": str(uuid4())})
                else:
                    yield event
        self.public_joined = True

    def release_tool_execution(self, *, tool_execution_control: ToolExecutionControl) -> None:
        """Record the public lifecycle release only after real provider cleanup joined."""
        self.releases.append(self.model.joined.is_set())
        super().release_tool_execution(tool_execution_control=tool_execution_control)


@pytest.mark.parametrize(argnames="mismatch", argvalues=[False, True])
async def test_session_failure_joins_held_provider_before_idle_or_binding_release(
    tmp_path: Path, mismatch: bool, isolated_journey_tasks: None
) -> None:
    """Consumer failure and runtime mismatch cannot release ownership or claim pending input."""
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model = HeldLiveProvider(responses=[])
    agents: list[ContractProbeAgent] = []

    def factory(*, message_source: AgentMessageSource) -> SloAgent:
        """Inject a real agent with a narrow public-contract fault probe."""
        agent = ContractProbeAgent(model=model, source=message_source, workdir=tmp_path, mismatch=mismatch)
        agents.append(agent)
        return agent

    history = ConsumerFailureHistory(root=root)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=factory,
    )
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
            )
        )
        await _wait_until(predicate=model.entered.is_set)
        pending = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="retained"
        )
        await client.submit(submission=pending)
        model.release.set()
        await _wait_until(predicate=model.closing.is_set)
        assert session.is_running and not agents[0].releases
        competing = agents[0].invoke(query="must refuse")
        with pytest.raises(RuntimeError, match="processing"):
            await anext(competing)
        await competing.aclose()
        assert len(model.requests) == 1 and model.closes == 1
        events = await history.load_events(session_id=session.session_id)
        assert not any(event.kind in {"run_completed", "run_failed"} for event in events)
        model.cleanup_release.set()
        await _wait_until(predicate=lambda: not session.is_running)
        assert agents[0].releases == [True]
        assert model.joined.is_set() and model.closes == 1 and len(model.requests) == 1
        events = await history.load_events(session_id=session.session_id)
        assert sum(event.kind == "run_failed" for event in events) == 1
        assert not any(event.kind == "run_completed" for event in events)
        assert sum("messaging_v1" in event.payload.metadata for event in events) == 1
        if mismatch:
            assert not any(event.kind == "assistant_delta" for event in events)
            assert "cooperative_yield_settlement_failed" in str(
                [event.payload for event in events if event.kind == "run_failed"]
            )
    finally:
        model.release.set()
        model.cleanup_release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session.session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (pending.message_id, 1, "accepted") in rows
