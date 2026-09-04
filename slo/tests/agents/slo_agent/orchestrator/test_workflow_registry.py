"""Tests for the workflow handle registry (spec 57.a.1)."""

from __future__ import annotations

import asyncio
import fcntl
import json
import multiprocessing
import queue
from multiprocessing.synchronize import Event
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import OrchestratorStatusDAO
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowState,
    WorkflowStateTransitionError,
    WorkflowStatusTool,
)

_OWNER_SESSION_ID: str = "tui-session-1"


def _build_store(
    *,
    tmp_path: Path,
    pid_alive: bool = True,
) -> WorkflowHandleStore:
    """Build a handle store rooted under ``tmp_path`` with an injected liveness probe.

    Args:
        tmp_path (Path): Pytest tmp path.
        pid_alive (bool, optional): Fixed liveness result. Defaults to ``True``.

    Returns:
        WorkflowHandleStore: Test-scoped handle store.
    """
    return WorkflowHandleStore(
        history_root=tmp_path / "history",
        pid_alive=lambda pid: pid_alive,
    )


def _build_handle(
    *,
    workflow_id: str = "wf-3f2a",
    state: WorkflowState = "launching",
    pid: int = 4242,
    started_at: datetime | None = None,
) -> WorkflowHandleDAO:
    """Build one deterministic workflow handle.

    Args:
        workflow_id (str, optional): Workflow id. Defaults to ``"wf-3f2a"``.
        state (WorkflowState, optional): Initial state. Defaults to ``"launching"``.
        pid (int, optional): Process id. Defaults to ``4242``.
        started_at (datetime | None, optional): Launch timestamp override.

    Returns:
        WorkflowHandleDAO: Deterministic handle fixture.
    """
    return WorkflowHandleDAO(
        workflow_id=workflow_id,
        owner_session_id=_OWNER_SESSION_ID,
        orchestrator_session_id="orch-session-1",
        pid=pid,
        brief="run the code-test-review workflow for spec 57",
        cwd="/repo",
        state=state,
        started_at=started_at or datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
    )


def _build_status(
    *,
    state: str = "running",
    updated_at: datetime | None = None,
    workflow_id: str = "wf-3f2a",
    orchestrator_session_id: str = "orch-session-1",
) -> OrchestratorStatusDAO:
    """Build one deterministic self-reported orchestrator status.

    Args:
        state (str, optional): Self-reported workflow state. Defaults to ``"running"``.
        updated_at (datetime | None, optional): Evidence timestamp override.
        workflow_id (str, optional): Workflow identity for evidence matching.
        orchestrator_session_id (str, optional): Orchestrator identity for matching.

    Returns:
        OrchestratorStatusDAO: Status evidence for the fixture orchestrator.
    """
    return OrchestratorStatusDAO(
        workflow_id=workflow_id,
        orchestrator_session_id=orchestrator_session_id,
        pid=4242,
        state=state,  # type: ignore[arg-type]
        updated_at=(updated_at or datetime.now(timezone.utc)).isoformat(),
    )


def _write_status(*, tmp_path: Path, status: OrchestratorStatusDAO) -> None:
    """Persist status evidence where reconcile resolves it.

    Args:
        tmp_path (Path): Pytest temporary directory.
        status (OrchestratorStatusDAO): Self-reported evidence to persist.
    """
    AtomicFileWriter.write_json(
        path=OrchestrationLayout.orchestrator_status_path(
            history_root=tmp_path / "history",
            orchestrator_session_id=status.orchestrator_session_id,
        ),
        model=status,
    )


def _update_state_in_child(*, history_root: str, result_queue: multiprocessing.Queue[str]) -> None:
    """Attempt one handle transition from a separate operating-system process.

    Args:
        history_root (str): String form of the temporary history root.
        result_queue (multiprocessing.Queue[str]): IPC queue for the result state.
    """
    child_store: WorkflowHandleStore = WorkflowHandleStore(
        history_root=Path(history_root),
        pid_alive=lambda pid: True,
    )
    updated: WorkflowHandleDAO = asyncio.run(
        child_store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="running",
        )
    )
    result_queue.put(updated.state)


def _reconcile_in_child(
    *,
    history_root: str,
    ready_queue: multiprocessing.Queue[str],
    start_event: Event,
    result_queue: multiprocessing.Queue[str],
    lock_attempt_queue: multiprocessing.Queue[str] | None = None,
) -> None:
    """Reconcile matching terminal evidence from a separate operating-system process.

    WHAT: Waits for a shared start signal, then reconciles one durable workflow
        handle using a store constructed in this child process.
    WHO: Called by the concurrent correction regression test.
    WHEN: Whenever correction locking or evidence reconciliation changes.

    Args:
        history_root (str): Temporary durable-history root.
        ready_queue (multiprocessing.Queue[str]): Signals child readiness.
        start_event (Event): Releases both child reconciliations together.
        result_queue (multiprocessing.Queue[str]): Receives the reconciled state.
        lock_attempt_queue (multiprocessing.Queue[str] | None): Optional signal
            emitted at the real ``flock(LOCK_EX)`` call boundary.
    """
    child_store: WorkflowHandleStore = WorkflowHandleStore(
        history_root=Path(history_root),
        pid_alive=lambda pid: False,
    )
    ready_queue.put("ready")
    start_event.wait(timeout=2)

    if lock_attempt_queue is None:
        reconciled: list[WorkflowHandleDAO] = asyncio.run(
            child_store.reconcile(owner_session_id=_OWNER_SESSION_ID)
        )
    else:
        original_flock = fcntl.flock

        def signal_lock_attempt(lock_file: object, operation: int) -> object:
            """Signal immediately before the correction path invokes ``flock``."""
            if operation == fcntl.LOCK_EX:
                lock_attempt_queue.put("attempt")
            return original_flock(lock_file, operation)

        with patch(
            "src.agents.slo_agent.orchestrator.workflow_registry.fcntl.flock",
            side_effect=signal_lock_attempt,
        ):
            reconciled = asyncio.run(child_store.reconcile(owner_session_id=_OWNER_SESSION_ID))

    result_queue.put(reconciled[0].state)


async def _seed_handle(
    *,
    store: WorkflowHandleStore,
    handle: WorkflowHandleDAO,
) -> Path:
    """Write one handle through the store's public API.

    Args:
        store (WorkflowHandleStore): Store under test.
        handle (WorkflowHandleDAO): Handle to persist.

    Returns:
        Path: Persisted handle path.
    """
    return await store.write(handle=handle)


class TestDefaultPidAlive:
    """``WorkflowHandleStore`` delegates PID liveness to ``ProcessProbe``."""

    def test_default_pid_alive_returns_false_for_missing_pid(self) -> None:
        """A missing-process probe result remains false through the store seam."""
        with patch(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive",
            return_value=False,
        ) as probe:
            assert WorkflowHandleStore._default_pid_alive(pid=1234) is False

        probe.assert_called_once_with(pid=1234)

    def test_default_pid_alive_returns_true_for_eprem(self) -> None:
        """A permission-denied probe result remains true through the store seam."""
        with patch(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive",
            return_value=True,
        ) as probe:
            assert WorkflowHandleStore._default_pid_alive(pid=1234) is True

        probe.assert_called_once_with(pid=1234)

    def test_default_pid_alive_returns_true_for_other_oserror(self) -> None:
        """An indeterminate OS-error probe result remains true through the store seam."""
        with patch(
            "src.agents.slo_agent.orchestrator.workflow_registry.ProcessProbe.is_alive",
            return_value=True,
        ) as probe:
            assert WorkflowHandleStore._default_pid_alive(pid=1234) is True

        probe.assert_called_once_with(pid=1234)


class TestWriteAndRead:
    """write() / read() round-trip and miss behaviour."""

    async def test_write_then_read_round_trips_handle(self, tmp_path: Path) -> None:
        """A written handle reads back field-identical."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = _build_handle()

        path: Path = await _seed_handle(store=store, handle=handle)
        loaded: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
        )

        assert loaded == handle
        assert path.name == "wf-3f2a.json"

    async def test_write_sets_private_permissions(self, tmp_path: Path) -> None:
        """Handle files land 0600 inside a 0700 workflows directory."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        path: Path = await _seed_handle(store=store, handle=_build_handle())

        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert path.parent.name == "workflows"

    async def test_read_missing_handle_returns_none(self, tmp_path: Path) -> None:
        """Reading an unknown workflow id returns ``None``."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        loaded: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-nope",
        )

        assert loaded is None

    async def test_write_rejects_state_bypass(self, tmp_path: Path) -> None:
        """Re-writing a handle with a different state must go through update_state."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))

        with pytest.raises(WorkflowStateTransitionError):
            await store.write(handle=_build_handle(state="completed"))

    async def test_write_allows_same_state_rewrite_for_pid_patch(self, tmp_path: Path) -> None:
        """A same-state rewrite (pid patch after spawn) is accepted."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        handle: WorkflowHandleDAO = _build_handle(pid=0)
        await _seed_handle(store=store, handle=handle)

        patched: WorkflowHandleDAO = handle.model_copy(update={"pid": 7777})
        await store.write(handle=patched)
        loaded: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
        )

        assert loaded is not None
        assert loaded.pid == 7777


class TestList:
    """list() ordering and corruption tolerance."""

    async def test_list_orders_by_started_at(self, tmp_path: Path) -> None:
        """Handles list oldest-first regardless of filename order."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        newer: WorkflowHandleDAO = _build_handle(
            workflow_id="wf-aaaa",
            started_at=datetime(2026, 7, 21, 13, 0, tzinfo=timezone.utc),
        )
        older: WorkflowHandleDAO = _build_handle(
            workflow_id="wf-bbbb",
            started_at=datetime(2026, 7, 21, 11, 0, tzinfo=timezone.utc),
        )
        await _seed_handle(store=store, handle=newer)
        await _seed_handle(store=store, handle=older)

        handles: list[WorkflowHandleDAO] = await store.list(owner_session_id=_OWNER_SESSION_ID)

        assert [handle.workflow_id for handle in handles] == ["wf-bbbb", "wf-aaaa"]

    async def test_list_skips_corrupt_handle_file(self, tmp_path: Path) -> None:
        """An unparseable handle file is skipped, not fatal."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(workflow_id="wf-good"))
        workflows_dir: Path = tmp_path / "history" / _OWNER_SESSION_ID / "workflows"
        (workflows_dir / "wf-bad.json").write_text("{not json", encoding="utf-8")

        handles: list[WorkflowHandleDAO] = await store.list(owner_session_id=_OWNER_SESSION_ID)

        assert [handle.workflow_id for handle in handles] == ["wf-good"]

    async def test_list_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        """A session with no workflows directory lists empty."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        assert await store.list(owner_session_id="never-launched") == []


class TestUpdateState:
    """update_state() legal-transition enforcement."""

    async def test_update_state_launching_to_running(self, tmp_path: Path) -> None:
        """launching → running succeeds and persists."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="running",
        )
        loaded: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
        )

        assert updated.state == "running"
        assert loaded is not None and loaded.state == "running"

    async def test_update_state_launching_to_failed(self, tmp_path: Path) -> None:
        """launching → failed (spawn error) succeeds."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="failed",
        )

        assert updated.state == "failed"

    @pytest.mark.parametrize("terminal", ["completed", "failed", "aborted", "stalled"])
    async def test_update_state_running_to_each_exit(self, tmp_path: Path, terminal: str) -> None:
        """running → completed|failed|aborted|stalled all succeed."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="running"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state=terminal,  # type: ignore[arg-type]
        )

        assert updated.state == terminal

    async def test_update_state_launching_to_aborted(self, tmp_path: Path) -> None:
        """launching → aborted (operator abort in the spawn window) succeeds."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="aborted",
        )

        assert updated.state == "aborted"

    async def test_update_state_stalled_to_failed(self, tmp_path: Path) -> None:
        """stalled → failed (operator acknowledgement) succeeds."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="failed",
        )

        assert updated.state == "failed"

    @pytest.mark.parametrize(
        "current,requested",
        [
            ("completed", "running"),
            ("failed", "running"),
            ("aborted", "running"),
            ("launching", "completed"),
            ("launching", "stalled"),
            ("stalled", "running"),
            ("stalled", "completed"),
            ("running", "launching"),
        ],
    )
    async def test_update_state_rejects_correction_edges(
        self,
        tmp_path: Path,
        current: str,
        requested: str,
    ) -> None:
        """Every transition outside the legal table raises."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state=current))  # type: ignore[arg-type]

        with pytest.raises(WorkflowStateTransitionError):
            await store.update_state(
                owner_session_id=_OWNER_SESSION_ID,
                workflow_id="wf-3f2a",
                state=requested,  # type: ignore[arg-type]
            )

    async def test_update_state_same_state_is_noop(self, tmp_path: Path) -> None:
        """A same-state request returns the handle without raising (idempotent re-delivery)."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="running"))

        updated: WorkflowHandleDAO = await store.update_state(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="running",
        )

        assert updated.state == "running"

    async def test_update_state_missing_handle_raises(self, tmp_path: Path) -> None:
        """Advancing a missing handle raises ``FileNotFoundError``."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        with pytest.raises(FileNotFoundError):
            await store.update_state(
                owner_session_id=_OWNER_SESSION_ID,
                workflow_id="wf-missing",
                state="running",
            )


class TestEvidenceCorrection:
    """correct_from_evidence() correction-edge behavior."""

    async def test_correct_from_evidence_rejects_mismatched_evidence(self, tmp_path: Path) -> None:
        """Terminal corrections reject evidence whose state differs from the target."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))

        with pytest.raises(WorkflowStateTransitionError):
            await store.correct_from_evidence(
                owner_session_id=_OWNER_SESSION_ID,
                workflow_id="wf-3f2a",
                state="completed",
                evidence=_build_status(state="failed"),
            )

    async def test_correct_from_evidence_noops_when_already_in_state(self, tmp_path: Path) -> None:
        """An evidence correction leaves an already-agreeing handle unchanged."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="completed"))

        corrected: WorkflowHandleDAO = await store.correct_from_evidence(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
            state="completed",
            evidence=_build_status(state="completed"),
        )

        assert corrected.state == "completed"

    @pytest.mark.parametrize(
        ("workflow_id", "orchestrator_session_id"),
        [
            ("wf-other", "orch-session-1"),
            ("wf-3f2a", "orch-session-other"),
        ],
    )
    async def test_correct_from_evidence_rejects_foreign_identity(
        self,
        tmp_path: Path,
        workflow_id: str,
        orchestrator_session_id: str,
    ) -> None:
        """Evidence for another workflow or orchestrator cannot correct this handle.

        WHAT: Rejects identity-mismatched durable evidence before it reaches a
            correction-only workflow transition.
        WHO: The evidence-backed reconcile regression suite.
        WHEN: Whenever the status admission rule changes.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))
        evidence: OrchestratorStatusDAO = _build_status(
            state="completed",
            workflow_id=workflow_id,
            orchestrator_session_id=orchestrator_session_id,
        )

        with pytest.raises(WorkflowStateTransitionError, match="does not identify"):
            await store.correct_from_evidence(
                owner_session_id=_OWNER_SESSION_ID,
                workflow_id="wf-3f2a",
                state="completed",
                evidence=evidence,
            )


class TestReconcile:
    """reconcile() evidence ladder and legacy PID fallback."""

    async def test_reconcile_corrects_to_completed_from_terminal_evidence(self, tmp_path: Path) -> None:
        """Terminal self-report corrects a running handle before probing its pid."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="completed"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "completed"

    @pytest.mark.parametrize(
        ("workflow_id", "orchestrator_session_id"),
        [
            ("wf-other", "orch-session-1"),
            ("wf-3f2a", "orch-session-other"),
        ],
    )
    async def test_reconcile_ignores_foreign_status_identity(
        self,
        tmp_path: Path,
        workflow_id: str,
        orchestrator_session_id: str,
    ) -> None:
        """Foreign status evidence falls through to legacy dead-PID reconciliation.

        WHAT: Writes a foreign payload at the expected status path and proves
            identity validation prevents it from keeping or completing this handle.
        WHO: The evidence-backed reconcile regression suite.
        WHEN: Whenever durable status evidence is admitted.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        foreign_status: OrchestratorStatusDAO = _build_status(
            state="completed",
            workflow_id=workflow_id,
            orchestrator_session_id=orchestrator_session_id,
        )
        AtomicFileWriter.write_json(
            path=OrchestrationLayout.orchestrator_status_path(
                history_root=tmp_path / "history",
                orchestrator_session_id="orch-session-1",
            ),
            model=foreign_status,
        )

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "stalled"

    async def test_reconcile_corrects_stalled_to_completed(self, tmp_path: Path) -> None:
        """Terminal self-report repairs a premature stalled label."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="completed"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "completed"

    async def test_reconcile_corrects_launching_to_completed(self, tmp_path: Path) -> None:
        """Terminal self-report repairs a fast workflow before its start note arrives."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="completed"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "completed"

    async def test_reconcile_corrects_launching_to_aborted(self, tmp_path: Path) -> None:
        """Terminal abort evidence repairs a workflow before its start note is claimed."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="aborted"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "aborted"

    async def test_reconcile_keeps_running_on_fresh_evidence_despite_dead_pid(self, tmp_path: Path) -> None:
        """Fresh running evidence takes precedence over a false dead-pid probe."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        _write_status(tmp_path=tmp_path, status=_build_status())

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "running"

    async def test_reconcile_advances_launching_on_fresh_evidence(self, tmp_path: Path) -> None:
        """Fresh running evidence proves a launching orchestrator has started."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))
        _write_status(tmp_path=tmp_path, status=_build_status())

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "running"

    async def test_reconcile_repairs_stalled_to_running_on_fresh_evidence(self, tmp_path: Path) -> None:
        """Fresh heartbeat evidence repairs a stalled handle after resume."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))
        _write_status(tmp_path=tmp_path, status=_build_status())

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "running"

    async def test_reconcile_repairs_failed_to_running_on_fresh_evidence(self, tmp_path: Path) -> None:
        """Fresh heartbeat evidence repairs a failed handle after resume."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="failed"))
        _write_status(tmp_path=tmp_path, status=_build_status())

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "running"

    async def test_reconcile_stalls_on_stale_evidence_and_dead_pid(self, tmp_path: Path) -> None:
        """Stale heartbeat evidence falls through to the dead-pid stall path."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        _write_status(
            tmp_path=tmp_path,
            status=_build_status(updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc)),
        )

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "stalled"

    async def test_reconcile_falls_back_to_pid_on_corrupt_status(self, tmp_path: Path) -> None:
        """Unreadable status evidence falls back to the legacy dead-pid result."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        status_path: Path = OrchestrationLayout.orchestrator_status_path(
            history_root=tmp_path / "history",
            orchestrator_session_id="orch-session-1",
        )
        status_path.parent.mkdir(parents=True)
        status_path.write_text("{corrupt", encoding="utf-8")

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "stalled"

    async def test_reconcile_falls_back_to_pid_when_status_timestamp_is_invalid(self, tmp_path: Path) -> None:
        """Parseable status JSON with an invalid timestamp is not liveness evidence."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        invalid_timestamp_status: OrchestratorStatusDAO = _build_status().model_copy(
            update={"updated_at": "not-a-date"},
        )
        _write_status(tmp_path=tmp_path, status=invalid_timestamp_status)

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "stalled"

    async def test_reconcile_leaves_stalled_stalled_without_new_evidence(self, tmp_path: Path) -> None:
        """A stalled handle remains stalled when no new durable evidence exists."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "stalled"

    async def test_reconcile_legacy_pid_fallback_without_status_file(self, tmp_path: Path) -> None:
        """A dead-pid running handle flips to stalled."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(
            owner_session_id=_OWNER_SESSION_ID,
        )

        assert reconciled[0].state == "stalled"

    async def test_reconcile_marks_dead_pid_launching_failed(self, tmp_path: Path) -> None:
        """A dead-pid launching handle flips to failed (spawn never survived)."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(
            owner_session_id=_OWNER_SESSION_ID,
        )

        assert reconciled[0].state == "failed"

    async def test_reconcile_treats_zero_pid_as_dead(self, tmp_path: Path) -> None:
        """An OLD pid-0 launching handle (spawn never completed) reconciles to failed."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        # The fixture's default started_at is well outside _LAUNCH_GRACE_SECONDS.
        await _seed_handle(store=store, handle=_build_handle(state="launching", pid=0))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(
            owner_session_id=_OWNER_SESSION_ID,
        )

        assert reconciled[0].state == "failed"

    async def test_reconcile_spares_young_zero_pid_launching_handle(
        self, tmp_path: Path
    ) -> None:
        """A pid-0 launching handle inside the spawn grace window is untouched.

        The launch tool writes the handle before the spawn and patches the pid
        after; a reconcile pass racing that window (slash commands dispatch
        mid-turn) must not reap the brand-new workflow as failed.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        await _seed_handle(
            store=store,
            handle=_build_handle(
                state="launching",
                pid=0,
                started_at=datetime.now(timezone.utc),
            ),
        )

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(
            owner_session_id=_OWNER_SESSION_ID,
        )

        assert reconciled[0].state == "launching"

    async def test_reconcile_legacy_keeps_live_pid(self, tmp_path: Path) -> None:
        """A live PID keeps a legacy running handle unchanged without status evidence."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        await _seed_handle(store=store, handle=_build_handle(state="running"))

        reconciled: list[WorkflowHandleDAO] = await store.reconcile(owner_session_id=_OWNER_SESSION_ID)

        assert reconciled[0].state == "running"

    async def test_concurrent_corrections_do_not_lose_updates(self, tmp_path: Path) -> None:
        """Two independent reconciles serialize one terminal evidence correction.

        WHAT: Releases two processes against the same stalled handle and proves
            both reconcile calls and the durable projection end completed.
        WHO: The evidence-backed reconciliation regression suite.
        WHEN: The correction writer or its flock scope changes.

        Args:
            tmp_path (Path): Temporary durable-history root supplied by pytest.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="completed"))
        process_context: multiprocessing.context.BaseContext = multiprocessing.get_context("fork")
        ready_queue: multiprocessing.Queue[str] = process_context.Queue()
        result_queue: multiprocessing.Queue[str] = process_context.Queue()
        start_event: Event = process_context.Event()
        processes: list[multiprocessing.Process] = [
            process_context.Process(
                target=_reconcile_in_child,
                kwargs={
                    "history_root": str(tmp_path / "history"),
                    "ready_queue": ready_queue,
                    "start_event": start_event,
                    "result_queue": result_queue,
                },
            )
            for _ in range(2)
        ]

        for process in processes:
            process.start()

        assert [ready_queue.get(timeout=2), ready_queue.get(timeout=2)] == ["ready", "ready"]
        start_event.set()
        assert sorted([result_queue.get(timeout=2), result_queue.get(timeout=2)]) == [
            "completed",
            "completed",
        ]

        for process in processes:
            process.join(timeout=2)
            assert process.exitcode == 0

        persisted: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
        )

        assert persisted is not None
        assert persisted.state == "completed"

    async def test_reconcile_waits_for_cross_process_handle_lock(self, tmp_path: Path) -> None:
        """Terminal evidence correction waits for its handle flock before writing.

        WHAT: Holds the stalled handle's sibling lock while a child process starts
            a matching terminal-evidence reconciliation.
        WHO: The correction-writer concurrency regression suite.
        WHEN: The correction lock scope or reconcile write path changes.

        Args:
            tmp_path (Path): Temporary durable-history root supplied by pytest.
        """
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="stalled"))
        _write_status(tmp_path=tmp_path, status=_build_status(state="completed"))
        handle_path: Path = tmp_path / "history" / _OWNER_SESSION_ID / "workflows" / "wf-3f2a.json"
        lock_path: Path = handle_path.with_suffix(handle_path.suffix + ".lock")
        process_context: multiprocessing.context.BaseContext = multiprocessing.get_context("fork")
        ready_queue: multiprocessing.Queue[str] = process_context.Queue()
        result_queue: multiprocessing.Queue[str] = process_context.Queue()
        lock_attempt_queue: multiprocessing.Queue[str] = process_context.Queue()
        start_event: Event = process_context.Event()

        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            process: multiprocessing.Process = process_context.Process(
                target=_reconcile_in_child,
                kwargs={
                    "history_root": str(tmp_path / "history"),
                    "ready_queue": ready_queue,
                    "start_event": start_event,
                    "result_queue": result_queue,
                    "lock_attempt_queue": lock_attempt_queue,
                },
            )
            process.start()
            assert ready_queue.get(timeout=2) == "ready"
            start_event.set()
            assert lock_attempt_queue.get(timeout=2) == "attempt"
            time.sleep(0.1)
            with pytest.raises(queue.Empty):
                result_queue.get_nowait()
            fcntl.flock(lock_file, fcntl.LOCK_UN)

        assert result_queue.get(timeout=2) == "completed"
        process.join(timeout=2)
        assert process.exitcode == 0
        persisted: WorkflowHandleDAO | None = await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id="wf-3f2a",
        )
        assert persisted is not None
        assert persisted.state == "completed"

    async def test_update_state_waits_for_cross_process_handle_lock(self, tmp_path: Path) -> None:
        """A second process cannot mutate a handle until its sibling flock is released."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(state="launching"))
        handle_path: Path = tmp_path / "history" / _OWNER_SESSION_ID / "workflows" / "wf-3f2a.json"
        lock_path: Path = handle_path.with_suffix(handle_path.suffix + ".lock")
        process_context: multiprocessing.context.BaseContext = multiprocessing.get_context("fork")
        result_queue: multiprocessing.Queue[str] = process_context.Queue()

        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            process: multiprocessing.Process = process_context.Process(
                target=_update_state_in_child,
                kwargs={
                    "history_root": str(tmp_path / "history"),
                    "result_queue": result_queue,
                },
            )
            process.start()
            time.sleep(0.1)
            with pytest.raises(queue.Empty):
                result_queue.get_nowait()
            fcntl.flock(lock_file, fcntl.LOCK_UN)

        assert result_queue.get(timeout=2) == "running"
        process.join(timeout=2)
        assert process.exitcode == 0


class TestAtomicWrite:
    """Atomic temp+rename discipline."""

    async def test_atomic_write_ignores_leftover_tmp(self, tmp_path: Path) -> None:
        """A crash-orphaned ``.tmp`` file is neither listed nor read."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle(workflow_id="wf-good"))
        workflows_dir: Path = tmp_path / "history" / _OWNER_SESSION_ID / "workflows"
        (workflows_dir / "wf-dead.json.tmp").write_text("{partial", encoding="utf-8")

        handles: list[WorkflowHandleDAO] = await store.list(owner_session_id=_OWNER_SESSION_ID)

        assert [handle.workflow_id for handle in handles] == ["wf-good"]

    async def test_write_leaves_no_tmp_file_behind(self, tmp_path: Path) -> None:
        """A completed write leaves only the final handle file."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        path: Path = await _seed_handle(store=store, handle=_build_handle())

        assert sorted(entry.name for entry in path.parent.iterdir()) == [
            "wf-3f2a.json",
            "wf-3f2a.json.lock",
        ]


class TestWorkflowStatusTool:
    """The read-only ``workflow_status`` LangChain tool."""

    async def test_status_tool_returns_single_handle_json(self, tmp_path: Path) -> None:
        """By-id lookup returns that handle's JSON."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        status_tool = WorkflowStatusTool.build(owner_session_id=_OWNER_SESSION_ID, store=store)

        result: str = await status_tool.ainvoke({"workflow_id": "wf-3f2a"})
        parsed: dict = json.loads(result)

        assert parsed["workflow_id"] == "wf-3f2a"
        assert parsed["state"] == "running"

    async def test_status_tool_lists_all_when_id_omitted(self, tmp_path: Path) -> None:
        """No-id lookup returns a JSON array of every handle."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        await _seed_handle(store=store, handle=_build_handle(workflow_id="wf-one"))
        await _seed_handle(
            store=store,
            handle=_build_handle(
                workflow_id="wf-two",
                started_at=datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc),
            ),
        )
        status_tool = WorkflowStatusTool.build(owner_session_id=_OWNER_SESSION_ID, store=store)

        result: str = await status_tool.ainvoke({})
        parsed: list[dict] = json.loads(result)

        assert [entry["workflow_id"] for entry in parsed] == ["wf-one", "wf-two"]

    async def test_status_tool_unknown_id_returns_error_json(self, tmp_path: Path) -> None:
        """Unknown ids return an error JSON string — never raise into the graph."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=True)
        status_tool = WorkflowStatusTool.build(owner_session_id=_OWNER_SESSION_ID, store=store)

        result: str = await status_tool.ainvoke({"workflow_id": "wf-nope"})
        parsed: dict = json.loads(result)

        assert parsed == {"error": "unknown workflow_id: wf-nope"}

    async def test_status_tool_reflects_reconciled_state(self, tmp_path: Path) -> None:
        """The tool reports post-reconcile state (dead running pid → stalled)."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path, pid_alive=False)
        await _seed_handle(store=store, handle=_build_handle(state="running"))
        status_tool = WorkflowStatusTool.build(owner_session_id=_OWNER_SESSION_ID, store=store)

        result: str = await status_tool.ainvoke({"workflow_id": "wf-3f2a"})

        assert json.loads(result)["state"] == "stalled"


class TestWorkflowIdPathSafety:
    """Workflow ids from external input must never escape the workflows dir."""

    @pytest.mark.parametrize("unsafe_id", ["../evil", "a/b", "a\\b", "", "wf-..x"])
    async def test_read_rejects_path_meta_workflow_id(
        self, tmp_path: Path, unsafe_id: str
    ) -> None:
        """An unsafe id reads back as an unknown workflow."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)
        await _seed_handle(store=store, handle=_build_handle())

        assert await store.read(
            owner_session_id=_OWNER_SESSION_ID,
            workflow_id=unsafe_id,
        ) is None

    async def test_update_state_rejects_path_meta_workflow_id(self, tmp_path: Path) -> None:
        """An unsafe id behaves exactly like a missing handle."""
        store: WorkflowHandleStore = _build_store(tmp_path=tmp_path)

        with pytest.raises(FileNotFoundError):
            await store.update_state(
                owner_session_id=_OWNER_SESSION_ID,
                workflow_id="../evil",
                state="failed",
            )
