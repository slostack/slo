"""`DeliverScheduleInvocationAppService` — decide, send or skip, then mark the outcome."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Optional, Protocol
from uuid import UUID, uuid4

from src.channels.dao import ChannelMessageDAO
from src.channels.errors import RecipientClosedError, UnknownParticipantError
from src.schedules.channel_delivery import ScheduleChannelSender
from src.schedules.dao import DeliveryDecisionDAO, ScheduleInvocationDAO
from src.schedules.fresh_run import FreshRunResultDAO
from src.schedules.database import ScheduleDatabase, ScheduleTransaction
from src.schedules.exceptions import InvocationNotPendingError, InvocationNotRunningError
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.service import ScheduleService

__all__ = ["DeliverScheduleInvocationAppService", "FreshRunStarter"]

_RUN_TIMEOUT_SECONDS: int = 3600


class FreshRunStarter(Protocol):
    """Consumer-side seam: anything that can start one headless fresh run.

    ``FreshRunInvoker`` is the production implementation; tests inject a
    scripted runner through the same constructor parameter.
    """

    async def start(
        self,
        *,
        prompt: str,
        cwd: str | None,
        model: str | None,
        session_id: str,
    ) -> FreshRunResultDAO:
        """Start one headless fresh run and wait for it.

        Args:
            prompt (str): The schedule prompt.
            cwd (str | None): The schedule's working directory override.
            model (str | None): The schedule's model override.
            session_id (str): The minted session id for this run.

        Returns:
            FreshRunResultDAO: The run result with the child's exit code.
        """
        ...


class DeliverScheduleInvocationAppService:
    """Runs one invocation's delivery: decide, send or skip, then mark the outcome.

    Deliver reads in one short transaction, sends outside any transaction, then
    marks the status in a second one (111.a.2 §3.2 transaction rule).
    """

    def __init__(
        self,
        *,
        database: ScheduleDatabase,
        schedules: ScheduleService,
        invocations: ScheduleInvocationRepository,
        sender: ScheduleChannelSender,
        fresh_runs: FreshRunStarter,
        now_provider: Callable[[], datetime],
        run_timeout_seconds: int = _RUN_TIMEOUT_SECONDS,
    ) -> None:
        """Bind the collaborators deliver owns.

        Args:
            database (ScheduleDatabase): The schedules database; opens the two
                short transactions of the deliver steps.
            schedules (ScheduleService): The only source of the delivery decision.
            invocations (ScheduleInvocationRepository): The invocation table SQL.
            sender (ScheduleChannelSender): The channel send collaborator.
            fresh_runs (FreshRunStarter): The fresh-run starter for run decisions.
            now_provider (Callable[[], datetime]): Returns the current boundary
                clock instant. Deliver reads it only after a fresh run finishes,
                so ``delivered_at`` records the time the run finished (111.a.3
                §5.3 step 4); the service itself never reads the wall clock.
            run_timeout_seconds (int): Maximum age of a running row before the
                worker start recovery marks it run_failed (D24; default 3600).
        """
        self._database: ScheduleDatabase = database
        self._schedules: ScheduleService = schedules
        self._invocations: ScheduleInvocationRepository = invocations
        self._sender: ScheduleChannelSender = sender
        self._fresh_runs: FreshRunStarter = fresh_runs
        self._now_provider: Callable[[], datetime] = now_provider
        self._run_timeout_seconds: int = run_timeout_seconds

    async def invoke(self, *, invocation_id: UUID, now: datetime) -> ScheduleInvocationDAO:
        """Deliver one invocation, or return its stored row when it is not pending.

        Args:
            invocation_id (UUID): The invocation to deliver.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleInvocationDAO: The final row (delivered, skipped or failed),
                or the stored row when another delivery already finished it.
        """
        async with self._database.transaction() as transaction:
            invocation = await self._invocations.get(invocation_id=invocation_id, transaction=transaction)
        if invocation is None or invocation.status != "pending":
            return _stored_or_missing(invocation_id=invocation_id, invocation=invocation)
        stored: Optional[ChannelMessageDAO] = await self._sender.stored_message(invocation_id=invocation_id)
        if stored is not None:
            return await self._mark_delivered(
                invocation_id=invocation_id,
                schedule_id=invocation.schedule_id,
                now=now,
                # The channel row is the only record of whom the crashed send
                # targeted; an agent conversation carries the recipient session.
                recipient_session_id=str(stored.agent_session_id),
            )
        decision = await self._schedules.decide_delivery(invocation=invocation, now=now)
        if decision.outcome == "skip":
            return await self._mark_skipped(
                invocation_id=invocation_id,
                schedule_id=invocation.schedule_id,
                skip_reason=decision.skip_reason,
                now=now,
            )
        if decision.outcome == "fail":
            failure_reason = decision.failure_reason
            assert failure_reason is not None, "fail decisions carry a reason"
            return await self._mark_failed(
                invocation_id=invocation_id,
                schedule_id=invocation.schedule_id,
                failure_reason=failure_reason,
                now=now,
            )
        if decision.outcome == "run":
            return await self._start_fresh_run(
                invocation_id=invocation_id,
                decision=decision,
                now=now,
            )
        return await self._send(
            invocation_id=invocation_id,
            decision=decision,
            now=now,
        )

    async def recover_stale_running(self, *, now: datetime) -> None:
        """Mark each running row older than the run timeout run_failed (D24).

        Called at worker start. The occurrence is lost; the row is never re-run.
        The recovery reason and the one-shot end commit with the status write.

        Args:
            now (datetime): The boundary clock instant supplied by the caller.
        """
        async with self._database.transaction() as transaction:
            stale_schedule_ids: list[UUID] = await self._invocations.mark_stale_running_failed(
                older_than=now - timedelta(seconds=self._run_timeout_seconds),
                failure_reason="run_timeout",
                recovered_at=now,
                transaction=transaction,
            )
            for stale_schedule_id in stale_schedule_ids:
                await self._schedules.complete_occurrence(
                    schedule_id=stale_schedule_id,
                    now=now,
                    transaction=transaction,
                )

    async def _mark_delivered(
        self,
        *,
        invocation_id: UUID,
        schedule_id: UUID,
        now: datetime,
        recipient_session_id: Optional[str],
    ) -> ScheduleInvocationDAO:
        """Mark one invocation delivered and return the stored row.

        The delivered write, the recipient and the one-shot end commit together
        (111.a.4 §5.4; the recipient contract is 111.a.2 §4/A17).

        Args:
            invocation_id (UUID): The invocation to finalise.
            schedule_id (UUID): The schedule that owns the invocation.
            now (datetime): The delivery instant.
            recipient_session_id (Optional[str]): The agent session that
                received the message, when it is known.

        Returns:
            ScheduleInvocationDAO: The stored row.

        Raises:
            InvocationNotPendingError: When another delivery already finalised it
                (the caller replay case then returns the stored row).
        """
        async with self._database.transaction() as transaction:
            try:
                await self._invocations.mark_delivered(
                    invocation_id=invocation_id,
                    channel_message_id=invocation_id,
                    delivered_at=now,
                    recipient_session_id=recipient_session_id,
                    transaction=transaction,
                )
            except InvocationNotPendingError:
                return await self._get_row(invocation_id=invocation_id, transaction=transaction)
            await self._schedules.complete_occurrence(
                schedule_id=schedule_id,
                now=now,
                transaction=transaction,
            )
        return await self._get_row(invocation_id=invocation_id)

    async def _mark_skipped(
        self,
        *,
        invocation_id: UUID,
        schedule_id: UUID,
        skip_reason: str | None,
        now: datetime,
    ) -> ScheduleInvocationDAO:
        """Mark one invocation skipped and return the stored row.

        A misfire skip ends the one-shot occurrence in the same commit (111.a.4
        §5.3 step 2.2); the disabled and deleted skips do not (the schedule is
        already off).

        Args:
            invocation_id (UUID): The invocation to finalise.
            schedule_id (UUID): The schedule that owns the invocation.
            skip_reason (str | None): The skip reason from the decision.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleInvocationDAO: The stored row.
        """
        async with self._database.transaction() as transaction:
            try:
                await self._invocations.mark_skipped(
                    invocation_id=invocation_id,
                    skip_reason=skip_reason,  # type: ignore[arg-type]
                    transaction=transaction,
                )
            except InvocationNotPendingError:
                return await self._get_row(invocation_id=invocation_id, transaction=transaction)
            if skip_reason == "misfire":
                await self._schedules.complete_occurrence(
                    schedule_id=schedule_id,
                    now=now,
                    transaction=transaction,
                )
        return await self._get_row(invocation_id=invocation_id)

    async def _mark_failed(
        self,
        *,
        invocation_id: UUID,
        schedule_id: UUID,
        failure_reason: str,
        now: datetime,
    ) -> ScheduleInvocationDAO:
        """Mark one invocation failed and return the stored row.

        A failed write ends the one-shot occurrence in the same commit (D19,
        decided: disable).

        Args:
            invocation_id (UUID): The invocation to finalise.
            schedule_id (UUID): The schedule that owns the invocation.
            failure_reason (str): The failure reason from the decision or the
                channel refusal.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleInvocationDAO: The stored row.
        """
        async with self._database.transaction() as transaction:
            try:
                await self._invocations.mark_failed(
                    invocation_id=invocation_id,
                    failure_reason=failure_reason,
                    transaction=transaction,
                )
            except InvocationNotPendingError:
                return await self._get_row(invocation_id=invocation_id, transaction=transaction)
            await self._schedules.complete_occurrence(
                schedule_id=schedule_id,
                now=now,
                transaction=transaction,
            )
        return await self._get_row(invocation_id=invocation_id)

    async def _start_fresh_run(
        self,
        *,
        invocation_id: UUID,
        decision: DeliveryDecisionDAO,
        now: datetime,
    ) -> ScheduleInvocationDAO:
        """Start one fresh headless run and record its outcome.

        The running status is committed before the child starts (111.a.3 §5.3
        step 2); the final status is written once after the child ends. A replay
        after the run finalised returns the stored row; the row is never run twice.

        Args:
            invocation_id (UUID): The invocation to run.
            decision (DeliveryDecisionDAO): The run decision with the schedule row.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleInvocationDAO: The final row (completed or run_failed).

        Raises:
            InvocationNotPendingError: When another delivery already finalised the
                row (the caller replay case then returns the stored row).
        """
        session_id: str = str(uuid4())
        async with self._database.transaction() as transaction:
            try:
                await self._invocations.mark_running(
                    invocation_id=invocation_id,
                    recipient_session_id=session_id,
                    transaction=transaction,
                )
            except InvocationNotPendingError:
                return await self._get_row(invocation_id=invocation_id, transaction=transaction)
        schedule = decision.schedule
        try:
            result: FreshRunResultDAO = await self._fresh_runs.start(
                prompt=schedule.prompt,
                cwd=schedule.cwd,
                model=schedule.model,
                session_id=session_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A launch the invoker could not settle still owns a known failure:
            # the row must not sit running until the next restart recovery.
            finished_at: datetime = self._now_provider()
            async with self._database.transaction() as transaction:
                await self._invocations.mark_run_failed(
                    invocation_id=invocation_id,
                    failure_reason="fresh_run_launch_failed",
                    delivered_at=finished_at,
                    transaction=transaction,
                )
                await self._schedules.complete_occurrence(
                    schedule_id=schedule.id,
                    now=finished_at,
                    transaction=transaction,
                )
            return await self._get_row(invocation_id=invocation_id)
        finished_at = self._now_provider()
        async with self._database.transaction() as transaction:
            await self._invocations.mark_run_finished(
                invocation_id=invocation_id,
                status=result.status,
                run_exit_code=result.exit_code,
                delivered_at=finished_at,
                transaction=transaction,
            )
            await self._schedules.complete_occurrence(
                schedule_id=schedule.id,
                now=finished_at,
                transaction=transaction,
            )
        return await self._get_row(invocation_id=invocation_id)

    async def _send(
        self,
        *,
        invocation_id: UUID,
        decision: DeliveryDecisionDAO,
        now: datetime,
    ) -> ScheduleInvocationDAO:
        """Send one invocation's prompt through the channel and mark the outcome.

        Args:
            invocation_id (UUID): The invocation to deliver.
            decision (DeliveryDecisionDAO): The deliver decision with the recipient.
            now (datetime): The boundary clock instant.

        Returns:
            ScheduleInvocationDAO: The final row.
        """
        recipient_session_id = decision.recipient_session_id
        assert recipient_session_id is not None, "deliver decisions carry a recipient"
        schedule = decision.schedule
        assert schedule is not None, "deliver decisions carry the schedule row"
        try:
            await self._sender.send(
                schedule=schedule,
                invocation_id=invocation_id,
                recipient_session_id=recipient_session_id,
            )
        except UnknownParticipantError:
            return await self._mark_failed(
                invocation_id=invocation_id,
                schedule_id=schedule.id,
                failure_reason="unknown_recipient",
                now=now,
            )
        except RecipientClosedError:
            return await self._mark_failed(
                invocation_id=invocation_id,
                schedule_id=schedule.id,
                failure_reason="recipient_closed",
                now=now,
            )
        return await self._mark_delivered(
            invocation_id=invocation_id,
            schedule_id=schedule.id,
            now=now,
            recipient_session_id=recipient_session_id,
        )

    async def _get_row(
        self,
        *,
        invocation_id: UUID,
        transaction: Optional[ScheduleTransaction] = None,
    ) -> ScheduleInvocationDAO:
        """Load one invocation row for the caller.

        Args:
            invocation_id (UUID): The invocation to load.
            transaction (Optional[ScheduleTransaction]): The caller's open
                transaction; the replay guard passes its own so the read never
                opens a second transaction on the serialised database.

        Returns:
            ScheduleInvocationDAO: The row; a missing row is impossible after a
                guarded update, so the caller never sees None here.
        """
        if transaction is not None:
            reloaded_invocation: Optional[ScheduleInvocationDAO] = await self._invocations.get(
                invocation_id=invocation_id, transaction=transaction
            )
        else:
            async with self._database.transaction() as fresh_transaction:
                reloaded_invocation = await self._invocations.get(
                    invocation_id=invocation_id, transaction=fresh_transaction
                )
        assert reloaded_invocation is not None, "guarded update leaves the row in place"
        return reloaded_invocation


def _stored_or_missing(
    *, invocation_id: UUID, invocation: ScheduleInvocationDAO | None
) -> ScheduleInvocationDAO:
    """Return the stored row for a replay, or raise when the row is missing.

    Args:
        invocation_id (UUID): The invocation the caller asked about.
        invocation (ScheduleInvocationDAO | None): The loaded row, or None.

    Returns:
        ScheduleInvocationDAO: The stored row.

    Raises:
        KeyError: When no row exists for the id (the workflow never enqueues one).
    """
    if invocation is None:
        raise KeyError(f"No invocation row exists for id {invocation_id}")
    return invocation
