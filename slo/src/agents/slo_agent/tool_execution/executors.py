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
    ToolInvocationDAO,
)
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl, ToolYieldPolicy

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
    async def execute(
        self,
        *,
        plan: ToolExecutionPlanDAO,
        control: Optional[ToolExecutionControl] = None,
        policy: Optional[ToolYieldPolicy] = None,
    ) -> list[ToolMessage]:
        """Execute one planned tool batch.

        Args:
            plan (ToolExecutionPlanDAO): Planned execution for one
                assistant-emitted batch.
            control: Optional run control owning phase/checkpoint eligibility.
            policy: Trusted cancellation policy; default is defer. Invocation and
                port ownership must join before terminal results are returned.

        Returns:
            list[ToolMessage]: Tool results in source order.
        """
        raise NotImplementedError

    async def _invoke_one(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
        control: Optional[ToolExecutionControl] = None,
        policy: Optional[ToolYieldPolicy] = None,
    ) -> tuple[int, ToolMessage]:
        """Execute one tool call safely and return its source index plus message.

        Args:
            envelope (ToolCallEnvelopeDAO): One source-ordered tool call.

        Returns:
            tuple[int, ToolMessage]: The source-order index and the
                resulting ``ToolMessage``.
        """
        prepared = await self._preflight(envelope=envelope, control=control)
        if isinstance(prepared, ToolMessage):
            return envelope.source_index, prepared
        tool, tool_input = prepared
        if control is not None and not control.before_dispatch(tool_call_id=str(envelope.call["id"])):
            return envelope.source_index, self._not_started(envelope=envelope)
        task = asyncio.create_task(
            coro=self._invoke_message(envelope=envelope, tool=tool, tool_input=tool_input)
        )
        return await self._join_invocation(
            envelope=envelope, tool=tool, task=task, control=control, policy=policy
        )

    async def _join_invocation(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
        tool: BaseTool,
        task: asyncio.Task[ToolMessage],
        control: Optional[ToolExecutionControl],
        policy: Optional[ToolYieldPolicy] = None,
        concurrent: bool = False,
    ) -> tuple[int, ToolMessage]:
        """Own an already registered task and all urgency/port joins through shutdown."""
        tool_call_id = str(envelope.call["id"])
        urgent: Optional[asyncio.Task[None]] = None
        try:
            if control is not None:
                urgent = asyncio.create_task(coro=control.wait_for_yield())
                await asyncio.wait(fs={task, urgent}, return_when=asyncio.FIRST_COMPLETED)
                if not task.done() and control.yield_is_requested():
                    if policy is not None and policy.mode_for(tool=tool) == "cancel_confirmed":
                        outcome = await policy.cancel_and_join(
                            invocation=ToolInvocationDAO(tool=tool, tool_call_id=tool_call_id, task=task),
                            control=control,
                        )
                        assert outcome.result is not None
                        return envelope.source_index, outcome.result
                    await control.defer(
                        tool_call_id=tool_call_id,
                        reason="concurrent_batch" if concurrent else "noninterruptible_tool",
                    )
            return envelope.source_index, await asyncio.shield(task)
        finally:
            if urgent is not None and not urgent.done():
                urgent.cancel()
            joined = asyncio.gather(task, *([urgent] if urgent is not None else []), return_exceptions=True)
            while not joined.done():
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError:
                    continue
            joined.result()

    async def _preflight(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
        control: Optional[ToolExecutionControl],
    ) -> ToolMessage | tuple[BaseTool, dict[str, Any]]:
        """Join decision-bearing interception without starting actual tool work."""
        tool_name = str(envelope.call["name"])
        call_id = str(envelope.call["id"])
        if control is not None and not control.before_dispatch(tool_call_id=call_id):
            return self._not_started(envelope=envelope)
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            return ToolMessage(
                tool_call_id=call_id,
                name=tool_name,
                content=f"Error: tool '{tool_name}' not found.",
                status="error",
            )
        tool_input = dict(envelope.call.get("args") or {})
        decision = await self._run_before_tool_call(
            tool_name=tool_name, tool_call_id=call_id, tool_input=tool_input
        )
        if control is not None and not control.before_dispatch(tool_call_id=call_id):
            return self._not_started(envelope=envelope)
        if decision.block:
            return await self._build_terminal_message(
                tool_call_id=call_id,
                tool_name=tool_name,
                content=decision.reason or "Error: blocked by plugin.",
                is_error=True,
            )
        return tool, dict(decision.mutated_input) if decision.mutated_input is not None else tool_input

    @staticmethod
    def _not_started(*, envelope: ToolCallEnvelopeDAO) -> ToolMessage:
        """Pair denied work without running any interceptor or inventing an effect."""
        return ToolMessage(
            tool_call_id=str(envelope.call["id"]),
            name=str(envelope.call["name"]),
            content="not_started: cooperative yield before dispatch",
            status="error",
        )

    async def _invoke_message(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
        tool: BaseTool,
        tool_input: dict[str, Any],
    ) -> ToolMessage:
        """Own actual invocation and awaited result plugins in one exact message task."""
        tool_name = str(envelope.call["name"])
        tool_call_id = str(envelope.call["id"])
        invocation_tool, invocation_config = self._prepare_output_update_transport(
            tool=tool,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        try:
            result: Any = await invocation_tool.ainvoke(tool_input, config=invocation_config)
        except Exception as exc:  # noqa: BLE001
            log_error(msg=f"ToolExecutor: {tool_name} raised", e=exc, stack_trace=False)
            return await self._build_terminal_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=f"Error: {exc}",
                is_error=True,
            )

        if isinstance(result, ToolResultDAO):
            return await self._build_terminal_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                content=self._coerce_tool_content(result=result.content),
                is_error=False,
                image_reference=result.image_reference,
            )

        return await self._build_terminal_message(
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
                final_error = is_error or patch.is_error
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

    async def execute(
        self,
        *,
        plan: ToolExecutionPlanDAO,
        control: Optional[ToolExecutionControl] = None,
        policy: Optional[ToolYieldPolicy] = None,
    ) -> list[ToolMessage]:
        """Execute the planned batch sequentially.

        Args:
            plan (ToolExecutionPlanDAO): Planned tool batch.
            control: Run authority; checkpoints deny unstarted calls on newer urgency.
            policy: Trusted sequential cancellation capability. Default defer retains
                actual invocation and port joins before results or failure escape.

        Returns:
            list[ToolMessage]: Tool results in source order.
        """
        tool_messages: list[ToolMessage] = []
        for envelope in plan.calls:
            _, tool_message = await self._invoke_one(envelope=envelope, control=control, policy=policy)
            tool_messages.append(tool_message)
        return tool_messages


class ConcurrentToolExecutor(ToolExecutor):
    """Execute an all-read-only batch concurrently and reorder results."""

    async def execute(
        self,
        *,
        plan: ToolExecutionPlanDAO,
        control: Optional[ToolExecutionControl] = None,
        policy: Optional[ToolYieldPolicy] = None,
    ) -> list[ToolMessage]:
        """Execute the planned batch concurrently.

        Args:
            plan (ToolExecutionPlanDAO): Planned all-read-only tool batch.
            control: Run-scoped dispatch authority; newer urgency denies unstarted
                calls but never cancels an already registered concurrent batch.
            policy: Retained sequential cancellation capability; concurrent work
                always defers and joins all siblings before returning or raising.

        Returns:
            list[ToolMessage]: Tool results in source order.

        Raises:
            ValueError: If ``plan`` is not safe for concurrent execution.
        """
        self._require_concurrent_plan(plan=plan)
        prepared = await self._preflight_batch(plan=plan, control=control)
        return await self._register_and_join_batch(plan=plan, prepared=prepared, control=control)

    @staticmethod
    def _require_concurrent_plan(*, plan: ToolExecutionPlanDAO) -> None:
        """Reject unsafe batches before asynchronous preflight or any effect."""
        if not plan.run_concurrently:
            raise ValueError("ConcurrentToolExecutor requires plan.run_concurrently=True")
        if any(call.concurrency_class is not ToolConcurrencyClass.READ_ONLY for call in plan.calls):
            raise ValueError("ConcurrentToolExecutor requires all calls to be READ_ONLY")

    async def _preflight_batch(
        self, *, plan: ToolExecutionPlanDAO, control: Optional[ToolExecutionControl]
    ) -> list[ToolMessage | tuple[BaseTool, dict[str, Any]]]:
        """Join every interceptor before validating results or registering work."""
        preflight = asyncio.gather(
            *[self._preflight(envelope=envelope, control=control) for envelope in plan.calls],
            return_exceptions=True,
        )
        await self._join_batch(joined=preflight)
        prepared: list[ToolMessage | tuple[BaseTool, dict[str, Any]]] = []
        for result in preflight.result():
            if isinstance(result, BaseException):
                raise result
            prepared.append(result)
        return prepared

    async def _register_and_join_batch(
        self,
        *,
        plan: ToolExecutionPlanDAO,
        prepared: list[ToolMessage | tuple[BaseTool, dict[str, Any]]],
        control: Optional[ToolExecutionControl],
    ) -> list[ToolMessage]:
        """Register the eligible whole batch without awaits, then join source-ordered truth."""
        tasks, completed_results = self._register_batch(plan=plan, prepared=prepared, control=control)
        joined = asyncio.gather(*tasks, return_exceptions=True)
        await self._join_batch(joined=joined)
        return self._source_ordered_results(joined=joined.result(), completed_results=completed_results)

    def _register_batch(
        self,
        *,
        plan: ToolExecutionPlanDAO,
        prepared: list[ToolMessage | tuple[BaseTool, dict[str, Any]]],
        control: Optional[ToolExecutionControl],
    ) -> tuple[list[asyncio.Task[tuple[int, ToolMessage]]], list[tuple[int, ToolMessage]]]:
        """Synchronously register all eligible invocations before yielding to the owner loop."""
        tasks: list[asyncio.Task[tuple[int, ToolMessage]]] = []
        completed_results: list[tuple[int, ToolMessage]] = []
        # No await from this final eligibility check through ALL task registrations.
        for envelope, result in zip(plan.calls, prepared):
            if control is not None and not control.before_dispatch(tool_call_id=str(envelope.call["id"])):
                completed_results.append((envelope.source_index, self._not_started(envelope=envelope)))
                continue
            if isinstance(result, ToolMessage):
                completed_results.append((envelope.source_index, result))
                continue
            assert not isinstance(result, BaseException)
            tool, tool_input = result
            tasks.append(
                self._register_invocation(
                    envelope=envelope, tool=tool, tool_input=tool_input, control=control
                )
            )
        return tasks, completed_results

    def _register_invocation(
        self,
        *,
        envelope: ToolCallEnvelopeDAO,
        tool: BaseTool,
        tool_input: dict[str, Any],
        control: Optional[ToolExecutionControl],
    ) -> asyncio.Task[tuple[int, ToolMessage]]:
        """Retain the exact message task inside its source-indexed join owner, without an await gap."""
        invocation: asyncio.Task[ToolMessage] = asyncio.create_task(
            coro=self._invoke_message(envelope=envelope, tool=tool, tool_input=tool_input)
        )
        return asyncio.create_task(
            coro=self._join_invocation(
                envelope=envelope, tool=tool, task=invocation, control=control, concurrent=True
            )
        )

    @staticmethod
    def _source_ordered_results(
        *,
        joined: list[tuple[int, ToolMessage] | BaseException],
        completed_results: list[tuple[int, ToolMessage]],
    ) -> list[ToolMessage]:
        """Propagate joined failure or return exact completed truth in original call order."""
        for completed in joined:
            if isinstance(completed, BaseException):
                raise completed
            completed_results.append(completed)
        completed_results.sort(key=lambda item: item[0])
        return [tool_message for _, tool_message in completed_results]

    @staticmethod
    async def _join_batch(*, joined: asyncio.Future[Any]) -> None:
        """Retain all sibling/preflight ownership on errors and repeated cancellation."""
        try:
            await asyncio.shield(joined)
        finally:
            while not joined.done():
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError:
                    continue
