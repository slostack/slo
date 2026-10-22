"""Session message queue: ordering and wake-up rules (feature 96, sub-spec A.1).

``SessionMessageQueue`` is the traffic rulebook, not another agent. It
never calls the model, runs tools or renders anything.

Queue contract rules:

- One ``asyncio.Lock`` plus work/yield Events on the session's loop;
  queue methods serialize store mutations and signal refresh and never
  await model/tools/network/subscribers. Bounded offloaded store
  transactions are permitted under the mutex.
- Session shutdown seals through this same mutex: an admission either
  commits before seal or rejects with ``completing``.
- Work is signaled only after a successful commit; urgency is observed
  during active execution through the A.2 contract.
- Lock order for application: execution lock → history barrier → queue
  mutex. Admission takes only the queue mutex. No queue mutex is ever
  acquired while waiting for the execution lock.
- Notes use a separate bounded lane within the same component and wake
  the session's maintenance task, not its model scheduler; a
  continuously nonempty note lane cannot starve instructions.

This component is inactive until Change 6 composes it into the session.
Construction allocates loop-local mutex/Condition/Events only.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageDeliveryDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    QueueSummaryDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore

__all__ = ["SessionMessageQueue"]


class SessionMessageQueue:
    """Own serialized admission, selection and signals for one session.

    The session is the only claimant. The bound ``authorize`` callable is
    the session's synchronous registered-authority check: it performs no
    I/O, callback or plugin work, raises
    ``MessageAdmissionError(unauthorized)``, and runs only inside the
    transaction lock.
    """

    def __init__(
        self,
        *,
        store: MessageStore,
        target: MessageAddressDAO,
        authorize: Callable[[MessageSubmissionDAO, MessagePrincipalDAO], None],
    ) -> None:
        """Allocate loop-local mutex/Condition/Events only.

        WHAT: Bind storage, the exact target incarnation and the
            synchronous authority check without starting anything.
        WHO: ``SloAgentSession.start_messaging`` composes this queue.
        WHEN: After the store opens and before admission opens.
        DATA FLOW: Store transactions execute on the store's worker under
            this queue's mutex.
        LIFETIME: Owned by the session; sealed and settled during
            close_messaging.

        Args:
            store (MessageStore): The opened session messaging store.
            target (MessageAddressDAO): Exact session incarnation served.
            authorize (Callable[[MessageSubmissionDAO, MessagePrincipalDAO], None]):
                Synchronous registered-authority recheck used only inside
                the transaction lock.
        """
        ...

    async def admit(
        self,
        *,
        submission: MessageSubmissionDAO,
        principal: MessagePrincipalDAO,
    ) -> MessageReceiptDAO:
        """Commit authorized input before signaling executable work.

        WHAT: Return the original duplicate receipt or one new acceptance.
        WHO: ``SloAgentSession.admit_message`` delegates to this queue.
        WHEN: On submission, including while the agent is running.
        DATA FLOW: Submission and registered principal enter MessageStore
            together in one transaction.
        LIFETIME: The queue mutex spans this bounded transaction, not
            model execution.

        Admission ordering:
            1. Acquire the queue mutex.
            2. Recheck the session-bound authority and whether admission
               is still open.
            3. Call ``MessageStore.admit`` and confirm the transaction.
            4. Refresh work/yield signals while still holding the mutex.
            5. Release the mutex and return the receipt.

        Args:
            submission (MessageSubmissionDAO): Immutable input and retry
                identity.
            principal (MessagePrincipalDAO): Bound identity rechecked
                under the mutex.

        Returns:
            MessageReceiptDAO: Confirmed admission, not a model answer.

        Raises:
            MessageAdmissionError: Admission is sealed, unauthorized,
                invalid, conflicting or full.
            MessageStoreError: The durable commit cannot be confirmed;
                reconcile before reuse.
        """
        ...

    async def take_one(self, *, boundary: BoundaryDAO) -> Optional[MessageDeliveryDAO]:
        """Claim at most one instruction for one boundary under the mutex.

        A second claim for the same ``(run_id, boundary_index)`` is
        refused; the same already-claimed delivery is returned until
        commit, then None on repeat. This internal instruction-only claim
        is not the agent port — ``delivery.AgentMessageSource`` is.
        """
        ...

    async def seal(self) -> None:
        """Seal admission through the queue's serialization point.

        After seal, new admissions reject with ``completing``; committed
        admissions retain their outcomes.
        """
        ...

    async def wait_for_work(self) -> None:
        """Wait until executable input exists or admission seals."""
        ...

    async def wait_for_yield(self, *, after_sequence: int) -> None:
        """Wait under the queue Condition until newer eligible urgency exists.

        The predicate is checked under the Condition and waits for a
        change rather than spinning on an already-set Event. Every
        eligibility change notifies the Condition.

        Args:
            after_sequence (int): The boundary's urgent high-water snapshot.
        """
        ...

    async def summary(self, *, principal: MessagePrincipalDAO) -> QueueSummaryDAO:
        """Return the bounded presentation projection for authorized readers."""
        ...
