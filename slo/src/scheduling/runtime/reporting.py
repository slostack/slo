"""Schedule outcome reporting and state progression."""

from __future__ import annotations

from src.scheduling.dao import LoadedScheduleDAO, ScheduleRunRecordDAO, ScheduleStateDAO
from src.scheduling.runtime.dao import ScheduleExecutionOutcomeDAO
from src.scheduling.store import ScheduleStore

__all__ = ["ScheduleReportWriter"]


class ScheduleReportWriter:
    """Persist immutable run records and mutable schedule state snapshots."""

    def __init__(self, *, store: type[ScheduleStore] = ScheduleStore) -> None:
        """Bind the writer to the canonical store implementation.

        Args:
            store (type[ScheduleStore]): Store class to persist through.
        """
        self._store: type[ScheduleStore] = store

    async def write(
        self,
        *,
        loaded: LoadedScheduleDAO,
        outcome: ScheduleExecutionOutcomeDAO,
    ) -> None:
        """Append a run record and rewrite the mutable state snapshot.

        Args:
            loaded (LoadedScheduleDAO): Loaded schedule definition/state pair.
            outcome (ScheduleExecutionOutcomeDAO): Normalized runtime outcome.
        """
        record: ScheduleRunRecordDAO = ScheduleRunRecordDAO(
            run_id=outcome.run_id,
            schedule_id=loaded.schedule_id,
            started_at=outcome.started_at,
            finished_at=outcome.finished_at,
            status=outcome.status,
            delivery_path=outcome.delivery_path,
            delivery_state=outcome.delivery_state,
            session_id=outcome.session_id,
            target_session_id=outcome.target_session_id,
            exit_code=outcome.exit_code,
            summary=outcome.summary,
            stdout_summary=outcome.stdout_summary,
            stderr_summary=outcome.stderr_summary,
            skipped_reason=outcome.skipped_reason,
            coalesced_fire_count=outcome.coalesced_fire_count,
        )
        self._store.append_run_record(schedule_id=loaded.schedule_id, record=record)
        self._store.update_state(
            schedule_id=loaded.schedule_id,
            state=self._build_next_state(
                loaded=loaded,
                outcome=outcome,
            ),
        )

    def _build_next_state(
        self,
        *,
        loaded: LoadedScheduleDAO,
        outcome: ScheduleExecutionOutcomeDAO,
    ) -> ScheduleStateDAO:
        """Project the next mutable schedule state snapshot.

        Args:
            loaded (LoadedScheduleDAO): Prior loaded schedule snapshot.
            outcome (ScheduleExecutionOutcomeDAO): Runtime outcome to apply.

        Returns:
            ScheduleStateDAO: Replacement schedule state.
        """
        current: ScheduleStateDAO = loaded.state
        return current.model_copy(
            update={
                "last_run_at": outcome.started_at,
                "last_status": outcome.status,
                "last_session_id": outcome.session_id or current.last_session_id,
                "last_delivery_path": outcome.delivery_path,
                "last_delivery_state": outcome.delivery_state,
                "run_count": current.run_count + 1,
            },
        )
