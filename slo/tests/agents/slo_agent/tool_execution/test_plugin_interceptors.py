"""Decision-path tests for plugin interception at the executor chokepoint."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO, BeforeToolCallDecisionDAO
from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)
from src.agents.slo_agent.tool_execution.executors import SequentialToolExecutor


class _RecordingTool(BaseTool):
    """Small tool that records the exact input passed through the executor."""

    name: str = "record"
    description: str = "Test-only recording tool."
    received: dict[str, Any] | None = None

    def _run(self, **kwargs: Any) -> str:
        """Record the supplied arguments and produce terminal text.

        Args:
            **kwargs (Any): Model or plugin supplied tool arguments.

        Returns:
            str: Fixed terminal content.
        """
        self.received = dict(kwargs)
        return "core-result"


class _Dispatcher:
    """Typed executor collaborator with configurable pre/post decision behavior."""

    def __init__(self, *, before: BeforeToolCallDecisionDAO, patch: AfterToolResultPatchDAO) -> None:
        """Store the decisions returned at the two interceptor boundaries."""
        self.before: BeforeToolCallDecisionDAO = before
        self.patch: AfterToolResultPatchDAO = patch
        self.after_calls: int = 0

    async def run_before_tool_call(
        self, *, tool_name: str, tool_call_id: str, tool_input: dict[str, Any]
    ) -> BeforeToolCallDecisionDAO:
        """Return the configured pre-tool decision."""
        del tool_name, tool_call_id, tool_input
        return self.before

    async def run_after_tool_result(
        self, *, tool_name: str, tool_call_id: str, content: str, is_error: bool
    ) -> AfterToolResultPatchDAO:
        """Return the configured post-result patch."""
        del tool_name, tool_call_id, content, is_error
        self.after_calls += 1
        return self.patch


def _plan() -> ToolExecutionPlanDAO:
    """Build one mutating call plan for the test tool."""
    return ToolExecutionPlanDAO(
        calls=[
            ToolCallEnvelopeDAO(
                source_index=0,
                call={"name": "record", "id": "call-1", "args": {"value": "model"}},
                concurrency_class=ToolConcurrencyClass.MUTATING,
            )
        ],
        run_concurrently=False,
    )


@pytest.mark.asyncio
async def test_executor_blocks_before_tool_call_without_invoking_tool() -> None:
    """A plugin block returns one error ToolMessage and skips the core tool."""
    tool: _RecordingTool = _RecordingTool()
    dispatcher = _Dispatcher(
        before=BeforeToolCallDecisionDAO(block=True, reason="blocked"),
        patch=AfterToolResultPatchDAO(content="patched block"),
    )
    executor = SequentialToolExecutor(tools_by_name={"record": tool}, plugin_dispatcher=dispatcher)

    messages = await executor.execute(plan=_plan())

    assert tool.received is None
    assert messages[0].content == "patched block"
    assert messages[0].status == "error"


@pytest.mark.asyncio
async def test_executor_applies_mutation_then_terminal_patch() -> None:
    """A typed mutation reaches the tool and a patch changes its sole result."""
    tool: _RecordingTool = _RecordingTool()
    dispatcher = _Dispatcher(
        before=BeforeToolCallDecisionDAO(mutated_input={"value": "plugin"}),
        patch=AfterToolResultPatchDAO(content="plugin-result"),
    )
    executor = SequentialToolExecutor(tools_by_name={"record": tool}, plugin_dispatcher=dispatcher)

    messages = await executor.execute(plan=_plan())

    assert tool.received == {"value": "plugin"}
    assert messages[0].content == "plugin-result"
    assert messages[0].status == "success"
    assert dispatcher.after_calls == 1


@pytest.mark.asyncio
async def test_executor_allows_error_patch_to_clear_core_error() -> None:
    """Post-result patches use the DAO error field for a core invocation error."""
    tool: _RecordingTool = _RecordingTool()
    dispatcher = _Dispatcher(
        before=BeforeToolCallDecisionDAO(),
        patch=AfterToolResultPatchDAO(content="recovered", is_error=False),
    )
    tool._run = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
    executor = SequentialToolExecutor(tools_by_name={"record": tool}, plugin_dispatcher=dispatcher)

    messages = await executor.execute(plan=_plan())

    assert messages[0].content == "recovered"
    assert messages[0].status == "success"


@pytest.mark.asyncio
async def test_executor_without_dispatcher_preserves_legacy_terminal_result() -> None:
    """Absent dispatcher neither mutates input nor changes terminal result behavior."""
    tool: _RecordingTool = _RecordingTool()
    executor = SequentialToolExecutor(tools_by_name={"record": tool})

    messages = await executor.execute(plan=_plan())

    assert tool.received == {"value": "model"}
    assert messages[0].content == "core-result"
    assert messages[0].status == "success"
