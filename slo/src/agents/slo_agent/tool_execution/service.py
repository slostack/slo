"""Tool batch execution planner — canonical location (renamed from planner.py)."""

from __future__ import annotations

from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
)

__all__ = ["plan_tool_batch"]


_READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset({"read", "find", "grep", "ls", "read_pdf", "now"})


def _classify_tool_name(*, tool_name: str) -> ToolConcurrencyClass:
    """Return the scheduler class for one tool name.

    Args:
        tool_name (str): The registered tool name emitted by the model.

    Returns:
        ToolConcurrencyClass: The scheduler safety class.
    """
    if tool_name in _READ_ONLY_TOOL_NAMES:
        return ToolConcurrencyClass.READ_ONLY
    return ToolConcurrencyClass.MUTATING


def plan_tool_batch(*, calls: list[dict]) -> ToolExecutionPlanDAO:
    """Build a batch-level execution plan from raw tool calls.

    Args:
        calls (list[dict]): Assistant-emitted tool call dicts.

    Returns:
        ToolExecutionPlanDAO: Planned execution for the whole batch.
    """
    envelopes: list[ToolCallEnvelopeDAO] = []
    for source_index, call in enumerate(calls):
        envelopes.append(
            ToolCallEnvelopeDAO(
                source_index=source_index,
                call=call,
                concurrency_class=_classify_tool_name(tool_name=str(call["name"])),
            )
        )
    run_concurrently: bool = all(
        envelope.concurrency_class is ToolConcurrencyClass.READ_ONLY for envelope in envelopes
    )
    return ToolExecutionPlanDAO(run_concurrently=run_concurrently, calls=envelopes)
