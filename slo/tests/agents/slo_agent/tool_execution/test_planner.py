"""Tests for tool-batch planning."""
from __future__ import annotations

from src.agents.slo_agent.tool_execution import ToolConcurrencyClass, plan_tool_batch


def test_plan_tool_batch_marks_all_read_only_calls_concurrent() -> None:
    """All read-only calls should produce a concurrent plan."""
    plan = plan_tool_batch(calls=[
        {"id": "1", "name": "read", "args": {"path": "a.py"}},
        {"id": "2", "name": "grep", "args": {"pattern": "x", "path": "."}},
        {"id": "3", "name": "read_pdf", "args": {"path": "a.pdf"}},
    ])

    assert plan.run_concurrently is True
    assert [call.concurrency_class for call in plan.calls] == [
        ToolConcurrencyClass.READ_ONLY,
        ToolConcurrencyClass.READ_ONLY,
        ToolConcurrencyClass.READ_ONLY,
    ]


def test_plan_tool_batch_marks_mixed_read_write_batch_sequential() -> None:
    """Any mutating call should force whole-batch sequential execution."""
    plan = plan_tool_batch(calls=[
        {"id": "1", "name": "read", "args": {"path": "a.py"}},
        {"id": "2", "name": "write", "args": {"path": "b.py", "content": "x"}},
        {"id": "3", "name": "read", "args": {"path": "b.py"}},
    ])

    assert plan.run_concurrently is False
    assert [call.concurrency_class for call in plan.calls] == [
        ToolConcurrencyClass.READ_ONLY,
        ToolConcurrencyClass.MUTATING,
        ToolConcurrencyClass.READ_ONLY,
    ]


def test_plan_tool_batch_forces_sequential_when_bash_is_present() -> None:
    """Bash is always classified as mutating."""
    plan = plan_tool_batch(calls=[
        {"id": "1", "name": "bash", "args": {"command": "pwd"}},
    ])

    assert plan.run_concurrently is False
    assert plan.calls[0].concurrency_class is ToolConcurrencyClass.MUTATING


def test_plan_tool_batch_treats_unknown_tool_as_mutating() -> None:
    """Unknown tools should default to the conservative mutating class."""
    plan = plan_tool_batch(calls=[
        {"id": "1", "name": "future_tool", "args": {}},
    ])

    assert plan.run_concurrently is False
    assert plan.calls[0].concurrency_class is ToolConcurrencyClass.MUTATING
