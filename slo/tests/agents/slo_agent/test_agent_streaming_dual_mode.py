"""Tests for Slo's dual-stream agent loop."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool

from src.agents.hooks import ShouldStopAfterTurnHookContextDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.providers import FauxChatModel


@tool
def stub_now() -> str:
    """Stub tool returning a fixed timestamp."""
    return "2026-06-10T00:00:00Z"


class TestDualStreamLoop:
    """Channel ownership, final-answer truth, and abort behavior."""

    @pytest.mark.asyncio
    async def test_prefers_completed_assistant_message_for_final_answer(self) -> None:
        """Final answer comes from the completed update-channel assistant message."""

        class _StubGraph:
            async def astream(self, *_args, **_kwargs):
                yield ("messages", AIMessageChunk(content="partial "))
                yield ("messages", AIMessageChunk(content="streamed text"))
                yield (
                    "updates",
                    {"agent": {"messages": [AIMessage(content="completed truth")]}},
                )

        agent: SloAgent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="unused")]),
            tools=[],
        )
        agent._graph = _StubGraph()  # type: ignore[assignment]

        events = [event async for event in agent.invoke(query="hello")]

        assert [event.kind for event in events[:-1]] == [
            "text_start",
            "text_delta",
            "text_delta",
            "text_end",
        ]
        assert events[-1].kind == "run_completed"
        assert events[-1].content == "completed truth"

    @pytest.mark.asyncio
    async def test_updates_channel_emits_tool_result_but_not_visible_text_delta(self) -> None:
        """Tool results come from updates while assistant deltas come from messages."""
        faux: FauxChatModel = FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="done"),
            ],
            chunk_scripts=[
                [
                    AIMessageChunk(
                        content="",
                        tool_calls=[{"id": "call_1", "name": "stub_now", "args": {}}],
                    )
                ],
                [AIMessageChunk(content="done")],
            ],
        )
        agent: SloAgent = SloAgent(llm=faux, tools=[stub_now])

        events = [event async for event in agent.invoke(query="when?")]

        assert any(event.kind == "tool_call_start" for event in events)
        tool_call_end = next(event for event in events if event.kind == "tool_call_end")
        assert tool_call_end.tool_input == {}
        assert any(event.kind == "tool_result" for event in events)
        assert events[-1].kind == "run_completed"
        assert events[-1].content == "done"

    @pytest.mark.asyncio
    async def test_abort_before_run_starts_yields_single_terminal_abort_event(self) -> None:
        """Pre-start abort returns one terminal abort event immediately."""
        agent: SloAgent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")]),
            tools=[],
        )
        agent.abort()

        events = [event async for event in agent.invoke(query="hello")]

        assert len(events) == 1
        assert events[0].kind == "run_aborted"
        assert events[0].content == "<aborted>"

    @pytest.mark.asyncio
    async def test_abort_mid_stream_yields_exactly_one_terminal_abort_event(self) -> None:
        """Mid-stream abort emits one terminal abort event and stops."""
        faux: FauxChatModel = FauxChatModel(
            responses=[FauxChatModel.assistant_message(content="completed truth")],
            chunk_scripts=[[AIMessageChunk(content="partial "), AIMessageChunk(content="more")]],
        )
        agent: SloAgent = SloAgent(llm=faux, tools=[])

        stream = agent.invoke(query="hello")
        first_event = await stream.__anext__()
        agent.abort()
        remaining_events = [event async for event in stream]

        assert first_event.kind == "text_start"
        assert remaining_events[-1].kind == "run_aborted"
        assert remaining_events[-1].content == "<aborted>"
        assert [event.kind for event in remaining_events].count("run_aborted") == 1

    @pytest.mark.asyncio
    async def test_stop_hook_still_evaluates_completed_turn_state(self) -> None:
        """Stop hooks still see completed assistant/tool state from updates."""
        faux: FauxChatModel = FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="never reached"),
            ],
            chunk_scripts=[
                [
                    AIMessageChunk(
                        content="",
                        tool_calls=[{"id": "call_1", "name": "stub_now", "args": {}}],
                    )
                ]
            ],
        )
        captured: list[ShouldStopAfterTurnHookContextDAO] = []

        def stop_after_first(context: ShouldStopAfterTurnHookContextDAO) -> bool:
            captured.append(context)
            return True

        agent: SloAgent = SloAgent(
            llm=faux,
            tools=[stub_now],
            should_stop_after_turn_hook=stop_after_first,
        )

        events = [event async for event in agent.invoke(query="hello")]

        assert events[-1].kind == "run_completed"
        assert len(captured) == 1
        assert captured[0].message.tool_calls[0]["name"] == "stub_now"
        assert len(captured[0].tool_results) == 1
        assert captured[0].tool_results[0].name == "stub_now"
