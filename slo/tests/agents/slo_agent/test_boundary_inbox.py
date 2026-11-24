"""Unit tests for the boundary-inbox port and its in-memory adapter (108.2).

The port is what ``SloAgent`` consumes at each safe boundary; the memory
adapter serves agents without a channel poller and tests. No infrastructure
is involved: this is a plain in-process queue.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO, MemoryBoundaryInbox


class TestBoundaryDeliveryDAOShape:
    def test_delivery_carries_the_spec_fields(self) -> None:
        """The DAO carries the message id, text, sender label and iteration."""
        delivery: BoundaryDeliveryDAO = BoundaryDeliveryDAO(
            message_id=uuid4(),
            text="use pytest -x",
            sender_name="you (tui)",
            iteration=3,
        )
        assert delivery.text == "use pytest -x"
        assert delivery.sender_name == "you (tui)"
        assert delivery.iteration == 3


class TestMemoryBoundaryInbox:
    async def test_empty_inbox_reports_no_forced_and_takes_nothing(self) -> None:
        """An empty memory inbox has nothing to apply and yields no deliveries."""
        inbox: MemoryBoundaryInbox = MemoryBoundaryInbox()
        assert inbox.has_forced() is False
        assert await inbox.take(iteration=0) == []

    async def test_enqueued_messages_are_taken_fifo_then_confirmed(self) -> None:
        """``take`` drains FIFO; ``confirm`` accepts them (a no-op in memory)."""
        inbox: MemoryBoundaryInbox = MemoryBoundaryInbox()
        inbox.enqueue(text="first steer")
        inbox.enqueue(text="second steer")
        assert inbox.has_forced() is True
        deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=2)
        assert [delivery.text for delivery in deliveries] == ["first steer", "second steer"]
        assert [delivery.iteration for delivery in deliveries] == [2, 2]
        assert deliveries[0].message_id != deliveries[1].message_id
        await inbox.confirm(deliveries=deliveries)
        assert inbox.has_forced() is False
        assert await inbox.take(iteration=3) == []

    async def test_sender_name_defaults_to_the_operator(self) -> None:
        """Messages without an explicit sender label come from the operator."""
        inbox: MemoryBoundaryInbox = MemoryBoundaryInbox()
        inbox.enqueue(text="keep going")
        deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
        assert deliveries[0].sender_name == "you"

    @pytest.mark.parametrize("sender_name", ["orchestrator wf-12", "telegram: sid"])
    async def test_non_operator_senders_carry_their_label(self, sender_name: str) -> None:
        """A forced row from another sender keeps its label for the transcript."""
        inbox: MemoryBoundaryInbox = MemoryBoundaryInbox()
        inbox.enqueue(text="hello", sender_name=sender_name)
        deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
        assert deliveries[0].sender_name == sender_name
