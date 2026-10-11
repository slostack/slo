"""Provider-progress watchdog timing for one streamed LangGraph turn."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Literal

from src.agents.providers.stream_recovery.dao import ProviderStreamProgressTimeout
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = ["WatchDogTimer"]


class WatchDogTimer:
    """Own provider progress deadlines and local-tool suspension for one graph stream."""

    def __init__(
        self,
        *,
        first_progress_timeout_seconds: float,
        idle_timeout_seconds: float,
    ) -> None:
        """Initialize one timer with the configured provider-progress deadlines.

        Args:
            first_progress_timeout_seconds (float): Maximum wait for the first graph item.
            idle_timeout_seconds (float): Maximum gap between later provider graph items.
        """
        self._first_progress_timeout_seconds: float = first_progress_timeout_seconds
        self._idle_timeout_seconds: float = idle_timeout_seconds
        self._first_progress_pending: bool = True
        self._provider_read_pending: bool = True
        self._local_tool_calls_in_flight: int = 0

    @classmethod
    def build(
        cls,
        *,
        first_progress_timeout_seconds: float,
        idle_timeout_seconds: float,
    ) -> WatchDogTimer:
        """Build a timer for one LangGraph stream attempt.

        WHAT: Creates the state that selects first-progress versus idle deadlines
            and remembers local tool calls that suspend provider timing.
        WHO: ``SloAgent._stream_graph_turn`` creates one timer for each graph stream.
        WHEN: Runs immediately before the agent begins consuming that graph stream.

        Args:
            first_progress_timeout_seconds (float): Maximum wait before initial provider progress.
            idle_timeout_seconds (float): Maximum provider-progress gap after the first item.

        Returns:
            WatchDogTimer: A fresh timer with no observed stream or tool events.
        """
        return cls(
            first_progress_timeout_seconds=first_progress_timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )

    async def invoke(self, *, graph_stream: AsyncIterator[object]) -> object | None:
        """Read the next graph item with the active provider-progress policy.

        WHAT: Applies the first-progress deadline before provider output begins and
            the idle deadline between later provider reads. Local tool execution is
            read without a provider deadline until every observed tool result arrives.
        WHO: ``SloAgent._stream_graph_turn`` calls this once for each pending graph read.
        WHEN: Runs for the lifetime of one ReAct graph stream, before parsing each item.

        Args:
            graph_stream (AsyncIterator[object]): Combined LangGraph messages/updates stream.

        Returns:
            object | None: The next graph item, or ``None`` when the stream is complete.

        Raises:
            ProviderStreamProgressTimeout: If provider progress misses its active deadline.
        """
        raw_item: object | None = await self._read_next_graph_item(graph_stream=graph_stream)
        if raw_item is None:
            return None
        self._first_progress_pending = False
        return raw_item

    def observe_message_events(self, *, events: list[AgentStreamEventDAO]) -> None:
        """Record local tool calls requested by streamed assistant messages.

        WHAT: Counts each newly opened tool call and suspends provider timing while
            LangGraph may execute those calls locally.
        WHO: ``SloAgent._stream_graph_turn`` calls this after normalizing a messages-mode chunk.
        WHEN: Runs after each provider message chunk and before the next graph read.

        Args:
            events (list[AgentStreamEventDAO]): Normalized events from one messages-mode chunk.
        """
        local_tool_call_count: int = self._tool_call_start_count(events=events)
        if local_tool_call_count == 0:
            return
        self._local_tool_calls_in_flight += local_tool_call_count
        self._provider_read_pending = False

    def observe_update_events(self, *, events: list[AgentStreamEventDAO]) -> None:
        """Record completed local tool calls from LangGraph update events.

        WHAT: Decrements the local-tool count for each result and re-enables provider
            timing only after all observed local tool calls have completed.
        WHO: ``SloAgent._stream_graph_turn`` calls this after processing an updates-mode chunk.
        WHEN: Runs before the agent asks LangGraph for the following item.

        Args:
            events (list[AgentStreamEventDAO]): Normalized events from one updates-mode chunk.
        """
        local_tool_result_count: int = self._tool_result_count(events=events)
        if local_tool_result_count == 0:
            return
        self._local_tool_calls_in_flight = max(0, self._local_tool_calls_in_flight - local_tool_result_count)
        self._provider_read_pending = self._local_tool_calls_in_flight == 0

    async def _read_next_graph_item(self, *, graph_stream: AsyncIterator[object]) -> object | None:
        """Choose a provider-deadline or local-tool read for the next graph item."""
        if not self._provider_read_pending:
            return await self._read_graph_item_without_provider_deadline(graph_stream=graph_stream)
        return await self._read_graph_item_with_provider_deadline(graph_stream=graph_stream)

    async def _read_graph_item_with_provider_deadline(
        self,
        *,
        graph_stream: AsyncIterator[object],
    ) -> object | None:
        """Read one provider-pending item and translate only deadline expiry."""
        try:
            # Keep graph iteration in the caller task. wait_for's separate
            # reader can outlive cancellation racing with a completed chunk,
            # leaving aclose() to collide with an active async generator.
            async with asyncio.timeout(self._provider_read_timeout_seconds()):
                return await anext(graph_stream)
        except StopAsyncIteration:
            return None
        except asyncio.TimeoutError as exc:
            raise ProviderStreamProgressTimeout(phase=self._timeout_phase()) from exc

    @staticmethod
    async def _read_graph_item_without_provider_deadline(
        *,
        graph_stream: AsyncIterator[object],
    ) -> object | None:
        """Read one graph item while LangGraph waits for local tool execution."""
        try:
            return await anext(graph_stream)
        except StopAsyncIteration:
            return None

    def _provider_read_timeout_seconds(self) -> float:
        """Return the deadline for the current provider-pending graph read."""
        if self._first_progress_pending:
            return self._first_progress_timeout_seconds
        return self._idle_timeout_seconds

    def _timeout_phase(self) -> Literal["first_progress", "idle"]:
        """Return the typed phase for the current provider-progress deadline."""
        if self._first_progress_pending:
            return "first_progress"
        return "idle"

    @staticmethod
    def _tool_call_start_count(*, events: list[AgentStreamEventDAO]) -> int:
        """Return the number of local tool calls newly opened by one message chunk."""
        return sum(event.kind == "tool_call_start" for event in events)

    @staticmethod
    def _tool_result_count(*, events: list[AgentStreamEventDAO]) -> int:
        """Return the number of local tool results completed by one update chunk."""
        return sum(event.kind == "tool_result" for event in events)
