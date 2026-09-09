"""Sequential and concurrent executors for planned tool batches."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Optional

from langchain_core.runnables import RunnableConfig

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from config.logger import log_error
from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO, BeforeToolCallDecisionDAO
from src.agents.slo_agent.tool_execution.dao import (
    ToolCallEnvelopeDAO,
    ToolConcurrencyClass,
    ToolExecutionPlanDAO,
    ToolResultDAO,
)
from src.agents.tools.tool_output import ToolOutputUpdateDAO

if TYPE_CHECKING:
    from src.agents.slo_agent.plugins.dispatcher import PluginToolInterceptorProtocol

__all__ = [
    "ConcurrentToolExecutor",
    "SequentialToolExecutor",
    "ToolExecutor",
]


class ToolExecutor(ABC):
    """Abstract executor for one planned tool batch."""

    def __init__(
        self,
        *,
        tools_by_name: dict[str, BaseTool],
        output_update_sink: Optional[Callable[..., Awaitable[None]]] = None,
        plugin_dispatcher: "PluginToolInterceptorProtocol | None" = None,
    ) -> None:
        """Store the registered tools keyed by tool name.

        Args:
            tools_by_name (dict[str, BaseTool]): Registered tools keyed by
                their LangChain-visible names.
            output_update_sink (Optional[Callable[..., Awaitable[None]]]):
                Core graph-to-agent partial-output queue sink.
        """
        self._tools_by_name: dict[str, BaseTool] = tools_by_name
        self._output_update_sink: Optional[Callable[..., Awaitable[None]]] = output_update_sink
        self._plugin_dispatcher: "PluginToolInterceptorProtocol | None" = plugin_dispatcher

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

        before_decision = await self._run_before_tool_call(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
        )
        if before_decision.block:
            return envelope.source_index, await self._build_terminal_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=before_decision.reason or "Error: blocked by plugin.",
                is_error=True,
            )
        if before_decision.mutated_input is not None:
            tool_input = dict(before_decision.mutated_input)

        invocation_tool, invocation_config = self._prepare_output_update_transport(
            tool=tool,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        try:
            result: Any = await invocation_tool.ainvoke(tool_input, config=invocation_config)
        except Exception as exc:  # noqa: BLE001
            log_error(msg=f"ToolExecutor: {tool_name} raised", e=exc, stack_trace=False)
            return envelope.source_index, await self._build_terminal_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=f"Error: {exc}",
                is_error=True,
            )

        if isinstance(result, ToolResultDAO):
            return envelope.source_index, await self._build_terminal_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=self._coerce_tool_content(result=result.content),
                is_error=False,
                image_reference=result.image_reference,
            )

        return envelope.source_index, await self._build_terminal_message(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=self._coerce_tool_content(result=result),
            is_error=False,
        )

    async def _run_before_tool_call(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict[str, Any],
    ) -> "BeforeToolCallDecisionDAO":
        """Run the configured typed pre-tool interception chain when present.

        Args:
            tool_name (str): Tool selected for invocation.
            tool_call_id (str): Stable tool-call identity.
            tool_input (dict[str, Any]): Current model-supplied arguments.

        Returns:
            BeforeToolCallDecisionDAO: Block or mutation decision; a no-op
            decision preserves legacy behavior when no dispatcher is configured.
        """
        if self._plugin_dispatcher is None:
            return BeforeToolCallDecisionDAO()
        return await self._plugin_dispatcher.run_before_tool_call(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
        )

    async def _build_terminal_message(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        content: str | list[str | dict[Any, Any]],
        is_error: bool,
        image_reference: str | None = None,
    ) -> ToolMessage:
        """Patch terminal content through plugins and create the sole ToolMessage.

        Args:
            tool_call_id (str): Stable tool-call identity.
            tool_name (str): Tool that settled or was blocked.
            content (str | list[str | dict[Any, Any]]): Terminal model-visible content.
            is_error (bool): Whether core produced an error result.
            image_reference (str | None): Optional image attachment reference.

        Returns:
            ToolMessage: The one terminal message for this invocation.
        """
        terminal_content: str | list[str | dict[Any, Any]] = content
        final_error: bool = is_error
        if self._plugin_dispatcher is not None:
            patch: AfterToolResultPatchDAO = await self._plugin_dispatcher.run_after_tool_result(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                content=content if isinstance(content, str) else str(content),
                is_error=is_error,
            )
            if patch.content is not None:
                terminal_content = patch.content
            if patch.is_error is not None:
                final_error = patch.is_error
        return ToolMessage(
            tool_call_id=tool_call_id,
            name=tool_name,
            content=terminal_content,
            status="error" if final_error else "success",
            additional_kwargs={"image_reference": image_reference} if image_reference is not None else {},
        )

    def _prepare_output_update_transport(
        self,
        *,
        tool: BaseTool,
        tool_call_id: str,
        tool_name: str,
    ) -> tuple[BaseTool, RunnableConfig | None]:
        """Prepare immutable callback transport for one tool invocation.

        WHAT: Clones legacy callback-aware tools and otherwise uses LangChain
        invocation config, never mutating a shared registered tool.
        WHO: ``_invoke_one`` calls this at the core tool-execution chokepoint.
        WHEN: A graph supplies an output-update sink for a running tool call.

        Args:
            tool (BaseTool): Registered shared tool instance.
            tool_call_id (str): Stable identity for this invocation.
            tool_name (str): Visible name for this invocation.

        Returns:
            tuple[BaseTool, RunnableConfig | None]: Invocation-local tool and
                optional LangChain config containing the output callback.
        """
        if self._output_update_sink is None:
            return tool, None

        sink: Callable[..., Awaitable[None]] = self._output_update_sink

        async def on_update(*, snapshot: ToolOutputUpdateDAO) -> None:
            """Stamp and forward one partial snapshot to the graph bridge.

            Args:
                snapshot (ToolOutputUpdateDAO): Tool-produced display snapshot.
            """
            await sink(
                snapshot=snapshot.model_copy(update={"tool_call_id": tool_call_id, "tool_name": tool_name})
            )

        if "update_callback" in type(tool).model_fields:
            return tool.model_copy(update={"update_callback": on_update}), None
        return tool, RunnableConfig(
            configurable={"slo_tool_output_update_callback": on_update},
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
            asyncio.create_task(self._invoke_one(envelope=envelope)) for envelope in plan.calls
        ]
        completed_results: list[tuple[int, ToolMessage]] = await asyncio.gather(*tasks)
        completed_results.sort(key=lambda item: item[0])
        return [tool_message for _, tool_message in completed_results]
