"""One owned updates-only graph driver with public live-model callbacks.

Updates-only avoids LangGraph's unowned messages/custom queue waiter. The
callback supplies presentation chunks; root updates remain completed truth.
"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextvars import ContextVar
from typing import Any, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    message_chunk_to_message,
)
from langchain_core.outputs import ChatGenerationChunk, GenerationChunk
from langgraph.graph.state import CompiledStateGraph

from src.agents.slo_agent.graph.dao import SloAgentStateDAO

_completed_response_sink: ContextVar[Optional[Callable[[BaseMessage], None]]] = ContextVar(
    "completed_response_sink", default=None
)


class GraphEventQueue(asyncio.Queue[object]):
    """Backpressure count and serialized bytes; admit one oversize truth only when empty.

    A provider may produce an indivisible chunk larger than the byte budget. It
    must not be dropped or split into invented completion: allow that one item
    alone and block all following producers until the consumer takes it.
    """

    def __init__(self, *, maxsize: int = 256, max_bytes: int = 1024 * 1024) -> None:
        """Set attempt-local bounds without creating tasks."""
        super().__init__(maxsize=maxsize)
        self._max_bytes = max_bytes
        self._bytes = 0
        self._space = asyncio.Event()
        self._space.set()

    @staticmethod
    def _size(item: object) -> int:
        """Measure retained messages and updates using their full public JSON shape."""
        return len(
            json.dumps(
                item,
                default=lambda value: (
                    value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)
                ),
                ensure_ascii=False,
            ).encode("utf-8")
        )

    async def put(self, item: object) -> None:
        """Wait for both budgets, never holding a separate producer task."""
        size = self._size(item)
        while self.full() or (self.qsize() > 0 and self._bytes + size > self._max_bytes):
            self._space.clear()
            await self._space.wait()
        self.put_nowait(item)

    def put_nowait(self, item: object) -> None:
        """Account one registered item synchronously after admission."""
        size = self._size(item)
        if self.qsize() > 0 and self._bytes + size > self._max_bytes:
            raise asyncio.QueueFull()
        super().put_nowait(item)
        self._bytes += size

    def get_nowait(self) -> object:
        """Release capacity and wake every blocked producer on the same loop."""
        item = super().get_nowait()
        self._bytes -= self._size(item)
        self._space.set()
        return item


class GraphStreamCallbacks(AsyncCallbackHandler):
    """Publish agent-node chunks without enabling LangGraph messages mode."""

    def __init__(self, *, queue: asyncio.Queue[object]) -> None:
        """Borrow the invocation-owned queue; start no work."""
        self._queue = queue
        self.failure: Optional[BaseException] = None
        self.closing = False
        self._agent_runs: set[UUID] = set()
        self._model_runs: set[UUID] = set()
        self._agent_descendants: set[UUID] = set()

    async def on_chain_start(
        self,
        serialized: Optional[dict[str, Any]],
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Identify the actual agent node, not models invoked inside tools."""
        metadata = kwargs.get("metadata") or {}
        if kwargs.get("name") == "agent" and metadata.get("langgraph_node") == "agent":
            self._agent_runs.add(run_id)
            self._agent_descendants.add(run_id)
        elif parent_run_id in self._agent_descendants:
            self._agent_descendants.add(run_id)

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Admit the agent's nested bound/pool model lineage, excluding tool models."""
        if parent_run_id in self._agent_descendants:
            self._model_runs.add(run_id)
            self._agent_descendants.add(run_id)

    async def on_custom_event(
        self,
        name: str,
        data: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Wake the existing output queue without enabling LangGraph custom mode."""
        if name == "slo_tool_output_ready" and not self.closing:
            await self._queue.put(("updates", {}))

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Retain actual provider cleanup failure even if graph cancellation wins."""
        if run_id in self._model_runs and not isinstance(error, asyncio.CancelledError):
            self.failure = error

    async def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: Optional[GenerationChunk | ChatGenerationChunk] = None,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Retain the original structured live chunk, not reconstructed text."""
        if self.closing or run_id not in self._model_runs:
            return
        if isinstance(chunk, ChatGenerationChunk) and isinstance(chunk.message, AIMessageChunk):
            await self._queue.put(("messages", (chunk.message, {})))


# invoke -> one updates driver + public callbacks -> drain -> joined close.
class GraphEventStream:
    """Own attempt transport and retained provider completion through joined teardown."""

    @classmethod
    async def invoke_joined_provider(
        cls, *, llm: BaseChatModel, messages: list[BaseMessage], kwargs: dict[str, Any]
    ) -> BaseMessage:
        """Consume the retained provider and join cancellation before node termination.

        Args:
            llm: Existing bound provider or pool; never rebuilt or rebound here.
            messages: Validated context, already shaped for the provider lane.
            kwargs: Existing lane-specific request options, forwarded unchanged.

        Returns:
            BaseMessage: Actual assembled completion, including suppressed cancellation.

        Raises:
            ValueError: The provider stream ended without a message.
            BaseException: Provider failure or cancellation after cleanup joins.
        """
        if not hasattr(llm, "astream"):
            return await llm.ainvoke(messages, **kwargs)
        provider_task: asyncio.Task[BaseMessage] = asyncio.create_task(
            coro=cls._consume_provider_response(llm=llm, messages=messages, kwargs=kwargs)
        )
        return await cls._join_provider_response(provider_task=provider_task)

    @classmethod
    async def _consume_provider_response(
        cls, *, llm: BaseChatModel, messages: list[BaseMessage], kwargs: dict[str, Any]
    ) -> BaseMessage:
        """Assemble public chunks and close the exact stream before returning truth.

        Args:
            llm: Retained provider whose public stream preserves bound options/context.
            messages: Original validated provider request.
            kwargs: Original provider-lane options.

        Returns:
            BaseMessage: Completed message assembled from the actual stream chunks.

        Raises:
            ValueError: The stream produced no chunks.
            BaseException: Stream consumption or generator cleanup failed.
        """
        stream: AsyncIterator[BaseMessageChunk] = llm.astream(input=messages, **kwargs)
        completed: Optional[BaseMessageChunk] = None
        chunk: BaseMessageChunk
        try:
            async for chunk in stream:
                completed = chunk if completed is None else completed + chunk
        finally:
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()
        if completed is None:
            raise ValueError("provider_completed_without_message")
        return message_chunk_to_message(completed)

    @classmethod
    async def _join_provider_response(cls, *, provider_task: asyncio.Task[BaseMessage]) -> BaseMessage:
        """Cancel once and retrieve provider truth only after its task has terminated.

        Args:
            provider_task: Exact consumption task inheriting the graph's ContextVars.

        Returns:
            BaseMessage: Actual completion, even when the provider suppresses cancellation.

        Raises:
            BaseException: Actual provider failure or cancellation after the join;
                repeated caller cancellation never releases cleanup early.
        """
        cancellation_requested: bool = False
        while not provider_task.done():
            try:
                await asyncio.shield(provider_task)
            except asyncio.CancelledError:
                if not cancellation_requested:
                    cancellation_requested = True
                    provider_task.cancel()
            except Exception:
                break
        return provider_task.result()

    @classmethod
    def retain_completed_response(cls, *, message: BaseMessage) -> None:
        """Retain actual node truth synchronously before graph cancellation can discard it."""
        sink = _completed_response_sink.get()
        if sink is not None:
            sink(message)

    @classmethod
    async def invoke(
        cls,
        *,
        graph: CompiledStateGraph,
        state: SloAgentStateDAO,
        completed_responses: list[BaseMessage],
    ) -> AsyncGenerator[object, None]:
        """Drive one graph and join its exact task before the iterator closes.

        Args:
            graph: Existing compiled graph with retained model, tools and output queue.
            state: Initial context for this attempt.
            completed_responses: Caller-owned bounded-by-topology completion slot; one
                node response retained synchronously even when cancellation wins.

        Yields:
            object: Existing messages/updates parser inputs.

        Raises:
            Exception: Actual driver or cleanup failure, including after cancellation.
            asyncio.CancelledError: Caller cancellation after driver cleanup joins.
        """
        queue: asyncio.Queue[object] = GraphEventQueue()
        terminal = object()
        callbacks = GraphStreamCallbacks(queue=queue)

        async def drive() -> None:
            """Own the only graph invocation and close its updates iterator."""
            token = _completed_response_sink.set(completed_responses.append)
            updates = graph.astream(
                state, config={"callbacks": [callbacks]}, stream_mode="updates", subgraphs=False
            )
            try:
                async for update in updates:
                    if not callbacks.closing:
                        await queue.put(("updates", update))
            finally:
                try:
                    if isinstance(updates, AsyncGenerator):
                        await updates.aclose()
                finally:
                    _completed_response_sink.reset(token)
                    if not callbacks.closing:
                        await queue.put(terminal)

        driver: asyncio.Task[None] = asyncio.create_task(coro=drive())
        try:
            while True:
                item = await queue.get()
                if item is terminal:
                    await driver
                    return
                yield item
        finally:
            callbacks.closing = True
            while not queue.empty():
                queue.get_nowait()
            if not driver.done():
                driver.cancel()
            joined = asyncio.gather(driver, return_exceptions=True)
            while not joined.done():
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError:
                    continue
            failure = callbacks.failure or joined.result()[0]
            if isinstance(failure, BaseException) and not isinstance(failure, asyncio.CancelledError):
                raise failure
