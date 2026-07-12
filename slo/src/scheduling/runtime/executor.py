"""Scheduler runtime engine."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.scheduling.dao import DeliveryPath, DeliveryState, LoadedScheduleDAO, ScheduleDefinitionDAO
from src.scheduling.runtime.dao import (
    ResolvedSessionTargetDAO,
    ScheduleExecutionOutcomeDAO,
    ScheduleSubprocessResultDAO,
)
from src.scheduling.runtime.fire_lock import ScheduleFireLockFactory
from src.scheduling.runtime.reporting import ScheduleReportWriter
from src.scheduling.runtime.session_target_resolver import SessionTargetResolver
from src.scheduling.runtime.subprocess_runner import ScheduleSubprocessRunner
from src.scheduling.store import ScheduleStore

__all__ = ["ScheduleExecutor"]


class ScheduleExecutor:
    """Execute one schedule fire and persist exactly one outcome record."""

    def __init__(
        self,
        *,
        store: type[ScheduleStore] = ScheduleStore,
        fire_lock_factory: ScheduleFireLockFactory | None = None,
        target_resolver: SessionTargetResolver | None = None,
        subprocess_runner: ScheduleSubprocessRunner | None = None,
        report_writer: ScheduleReportWriter | None = None,
        session_lease_store: SessionOwnershipLeaseStore | None = None,
        session_inbox_store: SessionInboxStore | None = None,
    ) -> None:
        """Bind the executor to its collaborators.

        Args:
            store (type[ScheduleStore]): Canonical schedule store.
            fire_lock_factory (ScheduleFireLockFactory | None): Optional injected lock factory.
            target_resolver (SessionTargetResolver | None): Optional injected target resolver.
            subprocess_runner (ScheduleSubprocessRunner | None): Optional injected subprocess runner.
            report_writer (ScheduleReportWriter | None): Optional injected report writer.
            session_lease_store (SessionOwnershipLeaseStore | None): Optional injected lease store.
            session_inbox_store (SessionInboxStore | None): Optional injected inbox store.
        """
        self._store: type[ScheduleStore] = store
        self._locks: ScheduleFireLockFactory = fire_lock_factory or ScheduleFireLockFactory()
        self._targets: SessionTargetResolver = target_resolver or SessionTargetResolver()
        self._runner: ScheduleSubprocessRunner = subprocess_runner or ScheduleSubprocessRunner()
        self._reports: ScheduleReportWriter = report_writer or ScheduleReportWriter(store=store)
        self._leases: SessionOwnershipLeaseStore | None = session_lease_store
        self._inbox: SessionInboxStore | None = session_inbox_store

    async def execute(self, *, reference: str) -> int:
        """Execute one schedule fire and return the scheduler-facing exit code.

        Args:
            reference (str): Schedule id or normalized name.

        Returns:
            int: Scheduler-facing exit code.
        """
        loaded: LoadedScheduleDAO = self._store.load(reference=reference)
        if not loaded.definition.enabled:
            await self._reports.write(
                loaded=loaded,
                outcome=self._skipped_outcome(
                    delivery_state="skipped_disabled",
                    skipped_reason="schedule disabled",
                ),
            )
            return 0

        fire_lock = self._locks.build(schedule_id=loaded.schedule_id)
        if not await fire_lock.acquire():
            await self._reports.write(
                loaded=loaded,
                outcome=self._skipped_outcome(
                    delivery_state="skipped_overlapping",
                    skipped_reason="another fire is already active",
                ),
            )
            return 0

        try:
            outcome: ScheduleExecutionOutcomeDAO = await self._execute_with_lock(loaded=loaded)
            await self._reports.write(loaded=loaded, outcome=outcome)
            return 0 if outcome.exit_code is None else outcome.exit_code
        finally:
            await fire_lock.release()

    async def _execute_with_lock(
        self,
        *,
        loaded: LoadedScheduleDAO,
    ) -> ScheduleExecutionOutcomeDAO:
        """Execute one fire after preconditions and overlap checks have passed.

        Args:
            loaded (LoadedScheduleDAO): Loaded schedule definition/state pair.

        Returns:
            ScheduleExecutionOutcomeDAO: Normalized outcome.
        """
        definition: ScheduleDefinitionDAO = loaded.definition
        if definition.session_mode == "fresh":
            subprocess_result: ScheduleSubprocessResultDAO = await self._runner.run_fresh(
                definition=definition,
            )
            return self._outcome_from_subprocess(
                delivery_path="fresh_headless",
                target_session_id=None,
                subprocess_result=subprocess_result,
            )

        resolved_target: ResolvedSessionTargetDAO = await self._targets.resolve(
            definition=definition,
            state=loaded.state,
        )
        target_session_id: str | None = resolved_target.target_session_id
        if target_session_id is not None and await self._session_is_active(session_id=target_session_id):
            return await self._queue_for_active_session(
                definition=definition,
                target=resolved_target,
            )

        if resolved_target.resolved_reference is not None:
            subprocess_result = await self._runner.run_resume(
                definition=definition,
                session_reference=resolved_target.resolved_reference,
                target_session_id=resolved_target.target_session_id,
            )
            return self._outcome_from_subprocess(
                delivery_path="resume_headless",
                target_session_id=resolved_target.target_session_id,
                subprocess_result=subprocess_result,
            )

        subprocess_result = await self._runner.run_fresh(
            definition=definition,
            explicit_session_id=resolved_target.explicit_session_id,
            enable_history=True,
        )
        return self._outcome_from_subprocess(
            delivery_path="fresh_headless",
            target_session_id=resolved_target.target_session_id,
            subprocess_result=subprocess_result,
        )

    async def _session_is_active(self, *, session_id: str) -> bool:
        """Return whether ``session_id`` currently has a valid active lease.

        Args:
            session_id (str): Target session id.

        Returns:
            bool: True when the target session is actively owned by the TUI.
        """
        if self._leases is None:
            return False
        return await self._leases.is_active(session_id=session_id)

    async def _queue_for_active_session(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        target: ResolvedSessionTargetDAO,
    ) -> ScheduleExecutionOutcomeDAO:
        """Enqueue work for an active TUI-owned session.

        Args:
            definition (ScheduleDefinitionDAO): Loaded schedule definition.
            target (ResolvedSessionTargetDAO): Resolved target session info.

        Returns:
            ScheduleExecutionOutcomeDAO: Queue/coalesce outcome.
        """
        if self._inbox is None or target.target_session_id is None:
            raise RuntimeError("SessionInbox delivery requested without an inbox store or target session id.")
        started_at: datetime = datetime.now(timezone.utc)
        run_id: str = str(uuid4())
        message: SessionInboxMessageDAO = SessionInboxMessageDAO(
            session_id=target.target_session_id,
            schedule_id=definition.schedule_id,
            run_id=run_id,
            kind="scheduled_prompt",
            delivery_mode="chat_turn",
            coalesce_key=(
                definition.session_policy.coalescing_key if definition.session_policy is not None else None
            ),
            title=definition.name,
            text=definition.prompt,
            payload={"cwd": definition.cwd, "model": definition.model},
        )
        enqueue_result = await self._inbox.enqueue(message=message)
        finished_at: datetime = datetime.now(timezone.utc)
        return ScheduleExecutionOutcomeDAO(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            status=None,
            delivery_path="session_inbox",
            delivery_state="coalesced" if enqueue_result.result == "coalesced" else "queued",
            session_id=None,
            target_session_id=target.target_session_id,
            exit_code=None,
            summary=definition.prompt[:200],
            stdout_summary="",
            stderr_summary="",
            skipped_reason=None,
            coalesced_fire_count=1 if enqueue_result.result == "coalesced" else 0,
        )

    @staticmethod
    def _outcome_from_subprocess(
        *,
        delivery_path: DeliveryPath,
        target_session_id: str | None,
        subprocess_result: ScheduleSubprocessResultDAO,
    ) -> ScheduleExecutionOutcomeDAO:
        """Project a subprocess result into the normalized outcome shape.

        Args:
            delivery_path (str): Delivery path used to run the child.
            target_session_id (str | None): Resolved target session id, when any.
            subprocess_result (ScheduleSubprocessResultDAO): Child-process result.

        Returns:
            ScheduleExecutionOutcomeDAO: Normalized scheduler outcome.
        """
        finished_at: datetime = datetime.now(timezone.utc)
        return ScheduleExecutionOutcomeDAO(
            finished_at=finished_at,
            status=subprocess_result.status,
            delivery_path=delivery_path,
            delivery_state="executed",
            session_id=subprocess_result.session_id,
            target_session_id=target_session_id,
            exit_code=subprocess_result.exit_code,
            summary=subprocess_result.summary,
            stdout_summary=subprocess_result.stdout_summary,
            stderr_summary=subprocess_result.stderr_summary,
        )

    @staticmethod
    def _skipped_outcome(
        *,
        delivery_state: DeliveryState,
        skipped_reason: str,
    ) -> ScheduleExecutionOutcomeDAO:
        """Build a normalized skipped outcome.

        Args:
            delivery_state (str): Skip-state discriminator.
            skipped_reason (str): Human-readable skip reason.

        Returns:
            ScheduleExecutionOutcomeDAO: Skipped normalized outcome.
        """
        current_time: datetime = datetime.now(timezone.utc)
        return ScheduleExecutionOutcomeDAO(
            started_at=current_time,
            finished_at=current_time,
            status=None,
            delivery_path="none",
            delivery_state=delivery_state,
            session_id=None,
            target_session_id=None,
            exit_code=None,
            summary="",
            stdout_summary="",
            stderr_summary="",
            skipped_reason=skipped_reason,
            coalesced_fire_count=0,
        )
