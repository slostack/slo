"""Critical live output failure through the real session and owned graph/tool lifetime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory, RecordingModel
from tests.integration.test_messaging_yield import isolated_journey_tasks
from tests.integration.test_session_messaging import read_closed_message_rows
from tests.tui.test_durable_composer import _wait_until


class FailingOutputHistory(FilesystemSessionHistoryStore):
    """Inject failure only at the public canonical append boundary, retaining all real files."""

    async def append_event(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Refuse live tool snapshots, leaving cooperative and terminal persistence real."""
        if event.kind == "tool_output_update":
            raise OSError("injected output persistence failure")
        return await super().append_event(event=event)


async def test_output_history_failure_joins_tool_and_preserves_unapplied_urgent(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """A failed output write cannot retry or enter another provider before tool cleanup joins."""
    entered, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @tool
    async def held_output(config: RunnableConfig) -> str:
        """Keep graph-owned work live until failure cleanup has waited for its actual result."""
        try:
            entered.set()
            callback = config["configurable"]["slo_tool_output_update_callback"]
            await callback(
                snapshot=ToolOutputUpdateDAO(tool_call_id="", tool_name="", content_snapshot="unpersistable")
            )
            await release.wait()
            return "real result"
        finally:
            joined.set()

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    model = RecordingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"id": "output", "name": "held_output", "args": {}}]),
            AIMessage(content="forbidden next request"),
        ]
    )
    model.release.set()
    history = FailingOutputHistory(root=root)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[held_output]),
    )
    client = None
    urgent = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="start"
            )
        )
        await _wait_until(predicate=entered.is_set)
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="retain",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        release.set()
        await _wait_until(predicate=lambda: joined.is_set() and not session.is_running)
        assert len(model.requests) == 1
        events = await history.load_events(session_id=session_id)
        assert not any(e.kind == "run_completed" for e in events)
        assert sum("messaging_v1" in e.payload.metadata for e in events) == 1
    finally:
        release.set()
        if client is not None:
            await client.close()
        await session.close_messaging()
    assert urgent is not None
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (urgent.message_id, 1, "accepted") in rows


async def test_session_side_public_consumer_failure_joins_before_idle(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """A real session consumer failure retains public invocation cleanup before pause."""
    from collections.abc import AsyncIterator
    from typing import Optional
    from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import ChatGenerationChunk

    class FailingHistory(FilesystemSessionHistoryStore):
        async def append_event(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
            """Fail the public session consumer's real text-end persistence boundary."""
            if event.kind == "run_retrying":
                raise OSError("controlled consumer failure")
            return await super().append_event(event=event)

    # A session's bounded retry-status persistence is downstream of agent.invoke.
    # Use the existing source factory and provider failure to reach that consumer,
    # rather than replacing any session private method.
    class RetryNoticeProvider(RecordingModel):
        def __init__(self, *, responses: list[AIMessage]) -> None:
            """Construct the external failure script."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Fail before output with a retryable rate response."""
            import httpx

            self.requests.append(list(messages))
            self.entered.set()
            await self.release.wait()
            raise httpx.HTTPStatusError(
                "Rate limit reached; retry in 1s",
                request=httpx.Request(method="POST", url="https://provider.invalid"),
                response=httpx.Response(status_code=429),
            )
            if False:
                yield ChatGenerationChunk(message=AIMessage(content="unreachable"))

    model = RetryNoticeProvider(responses=[])
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    history = FailingHistory(root=root)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        history_store=history,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
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
        # Normal admission keeps the retry-status consumer branch, rather than
        # reserving provider yield before the external failure is observed.
        pending = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="retained",
            priority="normal",
        )
        await client.submit(submission=pending)
        model.release.set()
        await _wait_until(predicate=lambda: not session.is_running)
        assert len(model.requests) == 1
        events = await history.load_events(session_id=session_id)
        assert not any(event.kind == "run_completed" for event in events)
        assert sum("messaging_v1" in event.payload.metadata for event in events) == 1
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (pending.message_id, 1, "accepted") in rows
