"""Orchestration tests for the single workflow observation coordinator (feature 94 a.3).

The coordinator is driven with a recording sink, a fake timer factory and a
fake service whose reads block on ``asyncio.Event`` barriers, so every ordering
claim (single flight, coalescing, generation discard, joins) is deterministic.
No sleeps, files, providers or processes are involved.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

import pytest

from src.tui.workflows.dao import (
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionRowDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.progress_coordinator import WorkflowProgressCoordinator

_PARENT: str = "parent-session"
_CHILD_KEY: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
    orchestrator_session_id=_PARENT, session_id="child-a"
)
_OTHER_KEY: WorkflowSessionKeyDAO = WorkflowSessionKeyDAO(
    orchestrator_session_id=_PARENT, session_id="child-b"
)
_EXECUTION_1: str = "11111111-1111-4111-8111-111111111111"
_EXECUTION_2: str = "22222222-2222-4222-8222-222222222222"


def _row(
    *,
    key: WorkflowSessionKeyDAO = _CHILD_KEY,
    execution_id: str = _EXECUTION_1,
    status: str = "running",
    availability: str = "available",
) -> WorkflowSessionRowDAO:
    """Build one child row.

    Args:
        key (WorkflowSessionKeyDAO, optional): Row key. Defaults to the child key.
        execution_id (str, optional): Incarnation. Defaults to the first execution.
        status (str, optional): Display status. Defaults to ``"running"``.
        availability (str, optional): Row freshness. Defaults to ``"available"``.

    Returns:
        WorkflowSessionRowDAO: The row.
    """
    return WorkflowSessionRowDAO(
        key=key,
        role="child",
        execution_id=execution_id,
        status=status,
        task_text="Audit the parser",
        task_text_complete=True,
        availability=availability,  # type: ignore[arg-type]
    )


def _sessions(*rows: WorkflowSessionRowDAO, notice: Optional[str] = None) -> WorkflowSessionSnapshotDAO:
    """Build a list snapshot.

    Args:
        *rows (WorkflowSessionRowDAO): Rows in order.
        notice (Optional[str], optional): Fixed notice. Defaults to None.

    Returns:
        WorkflowSessionSnapshotDAO: Snapshot.
    """
    return WorkflowSessionSnapshotDAO(rows=rows, notice=notice)


def _progress(
    *,
    key: WorkflowSessionKeyDAO = _CHILD_KEY,
    execution_id: str = _EXECUTION_1,
    revision: str = "r1",
    availability: str = "available",
    final_read_complete: bool = False,
    membership_removed: bool = False,
) -> SessionProgressSnapshotDAO:
    """Build one progress result.

    Args:
        key (WorkflowSessionKeyDAO, optional): Observed key. Defaults to the child key.
        execution_id (str, optional): Incarnation. Defaults to the first execution.
        revision (str, optional): Content revision. Defaults to ``"r1"``.
        availability (str, optional): Readability. Defaults to ``"available"``.
        final_read_complete (bool, optional): Terminal final read. Defaults to False.
        membership_removed (bool, optional): Authoritative removal. Defaults to False.

    Returns:
        SessionProgressSnapshotDAO: Progress result.
    """
    return SessionProgressSnapshotDAO(
        key=key,
        execution_id="" if membership_removed else execution_id,
        revision=revision,
        source_generation="capture:1",
        availability=availability,  # type: ignore[arg-type]
        observed_at=datetime.now(tz=timezone.utc).isoformat(),
        task_text="Audit the parser",
        task_text_complete=True,
        status="completed" if final_read_complete else "running",
        final_read_complete=final_read_complete,
        membership_removed=membership_removed,
    )


class _FakeTimer:
    """Stand-in for a Textual timer; records ``stop``."""

    def __init__(self) -> None:
        """Start running."""
        self.stopped: bool = False

    def stop(self) -> None:
        """Record that the owner stopped the timer."""
        self.stopped = True


class _Scheduler:
    """Record every timer registration made through the injected factory."""

    def __init__(self) -> None:
        """Start with no registrations."""
        self.registrations: list[tuple[float, Callable[[], None]]] = []
        self.timers: list[_FakeTimer] = []

    def __call__(self, seconds: float, callback: Callable[[], None]) -> _FakeTimer:
        """Register one interval and return its timer.

        Args:
            seconds (float): Interval.
            callback (Callable[[], None]): Tick callback.

        Returns:
            _FakeTimer: Timer handle.
        """
        self.registrations.append((seconds, callback))
        timer: _FakeTimer = _FakeTimer()
        self.timers.append(timer)
        return timer


class _FakeService:
    """Answer list and progress reads from queues; optional barriers hold a read open."""

    def __init__(self) -> None:
        """Start with an empty list answer and open barriers."""
        self.calls: list[str] = []
        self.sessions: list[WorkflowSessionSnapshotDAO] = []
        self.default_sessions: WorkflowSessionSnapshotDAO = _sessions()
        self.progress: list[SessionProgressSnapshotDAO] = []
        self.default_progress: SessionProgressSnapshotDAO = _progress()
        self.list_gate: Optional[asyncio.Event] = None
        self.progress_gate: Optional[asyncio.Event] = None
        self.list_entered: asyncio.Event = asyncio.Event()
        self.progress_entered: asyncio.Event = asyncio.Event()
        self.list_error: Optional[BaseException] = None

    async def load_session_snapshot(self) -> WorkflowSessionSnapshotDAO:
        """Return the next queued list answer, waiting on the list barrier first.

        Returns:
            WorkflowSessionSnapshotDAO: Next answer or the default.

        Raises:
            BaseException: The configured list error, once.
        """
        self.calls.append("snapshot")
        self.list_entered.set()
        if self.list_gate is not None:
            await self.list_gate.wait()
        if self.list_error is not None:
            error, self.list_error = self.list_error, None
            raise error
        return self.sessions.pop(0) if self.sessions else self.default_sessions

    async def load_session_progress(self, *, key: WorkflowSessionKeyDAO) -> SessionProgressSnapshotDAO:
        """Return the next queued progress answer, waiting on the progress barrier first.

        Args:
            key (WorkflowSessionKeyDAO): Requested key.

        Returns:
            SessionProgressSnapshotDAO: Next answer or the default.
        """
        self.calls.append(f"progress:{key.session_id}")
        self.progress_entered.set()
        if self.progress_gate is not None:
            await self.progress_gate.wait()
        return self.progress.pop(0) if self.progress else self.default_progress

    @property
    def snapshot_reads(self) -> int:
        """Return how many list reads ran."""
        return self.calls.count("snapshot")

    @property
    def progress_reads(self) -> list[str]:
        """Return the progress reads in order."""
        return [call for call in self.calls if call.startswith("progress:")]


class _RecordingSink:
    """Record every presentation callback in order; ``accept_open`` models modal refusal."""

    def __init__(self) -> None:
        """Accept selections by default."""
        self.events: list[str] = []
        self.accept_open: bool = True
        self.applied_sessions: list[WorkflowSessionSnapshotDAO] = []
        self.applied_progress: list[SessionProgressSnapshotDAO] = []
        self.on_apply_sessions: Optional[Callable[[], None]] = None

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Record an open request.

        Args:
            key (WorkflowSessionKeyDAO): Requested key.

        Returns:
            bool: Whether the open was accepted.
        """
        self.events.append(f"open:{key.session_id}")
        return self.accept_open

    def minimize_progress(self) -> None:
        """Record a minimize."""
        self.events.append("minimize")

    async def apply_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Record a list paint and run the optional reentrancy hook.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Rows.
        """
        self.events.append("sessions")
        self.applied_sessions.append(snapshot)
        if self.on_apply_sessions is not None:
            self.on_apply_sessions()

    def apply_progress(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Record a progress paint.

        Args:
            snapshot (SessionProgressSnapshotDAO): Progress.
        """
        self.events.append(f"progress:{snapshot.key.session_id}:{snapshot.revision}")
        self.applied_progress.append(snapshot)

    def membership_removed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Record a removal notice.

        Args:
            key (WorkflowSessionKeyDAO): Removed key.
        """
        self.events.append(f"removed:{key.session_id}")

    def observation_failed(self) -> None:
        """Record an unexpected failure notice."""
        self.events.append("failed")


class _Harness:
    """Bundle one coordinator with its fakes."""

    def __init__(self) -> None:
        """Build the coordinator without starting it."""
        self.service: _FakeService = _FakeService()
        self.sink: _RecordingSink = _RecordingSink()
        self.scheduler: _Scheduler = _Scheduler()
        self.coordinator: WorkflowProgressCoordinator = WorkflowProgressCoordinator(
            service=self.service,
            sink=self.sink,
            schedule=self.scheduler,  # type: ignore[arg-type]
        )

    async def settle(self) -> None:
        """Await the coordinator's current drain task, if any."""
        task: Optional[asyncio.Task[None]] = self.coordinator._task
        if task is not None:
            await task

    def tick(self) -> None:
        """Fire the registered five-second callback once."""
        self.scheduler.registrations[0][1]()


@pytest.fixture
def harness() -> _Harness:
    """Provide a fresh coordinator harness.

    Returns:
        _Harness: Unstarted coordinator with fakes.
    """
    return _Harness()


class TestScheduling:
    """Exactly one 5.0-second timer, an immediate read and bounded coalescing."""

    async def test_single_flight_and_coalescing(self, harness: _Harness) -> None:
        """Start registers 5.0 once and reads immediately; ticks during a read coalesce to one."""
        harness.service.list_gate = asyncio.Event()

        harness.coordinator.start()
        harness.coordinator.start()
        await harness.service.list_entered.wait()
        first_task: Optional[asyncio.Task[None]] = harness.coordinator._task
        harness.tick()
        harness.tick()
        harness.coordinator.request_refresh()

        assert [seconds for seconds, _ in harness.scheduler.registrations] == [5.0]
        assert harness.coordinator._task is first_task
        assert harness.service.snapshot_reads == 1
        harness.service.list_gate.set()
        await harness.settle()
        assert harness.service.snapshot_reads == 2

    async def test_continuous_ticks_stop_after_two_reads(self, harness: _Harness) -> None:
        """Ticks arriving during both reads still end the drain after two reads; the next tick restarts."""
        harness.service.list_gate = asyncio.Event()
        harness.coordinator.start()
        await harness.service.list_entered.wait()
        harness.tick()
        harness.service.list_entered.clear()
        harness.service.list_gate.set()
        harness.service.list_gate = asyncio.Event()
        await harness.service.list_entered.wait()
        harness.tick()
        harness.service.list_gate.set()
        await harness.settle()

        assert harness.service.snapshot_reads == 2
        assert harness.coordinator._pending is False
        harness.service.list_gate = None
        harness.tick()
        await harness.settle()
        assert harness.service.snapshot_reads == 3

    async def test_idle_tick_reads_the_list_only(self, harness: _Harness) -> None:
        """Without a selection a tick reads the list and paints it, never progress."""
        harness.service.default_sessions = _sessions(_row())
        harness.coordinator.start()
        await harness.settle()

        assert harness.service.calls == ["snapshot"]
        assert harness.sink.events == ["sessions"]

    async def test_constructor_starts_nothing(self, harness: _Harness) -> None:
        """Building the coordinator registers no timer and starts no read."""
        await asyncio.sleep(0)

        assert harness.scheduler.registrations == []
        assert harness.service.calls == []
        assert harness.coordinator._task is None


class TestSelection:
    """Selection opens through the sink and reads that exact key."""

    async def test_select_opens_then_reads_progress(self, harness: _Harness) -> None:
        """An accepted selection reads the list, then the selected key, and paints both."""
        harness.service.default_sessions = _sessions(_row())

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.sink.events == ["open:child-a", "sessions", "progress:child-a:r1"]
        assert harness.service.calls == ["snapshot", "progress:child-a"]

    async def test_unrelated_modal_refuses_selection(self, harness: _Harness) -> None:
        """A refused open adopts nothing: no generation change and no progress read."""
        harness.service.default_sessions = _sessions(_row())
        harness.sink.accept_open = False
        generation: int = harness.coordinator._generation

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.coordinator._generation == generation
        assert harness.coordinator._selected is None
        assert harness.service.progress_reads == []
        assert harness.coordinator._task is None

    async def test_membership_removed_closes_before_progress_read(self, harness: _Harness) -> None:
        """A selected key missing from the fresh list is minimized and never read."""
        harness.service.default_sessions = _sessions(_row(key=_OTHER_KEY))

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.service.progress_reads == []
        assert harness.sink.events == ["open:child-a", "sessions", "minimize", "removed:child-a"]
        assert harness.coordinator._selected is None

    async def test_progress_removal_result_minimizes(self, harness: _Harness) -> None:
        """A service removal answer minimizes and notifies instead of painting."""
        harness.service.default_sessions = _sessions(_row())
        harness.service.default_progress = _progress(membership_removed=True)

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.sink.events == ["open:child-a", "sessions", "minimize", "removed:child-a"]
        assert harness.sink.applied_progress == []

    async def test_list_failure_keeps_selected_progress_read(self, harness: _Harness) -> None:
        """Retained stale rows with a failure notice still let the selected read run and paint."""
        harness.service.default_sessions = _sessions(
            _row(availability="stale"), notice="Workflow list unavailable; showing last known sessions."
        )

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.service.progress_reads == ["progress:child-a"]
        assert harness.sink.events[-1] == "progress:child-a:r1"

    async def test_sink_minimize_during_list_paint_skips_the_read(self, harness: _Harness) -> None:
        """An incarnation-change minimize routed during ``apply_sessions`` prevents a stale read."""
        harness.service.default_sessions = _sessions(_row())
        harness.sink.on_apply_sessions = harness.coordinator.minimize

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.service.progress_reads == []
        assert harness.sink.applied_progress == []


class TestGenerationDiscard:
    """Late results for an old generation or key never paint."""

    async def test_close_and_generation_discard_late_results(self, harness: _Harness) -> None:
        """Minimize during a progress read discards its result; nothing but reads reach the service."""
        harness.service.default_sessions = _sessions(_row())
        harness.service.progress_gate = asyncio.Event()
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.service.progress_entered.wait()

        harness.coordinator.minimize()
        harness.service.progress_gate.set()
        await harness.settle()

        assert harness.sink.applied_progress == []
        assert set(harness.service.calls) <= {"snapshot", "progress:child-a"}

    async def test_reselect_during_read_discards_the_old_key(self, harness: _Harness) -> None:
        """Selecting another key during a read paints only the new key's result."""
        harness.service.default_sessions = _sessions(_row(), _row(key=_OTHER_KEY, execution_id=_EXECUTION_2))
        harness.service.progress = [_progress(revision="old"), _progress(key=_OTHER_KEY, revision="new")]
        harness.service.progress_gate = asyncio.Event()
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.service.progress_entered.wait()

        harness.coordinator.select(key=_OTHER_KEY)
        harness.service.progress_gate.set()
        await harness.settle()

        assert [snapshot.revision for snapshot in harness.sink.applied_progress] == ["new"]
        assert harness.service.progress_reads == ["progress:child-a", "progress:child-b"]

    async def test_close_during_read_joins_without_late_paint(self, harness: _Harness) -> None:
        """Close cancels and awaits the read; no paint and no failure notice follow."""
        harness.service.default_sessions = _sessions(_row())
        harness.service.progress_gate = asyncio.Event()
        harness.coordinator.start()
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.service.progress_entered.wait()
        task: Optional[asyncio.Task[None]] = harness.coordinator._task

        await harness.coordinator.close()
        harness.service.progress_gate.set()
        await asyncio.sleep(0)

        assert task is not None and task.done()
        assert harness.coordinator._task is None
        assert harness.scheduler.timers[0].stopped is True
        assert harness.sink.applied_progress == []
        assert "failed" not in harness.sink.events

    async def test_close_during_list_read_skips_the_list_paint(self, harness: _Harness) -> None:
        """A list result arriving after close is never painted."""
        harness.service.list_gate = asyncio.Event()
        harness.coordinator.start()
        await harness.service.list_entered.wait()

        await harness.coordinator.close()

        assert harness.sink.applied_sessions == []

    async def test_close_twice_and_start_after_close(self, harness: _Harness) -> None:
        """Close is idempotent; start, select and refresh after close do nothing."""
        harness.coordinator.start()
        await harness.settle()
        await harness.coordinator.close()
        await harness.coordinator.close()
        reads: int = harness.service.snapshot_reads

        harness.coordinator.start()
        harness.coordinator.select(key=_CHILD_KEY)
        harness.coordinator.request_refresh()
        await asyncio.sleep(0)

        assert len(harness.scheduler.registrations) == 1
        assert harness.service.snapshot_reads == reads
        assert "open:child-a" not in harness.sink.events
        assert harness.coordinator._task is None


class TestTerminalSuppression:
    """One successful final read per execution; reopen and new incarnations read again."""

    async def test_terminal_final_read_retries_until_source_complete(self, harness: _Harness) -> None:
        """An incomplete terminal source keeps being read on ticks until the final read completes."""
        harness.service.default_sessions = _sessions(_row(status="completed"))
        harness.service.progress = [
            _progress(availability="stale"),
            _progress(revision="r2", final_read_complete=True),
        ]
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()
        harness.coordinator.request_refresh()
        await harness.settle()
        harness.coordinator.request_refresh()
        await harness.settle()

        assert harness.service.progress_reads == ["progress:child-a", "progress:child-a"]
        assert harness.service.snapshot_reads == 3

    async def test_reopen_terminal_forces_fresh_read(self, harness: _Harness) -> None:
        """Selecting a finished session again clears suppression and reads once more."""
        harness.service.default_sessions = _sessions(_row(status="completed"))
        harness.service.default_progress = _progress(final_read_complete=True)
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()
        harness.coordinator.minimize()

        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        assert harness.service.progress_reads == ["progress:child-a", "progress:child-a"]

    async def test_incarnation_change_clears_terminal_suppression(self, harness: _Harness) -> None:
        """A new execution under the same key is read even after the old one's final read."""
        harness.service.sessions = [
            _sessions(_row(status="completed")),
            _sessions(_row(execution_id=_EXECUTION_2)),
        ]
        harness.service.progress = [
            _progress(final_read_complete=True),
            _progress(execution_id=_EXECUTION_2, revision="new"),
        ]
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        harness.coordinator.request_refresh()
        await harness.settle()

        assert harness.service.progress_reads == ["progress:child-a", "progress:child-a"]
        assert harness.sink.applied_progress[-1].revision == "new"

    async def test_unavailable_row_is_read_despite_suppression(self, harness: _Harness) -> None:
        """Suppression applies only to an available row of the finished execution."""
        harness.service.sessions = [
            _sessions(_row(status="completed")),
            _sessions(_row(status="completed", availability="stale")),
        ]
        harness.service.default_progress = _progress(final_read_complete=True)
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        harness.coordinator.request_refresh()
        await harness.settle()

        assert len(harness.service.progress_reads) == 2

    async def test_legacy_identity_is_never_suppressed(self, harness: _Harness) -> None:
        """A final read without execution or dispatch identity keeps terminal polling alive."""
        harness.service.default_sessions = _sessions(_row(execution_id=""))
        harness.service.default_progress = _progress(execution_id="", final_read_complete=True)
        harness.coordinator.select(key=_CHILD_KEY)
        await harness.settle()

        harness.coordinator.request_refresh()
        await harness.settle()

        assert len(harness.service.progress_reads) == 2


class TestFailures:
    """Unexpected failures notify once per refresh and never stop later ticks."""

    async def test_unexpected_error_notifies_and_next_tick_retries(self, harness: _Harness) -> None:
        """A programming error reaches ``observation_failed``; the next tick reads again."""
        harness.service.list_error = RuntimeError("bug")
        harness.coordinator.start()
        await harness.settle()

        assert harness.sink.events == ["failed"]
        harness.tick()
        await harness.settle()
        assert harness.service.snapshot_reads == 2
        assert harness.sink.events == ["failed", "sessions"]
