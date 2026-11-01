"""The session/agent delivery seam (feature 96, sub-spec A.1).

This module is the narrow seam between session-owned claims and
agent-owned context. The agent requests a safe delivery without knowing
SQLite, queue implementation or UI details; the session keeps one
logical cursor across provider retries and agent rebuilds.

Delivery rules from the A.1 contract:

- ``BoundaryDeliveryDAO`` is the only agent-facing return shape; empty
  and note-only results are valid.
- The draft permits one instruction plus at most one note per boundary,
  not unlimited draining.
- A repeated boundary returns the same cached selection, even when
  empty; every populated slot has its canonical history event.
- The urgency snapshot/wait methods are consumed by A.2; defining them
  here does not implement expedited interruption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    BoundaryDeliveryDAO,
    MessageDeliveryDAO,
)

__all__ = ["MessageRunState", "AgentMessageSource"]


@dataclass
class MessageRunState:
    """Session-owned logical run cursor borrowed by exactly one agent execution.

    The session creates this once per logical run; retries borrow the
    same cursor and cached boundary selection.
    """

    run_id: str
    boundary_index: int = 0
    delivery: Optional[BoundaryDeliveryDAO] = None
    applied_message_ids: frozenset[str] = field(default_factory=frozenset)


class AgentMessageSource(Protocol):
    """Supply one durable input at an agent-confirmed safe boundary.

    Exposes session-owned claims without giving the agent storage
    ownership. Implemented by ``SloAgentSession``.
    """

    async def take_one(self, *, boundary: BoundaryDAO) -> BoundaryDeliveryDAO:
        """Return the prepared selection for this logical boundary.

        WHAT: Freeze at most one note and one instruction; retries reuse
            even an empty result.
        WHO: ``SloAgent._react_loop`` calls the session-implemented port.
        WHEN: At a safe boundary before the next provider request.
        DATA FLOW: Queue claims become journaled history events delivered
            to the agent.
        LIFETIME: The selection belongs to MessageRunState until safe
            boundary advancement.

        Args:
            boundary (BoundaryDAO): Stable logical run ID and boundary index.

        Returns:
            BoundaryDeliveryDAO: Prepared slots; empty and note-only
                selections are valid.

        Raises:
            MessageStoreError: Claim or application preparation is
                uncertain; stop reasoning.
        """
        ...

    async def commit_applied(self, *, delivery: MessageDeliveryDAO) -> None:
        """Acknowledge the agent's context append; never requeue on failure.

        Args:
            delivery (MessageDeliveryDAO): The slot whose event the agent
                inserted into live context.

        Raises:
            MessageStoreError: The acknowledgement cannot be confirmed.
        """
        ...

    def urgent_high_water(self) -> int:
        """Read highest eligible urgent sequence on the owner loop, or zero.

        Returns:
            int: Maximum eligible urgent sequence; zero when none exists.
        """
        ...

    def yield_is_requested(self, *, after_sequence: int) -> bool:
        """Report eligible urgency newer than the boundary snapshot.

        Args:
            after_sequence (int): The boundary's urgent high-water snapshot.

        Returns:
            bool: True when newer eligible urgency exists.
        """
        ...

    async def wait_for_yield(self, *, after_sequence: int) -> None:
        """Wait for newer urgency; cancellation removes only this waiter.

        Args:
            after_sequence (int): The boundary's urgent high-water snapshot.
        """
        ...

    async def has_pending_input(self) -> bool:
        """Query eligible inputs without claiming them at the continuation gate.

        Returns:
            bool: True when eligible input exists for a later boundary.
        """
        ...
