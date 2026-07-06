"""Tests for tool-batch executors."""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.tools import tool

from src.agents.slo_agent.tool_execution import (
    ConcurrentToolExecutor,
    SequentialToolExecutor,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)
from src.agents.slo_agent.tool_execution.dao import ToolCallEnvelopeDAO


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
