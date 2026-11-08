"""Completed portable call translation; never execute or deliver partial calls."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Self

from pydantic import BaseModel, ConfigDict

from .sdk.dao import ClaudeInteractionBindingDAO, ClaudeToolDefinitionDAO
from .sdk.events import ClaudeResponseCompletedDAO
from .sdk.inventory import ClaudeToolInventory


class ClaudeCompletedCallDAO(BaseModel):
    """One detached host-neutral call ready for a host message builder."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tool_call_id: str
    name: str
    arguments_json: str


class ClaudeCompletedCallBatchDAO(BaseModel):
    """Canonical source-ordered translation of one fully validated response."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    binding: ClaudeInteractionBindingDAO
    completion: ClaudeResponseCompletedDAO
    calls: tuple[ClaudeCompletedCallDAO, ...]


class ToolCallAdapter:
    """Validate/translate a whole completed batch once and retain delivery ownership."""

    @classmethod
    def register(
        cls,
        *,
        binding: ClaudeInteractionBindingDAO,
        response_id: str,
        tools: tuple[ClaudeToolDefinitionDAO, ...],
        receiver: Callable[[ClaudeCompletedCallBatchDAO], Awaitable[None]],
    ) -> Self:
        """Bind one response and borrowed builder without starting background work."""
        if not 1 <= len(response_id) <= 256:
            raise ValueError("Invalid Claude response identity.")
        return cls(binding=binding, response_id=response_id, tools=tools, receiver=receiver)

    def __init__(
        self,
        *,
        binding: ClaudeInteractionBindingDAO,
        response_id: str,
        tools: tuple[ClaudeToolDefinitionDAO, ...],
        receiver: Callable[[ClaudeCompletedCallBatchDAO], Awaitable[None]],
    ) -> None:
        """Retain immutable inventory and one exact response association."""
        self._binding = binding
        self._response_id = response_id
        self._names = frozenset(tool.name for tool in ClaudeToolInventory.freeze(tools=tools))
        self._receiver = receiver
        self._accepted: ClaudeCompletedCallBatchDAO | None = None
        self._delivery: asyncio.Task[None] | None = None
        self._closed = False

    async def handle(self, *, event: ClaudeResponseCompletedDAO) -> None:
        """Validate every call before reserving a single ordered builder delivery."""
        if self._closed:
            raise RuntimeError("Claude call adapter is closed.")
        batch = self._translate(event=event)
        if self._accepted is not None and self._accepted != batch:
            raise ValueError("Claude completed calls conflict with accepted calls.")
        if self._delivery is None:
            self._accepted = batch
            self._delivery = asyncio.create_task(coro=self._deliver(batch=batch))
        await asyncio.shield(self._delivery)

    def _translate(self, *, event: ClaudeResponseCompletedDAO) -> ClaudeCompletedCallBatchDAO:
        """Reject stale, unsupported, duplicate, oversized or nonfinite completed calls."""
        if (
            event.session_id != self._binding.session_id
            or event.invocation_id != self._binding.invocation_id
            or event.response_id != self._response_id
            or event.stop_reason != "tool_calls"
        ):
            raise ValueError("Claude completed-call binding changed.")
        ids = tuple(call.tool_call_id for call in event.tool_calls)
        if not 1 <= len(ids) <= 128 or len(set(ids)) != len(ids):
            raise ValueError("Claude completed-call set is invalid.")
        calls: list[ClaudeCompletedCallDAO] = []
        for call in event.tool_calls:
            arguments = json.dumps(call.arguments, allow_nan=False)
            if call.name not in self._names or len(arguments.encode()) > 1024 * 1024:
                raise ValueError("Claude completed call is unsupported or oversized.")
            calls.append(
                ClaudeCompletedCallDAO(
                    tool_call_id=call.tool_call_id, name=call.name, arguments_json=arguments
                )
            )
        if sum(len(call.model_dump_json().encode()) for call in event.tool_calls) > 32 * 1024 * 1024:
            raise ValueError("Claude completed-call batch is oversized.")
        return ClaudeCompletedCallBatchDAO(
            binding=self._binding, completion=event.model_copy(deep=True), calls=tuple(calls)
        )

    async def _deliver(self, *, batch: ClaudeCompletedCallBatchDAO) -> None:
        """Let the borrowed builder accept the already reserved translation."""
        await self._receiver(batch.model_copy(deep=True))

    async def reset(self) -> None:
        """Join admitted work without clearing accepted-call protection."""
        if self._delivery is not None:
            await asyncio.shield(self._delivery)

    async def close(self) -> None:
        """Seal and join admitted work, including after caller cancellation."""
        self._closed = True
        if self._delivery is None:
            return
        joined = asyncio.gather(self._delivery, return_exceptions=True)
        cancelled = False
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
