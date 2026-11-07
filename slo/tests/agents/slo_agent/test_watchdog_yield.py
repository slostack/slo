"""Owned-read lifecycle branches complementary to the real SQLite journey."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import BoundaryDAO, BoundaryDeliveryDAO
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl
from src.agents.slo_agent.watchdog_timer import WatchDogTimer
from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError
from tests.agents.slo_agent.tool_execution.test_yield_control import RecordingMessageSource


def provider_control(*, source: RecordingMessageSource) -> ToolExecutionControl:
    """Enter an empty cached provider boundary without claiming input."""
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    control.enter_provider(
        delivery=BoundaryDeliveryDAO(
            boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=0), urgent_high_water=0
        ),
        attempt_turn_id=str(uuid4()),
        iteration=0,
    )
    return control


async def test_actual_none_is_an_item_not_exhaustion() -> None:
    """A framework None occupies one real read; only StopAsyncIteration ends it."""

    async def stream() -> AsyncGenerator[object, None]:
        """Produce a single nullable framework item."""
        yield None

    iterator = stream()
    timer = WatchDogTimer(first_progress_timeout_seconds=1.0, idle_timeout_seconds=1.0)
    assert (await timer.invoke(graph_stream=iterator)).kind == "item"
    assert (await timer.invoke(graph_stream=iterator)).kind == "end"


async def test_phase_transition_inside_read_disables_deadline() -> None:
    """Tools own a pending read before the deadline; no intermediate chunk is needed."""
    source = RecordingMessageSource(urgent_high_water=0)
    control = provider_control(source=source)

    async def stream() -> AsyncGenerator[object, None]:
        """Enter tools synchronously, then cross the former provider deadline."""
        control.enter_tools(tool_call_ids=("a",))
        await asyncio.sleep(delay=0.03)
        control.enter_settling()
        yield "truth"

    timer = WatchDogTimer(first_progress_timeout_seconds=0.01, idle_timeout_seconds=0.01)
    assert (await timer.invoke(graph_stream=stream(), control=control)).item == "truth"


@pytest.mark.parametrize(argnames="value", argvalues=[None, "settled truth"])
async def test_yield_retains_cancellation_suppressed_item(value: object) -> None:
    """Reservation cancels once and preserves even a normally returned None."""
    source = RecordingMessageSource(urgent_high_water=0)
    control = provider_control(source=source)
    entered = asyncio.Event()
    cancellations: list[int] = []

    async def stream() -> AsyncGenerator[object, None]:
        """Suppress cancellation only at the controlled external read boundary."""
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellations.append(1)
            yield value

    iterator = stream()
    timer = WatchDogTimer(first_progress_timeout_seconds=1.0, idle_timeout_seconds=1.0)
    task = asyncio.create_task(timer.invoke(graph_stream=iterator, control=control))
    try:
        await entered.wait()
        source.publish_newer_urgency(sequence=1)
        outcome = await task
        assert outcome.kind == "yield" and outcome.has_settled_item
        assert outcome.settled_item == value and cancellations == [1]
    finally:
        await iterator.aclose()
        assert task.done()


async def test_timeout_cleanup_failure_is_not_a_retryable_timeout() -> None:
    """A failed cancellation cleanup must bypass all provider retry planners."""

    async def stream() -> AsyncGenerator[object, None]:
        """Raise only while joining the cancelled external read."""
        try:
            await asyncio.Event().wait()
        finally:
            raise ValueError("private provider cleanup detail")
        yield None

    timer = WatchDogTimer(first_progress_timeout_seconds=0.01, idle_timeout_seconds=1.0)
    with pytest.raises(CooperativeYieldSettlementError, match="cooperative_yield_settlement_failed"):
        await timer.invoke(graph_stream=stream())


async def test_abort_beats_already_completed_item_and_urgency() -> None:
    """Abort prevents a completed read from becoming an urgent continuation."""
    source = RecordingMessageSource(urgent_high_water=0)
    control = provider_control(source=source)
    abort = asyncio.Event()

    async def stream() -> AsyncGenerator[object, None]:
        """Publish all competing signals in the exact reader task."""
        source.publish_newer_urgency(sequence=1)
        abort.set()
        yield "completed truth"

    timer = WatchDogTimer(first_progress_timeout_seconds=1.0, idle_timeout_seconds=1.0)
    with pytest.raises(asyncio.CancelledError):
        await timer.invoke(graph_stream=stream(), control=control, abort_event=abort)
    assert control.is_provider_active()


async def test_completed_item_beats_simultaneous_urgency() -> None:
    """Normal completed truth wins before any yield reservation."""
    source = RecordingMessageSource(urgent_high_water=0)
    control = provider_control(source=source)

    async def stream() -> AsyncGenerator[object, None]:
        """Signal urgency immediately before returning the real item."""
        source.publish_newer_urgency(sequence=1)
        yield "completed truth"

    timer = WatchDogTimer(first_progress_timeout_seconds=1.0, idle_timeout_seconds=1.0)
    outcome = await timer.invoke(graph_stream=stream(), control=control)
    assert outcome.kind == "item" and outcome.item == "completed truth"
    assert control.is_provider_active()


async def test_repeated_caller_cancel_cannot_abandon_reader_join() -> None:
    """Repeated cancellation leaves ownership held until the reader actually terminates."""
    entered, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stream() -> AsyncGenerator[object, None]:
        """Model cleanup remains held independently of caller cancellation."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            await release.wait()
        yield "unreachable"

    iterator = stream()
    timer = WatchDogTimer(first_progress_timeout_seconds=1.0, idle_timeout_seconds=1.0)
    task = asyncio.create_task(timer.invoke(graph_stream=iterator))
    try:
        await entered.wait()
        task.cancel()
        await stopping.wait()
        task.cancel()
        await asyncio.sleep(delay=0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await iterator.aclose()
    assert task.done()


async def test_nonprogress_callback_chatter_cannot_reset_provider_deadline() -> None:
    """Only normalized meaningful output affects timing; callback lifecycle chatter does not."""
    from src.agents.slo_agent.graph.event_stream import GraphStreamCallbacks
    from src.agents.providers.stream_recovery.dao import ProviderStreamProgressTimeout

    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=8)
    callbacks = GraphStreamCallbacks(queue=queue)
    stopped = asyncio.Event()
    count = 0

    async def chatter() -> None:
        """Produce public start callbacks without any live provider token."""
        nonlocal count
        try:
            while True:
                await callbacks.on_chain_start(None, {}, run_id=uuid4(), name="unrelated")
                count += 1
                await asyncio.sleep(delay=0)
        finally:
            stopped.set()

    async def read() -> AsyncGenerator[object, None]:
        """Wait for meaningful transport, which lifecycle callbacks never publish."""
        yield await queue.get()

    producer = asyncio.create_task(coro=chatter())
    stream = read()
    try:
        timer = WatchDogTimer(first_progress_timeout_seconds=0.01, idle_timeout_seconds=0.01)
        with pytest.raises(ProviderStreamProgressTimeout, match="first_progress"):
            await timer.invoke(graph_stream=stream)
        assert count > 0
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        await stream.aclose()
    assert stopped.is_set()
