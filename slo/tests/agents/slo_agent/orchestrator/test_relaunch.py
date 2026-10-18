"""Tests for resumed detached-workflow orchestrator spawning (spec 71.a.8)."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import IO
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


async def test_resume_does_not_restore_initial_reasoning(tmp_path: Path) -> None:
    """Initial high is not a durable handle field or a reconstructed resume flag."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher
    from src.agents.slo_agent.preferences.service import UserPreferencesStore
    from src.cli.typer_dispatch import TyperDispatch
    from tests.agents.slo_agent.orchestrator.test_launch_tool import _build_tool, _FakeSpawn

    spawn = _FakeSpawn()
    launch = _build_tool(tmp_path=tmp_path, spawn=spawn, default_reasoning_level="high")
    handle = WorkflowHandleDAO.model_validate_json(
        await launch.ainvoke({"brief": "bounded", "cwd": str(tmp_path)})
    )
    assert spawn.argv is not None
    assert spawn.argv[-2:] == ("--reasoning", "high")
    assert "reasoning_level" not in handle.model_dump()
    argv = WorkflowRelauncher._build_argv(handle=handle)
    assert "--reasoning" not in argv
    assert argv[argv.index("--resume") + 1] == handle.orchestrator_session_id
    assert argv[argv.index("--notify-session") + 1] == handle.owner_session_id
    assert argv[argv.index("--cwd") + 1] == str(tmp_path)
    UserPreferencesStore.upsert(reasoning_level="low")
    config = TyperDispatch._build_session_config(workdir=tmp_path, model="gpt-5.4")
    assert TyperDispatch._apply_reasoning_override(config=config, reasoning=None).reasoning_level == "low"


def test_build_argv_resumes_original_session_and_brief() -> None:
    """The relaunch argv retains the durable brief, owner, and resume session."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    argv: list[str] = WorkflowRelauncher._build_argv(handle=_build_handle())

    assert argv[:5] == [sys.executable, "-I", "-m", "src.cli", "run"]
    assert argv.count("-I") == 1
    assert "-p" in argv
    assert argv[argv.index("-p") + 1] == "resume the original workflow"
    assert argv[argv.index("--resume") + 1] == "orchestrator-1"
    assert argv[argv.index("--notify-session") + 1] == "owner-1"


def test_build_argv_omits_session_id_flag() -> None:
    """Resume argv never supplies a competing new session id."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    argv: list[str] = WorkflowRelauncher._build_argv(handle=_build_handle())

    assert "--session-id" not in argv


def test_two_os_processes_reserve_exactly_one_resume_workload(tmp_path: Path) -> None:
    """Independent interpreters use the durable reservation to admit one workload.

    The first process blocks at a test-owned barrier after reservation. The second
    process must observe the durable ``launching`` state and refuse; both child
    interpreters are finite, reaped normally, and write only under ``tmp_path``.
    """
    root: Path = tmp_path.resolve()
    history_root: Path = root / "history"
    barrier_path: Path = root / "reservation-entered"
    release_path: Path = root / "release-reservation"
    result_path: Path = root / "result.json"
    for path in (history_root, barrier_path, release_path, result_path):
        assert path.resolve(strict=False).is_relative_to(root)
    store: WorkflowHandleStore = WorkflowHandleStore(history_root=history_root, pid_alive=lambda pid: False)
    handle: WorkflowHandleDAO = _build_handle().model_copy(update={"state": "failed", "cwd": str(root)})
    awaitable = store.write(handle=handle)
    import asyncio

    asyncio.run(awaitable)
    source_root: Path = Path(__file__).resolve().parents[4]
    script: str = """
import asyncio
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore
root = Path(sys.argv[2]).resolve()
role = sys.argv[3]
store = WorkflowHandleStore(history_root=root / 'history', pid_alive=lambda pid: False)
async def run():
    try:
        await store.reserve_relaunch(owner_session_id='owner-1', workflow_id='wf-1')
    except Exception as exc:
        print('refused:' + type(exc).__name__)
        return
    (root / 'reservation-entered').write_text('entered', encoding='utf-8')
    while not (root / 'release-reservation').exists():
        await asyncio.sleep(0.01)
    (root / 'result.json').write_text(json.dumps({'workloads': 1, 'pid': os.getpid()}), encoding='utf-8')
    print('admitted')
asyncio.run(run())
"""
    first = subprocess.Popen(
        args=[sys.executable, "-I", "-B", "-c", script, str(source_root), str(root), "first"],
        cwd=root,
        env={"HOME": str(root / "home")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(500):
            if barrier_path.exists():
                break
            import time

            time.sleep(0.01)
        assert barrier_path.exists()
        second = subprocess.run(
            args=[sys.executable, "-I", "-B", "-c", script, str(source_root), str(root), "second"],
            cwd=root,
            env={"HOME": str(root / "home")},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=10,
        )
        assert second.returncode == 0
        assert second.stdout == "refused:WorkflowStateTransitionError\n"
        release_path.write_text("release", encoding="utf-8")
        first_stdout, first_stderr = first.communicate(timeout=10)
    finally:
        if first.poll() is None:
            release_path.write_text("release", encoding="utf-8")
            first.communicate(timeout=10)
    assert first.returncode == 0
    assert first_stdout == "admitted\n"
    assert "Traceback" not in first_stderr
    assert json.loads(result_path.read_text(encoding="utf-8"))["workloads"] == 1


async def test_spawn_for_adoption_cancellation_while_append_lease_waits_never_spawns_workload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel a waiting replacement opener before it can acquire a released append lease.

    WHAT: Holds the real sibling append lease until the replacement reaches its
        acquisition boundary, then cancels the owner and proves no delayed thread
        can acquire it or create a workload.
    WHO: The relaunch capture regression suite exercises this ownership boundary.
    WHEN: Whenever asynchronous append-lease acquisition or cancellation changes.

    Args:
        tmp_path (Path): Resolved pytest-owned root for every test artifact.
        monkeypatch (pytest.MonkeyPatch): Scoped runtime seam replacement.
    """
    from src.agents.slo_agent.orchestrator import spawn_env
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    root: Path = tmp_path.resolve()
    history_root: Path = root / "history"
    capture_path: Path = history_root / "orchestrator-1" / "stdout.jsonl"
    lock_path: Path = capture_path.with_suffix(capture_path.suffix + ".append.lock")
    for path in (history_root, capture_path, lock_path):
        assert path.resolve(strict=False).is_relative_to(root)
    capture_path.parent.mkdir(parents=True)
    held_lock_fd: int = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(held_lock_fd, fcntl.LOCK_EX)
    lease_attempted: threading.Event = threading.Event()
    real_acquire = spawn_env._acquire_capture_append_lease

    def signal_then_acquire(*, capture_path: Path) -> int:
        """Expose the real lease wait boundary without changing its ownership semantics.

        Args:
            capture_path (Path): Test-owned capture path passed to the real acquirer.

        Returns:
            int: Descriptor returned by the real capture lease acquisition.
        """
        lease_attempted.set()
        return real_acquire(capture_path=capture_path)

    spawn: AsyncMock = AsyncMock()
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", "synthetic-cancellation-key")
    monkeypatch.setattr(spawn_env, "_acquire_capture_append_lease", signal_then_acquire)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def enter_relaunch_context() -> None:
        """Enter the replacement lifetime only if capture setup incorrectly succeeds."""
        async with WorkflowRelauncher.spawn_for_adoption(
            handle=_build_handle().model_copy(update={"cwd": str(root)}),
            history_root=history_root,
        ):
            raise AssertionError("a cancelled replacement opener created a workload")

    task: asyncio.Task[None] = asyncio.create_task(enter_relaunch_context())
    try:
        await asyncio.wait_for(asyncio.to_thread(lease_attempted.wait), timeout=5)
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        fcntl.flock(held_lock_fd, fcntl.LOCK_UN)
        os.close(held_lock_fd)

    await asyncio.sleep(spawn_env._CAPTURE_WRITER_CLOSE_WAIT_SECONDS + 0.1)
    verification_lock_fd: int = os.open(lock_path, os.O_WRONLY)
    try:
        fcntl.flock(verification_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(verification_lock_fd)
    spawn.assert_not_awaited()


@pytest.mark.parametrize("name", ["stdout.jsonl", "stderr.log"])
async def test_cancelled_late_capture_open_closes_endpoint_without_workload_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Close a successful late opener result for either capture stream."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    root = tmp_path.resolve()
    release = asyncio.Event()
    endpoint_closed = threading.Event()
    spawn = AsyncMock()

    class Endpoint(BytesIO):
        """Binary endpoint that records late ownership teardown."""

        def close(self) -> None:
            """Close the binary stream and signal the late cleanup observer."""
            super().close()
            endpoint_closed.set()

    async def late_opener(**kwargs: object) -> IO[bytes]:
        """Return an endpoint only after the test has cancelled its waiter."""
        assert kwargs["name"] == name
        await release.wait()
        return Endpoint()

    opener = asyncio.create_task(late_opener(name=name))
    cleanup = asyncio.create_task(WorkflowRelauncher._close_late_capture_result(opener=opener))
    await asyncio.sleep(0)
    assert not endpoint_closed.is_set()
    release.set()
    await cleanup
    assert endpoint_closed.is_set()
    spawn.assert_not_awaited()


async def test_invoke_when_spawn_error_contains_environment_credential_returns_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relaunch spawn error cannot export the captured environment credential."""
    from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher

    secret: str = "synthetic-relaunch-spawn-secret"
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", secret)
    spawn: AsyncMock = AsyncMock(side_effect=OSError(f"spawn unavailable: {secret}"))
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)

    outcome = await WorkflowRelauncher.invoke(handle=_build_handle(), history_root=tmp_path)

    assert outcome.pid is None
    assert outcome.error == "workflow resume failed"
    assert secret not in outcome.model_dump_json()


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
