"""Tests for resumed detached-workflow orchestrator spawning (spec 71.a.8)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowStateTransitionError,
)


def _build_handle() -> WorkflowHandleDAO:
    """Build the terminal workflow handle consumed by relaunch tests."""
    return WorkflowHandleDAO(
        workflow_id="wf-1",
        owner_session_id="owner-1",
        orchestrator_session_id="orchestrator-1",
        pid=1234,
        brief="resume the original workflow",
        cwd="/workspace",
        state="stalled",
    )


def test_build_argv_resumes_original_session_and_brief() -> None:
    """The relaunch argv retains the durable brief, owner, and resume session."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    argv: list[str] = WorkflowRelauncher._build_argv(handle=_build_handle())

    assert argv[:4] == [sys.executable, "-m", "src.cli", "run"]
    assert "-I" not in argv
    assert "-p" in argv
    assert argv[argv.index("-p") + 1] == "resume the original workflow"
    assert argv[argv.index("--resume") + 1] == "orchestrator-1"
    assert argv[argv.index("--notify-session") + 1] == "owner-1"


def test_build_argv_omits_session_id_flag() -> None:
    """Resume argv never supplies a competing new session id."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    argv: list[str] = WorkflowRelauncher._build_argv(handle=_build_handle())

    assert "--session-id" not in argv


async def test_invoke_returns_error_on_spawn_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process spawn OSError becomes an operator-safe result, not an exception."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    spawn: AsyncMock = AsyncMock(side_effect=OSError("spawn unavailable"))
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)

    outcome = await WorkflowRelauncher.invoke(handle=_build_handle(), history_root=tmp_path)

    assert outcome.pid is None
    assert outcome.error == "workflow resume failed: spawn unavailable"


async def test_invoke_preserves_workflow_id_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The resumed child inherits the same workflow identity in its environment."""
    from src.agents.slo_agent.orchestrator.relaunch import RelaunchOutcomeDAO, WorkflowRelauncher

    process: SimpleNamespace = SimpleNamespace(pid=4321)
    spawn: AsyncMock = AsyncMock(return_value=process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)

    outcome: RelaunchOutcomeDAO = await WorkflowRelauncher.invoke(
        handle=_build_handle(), history_root=tmp_path
    )
    await_args = spawn.await_args

    assert outcome.pid == 4321
    assert await_args is not None
    assert await_args.kwargs["env"]["SLO_WORKFLOW_ID"] == "wf-1"


async def _write_handle(*, store: WorkflowHandleStore, state: str) -> WorkflowHandleDAO:
    """Persist one workflow handle in the requested test state."""
    handle: WorkflowHandleDAO = _build_handle().model_copy(update={"state": state})
    await store.write(handle=handle)
    return handle


async def test_relaunch_moves_stalled_to_launching_with_pid(tmp_path: Path) -> None:
    """The dedicated relaunch edge patches a stalled handle with the new pid."""
    store: WorkflowHandleStore = WorkflowHandleStore(history_root=tmp_path)
    await _write_handle(store=store, state="stalled")

    updated: WorkflowHandleDAO = await store.relaunch(
        owner_session_id="owner-1",
        workflow_id="wf-1",
        new_pid=4321,
    )

    assert updated.state == "launching"
    assert updated.pid == 4321


async def test_relaunch_moves_failed_to_launching(tmp_path: Path) -> None:
    """The dedicated relaunch edge permits a failed handle to launch again."""
    store: WorkflowHandleStore = WorkflowHandleStore(history_root=tmp_path)
    await _write_handle(store=store, state="failed")

    updated: WorkflowHandleDAO = await store.relaunch(
        owner_session_id="owner-1",
        workflow_id="wf-1",
        new_pid=4321,
    )

    assert updated.state == "launching"


async def test_relaunch_rejects_fresh_running_status_evidence(tmp_path: Path) -> None:
    """The locked relaunch edge refuses fresh same-workflow running evidence.

    WHAT: Verifies relaunch revalidates the durable status file immediately
        before it patches a replacement process id.
    WHO: The 71.a.8 relaunch unit suite calls this regression test.
    WHEN: Whenever the flock-protected relaunch admission boundary changes.

    Args:
        tmp_path (Path): Test-scoped history root.
    """
    from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
    from src.agents.slo_agent.orchestrator.dao import OrchestratorStatusDAO
    from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

    store: WorkflowHandleStore = WorkflowHandleStore(history_root=tmp_path, pid_alive=lambda pid: False)
    handle: WorkflowHandleDAO = await _write_handle(store=store, state="stalled")
    AtomicFileWriter.write_json(
        path=OrchestrationLayout.orchestrator_status_path(
            history_root=tmp_path,
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

    with pytest.raises(WorkflowStateTransitionError, match="fresh running evidence"):
        await store.relaunch(
            owner_session_id="owner-1",
            workflow_id="wf-1",
            new_pid=4321,
        )


@pytest.mark.parametrize("state", ["running", "completed", "aborted"])
async def test_relaunch_rejects_non_resumable_states(tmp_path: Path, state: str) -> None:
    """Live and final workflow states cannot enter the relaunch-only edge."""
    store: WorkflowHandleStore = WorkflowHandleStore(history_root=tmp_path)
    await _write_handle(store=store, state=state)

    with pytest.raises(WorkflowStateTransitionError, match="relaunch"):
        await store.relaunch(
            owner_session_id="owner-1",
            workflow_id="wf-1",
            new_pid=4321,
        )
