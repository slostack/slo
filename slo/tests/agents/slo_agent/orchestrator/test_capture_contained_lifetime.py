"""Separate-launcher clean-drain evidence and isolated reporter preconditions.

Clean output is released only after launcher reaping. Genuine I/O failure,
reporter-after-parent-exit acceptance and hardened negative containment remain
separate pending milestones; clean drain does not establish those contracts.
"""

from __future__ import annotations

from io import IOBase

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.agents.slo_agent.orchestrator.capture_writer import WorkflowCaptureCompletionContext
from src.agents.slo_agent.orchestrator.workflow_registry import (
    WorkflowHandleDAO,
    WorkflowHandleStore,
    WorkflowStatusTool,
)
from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment


def test_capture_interpreter_when_running_in_current_environment() -> None:
    """Keep capture child launches on pytest's interpreter on local and CI hosts."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import _HARNESS_PYTHON

    assert _HARNESS_PYTHON == sys.executable


@pytest.mark.parametrize("failure_stage", ["second_pipe", "script"])
@pytest.mark.parametrize("prior", [0, 1])
def test_setup_failure_restores_subreaper_and_closes_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior: int, failure_stage: str
) -> None:
    """Fail before spawn and observe real kernel state and descriptor cleanup."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import CleanDrainScenario

    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(original), 0, 0, 0) == 0
    allocated: list[int] = []
    real_pipe = os.pipe

    def pipe() -> tuple[int, int]:
        """Record only descriptors allocated by this finite failed setup."""
        if failure_stage == "second_pipe" and allocated:
            raise OSError("owned setup failure")
        pair = real_pipe()
        allocated.extend(pair)
        return pair

    def fail_write(**kwargs: object) -> None:
        """Reject script creation before any process or filesystem write."""
        raise OSError("owned setup failure")

    monkeypatch.setattr(os, "pipe", pipe)
    monkeypatch.setattr(CleanDrainScenario, "_write", fail_write)
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("spawn forbidden")))
    assert libc.prctl(36, prior, 0, 0, 0) == 0
    try:
        with pytest.raises(OSError, match="owned setup failure"):
            CleanDrainScenario.invoke(root=tmp_path.resolve(), monkeypatch=monkeypatch)
        observed = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(observed), 0, 0, 0) == 0
        assert observed.value == prior
        assert len(allocated) == (2 if failure_stage == "second_pipe" else 4)
        for descriptor in allocated:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        # The red run must not contaminate the runner or leak its owned FDs.
        for descriptor in allocated:
            try:
                os.close(descriptor)
            except OSError:
                pass
        assert libc.prctl(36, original.value, 0, 0, 0) == 0


@pytest.mark.parametrize("prior", [0, 1])
@pytest.mark.parametrize("wait_fails", [False, True])
def test_reap_restores_prior_subreaper_even_on_wait_failure(
    monkeypatch: pytest.MonkeyPatch, prior: int, wait_fails: bool
) -> None:
    """Observe real subreaper restoration without touching any real child PID."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import CleanDrainScenario

    libc = ctypes.CDLL(None, use_errno=True)
    original = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(original), 0, 0, 0) == 0
    monkeypatch.setattr(os, "pidfd_open", Mock(side_effect=OSError("owned wait failure")))
    identity = {"pid": 1234, "writers": [], "prior_subreaper": prior}
    if not wait_fails:
        monkeypatch.setattr(os, "pidfd_open", Mock(return_value=701))
        monkeypatch.setattr("select.select", Mock(return_value=([701], [], [])))
        monkeypatch.setattr(os, "waitpid", Mock(return_value=(1234, 0)))
        monkeypatch.setattr(os, "close", Mock())
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    try:
        if wait_fails:
            with pytest.raises(OSError, match="owned wait failure"):
                CleanDrainScenario.reap(identity=identity)
        else:
            CleanDrainScenario.reap(identity=identity)
        observed = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(observed), 0, 0, 0) == 0
        assert observed.value == prior
    finally:
        assert libc.prctl(36, original.value, 0, 0, 0) == 0


async def test_separate_launcher_clean_drain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reap the real launch parent before releasing two production capture streams."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import CleanDrainScenario

    identity = CleanDrainScenario.invoke(root=tmp_path.resolve(), monkeypatch=monkeypatch)
    try:
        store = WorkflowHandleStore(history_root=tmp_path.resolve())
        handle = await store.read(owner_session_id="owner", workflow_id=identity["workflow_id"])
        assert handle is not None
        assert handle.pid == identity["pid"] == identity["pgid"]
        assert handle.state == "launching" and handle.capture_health is None
        # Status is observed before reaping the finite workload (a zombie still has its PID).
        status = await WorkflowStatusTool.build(owner_session_id="owner", store=store).ainvoke(
            {"workflow_id": handle.workflow_id}
        )
        assert json.loads(status)["pid"] == handle.pid
        assert json.loads(status)["state"] == "launching"
        assert json.loads(status)["capture_health"] is None
        assert "synthetic-capture-key" not in status
        assert "capture_writer_failed" not in status
    finally:
        CleanDrainScenario.reap(identity=identity)
    CleanDrainScenario.assert_artifacts(root=tmp_path.resolve())
    assert len(list(tmp_path.glob("writer-proof-*.json"))) == 2
    assert not list(tmp_path.glob("reporter-proof-*.json"))


async def test_reaped_launcher_late_capture_failure_requires_durable_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require real late kernel write failure to reach fresh authoritative health."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import CleanDrainScenario

    root = tmp_path.resolve()
    marker = root / "late-fault"
    assert marker.resolve().is_relative_to(root)
    marker.write_bytes(b"enabled")
    identity = CleanDrainScenario.invoke(root=root, monkeypatch=monkeypatch)
    try:
        # Observe writer termination without reaping the workload identity.
        import select

        for pid in identity["writers"]:
            descriptor = os.pidfd_open(pid)
            try:
                assert select.select([descriptor], [], [], 10)[0]
            finally:
                os.close(descriptor)
        assert os.getpgid(identity["pid"]) == identity["pgid"]
        assert Path(f"/proc/{identity['pid']}/stat").read_text().split(") ", 1)[1][0] != "Z"
        fresh = WorkflowHandleStore(history_root=root)
        handle = await fresh.read(owner_session_id="owner", workflow_id=identity["workflow_id"])
        assert handle is not None and handle.pid == identity["pid"]
        assert handle.state == "launching"
        assert handle.capture_health is not None, "late writer failure lacks durable health"
        assert handle.capture_health.failure_code == "capture_writer_failed"
        assert (
            handle.capture_health.safe_message == "Capture writer failed; workflow output may be incomplete."
        )
        status = json.loads(
            await WorkflowStatusTool.build(owner_session_id="owner", store=fresh).ainvoke(
                {"workflow_id": handle.workflow_id}
            )
        )
        assert status["pid"] == identity["pid"] and status["state"] == "launching"
        assert status["capture_health"]["failure_code"] == "capture_writer_failed"
        stdout = (root / handle.orchestrator_session_id / "stdout.jsonl").read_bytes()
        stderr = (root / handle.orchestrator_session_id / "stderr.log").read_bytes()
        assert b"out:[REDACTED]" in stdout and b"err:[REDACTED]" in stderr
        assert b"synthetic-capture-key" not in stdout + stderr
        _assert_shipped_entry_evidence(root=root, writer_pids=identity["writers"])
    finally:
        CleanDrainScenario.reap(identity=identity)


@pytest.mark.parametrize("expected, enumerated", [((), (3,)), ((3,), (3, 9))])
def test_child_descriptor_scan_does_not_hide_live_fd_three(
    monkeypatch: pytest.MonkeyPatch, expected: tuple[int, ...], enumerated: tuple[int, ...]
) -> None:
    """Keep a live FD 3 while excluding only the closed proc enumeration FD."""
    real_fstat = os.fstat
    read_fd, write_fd = os.pipe()

    def fstat(descriptor: int) -> os.stat_result:
        """Model FD 3 as an owned live pipe without replacing the runner's FD 3."""
        if descriptor == 3:
            return real_fstat(read_fd)
        raise OSError(9, "enumeration descriptor already closed")

    monkeypatch.setattr(Path, "iterdir", lambda self: iter([Path(str(fd)) for fd in enumerated]))
    monkeypatch.setattr(os, "fstat", fstat)
    try:
        if expected:
            CaptureLaunchContainment._assert_child_descriptor_tuple(expected_fds=expected)
        else:
            with pytest.raises(AssertionError, match="inherited FD tuple mismatch"):
                CaptureLaunchContainment._assert_child_descriptor_tuple(expected_fds=expected)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_child_descriptor_probe_fails_closed_on_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not mistake a failed provenance probe for a closed descriptor."""
    monkeypatch.setattr(os, "fstat", Mock(side_effect=OSError(5, "probe failed")))
    with pytest.raises(OSError, match="probe failed"):
        CaptureLaunchContainment._descriptor_is_open(descriptor=901)


@pytest.mark.parametrize("inherited", [(1,), (1, 2), (True,), (-1,)])
def test_script_rejects_unregistered_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inherited: tuple[int, ...]
) -> None:
    """Reject inherited descriptors before a registered script can spawn."""
    root = tmp_path.resolve()
    script = _create_owned_script(root=root)
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    guard.allow_script(path=script)
    with pytest.raises(AssertionError):
        guard._validate_spawn(
            args=([sys.executable, "-I", "-B", str(script)],),
            kwargs=_script_spawn_kwargs(root=root, inherited=inherited),
        )


def test_script_rejects_duplicate_registered_inherited_fd_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a duplicate pipe descriptor without reaching the real launcher."""
    root = tmp_path.resolve()
    script = _create_owned_script(root=root)
    read_fd, write_fd = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        with pytest.raises(AssertionError, match="duplicate"):
            guard.allow_script(path=script, pass_fds=(read_fd, read_fd))
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_script_rejects_closed_or_unrelated_registered_fd_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject closed and non-pipe descriptors before any approved script can run."""
    root = tmp_path.resolve()
    script = _create_owned_script(root=root)
    read_fd, write_fd = os.pipe()
    unrelated = root / "unrelated"
    unrelated.write_bytes(b"owned")
    unrelated_fd = os.open(unrelated, os.O_RDONLY)
    os.close(read_fd)
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        with pytest.raises(AssertionError, match="closed"):
            guard.allow_script(path=script, pass_fds=(read_fd,))
        with pytest.raises(AssertionError, match="pipe"):
            guard.allow_script(path=script, pass_fds=(unrelated_fd,))
    finally:
        os.close(write_fd)
        os.close(unrelated_fd)


def test_script_rejects_wrong_pipe_direction_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a registered read end when the script requires its write end."""
    root = tmp_path.resolve()
    script = _create_owned_script(root=root)
    read_fd, write_fd = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=script, pass_fds=(write_fd,))
        with pytest.raises(AssertionError, match="registered inherited FD tuple"):
            guard._validate_spawn(
                args=([sys.executable, "-I", "-B", str(script)],),
                kwargs=_script_spawn_kwargs(root=root, inherited=(read_fd,)),
            )
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_script_accepts_exact_registered_pipe_tuple_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admit only the registered pipe endpoint tuple without launching it."""
    root = tmp_path.resolve()
    script = _create_owned_script(root=root)
    read_fd, write_fd = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=script, pass_fds=(write_fd,))
        guard._validate_spawn(
            args=([sys.executable, "-I", "-B", str(script)],),
            kwargs=_script_spawn_kwargs(root=root, inherited=(write_fd,)),
        )
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_child_local_guard_rejects_extra_inherited_fd_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove a child cannot write when its actual inherited tuple has an extra FD."""
    root = tmp_path.resolve()
    script = _create_audited_child_script(root=root)
    expected_read, expected_write = os.pipe()
    extra_read, extra_write = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=script, pass_fds=(expected_write, extra_write))
        (root / "expected-fds.json").write_text(json.dumps(sorted((expected_write,))), encoding="utf-8")
        process = guard.real_popen(
            [sys.executable, "-I", "-B", str(script)],
            **_script_spawn_kwargs(root=root, inherited=(expected_write, extra_write)),
        )
        output, error = process.communicate(timeout=5)
        assert process.returncode != 0
        assert output is None
        assert error is None
        assert not (root / "child-write").exists()
    finally:
        os.close(expected_read)
        os.close(expected_write)
        os.close(extra_read)
        os.close(extra_write)


def test_child_local_guard_rejects_wrong_inherited_endpoint_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove a child cannot write when it received an unregistered pipe endpoint."""
    root = tmp_path.resolve()
    script = _create_audited_child_script(root=root)
    read_fd, write_fd = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=script, pass_fds=(read_fd,))
        (root / "expected-fds.json").write_text(json.dumps(sorted((write_fd,))), encoding="utf-8")
        process = guard.real_popen(
            [sys.executable, "-I", "-B", str(script)],
            **_script_spawn_kwargs(root=root, inherited=(read_fd,)),
        )
        output, error = process.communicate(timeout=5)
        assert process.returncode != 0
        assert output is None
        assert error is None
        assert not (root / "child-write").exists()
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_child_local_guard_allows_exact_inherited_tuple_and_observes_real_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow a finite child only after it observes its exact inherited pipe tuple."""
    root = tmp_path.resolve()
    script = _create_audited_child_script(root=root)
    read_fd, write_fd = os.pipe()
    try:
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=script, pass_fds=(write_fd,))
        (root / "expected-fds.json").write_text(json.dumps(sorted((write_fd,))), encoding="utf-8")
        process = guard.real_popen(
            [sys.executable, "-I", "-B", str(script)],
            **_script_spawn_kwargs(root=root, inherited=(write_fd,)),
        )
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0
        assert output is None and error is None
        assert (root / "child-write").read_text(encoding="utf-8") == "ran"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_clean_writer_does_not_spawn_reporter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Observe an actual clean writer spawn while denying reporter execution by default."""
    root = tmp_path.resolve()
    reporter_counter = root / "reporter-counter"
    script = root / "clean-writer.py"
    script.write_text(
        "from pathlib import Path\n"
        "root = Path.cwd().resolve()\n"
        "# A clean writer must not create the reporter counter.\n"
        "(root / 'writer-output').write_text('clean', encoding='utf-8')\n",
        encoding="utf-8",
    )
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    guard.allow_script(path=script)
    process = guard.real_popen(
        [sys.executable, "-I", "-B", str(script)],
        cwd=root,
        env={"HOME": str(root), "SLO_HOME": str(root)},
        close_fds=True,
    )
    output, error = process.communicate(timeout=5)
    assert process.returncode == 0
    assert output is None and error is None
    assert (root / "writer-output").read_text(encoding="utf-8") == "clean"
    assert not reporter_counter.exists()


def test_child_local_default_deny_blocks_process_network_and_outside_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject child process, network, and symlink-escaped writes before side effects."""
    root = tmp_path.resolve()
    outside = root.parent / "outside"
    script = _create_default_deny_probe_script(root=root, outside=outside)
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    guard.allow_script(path=script)
    for mode in ("process", "network", "outside-write"):
        process = guard.real_popen(
            [sys.executable, "-I", "-B", str(script)],
            cwd=root,
            env={"HOME": str(root), "SLO_HOME": str(root), "SLO_TEST_MODE": mode},
            close_fds=True,
        )
        output, error = process.communicate(timeout=5)
        assert process.returncode != 0
        assert output is None and error is None
    assert not outside.exists()


def test_production_capture_opener_uses_exact_isolated_entry_without_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observe shipped opener wiring independently of the containment wrapper.

    The observer refuses process creation after validating the real destination
    and inherited pipes. This proves wiring only, not child-local containment or
    late-failure acceptance. The opener must close every pipe on spawn failure.
    """
    import stat
    import sys

    from src.agents.slo_agent.orchestrator.spawn_env import open_capture_file_append
    from tests.agents.slo_agent.orchestrator.capture_test_safety import _CAPTURE_WRITER_SCRIPT

    root = tmp_path.resolve()
    descriptors: list[int] = []
    real_pipe = os.pipe
    observed: list[list[str]] = []

    def track_pipe() -> tuple[int, int]:
        """Record only this opener's allocated descriptors for cleanup assertions."""
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def refuse_spawn(argv: list[str], **kwargs: object) -> None:
        """Validate production inputs and stop before any executable is launched."""
        observed.append(argv)
        assert argv == [sys.executable, "-I", "-B", str(_CAPTURE_WRITER_SCRIPT)]
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        append_lock_descriptor = int(environment["SLO_CAPTURE_APPEND_LOCK_FD"])
        expected_environment = {
            "SLO_OPENROUTER_API_KEY": "synthetic-capture-key",
            "SLO_CAPTURE_WRITER_ACK_FD": str(descriptors[3]),
            "SLO_CAPTURE_CONTROL_FD": str(descriptors[4]),
            "SLO_CAPTURE_APPEND_LOCK_FD": str(append_lock_descriptor),
        }
        assert environment == expected_environment
        assert append_lock_descriptor not in descriptors
        lock_path = root / "child" / "stdout.jsonl.append.lock"
        assert Path(os.readlink(f"/proc/self/fd/{append_lock_descriptor}")).resolve() == lock_path
        assert kwargs["stdin"] == descriptors[0]
        assert kwargs["pass_fds"] == (descriptors[3], descriptors[4], append_lock_descriptor)
        assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
        assert kwargs["stderr"] == subprocess.DEVNULL
        output = kwargs["stdout"]
        assert isinstance(output, IOBase)
        destination = Path(os.readlink(f"/proc/self/fd/{output.fileno()}")).resolve(strict=True)
        assert destination == root / "child" / "stdout.jsonl"
        assert destination.is_relative_to(root)
        assert all(stat.S_ISFIFO(os.fstat(fd).st_mode) for fd in descriptors)
        raise OSError("intentional no-spawn boundary")

    assert (root / "child" / "stdout.jsonl").resolve().is_relative_to(root)
    monkeypatch.setattr(os, "pipe", track_pipe)
    monkeypatch.setattr(subprocess, "Popen", refuse_spawn)
    with pytest.raises(OSError, match="intentional no-spawn boundary"):
        open_capture_file_append(
            history_root=root, session_id="child", name="stdout.jsonl", credential="synthetic-capture-key"
        )
    assert len(observed) == 1 and len(descriptors) == 6
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_production_writer_body_and_native_io_are_preserved_by_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qualify the audited entry recipe; live tests verify shipped-frame execution."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import _CAPTURE_WRITER_SCRIPT

    root = tmp_path.resolve()
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    guard.register_writer_bootstrap()
    real_launcher = Mock(return_value=Mock(pid=1234))
    guard._real_popen = real_launcher
    ack_read, ack_write = os.pipe()
    control_read, control_write = os.pipe()
    lock_read, lock_write = os.pipe()
    destination = root / "capture"
    assert destination.resolve().is_relative_to(root)
    expected = [sys.executable, "-I", "-B", str(_CAPTURE_WRITER_SCRIPT)]
    try:
        with destination.open("xb") as output:
            guard._guarded_popen(
                expected,
                stdin=ack_read,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env={
                    "SLO_OPENROUTER_API_KEY": "synthetic-capture-key",
                    "SLO_CAPTURE_WRITER_ACK_FD": str(ack_write),
                    "SLO_CAPTURE_CONTROL_FD": str(control_read),
                    "SLO_CAPTURE_APPEND_LOCK_FD": str(lock_write),
                },
                pass_fds=(ack_write, control_read, lock_write),
                start_new_session=True,
                close_fds=True,
            )
        launched = real_launcher.call_args.args[0]
        assert launched[:3] == expected[:3]
        bootstrap = Path(launched[3]).read_text(encoding="utf-8")
        assert f"runpy.run_path({str(_CAPTURE_WRITER_SCRIPT)!r}, run_name='__main__')" in bootstrap
        assert "setrlimit" not in bootstrap
        assert "sys.stdout =" not in bootstrap
        assert real_launcher.call_args.kwargs["pass_fds"] == (ack_write, control_read, lock_write)
    finally:
        for descriptor in (ack_read, ack_write, control_read, control_write, lock_read, lock_write):
            os.close(descriptor)


def test_production_reporter_body_and_resource_inheritance_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qualify exact reporter body/payload without pretending wrapper argv is shipped argv.

    The live late-failure test separately requires execution receipts and a fresh
    store/status mutation. No writer or reporter resource limit may be changed.
    """
    import resource

    root = tmp_path.resolve()
    call = _reporter_call(root=root, monkeypatch=monkeypatch)
    argv = call["args"]
    assert isinstance(argv, list)
    expected = list(argv)
    real_launcher = Mock(return_value=Mock(pid=1234))
    # Bootstrap setup must not alter the runner's real resource limit or devnull.
    set_limit = Mock()
    monkeypatch.setattr(resource, "setrlimit", set_limit)
    monkeypatch.setattr(os, "devnull", str(root / "null"))
    monkeypatch.setattr(subprocess, "Popen", real_launcher)
    CaptureLaunchContainment.install_reporter_bootstrap(root=root, monkeypatch=monkeypatch)

    invocation = CaptureLaunchContainment._argv(args=(), kwargs=call)
    subprocess.Popen(
        args=invocation,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    assert real_launcher.call_count == 1
    script = Path(real_launcher.call_args.args[0][3]).read_text(encoding="utf-8")
    assert f"body = {expected[4]!r}" in script
    assert f"sys.argv = ['-c', {expected[5]!r}]" in script
    assert "exec(compile(body, '<string>', 'exec'))" in script
    set_limit.assert_not_called()


def test_production_writer_requires_child_local_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject bare isolated writer exec until its child audit bootstrap is registered."""
    from tests.agents.slo_agent.orchestrator.capture_test_safety import _CAPTURE_WRITER_SCRIPT

    root = tmp_path.resolve()
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    ack_read, ack_write = os.pipe()
    control_read, control_write = os.pipe()
    destination = root / "capture"
    assert destination.resolve().is_relative_to(root)
    try:
        with destination.open("xb") as output:
            with pytest.raises(AssertionError, match="child-local writer registration"):
                guard._validate_spawn(
                    args=(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            str(_CAPTURE_WRITER_SCRIPT),
                        ],
                    ),
                    kwargs={
                        "stdin": ack_read,
                        "stdout": output,
                        "stderr": subprocess.DEVNULL,
                        "env": {
                            "SLO_OPENROUTER_API_KEY": "synthetic-capture-key",
                            "SLO_CAPTURE_WRITER_ACK_FD": str(ack_write),
                            "SLO_CAPTURE_CONTROL_FD": str(control_read),
                        },
                        "pass_fds": (ack_write, control_read),
                        "start_new_session": True,
                        "close_fds": True,
                    },
                )
    finally:
        for descriptor in (ack_read, ack_write, control_read, control_write):
            os.close(descriptor)


def _assert_shipped_entry_evidence(*, root: Path, writer_pids: list[int]) -> None:
    """Require native shipped writer execution and exact reporter completion evidence.

    Args:
        root (Path): Resolved test-owned artifact root.
        writer_pids (list[int]): Two actual independently launched writer identities.
    """
    import errno
    import hashlib
    import resource

    from tests.agents.slo_agent.orchestrator.capture_test_safety import _CAPTURE_WRITER_SCRIPT

    proofs = [json.loads((root / f"writer-proof-{pid}.json").read_text()) for pid in writer_pids]
    assert len(proofs) == 2
    for proof in proofs:
        assert proof["sha256"] == hashlib.sha256(_CAPTURE_WRITER_SCRIPT.read_bytes()).hexdigest()
        assert proof["file"] == str(_CAPTURE_WRITER_SCRIPT) and proof["entry"] == "__main__"
        assert proof["native_io"] is True
        assert proof["limit"] == list(resource.getrlimit(resource.RLIMIT_FSIZE))
    assert [proof.get("kernel_errno") for proof in proofs].count(errno.EBADF) == 1
    reports = list(root.glob("reporter-proof-*.json"))
    assert len(reports) == 1
    with pytest.MonkeyPatch.context() as patch:
        call = _reporter_call(root=root, monkeypatch=patch)
    argv = call["args"]
    assert isinstance(argv, list)
    report = json.loads(reports[0].read_text())
    assert report["sha256"] == hashlib.sha256(argv[4].encode()).hexdigest()
    assert report["argv"][0] == "-c"
    payload = json.loads(report["argv"][1])
    assert payload["history_root"] == str(root)
    assert report["fds"] == []
    # CPython can add LC_CTYPE during locale coercion to an empty environment.
    assert set(report["environment"]) <= {"LC_CTYPE"}
    assert report["limit"] == list(resource.getrlimit(resource.RLIMIT_FSIZE))
    assert len(list(root.glob("reporter-complete-*"))) == 1


def _create_owned_script(*, root: Path) -> Path:
    """Create one ordinary finite script within the resolved test root."""
    script = root / "finite.py"
    assert script.resolve().is_relative_to(root) and not script.is_symlink()
    script.write_text("pass\n", encoding="utf-8")
    return script


def _create_audited_child_script(*, root: Path) -> Path:
    """Create a finite child that audits its actual descriptor tuple before writing."""
    script = root / "audited.py"
    expected_fd_file = root / "expected-fds.json"
    expected_fd_file.write_text("[]", encoding="utf-8")
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(Path.cwd().resolve())!r})\n"
        "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
        "root = Path.cwd().resolve()\n"
        "expected = tuple(json.loads((root / 'expected-fds.json').read_text()))\n"
        "CaptureLaunchContainment.install_child_audit(root=root, expected_fds=expected)\n"
        "target = (root / 'child-write').resolve()\n"
        "assert target.is_relative_to(root)\n"
        "target.write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return script


def _create_default_deny_probe_script(*, root: Path, outside: Path) -> Path:
    """Create a finite child that installs default denial before its selected side effect."""
    script = root / "default-deny.py"
    script.write_text(
        "import os, socket, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(Path.cwd().resolve())!r})\n"
        "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
        "root = Path.cwd().resolve()\n"
        "CaptureLaunchContainment.install_child_audit(root=root, expected_fds=())\n"
        "mode = os.environ['SLO_TEST_MODE']\n"
        "if mode == 'process':\n"
        "    os.system('true')\n"
        "elif mode == 'network':\n"
        "    socket.create_connection(('127.0.0.1', 1))\n"
        "else:\n"
        f"    Path({str(outside)!r}).write_text('escape', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return script


def _script_spawn_kwargs(*, root: Path, inherited: tuple[int, ...]) -> dict[str, object]:
    """Build an otherwise valid no-spawn script command for FD admission checks."""
    return {
        "cwd": root,
        "env": {"HOME": str(root), "SLO_HOME": str(root)},
        "pass_fds": inherited,
        "close_fds": True,
    }


def _reporter_call(*, root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Capture production argv without spawning; used only for admission tests."""
    captured: dict[str, object] = {}
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", lambda **kwargs: captured.update(kwargs))
        WorkflowCaptureCompletionContext._report_serialized_failure(
            serialized_context=json.dumps(
                {
                    "history_root": str(root),
                    "owner_session_id": "owner",
                    "workflow_id": "wf-precondition",
                    "expected_pid": 1234,
                }
            )
        )
    captured.pop("check")
    return captured


@pytest.mark.parametrize(
    "mutation",
    ["inline_code", "payload_escape", "payload_field", "environment", "executable", "stdio", "fds"],
)
def test_reporter_precondition_rejects_nonexact_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Reject unsafe near-matches before any subprocess side effect."""
    root = tmp_path.resolve()
    call = _reporter_call(root=root, monkeypatch=monkeypatch)
    argv = call["args"]
    assert isinstance(argv, list)
    if mutation == "inline_code":
        argv[4] += "; raise RuntimeError('unapproved')"
    elif mutation in {"payload_escape", "payload_field"}:
        payload = json.loads(argv[5])
        if mutation == "payload_escape":
            payload["history_root"] = str(root.parent)
        else:
            payload["unexpected"] = "field"
        argv[5] = json.dumps(payload)
    elif mutation == "environment":
        call["env"] = {"SLO_OPENROUTER_API_KEY": "synthetic-capture-key"}
    elif mutation == "executable":
        call["executable"] = "/unapproved"
    elif mutation == "stdio":
        call["stderr"] = subprocess.PIPE
    else:
        call["pass_fds"] = (1,)
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    with pytest.raises(AssertionError):
        guard._validate_spawn(args=(), kwargs=call)


async def test_reporter_precondition_real_isolated_store_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute production reporter unchanged; outer store delegation stays zero.

    This verifies the prior reporter Path-shadow repair through an actual isolated
    interpreter, not a mocked observer. No writer or launching parent runs here.
    """
    root = tmp_path.resolve()
    handle = WorkflowHandleDAO(
        workflow_id="wf-precondition",
        owner_session_id="owner",
        orchestrator_session_id="child",
        pid=1234,
        brief="safe",
        cwd=str(root),
        state="launching",
    )
    assert (root / "owner/workflows/wf-precondition.json").resolve().is_relative_to(root)
    await WorkflowHandleStore(history_root=root).write(handle=handle)
    outer_report = Mock(side_effect=AssertionError("outer store delegation forbidden"))
    monkeypatch.setattr(WorkflowHandleStore, "record_capture_failure_sync", outer_report)
    guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
    call = _reporter_call(root=root, monkeypatch=monkeypatch)
    guard._validate_spawn(args=(), kwargs=call)

    WorkflowCaptureCompletionContext._report_serialized_failure(
        serialized_context=json.dumps(
            WorkflowCaptureCompletionContext(
                history_root=root,
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
                expected_pid=handle.pid,
            ).writer_payload()
        )
    )
    outer_report.assert_not_called()
    fresh = WorkflowHandleStore(history_root=root, pid_alive=lambda pid: True)
    reloaded = await fresh.read(owner_session_id="owner", workflow_id=handle.workflow_id)
    assert reloaded is not None and reloaded.capture_health is not None
    assert reloaded.model_copy(update={"capture_health": None}) == handle
    assert reloaded.capture_health.failure_code == "capture_writer_failed"
    assert reloaded.capture_health.safe_message == "Capture writer failed; workflow output may be incomplete."
    status = await WorkflowStatusTool.build(owner_session_id="owner", store=fresh).ainvoke(
        {"workflow_id": handle.workflow_id}
    )
    assert "capture_writer_failed" in status
    assert "synthetic-capture-key" not in status
