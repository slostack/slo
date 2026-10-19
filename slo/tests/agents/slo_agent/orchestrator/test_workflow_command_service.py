"""Tests for ``WorkflowCommandService`` — /workflows list/abort/dismiss (spec 57.a.6)."""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Callable, Optional
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.slo_agent.orchestrator.dao import FleetSnapshotDAO, SubAgentStatusDAO
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowCommandResultDAO,
    WorkflowCommandService,
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
    WorkflowStateTransitionError,
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

    def __call__(self, *, pid: int, signal_number: int) -> None:
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

    def __call__(self, *, delay_seconds: float, callback: Callable[[], None]) -> None:
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
        assert rows[0] == (f"wf-1  running  orch 9c41aaaa  started {started}  (abort: /workflows abort wf-1)")
        assert rows[1].startswith("wf-2  completed  orch 9c41aaaa  started ")

    @pytest.mark.asyncio
    async def test_format_row_shows_live_and_degraded_for_running(self, tmp_path: Path) -> None:
        """Running rows use fleet truth for live and degraded child counts."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        handle: WorkflowHandleDAO = await _write_handle(store=store)
        FleetStore(
            history_root=tmp_path / "history",
            orchestrator_session_id=handle.orchestrator_session_id,
        ).persist(
            entries=[SubAgentStatusDAO(task_id="t1", session_id="s1", status="running", pid=os.getpid())]
        )
        service: WorkflowCommandService = _build_service(store=store)

        assert "· 1 live · 1 degraded" in service._format_row(handle=handle)

    @pytest.mark.asyncio
    async def test_format_row_shows_cleanup_summary_when_drained(self, tmp_path: Path) -> None:
        """A drained terminal fleet appends its cleanup summary to the row."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed")
        FleetStore(
            history_root=tmp_path / "history",
            orchestrator_session_id=handle.orchestrator_session_id,
        ).persist(
            entries=[
                SubAgentStatusDAO(
                    task_id="t1",
                    session_id="s1",
                    status="completed",
                    terminal_reason="completed",
                )
            ]
        )
        service: WorkflowCommandService = _build_service(store=store)

        assert "fleet: 1 completed · 0 live" in service._format_row(handle=handle)

    @pytest.mark.asyncio
    async def test_format_row_warns_when_terminal_with_live_children(self, tmp_path: Path) -> None:
        """A terminal workflow with a live child remains visibly abortable."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed")
        FleetStore(
            history_root=tmp_path / "history",
            orchestrator_session_id=handle.orchestrator_session_id,
        ).persist(
            entries=[SubAgentStatusDAO(task_id="t1", session_id="s1", status="running", pid=os.getpid())]
        )
        service: WorkflowCommandService = _build_service(store=store)

        row: str = service._format_row(handle=handle)

        assert "⚠ 1 live children" in row
        assert "/workflows abort wf-1" in row

    @pytest.mark.asyncio
    async def test_format_row_unchanged_without_snapshot(self, tmp_path: Path) -> None:
        """Rows retain their legacy text when the fleet file does not exist."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store)
        service: WorkflowCommandService = _build_service(store=store)

        assert service._format_row(handle=handle) == service._base_row(handle=handle)

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


class TestTerminalFleetSweep:
    """Terminal workflow listings reap survivors only after owner death."""

    async def test_sweep_skips_when_orchestrator_alive(self, tmp_path: Path, monkeypatch) -> None:
        """A live terminal owner remains the only permitted fleet writer."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed", pid=4242)
        snapshot: FleetSnapshotDAO = FleetSnapshotDAO(
            orchestrator_session_id=handle.orchestrator_session_id,
            entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", status="running", pid=123)],
            updated_at="2026-01-01T00:00:00+00:00",
        )
        service: WorkflowCommandService = _build_service(store=store, pid_alive=True)
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive", lambda *, pid: True
        )

        remaining: int = await service._sweep_terminal_fleet(handle=handle, snapshot=snapshot)

        assert remaining == 1

    async def test_sweep_reaps_and_persists_fleet_corrections(self, tmp_path: Path, monkeypatch) -> None:
        """A dead owner permits a verified child reap and durable sweep correction."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed", pid=4242)
        fleet_store: FleetStore = FleetStore(
            history_root=tmp_path / "history", orchestrator_session_id=handle.orchestrator_session_id
        )
        fleet_store.persist(
            entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", status="running", pid=123)]
        )
        snapshot = fleet_store.load()
        assert snapshot is not None
        service: WorkflowCommandService = _build_service(store=store, pid_alive=False)
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.child_identity_outcome",
            lambda *, pid, session_id: "matching",
        )
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.reap",
            pytest.importorskip("unittest.mock").AsyncMock(return_value="graceful"),
        )

        remaining: int = await service._sweep_terminal_fleet(handle=handle, snapshot=snapshot)

        persisted = fleet_store.load()
        assert remaining == 0
        assert persisted is not None
        assert persisted.entries[0].terminal_reason == "reaped_orphan"
        assert persisted.entries[0].terminated_by == "sweep"

    async def test_sweep_records_recycled_pid_without_signaling(self, tmp_path: Path, monkeypatch) -> None:
        """A foreign argv is accounted for as failed without touching that pid."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed", pid=4242)
        snapshot: FleetSnapshotDAO = FleetSnapshotDAO(
            orchestrator_session_id=handle.orchestrator_session_id,
            entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", status="running", pid=123)],
            updated_at="2026-01-01T00:00:00+00:00",
        )
        service: WorkflowCommandService = _build_service(store=store, pid_alive=False)
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.child_identity_outcome",
            lambda *, pid, session_id: "recycled_pid",
        )
        reap = pytest.importorskip("unittest.mock").AsyncMock()
        monkeypatch.setattr("src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.reap", reap)

        remaining: int = await service._sweep_terminal_fleet(handle=handle, snapshot=snapshot)

        assert remaining == 0
        reap.assert_not_awaited()
        persisted: FleetSnapshotDAO | None = FleetStore.load_snapshot(
            path=OrchestrationLayout.fleet_path(
                history_root=tmp_path / "history",
                orchestrator_session_id=handle.orchestrator_session_id,
            )
        )
        assert persisted is not None
        assert persisted.entries[0].status == "failed"
        assert persisted.entries[0].terminated_by == "sweep"

    async def test_list_text_shows_zero_live_after_sweep(self, tmp_path: Path, monkeypatch) -> None:
        """A successful terminal sweep renders durable zero-live cleanup accounting."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed", pid=4242)
        FleetStore(
            history_root=tmp_path / "history", orchestrator_session_id=handle.orchestrator_session_id
        ).persist(entries=[SubAgentStatusDAO(task_id="t1", session_id="child-1", status="running", pid=123)])
        service: WorkflowCommandService = _build_service(store=store, pid_alive=False)
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive", lambda *, pid: True
        )
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.child_identity_outcome",
            lambda *, pid, session_id: "matching",
        )
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.reap",
            pytest.importorskip("unittest.mock").AsyncMock(return_value="killed"),
        )

        listing: str = await service.list_text()

        assert "0 live" in listing
        assert "⚠" not in listing


class TestAbort:
    """``/workflows abort <id>``."""

    @pytest.mark.asyncio
    async def test_abort_writes_durable_abort_request(self, tmp_path: Path) -> None:
        """Abort persists its watchdog order before signalling the process group."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store)
        service: WorkflowCommandService = _build_service(store=store)

        await service.abort(workflow_id=handle.workflow_id)

        assert OrchestrationLayout.abort_request_path(
            history_root=tmp_path / "history",
            orchestrator_session_id=handle.orchestrator_session_id,
        ).exists()

    @pytest.mark.asyncio
    async def test_abort_request_write_failure_returns_safe_failure_without_signal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unavailable durable abort channel prevents signal-only cancellation."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, pid=4242)
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)

        def _raise_write(*, path: Path, text: str, private: bool = True) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.AtomicFileWriter.write_text",
            _raise_write,
        )

        result: str = await service.abort(workflow_id="wf-1")

        assert "could not record" in result.lower()
        assert kill.calls == []
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "running"

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

    @pytest.mark.asyncio
    async def test_abort_terminal_handle_sweeps_verified_live_fleet_children(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Terminal abort uses the verified per-child sweep, never child killpg."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="completed")
        fleet_store: FleetStore = FleetStore(
            history_root=tmp_path / "history",
            orchestrator_session_id=handle.orchestrator_session_id,
        )
        fleet_store.persist(
            entries=[SubAgentStatusDAO(task_id="t1", session_id="s1", status="running", pid=4242)]
        )
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill, pid_alive=False)
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.child_identity_outcome",
            lambda *, pid, session_id: "matching",
        )
        reap = pytest.importorskip("unittest.mock").AsyncMock(return_value="graceful")
        monkeypatch.setattr("src.agents.slo_agent.orchestrator.workflow_registry.FleetReaper.reap", reap)

        confirmation: str = await service.abort(workflow_id=handle.workflow_id)
        snapshot = fleet_store.load()

        assert confirmation == "workflow wf-1 child cleanup completed"
        assert kill.calls == []
        assert snapshot is not None
        assert snapshot.entries[0].terminal_reason == "reaped_orphan"
        reap.assert_awaited_once_with(pid=4242)


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


class TestResume:
    """``/workflows resume <id>``."""

    @pytest.mark.asyncio
    async def test_resume_reports_unknown_workflow(self, tmp_path: Path) -> None:
        """An unknown workflow id returns a one-line error without spawning."""
        service: WorkflowCommandService = _build_service(store=_build_store(tmp_path=tmp_path))

        assert await service.resume(workflow_id="wf-nope") == "no workflow wf-nope"

    @pytest.mark.asyncio
    async def test_resume_refuses_running_workflow(self, tmp_path: Path) -> None:
        """A live workflow cannot be relaunched before it reaches a dead state."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="running")
        service: WorkflowCommandService = _build_service(store=store)

        result: str = await service.resume(workflow_id="wf-1")

        assert result == "workflow wf-1 is running — only stalled or failed workflows can be resumed"

    @pytest.mark.asyncio
    async def test_resume_refuses_stale_terminal_handle_with_fresh_running_evidence(
        self, tmp_path: Path
    ) -> None:
        """Fresh self-report evidence prevents a duplicate resumed orchestrator.

        WHAT: Verifies resume reconciles a stale terminal projection before it
            considers spawning a replacement process.
        WHO: The workflow command service regression suite calls this test.
        WHEN: Whenever resume admission or durable evidence handling changes.

        Args:
            tmp_path (Path): Test-scoped history root.
        """
        from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
        from src.agents.slo_agent.orchestrator.dao import OrchestratorStatusDAO
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        handle: WorkflowHandleDAO = await _write_handle(store=store, state="stalled")
        AtomicFileWriter.write_json(
            path=OrchestrationLayout.orchestrator_status_path(
                history_root=tmp_path / "history",
                orchestrator_session_id=handle.orchestrator_session_id,
            ),
            model=OrchestratorStatusDAO(
                workflow_id=handle.workflow_id,
                orchestrator_session_id=handle.orchestrator_session_id,
                pid=5678,
                state="running",
                updated_at="2999-01-01T00:00:00+00:00",
            ),
        )
        service: WorkflowCommandService = _build_service(store=store)

        with patch.object(WorkflowRelauncher, "invoke", new=AsyncMock()) as relaunch:
            result: str = await service.resume(workflow_id="wf-1")

        assert result == "workflow wf-1 is running — only stalled or failed workflows can be resumed"
        relaunch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_reaps_process_when_relaunch_transition_loses_race(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rejected post-spawn transition sends the fresh group through shutdown.

        WHAT: Verifies a concurrent durable-state change cannot leave a resumed
            orchestrator process untracked.
        WHO: The workflow command service regression suite calls this test.
        WHEN: Whenever relaunch admission or transition failure handling changes.

        Args:
            tmp_path (Path): Test-scoped history root.
            monkeypatch (pytest.MonkeyPatch): Pytest store-transition replacement fixture.
        """
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="failed")
        kill: _KillRecorder = _KillRecorder()
        schedule: _ScheduleRecorder = _ScheduleRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill, schedule=schedule)
        monkeypatch.setattr(
            store,
            "relaunch",
            AsyncMock(side_effect=WorkflowStateTransitionError("workflow wf-1 is running")),
        )

        @asynccontextmanager
        async def rejected_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield a synthetic owned workload without launching a CLI child."""
            del handle, history_root
            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=lambda *, expected_pid: None)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=rejected_adoption):
            result: str = await service.resume(workflow_id="wf-1")

        assert result == "could not relaunch workflow wf-1: workflow wf-1 is running"
        assert kill.calls == [(5678, signal.SIGTERM)]
        assert len(schedule.scheduled) == 1
        assert schedule.scheduled[0][0] == 5.0

    @pytest.mark.asyncio
    async def test_resume_retains_adopted_pid_when_capture_activation_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An activated capture failure preserves the durable workload identity.

        The fake ownership represents only the current command-owned workload;
        it cannot execute ``src.cli run``. Its activation raises after the
        store has adopted the PID, proving the error path does not roll the
        handle back to its terminal reservation state.
        """
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)

        @asynccontextmanager
        async def activation_fails(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield a fake owned workload and fail only at post-adoption activation."""
            del handle, history_root

            def activate(*, expected_pid: int) -> None:
                """Fail after verifying the current test-owned workload PID."""
                assert expected_pid == 5678
                raise OSError("controlled capture activation failure")

            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=activate)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=activation_fails):
            result: str = await service.resume(workflow_id="wf-1")

        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert result == "workflow wf-1 resume failed"
        assert handle is not None
        assert handle.state == "launching"
        assert handle.pid == 5678
        assert handle.capture_health is not None
        assert handle.capture_health.failure_code == "capture_writer_failed"
        assert kill.calls == []

    @pytest.mark.asyncio
    async def test_resume_cancellation_before_durable_adoption_stops_owned_workload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancellation before relaunch adoption stops only the owned replacement.

        WHAT: Holds the store adoption await after the context manager yields, then
            cancels the command and verifies its private replacement process is
            cooperatively stopped and the reservation is restored.
        WHO: The workflow command-service lifecycle suite exercises this boundary.
        WHEN: Whenever resume cancellation or ownership transfer changes.

        Args:
            tmp_path (Path): Test-scoped durable history root.
            monkeypatch (pytest.MonkeyPatch): Controlled store-adoption fixture.
        """
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)
        adoption_started: asyncio.Event = asyncio.Event()
        release_adoption: asyncio.Event = asyncio.Event()

        async def blocked_relaunch(**_: object) -> WorkflowHandleDAO:
            """Block the durable adoption boundary until the test cancels it."""
            adoption_started.set()
            await release_adoption.wait()
            raise AssertionError("cancelled adoption must not complete")

        monkeypatch.setattr(store, "relaunch", blocked_relaunch)

        @asynccontextmanager
        async def owned_replacement(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield only the synthetic replacement owned by this command."""
            del handle, history_root
            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=lambda *, expected_pid: None)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=owned_replacement):
            resume_task: asyncio.Task[str] = asyncio.create_task(service.resume(workflow_id="wf-1"))
            await adoption_started.wait()
            resume_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await resume_task

        handle: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-1",
        )
        assert kill.calls == [(5678, signal.SIGTERM)]
        assert handle is not None
        assert handle.state == "failed"

    @pytest.mark.asyncio
    async def test_resume_cancellation_after_durable_adoption_preserves_workload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancellation after adoption leaves the durably retained workload unsignalled.

        WHAT: Cancels the activation await only after the store persists the
            actual replacement PID, preserving its lifecycle and identity.
        WHO: The workflow command-service lifecycle suite exercises this boundary.
        WHEN: Whenever post-adoption cancellation handling changes.

        Args:
            tmp_path (Path): Test-scoped durable history root.
            monkeypatch (pytest.MonkeyPatch): Post-adoption activation fixture.
        """
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        kill: _KillRecorder = _KillRecorder()
        service: WorkflowCommandService = _build_service(store=store, kill=kill)
        activation_started: asyncio.Event = asyncio.Event()

        @asynccontextmanager
        async def adopted_replacement(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield a synthetic retained workload with a cancellable activation seam."""
            del handle, history_root

            async def activate(*, expected_pid: int) -> None:
                """Block after asserting the durable workload identity."""
                assert expected_pid == 5678
                activation_started.set()
                await asyncio.Event().wait()

            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=activate)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=adopted_replacement):
            resume_task: asyncio.Task[str] = asyncio.create_task(service.resume(workflow_id="wf-1"))
            await activation_started.wait()
            resume_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await resume_task

        handle: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-1",
        )
        assert kill.calls == []
        assert handle is not None
        assert handle.state == "launching"
        assert handle.pid == 5678

    async def test_resume_reports_spawn_failure_without_state_change(self, tmp_path: Path) -> None:
        """A failed relaunch leaves the durable terminal handle unchanged."""
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="stalled")
        service: WorkflowCommandService = _build_service(store=store)

        @asynccontextmanager
        async def failed_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Raise before yielding so no workload can be launched by this test."""
            del handle, history_root
            raise OSError("workflow resume failed: unavailable")
            yield

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=failed_adoption):
            result: str = await service.resume(workflow_id="wf-1")

        handle: Optional[WorkflowHandleDAO] = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-1",
        )
        assert result == "workflow wf-1 resume failed"
        assert handle is not None
        assert handle.state == "stalled"

    @pytest.mark.asyncio
    async def test_resume_admits_one_spawn_across_distinct_service_instances(self, tmp_path: Path) -> None:
        """A durable reservation prevents a second service instance from spawning.

        WHAT: Holds the first controlled relaunch at its workload-execution
            boundary, then proves a second command service sharing the same
            store returns without reaching that boundary.
        WHO: The workflow command-service concurrency regression suite invokes
            this test.
        WHEN: Whenever durable resume admission or its locking changes.

        Args:
            tmp_path (Path): Test-scoped durable history root.
        """
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        first_service: WorkflowCommandService = _build_service(store=store)
        second_service: WorkflowCommandService = _build_service(store=store)
        first_spawn_entered: asyncio.Event = asyncio.Event()
        release_first_spawn: asyncio.Event = asyncio.Event()
        workload_execution_count: int = 0

        @asynccontextmanager
        async def controlled_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Record ownership entry and yield a synthetic workload only."""
            del handle, history_root
            nonlocal workload_execution_count
            workload_execution_count += 1
            if workload_execution_count == 1:
                first_spawn_entered.set()
                await release_first_spawn.wait()
            pid: int = 5678 if workload_execution_count == 1 else 9876
            yield SimpleNamespace(process=SimpleNamespace(pid=pid), activate=lambda *, expected_pid: None)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=controlled_adoption):
            first_resume: asyncio.Task[str] = asyncio.create_task(first_service.resume(workflow_id="wf-1"))
            await first_spawn_entered.wait()
            second_result: str = await second_service.resume(workflow_id="wf-1")
            release_first_spawn.set()
            first_result: str = await first_resume

        assert workload_execution_count == 1
        assert second_result == "workflow wf-1 is launching — only stalled or failed workflows can be resumed"
        assert first_result == (
            "workflow wf-1 resumed (pid 5678); history replaying — state advances to running on the first heartbeat"
        )

    @pytest.mark.asyncio
    async def test_resume_restores_reservation_when_spawn_fails(self, tmp_path: Path) -> None:
        """Spawn failure rolls the durable reservation back to its resumable state."""
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        service: WorkflowCommandService = _build_service(store=store)

        @asynccontextmanager
        async def failed_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Fail before workload ownership becomes available."""
            del handle, history_root
            raise OSError("workflow resume failed: unavailable")
            yield

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=failed_adoption):
            result: str = await service.resume(workflow_id="wf-1")

        handle: Optional[WorkflowHandleDAO] = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-1",
        )
        assert result == "workflow wf-1 resume failed"
        assert handle is not None
        assert handle.state == "failed"

    @pytest.mark.asyncio
    async def test_resume_confirms_with_new_pid(self, tmp_path: Path) -> None:
        """A successful relaunch moves the handle to launching and names its pid."""
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        service: WorkflowCommandService = _build_service(store=store)

        @asynccontextmanager
        async def successful_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield a controlled process-shaped object without spawning a child."""
            del handle, history_root
            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=lambda *, expected_pid: None)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=successful_adoption):
            result: str = await service.resume(workflow_id="wf-1")

        handle: Optional[WorkflowHandleDAO] = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-1",
        )
        assert result == (
            "workflow wf-1 resumed (pid 5678); history replaying — state advances to running on the first heartbeat"
        )
        assert handle is not None
        assert handle.state == "launching"
        assert handle.pid == 5678


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


class TestTypedCommandResults:
    """Typed dismiss/resume results feed observation suppression (feature 94 a.2)."""

    @pytest.mark.asyncio
    async def test_successful_dismiss_names_the_workflow(self, tmp_path: Path) -> None:
        """Only a durable stalled→failed dismissal carries the dismissed id."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="stalled")
        service: WorkflowCommandService = _build_service(store=store)

        result: WorkflowCommandResultDAO = await service.dismiss_result(workflow_id="wf-1")

        assert result == WorkflowCommandResultDAO(
            rendered="workflow wf-1 dismissed (stalled → failed)",
            dismissed_workflow_id="wf-1",
        )
        handle = await store.read(owner_session_id=_OWNER_SESSION_ID, workflow_id="wf-1")
        assert handle is not None
        assert handle.state == "failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("state", "workflow_id", "rendered"),
        [
            ("running", "wf-1", "workflow wf-1 is running — only stalled workflows can be dismissed"),
            ("stalled", "wf-nope", "no workflow wf-nope"),
        ],
    )
    async def test_refused_dismiss_names_nothing(
        self, tmp_path: Path, state: WorkflowState, workflow_id: str, rendered: str
    ) -> None:
        """Refusals keep their text and never signal a dismissal."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state=state)
        service: WorkflowCommandService = _build_service(store=store)

        result: WorkflowCommandResultDAO = await service.dismiss_result(workflow_id=workflow_id)

        assert result == WorkflowCommandResultDAO(rendered=rendered)

    @pytest.mark.asyncio
    async def test_failed_dismiss_transition_names_nothing(self, tmp_path: Path) -> None:
        """A lost transition race keeps the existing error text without a dismissal."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="stalled")
        service: WorkflowCommandService = _build_service(store=store)
        with patch.object(
            store, "update_state", AsyncMock(side_effect=WorkflowStateTransitionError("raced"))
        ):
            result: WorkflowCommandResultDAO = await service.dismiss_result(workflow_id="wf-1")

        assert result == WorkflowCommandResultDAO(rendered="could not dismiss workflow wf-1: raced")

    @pytest.mark.asyncio
    async def test_successful_resume_names_the_workflow(self, tmp_path: Path) -> None:
        """A confirmed relaunch carries the resumed id beside the unchanged text."""
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        service: WorkflowCommandService = _build_service(store=store)

        @asynccontextmanager
        async def successful_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Yield a controlled process-shaped object without spawning a child."""
            del handle, history_root
            yield SimpleNamespace(process=SimpleNamespace(pid=5678), activate=lambda *, expected_pid: None)

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=successful_adoption):
            result: WorkflowCommandResultDAO = await service.resume_result(workflow_id="wf-1")

        assert result.resumed_workflow_id == "wf-1"
        assert result.dismissed_workflow_id is None
        assert result.rendered.startswith("workflow wf-1 resumed (pid 5678)")

    @pytest.mark.asyncio
    async def test_failed_resume_names_nothing(self, tmp_path: Path) -> None:
        """A spawn failure keeps its safe text and never clears suppression."""
        from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _write_handle(store=store, state="failed")
        service: WorkflowCommandService = _build_service(store=store)

        @asynccontextmanager
        async def failed_adoption(*, handle: WorkflowHandleDAO, history_root: Path):
            """Fail before workload ownership becomes available."""
            del handle, history_root
            raise OSError("workflow resume failed: unavailable")
            yield

        with patch.object(WorkflowRelauncher, "spawn_for_adoption", new=failed_adoption):
            result: WorkflowCommandResultDAO = await service.resume_result(workflow_id="wf-1")

        assert result == WorkflowCommandResultDAO(rendered="workflow wf-1 resume failed")

    @pytest.mark.asyncio
    async def test_refused_resume_names_nothing(self, tmp_path: Path) -> None:
        """A running workflow refusal carries no resumed id."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _write_handle(store=store, state="running")
        service: WorkflowCommandService = _build_service(store=store)

        result: WorkflowCommandResultDAO = await service.resume_result(workflow_id="wf-1")

        assert result == WorkflowCommandResultDAO(
            rendered="workflow wf-1 is running — only stalled or failed workflows can be resumed"
        )

    def test_result_rejects_both_signals(self) -> None:
        """One command result never claims dismissal and resume together."""
        with pytest.raises(ValueError):
            WorkflowCommandResultDAO(rendered="x", dismissed_workflow_id="wf-1", resumed_workflow_id="wf-1")
