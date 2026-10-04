"""Streaming and detached lifetime contracts using only owned temporary artifacts."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment
from src.agents.slo_agent.orchestrator.capture_writer import (
    StreamingCredentialRedactor,
    WorkflowCaptureCompletionContext,
)
from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool
from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher
from src.agents.slo_agent.orchestrator.spawn_env import open_capture_file_append
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO


@pytest.mark.parametrize("expected_pid", [4321, 4320])
@pytest.mark.parametrize("fail_write", [True, False])
@pytest.mark.parametrize("with_context", [True, False])
async def test_durable_completion_after_launch_helper_returns(
    tmp_path: Path, expected_pid: int, fail_write: bool, with_context: bool
) -> None:
    """Prove real writer failure, stale identity, clean drain, and legacy behavior.

    The helper returns and closes its ACK endpoint before input is released.
    A regular tmp_path file opened read-only injects the flush failure;
    actual writers and their synchronous reporters naturally exit and are reaped.
    """
    import os
    import subprocess

    from src.agents.slo_agent.orchestrator import capture_writer
    from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore, WorkflowStatusTool

    root = tmp_path.resolve()
    history = root / "history"
    assert history.resolve().is_relative_to(root)
    store = WorkflowHandleStore(history_root=history)
    handle = WorkflowHandleDAO(
        workflow_id="wf-completion",
        owner_session_id="owner",
        orchestrator_session_id="child",
        pid=4321,
        brief="safe",
        cwd=str(root),
        state="running",
    )
    assert (history / "owner/workflows/wf-completion.json").resolve().is_relative_to(root)
    await store.write(handle=handle)
    context = capture_writer.WorkflowCaptureCompletionContext(
        history_root=history,
        owner_session_id="owner",
        workflow_id="wf-completion",
        expected_pid=expected_pid,
    )
    destination = root / "read-only-capture"
    assert destination.resolve().is_relative_to(root)
    destination.write_bytes(b"")

    def launch_writer() -> subprocess.Popen[bytes]:
        """Return after real readiness, closing the launcher's ACK endpoint."""
        ack_read, ack_write = os.pipe()
        try:
            assert destination.resolve().is_relative_to(root)
            with destination.open("rb" if fail_write else "ab") as output:
                process = subprocess.Popen(
                    args=[sys.executable, "-I", "-B", capture_writer.__file__],
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    env={
                        "SLO_CAPTURE_WRITER_ACK_FD": str(ack_write),
                        "SLO_OPENROUTER_API_KEY": "synthetic-completion-secret",
                        **(context.writer_environment() if with_context else {}),
                    },
                    pass_fds=(ack_write,),
                )
            assert os.read(ack_read, 21) == b"capture-writer-ready\n"
            return process
        finally:
            os.close(ack_read)
            os.close(ack_write)

    writer = launch_writer()
    # The launcher has returned and its ACK channel is gone before the fault.
    assert destination.resolve().is_relative_to(root)
    output, error = writer.communicate(input=b"synthetic-completion-secret raw-exception-marker", timeout=15)
    assert writer.returncode == (1 if fail_write else 0)
    assert output is None
    assert error == b""
    reloaded_store = WorkflowHandleStore(history_root=history, pid_alive=lambda pid: True)
    reloaded = await reloaded_store.read(
        owner_session_id="owner",
        workflow_id="wf-completion",
    )
    assert reloaded is not None
    if fail_write and with_context and expected_pid == handle.pid:
        assert reloaded.capture_health is not None
        assert reloaded.capture_health.failure_code == "capture_writer_failed"
        assert (
            reloaded.capture_health.safe_message
            == "Capture writer failed; workflow output may be incomplete."
        )
    else:
        assert reloaded.capture_health is None
    assert reloaded.model_copy(update={"capture_health": None}) == handle
    public_status = await WorkflowStatusTool.build(owner_session_id="owner", store=reloaded_store).ainvoke(
        {"workflow_id": "wf-completion"}
    )
    assert "synthetic-completion-secret" not in public_status
    assert "raw-exception-marker" not in public_status
    assert ("capture_writer_failed" in public_status) == (
        fail_write and with_context and expected_pid == 4321
    )
    assert destination.read_bytes() == (b"" if fail_write else b"[REDACTED] raw-exception-marker")
    for path in history.rglob("*"):
        if path.is_file():
            assert b"synthetic-completion-secret" not in path.read_bytes()
            assert b"raw-exception-marker" not in path.read_bytes()


def test_capture_containment_blocks_unapproved_workload_before_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a ``src.cli run`` workload before the subprocess launcher is reached."""
    root = tmp_path.resolve()
    containment = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    marker = root / "unexpected-workload-ran"

    with pytest.raises(AssertionError, match="inline workload"):
        subprocess.Popen(
            [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"],
            cwd=root,
            env={"HOME": str(root / "home"), "SLO_OPENROUTER_API_KEY": "synthetic-capture-key"},
        )

    assert not marker.exists()
    del containment


def test_capture_containment_blocks_network_before_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an outbound connection before the socket can contact a host."""
    import socket

    containment = CaptureLaunchContainment(root=tmp_path.resolve(), monkeypatch=monkeypatch)

    with pytest.raises(AssertionError, match="external network"):
        socket.create_connection(("example.invalid", 443))

    del containment


def test_capture_containment_requires_explicit_script_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owned path alone is not approval; validation cannot execute the script."""
    script = tmp_path / "unexpected.py"
    assert script.resolve().is_relative_to(tmp_path.resolve())
    script.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    guard = CaptureLaunchContainment(root=tmp_path.resolve(), monkeypatch=monkeypatch)
    with pytest.raises(AssertionError, match="unapproved"):
        guard._validate_spawn(
            args=([sys.executable, "-I", "-B", str(script)],),
            kwargs={"cwd": str(tmp_path), "env": {"HOME": str(tmp_path)}},
        )


@pytest.mark.parametrize("credential", [b"synthetic-secret", b"aaa", b"", b"x"])
def test_every_byte_partition_and_eof(credential: bytes) -> None:
    """Every split and byte-sized chunks preserve safe diagnostics and unmatched EOF."""
    raw = b"safe:" + credential + credential + b":tail"
    expected = raw.replace(credential, b"[REDACTED]") if credential else raw
    for split in range(len(raw) + 1):
        redactor = StreamingCredentialRedactor(credential=credential)
        actual = redactor.feed(raw=raw[:split]) + redactor.feed(raw=raw[split:], final=True)
        assert actual == expected
    redactor = StreamingCredentialRedactor(credential=credential)
    actual = b"".join(redactor.feed(raw=bytes([byte])) for byte in raw)
    assert actual + redactor.feed(raw=b"", final=True) == expected
    redactor = StreamingCredentialRedactor(credential=credential)
    prefix = credential[:-1]
    assert redactor.feed(raw=prefix) + redactor.feed(raw=b"", final=True) == prefix


def test_capture_opener_when_writer_exits_before_acknowledgement_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject capture setup before a workload can inherit an unacknowledged pipe.

    The fake writer represents an immediate clean exit. It owns no workload
    process and all capture paths remain beneath the resolved pytest directory.
    """
    root = tmp_path.resolve()
    capture_path = root / "unacknowledged" / "stdout.jsonl"
    assert capture_path.resolve(strict=False).is_relative_to(root)

    class _ExitedWriter:
        """Minimal writer process that exits without writing startup acknowledgement."""

        def wait(self, timeout: float | None = None) -> int:
            """Report the controlled writer exit without blocking.

            Args:
                timeout (float | None): Ignored test-only wait ceiling.

            Returns:
                int: Controlled successful exit status.
            """
            return 0

    def exited_writer(*args: object, **kwargs: object) -> _ExitedWriter:
        """Return the exited writer without creating a child process.

        Returns:
            _ExitedWriter: Process-shaped controlled writer result.
        """
        return _ExitedWriter()

    monkeypatch.setattr("src.agents.slo_agent.orchestrator.spawn_env.subprocess.Popen", exited_writer)

    with pytest.raises(OSError, match="capture writer did not acknowledge startup"):
        open_capture_file_append(
            history_root=root,
            session_id="unacknowledged",
            name="stdout.jsonl",
            credential="synthetic",
        )

    assert capture_path.read_bytes() == b""


def test_writer_spawn_failure_closes_pipe_fds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No pipe endpoint leaks when the independent writer cannot be spawned."""
    import os

    root = tmp_path.resolve()
    assert (root / "failed").resolve().is_relative_to(root)
    real_pipe = os.pipe
    descriptors: list[int] = []

    def pipe() -> tuple[int, int]:
        """Track only descriptors allocated by this capture attempt."""
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def fail(*args: object, **kwargs: object) -> None:
        """Simulate failure without launching a child."""
        raise OSError("controlled writer failure")

    monkeypatch.setattr("src.agents.slo_agent.orchestrator.spawn_env.os.pipe", pipe)
    monkeypatch.setattr("src.agents.slo_agent.orchestrator.spawn_env.subprocess.Popen", fail)
    with pytest.raises(OSError, match="controlled writer failure"):
        open_capture_file_append(
            history_root=root, session_id="failed", name="stdout.jsonl", credential="synthetic"
        )
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert (root / "failed/stdout.jsonl").read_bytes() == b""


def test_buffered_close_failure_still_reaps_writer(tmp_path: Path) -> None:
    """A broken pipe during buffered flush cannot bypass writer ownership."""
    import os
    from unittest.mock import Mock
    from src.agents.slo_agent.orchestrator.spawn_env import _CapturePipe

    root = tmp_path.resolve()
    destination = root / "capture"
    assert destination.resolve(strict=False).is_relative_to(root)
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    writer = Mock()
    writer.wait.return_value = 1
    acknowledgement_read_fd, acknowledgement_write_fd = os.pipe()
    os.close(acknowledgement_write_fd)
    capture = _CapturePipe(
        fd=write_fd,
        path=destination,
        process=writer,
        acknowledgement_fd=acknowledgement_read_fd,
        control_fd=-1,
    )
    capture.write(b"synthetic")
    with pytest.raises(OSError, match="capture writer failed"):
        capture.close()
    writer.wait.assert_called_once()
    assert capture.closed


def test_second_pipe_failure_closes_first_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ACK pipe allocation failure must not leak the data pipe."""
    import os

    root = tmp_path.resolve()
    assert (root / "failed").resolve(strict=False).is_relative_to(root)
    real_pipe = os.pipe
    descriptors: list[int] = []

    def pipe() -> tuple[int, int]:
        """Allocate only the first pair, then fail before spawning anything."""
        if descriptors:
            raise OSError("controlled allocation failure")
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    monkeypatch.setattr("src.agents.slo_agent.orchestrator.spawn_env.os.pipe", pipe)
    try:
        with pytest.raises(OSError, match="controlled allocation failure"):
            open_capture_file_append(
                history_root=root, session_id="failed", name="stdout.jsonl", credential="synthetic"
            )
        for fd in descriptors:
            with pytest.raises(OSError):
                os.fstat(fd)
    finally:
        for fd in descriptors:
            try:
                os.close(fd)
            except OSError:
                pass  # The production owner already closed this test-owned descriptor.


@pytest.mark.parametrize("owner", ["launch", "relaunch"])
async def test_capture_close_failure_preserves_spawned_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    """Post-spawn close failure is a warning, never a lost workload identity."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import Iterator
    from unittest.mock import Mock

    @contextmanager
    def capture(**kwargs: object) -> Iterator[object]:
        """Fail only on exit, after the controlled spawn has returned."""
        yield Mock()
        raise OSError("synthetic-private-error")

    module = "launch_tool" if owner == "launch" else "relaunch"
    monkeypatch.setattr(f"src.agents.slo_agent.orchestrator.{module}.open_capture_file_append", capture)
    spawn = AsyncMock(return_value=SimpleNamespace(pid=4321))
    handle = WorkflowHandleDAO(
        workflow_id="wf-close",
        owner_session_id="owner",
        orchestrator_session_id="child",
        pid=0,
        brief="safe",
        cwd=str(tmp_path),
        state="launching",
    )
    if owner == "relaunch":
        monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
        outcome = await WorkflowRelauncher.invoke(handle=handle, history_root=tmp_path)
        assert outcome.pid == 4321
        assert outcome.error is None
        assert outcome.warning == "capture writer failed"
        return
    store = AsyncMock()
    result = json.loads(
        await LaunchWorkflowTool._spawn_and_patch(
            store=store,
            spawn=spawn,
            history_root=tmp_path,
            handle=handle,
            model=None,
            history_warning=None,
        )
    )
    assert result["pid"] == 4321
    assert result["warning"] == "capture writer failed"
    assert store.write.await_args.kwargs["handle"].pid == 4321
    store.update_state.assert_not_awaited()


@pytest.mark.parametrize("owner", ["launch", "relaunch"])
async def test_capture_close_runs_off_async_caller_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    """Close both capture contexts off-loop without replacing the workload PID.

    Only fake captures and a fake workload are used. The Event proves that the
    async caller can progress while close is running, without timing sleeps.
    """
    import threading
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import Iterator
    from unittest.mock import Mock

    caller_thread = threading.get_ident()
    loop = asyncio.get_running_loop()
    progressed = threading.Event()
    close_threads: list[int] = []

    @contextmanager
    def capture(**kwargs: object) -> Iterator[object]:
        """Check teardown's thread before waiting on caller-loop progress."""
        yield Mock()
        close_threads.append(threading.get_ident())
        assert threading.get_ident() != caller_thread
        loop.call_soon_threadsafe(progressed.set)
        assert progressed.wait(timeout=5)

    module = "launch_tool" if owner == "launch" else "relaunch"
    monkeypatch.setattr(f"src.agents.slo_agent.orchestrator.{module}.open_capture_file_append", capture)
    spawn = AsyncMock(return_value=SimpleNamespace(pid=4321))
    handle = WorkflowHandleDAO(
        workflow_id="wf-responsive",
        owner_session_id="owner",
        orchestrator_session_id="child",
        pid=0,
        brief="safe",
        cwd=str(tmp_path),
        state="launching",
    )
    if owner == "relaunch":
        monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
        result = await WorkflowRelauncher.invoke(handle=handle, history_root=tmp_path)
        assert result.pid == 4321
    else:
        result_json = await LaunchWorkflowTool._spawn_and_patch(
            store=AsyncMock(),
            spawn=spawn,
            history_root=tmp_path,
            handle=handle,
            model=None,
            history_warning=None,
        )
        assert json.loads(result_json)["pid"] == 4321
    assert len(close_threads) == 2
    assert progressed.is_set()


async def test_relaunch_appends_redacted_real_fd_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume appends through the same production FD owner and supports later readback."""
    root = tmp_path.resolve()
    session = root / "resumed"
    assert session.resolve().is_relative_to(root)
    session.mkdir()
    for name in ("stdout.jsonl", "stderr.log"):
        (session / name).write_bytes(b"previous safe diagnostic\n")
    sentinel = "synthetic-relaunch-secret"
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", sentinel)
    script = (
        "import os\n"
        "for fd in (1,2):\n"
        " for byte in b'next:' + os.environ['SLO_OPENROUTER_API_KEY'].encode() + b':end':\n"
        "  os.write(fd, bytes([byte]))\n"
    )
    monkeypatch.setattr(
        WorkflowRelauncher,
        "_build_argv",
        staticmethod(lambda **kw: [sys.executable, "-I", "-B", "-c", script]),
    )
    original = asyncio.create_subprocess_exec
    children: list[asyncio.subprocess.Process] = []

    async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Keep production FDs and wait for this finite workload only."""
        process = await original(*args, **kwargs)  # type: ignore[call-overload, arg-type]
        children.append(process)
        assert await process.wait() == 0
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await WorkflowRelauncher.invoke(
        handle=WorkflowHandleDAO(
            workflow_id="wf-resume",
            owner_session_id="owner",
            orchestrator_session_id="resumed",
            pid=0,
            brief="safe",
            cwd=str(root),
            state="failed",
        ),
        history_root=root,
    )
    assert result.error is None
    assert result.pid == children[0].pid
    for name in ("stdout.jsonl", "stderr.log"):
        assert (session / name).read_bytes() == b"previous safe diagnostic\nnext:[REDACTED]:end"


def test_resume_append_waits_for_old_writer_tail_before_new_first_byte(tmp_path: Path) -> None:
    """A replacement capture cannot append until the prior writer releases its tail lease.

    The old and replacement captures are real independent writer processes. Thread
    events are bounded test barriers, not timing sleeps: the replacement opener must
    remain blocked until the old pipe has flushed and its writer has exited.
    """
    root: Path = tmp_path.resolve()
    session_id: str = "resume-tail"
    capture_path: Path = root / session_id / "stdout.jsonl"
    assert capture_path.resolve(strict=False).is_relative_to(root)
    old_capture = open_capture_file_append(
        history_root=root,
        session_id=session_id,
        name="stdout.jsonl",
        credential="synthetic-old-key",
    )
    old_capture.write(b"old-tail")
    replacement_opened = threading.Event()
    release_replacement = threading.Event()
    replacement_closed = threading.Event()
    failures: list[BaseException] = []

    def open_and_write_replacement() -> None:
        """Open the replacement only after the old capture lease drains."""
        try:
            replacement = open_capture_file_append(
                history_root=root,
                session_id=session_id,
                name="stdout.jsonl",
                credential="synthetic-new-key",
            )
            replacement_opened.set()
            assert release_replacement.wait(timeout=5)
            replacement.write(b"new-first-byte")
            replacement.close()
            replacement_closed.set()
        except BaseException as exc:
            failures.append(exc)
            replacement_opened.set()

    replacement_thread = threading.Thread(target=open_and_write_replacement)
    replacement_thread.start()
    assert not replacement_opened.wait(timeout=0.2)
    old_capture.close()
    assert replacement_opened.wait(timeout=5)
    release_replacement.set()
    assert replacement_closed.wait(timeout=5)
    replacement_thread.join(timeout=5)
    assert not replacement_thread.is_alive()
    assert failures == []
    assert capture_path.read_bytes() == b"old-tailnew-first-byte"


def test_reaped_launcher_transfers_append_lease_until_old_writer_final_drain(tmp_path: Path) -> None:
    """Block a replacement until an orphaned writer commits its held tail exactly once.

    A finite intermediary opens the production capture, emits a prefix, leaves a
    tail endpoint with its child, and exits/reaps before the replacement opens.
    The test never changes workload PID/group/control/reporter behavior.
    """
    root = tmp_path.resolve()
    session_id = "reaped-tail"
    capture_path = root / session_id / "stdout.jsonl"
    source = Path(__file__).resolve().parents[4]
    ready_fd, ready_write_fd = os.pipe()
    release_fd, release_write_fd = os.pipe()
    script = (
        "import os,subprocess,sys\n"
        f"sys.path.insert(0, {str(source)!r})\n"
        "from pathlib import Path\n"
        "from src.agents.slo_agent.orchestrator.spawn_env import open_capture_file_append\n"
        f"root=Path({str(root)!r}).resolve()\n"
        "capture=open_capture_file_append(history_root=root,session_id='reaped-tail',name='stdout.jsonl',credential='synthetic-old')\n"
        "capture.write(b'old-prefix'); capture.flush()\n"
        'child=("import os; os.write('
        + str(ready_write_fd)
        + ",b'r'); os.read("
        + str(release_fd)
        + ",1); os.write(1,b'old-tail'); os.close(1)\")\n"
        "subprocess.Popen([sys.executable,'-I','-B','-c',child],stdout=capture,pass_fds=("
        + str(ready_write_fd)
        + ","
        + str(release_fd)
        + "),"
        f"env={{'PATH':os.environ.get('PATH',''), 'PYTHONPATH':'', 'SLO_OPENROUTER_API_KEY':'synthetic-old'}},"
        f"close_fds=True)\n"
        "os._exit(0)\n"
    )
    # The actual script must inherit only its two owned barrier descriptors.
    parent = subprocess.Popen(
        args=[sys.executable, "-I", "-B", "-c", script],
        pass_fds=(ready_write_fd, release_fd),
        close_fds=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    os.close(ready_write_fd)
    os.close(release_fd)
    try:
        for _ in range(100):
            if parent.poll() is not None:
                break
            import time

            time.sleep(0.01)
        assert parent.returncode == 0
        assert os.read(ready_fd, 1) == b"r"
        replacement_opened = threading.Event()
        replacement_done = threading.Event()
        failure: list[BaseException] = []

        def write_replacement() -> None:
            """Open only after the old orphan writer releases its inherited lease."""
            try:
                capture = open_capture_file_append(
                    history_root=root,
                    session_id=session_id,
                    name="stdout.jsonl",
                    credential="synthetic-new",
                )
                replacement_opened.set()
                capture.write(b"new-first-byte")
                capture.close()
                replacement_done.set()
            except BaseException as exc:
                failure.append(exc)
                replacement_opened.set()

        replacement = threading.Thread(target=write_replacement)
        replacement.start()
        assert not replacement_opened.wait(timeout=0.2)
        os.write(release_write_fd, b"x")
        assert replacement_opened.wait(timeout=10)
        assert replacement_done.wait(timeout=10)
        replacement.join(timeout=10)
        assert not replacement.is_alive()
        assert failure == []
        assert capture_path.read_bytes() == b"old-prefixold-tailnew-first-byte"
    finally:
        os.close(ready_fd)
        os.close(release_write_fd)


def test_capture_append_lease_refuses_when_old_writer_does_not_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bounded lease refusal leaves the blocked capture destination untouched."""
    import fcntl

    root: Path = tmp_path.resolve()
    capture_path: Path = root / "blocked" / "stdout.jsonl"
    assert capture_path.resolve(strict=False).is_relative_to(root)
    capture_path.parent.mkdir(parents=True)
    lock_path: Path = capture_path.with_suffix(capture_path.suffix + ".append.lock")
    assert lock_path.resolve(strict=False).is_relative_to(root)
    lock_fd: int = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    monkeypatch.setattr(
        "src.agents.slo_agent.orchestrator.spawn_env._CAPTURE_WRITER_CLOSE_WAIT_SECONDS",
        0.01,
    )
    try:
        with pytest.raises(OSError, match="capture append drain did not complete"):
            open_capture_file_append(
                history_root=root,
                session_id="blocked",
                name="stdout.jsonl",
                credential="synthetic",
            )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    assert not capture_path.exists()


def test_capture_pipe_close_when_writer_exits_after_acknowledgement_raises_safe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Surface a post-acknowledgement writer exit and reap the owned writer.

    The replacement is a new regular script below pytest's resolved root. It
    acknowledges through the production FD, then exits before the owner closes
    its pipe. No workload is spawned and the synthetic credential must not
    cross the fixed public failure.
    """
    import os
    import subprocess

    root = tmp_path.resolve()
    script = root / "writer_exits_after_ack.py"
    assert script.resolve(strict=False).is_relative_to(root)
    script.write_text(
        "import os, sys\n"
        "fd = int(os.environ['SLO_CAPTURE_WRITER_ACK_FD'])\n"
        "os.write(fd, b'capture-writer-ready\\n')\n"
        "os.close(fd)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    writers: list[subprocess.Popen[bytes]] = []

    def writer_that_exits_after_ack(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Run the owned test writer while retaining production pipe arguments."""
        argv = list(args[0])
        argv[-1] = str(script)
        process: subprocess.Popen[bytes] = real_popen(argv, **kwargs)  # type: ignore[call-overload]
        writers.append(process)
        return process

    monkeypatch.setattr(
        "src.agents.slo_agent.orchestrator.spawn_env.subprocess.Popen", writer_that_exits_after_ack
    )
    capture = open_capture_file_append(
        history_root=root,
        session_id="writer-failure",
        name="stdout.jsonl",
        credential="synthetic-post-ack-secret",
    )

    with pytest.raises(OSError, match="capture writer failed") as raised:
        capture.close()

    assert "synthetic-post-ack-secret" not in str(raised.value)
    assert str(root) not in str(raised.value)
    assert writers[0].poll() == 1


async def test_launch_reaps_post_acknowledgement_writer_after_spawn_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reap post-acknowledgement writers after the detached launcher returns.

    The controlled finite workload inherits both production pipe endpoints and
    exits normally. Each writer acknowledges then fails after the owner closes
    its endpoint. The existing daemon reaper observes those owned writer exits
    without changing workload argv, PID, or process group.
    """
    import os
    import subprocess
    import threading

    from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore

    root = tmp_path.resolve()
    sentinel = "synthetic-post-ack-dispatch-three-secret"
    raw_marker = "private-writer-error-dispatch-three"
    monkeypatch.setenv("SLO_OPENROUTER_API_KEY", sentinel)
    assert (root / "post-ack").resolve(strict=False).is_relative_to(root)
    assert (root / "owner").resolve(strict=False).is_relative_to(root)
    script = root / "writer_fails_after_drain.py"
    assert script.resolve(strict=False).is_relative_to(root)
    script.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "from src.agents.slo_agent.orchestrator.capture_writer import (\n"
        "    StreamingCredentialRedactor, WorkflowCaptureCompletionContext,\n"
        ")\n"
        "fd = StreamingCredentialRedactor._acknowledge_startup()\n"
        "StreamingCredentialRedactor._drain_capture_input()\n"
        "try:\n"
        " os.close(1)\n"
        f" sys.stdout.buffer.write(({raw_marker!r} + os.environ['SLO_OPENROUTER_API_KEY']).encode())\n"
        " sys.stdout.buffer.flush()\n"
        "except OSError:\n"
        " StreamingCredentialRedactor._acknowledge_failure(acknowledgement_fd=fd)\n"
        "os.close(fd)\n"
        "os._exit(1)\n",
        encoding="utf-8",
    )
    real_popen = subprocess.Popen
    writers: list[subprocess.Popen[bytes]] = []

    reaped = [threading.Event(), threading.Event()]
    reported = [threading.Event(), threading.Event()]
    report_lock = threading.Lock()
    original_report = WorkflowHandleStore.record_capture_failure_sync

    def record_failure(self: WorkflowHandleStore, **kwargs: Any) -> WorkflowHandleDAO:
        """Signal persistence completion separately from the earlier OS reap."""
        result = original_report(self, **kwargs)
        with report_lock:
            next(event for event in reported if not event.is_set()).set()
        return result

    monkeypatch.setattr(WorkflowHandleStore, "record_capture_failure_sync", record_failure)

    def writer_that_fails_after_drain(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Track two actual writer waits while preserving production pipe ownership."""
        argv = list(args[0])
        assert Path(argv[-1]).name == "capture_writer.py"
        argv[-1] = str(script)
        process: subprocess.Popen[bytes] = real_popen(argv, **kwargs)  # type: ignore[call-overload]
        terminal = reaped[len(writers)]
        original_wait = process.wait

        def wait(timeout: float | None = None) -> int:
            """Signal only after a real wait reaps this writer, not on close timeout."""
            result = original_wait(timeout=timeout)
            terminal.set()
            return result

        monkeypatch.setattr(process, "wait", wait)
        writers.append(process)
        return process

    monkeypatch.setattr(
        "src.agents.slo_agent.orchestrator.spawn_env.subprocess.Popen", writer_that_fails_after_drain
    )

    workloads: list[subprocess.Popen[bytes]] = []
    release_read, release_write = os.pipe()

    async def spawn(*args: str, **kwargs: Any) -> subprocess.Popen[bytes]:
        """Hold the finite workload beyond both actual close timeouts using a pipe."""
        process = real_popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import os; "
                "key=os.environ['SLO_OPENROUTER_API_KEY'].encode(); "
                "[os.write(fd, b'safe:' + key + b':done') for fd in (1,2)]; "
                f"os.read({release_read}, 1)",
            ],
            pass_fds=(release_read,),
            **kwargs,
        )
        workloads.append(process)
        return process

    store = WorkflowHandleStore(history_root=root)
    handle = WorkflowHandleDAO(
        workflow_id="wf-post-ack",
        owner_session_id="owner",
        orchestrator_session_id="post-ack",
        pid=0,
        brief="safe",
        cwd=str(root),
        state="launching",
    )
    await store.write(handle=handle)
    try:
        result = await LaunchWorkflowTool._spawn_and_patch(
            store=store,
            spawn=spawn,
            history_root=root,
            handle=handle,
            model=None,
            history_warning=None,
        )
        assert len(writers) == 2
        assert len(workloads) == 1
        assert workloads[0].poll() is None
        assert not reaped[0].is_set()
        assert not reaped[1].is_set()
        assert json.loads(result)["pid"] == workloads[0].pid
        persisted = await store.read(owner_session_id="owner", workflow_id="wf-post-ack")
        assert persisted is not None
        assert persisted.pid == workloads[0].pid
    finally:
        os.close(release_read)
        os.close(release_write)
        for workload in workloads:
            assert await asyncio.to_thread(workload.wait, timeout=5) == 0
        for terminal in reaped[: len(writers)]:
            assert await asyncio.to_thread(terminal.wait, timeout=5)

    assert [writer.returncode for writer in writers] == [1, 1]
    for terminal in reported:
        assert await asyncio.to_thread(terminal.wait, timeout=5)
    reloaded_store = WorkflowHandleStore(history_root=root)
    reloaded = await reloaded_store.read(owner_session_id="owner", workflow_id="wf-post-ack")
    assert reloaded is not None
    assert reloaded.pid == workloads[0].pid
    assert reloaded.state == "launching"
    assert reloaded.capture_health is not None
    assert reloaded.capture_health.status == "degraded"
    assert reloaded.capture_health.failure_code == "capture_writer_failed"
    for name in ("stdout.jsonl", "stderr.log"):
        assert (root / "post-ack" / name).read_bytes() == b"safe:[REDACTED]:done"
    assert persisted.pid == workloads[0].pid
    public = result + persisted.model_dump_json()
    for path in (root / "post-ack").iterdir():
        public += path.read_text()
    assert sentinel not in public
    assert raw_marker not in public


async def test_launch_activates_capture_writers_after_persisting_workload_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Launch activates both capture writers only after the workload pid is durable.

    The synthetic captures record their activation call while the fake store
    rejects any activation that occurs before its pid-bearing write.
    """
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import Iterator

    root = tmp_path.resolve()
    activation_pids: list[int] = []
    pid_was_persisted = False

    class Capture:
        """Test capture that exposes only the production activation seam."""

        def activate(self, *, expected_pid: int) -> None:
            """Record activation after the fake durable write boundary."""
            assert pid_was_persisted
            activation_pids.append(expected_pid)

    @contextmanager
    def open_capture(**kwargs: object) -> Iterator[Capture]:
        """Yield a capture with no external process or filesystem effect."""
        del kwargs
        yield Capture()

    class Store:
        """Minimal durable-store double that records the persisted pid."""

        async def write(self, *, handle: WorkflowHandleDAO) -> None:
            """Mark the workload pid as durable before activation is allowed."""
            nonlocal pid_was_persisted
            if handle.pid > 0:
                pid_was_persisted = True

        async def update_state(self, **kwargs: object) -> None:
            """Satisfy the launch error-path protocol without using it."""
            del kwargs

    monkeypatch.setattr(
        "src.agents.slo_agent.orchestrator.launch_tool.open_capture_file_append",
        open_capture,
    )
    handle = WorkflowHandleDAO(
        workflow_id="wf-activation",
        owner_session_id="owner",
        orchestrator_session_id="child",
        pid=0,
        brief="safe",
        cwd=str(root),
        state="launching",
    )

    result = await LaunchWorkflowTool._spawn_and_patch(
        store=Store(),  # type: ignore[arg-type]
        spawn=AsyncMock(return_value=SimpleNamespace(pid=5432)),
        history_root=root,
        handle=handle,
        model=None,
        history_warning=None,
    )

    assert json.loads(result)["pid"] == 5432
    assert activation_pids == [5432, 5432]


async def test_capture_writer_survives_actual_parent_exit(tmp_path: Path) -> None:
    """An intermediary exits while its child still holds both production capture FDs.

    The finite workload exits itself without signals. Bounded capture polling
    checks for its final diagnostic after the intermediary has been reaped.
    """
    root = tmp_path.resolve()
    assert root.is_relative_to(tmp_path.resolve())
    sentinel = "synthetic-parent-exit-secret"
    source = Path(__file__).resolve().parents[4]
    script = (
        "import os, subprocess, sys\n"
        f"sys.path.insert(0, {str(source)!r})\n"
        "from pathlib import Path\n"
        "from src.agents.slo_agent.orchestrator.spawn_env import open_capture_file_append\n"
        f"root = Path({str(root)!r}).resolve()\n"
        "key = os.environ['SLO_OPENROUTER_API_KEY']\n"
        "out = open_capture_file_append(history_root=root, session_id='orphan', name='stdout.jsonl', credential=key)\n"
        "err = open_capture_file_append(history_root=root, session_id='orphan', name='stderr.log', credential=key)\n"
        "child = \"import os,time; time.sleep(0.4); key=os.environ['SLO_OPENROUTER_API_KEY'].encode(); "
        "[(os.write(fd, bytes([b]))) for fd in (1,2) for b in b'safe:' + key + b':done']; os.close(1); os.close(2)\"\n"
        "subprocess.Popen([sys.executable,'-I','-B','-c',child], stdout=out, stderr=err, start_new_session=True)\n"
        "os._exit(0)\n"
    )
    parent = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-B",
        "-c",
        script,
        env={"SLO_OPENROUTER_API_KEY": sentinel},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await parent.communicate()
    assert parent.returncode == 0, error
    assert output == b""
    for _ in range(200):
        paths = [root / "orphan" / name for name in ("stdout.jsonl", "stderr.log")]
        contents = [path.read_bytes() if path.exists() else b"" for path in paths]
        assert all(sentinel.encode() not in content for content in contents)
        if contents == [b"safe:[REDACTED]:done"] * 2:
            break
        await asyncio.sleep(0.02)
    assert contents == [b"safe:[REDACTED]:done"] * 2
