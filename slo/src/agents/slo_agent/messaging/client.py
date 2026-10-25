"""Bound session messaging clients (feature 96, sub-spec A.1).

The trusted composition root binds identity once at construction;
``submit`` and ``get_receipt`` cannot choose a principal or another
target. Observation attach remains B.2's extension — it is not a second
submit contract.

Client rules from the A.1 contract:

- A constructed principal DAO is not authority; session admission
  rechecks the current registration and lifecycle under the same queue
  mutex as commit. Receipt lookup rechecks authority before existence.
- Target mismatch is ``invalid_message``; matching session with obsolete
  generation is ``stale_generation``; unregistered or revoked principal
  is ``unauthorized``; unstarted session is ``offline``; closing/closed
  session is ``completing``. The client never starts the session.
- Both submit and receipt use ``messaging_limits.admission_seconds``
  (default five seconds). A submit timeout after starting is
  ``unknown_outcome``; the caller queries the original ID, never invents
  a new one. Caller cancellation propagates CancelledError while the
  admission task remains session-tracked.
- ``close`` is idempotent, refuses new calls with ``completing``, joins
  rather than cancels outstanding admission tasks, and never seals,
  aborts or closes the target session.

Typical composition: after explicit ``await session.start_messaging()``,
trusted TUI composition constructs
``LocalSessionMessagingClient(session=session, target=target,
principal=owner_principal)`` and submits through it. The owning
TUI/runner closes the client and then the session in its outer finally;
an attached view closes only its client.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Coroutine, Optional, Protocol

from src.agents.slo_agent.messaging.dao import _require_uuid

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__: list[str] = ["SessionMessagingClient", "LocalSessionMessagingClient"]


class SessionMessagingClient(Protocol):
    """Publish/query one bound route without owning execution or the session lifetime."""

    async def submit(
        self,
        *,
        submission: MessageSubmissionDAO,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Return committed receipt or fixed error; timeout after starting is unknown_outcome.

        Args:
            submission (MessageSubmissionDAO): Immutable input with stable
                retry identity.

        Returns:
            MessageReceiptDAO | MessageErrorDAO: Confirmed admission or a
                fixed safe error. Never a raw exception; caller
                cancellation is the only propagating exception.
        """
        ...

    async def get_receipt(
        self,
        *,
        message_id: str,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Query as the bound principal; absence is not_found, never another sender's data.

        Args:
            message_id (str): The original submission's stable ID.

        Returns:
            MessageReceiptDAO | MessageErrorDAO: The receipt, not_found,
                or unknown_outcome on timeout (which never asserts absence).
        """
        ...

    async def close(self) -> None:
        """Detach this client and join its waits; do not seal, abort or close the target."""
        ...


class LocalSessionMessagingClient:
    """Borrow one session route and registered identity without owning execution.

    Each operation has exactly one task shared with the session. Deadlines and
    caller cancellation stop only the wait; both close paths can still join it.
    """

    def __init__(
        self,
        *,
        session: "SloAgentSession",
        target: MessageAddressDAO,
        principal: MessagePrincipalDAO,
    ) -> None:
        """Bind trusted composition inputs only; no I/O, tasks, grants or implicit startup.

        Args:
            session (SloAgentSession): The already-started target session.
            target (MessageAddressDAO): The exact bound session incarnation.
            principal (MessagePrincipalDAO): The authenticated principal
                from trusted composition (startup registers only the
                embedded owner-human for its own route; B.1's launch/grant
                composition installs others).
        """
        self._session: SloAgentSession = session
        self._target: MessageAddressDAO = target
        self._principal: MessagePrincipalDAO = principal
        self._admission_seconds: float = session.messaging_limits.admission_seconds
        self._calls: set[asyncio.Task[MessageReceiptDAO | MessageErrorDAO]] = set()
        self._closing: bool = False
        self._close_task: Optional[asyncio.Task[None]] = None

    async def submit(
        self,
        *,
        submission: MessageSubmissionDAO,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Delegate once, preserving the original identity when the reply is uncertain.

        Args:
            submission: Immutable caller intent with a stable retry identity.

        Returns:
            Committed receipt or fixed safe error; timeout is unknown_outcome.
        """
        if self._closing:
            return MessageErrorDAO(code="completing", message_id=submission.message_id)
        if submission.target != self._target:
            return MessageErrorDAO(code="invalid_message", message_id=submission.message_id)
        return await self._wait_for_call(
            operation=self._session.admit_message(submission=submission, principal=self._principal),
            message_id=submission.message_id,
        )

    async def get_receipt(
        self,
        *,
        message_id: str,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Query only the bound route; a deadline never establishes absence.

        Args:
            message_id: Original stable ID, not an alternate target or identity.

        Returns:
            Authorized receipt or fixed safe error.
        """
        try:
            _require_uuid(value=message_id, field="message_id")
        except (TypeError, ValueError):
            return MessageErrorDAO(code="invalid_message")
        if self._closing:
            return MessageErrorDAO(code="completing", message_id=message_id)
        return await self._wait_for_call(
            operation=self._session.get_message_receipt(
                message_id=message_id, target=self._target, principal=self._principal
            ),
            message_id=message_id,
        )

    async def _wait_for_call(
        self,
        *,
        operation: Coroutine[None, None, MessageReceiptDAO | MessageErrorDAO],
        message_id: str,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Register with both owners before awaiting; never cancel the operation on timeout."""
        task: asyncio.Task[MessageReceiptDAO | MessageErrorDAO] = self._session.track_messaging_call(
            operation=operation
        )
        self._calls.add(task)
        task.add_done_callback(self._call_settled)
        try:
            async with asyncio.timeout(delay=self._admission_seconds):
                return await asyncio.shield(arg=task)
        except TimeoutError:
            return MessageErrorDAO(code="unknown_outcome", message_id=message_id)
        except Exception:
            return MessageErrorDAO(code="storage_unavailable", message_id=message_id)

    def _call_settled(self, task: asyncio.Task[MessageReceiptDAO | MessageErrorDAO]) -> None:
        """Consume any abandoned failure and drop only a settled client registration."""
        if not task.cancelled():
            task.exception()
        self._calls.discard(task)

    async def close(self) -> None:
        """Join outstanding calls once without a deadline, leaving the session open."""
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(coro=self._join_calls())
        cancelled: bool = False
        while not self._close_task.done():
            try:
                await asyncio.shield(arg=self._close_task)
            except asyncio.CancelledError:
                cancelled = True
        self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError()

    async def _join_calls(self) -> None:
        """Drain the fixed closing set without cancelling any session-owned operation."""
        calls: tuple[asyncio.Task[MessageReceiptDAO | MessageErrorDAO], ...] = tuple(self._calls)
        for call in calls:
            try:
                await asyncio.shield(arg=call)
            except Exception:
                pass  # The safe call boundary reports errors; detach still joins all siblings.
