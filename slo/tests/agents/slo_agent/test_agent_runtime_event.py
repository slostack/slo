"""Tests for ``SloAgent`` runtime trace events (sub-spec 05.b §8)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO
from src.agents.providers import FauxChatModel


@tool
def stub_now() -> str:
    """Stub tool returning a fixed iso8601 timestamp."""
    return "ALPHA-BETA-GAMMA-" + "x" * 1_000  # large enough to detect truncation


async def _capture(events: list[AgentRuntimeEventDAO]) -> Callable[[AgentRuntimeEventDAO], Awaitable[None]]:
    """Return an async trace handler that appends to ``events``."""

    async def _handler(event: AgentRuntimeEventDAO) -> None:
        events.append(event)

    return _handler


async def _collect_final_response(*, agent: SloAgent, query: str) -> str:
    """Drain ``agent.invoke`` and return the final assistant text.

    Args:
        agent (SloAgent): Agent under test.
        query (str): Prompt text.

    Returns:
        str: Final response text.
    """
    final_response: str = ""
    async for event in agent.invoke(query=query):
        if event.kind == "run_completed":
            final_response = event.content or ""
    return final_response


@pytest.mark.asyncio
async def test_react_streaming_emits_run_started_trace_event() -> None:
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        tools=[],
    )

    async for _ in agent.invoke(query="hello", runtime_handler=handler):
        pass

    assert captured[0].kind == "run_started"
    assert captured[0].payload.content == "hello"


@pytest.mark.asyncio
async def test_react_streaming_emits_assistant_delta_trace_events_for_visible_thinking_and_text() -> None:
    """Visible thinking/text stream events are forwarded onto the runtime trace seam."""
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[FauxChatModel.assistant_message(content="final answer")],
            chunk_scripts=[
                [
                    AIMessageChunk(
                        content=[
                            {"type": "thinking", "thinking": "plan"},
                            {"type": "text", "text": "partial"},
                        ]
                    )
                ]
            ],
        ),
        tools=[],
    )

    async for _ in agent.invoke(query="hello", runtime_handler=handler):
        pass

    assistant_deltas: list[AgentRuntimeEventDAO] = [
        event for event in captured if event.kind == "assistant_delta"
    ]
    assert [event.payload.delta_kind for event in assistant_deltas] == [
        "thinking_start",
        "thinking_delta",
        "thinking_end",  # implicit close (no content) when text block opens
        "text_start",
        "text_delta",
        "thinking_end",  # repair event from finalize_open_blocks (with completed content)
        "text_end",
    ]


@pytest.mark.asyncio
async def test_react_streaming_emits_full_tool_call_trace_event() -> None:
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="ok"),
            ],
        ),
        tools=[stub_now],
    )

    async for _ in agent.invoke(query="when?", runtime_handler=handler):
        pass

    tool_calls: list[AgentRuntimeEventDAO] = [e for e in captured if e.kind == "tool_call"]
    assert tool_calls, "Expected at least one tool_call trace event"
    assert tool_calls[0].payload.tool_name == "stub_now"
    assert tool_calls[0].payload.tool_calls is not None


@pytest.mark.asyncio
async def test_react_streaming_emits_full_untruncated_tool_result_trace_event() -> None:
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="done"),
            ],
        ),
        tools=[stub_now],
    )

    async for _ in agent.invoke(query="time?", runtime_handler=handler):
        pass

    tool_results: list[AgentRuntimeEventDAO] = [e for e in captured if e.kind == "tool_result"]
    assert tool_results
    # Full fidelity: the raw return value is ~1000+ chars and must not be
    # truncated to the render preview cap.
    assert tool_results[0].payload.tool_output is not None
    assert len(tool_results[0].payload.tool_output) > 500


@pytest.mark.asyncio
async def test_react_streaming_emits_run_completed_trace_event() -> None:
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        tools=[],
    )

    async for _ in agent.invoke(query="hello", runtime_handler=handler):
        pass

    assert captured[-1].kind == "run_completed"


@pytest.mark.asyncio
async def test_react_streaming_normalizes_responses_content_blocks_in_trace_events() -> None:
    """Responses-style assistant content is persisted as plain text, not ``str(list)``."""
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                AIMessage(content=[{"type": "text", "text": "normalized text"}]),
            ]
        ),
        tools=[],
    )

    async for _ in agent.invoke(query="hello", runtime_handler=handler):
        pass

    assistant_events: list[AgentRuntimeEventDAO] = [
        event for event in captured if event.kind == "assistant_message"
    ]
    assert assistant_events[-1].payload.content == "normalized text"
    assert captured[-1].payload.content == "normalized text"


@pytest.mark.asyncio
async def test_react_streaming_emits_run_aborted_trace_event() -> None:
    captured: list[AgentRuntimeEventDAO] = []
    handler = await _capture(events=captured)
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        tools=[],
    )
    agent.abort()

    async for _ in agent.invoke(query="hello", runtime_handler=handler):
        pass

    assert any(e.kind == "run_aborted" for e in captured)


@pytest.mark.asyncio
async def test_react_without_runtime_handler_behaves_as_before() -> None:
    """No-handler path stays identical to the pre-05.b behaviour."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        tools=[],
    )

    result: str = await _collect_final_response(agent=agent, query="hello")

    assert result == "hi"


@pytest.mark.asyncio
async def test_react_rejects_both_history_representations() -> None:
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
        tools=[],
    )

    with pytest.raises(ValueError):
        async for _ in agent.invoke(
            query="hi",
            history=[{"role": "user", "content": "x"}],
            message_history=[],
        ):
            pass
