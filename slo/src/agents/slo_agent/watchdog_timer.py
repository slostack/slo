"""Provider-progress watchdog timing for one streamed LangGraph turn."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.providers.stream_recovery.dao import ProviderStreamProgressTimeout
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl, CooperativeProviderYield

__all__ = ["GraphReadOutcomeDAO", "WatchDogTimer"]


class GraphReadOutcomeDAO(BaseModel):
    """Closed outcome of one provider graph read.

    WHAT: Discriminates a framework item from normal stream exhaustion while
        reserving a separate cancellation-race payload for the later yield seam.
    WHO: ``WatchDogTimer.invoke`` returns it; ``SloAgent._stream_graph_turn``
        and callers interpret the explicit kind instead of a raw ``None`` sentinel.
    WHEN: Once per watchdog read, before parsing or stream cleanup.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["item", "end", "yield"] = Field(
        description="Outcome kind; the kind, not a nullable payload, proves exhaustion.",
    )
    item: Optional[object] = Field(
        default=None,
        description="Framework graph item; only kind=item permits a payload, and None is a valid item.",
    )
    settled_item: Optional[object] = Field(
        default=None,
        description="Cancellation-race item retained for cleanup; only kind=yield permits it.",
    )
    has_settled_item: bool = Field(
        default=False,
        description="True when a settled race item exists, even when its value is None.",
    )

    @model_validator(mode="after")
    def _validate_kind_payload(self) -> "GraphReadOutcomeDAO":
        """Reject payloads and presence flags owned by a different outcome kind."""
        if self.kind != "item" and self.item is not None:
            raise ValueError("graph_read_outcome_invalid")
        if self.kind in ("item", "end") and (self.settled_item is not None or self.has_settled_item):
            raise ValueError("graph_read_outcome_invalid")
        if self.kind == "yield" and not self.has_settled_item and self.settled_item is not None:
            raise ValueError("graph_read_outcome_invalid")
        return self


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

    async def invoke(
        self,
        *,
        graph_stream: AsyncIterator[object],
        control: Optional[ToolExecutionControl] = None,
        abort_event: Optional[asyncio.Event] = None,
    ) -> GraphReadOutcomeDAO:
        """Read the next graph item with the active provider-progress policy.

        WHAT: Applies the first-progress deadline before provider output begins and
            the idle deadline between later provider reads. Local tool execution is
            read without a provider deadline until every observed tool result arrives.
            Exhaustion is returned as an explicit end outcome, never a raw ``None``.
        WHO: ``SloAgent._stream_graph_turn`` calls this once for each pending graph read.
        WHEN: Runs for the lifetime of one ReAct graph stream, before parsing each item.

        Args:
            graph_stream (AsyncIterator[object]): Supported graph transport iterator.
            control (Optional[ToolExecutionControl]): Exact run phase/high-water owner;
                None retains legacy observed-tool timing.
            abort_event (Optional[asyncio.Event]): Explicit abort signal; None adds no waiter.

        Returns:
            GraphReadOutcomeDAO: Item, end, or reserved yield with optional settled race truth.

        Raises:
            ProviderStreamProgressTimeout: If provider progress misses its active deadline.
            CooperativeYieldSettlementError: Cancellation cleanup fails or timeout returns truth.
            asyncio.CancelledError: Abort/caller cancellation, only after all owned joins.
        """
        reader: asyncio.Task[object] = asyncio.create_task(self._read_graph_item(graph_stream=graph_stream))
        waiters: list[asyncio.Task[object]] = []
        try:
            outcome = await self._race_read(
                reader=reader, waiters=waiters, control=control, abort_event=abort_event
            )
            if outcome.kind == "item":
                self._first_progress_pending = False
            return outcome
        finally:
            await self._join_owned_read(reader=reader, waiters=waiters)

    @staticmethod
    async def _read_graph_item(*, graph_stream: AsyncIterator[object]) -> object:
        """Read exactly once in the creator's operation/credential context."""
        return await anext(graph_stream)

    async def _race_read(
        self,
        *,
        reader: asyncio.Task[object],
        waiters: list[asyncio.Task[object]],
        control: Optional[ToolExecutionControl],
        abort_event: Optional[asyncio.Event],
    ) -> GraphReadOutcomeDAO:
        """Arbitrate abort, completed truth, active deadline, then newer urgency.

        The caller owns every handle until the final shielded join. Phase exit
        disables timing inside a pending read, not merely after a yielded chunk.
        """
        urgent = asyncio.create_task(control.wait_for_yield()) if control is not None else None
        phase = asyncio.create_task(control.wait_for_provider_exit()) if control is not None else None
        abort = asyncio.create_task(abort_event.wait()) if abort_event is not None else None
        waiters.extend(task for task in (urgent, phase, abort) if task is not None)
        deadline: Optional[float] = (
            asyncio.get_running_loop().time() + self._provider_read_timeout_seconds()
            if self._provider_read_pending
            else None
        )
        active: set[asyncio.Task] = {reader, *waiters}
        while True:
            if abort_event is not None and abort_event.is_set():
                raise asyncio.CancelledError()
            if reader.done():
                return self._completed_read(reader=reader)
            if control is not None and not control.is_provider_active():
                deadline = None
            if deadline is not None and asyncio.get_running_loop().time() >= deadline:
                reader.cancel()
                await self._join_owned_read(reader=reader, waiters=waiters, cancel_reader=False)
                # A cancellation-suppressed item or exception is settled truth,
                # not permission to classify uncertain cleanup as retryable.
                settled = self._yielded_read(reader=reader)
                if settled.has_settled_item:
                    from src.agents.slo_agent.history.message_contract_reconciler import (
                        CooperativeYieldSettlementError,
                    )

                    raise CooperativeYieldSettlementError()
                raise ProviderStreamProgressTimeout(phase=self._timeout_phase())
            if urgent is not None and urgent.done():
                urgent.result()
                active.discard(urgent)
                urgent = None
                if control is not None and control.reserve_provider_yield():
                    reader.cancel()
                    await self._join_owned_read(reader=reader, waiters=waiters, cancel_reader=False)
                    outcome: GraphReadOutcomeDAO = self._yielded_read(reader=reader)
                    if abort_event is not None and abort_event.is_set():
                        raise asyncio.CancelledError()
                    return outcome
            if phase is not None and phase.done():
                phase.result()
                active.discard(phase)
                phase = None
            remaining = None if deadline is None else max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.wait(fs=active, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)

    @staticmethod
    def _completed_read(*, reader: asyncio.Task[object]) -> GraphReadOutcomeDAO:
        """Preserve a real None item separately from stream exhaustion."""
        try:
            return GraphReadOutcomeDAO(kind="item", item=reader.result())
        except StopAsyncIteration:
            return GraphReadOutcomeDAO(kind="end")

    @staticmethod
    def _yielded_read(*, reader: asyncio.Task[object]) -> GraphReadOutcomeDAO:
        """Retain cancellation-suppressed completed truth; never retry a failed join."""
        from src.agents.slo_agent.history.message_contract_reconciler import CooperativeYieldSettlementError

        try:
            return GraphReadOutcomeDAO(kind="yield", settled_item=reader.result(), has_settled_item=True)
        except (asyncio.CancelledError, StopAsyncIteration, CooperativeProviderYield):
            return GraphReadOutcomeDAO(kind="yield")
        except Exception as error:
            raise CooperativeYieldSettlementError() from error

    @staticmethod
    async def _join_owned_read(
        *,
        reader: asyncio.Task[object],
        waiters: list[asyncio.Task[object]],
        cancel_reader: bool = True,
    ) -> None:
        """Cancel once and retrieve every owned handle despite repeated caller cancellation.

        Cleanup is retained before suspension. No next read or stream close may
        proceed until this owner task has retrieved all results/exceptions.
        """

        async def join() -> None:
            """Drain the exact handles without transferring graph ownership."""
            for task in waiters:
                if not task.done():
                    task.cancel()
            if cancel_reader and not reader.done() and not reader.cancelling():
                reader.cancel()
            await asyncio.gather(reader, *waiters, return_exceptions=True)

        cleanup: asyncio.Task[object] = asyncio.create_task(join())
        cancelled: bool = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if reader.done() and not reader.cancelled():
            failure = reader.exception()
            if failure is not None and not isinstance(
                failure, (StopAsyncIteration, CooperativeProviderYield)
            ):
                from src.agents.slo_agent.history.message_contract_reconciler import (
                    CooperativeYieldSettlementError,
                )

                # Ordinary read failures are handled by _completed_read. A failure
                # after a cancellation request is uncertain cleanup, never abort.
                if reader.cancelling():
                    raise CooperativeYieldSettlementError() from failure
        if cancelled:
            raise asyncio.CancelledError()

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
