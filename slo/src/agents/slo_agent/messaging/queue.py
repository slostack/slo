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

import asyncio
from typing import Awaitable, Callable, Optional, TypeVar

from pydantic import Field

from src.agents.slo_agent.messaging.dao import (
    BoundaryDAO,
    MessageAddressDAO,
    MessageAdmissionError,
    MessageErrorDAO,
    MessageDeliveryDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    QueueSummaryDAO,
    MessageDAO,
    RecoveryTransferDAO,
    RecoveryOutcomeDAO,
    MessageStoreError,
    QueueStateDAO,
)
from src.agents.slo_agent.messaging.store import MessageStore

__all__ = ["SessionMessageQueue", "BoundaryClaimsDAO"]

_T = TypeVar("_T")


class BoundaryClaimsDAO(MessageDAO):
    """Raw serialized selection, not history application or a frozen empty delivery."""

    boundary: BoundaryDAO = Field(description="Session-owned identity of this selection opportunity.")
    urgent_high_water: int = Field(description="Highest eligible urgent sequence before either claim.")
    note: Optional[MessageDeliveryDAO] = Field(default=None, description="At most one raw note claim.")
    instruction: Optional[MessageDeliveryDAO] = Field(
        default=None, description="At most one raw instruction claim."
    )


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
        authorize_read: Callable[[MessagePrincipalDAO], None],
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
            authorize_read (Callable[[MessagePrincipalDAO], None]): Registered
                read authority, checked under the same mutex without I/O.
        """
        self._store: MessageStore = store
        self._target: MessageAddressDAO = target
        self._authorize: Callable[[MessageSubmissionDAO, MessagePrincipalDAO], None] = authorize
        self._authorize_read: Callable[[MessagePrincipalDAO], None] = authorize_read
        self._mutex: asyncio.Lock = asyncio.Lock()
        self._changed: asyncio.Condition = asyncio.Condition(lock=self._mutex)
        self._sealed: bool = False
        self._storage_failed: bool = False
        self._work: asyncio.Event = asyncio.Event()
        self._yield: asyncio.Event = asyncio.Event()
        self._notes: asyncio.Event = asyncio.Event()
        self._urgent_high_water: int = 0

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
        async with self._mutex:
            # Callable's declared parameters are positional, as in the canonical contract.
            self._authorize(submission, principal)
            self._require_accepting(submission=submission)
            return await self._settle_mutation_locked(
                operation=self._store.admit(submission=submission, principal=principal)
            )

    async def _settle_mutation_locked(self, *, operation: Awaitable[_T]) -> _T:
        """Join mutation and publication before releasing serialization, even on cancellation.

        Caller cancellation is propagated only after the owned task settles. A
        committed admission is never represented as a rejection; callers query
        the original identity after cancellation or storage uncertainty.
        """
        return await self._settle_operation_locked(
            operation=self._mutate_and_publish_locked(operation=operation)
        )

    async def _settle_operation_locked(self, *, operation: Awaitable[_T]) -> _T:
        """Join storage outcome publication before propagating caller cancellation.

        The caller holds the mutex until this returns or raises. Shield the
        complete queue-owned operation, not just its store worker, so a failed
        read still latches failure and wakes siblings before cancellation wins.
        """
        task: asyncio.Task[_T] = asyncio.create_task(self._observe_storage_locked(operation=operation))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError()
        return task.result()

    async def _observe_storage_locked(self, *, operation: Awaitable[_T]) -> _T:
        """Publish storage failure for reads and mutations within the owned task."""
        try:
            return await operation
        except MessageStoreError:
            self._storage_failed = True
            self._changed.notify_all()
            raise

    async def _mutate_and_publish_locked(self, *, operation: Awaitable[_T]) -> _T:
        """Own the complete mutation-to-notification lifetime under the caller's lock."""
        result: _T = await operation
        await self._refresh_signals_locked()
        return result

    def _require_accepting(self, *, submission: MessageSubmissionDAO) -> None:
        """Refuse a stale destination or sealed admission before any store write."""
        if self._storage_failed:
            raise MessageStoreError()
        # Match the store's logical-route rule; generation is a separate error.
        if (submission.target.kind, submission.target.session_id, submission.target.channel_id) != (
            self._target.kind,
            self._target.session_id,
            self._target.channel_id,
        ):
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
            )
        if submission.target.generation != self._target.generation:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="stale_generation", message_id=submission.message_id)
            )
        if self._sealed:
            raise MessageAdmissionError(
                error=MessageErrorDAO(code="completing", message_id=submission.message_id)
            )

    async def _refresh_signals_locked(self) -> None:
        """Publish committed eligibility while holding the single queue mutex."""
        self._require_storage_healthy()
        state: QueueStateDAO = await self._store.read_queue_state()
        self._urgent_high_water = state.urgent_high_water
        self._set_signal(signal=self._work, eligible=state.eligible_inputs > 0)
        self._set_signal(signal=self._yield, eligible=state.urgent_high_water > 0)
        self._set_signal(signal=self._notes, eligible=state.eligible_notes > 0)
        self._changed.notify_all()

    def _require_storage_healthy(self) -> None:
        """Refuse reuse after uncertain storage until session-owned reconciliation."""
        if self._storage_failed:
            raise MessageStoreError()

    @staticmethod
    def _set_signal(*, signal: asyncio.Event, eligible: bool) -> None:
        """Update a loop-local notification only within queue serialization."""
        if eligible:
            signal.set()
            return
        signal.clear()

    async def take_one(self, *, boundary: BoundaryDAO) -> Optional[MessageDeliveryDAO]:
        """Claim at most one instruction for one boundary under the mutex.

        The same already-claimed delivery is returned until application,
        then None on repeat. No second message occupies that boundary.
        This internal instruction-only claim is not the agent port —
        ``delivery.AgentMessageSource`` is.

        Args:
            boundary (BoundaryDAO): Session-owned stable claim identity.

        Returns:
            Optional[MessageDeliveryDAO]: Raw instruction claim, or None.

        Raises:
            MessageStoreError: Claim or publication failed; reconcile before reuse.
            asyncio.CancelledError: Caller cancelled; mutation and publication were joined.
        """
        async with self._mutex:
            self._require_storage_healthy()
            return await self._settle_mutation_locked(operation=self._store.claim_one(boundary=boundary))

    async def take_note(self, *, boundary: BoundaryDAO) -> Optional[MessageDeliveryDAO]:
        """Claim one note for idle maintenance without requesting model execution.

        Args:
            boundary (BoundaryDAO): Maintenance-owned stable claim identity.

        Returns:
            Optional[MessageDeliveryDAO]: One raw claim, or None; no history is fabricated.

        Raises:
            MessageStoreError: Claim or signal publication failed.
        """
        async with self._mutex:
            self._require_storage_healthy()
            return await self._settle_mutation_locked(operation=self._store.claim_note(boundary=boundary))

    async def select_boundary(self, *, boundary: BoundaryDAO) -> BoundaryClaimsDAO:
        """Snapshot urgency and claim at most one note and instruction atomically to callers.

        Args:
            boundary (BoundaryDAO): Session-owned stable boundary identity.

        Returns:
            BoundaryClaimsDAO: Preclaim urgency and raw claims, without history events.

        Raises:
            MessageStoreError: Either transaction or publication failed. The two
                store transactions are not a single durable transaction; reconcile
                partial claims before reuse. Cancellation joins both and publication.
        """
        async with self._mutex:
            self._require_storage_healthy()
            return await self._settle_mutation_locked(
                operation=self._select_boundary_locked(boundary=boundary)
            )

    async def _select_boundary_locked(self, *, boundary: BoundaryDAO) -> BoundaryClaimsDAO:
        """Keep preclaim urgency and both lane selections inside one owned operation."""
        await self._refresh_signals_locked()
        urgent_high_water: int = self._urgent_high_water
        note: Optional[MessageDeliveryDAO] = await self._store.claim_note(boundary=boundary)
        instruction: Optional[MessageDeliveryDAO] = await self._store.claim_one(boundary=boundary)
        return BoundaryClaimsDAO(
            boundary=boundary, urgent_high_water=urgent_high_water, note=note, instruction=instruction
        )

    async def retain_pending(self) -> None:
        """Retain accepted work and publish ineligibility before session shutdown.

        Raises:
            MessageStoreError: Mutation/publication failed; reconciliation is required.
        """
        async with self._mutex:
            self._require_storage_healthy()
            await self._settle_mutation_locked(operation=self._store.retain_pending())

    async def cancel_retained(self, *, message_ids: tuple[str, ...]) -> None:
        """Cancel a session-confirmed retained selection and refresh signals.

        Args:
            message_ids (tuple[str, ...]): Exact owner-confirmed selection.

        Raises:
            MessageAdmissionError: Selection changed before commit.
            MessageStoreError: Mutation/publication failed.
        """
        async with self._mutex:
            self._require_storage_healthy()
            await self._settle_mutation_locked(operation=self._store.cancel_retained(message_ids=message_ids))

    async def recover(
        self, *, transfer: RecoveryTransferDAO, principal: MessagePrincipalDAO
    ) -> RecoveryOutcomeDAO:
        """Publish eligibility from a session-verified, human-confirmed recovery.

        Args:
            transfer (RecoveryTransferDAO): Verified transfer from the session recovery owner.
            principal (MessagePrincipalDAO): Registered confirming human.

        Returns:
            RecoveryOutcomeDAO: Durable transfer and original receipt.

        Raises:
            MessageAdmissionError: Authority, lifecycle or transfer refused.
            MessageStoreError: Mutation/publication failed.
        """
        async with self._mutex:
            self._authorize_read(principal)
            self._require_storage_healthy()
            if self._sealed:
                raise MessageAdmissionError(error=MessageErrorDAO(code="completing"))
            return await self._settle_mutation_locked(
                operation=self._store.recover(transfer=transfer, principal=principal)
            )

    async def set_lifecycle(self, *, accepting: bool) -> None:
        """Publish durable lifecycle eligibility after session-owned settlement/retention.

        This is not the admission-only memory seal. Startup reconciliation stays
        outside this queue before publication; history application stays outside
        its mutex. Reopening durable storage never reopens a memory-sealed queue.

        Args:
            accepting (bool): Persisted lifecycle eligibility selected by the session.

        Raises:
            MessageStoreError: Mutation/publication failed.
        """
        async with self._mutex:
            self._require_storage_healthy()
            await self._settle_mutation_locked(operation=self._store.set_lifecycle(accepting=accepting))

    async def wait_for_notes(self) -> None:
        """Wait for claimable notes or seal; cancellation removes only this waiter.

        Raises:
            MessageStoreError: Eligibility could not be read safely.
        """
        async with self._changed:
            self._require_storage_healthy()
            if self._sealed:
                return
            await self._settle_operation_locked(operation=self._refresh_signals_locked())
            await self._changed.wait_for(lambda: self._sealed or self._storage_failed or self._notes.is_set())
            if self._storage_failed:
                raise MessageStoreError()

    async def seal(self) -> None:
        """Seal admission through the queue's serialization point.

        After seal, new admissions reject with ``completing``; committed
        admissions retain their outcomes.
        """
        async with self._mutex:
            self._sealed = True
            self._changed.notify_all()

    async def wait_for_work(self) -> None:
        """Wait until executable input exists or admission seals.

        Raises:
            MessageStoreError: Storage failed, including another operation's failure.
            asyncio.CancelledError: Only this waiting consumer was cancelled.
        """
        async with self._changed:
            self._require_storage_healthy()
            if self._sealed:
                return
            await self._settle_operation_locked(operation=self._refresh_signals_locked())
            await self._changed.wait_for(lambda: self._sealed or self._storage_failed or self._work.is_set())
            if self._storage_failed:
                raise MessageStoreError()

    async def wait_for_yield(self, *, after_sequence: int) -> None:
        """Wait under the queue Condition until newer eligible urgency exists.

        The predicate is checked under the Condition and waits for a
        change rather than spinning on an already-set Event. Every
        eligibility change notifies the Condition.

        Args:
            after_sequence (int): The boundary's urgent high-water snapshot.

        Raises:
            MessageStoreError: Storage failed, including another operation's failure.
            asyncio.CancelledError: Only this waiting consumer was cancelled.
        """
        async with self._changed:
            self._require_storage_healthy()
            if self._sealed:
                return
            await self._settle_operation_locked(operation=self._refresh_signals_locked())
            await self._changed.wait_for(
                lambda: self._sealed or self._storage_failed or self._urgent_high_water > after_sequence
            )
            if self._storage_failed:
                raise MessageStoreError()

    async def summary(self, *, principal: MessagePrincipalDAO) -> QueueSummaryDAO:
        """Return one authorized reader's bounded preview, including after admission seal.

        Args:
            principal (MessagePrincipalDAO): Identity rechecked by bound read policy.

        Returns:
            QueueSummaryDAO: Total pending inputs and at most one same-principal text.

        Raises:
            MessageAdmissionError: Reader registration is absent or revoked.
            MessageStoreError: Storage is closed, failed or unreadable.
        """
        async with self._mutex:
            self._authorize_read(principal)
            self._require_storage_healthy()
            return await self._settle_operation_locked(
                operation=self._store.read_summary(principal=principal)
            )
