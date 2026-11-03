"""Component-owned submission adapter: bounded waits, same-ID lookup, identical retry.

The adapter borrows the client and the outcome receiver. It never closes the
client, stops the session or cancels a session-owned admission task. Completing
``handle`` means the local handoff is registered, never that the recipient
accepted it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Optional, Self

from src.agents.slo_agent.messaging.client import SessionMessagingClient
from src.agents.slo_agent.messaging.dao import MessageErrorDAO, MessageReceiptDAO
from src.tui.components.prompt_input.submission import (
    DraftSubmissionDAO,
    RetrySubmissionDAO,
    SubmissionInput,
    SubmissionOutcomeDAO,
    SubmissionOutcomeReceiver,
)

__all__: list[str] = ["MessageSubmissionAdapter"]

_MAX_WAITING_TASKS: int = 4
_MAX_UNSETTLED_DRAFTS: int = 32


class MessageSubmissionAdapter:
    """Register bounded admission waits and translate outcomes for the component.

    Registration is inert: no tasks start and no loop is captured until the
    first ``handle``. A settled receipt settles its draft; an error leaves the
    draft retryable with its original ID and bytes.
    """

    def __init__(
        self,
        *,
        client: SessionMessagingClient,
        receiver: SubmissionOutcomeReceiver,
    ) -> None:
        """Store borrowed dependencies only; construction never starts work.

        Args:
            client (SessionMessagingClient): Borrowed bound session route.
            receiver (SubmissionOutcomeReceiver): Owning component's outcome delivery.
        """
        self._client: Optional[SessionMessagingClient] = client
        self._receiver: Optional[SubmissionOutcomeReceiver] = receiver
        self._drafts_by_id: dict[str, DraftSubmissionDAO] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._first_wait_failure: Optional[BaseException] = None
        self._closed: bool = False
        self._closing_task: Optional[asyncio.Task[None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def register(cls, *, client: SessionMessagingClient, receiver: SubmissionOutcomeReceiver) -> Self:
        """Return a fresh adapter without tasks, loop capture or submission.

        Args:
            client (SessionMessagingClient): Borrowed bound session route.
            receiver (SubmissionOutcomeReceiver): Owning component's outcome delivery.

        Returns:
            MessageSubmissionAdapter: Inert registered adapter.
        """
        return cls(client=client, receiver=receiver)

    async def handle(self, *, event: SubmissionInput) -> None:
        """Register one bounded admission or retry wait, then return.

        WHAT: Remembers the draft and starts one tracked task; return means the
            local handoff is registered, never that the recipient accepted it.
        WHO: The prompt component calls this from its ordered submission flow.
        WHEN: After capacity reservation, before the clear commit.

        Args:
            event (SubmissionInput): One captured draft or one named retry.

        Raises:
            RuntimeError: The adapter is closed, a foreign loop delivered, or the
                waiting-task invariant broke; the loop pin precedes the closed check.
            TypeError: The input is not a declared submission input.
            LookupError: The retry names an unknown or evicted draft.
        """
        self._pin_first_loop()
        if self._closed:
            raise RuntimeError("MessageSubmissionAdapter is closed")
        if not isinstance(event, (DraftSubmissionDAO, RetrySubmissionDAO)):
            raise TypeError("Unsupported submission input")
        if isinstance(event, DraftSubmissionDAO):
            self._drafts_by_id[event.message_submission.message_id] = event
            self._evict_oldest_unsettled_draft()
            self._start_wait_task(flow=self._submit_flow(draft=event))
            return
        draft: DraftSubmissionDAO | None = self._drafts_by_id.get(event.message_id)
        if draft is None:
            raise LookupError("This draft can no longer be retried here")
        self._start_wait_task(flow=self._retry_flow(draft=draft))

    def _pin_first_loop(self) -> None:
        """Pin the first delivery loop and refuse any foreign loop thereafter.

        Raises:
            RuntimeError: A later call runs on a different event loop.
        """
        running: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = running
            return
        if running is not self._loop:
            raise RuntimeError("MessageSubmissionAdapter requires its first delivery loop")

    def _start_wait_task(self, *, flow: Coroutine[None, None, None]) -> None:
        """Start one tracked wait, enforcing the four-wait admission invariant.

        Args:
            flow (asyncio.Coroutine[None, None, None]): The owned wait coroutine.

        Raises:
            RuntimeError: A fifth concurrent wait would start; the component's
                capacity check is the real gate and this invariant must hold.
        """
        for completed in tuple(self._tasks):
            if completed.done():
                self._observe_completed_wait(completed)
        if len(self._tasks) >= _MAX_WAITING_TASKS:
            raise RuntimeError("MessageSubmissionAdapter admits at most four waiting drafts")
        task: asyncio.Task[None] = asyncio.create_task(coro=flow)
        self._tasks.add(task)
        if task.done():
            self._observe_completed_wait(task)
            return
        task.add_done_callback(self._observe_completed_wait)

    def _observe_completed_wait(self, task: asyncio.Task[None]) -> None:
        """Observe a completed wait before releasing its owned Task reference.

        The loop calls this after delivery. Keep only the first unexpected
        failure, without its delivery traceback, for every later reset/close.
        This bounds failure retention without silently discarding errors.

        Args:
            task (asyncio.Task[None]): Completed admission or retry wait.
        """
        self._tasks.discard(task)
        if task.cancelled():
            return
        failure: Optional[BaseException] = task.exception()
        if failure is not None and self._first_wait_failure is None:
            self._first_wait_failure = failure.with_traceback(None)

    async def _join_submission_waits(self) -> None:
        """Join every captured sibling before reporting the sticky first failure.

        Reset and owned close use this barrier. Completion callbacks may release
        Tasks during the join; the snapshot keeps every sibling joinable until
        it settles. Caller cancellation never cancels admission work.
        """
        tasks: tuple[asyncio.Task[None], ...] = tuple(self._tasks)
        cancelled: bool = False
        try:
            await self._join_wait_tasks(tasks=tasks)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            # The join observed every result; retain its first failure below.
            pass
        for task in tasks:
            self._observe_completed_wait(task)
        if self._first_wait_failure is not None:
            raise self._first_wait_failure.with_traceback(None)
        if cancelled:
            raise asyncio.CancelledError() from None

    def _evict_oldest_unsettled_draft(self) -> None:
        """Bound retained snapshots; a retry for an evicted ID refuses safely."""
        while len(self._drafts_by_id) > _MAX_UNSETTLED_DRAFTS:
            oldest: str = next(iter(self._drafts_by_id))
            del self._drafts_by_id[oldest]

    async def _submit_flow(self, *, draft: DraftSubmissionDAO) -> None:
        """Submit once, look up one uncertain outcome exactly once, then deliver.

        Args:
            draft (DraftSubmissionDAO): The exact snapshot admitted by the component.
        """
        assert self._client is not None
        message_id: str = draft.message_submission.message_id
        outcome: MessageReceiptDAO | MessageErrorDAO = await self._client.submit(
            submission=draft.message_submission
        )
        if isinstance(outcome, MessageErrorDAO) and outcome.code == "unknown_outcome":
            outcome = await self._client.get_receipt(message_id=message_id)
        await self._deliver(draft=draft, outcome=outcome)

    async def _retry_flow(self, *, draft: DraftSubmissionDAO) -> None:
        """Look up the same ID first; only a verified absence resubmits identical bytes.

        Args:
            draft (DraftSubmissionDAO): The retained snapshot being retried.
        """
        assert self._client is not None
        message_id: str = draft.message_submission.message_id
        receipt: MessageReceiptDAO | MessageErrorDAO = await self._client.get_receipt(message_id=message_id)
        if isinstance(receipt, MessageReceiptDAO) or receipt.code != "not_found":
            await self._deliver(draft=draft, outcome=receipt)
            return
        await self._submit_flow(draft=draft)

    async def _deliver(
        self, *, draft: DraftSubmissionDAO, outcome: MessageReceiptDAO | MessageErrorDAO
    ) -> None:
        """Settle remembered state for a receipt, then hand the answer to the receiver.

        Args:
            draft (DraftSubmissionDAO): The snapshot this outcome answers.
            outcome (MessageReceiptDAO | MessageErrorDAO): Validated recipient answer.
        """
        assert self._receiver is not None
        if isinstance(outcome, MessageReceiptDAO):
            self._drafts_by_id.pop(draft.message_submission.message_id, None)
        await self._receiver.handle(command=SubmissionOutcomeDAO(draft_submission=draft, outcome=outcome))

    async def reset(self) -> None:
        """Join every outstanding wait, keeping client, receiver and retained drafts.

        Caller cancellation still joins the shared waits, then propagates. The
        first unexpected task exception remains reportable on every reset/close
        after all joins settle; successful and failed Tasks are released on completion.
        """
        await self._join_submission_waits()

    async def close(self) -> None:
        """Seal admission first, join waits, then release borrowed references last.

        One shared barrier owns the actual close; every concurrent caller joins
        that same operation, so a second call can never return before the first
        finishes. Caller cancellation still joins, then propagates. The
        borrowed client is never closed here. The first unexpected task
        exception re-raises after all joins settle.
        """
        if self._closing_task is None:
            self._closed = True
            self._closing_task = asyncio.create_task(coro=self._close_owned())
        await self._join_wait_tasks(tasks=(self._closing_task,))

    async def _close_owned(self) -> None:
        """Perform the single actual close: join waits, then release references last."""
        try:
            await self._join_submission_waits()
        finally:
            self._drafts_by_id.clear()
            self._client = None
            self._receiver = None

    async def _join_wait_tasks(self, *, tasks: tuple[asyncio.Task[None], ...]) -> None:
        """Shielded join of the given waits, observing every owned result.

        Every task is joined to completion even when a sibling or the caller
        fails; caller cancellation propagates only after all joins settle.

        Args:
            tasks (tuple[asyncio.Task[None], ...]): Owned waits to join in order.
        """
        cancelled: bool = False
        first_failure: Optional[BaseException] = None
        for task in tasks:
            while not task.done():
                try:
                    await asyncio.shield(arg=task)
                except asyncio.CancelledError:
                    cancelled = True
                except BaseException:
                    # Shield forwards the owned task's failure immediately. Observe
                    # it below, but keep joining siblings before releasing borrowers.
                    break
            if task.cancelled():
                continue
            failure: Optional[BaseException] = task.exception()
            if failure is not None and first_failure is None:
                first_failure = failure
        if first_failure is not None:
            raise first_failure.with_traceback(None)
        if cancelled:
            raise asyncio.CancelledError() from None
