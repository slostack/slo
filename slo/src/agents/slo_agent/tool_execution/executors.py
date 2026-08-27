"""Sequential and concurrent executors for planned tool batches."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from config.logger import log_error
from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
    ToolResultDAO,
)


__all__ = [
    "ConcurrentToolExecutor",
    "SequentialToolExecutor",
    "ToolExecutor",
]


class ToolExecutor(ABC):
    """Abstract executor for one planned tool batch."""

    def __init__(self, *, tools_by_name: dict[str, BaseTool]) -> None:
        """Store the registered tools keyed by tool name.

        Args:
            tools_by_name (dict[str, BaseTool]): Registered tools keyed by
                their LangChain-visible names.
        """
        self._tools_by_name = tools_by_name

    @abstractmethod
    async def execute(self, *, plan: ToolExecutionPlanDAO) -> list[ToolMessage]:
        """Execute one planned tool batch.

        Args:
            plan (ToolExecutionPlanDAO): Planned execution for one
                assistant-emitted batch.

        Returns:
            list[ToolMessage]: Tool results in source order.
        """
        raise NotImplementedError

    async def _invoke_one(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
    ) -> tuple[int, ToolMessage]:
        """Execute one tool call safely and return its source index plus message.

        Args:
            envelope (ToolCallEnvelopeDAO): One source-ordered tool call.

        Returns:
            tuple[int, ToolMessage]: The source-order index and the
                resulting ``ToolMessage``.
        """
        call: dict[str, Any] = dict(envelope.call)
        tool_name: str = str(call["name"])
        tool_call_id: str = str(call["id"])
        tool_input: dict[str, Any] = dict(call.get("args") or {})

        tool: BaseTool | None = self._tools_by_name.get(tool_name)
        if tool is None:
            return (
                envelope.source_index,
                ToolMessage(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    content=f"Error: tool '{tool_name}' not found.",
                    status="error",
                ),
            )

        try:
            result: Any = await tool.ainvoke(tool_input)
        except Exception as exc:  # noqa: BLE001
            log_error(msg=f"ToolExecutor: {tool_name} raised", e=exc, stack_trace=False)
            return (
                envelope.source_index,
                ToolMessage(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    content=f"Error: {exc}",
                    status="error",
                ),
            )

        if isinstance(result, ToolResultDAO):
            return (
                envelope.source_index,
                ToolMessage(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    content=self._coerce_tool_content(result=result.content),
                    additional_kwargs=(
                        {"image_reference": result.image_reference}
                        if result.image_reference is not None
                        else {}
                    ),
                ),
            )

        return (
            envelope.source_index,
            ToolMessage(
                tool_call_id=tool_call_id,
                name=tool_name,
                content=self._coerce_tool_content(result=result),
            ),
        )

    def _coerce_tool_content(self, *, result: Any) -> str | list[str | dict[Any, Any]]:
        """Normalize one tool return value into ``ToolMessage`` content.

        Args:
            result (Any): Raw tool return value.

        Returns:
            str | list[str | dict[Any, Any]]: Content accepted by LangChain
                ``ToolMessage``.
        """
        if isinstance(result, (str, list)):
            return result
        return str(result)


class SequentialToolExecutor(ToolExecutor):
    """Execute every call in source order."""

    async def execute(self, *, plan: ToolExecutionPlanDAO) -> list[ToolMessage]:
        """Execute the planned batch sequentially.

        Args:
            plan (ToolExecutionPlanDAO): Planned tool batch.

        Returns:
            list[ToolMessage]: Tool results in source order.
        """
        tool_messages: list[ToolMessage] = []
        for envelope in plan.calls:
            _, tool_message = await self._invoke_one(envelope=envelope)
            tool_messages.append(tool_message)
        return tool_messages


class ConcurrentToolExecutor(ToolExecutor):
    """Execute an all-read-only batch concurrently and reorder results."""

    async def execute(self, *, plan: ToolExecutionPlanDAO) -> list[ToolMessage]:
        """Execute the planned batch concurrently.

        Args:
            plan (ToolExecutionPlanDAO): Planned all-read-only tool batch.

        Returns:
            list[ToolMessage]: Tool results in source order.

        Raises:
            ValueError: If ``plan`` is not safe for concurrent execution.
        """
        if not plan.run_concurrently:
            raise ValueError("ConcurrentToolExecutor requires plan.run_concurrently=True")

        for envelope in plan.calls:
            if envelope.concurrency_class is not ToolConcurrencyClass.READ_ONLY:
                raise ValueError(
                    "ConcurrentToolExecutor requires all calls to be READ_ONLY",
                )

        tasks: list[asyncio.Task[tuple[int, ToolMessage]]] = [
            asyncio.create_task(self._invoke_one(envelope=envelope))
            for envelope in plan.calls
        ]
        completed_results: list[tuple[int, ToolMessage]] = await asyncio.gather(*tasks)
        completed_results.sort(key=lambda item: item[0])
        return [tool_message for _, tool_message in completed_results]
