"""Response-scoped portable result acceptance, independent of host message formats."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional, Self

from .sdk.dao import (
    ClaudeInteractionBindingDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultSubmissionDAO,
)
from .sdk.events import ClaudeResponseCompletedDAO
from .sdk.exceptions import ClaudeBridgeError


class ToolCallResponseAdapter:
    """Bind one complete result set to one response and join its local SDK acceptance.

    The bridge owns this adapter; the receiver is borrowed. No tools or history
    are executed here. Accepted submissions survive reset, including failed or
    uncertain sends, so neither cancellation nor reset authorizes replay.
    """

    def __init__(
        self,
        *,
        binding: ClaudeInteractionBindingDAO,
        expected: ClaudeResponseCompletedDAO,
        receiver: Callable[[ClaudeToolResultSubmissionDAO], Awaitable[None]],
    ) -> None:
        """Store a validated response association without starting delivery.

        Args:
            binding: Session, invocation and version fixed by registration.
            expected: Completed native response whose exact calls must be answered.
            receiver: Borrowed local SDK submission operation; never closed here.
        """
        self._binding: ClaudeInteractionBindingDAO = binding
        self._response_id: str = expected.response_id
        self._call_ids: tuple[str, ...] = tuple(call.tool_call_id for call in expected.tool_calls)
        self._receiver: Callable[[ClaudeToolResultSubmissionDAO], Awaitable[None]] = receiver
        self._submission: Optional[ClaudeToolResultSubmissionDAO] = None
        self._delivery: Optional[asyncio.Task[None]] = None
        self._closed = False

    @classmethod
    def register(
        cls,
        *,
        binding: ClaudeInteractionBindingDAO,
        expected: ClaudeResponseCompletedDAO,
        receiver: Callable[[ClaudeToolResultSubmissionDAO], Awaitable[None]],
    ) -> Self:
        """Validate the response binding before exposing an inert result owner.

        Args:
            binding: Immutable host invocation association and binding version.
            expected: Complete tool-call boundary for this registration.
            receiver: Async receiver of a portable whole-result submission.

        Returns:
            Self: Response-scoped acceptance owner, without background work.

        Raises:
            ValueError: Response does not belong to the binding or repeats call IDs.
        """
        if (
            expected.session_id != binding.session_id
            or expected.invocation_id != binding.invocation_id
            or expected.stop_reason != "tool_calls"
        ):
            raise ValueError("Claude tool response does not match its interaction binding.")
        call_ids = tuple(call.tool_call_id for call in expected.tool_calls)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("Claude tool response repeats a call ID.")
        return cls(binding=binding, expected=expected, receiver=receiver)

    async def handle(self, *, event: ClaudeToolResultSubmissionDAO) -> None:
        """Reserve a complete matching set once, then await local SDK acceptance.

        The bridge calls this after translating every terminal host block. Exact
        repeats join the original delivery; conflicts and stale bindings never send.
        Caller cancellation leaves the owned delivery joinable by reset/close.

        Args:
            event: Portable results for the registered invocation and response.

        Raises:
            RuntimeError: Registration has been closed.
            ValueError: Binding, unknown/duplicate IDs or previously reserved results differ.
            ClaudeBridgeError: A missing subset is correctable without delivery.
            Exception: The receiver failed; that same failed delivery remains retained.
        """
        if self._closed:
            raise RuntimeError("Claude tool result adapter is closed.")
        submission = self._build_ordered_submission(event=event)
        if self._submission is not None and self._submission != submission:
            raise ValueError("Claude tool result submission conflicts with accepted results.")
        if self._delivery is None:
            self._submission = submission
            self._delivery = asyncio.create_task(coro=self._submit_results(submission=submission))
        await asyncio.shield(self._delivery)

    def _build_ordered_submission(
        self, *, event: ClaudeToolResultSubmissionDAO
    ) -> ClaudeToolResultSubmissionDAO:
        """Reject stale/incomplete sets and canonicalize valid arrival order.

        Args:
            event: Candidate portable result submission.

        Returns:
            ClaudeToolResultSubmissionDAO: Results ordered by the native call set.

        Raises:
            ValueError: Invocation, response or unknown/duplicate IDs do not match.
            ClaudeBridgeError: Missing results leave the complete set unreserved.
        """
        batch = event.tool_result_batch
        if event.invocation_id != self._binding.invocation_id or batch.response_id != self._response_id:
            raise ValueError("Claude tool result binding changed.")
        by_call_id = {result.tool_call_id: result for result in batch.results}
        if len(by_call_id) != len(batch.results) or not set(by_call_id).issubset(self._call_ids):
            raise ValueError("Claude tool result set contains unknown or duplicate IDs.")
        if set(by_call_id) != set(self._call_ids):
            raise ClaudeBridgeError(
                code="tool_result_mismatch", safe_message="Expected the complete Claude tool result set."
            )
        return ClaudeToolResultSubmissionDAO(
            invocation_id=self._binding.invocation_id,
            tool_result_batch=ClaudeToolResultBatchDAO(
                response_id=self._response_id,
                results=tuple(by_call_id[call_id] for call_id in self._call_ids),
            ),
        )

    async def _submit_results(self, *, submission: ClaudeToolResultSubmissionDAO) -> None:
        """Deliver the reserved portable batch in one owned task.

        Args:
            submission: Canonical complete result set retained before this task starts.
        """
        await self._receiver(submission)

    async def reset(self) -> None:
        """Join admitted delivery without discarding accepted-result protection.

        This adapter has no transient translation buffer. The bridge retires each
        response registration before registering another, never rebinds it.
        Receiver failure propagates and does not authorize resubmission.
        """
        if self._delivery is not None:
            await asyncio.shield(self._delivery)

    async def close(self) -> None:
        """Seal new submissions and join admitted delivery, not the borrowed SDK.

        Repeated or cancelled close callers join the same retained delivery.
        Delivery errors belong to handle/reset, not cleanup: a settled failed
        send has no live resources and must not permanently block retirement.
        """
        self._closed = True
        if self._delivery is None:
            return
        joined = asyncio.gather(self._delivery, return_exceptions=True)
        cancelled = False
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
