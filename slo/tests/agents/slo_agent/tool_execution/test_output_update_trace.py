"""A3 tests: ``tool_output_update`` on the persisted trace and headless stdout.

Finding A3 resolution: ``tool_output_update`` is present on the headless
stdout JSONL event stream (always on) AND on the persisted history trace when
history is enabled — while remaining excluded from model-visible replay.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO, AgentRuntimePayloadDAO
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.tool_output import ToolOutputUpdateDAO


def _history_event(*, kind: str) -> SessionHistoryEventDAO:
    """Build one canonical history event for projector tests.

    Args:
        kind (str): Event kind discriminator.

    Returns:
        SessionHistoryEventDAO: The event with an empty payload.
    """
    return SessionHistoryEventDAO(
        session_id="s",
        turn_id="t1",
        kind=kind,  # type: ignore[arg-type]
        payload=SessionHistoryEventPayloadDAO(),
    )


class TestHistoryReplayExclusion:
    """``tool_output_update`` never enters model-visible replay (AC#12)."""

    @pytest.mark.asyncio
    async def test_build_message_history_excludes_tool_output_update(self) -> None:
        """A persisted partial update projects to no model message."""
        events: list[SessionHistoryEventDAO] = [
            _history_event(kind="user_message"),
            _history_event(kind="tool_output_update"),
            _history_event(kind="tool_result"),
            _history_event(kind="run_completed"),
        ]

        messages = await SessionHistoryProjector.build_message_history(events=events)

        kinds: list[str] = [type(message).__name__ for message in messages]
        assert "HumanMessage" in kinds
        assert len(messages) == 1


class TestPersistedTrace:
    """The runtime trace carries the partial snapshot into history (A3)."""

    @pytest.mark.asyncio
    async def test_session_runtime_handler_persists_tool_output_update(self, tmp_path: Path) -> None:
        """The session's trace handler writes one history event per update."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        agent: SloAgent = SloAgent(llm=faux, cwd=str(tmp_path))
        session: SloAgentSession = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id="a3-trace",
        )
        persisted: list[SessionHistoryEventDAO] = []

        async def _capture(*, event: SessionHistoryEventDAO) -> None:
            """Record one appended history event.

            Args:
                event (SessionHistoryEventDAO): The event being persisted.
            """
            persisted.append(event)

        session._append_history_event = _capture  # type: ignore[method-assign]
        handler = session._runtime_handler_for_turn(turn_id="t1")

        await handler(
            AgentRuntimeEventDAO(
                kind="tool_output_update",
                iteration=0,
                payload=AgentRuntimePayloadDAO(
                    content="exit_code: 0\npartial",
                    tool_name="bash",
                    tool_call_id="call-1",
                    metadata={"truncated": False},
                ),
            )
        )

        assert len(persisted) == 1
        assert persisted[0].kind == "tool_output_update"
        assert persisted[0].payload.content == "exit_code: 0\npartial"
        assert persisted[0].payload.tool_call_id == "call-1"

    @pytest.mark.asyncio
    async def test_agent_emits_runtime_trace_for_drained_updates(self, tmp_path: Path) -> None:
        """A drained queue snapshot reaches the runtime handler as a trace event."""
        traces: list[AgentRuntimeEventDAO] = []

        async def _handler(event: AgentRuntimeEventDAO) -> None:
            """Collect one runtime trace event.

            Args:
                event (AgentRuntimeEventDAO): The trace event.
            """
            traces.append(event)

        faux: FauxChatModel = FauxChatModel(responses=[AIMessage(content="done")])
        agent: SloAgent = SloAgent(llm=faux, cwd=str(tmp_path))
        await agent._output_update_queue.put(
            ToolOutputUpdateDAO(
                tool_call_id="call-1",
                tool_name="bash",
                content_snapshot="partial",
            )
        )

        async for _ in agent.invoke(query="hi", runtime_handler=_handler):
            pass

        update_traces: list[AgentRuntimeEventDAO] = [
            trace for trace in traces if trace.kind == "tool_output_update"
        ]
        assert len(update_traces) == 1
        assert update_traces[0].payload.tool_call_id == "call-1"


class TestHeadlessStdoutJsonl:
    """The headless stdout JSONL stream includes the update events (A3)."""

    @pytest.mark.asyncio
    async def test_headless_emit_writes_tool_output_update_jsonl(self) -> None:
        """``HeadlessRunner._emit`` serializes updates onto stdout like any event."""
        from src.agents.slo_agent.events.stream import AgentStreamEventDAO
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO
        from src.cli.headless import HeadlessRunner

        runner: HeadlessRunner = HeadlessRunner(
            config=SessionConfigDAO(workdir=Path("/tmp/a3-headless")),
        )
        import io
        import sys

        buffer: io.StringIO = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = buffer
            await runner._emit(
                AgentStreamEventDAO(
                    kind="tool_output_update",
                    tool_call_id="call-1",
                    tool_name="bash",
                    content="exit_code: 0\npartial",
                    metadata={"truncated": False},
                )
            )
        finally:
            sys.stdout = original_stdout

        line: str = buffer.getvalue().strip()
        assert line
        parsed: dict = json.loads(line)
        assert parsed["kind"] == "tool_output_update"
        assert parsed["tool_call_id"] == "call-1"
        assert parsed["content"] == "exit_code: 0\npartial"
