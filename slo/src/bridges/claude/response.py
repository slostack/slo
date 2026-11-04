"""Correlated portable response assembly and ordered receiver acceptance."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Self

from pydantic import BaseModel, ConfigDict

from .sdk.dao import ClaudeInteractionBindingDAO
from .sdk.events import ClaudeBridgeEvent, ClaudeResponseCompletedDAO, ClaudeTextEventDAO


class ClaudeResponseTranslationDAO(BaseModel):
    """Accepted event and per-response assembled text for a borrowed host builder."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    event: ClaudeBridgeEvent
    text: str


class AIAgentResponseAdapter:
    """Own correlation, echo suppression, response assembly and receiver ordering.

    Native fragment/echo validation remains in the SDK parser. This owner rejects
    stale portable events and never allows a late event to update another response.
    """

    @classmethod
    def register(
        cls,
        *,
        binding: ClaudeInteractionBindingDAO,
        response_receiver: Callable[[ClaudeResponseTranslationDAO], Awaitable[None]],
        tool_call_receiver: Callable[[ClaudeResponseTranslationDAO], Awaitable[None]],
    ) -> Self:
        """Register borrowed builders for one invocation without I/O."""
        return cls(
            binding=binding, response_receiver=response_receiver, tool_call_receiver=tool_call_receiver
        )

    def __init__(
        self,
        *,
        binding: ClaudeInteractionBindingDAO,
        response_receiver: Callable[[ClaudeResponseTranslationDAO], Awaitable[None]],
        tool_call_receiver: Callable[[ClaudeResponseTranslationDAO], Awaitable[None]],
    ) -> None:
        """Keep one assembly, bounded identity digests and serialized delivery."""
        self._binding = binding
        self._response_receiver = response_receiver
        self._tool_call_receiver = tool_call_receiver
        self._accepted: dict[int, bytes] = {}
        self._completed: set[str] = set()
        self._response_id: str | None = None
        self._text = ""
        self._sequence = 0
        self._delivery: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def handle(self, *, event: ClaudeBridgeEvent) -> None:
        """Reserve a correlated ordered event before its builder runs; never replay failure."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("Claude response adapter is closed.")
            await self.reset()
            digest = hashlib.sha256(event.model_dump_json().encode()).digest()
            if self._validate_event(event=event, digest=digest):
                return
            self._assemble(event=event)
            self._accepted[event.sequence] = digest
            self._sequence = event.sequence
            translated = ClaudeResponseTranslationDAO(event=event.model_copy(deep=True), text=self._text)
            self._delivery = asyncio.create_task(coro=self._deliver(translation=translated))
            await asyncio.shield(self._delivery)

    def _validate_event(self, *, event: ClaudeBridgeEvent, digest: bytes) -> bool:
        """Return exact-repeat status or reject changed binding/order before mutation."""
        if event.session_id != self._binding.session_id or event.invocation_id != self._binding.invocation_id:
            raise ValueError("Claude response binding changed.")
        if event.sequence in self._accepted:
            if self._accepted[event.sequence] != digest:
                raise ValueError("Claude response echo contradicts accepted event.")
            return True
        if event.sequence <= self._sequence or event.response_id in self._completed:
            raise ValueError("Claude response sequence or completion order changed.")
        if self._response_id is not None and event.response_id != self._response_id:
            raise ValueError("Claude response overlaps unfinished assembly.")
        if len(self._accepted) >= 10000:
            raise ValueError("Claude response identity limit exceeded.")
        return False

    def _assemble(self, *, event: ClaudeBridgeEvent) -> None:
        """Keep text isolated per response and retire only validated completions."""
        previous_text = "" if self._response_id is None else self._text
        if isinstance(event, ClaudeTextEventDAO):
            if len(previous_text.encode()) + len(event.text.encode()) > 32 * 1024 * 1024:
                raise ValueError("Claude response text limit exceeded.")
        if self._response_id is None:
            self._response_id = event.response_id
            self._text = ""
        if isinstance(event, ClaudeTextEventDAO):
            self._text += event.text
        if isinstance(event, ClaudeResponseCompletedDAO):
            self._completed.add(event.response_id)
            self._response_id = None

    async def _deliver(self, *, translation: ClaudeResponseTranslationDAO) -> None:
        """Route a completed tool response separately from text/terminal acceptance."""
        event = translation.event
        receiver = (
            self._tool_call_receiver
            if isinstance(event, ClaudeResponseCompletedDAO) and event.tool_calls
            else self._response_receiver
        )
        await receiver(translation)

    async def reset(self) -> None:
        """Join admitted delivery; never erase accepted identity or unfinished assembly."""
        if self._delivery is not None:
            await asyncio.shield(self._delivery)

    async def close(self) -> None:
        """Seal admission and join the current builder without closing borrowed receivers."""
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
