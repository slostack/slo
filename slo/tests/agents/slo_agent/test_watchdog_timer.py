"""Tests for the provider-progress watchdog timer."""

import asyncio
from typing import AsyncIterator

import pytest

from src.agents.providers.stream_recovery.dao import ProviderStreamProgressTimeout
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.watchdog_timer import WatchDogTimer


class TestWatchDogTimer:
    """Verify provider-progress deadlines and local-tool suspension."""

    @pytest.mark.asyncio
    async def test_invoke_when_first_provider_progress_never_arrives_raises_first_progress_timeout(
        self,
    ) -> None:
        """The initial provider read uses the first-progress deadline."""

        async def silent_stream() -> AsyncIterator[object]:
            await asyncio.Event().wait()
            yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=0.01,
            idle_timeout_seconds=1.0,
        )
        with pytest.raises(ProviderStreamProgressTimeout, match="first_progress"):
            await watchdog_timer.invoke(graph_stream=silent_stream())

    @pytest.mark.asyncio
    async def test_invoke_when_provider_stalls_after_progress_raises_idle_timeout(self) -> None:
        """A successful read changes the next provider deadline to idle."""

        async def one_item_then_silent_stream() -> AsyncIterator[object]:
            yield "provider progress"
            await asyncio.Event().wait()
            yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=1.0,
            idle_timeout_seconds=0.01,
        )
        stream: AsyncIterator[object] = one_item_then_silent_stream()

        assert await watchdog_timer.invoke(graph_stream=stream) == "provider progress"
        with pytest.raises(ProviderStreamProgressTimeout, match="idle"):
            await watchdog_timer.invoke(graph_stream=stream)

    @pytest.mark.asyncio
    async def test_invoke_when_local_tools_are_in_flight_skips_idle_deadline_until_all_results_arrive(
        self,
    ) -> None:
        """Local work remains outside provider timing through tool-call closure."""

        async def provider_then_slow_tool_results_stream() -> AsyncIterator[object]:
            yield "provider progress"
            await asyncio.sleep(0.03)
            yield "first tool result"
            await asyncio.sleep(0.03)
            yield "second tool result"
            await asyncio.Event().wait()
            yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=1.0,
            idle_timeout_seconds=0.01,
        )
        stream: AsyncIterator[object] = provider_then_slow_tool_results_stream()

        assert await watchdog_timer.invoke(graph_stream=stream) == "provider progress"
        watchdog_timer.observe_message_events(
            events=[
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="call-1"),
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="call-2"),
            ]
        )
        watchdog_timer.observe_message_events(events=[AgentStreamEventDAO(kind="tool_call_end")])

        assert await watchdog_timer.invoke(graph_stream=stream) == "first tool result"
        watchdog_timer.observe_update_events(
            events=[AgentStreamEventDAO(kind="tool_result", tool_call_id="call-1")]
        )

        assert await watchdog_timer.invoke(graph_stream=stream) == "second tool result"
        watchdog_timer.observe_update_events(
            events=[AgentStreamEventDAO(kind="tool_result", tool_call_id="call-2")]
        )

        with pytest.raises(ProviderStreamProgressTimeout, match="idle"):
            await watchdog_timer.invoke(graph_stream=stream)

    @pytest.mark.asyncio
    async def test_resumes_idle_deadline_after_last_result_when_starts_arrive_in_update_events(
        self,
    ) -> None:
        """A17: completed-message starts pause timing until the last parallel result arrives.

        Spec 107 §9: a completed-only or late-named call gets its ``tool_call_start``
        on the updates channel, together with its ``tool_call_end``.
        """

        async def completed_message_then_slow_parallel_results_stream() -> AsyncIterator[object]:
            """Yield delayed local results, then stall provider reads until timeout cancellation.

            Yields:
                object: Completed assistant progress followed by each parallel result.
            """
            yield "completed assistant message"
            await asyncio.sleep(0.03)
            yield "first tool result"
            await asyncio.sleep(0.03)
            yield "second tool result"
            await asyncio.Event().wait()
            yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=1.0,
            idle_timeout_seconds=0.01,
        )
        stream: AsyncIterator[object] = completed_message_then_slow_parallel_results_stream()

        assert await watchdog_timer.invoke(graph_stream=stream) == "completed assistant message"
        watchdog_timer.observe_update_events(
            events=[
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="call-1", tool_name="read"),
                AgentStreamEventDAO(kind="tool_call_end", tool_call_id="call-1", tool_name="read"),
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="call-2", tool_name="grep"),
                AgentStreamEventDAO(kind="tool_call_end", tool_call_id="call-2", tool_name="grep"),
            ]
        )

        assert await watchdog_timer.invoke(graph_stream=stream) == "first tool result"
        watchdog_timer.observe_update_events(
            events=[AgentStreamEventDAO(kind="tool_result", tool_call_id="call-1")]
        )

        assert await watchdog_timer.invoke(graph_stream=stream) == "second tool result"
        watchdog_timer.observe_update_events(
            events=[AgentStreamEventDAO(kind="tool_result", tool_call_id="call-2")]
        )

        with pytest.raises(ProviderStreamProgressTimeout, match="idle"):
            await watchdog_timer.invoke(graph_stream=stream)

    @pytest.mark.asyncio
    async def test_counts_starts_before_results_when_update_batch_contains_both(self) -> None:
        """A17 supplemental: mixed updates subtract results only after counting every new start."""

        async def delayed_remaining_result() -> AsyncIterator[object]:
            """Outlive the provider deadline while one local call remains.

            Yields:
                object: The remaining local result, followed by a provider stall.
            """
            await asyncio.sleep(0.03)
            yield "last result"
            await asyncio.Event().wait()
            yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=0.01, idle_timeout_seconds=0.01
        )
        watchdog_timer.observe_update_events(
            events=[
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="first", tool_name="read"),
                AgentStreamEventDAO(kind="tool_call_start", tool_call_id="last", tool_name="read"),
                AgentStreamEventDAO(kind="tool_result", tool_call_id="first"),
            ]
        )
        stream: AsyncIterator[object] = delayed_remaining_result()
        async with asyncio.timeout(1):
            assert await watchdog_timer.invoke(graph_stream=stream) == "last result"
        watchdog_timer.observe_update_events(
            events=[AgentStreamEventDAO(kind="tool_result", tool_call_id="last")]
        )
        with pytest.raises(ProviderStreamProgressTimeout, match="idle"):
            await watchdog_timer.invoke(graph_stream=stream)

    @pytest.mark.asyncio
    async def test_invoke_when_graph_stream_ends_returns_none(self) -> None:
        """A completed graph stream is not reported as a provider failure."""

        async def empty_stream() -> AsyncIterator[object]:
            if False:  # pragma: no cover
                yield "unreachable"

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=1.0,
            idle_timeout_seconds=1.0,
        )

        assert await watchdog_timer.invoke(graph_stream=empty_stream()) is None

    @pytest.mark.asyncio
    async def test_invoke_when_graph_stream_raises_non_timeout_error_propagates_it(self) -> None:
        """Only a deadline expiry is translated into a provider-progress timeout."""

        async def failing_stream() -> AsyncIterator[object]:
            raise ValueError("graph failed")
            yield "unreachable"  # pragma: no cover

        watchdog_timer: WatchDogTimer = WatchDogTimer.build(
            first_progress_timeout_seconds=1.0,
            idle_timeout_seconds=1.0,
        )

        with pytest.raises(ValueError, match="graph failed"):
            await watchdog_timer.invoke(graph_stream=failing_stream())
