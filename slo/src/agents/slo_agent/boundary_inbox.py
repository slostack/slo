"""The boundary-inbox port and its in-memory adapter (108.2 §5).

``SloAgent`` consumes a ``BoundaryInbox`` at each safe boundary of its ReAct
loop: forced messages take here, enter the model context, and are confirmed
after the history record is written. ``ChannelBoundaryInbox``
(``channel_delivery/boundary_inbox.py``) adapts the shared channel queue;
``MemoryBoundaryInbox`` serves agents without a channel poller and tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BoundaryDeliveryDAO", "BoundaryInbox", "MemoryBoundaryInbox"]


class BoundaryDeliveryDAO(BaseModel):
    """One channel message being applied at this boundary (108.2 §4)."""

    model_config = ConfigDict(frozen=True)

    message_id: UUID = Field(description="Channel message being applied at this boundary.")
    text: str = Field(description="Message contents added to the model context.")
    sender_name: str = Field(description="Sender label; shown in the transcript when it is not you.")
    iteration: int = Field(description="Agent loop iteration whose boundary applied it.")


@runtime_checkable
class BoundaryInbox(Protocol):
    """Where a run takes forced messages at each safe boundary.

    ``has_forced`` is synchronous and reads the last snapshot so the loop's
    stop decision never awaits; ``take``/``confirm`` are asynchronous.
    """

    def has_forced(self) -> bool:
        """Return whether a forced delivery is pending (non-destructively)."""
        ...

    async def take(self, *, iteration: int) -> list[BoundaryDeliveryDAO]:
        """Take the pending forced deliveries, FIFO.

        Args:
            iteration (int): Agent loop iteration whose boundary takes them.

        Returns:
            list[BoundaryDeliveryDAO]: The taken deliveries, in order.
        """
        ...

    async def confirm(self, *, deliveries: list[BoundaryDeliveryDAO]) -> None:
        """Settle the deliveries after their history record is written.

        Args:
            deliveries (list[BoundaryDeliveryDAO]): The taken deliveries to
                accept; each is settled exactly once.
        """
        ...


class MemoryBoundaryInbox:
    """In-process boundary inbox for agents without a channel poller.

    Every enqueued message is a forced-style delivery: it joins the current
    run at the next boundary (or the first boundary of the next run) and
    revives a run that would otherwise stop — the pre-108.2 ``steer``
    contract, kept for in-process senders and tests.
    """

    def __init__(self) -> None:
        """Start with an empty delivery queue."""
        self._pending: list[BoundaryDeliveryDAO] = []

    def enqueue(self, *, text: str, sender_name: str = "you") -> None:
        """Queue one forced delivery for the next boundary.

        Args:
            text (str): Message contents added to the model context.
            sender_name (str): Sender label shown in the transcript.
        """
        self._pending.append(
            BoundaryDeliveryDAO(
                message_id=uuid4(),
                text=text,
                sender_name=sender_name,
                iteration=0,
            )
        )

    def has_forced(self) -> bool:
        """Return whether any delivery is waiting for a boundary.

        Returns:
            bool: ``True`` while at least one enqueued message is untaken.
        """
        return bool(self._pending)

    async def take(self, *, iteration: int) -> list[BoundaryDeliveryDAO]:
        """Drain every pending delivery in enqueue order.

        Args:
            iteration (int): Agent loop iteration whose boundary takes them.

        Returns:
            list[BoundaryDeliveryDAO]: The drained deliveries, FIFO.
        """
        deliveries: list[BoundaryDeliveryDAO] = self._pending
        self._pending = []
        return [delivery.model_copy(update={"iteration": iteration}) for delivery in deliveries]

    async def confirm(self, *, deliveries: list[BoundaryDeliveryDAO]) -> None:
        """Settle taken deliveries (nothing is persisted; a no-op).

        Args:
            deliveries (list[BoundaryDeliveryDAO): The taken deliveries.
        """
        del deliveries
