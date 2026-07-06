"""Tests for ``FauxChatModel`` (sub-spec 01.b §5.2)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import tool

from src.agents.providers import (
    FauxChatModel,
    FauxScriptUnderrun,
)


@pytest.mark.asyncio
async def test_faux_returns_scripted_message() -> None:
    model = FauxChatModel(responses=[FauxChatModel.assistant_message(content="hi")])
    result = await model.ainvoke([HumanMessage(content="hello")])
    assert result.content == "hi"


@pytest.mark.asyncio
async def test_faux_supports_tool_calls() -> None:
    model = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="echo", args={"text": "x"})],
            ),
            FauxChatModel.assistant_message(content="done"),
        ]
    )
    first = await model.ainvoke([HumanMessage(content="run echo")])
    assert first.tool_calls[0]["name"] == "echo"
    assert first.tool_calls[0]["args"] == {"text": "x"}

    second = await model.ainvoke([HumanMessage(content="continue")])
    assert second.content == "done"


@pytest.mark.asyncio
async def test_faux_underrun_raises() -> None:
    model = FauxChatModel(responses=[FauxChatModel.assistant_message(content="only one")])
    await model.ainvoke([HumanMessage(content="first")])
    with pytest.raises(FauxScriptUnderrun):
        await model.ainvoke([HumanMessage(content="second")])


def test_bind_tools_captures_list() -> None:
    @tool
    def example_tool(text: str) -> str:
        """Example."""
        return text

    base = FauxChatModel(responses=[FauxChatModel.assistant_message(content="x")])
    bound = base.bind_tools(tools=[example_tool])
    assert bound.bound_tools == [example_tool]
    # base should be untouched (clone semantics)
    assert base.bound_tools == []


@pytest.mark.asyncio
async def test_astream_yields_default_single_chunk() -> None:
    """Without chunk scripts, Faux preserves the legacy one-chunk stream shape."""
    model = FauxChatModel(
        responses=[FauxChatModel.assistant_message(content="streamed")],
    )
    chunks: list[str] = []
    async for chunk in model.astream([HumanMessage(content="x")]):
        chunks.append(chunk.content)
    assert "".join(chunks) == "streamed"


@pytest.mark.asyncio
async def test_astream_yields_scripted_multiple_chunks_in_order() -> None:
    """Explicit chunk scripts stream multiple deltas for one completed response."""
    model = FauxChatModel(
        responses=[FauxChatModel.assistant_message(content="completed")],
        chunk_scripts=[
            [
                AIMessageChunk(content="part 1 "),
                AIMessageChunk(content="part 2"),
            ]
        ],
    )

    chunks: list[str] = []
    async for chunk in model.astream([HumanMessage(content="x")]):
        chunks.append(chunk.content)

    assert chunks == ["part 1 ", "part 2"]


@pytest.mark.asyncio
async def test_bind_tools_preserves_chunk_scripts_on_clone() -> None:
    """Binding tools keeps the source model's chunk scripting intact."""

    @tool
    def example_tool(text: str) -> str:
        """Example."""
        return text

    base = FauxChatModel(
        responses=[FauxChatModel.assistant_message(content="completed")],
        chunk_scripts=[[AIMessageChunk(content="part 1"), AIMessageChunk(content=" part 2")]],
    )

    bound = base.bind_tools(tools=[example_tool])
    chunks: list[str] = []
    async for chunk in bound.astream([HumanMessage(content="x")]):
        chunks.append(chunk.content)

    assert bound.bound_tools == [example_tool]
    assert chunks == ["part 1", " part 2"]


def test_fake_tool_call_shape() -> None:
    call = FauxChatModel.tool_call_dict(name="x", args={"a": 1})
    assert call["name"] == "x"
    assert call["args"] == {"a": 1}
    assert call["id"].startswith("call_")
    assert call["type"] == "tool_call"


def test_fake_tool_call_explicit_id() -> None:
    call = FauxChatModel.tool_call_dict(name="x", args={}, call_id="custom-id")
    assert call["id"] == "custom-id"
