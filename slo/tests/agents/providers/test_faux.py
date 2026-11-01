"""Tests for ``FauxChatModel`` (sub-spec 01.b §5.2)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
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
    assert isinstance(first, AIMessage)
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
        assert isinstance(chunk.content, str)
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
        assert isinstance(chunk.content, str)
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
        assert isinstance(chunk.content, str)
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


@pytest.mark.parametrize("tool_choice", [None, "auto", "required"])
def test_binding_accepts_upstream_forms_without_consuming_scripts(tool_choice: str | None) -> None:
    """Schema, class, callable and BaseTool inputs retain independent clone queues."""
    from pydantic import BaseModel

    class InputSchema(BaseModel):
        """Offline callable input."""

        text: str

    def echo(text: str) -> str:
        """Return the supplied text."""
        return text

    decorated = tool(echo)
    schema: dict[str, object] = {"name": "echo", "parameters": {"type": "object"}}
    original = FauxChatModel(
        responses=[AIMessage(content="done")],
        chunk_scripts=[[AIMessageChunk(content="do"), AIMessageChunk(content="ne")]],
    )
    clone = original.bind_tools(tools=[schema, InputSchema, echo, decorated], tool_choice=tool_choice)
    assert clone.bound_tools == [schema, InputSchema, echo, decorated]
    assert original.bound_tools == []
    assert clone.queue is not original.queue
    assert clone.chunk_queue is not original.chunk_queue
    assert clone.chunk_queue[0] is not original.chunk_queue[0]
    assert [chunk.content for chunk in clone.stream("go")] == ["do", "ne"]
    with pytest.raises(FauxScriptUnderrun):
        list(clone.stream("again"))
    assert original.invoke("go").content == "done"
    other = FauxChatModel(responses=[])
    assert other.queue is not original.queue
    assert other.chunk_queue is not original.chunk_queue
    assert other.bound_tools is not original.bound_tools
