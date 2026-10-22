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

from typing import TYPE_CHECKING, Protocol

from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessagePrincipalDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__ = ["SessionMessagingClient", "LocalSessionMessagingClient"]


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
    """Unimplemented local client contract; not wired into session execution.

    Submission and receipt lookup raise NotImplementedError until the session
    integration slice implements this adapter. Construction and close remain
    inert skeletons; neither acquires resources nor claims runtime readiness.
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
        ...

    async def submit(
        self,
        *,
        submission: MessageSubmissionDAO,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Refuse submission until the session integration slice is implemented.

        Args:
            submission (MessageSubmissionDAO): Input reserved for future admission.

        Raises:
            NotImplementedError: Local session admission is not implemented.
        """
        raise NotImplementedError("Local session messaging is not implemented.")

    async def get_receipt(
        self,
        *,
        message_id: str,
    ) -> MessageReceiptDAO | MessageErrorDAO:
        """Refuse receipt lookup until the session integration slice is implemented.

        Args:
            message_id (str): Original ID reserved for future authorized lookup.

        Raises:
            NotImplementedError: Local session receipt lookup is not implemented.
        """
        raise NotImplementedError("Local session messaging is not implemented.")

    async def close(self) -> None:
        """Join tracked calls once, without cancelling admitted execution or session resources."""
        ...
