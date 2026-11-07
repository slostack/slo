"""ToolExecutionControl provider/tools/high-water ownership (96.a.2 §3.3, §5.2)."""

from __future__ import annotations

import asyncio
from typing import Optional
from uuid import uuid4

import pytest

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    BoundaryDeliveryDAO,
    MessageDeliveryDAO,
)
from src.agents.slo_agent.tool_execution.yield_policy import (
    CooperativeProviderYield,
    ToolExecutionControl,
    ToolYieldCapabilityError,
)


class RecordingMessageSource:
    """Typed recording source; records reads/waits and refuses claims."""

    def __init__(self, *, urgent_high_water: int) -> None:
        """Bind the initial urgency snapshot and an unset newer-urgency event."""
        self.urgent_high_water_value: int = urgent_high_water
        self.wait_calls: list[int] = []
        self.claim_calls: int = 0
        self.commit_calls: int = 0
        self._newer_urgency: asyncio.Event = asyncio.Event()

    async def take_one(self, *, boundary: BoundaryDAO) -> BoundaryDeliveryDAO:
        """Refuse a claim; control must never advance the queue for itself."""
        self.claim_calls += 1
        raise AssertionError("control must not claim input")

    async def commit_applied(self, *, delivery: MessageDeliveryDAO) -> None:
        """Refuse an acknowledgement; control owns no application receipt."""
        self.commit_calls += 1
        raise AssertionError("control must not acknowledge input")

    def urgent_high_water(self) -> int:
        """Return the current recorded urgency high-water."""
        return self.urgent_high_water_value

    def yield_is_requested(self, *, after_sequence: int) -> bool:
        """Return whether urgency newer than the boundary snapshot exists."""
        return self.urgent_high_water_value > after_sequence

    async def wait_for_yield(self, *, after_sequence: int) -> None:
        """Wait for a recorded newer-urgency notification."""
        self.wait_calls.append(after_sequence)
        if self.urgent_high_water_value > after_sequence:
            return
        await self._newer_urgency.wait()

    async def has_pending_input(self) -> bool:
        """Report no independent pending-input query."""
        return False

    def publish_newer_urgency(self, *, sequence: int) -> None:
        """Record a newer urgent sequence and wake the source waiter."""
        self.urgent_high_water_value = sequence
        self._newer_urgency.set()


def _delivery(*, urgent_high_water: int = 0, boundary_index: int = 0) -> BoundaryDeliveryDAO:
    """Build an empty cached selection for one stable boundary."""
    return BoundaryDeliveryDAO(
        boundary=BoundaryDAO(run_id=str(uuid4()), boundary_index=boundary_index),
        urgent_high_water=urgent_high_water,
    )


async def test_provider_reservation_wins_before_tools_and_claims_nothing() -> None:
    """A newer urgent sequence reserves provider yield and blocks tool entry."""
    source = RecordingMessageSource(urgent_high_water=7)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    control.enter_provider(
        delivery=_delivery(urgent_high_water=7),
        attempt_turn_id=str(uuid4()),
        iteration=0,
    )

    waiter = asyncio.create_task(control.wait_for_yield())
    await asyncio.sleep(0)
    assert source.wait_calls == [7]
    source.publish_newer_urgency(sequence=8)
    await waiter

    assert control.reserve_provider_yield() is True
    with pytest.raises(CooperativeProviderYield):
        control.enter_tools(tool_call_ids=("call-a",))
    assert source.claim_calls == 0
    assert source.commit_calls == 0


async def test_equal_high_water_enters_tools_and_newer_urgency_denies_dispatch() -> None:
    """Only urgency newer than the boundary snapshot changes a dispatch decision."""
    source = RecordingMessageSource(urgent_high_water=7)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)
    control.enter_provider(
        delivery=_delivery(urgent_high_water=7),
        attempt_turn_id=str(uuid4()),
        iteration=0,
    )

    assert control.reserve_provider_yield() is False
    control.enter_tools(tool_call_ids=("call-a", "call-b"))
    await asyncio.wait_for(control.wait_for_provider_exit(), timeout=1)
    assert control.before_dispatch(tool_call_id="call-a") is True

    source.publish_newer_urgency(sequence=8)
    assert control.before_dispatch(tool_call_id="call-a") is False
    assert source.claim_calls == 0
    assert source.commit_calls == 0


async def test_illegal_transitions_and_new_attempt_identity_are_rejected() -> None:
    """Duplicate/out-of-phase transitions fail closed with the fixed error."""
    source = RecordingMessageSource(urgent_high_water=0)
    control = ToolExecutionControl(source=source, on_deferred=lambda metadata: None)

    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_tools(tool_call_ids=("call-a",))

    delivery = _delivery()
    attempt_turn_id = str(uuid4())
    control.enter_provider(
        delivery=delivery,
        attempt_turn_id=attempt_turn_id,
        iteration=0,
    )
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_provider(
            delivery=delivery,
            attempt_turn_id=attempt_turn_id,
            iteration=0,
        )
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.before_dispatch(tool_call_id="unknown")
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_tools(tool_call_ids=("call-a", "call-a"))
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_settling()
    control.settle_attempt()
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.settle_attempt()

    control.enter_provider(
        delivery=delivery,
        attempt_turn_id=str(uuid4()),
        iteration=1,
    )
    control.enter_tools(tool_call_ids=("call-a",))
    control.enter_settling()
    control.settle_attempt()
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_provider(
            delivery=_delivery(boundary_index=1),
            attempt_turn_id=str(uuid4()),
            iteration=2,
        )

    control.enter_provider(
        delivery=delivery,
        attempt_turn_id=str(uuid4()),
        iteration=2,
    )
    control.close()
    control.close()
    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        control.enter_provider(
            delivery=delivery,
            attempt_turn_id=str(uuid4()),
            iteration=2,
        )


def test_control_rejects_cross_loop_invocation() -> None:
    """One control may only be operated from the loop that first owned it."""

    async def first_loop() -> ToolExecutionControl:
        """Bind ownership to this loop and enter the provider phase."""
        control = ToolExecutionControl(
            source=RecordingMessageSource(urgent_high_water=0),
            on_deferred=lambda metadata: None,
        )
        control.enter_provider(
            delivery=_delivery(),
            attempt_turn_id=str(uuid4()),
            iteration=0,
        )
        return control

    control = asyncio.run(first_loop())

    async def second_loop() -> None:
        """Attempt a transition from a different running loop."""
        control.enter_tools(tool_call_ids=("call-a",))

    with pytest.raises(ToolYieldCapabilityError, match="tool_yield_capability_invalid"):
        asyncio.run(second_loop())
