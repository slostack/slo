"""Tests for tool-batch executors."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest
from langchain_core.tools import tool
from PIL import Image

from src.agents.slo_agent.tool_execution import (
    ConcurrentToolExecutor,
    SequentialToolExecutor,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)
from src.agents.slo_agent.tool_execution.dao import ToolCallEnvelopeDAO, ToolResultDAO
from src.agents.tools.read import read_tool


@tool
async def delayed_alpha() -> str:
    """Return after a longer delay."""
    await asyncio.sleep(delay=0.02)
    return "alpha"


@tool
async def delayed_beta() -> str:
    """Return after a shorter delay."""
    await asyncio.sleep(delay=0.001)
    return "beta"


@tool
async def delayed_record_a() -> str:
    """Return A after recording execution order."""
    await asyncio.sleep(delay=0)
    return "a"


@tool
async def delayed_record_b() -> str:
    """Return B after recording execution order."""
    await asyncio.sleep(delay=0)
    return "b"


@tool
async def broken_read() -> str:
    """Always raise for executor error tests."""
    raise RuntimeError("boom")


def _concurrent_plan() -> ToolExecutionPlanDAO:
    """Build a two-call read-only concurrent plan."""
    return ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "1", "name": "delayed_alpha", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            ),
            ToolCallEnvelopeDAO(
                source_index=1,
                call={"id": "2", "name": "delayed_beta", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            ),
        ],
    )


def _read_envelope(*, path: str, call_id: str = "tc_img") -> ToolCallEnvelopeDAO:
    """Build an envelope that calls the production read tool."""
    return ToolCallEnvelopeDAO(
        source_index=0,
        call={"id": call_id, "name": "read", "args": {"path": path}},
        concurrency_class=ToolConcurrencyClass.READ_ONLY,
    )


@pytest.mark.asyncio
async def test_sequential_executor_executes_calls_in_source_order() -> None:
    """Sequential executor should preserve source-order results."""
    executor = SequentialToolExecutor(
        tools_by_name={
            "delayed_record_a": delayed_record_a,
            "delayed_record_b": delayed_record_b,
        }
    )
    plan = ToolExecutionPlanDAO(
        run_concurrently=False,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "1", "name": "delayed_record_a", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            ),
            ToolCallEnvelopeDAO(
                source_index=1,
                call={"id": "2", "name": "delayed_record_b", "args": {}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            ),
        ],
    )

    result = await executor.execute(plan=plan)

    assert [message.name for message in result] == ["delayed_record_a", "delayed_record_b"]
    assert [message.content for message in result] == ["a", "b"]


@pytest.mark.asyncio
async def test_concurrent_executor_reorders_results_back_to_source_order() -> None:
    """Concurrent completion order should not change returned message order."""
    executor = ConcurrentToolExecutor(
        tools_by_name={
            "delayed_alpha": delayed_alpha,
            "delayed_beta": delayed_beta,
        }
    )

    result = await executor.execute(plan=_concurrent_plan())

    assert [message.name for message in result] == ["delayed_alpha", "delayed_beta"]
    assert [message.content for message in result] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_concurrent_executor_surfaces_tool_error_as_error_tool_message() -> None:
    """Raised tool errors should become error ToolMessages."""
    executor = ConcurrentToolExecutor(tools_by_name={"broken_read": broken_read})
    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "1", "name": "broken_read", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            ),
        ],
    )

    result = await executor.execute(plan=plan)

    assert result[0].status == "error"
    assert "boom" in str(result[0].content)


@pytest.mark.asyncio
async def test_concurrent_executor_rejects_non_concurrent_plan() -> None:
    """Concurrent executor should reject a sequential plan."""
    executor = ConcurrentToolExecutor(tools_by_name={"delayed_alpha": delayed_alpha})
    plan = ToolExecutionPlanDAO(
        run_concurrently=False,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "1", "name": "delayed_alpha", "args": {}},
                concurrency_class=ToolConcurrencyClass.READ_ONLY,
            ),
        ],
    )

    with pytest.raises(ValueError):
        await executor.execute(plan=plan)


@pytest.mark.asyncio
async def test_concurrent_executor_rejects_mutating_call() -> None:
    """Concurrent executor should reject a plan with a mutating call."""
    executor = ConcurrentToolExecutor(tools_by_name={"delayed_alpha": delayed_alpha})
    plan = ToolExecutionPlanDAO(
        run_concurrently=True,
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"id": "1", "name": "delayed_alpha", "args": {}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            ),
        ],
    )

    with pytest.raises(ValueError):
        await executor.execute(plan=plan)


@pytest.mark.asyncio
async def test_read_image_through_executor_sets_image_reference(tmp_path: Path) -> None:
    """The real executor separates image content from its durable reference."""
    target: Path = tmp_path / "large.png"
    Image.new("RGB", (3000, 2000), color="red").save(target, format="PNG")
    executor = SequentialToolExecutor(tools_by_name={"read": read_tool})

    _, message = await executor._invoke_one(envelope=_read_envelope(path=str(target)))

    assert isinstance(message.content, list)
    assert message.content[0]["type"] == "image"
    base64.b64decode(message.content[0]["source"]["data"])
    assert message.additional_kwargs["image_reference"].startswith("[image attached: large.png,")


@pytest.mark.asyncio
async def test_read_text_through_executor_has_no_image_reference(tmp_path: Path) -> None:
    """The executor preserves the existing text result path unchanged."""
    target: Path = tmp_path / "notes.txt"
    target.write_text("hello world")
    executor = SequentialToolExecutor(tools_by_name={"read": read_tool})

    _, message = await executor._invoke_one(envelope=_read_envelope(path=str(target)))

    assert isinstance(message.content, str)
    assert "hello world" in message.content
    assert message.additional_kwargs.get("image_reference") is None


@pytest.mark.asyncio
async def test_executor_splits_direct_tool_result_dao() -> None:
    """The executor preserves ToolResultDAO content and metadata separately."""

    @tool
    async def fake_image() -> ToolResultDAO:
        """Return structured content that exercises the executor split path."""
        return ToolResultDAO(
            content=[{"type": "image", "source": {"type": "base64", "data": "aGVsbG8="}}],
            image_reference="[image attached: x.png, 10x10, ref /x.png]",
        )

    executor = SequentialToolExecutor(tools_by_name={"fake_image": fake_image})
    envelope = ToolCallEnvelopeDAO(
        source_index=0,
        call={"id": "1", "name": "fake_image", "args": {}},
        concurrency_class=ToolConcurrencyClass.READ_ONLY,
    )

    _, message = await executor._invoke_one(envelope=envelope)

    assert message.content[0]["type"] == "image"
    assert message.additional_kwargs["image_reference"] == "[image attached: x.png, 10x10, ref /x.png]"
