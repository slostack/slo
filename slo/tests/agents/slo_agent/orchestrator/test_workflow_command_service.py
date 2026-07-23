"""Tests for ``WorkflowCommandService`` — /workflows list/abort/dismiss (spec 57.a.6)."""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Callable, Optional

import pytest

from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowCommandService,
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
)

_OWNER_SESSION_ID: str = "session-1234"


class _KillRecorder:
    """Records signal deliveries and optionally raises for dead pids."""

    def __init__(self, *, raise_process_lookup: bool = False) -> None:
        """Seed the recorder.

        Args:
            raise_process_lookup (bool): When True, every call raises
                ``ProcessLookupError`` (the already-dead-pid branch).
        """
        self.calls: list[tuple[int, int]] = []
        self._raise_process_lookup: bool = raise_process_lookup

    def __call__(self, pid: int, signal_number: int) -> None:
        """Record one delivery attempt.

        Args:
            pid (int): Target process-group leader pid.
            signal_number (int): Delivered signal.
        """
        self.calls.append((pid, signal_number))
        if self._raise_process_lookup:
            raise ProcessLookupError(pid)


class _ScheduleRecorder:
    """Captures escalation timers so tests can fire them synchronously."""

    def __init__(self) -> None:
        """Seed the empty capture list."""
        self.scheduled: list[tuple[float, Callable[[], None]]] = []

    def __call__(self, delay_seconds: float, callback: Callable[[], None]) -> None:
        """Capture one delayed callback.

        Args:
            delay_seconds (float): Requested delay.
            callback (Callable[[], None]): The escalation callback.
        """
        self.scheduled.append((delay_seconds, callback))


def _build_store(*, tmp_path: Path, pid_alive: bool = True) -> WorkflowHandleStore:
    """Build a handle store with an injected liveness probe.

    Args:
        tmp_path (Path): Test-scoped store root.
        pid_alive (bool): Fixed probe answer for every pid.

    Returns:
        WorkflowHandleStore: Store rooted under ``tmp_path``.
    """
    return WorkflowHandleStore(
        history_root=tmp_path / "history",
        pid_alive=lambda pid: pid_alive,
    )


async def _write_handle(
    *,
    store: WorkflowHandleStore,
    workflow_id: str = "wf-1",
    state: WorkflowState = "running",
    pid: int = 4242,
) -> WorkflowHandleDAO:
    """Persist one handle owned by the test session.

    Args:
        store (WorkflowHandleStore): Target store.
        workflow_id (str): Handle workflow id.
        state (WorkflowState): Initial handle state.
        pid (int): Process-group leader pid.

    Returns:
        WorkflowHandleDAO: The persisted handle.
    """
    handle: WorkflowHandleDAO = WorkflowHandleDAO(
        workflow_id=workflow_id,
        owner_session_id=_OWNER_SESSION_ID,
        orchestrator_session_id="9c41aaaa-bbbb-cccc-dddd-eeeeffff0000",
        pid=pid,
        brief="run the workflow",
        cwd="/tmp",
        state=state,
    )
    await store.write(handle=handle)
    return handle


def _build_service(
    *,
    store: WorkflowHandleStore,
    kill: Optional[_KillRecorder] = None,
    pid_alive: bool = False,
    schedule: Optional[_ScheduleRecorder] = None,
) -> WorkflowCommandService:
    """Build a service with injected signal/liveness/scheduler seams.

    Args:
        store (WorkflowHandleStore): Handle store under test.
        kill (Optional[_KillRecorder]): Signal recorder; a fresh one when None.
        pid_alive (bool): Fixed escalation-probe answer.
        schedule (Optional[_ScheduleRecorder]): Timer recorder; fresh when None.

    Returns:
        WorkflowCommandService: Fully injected service.
    """
    return WorkflowCommandService(
        store=store,
        owner_session_id=_OWNER_SESSION_ID,
        kill=kill or _KillRecorder(),
        pid_alive=lambda pid: pid_alive,
        schedule=schedule or _ScheduleRecorder(),
    )


class TestListText:
    """``/workflows`` listing."""

    @pytest.mark.asyncio
    async def test_list_text_renders_one_row_per_handle(self, tmp_path: Path) -> None:
        """Every handle renders one row with id, state, orch prefix, and hint."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        first: WorkflowHandleDAO = await _write_handle(store=store, workflow_id="wf-1")
        await _write_handle(store=store, workflow_id="wf-2", state="completed")
        service: WorkflowCommandService = _build_service(store=store)

        listing: str = await service.list_text()

        rows: list[str] = listing.splitlines()
        assert len(rows) == 2
        started: str = first.started_at.strftime("%H:%M")
        assert rows[0] == (
            f"wf-1  running  orch 9c41aaaa  started {started}  (abort: /workflows abort wf-1)"
        )
        assert rows[1].startswith("wf-2  completed  orch 9c41aaaa  started ")

    @pytest.mark.asyncio
    async def test_list_text_reports_no_workflows(self, tmp_path: Path) -> None:
        """An empty store renders the no-workflows line."""
        service: WorkflowCommandService = _build_service(store=_build_store(tmp_path=tmp_path))

        assert await service.list_text() == "no detached workflows for this session"

    @pytest.mark.asyncio
    async def test_list_reconciles_dead_pid_to_stalled(self, tmp_path: Path) -> None:
        """A dead running workflow lists as ``stalled`` with the dismiss hint."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="running")
        service: WorkflowCommandService = _build_service(store=store)

        listing: str = await service.list_text()

        assert "wf-1  stalled" in listing
        assert "(dismiss: /workflows dismiss wf-1)" in listing


class TestAbort:
    """``/workflows abort <id>``."""

    @pytest.mark.asyncio
    async def test_abort_sends_sigterm_to_process_group(self, tmp_path: Path) -> None:
        """Abort delivers SIGTERM to the handle's process-group leader pid."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, pid=4242)
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)

        await service.abort(workflow_id="wf-1")

        assert kill.calls == [(4242, signal.SIGTERM)]

    @pytest.mark.asyncio
    async def test_abort_marks_aborted_and_confirms(self, tmp_path: Path) -> None:
        """Abort persists state ``aborted`` and returns the confirmation line."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, pid=4242)
        service: WorkflowCommandService = _build_service(store=store)

        confirmation: str = await service.abort(workflow_id="wf-1")

        assert confirmation == "workflow wf-1 aborted (SIGTERM sent to process group 4242)"
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "aborted"

    @pytest.mark.asyncio
    async def test_abort_launching_handle_marks_aborted(self, tmp_path: Path) -> None:
        """A launching handle transitions directly to aborted."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="launching")
        service: WorkflowCommandService = _build_service(store=store)

        confirmation: str = await service.abort(workflow_id="wf-1")

        assert "aborted" in confirmation
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "aborted"

    @pytest.mark.asyncio
    async def test_abort_escalates_to_sigkill_when_alive(self, tmp_path: Path) -> None:
        """The 5 s escalation SIGKILLs a process group that survived SIGTERM."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, pid=4242)
        kill: _KillRecorder = _KillRecorder()
        schedule: _ScheduleRecorder = _ScheduleRecorder()
        service: WorkflowCommandService = _build_service(
            store=store,
            kill=kill,
            pid_alive=True,
            schedule=schedule,
        )

        await service.abort(workflow_id="wf-1")
        assert len(schedule.scheduled) == 1
        delay_seconds, escalate = schedule.scheduled[0]
        escalate()

        assert delay_seconds == 5.0
        assert kill.calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]

    @pytest.mark.asyncio
    async def test_abort_does_not_escalate_when_pid_died(self, tmp_path: Path) -> None:
        """The escalation is a no-op when SIGTERM already terminated the group."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, pid=4242)
        kill: _KillRecorder = _KillRecorder()
        schedule: _ScheduleRecorder = _ScheduleRecorder()
        service: WorkflowCommandService = _build_service(
            store=store,
            kill=kill,
            pid_alive=False,
            schedule=schedule,
        )

        await service.abort(workflow_id="wf-1")
        schedule.scheduled[0][1]()

        assert kill.calls == [(4242, signal.SIGTERM)]

    @pytest.mark.asyncio
    async def test_abort_already_dead_pid_still_marks_aborted(self, tmp_path: Path) -> None:
        """``ProcessLookupError`` from killpg still honours the abort intent."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store)
        kill: _KillRecorder = _KillRecorder(raise_process_lookup=True)
        service: WorkflowCommandService = _build_service(store=store, kill=kill)

        confirmation: str = await service.abort(workflow_id="wf-1")

        assert "aborted" in confirmation
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "aborted"

    @pytest.mark.asyncio
    async def test_abort_unknown_id_returns_error_text(self, tmp_path: Path) -> None:
        """An unknown workflow id returns error text, never raises."""
        service: WorkflowCommandService = _build_service(store=_build_store(tmp_path=tmp_path))

        assert await service.abort(workflow_id="wf-nope") == "no workflow wf-nope"

    @pytest.mark.asyncio
    async def test_abort_terminal_state_refused(self, tmp_path: Path) -> None:
        """Terminal-state handles are refused and receive no signal."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="completed")
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)

        refusal: str = await service.abort(workflow_id="wf-1")

        assert refusal == "no live workflow wf-1 (state completed)"
        assert kill.calls == []


class TestDismiss:
    """``/workflows dismiss <id>``."""

    @pytest.mark.asyncio
    async def test_dismiss_stalled_marks_failed(self, tmp_path: Path) -> None:
        """Dismiss acknowledges a stalled workflow via ``stalled → failed``."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="stalled")
        service: WorkflowCommandService = _build_service(store=store)

        confirmation: str = await service.dismiss(workflow_id="wf-1")

        assert confirmation == "workflow wf-1 dismissed (stalled → failed)"
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "failed"

    @pytest.mark.asyncio
    async def test_dismiss_non_stalled_returns_error_text(self, tmp_path: Path) -> None:
        """Dismissing a non-stalled workflow returns error text."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="running")
        service: WorkflowCommandService = _build_service(store=store)

        assert await service.dismiss(workflow_id="wf-1") == (
            "workflow wf-1 is running — only stalled workflows can be dismissed"
        )

    @pytest.mark.asyncio
    async def test_dismiss_unknown_id_returns_error_text(self, tmp_path: Path) -> None:
        """An unknown workflow id returns error text, never raises."""
        service: WorkflowCommandService = _build_service(store=_build_store(tmp_path=tmp_path))

        assert await service.dismiss(workflow_id="wf-nope") == "no workflow wf-nope"


class TestAbortPidSafety:
    """Non-positive pids must never be signalled (killpg(0) hits the TUI itself)."""

    @pytest.mark.asyncio
    async def test_abort_pid_zero_marks_aborted_without_signal(self, tmp_path: Path) -> None:
        """A never-patched pid-0 handle aborts with no signal and no escalation."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="launching", pid=0)
        kill: _KillRecorder = _KillRecorder()
        schedule: _ScheduleRecorder = _ScheduleRecorder()
        service: WorkflowCommandService = _build_service(
            store=store,
            kill=kill,
            pid_alive=True,
            schedule=schedule,
        )

        confirmation: str = await service.abort(workflow_id="wf-1")

        assert confirmation == "workflow wf-1 aborted (no live process to signal)"
        assert kill.calls == []
        assert schedule.scheduled == []
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "aborted"

    @pytest.mark.asyncio
    async def test_escalate_ignores_non_positive_pid(self, tmp_path: Path) -> None:
        """Escalation never SIGKILLs pid 0 even when the alive probe says alive."""
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(
            store=_build_store(tmp_path=tmp_path),
            kill=kill,
            pid_alive=True,
        )

        service._escalate(pid=0)
        service._escalate(pid=-1)

        assert kill.calls == []

    @pytest.mark.asyncio
    async def test_abort_unsafe_workflow_id_returns_error_text(self, tmp_path: Path) -> None:
        """A path-meta workflow id behaves like an unknown workflow."""
        service: WorkflowCommandService = _build_service(store=_build_store(tmp_path=tmp_path))

        assert await service.abort(workflow_id="../evil") == "no workflow ../evil"
