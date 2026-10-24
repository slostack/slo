"""ChildAbortSubmission — one confirmed child-abort request's tracked lifetime (feature 94 a.4).

Owned by ``DetachedWorkflowAppService``, never by a screen: the progress view
can minimize, reopen or vanish while the request lives on. The record holds the
immutable target and request captured at confirmation plus the service-owned
operation task, and answers the presentation questions about them: which fixed
notice to show, whether a receipt is still awaited, and whether a new request
for the same incarnation may be made. It performs no I/O and starts no timer;
the service feeds it receipts and list rows on the normal observation refresh.

Precedence (a.4): terminal list truth, then a matching receipt, then the
operation's own settling result. ``requested`` is admission only and never
reported as aborted.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_STATUSES,
    ChildAbortOutcomeDAO,
    ChildAbortRequestDAO,
)
from src.tui.workflows.dao import ChildAbortTargetDAO, WorkflowSessionRowDAO

__all__ = [
    "ABORT_CONFIRMATION_WAIT_SECONDS",
    "ABORT_NOT_CONFIRMED_NOTICE",
    "ABORT_SUBMITTING_NOTICE",
    "ChildAbortSubmission",
]

ABORT_CONFIRMATION_WAIT_SECONDS: float = 30.0
"""Monotonic seconds without settlement before the not-confirmed notice appears."""

ABORT_NOT_CONFIRMED_NOTICE: str = (
    "Abort not yet confirmed; inspect progress or use existing workflow controls."
)
"""Fixed notice after the wait; the request is kept, never resubmitted, never called failed."""

ABORT_SUBMITTING_NOTICE: str = "Submitting abort request…"
"""Fixed notice while a detached request is validated and committed (not yet admitted)."""


class ChildAbortSubmission:
    """Track one confirmed request from submission until terminal truth or receipt.

    Invariants: target and request never change; once terminal evidence is seen
    it outranks any receipt or operation result; a request blocks a new one for
    the same incarnation until it settles and its operation task has finished,
    so the service never drops a possibly committing operation it must join.
    """

    def __init__(
        self,
        *,
        target: ChildAbortTargetDAO,
        request: ChildAbortRequestDAO,
        operation: asyncio.Task[ChildAbortOutcomeDAO],
        started_at: float,
        attached: bool,
    ) -> None:
        """Bind the captured identity to its service-owned operation.

        Args:
            target (ChildAbortTargetDAO): Identity captured when confirmation opened.
            request (ChildAbortRequestDAO): Request allocated once for that target.
            operation (asyncio.Task[ChildAbortOutcomeDAO]): Service-owned submission task.
            started_at (float): Monotonic time of the confirmed submission.
            attached (bool): True when the attached pool facade, not the detached
                store, receives the request.
        """
        self._target: ChildAbortTargetDAO = target
        self._request: ChildAbortRequestDAO = request
        self._operation: asyncio.Task[ChildAbortOutcomeDAO] = operation
        self._started_at: float = started_at
        self._attached: bool = attached
        self._receipt: Optional[ChildAbortOutcomeDAO] = None
        self._terminal: Optional[ChildAbortOutcomeDAO] = None

    @property
    def target(self) -> ChildAbortTargetDAO:
        """Return the immutable confirmed target."""
        return self._target

    @property
    def request(self) -> ChildAbortRequestDAO:
        """Return the request retained for this target while it is pending."""
        return self._request

    @property
    def awaits_receipt(self) -> bool:
        """Return whether the request was durably admitted and nothing has settled it."""
        admission: Optional[ChildAbortOutcomeDAO] = self._operation_outcome()
        return self._settled() is None and admission is not None and admission.outcome == "requested"

    @property
    def blocks_new_request(self) -> bool:
        """Return whether a new request for this incarnation must wait.

        Returns:
            bool: True while unsettled or while the operation task still runs;
                terminal list truth alone never releases a running operation.
        """
        return self._settled() is None or not self._operation.done()

    def concerns(self, *, row: WorkflowSessionRowDAO) -> bool:
        """Return whether ``row`` shows this request's exact key and incarnation.

        Args:
            row (WorkflowSessionRowDAO): Current list row.

        Returns:
            bool: True for the same key and execution; a new incarnation never inherits.
        """
        return (row.key, row.execution_id) == (self._target.key, self._target.execution_id)

    def observe_row(self, *, row: WorkflowSessionRowDAO) -> None:
        """Settle from terminal list truth of the same incarnation.

        WHO: The service's observation refresh, for every tracked request.
        WHEN: After each list snapshot, even while no progress view is open.

        Args:
            row (WorkflowSessionRowDAO): Current row for the target's key.
        """
        if (
            row.availability != "available"
            or not self.concerns(row=row)
            or row.status not in TERMINAL_STATUSES
        ):
            return
        self._terminal = ChildAbortOutcomeDAO.for_request(
            request=self._request,
            outcome="aborted" if row.status == "aborted" else "already_terminal",
            terminal_status=row.status,  # type: ignore[arg-type]
        )

    def observe_receipt(self, *, receipt: Optional[ChildAbortOutcomeDAO]) -> None:
        """Retain the first receipt; an absent receipt keeps the request pending.

        Args:
            receipt (Optional[ChildAbortOutcomeDAO]): Store-validated receipt, or None.
        """
        if self._receipt is None:
            self._receipt = receipt

    def notice(self, *, now: float) -> str:
        """Return the fixed notice for the progress view at monotonic time ``now``.

        Args:
            now (float): Current monotonic time from the service's clock.

        Returns:
            str: Settled message; otherwise the not-confirmed notice after the
                wait, else the admission or pending message.
        """
        settled: Optional[ChildAbortOutcomeDAO] = self._settled()
        if settled is not None:
            return settled.safe_message
        if now - self._started_at >= ABORT_CONFIRMATION_WAIT_SECONDS:
            return ABORT_NOT_CONFIRMED_NOTICE
        return self._pending_message()

    async def join(self) -> None:
        """Wait for the operation to finish by itself and retrieve its result.

        WHO: The service's ``close``; a possibly committing write is never
            cancelled, even when the joiner itself is cancelled.
        """
        await asyncio.wait({self._operation})
        if not self._operation.cancelled():
            self._operation.exception()

    def _pending_message(self) -> str:
        """Return the message before settlement and before the wait elapsed.

        Returns:
            str: Admission message, or the attached requested / detached submitting notice.
        """
        admission: Optional[ChildAbortOutcomeDAO] = self._operation_outcome()
        if admission is not None:
            return admission.safe_message
        if self._attached:
            return ChildAbortOutcomeDAO.for_request(request=self._request, outcome="requested").safe_message
        return ABORT_SUBMITTING_NOTICE

    def _settled(self) -> Optional[ChildAbortOutcomeDAO]:
        """Return the settling outcome by precedence: terminal, receipt, operation.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Settled outcome, or None while pending.
        """
        if self._terminal is not None or self._receipt is not None:
            return self._terminal or self._receipt
        admission: Optional[ChildAbortOutcomeDAO] = self._operation_outcome()
        return None if admission is None or admission.outcome == "requested" else admission

    def _operation_outcome(self) -> Optional[ChildAbortOutcomeDAO]:
        """Return the finished operation's outcome; a failed one is unresolved.

        Returns:
            Optional[ChildAbortOutcomeDAO]: Outcome, or None while the task runs.
        """
        if not self._operation.done():
            return None
        if self._operation.cancelled() or self._operation.exception() is not None:
            return ChildAbortOutcomeDAO.for_request(request=self._request, outcome="unresolved")
        return self._operation.result()
