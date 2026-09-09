"""Tests for executor publication of core tool-output snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)
from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor
from src.agents.tools.bash import bash_tool
from src.agents.tools.tool_output import ToolOutputUpdateDAO


class _StreamingTool(BaseTool):
    """Minimal callback-aware tool used to verify executor transport behavior."""

    name: str = "stream"
    description: str = "Test-only streaming tool."
    update_callback: Callable[..., Awaitable[None]] | None = None
    delay_sink: bool = False

    def _run(self, **_: Any) -> str:
        """Reject the sync test-tool path.

        Returns:
            str: Never returns.

        Raises:
            RuntimeError: The executor must use the async path.
        """
        raise RuntimeError("test tool is async only")

    async def _arun(self, **_: Any) -> str:
        """Publish one snapshot then return terminal output.

        Returns:
            str: Terminal tool content.
        """
        if self.update_callback is not None:
            await self.update_callback(
                snapshot=ToolOutputUpdateDAO(
                    tool_call_id="wrong",
                    tool_name="wrong",
                    content_snapshot="working",
                )
            )
        return "done"


def _build_plan() -> ToolExecutionPlanDAO:
    """Build a single-call ordered execution plan.

    Returns:
        ToolExecutionPlanDAO: One streaming-tool call.
    """
    return ToolExecutionPlanDAO(
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"name": "stream", "id": "call-1", "args": {}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            )
        ],
        run_concurrently=False,
    )


@pytest.mark.asyncio
async def test_executor_publishes_snapshot_with_envelope_identity() -> None:
    """One callback-aware snapshot is stamped and forwarded to the core sink."""
    tool: _StreamingTool = _StreamingTool()
    updates: list[ToolOutputUpdateDAO] = []

    async def sink(*, snapshot: ToolOutputUpdateDAO) -> None:
        """Collect one executor-published core snapshot.

        Args:
            snapshot (ToolOutputUpdateDAO): Snapshot emitted by the executor.
        """
        updates.append(snapshot)

    executor: SequentialToolExecutor = SequentialToolExecutor(
        tools_by_name={"stream": tool},
        output_update_sink=sink,
    )

    messages = await executor.execute(plan=_build_plan())

    assert messages[0].content == "done"
    assert updates == [
        ToolOutputUpdateDAO(
            tool_call_id="call-1",
            tool_name="stream",
            content_snapshot="working",
        )
    ]


@pytest.mark.asyncio
async def test_executor_uses_legacy_tool_path_without_sink() -> None:
    """No update callback is attached when the caller has no core output sink."""
    tool: _StreamingTool = _StreamingTool()
    executor: SequentialToolExecutor = SequentialToolExecutor(tools_by_name={"stream": tool})

    messages = await executor.execute(plan=_build_plan())

    assert tool.update_callback is None
    assert messages[0].content == "done"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_executor_delivers_real_bash_callbacks_through_runnable_config() -> None:
    """A real LangChain Bash bridge reads the per-invocation config callback."""
    updates: list[ToolOutputUpdateDAO] = []

    async def sink(*, snapshot: ToolOutputUpdateDAO) -> None:
        """Collect a snapshot from the real Bash bridge.

        Args:
            snapshot (ToolOutputUpdateDAO): Executor-stamped display snapshot.
        """
        updates.append(snapshot)

    executor: SequentialToolExecutor = SequentialToolExecutor(
        tools_by_name={"bash": bash_tool},
        output_update_sink=sink,
    )
    plan: ToolExecutionPlanDAO = ToolExecutionPlanDAO(
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={
                    "name": "bash",
                    "id": "bash-call-1",
                    "args": {"command": "echo first; sleep 0.12; echo second"},
                },
                concurrency_class=ToolConcurrencyClass.MUTATING,
            )
        ],
        run_concurrently=False,
    )

    messages = await executor.execute(plan=plan)

    assert len(messages) == 1
    assert "second" in str(messages[0].content)
    assert updates
    assert {snapshot.tool_call_id for snapshot in updates} == {"bash-call-1"}
    assert {snapshot.tool_name for snapshot in updates} == {"bash"}


@pytest.mark.asyncio
async def test_executor_waits_for_pending_update_delivery() -> None:
    """A terminal ToolMessage is held until an accepted update reaches the sink."""
    tool: _StreamingTool = _StreamingTool()
    delivered: asyncio.Event = asyncio.Event()

    async def sink(*, snapshot: ToolOutputUpdateDAO) -> None:
        """Delay delivery to prove executor settlement waits for it.

        Args:
            snapshot (ToolOutputUpdateDAO): Pending snapshot.
        """
        await asyncio.sleep(0.01)
        delivered.set()

    executor: SequentialToolExecutor = SequentialToolExecutor(
        tools_by_name={"stream": tool},
        output_update_sink=sink,
    )

    messages = await executor.execute(plan=_build_plan())

    assert delivered.is_set()
    assert messages[0].content == "done"
