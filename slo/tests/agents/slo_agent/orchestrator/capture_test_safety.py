"""Default-deny containment used only by detached-capture process tests.

This test helper is deliberately outside production source. It is installed only
around tests that exercise real capture writers and is not a runtime sandbox.
"""

from __future__ import annotations

import asyncio as asyncio_module
import json
import os
import sys
import ctypes
import select
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

_CAPTURE_WRITER_SCRIPT: Path = (
    Path(__file__).resolve().parents[4] / "src/agents/slo_agent/orchestrator/capture_writer.py"
)
# Match production child argv without depending on one developer's virtualenv path.
_HARNESS_PYTHON: str = sys.executable


class CleanDrainScenario:
    """Own only finite tmp-root scripts, pipes and naturally reaped descendants."""

    @classmethod
    def invoke(cls, *, root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """Run a separate real launcher, reap it, then release workload output."""
        libc = ctypes.CDLL(None, use_errno=True)
        prior = ctypes.c_int()
        assert libc.prctl(37, ctypes.byref(prior), 0, 0, 0) == 0
        assert libc.prctl(36, 1, 0, 0, 0) == 0
        owned_fds: set[int] = set()
        try:
            identity = cls._invoke_owned(root=root, monkeypatch=monkeypatch, owned_fds=owned_fds)
            identity["prior_subreaper"] = prior.value
            return identity
        except BaseException:
            assert libc.prctl(36, prior.value, 0, 0, 0) == 0
            raise
        finally:
            for descriptor in tuple(owned_fds):
                cls._close_owned(descriptor=descriptor, owned_fds=owned_fds)

    @classmethod
    def _invoke_owned(
        cls, *, root: Path, monkeypatch: pytest.MonkeyPatch, owned_fds: set[int]
    ) -> dict[str, Any]:
        """Allocate setup pipes under the caller's failure cleanup boundary.

        Args:
            root (Path): Resolved test-owned destination.
            monkeypatch (pytest.MonkeyPatch): Scoped interception owner.
            owned_fds (set[int]): Parent endpoints closed even before identity exists.

        Returns:
            dict[str, Any]: Validated workload and writer identities.
        """
        barrier_read, barrier_write = os.pipe()
        owned_fds.update((barrier_read, barrier_write))
        identity_read, identity_write = os.pipe()
        owned_fds.update((identity_read, identity_write))
        source = _CAPTURE_WRITER_SCRIPT.parents[4]
        workload = root / "workload.py"
        launcher = root / "launcher.py"
        cls._write(
            root=root,
            path=workload,
            text=(
                "import os, select, sys, signal\nfrom pathlib import Path\n"
                "signal.alarm(20)\n"
                f"sys.path.insert(0, {str(source)!r})\n"
                "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
                f"CaptureLaunchContainment.install_child_audit(root=Path({str(root)!r}), expected_fds=({barrier_read},))\n"
                f"assert select.select([{barrier_read}], [], [], 30)[0]\n"
                f"assert os.read({barrier_read}, 1) == b'x'\n"
                "key = bytes([115,121,110,116,104,101,116,105,99,45,99,97,112,116,117,114,101,45,107,101,121])\n"
                "os.write(1, b'out:' + key + b'\\n')\n"
                "os.write(2, b'err:' + key + b'\\n')\n"
                "if (Path.cwd() / 'late-fault').exists():\n"
                "    import time\n"
                "    deadline = time.monotonic() + 5\n"
                "    while not any(p.stat().st_size for p in Path.cwd().glob('*/stdout.jsonl')):\n"
                "        assert time.monotonic() < deadline\n"
                "        time.sleep(0.01)\n"
                "    os.write(1, b'x' * 8192)\n"
                "    os.close(1)\n"
                "    os.close(2)\n"
                f"    assert select.select([{barrier_read}], [], [], 15)[0]\n"
                f"    os.read({barrier_read}, 1)\n"
            ),
        )
        cls._write(
            root=root,
            path=launcher,
            text=(
                "import sys, os, json, asyncio, signal\nfrom pathlib import Path\n"
                "signal.alarm(20)\n"
                f"sys.path.insert(0, {str(source)!r})\n"
                "import pytest\n"
                "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
                f"root = Path({str(root)!r})\n"
                "guard = CaptureLaunchContainment(root=root, monkeypatch=pytest.MonkeyPatch())\n"
                f"guard.allow_script(path=Path({str(workload)!r}), pass_fds=({barrier_read},))\n"
                f"guard._assert_child_descriptor_tuple(expected_fds=({barrier_read}, {identity_write}))\n"
                "guard.register_writer_bootstrap()\n"
                "guard.install_write_audit()\n"
                "os.devnull = str(guard.validate_output_path(path=root / 'null'))\n"
                "Path(os.devnull).touch()\n"
                "from src.agents.slo_agent.orchestrator.launch_tool import LaunchWorkflowTool\n"
                "async def spawn(*args: object, **kwargs: object):\n"
                "    assert args[1:5] == ('-I', '-m', 'src.cli', 'run')\n"
                f"    kwargs['pass_fds'] = ({barrier_read},)\n"
                "    kwargs['cwd'] = root\n"
                f"    return await asyncio.create_subprocess_exec({ _HARNESS_PYTHON!r}, '-I', '-B', {str(workload)!r}, **kwargs)\n"
                "async def main() -> None:\n"
                "    tool = LaunchWorkflowTool.build(owner_session_id='owner', default_model=None, history_root=root, spawn=spawn)\n"
                "    result = json.loads(await tool.ainvoke({'brief': 'finite clean drain', 'cwd': str(root)}))\n"
                "    assert 'error' not in result, result\n"
                "    payload = {name: result[name] for name in ('workflow_id', 'pid')}\n"
                "    payload.update(writers=guard.writer_pids, pgid=os.getpgid(result['pid']))\n"
                f"    os.write({identity_write}, json.dumps(payload).encode())\n"
                "asyncio.run(main())\n"
            ),
        )
        guard = CaptureLaunchContainment(root=root, monkeypatch=monkeypatch)
        guard.allow_script(path=workload)
        guard.allow_script(path=launcher, pass_fds=(barrier_read, identity_write))
        environment = {
            "HOME": str(root),
            "SLO_HOME": str(root),
            "SLO_OPENROUTER_API_KEY": "synthetic-capture-key",
        }
        process = subprocess.Popen(
            [_HARNESS_PYTHON, "-I", "-B", str(launcher)],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(barrier_read, identity_write),
            close_fds=True,
        )
        cls._close_owned(descriptor=barrier_read, owned_fds=owned_fds)
        cls._close_owned(descriptor=identity_write, owned_fds=owned_fds)
        try:
            output, error = process.communicate(timeout=25)
            assert process.returncode == 0, (output, error)
            assert select.select([identity_read], [], [], 1)[0]
            identity = json.loads(os.read(identity_read, 65536))
            assert set(identity) == {"workflow_id", "pid", "pgid", "writers"}
            assert len(set(identity["writers"])) == 2
            assert identity["pid"] not in identity["writers"]
            assert os.getpgid(identity["pid"]) == identity["pid"]
            os.write(barrier_write, b"x")
            if (root / "late-fault").exists():
                identity["release_fd"] = barrier_write
                owned_fds.remove(barrier_write)
            return identity
        finally:
            cls._close_owned(descriptor=identity_read, owned_fds=owned_fds)
            if barrier_write in owned_fds:
                cls._close_owned(descriptor=barrier_write, owned_fds=owned_fds)

    @staticmethod
    def _close_owned(*, descriptor: int, owned_fds: set[int]) -> None:
        """Close and relinquish exactly one parent endpoint, never a reused FD."""
        owned_fds.remove(descriptor)
        os.close(descriptor)

    @staticmethod
    def _write(*, root: Path, path: Path, text: str) -> None:
        """Prove ancestry immediately before creating a regular owned script."""
        assert path.resolve().is_relative_to(root) and not path.is_symlink()
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)

    @staticmethod
    def reap(*, identity: dict[str, Any]) -> None:
        """Reap adopted workload and both writers on normal EOF, without signals."""
        try:
            if "release_fd" in identity:
                os.close(identity["release_fd"])
            for pid in [identity["pid"], *identity["writers"]]:
                descriptor = os.pidfd_open(pid)
                try:
                    assert select.select([descriptor], [], [], 10)[0]
                    waited_pid, status = os.waitpid(pid, 0)
                    assert waited_pid == pid
                    assert status == 0 or (pid in identity["writers"] and status == 256)
                finally:
                    os.close(descriptor)
        finally:
            assert ctypes.CDLL(None).prctl(36, identity["prior_subreaper"], 0, 0, 0) == 0

    @staticmethod
    def assert_artifacts(*, root: Path) -> None:
        """Scan every populated artifact, including scripts and durable handles."""
        captures = []
        for path in root.rglob("*"):
            assert path.resolve().is_relative_to(root)
            if path.is_file():
                content = path.read_bytes()
                assert b"synthetic-capture-key" not in content
                assert b"out:synthetic" not in content and b"err:synthetic" not in content
                if b"[REDACTED]" in content:
                    captures.append(content)
        assert sorted(captures) == [b"err:[REDACTED]\n", b"out:[REDACTED]\n"]


class CaptureLaunchContainment:
    """Deny network and unapproved subprocesses around one owned capture test.

    WHAT: Validates subprocess identity before delegating to the real stdlib
        launcher and rejects outbound sockets before their side effect.
    WHO: Real detached-capture acceptance tests install this owner explicitly.
    WHEN: It lives only for the enclosing pytest test and accepts only finite
        writer/workload/helper scripts rooted in that test's resolved tmp path.
    """

    def __init__(self, *, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bind the resolved test root and install default-deny tripwires.

        Args:
            root (Path): Resolved pytest-owned root for scripts and outputs.
            monkeypatch (pytest.MonkeyPatch): Scoped pytest patch owner.
        """
        self._root: Path = root.resolve(strict=True)
        self._approved: dict[Path, tuple[int, ...]] = {}
        self.writer_pids: list[int] = []
        self._writer_bootstrap: Path | None = None
        self._monkeypatch: pytest.MonkeyPatch = monkeypatch
        self._real_popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen
        self._real_create_subprocess_exec: Callable[..., Any] = asyncio_module.create_subprocess_exec
        self._install_network_guard()
        self._install_process_guard()

    def register_writer_bootstrap(self) -> None:
        """Create the one owned bootstrap for unchanged production writer execution.

        The separate launcher calls this before opening captures. Each writer
        checks its actual inherited descriptors before entering production code.
        The script is a regular test-root file, never an interpreter/PATH shim.
        """
        path = self.validate_output_path(path=self._root / "writer-bootstrap.py")
        CleanDrainScenario._write(
            root=self._root,
            path=path,
            text=(
                "import os, sys, runpy, signal\nfrom pathlib import Path\n"
                "signal.alarm(20)\n"
                f"sys.path.insert(0, {str(_CAPTURE_WRITER_SCRIPT.parents[4])!r})\n"
                "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
                f"root = Path({str(self._root)!r})\n"
                "expected = tuple(int(os.environ[key]) for key in "
                "('SLO_CAPTURE_WRITER_ACK_FD', 'SLO_CAPTURE_CONTROL_FD', 'SLO_CAPTURE_APPEND_LOCK_FD'))\n"
                "CaptureLaunchContainment.install_child_audit(root=root, expected_fds=expected)\n"
                "CaptureLaunchContainment.install_writer_fd_checks(root=root, expected_fds=expected)\n"
                # Deny reporter until it too has a child-local admission proof.
                "import pytest\n"
                "CaptureLaunchContainment.install_reporter_bootstrap(root=root, monkeypatch=pytest.MonkeyPatch())\n"
                f"runpy.run_path({str(_CAPTURE_WRITER_SCRIPT)!r}, run_name='__main__')\n"
            ),
        )
        self._writer_bootstrap = path

    @classmethod
    def install_reporter_bootstrap(cls, *, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admit only the exact production reporter through an owned audited script.

        Args:
            root (Path): Validated capture test root inherited by the writer.
            monkeypatch (pytest.MonkeyPatch): Caller-owned lifetime; pytest callers
                must undo it at teardown. Finite children own it until process exit.
        """
        guard = cls(root=root, monkeypatch=monkeypatch)
        original_popen = guard._real_popen
        monkeypatch.setattr(os, "devnull", str(guard.validate_output_path(path=root / "null")))

        def launch(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            """Validate production reporter arguments, then execute its exact body."""
            argv = guard._argv(args=args, kwargs=kwargs)
            assert guard._is_isolated_reporter(argv=argv), "unexpected writer child"
            guard._validate_isolated_reporter(argv=argv, kwargs=kwargs)
            path = root / f"reporter-{os.getpid()}.py"
            CleanDrainScenario._write(
                root=root,
                path=path,
                text=(
                    "import sys, signal\nfrom pathlib import Path\n"
                    "signal.alarm(10)\n"
                    f"sys.path.insert(0, {str(_CAPTURE_WRITER_SCRIPT.parents[4])!r})\n"
                    "from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment\n"
                    f"root = Path({str(root)!r})\n"
                    "CaptureLaunchContainment.install_child_audit(root=root, expected_fds=())\n"
                    "def deny(event, args):\n"
                    "    if event == 'subprocess.Popen':\n"
                    "        raise AssertionError('reporter process escape')\n"
                    "sys.addaudithook(deny)\n"
                    f"sys.argv = ['-c', {argv[5]!r}]\n"
                    "import hashlib, json, resource\n"
                    f"body = {argv[4]!r}\n"
                    "(root / f'reporter-proof-{__import__(\"os\").getpid()}.json').write_text(json.dumps({\n"
                    "    'sha256': hashlib.sha256(body.encode()).hexdigest(),\n"
                    "    'argv': sys.argv, 'fds': [], 'environment': dict(__import__('os').environ),\n"
                    "    'limit': resource.getrlimit(resource.RLIMIT_FSIZE)}))\n"
                    "exec(compile(body, '<string>', 'exec'))\n"
                    "(root / f'reporter-complete-{__import__(\"os\").getpid()}').write_text('store returned')\n"
                ),
            )
            invocation = dict(kwargs)
            invocation.pop("args", None)
            return original_popen([_HARNESS_PYTHON, "-I", "-B", str(path)], **invocation)

        guard._monkeypatch.setattr(subprocess, "Popen", launch)

    def allow_script(self, *, path: Path, pass_fds: tuple[int, ...] = ()) -> Path:
        """Validate and return one regular finite script owned by this test.

        Args:
            path (Path): Candidate script path.

        Returns:
            Path: Resolved approved script path.

        Raises:
            AssertionError: The script is not a regular file under the test root.
        """
        resolved: Path = path.resolve(strict=True)
        assert resolved.is_relative_to(self._root)
        assert resolved.is_file()
        assert path.is_absolute() and not path.is_symlink()
        self._validate_registration_fds(pass_fds=pass_fds)
        self._approved[resolved] = pass_fds
        return resolved

    def _validate_registration_fds(self, *, pass_fds: tuple[int, ...]) -> None:
        """Require unique, open, nonstandard pipe descriptors at registration time.

        Args:
            pass_fds (tuple[int, ...]): Exact descriptors the approved script may inherit.

        Raises:
            AssertionError: A descriptor is standard, duplicate, closed, or not a pipe.
        """
        assert all(type(fd) is int and fd >= 3 for fd in pass_fds), "standard inherited FD"
        assert len(set(pass_fds)) == len(pass_fds), "duplicate inherited FD"
        for descriptor in pass_fds:
            try:
                mode = os.fstat(descriptor).st_mode
            except OSError as error:
                raise AssertionError("closed inherited FD") from error
            assert os.path.exists(f"/proc/self/fd/{descriptor}"), "closed inherited FD"
            assert __import__("stat").S_ISFIFO(mode), "unrelated inherited FD is not a pipe"

    def validate_output_path(self, *, path: Path) -> Path:
        """Validate a resolved temporary output path before a child can receive it.

        Args:
            path (Path): Candidate test output path.

        Returns:
            Path: Validated absolute path.
        """
        resolved: Path = path.resolve()
        assert path.is_absolute() and resolved.is_relative_to(self._root)
        return resolved

    @classmethod
    def install_child_audit(cls, *, root: Path, expected_fds: tuple[int, ...]) -> None:
        """Install exact-descriptor and default-deny audit hooks inside one finite child.

        Args:
            root (Path): Resolved test-owned root that bounds child writes.
            expected_fds (tuple[int, ...]): Exact nonstandard descriptors permitted in the child.

        Raises:
            AssertionError: The child inherited an unexpected descriptor or reaches a denied side effect.
        """
        resolved_root = root.resolve(strict=True)
        cls._assert_child_descriptor_tuple(expected_fds=expected_fds)
        cls._install_child_default_deny_audit(root=resolved_root)

    @staticmethod
    def install_writer_fd_checks(*, root: Path, expected_fds: tuple[int, ...]) -> None:
        """Observe native writer IO and inject a test-owned descriptor fault.

        Args:
            root (Path): Resolved test root for the capture destination.
            expected_fds (tuple[int, ...]): Registered ACK and control pipe ends.
        """
        import hashlib
        import io
        import resource
        import stat
        from types import FrameType

        assert stat.S_ISFIFO(os.fstat(0).st_mode)
        assert stat.S_ISREG(os.fstat(1).st_mode)
        destination = Path(os.readlink("/proc/self/fd/1")).resolve(strict=True)
        assert destination.is_relative_to(root)
        assert isinstance(sys.stdout.buffer, io.BufferedWriter)
        assert isinstance(sys.stdout.buffer.raw, io.FileIO)
        original_stdout = sys.stdout
        original_write = os.write
        source = _CAPTURE_WRITER_SCRIPT.read_bytes()
        proof = root / f"writer-proof-{os.getpid()}.json"
        assert proof.resolve().is_relative_to(root)
        evidence: dict[str, object] = {
            "sha256": hashlib.sha256(source).hexdigest(),
            "native_io": True,
            "limit": resource.getrlimit(resource.RLIMIT_FSIZE),
            "destination": str(destination),
        }
        faulted = False

        def trace(frame: FrameType, event: str, argument: object) -> Callable:
            """Observe shipped frames; revoke only the owned FD after first flush.

            The trace never replaces production methods or IO. On the second
            input chunk, dup2 of a read-only handle to the SAME owned inode makes
            the native FileIO write fail with kernel EBADF. No process-wide
            resource limit changes propagate to the reporter.
            """
            nonlocal faulted
            if frame.f_code.co_filename != str(_CAPTURE_WRITER_SCRIPT):
                return trace
            assert sys.stdout is original_stdout and os.write is original_write
            if event == "call" and frame.f_code.co_name == "invoke":
                evidence["entry"] = frame.f_globals["__name__"]
                evidence["file"] = frame.f_globals["__file__"]
                proof.write_text(json.dumps(evidence), encoding="utf-8")
            if frame.f_code.co_name != "_drain_capture_input":
                return trace
            if event == "line" and not faulted and (root / "late-fault").exists():
                if destination.name == "stdout.jsonl" and destination.stat().st_size > 0:
                    descriptor = os.open(destination, os.O_RDONLY)
                    try:
                        assert os.fstat(descriptor).st_ino == os.fstat(1).st_ino
                        os.dup2(descriptor, 1)
                    finally:
                        os.close(descriptor)
                    faulted = True
            if event == "exception" and isinstance(argument, tuple):
                error = argument[1]
                if isinstance(error, OSError):
                    evidence["kernel_errno"] = error.errno
                    proof.write_text(json.dumps(evidence), encoding="utf-8")
            return trace

        sys.settrace(trace)

    @classmethod
    def _assert_child_descriptor_tuple(cls, *, expected_fds: tuple[int, ...]) -> None:
        """Reject descriptor bypass before child code can write or spawn.

        Args:
            expected_fds (tuple[int, ...]): Exact descriptor tuple supplied by the parent registration.

        Raises:
            AssertionError: Actual nonstandard inherited descriptors differ from the registration.
        """
        # Materialize first so proc's enumeration FD is closed before probing.
        entries = list(Path("/proc/self/fd").iterdir())
        actual_fds = tuple(
            sorted(
                int(entry.name)
                for entry in entries
                if int(entry.name) >= 3 and cls._descriptor_is_open(descriptor=int(entry.name))
            )
        )
        assert actual_fds == tuple(sorted(expected_fds)), "extra inherited FD or inherited FD tuple mismatch"

    @staticmethod
    def _descriptor_is_open(*, descriptor: int) -> bool:
        """Exclude only closed enumeration entries, never a magic FD number.

        Args:
            descriptor (int): Descriptor observed in the completed proc listing.

        Returns:
            bool: Whether the descriptor is still open.

        Raises:
            OSError: A probe failed for a reason other than a closed descriptor.
        """
        try:
            os.fstat(descriptor)
        except OSError as error:
            if error.errno != __import__("errno").EBADF:
                raise
            return False
        return True

    @staticmethod
    def _install_child_default_deny_audit(*, root: Path) -> None:
        """Deny child network, process escape, and writes outside its owned root.

        Args:
            root (Path): Resolved test-owned root for all permitted mutations.
        """

        def audit(event: str, args: tuple[object, ...]) -> None:
            """Reject a child side effect outside the finite capture topology."""
            if event.startswith("socket.") and event not in {"socket.__new__", "socket.gethostname"}:
                raise AssertionError("network denied")
            if event in {"os.system", "os.posix_spawn", "os.fork", "os.exec", "os.spawn"}:
                raise AssertionError("process escape denied")
            if event == "open":
                path, _, flags = args
                writing = isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
                if writing and not isinstance(path, int):
                    resolved = Path(str(path)).resolve()
                    assert resolved.is_relative_to(root), "write outside test root"
                return
            if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"}:
                resolved = Path(str(args[0])).resolve()
                assert resolved.is_relative_to(root), "write outside test root"
                return
            if event in {"os.rename", "os.link", "os.symlink"}:
                for path in args[:2]:
                    resolved = Path(str(path)).resolve()
                    assert resolved.is_relative_to(root), "write outside test root"

        sys.addaudithook(audit)

    def _install_network_guard(self) -> None:
        """Reject outbound socket APIs before a connection attempt begins."""
        self._monkeypatch.setattr(socket, "create_connection", self._reject_network)
        self._monkeypatch.setattr(socket.socket, "connect", self._reject_network)
        self._monkeypatch.setattr(socket.socket, "connect_ex", self._reject_network)

    def _install_process_guard(self) -> None:
        """Route stdlib subprocess entry points through argv/environment validation."""
        self._monkeypatch.setattr(subprocess, "Popen", self._guarded_popen)
        self._monkeypatch.setattr(asyncio_module, "create_subprocess_exec", self._guarded_async_exec)

    def _reject_network(self, *args: object, **kwargs: object) -> None:
        """Fail before any real network side effect.

        Raises:
            AssertionError: Always, because capture tests must stay offline.
        """
        del args, kwargs
        raise AssertionError("capture containment blocked external network before side effect")

    def _guarded_popen(self, *args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        """Validate a synchronous spawn before reaching the real launcher.

        Returns:
            subprocess.Popen[bytes]: The approved finite child process.
        """
        self._validate_spawn(args=args, kwargs=kwargs)
        is_writer = self._argv(args=args, kwargs=kwargs)[-1] == str(_CAPTURE_WRITER_SCRIPT)
        if is_writer:
            assert self._writer_bootstrap is not None
            args = ([_HARNESS_PYTHON, "-I", "-B", str(self._writer_bootstrap)],)
        process = self._real_popen(*args, **kwargs)  # type: ignore[arg-type,call-overload]
        if is_writer:
            self.writer_pids.append(process.pid)
        return process

    async def _guarded_async_exec(self, *args: object, **kwargs: object) -> Any:
        """Validate an asynchronous spawn before reaching the real launcher."""
        self._validate_spawn(args=(args,), kwargs=kwargs)
        return await self._real_create_subprocess_exec(*args, **kwargs)

    def _validate_spawn(self, *, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        """Require an approved finite child or the exact isolated writer reporter.

        Args:
            args (tuple[object, ...]): Positional subprocess inputs.
            kwargs (dict[str, object]): Keyword subprocess inputs.

        Raises:
            AssertionError: The child is not a finite capture-test process.
        """
        argv: list[str] = self._argv(args=args, kwargs=kwargs)
        if self._is_isolated_reporter(argv=argv):
            self._validate_isolated_reporter(argv=argv, kwargs=kwargs)
            return
        if argv == [_HARNESS_PYTHON, "-I", "-B", str(_CAPTURE_WRITER_SCRIPT)]:
            assert self._writer_bootstrap is not None, "child-local writer registration required"
            assert set(kwargs) <= {
                "stdin",
                "stdout",
                "stderr",
                "env",
                "start_new_session",
                "close_fds",
                "pass_fds",
            }
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            assert set(environment) == {
                "SLO_OPENROUTER_API_KEY",
                "SLO_CAPTURE_WRITER_ACK_FD",
                "SLO_CAPTURE_CONTROL_FD",
                "SLO_CAPTURE_APPEND_LOCK_FD",
            }
            assert environment["SLO_OPENROUTER_API_KEY"] == "synthetic-capture-key"
            assert kwargs["pass_fds"] == (
                int(environment["SLO_CAPTURE_WRITER_ACK_FD"]),
                int(environment["SLO_CAPTURE_CONTROL_FD"]),
                int(environment["SLO_CAPTURE_APPEND_LOCK_FD"]),
            )
            assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
            assert kwargs["stderr"] == subprocess.DEVNULL
            self._validate_streams(kwargs=kwargs)
            return
        assert argv[0] == _HARNESS_PYTHON
        script: Path = self._script_from_argv(argv=argv)
        assert script in self._approved, "capture containment blocked unapproved script"
        assert script.resolve(strict=True) == script and script.is_file()
        assert not kwargs.get("shell") and "executable" not in kwargs
        self._validate_cwd(kwargs=kwargs)
        self._validate_environment(kwargs=kwargs)
        self._validate_streams(kwargs=kwargs)
        self._validate_inherited_fds(kwargs=kwargs)
        assert kwargs.get("pass_fds", ()) == self._approved[script], "registered inherited FD tuple mismatch"

    def _is_isolated_reporter(self, *, argv: list[str]) -> bool:
        """Recognize the one shipped reporter argv without admitting general inline code."""
        source_root = _CAPTURE_WRITER_SCRIPT.parents[4]
        expected_script = (
            "import json,sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(source_root)!r}); "
            "from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore; "
            "data=json.loads(sys.argv[1]); "
            "history_root=Path(data.pop('history_root')); "
            "store=WorkflowHandleStore(history_root=history_root); "
            "store.record_capture_failure_sync(**data)"
        )
        return (
            len(argv) == 6 and argv[:4] == [_HARNESS_PYTHON, "-I", "-B", "-c"] and argv[4] == expected_script
        )

    def _validate_isolated_reporter(self, *, argv: list[str], kwargs: dict[str, object]) -> None:
        """Allow exact reporter code and identity confined to this owned store root."""
        assert set(kwargs) <= {"args", "env", "stdin", "stdout", "stderr", "close_fds"}
        payload = json.loads(argv[5])
        assert isinstance(payload, dict) and set(payload) == {
            "history_root",
            "owner_session_id",
            "workflow_id",
            "expected_pid",
        }
        self.validate_output_path(path=Path(payload["history_root"]))
        assert type(payload["expected_pid"]) is int and payload["expected_pid"] > 0
        for key in ("owner_session_id", "workflow_id"):
            value = payload[key]
            assert isinstance(value, str) and value.strip() and value not in {".", ".."}
            assert not any(character in value for character in ("/", "\\", "\x00"))
        environment: object = kwargs.get("env")
        assert environment == {}
        assert kwargs.get("stdin") is subprocess.DEVNULL
        assert kwargs.get("stdout") is subprocess.DEVNULL
        assert kwargs.get("stderr") is subprocess.DEVNULL
        assert kwargs.get("close_fds") is True
        assert "cwd" not in kwargs and "pass_fds" not in kwargs and not kwargs.get("shell")

    def real_popen(self, *args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        """Launch one already-validated approved fixture without recursive interception.

        Args:
            args (object): Positional stdlib process inputs.
            kwargs (object): Keyword stdlib process inputs.

        Returns:
            subprocess.Popen[bytes]: The owned child process.
        """
        self._validate_spawn(args=args, kwargs=kwargs)
        return self._real_popen(*args, **kwargs)  # type: ignore[arg-type,call-overload]

    def _validate_inherited_fds(self, *, kwargs: dict[str, object]) -> None:
        """Default-deny inherited file descriptors outside finite approved pipes.

        Args:
            kwargs (dict[str, object]): Spawn keyword inputs.

        Raises:
            AssertionError: A child would inherit an uncontrolled descriptor.
        """
        pass_fds: object = kwargs.get("pass_fds", ())
        assert isinstance(pass_fds, tuple)
        assert all(type(fd) is int and fd >= 0 for fd in pass_fds)
        assert kwargs.get("close_fds", True) is True

    @staticmethod
    def _argv(*, args: tuple[object, ...], kwargs: dict[str, object]) -> list[str]:
        """Extract an argv without permitting shell strings."""
        command: object = kwargs.get("args", args[0] if args else ())
        if not isinstance(command, (list, tuple)):
            raise AssertionError("capture containment requires argv")
        argv: list[str] = [str(value) for value in command]
        if not argv:
            raise AssertionError("capture containment requires argv")
        return argv

    @staticmethod
    def _script_from_argv(*, argv: list[str]) -> Path:
        """Return the script operand after interpreter flags.

        Raises:
            AssertionError: The argv has no regular script operand.
        """
        assert len(argv) == 4 and argv[1:3] == [
            "-I",
            "-B",
        ], "blocked inline workload or unexpected argv shape"
        script = Path(argv[3])
        assert script.is_absolute()
        return script

    def _validate_cwd(self, *, kwargs: dict[str, object]) -> None:
        """Require a resolved test-root working directory for every child."""
        assert "cwd" in kwargs
        cwd: Path = Path(str(kwargs["cwd"])).resolve(strict=True)
        assert cwd.is_relative_to(self._root)

    def _validate_environment(self, *, kwargs: dict[str, object]) -> None:
        """Require synthetic credentials and an isolated HOME in child environments."""
        environment: object = kwargs.get("env")
        assert isinstance(environment, dict)
        for key in ("HOME", "SLO_HOME"):
            assert key in environment
            self.validate_output_path(path=Path(str(environment[key])))
        allowed = {
            "HOME",
            "SLO_HOME",
            "SLO_OPENROUTER_API_KEY",
            "SLO_CAPTURE_WRITER_ACK_FD",
            "SLO_CAPTURE_CONTROL_FD",
            "SLO_CAPTURE_APPEND_LOCK_FD",
            "SLO_WORKFLOW_ID",
            "PYTHONDONTWRITEBYTECODE",
            "SLO_TEST_WRITER_ERROR",
            "SLO_TEST_MODE",
        }
        assert set(environment) <= allowed
        assert environment.get("SLO_OPENROUTER_API_KEY", "synthetic-capture-key") == "synthetic-capture-key"

    def install_write_audit(self) -> None:
        """Install irreversible child-local path and process tripwires before production imports."""

        def audit(event: str, args: tuple[object, ...]) -> None:
            """Reject external mutations and non-subprocess launch escape hatches."""
            if event.startswith("socket.") and event not in {"socket.__new__", "socket.gethostname"}:
                raise AssertionError("network denied")
            if event in {"os.system", "os.posix_spawn", "os.fork", "os.exec", "os.spawn"}:
                raise AssertionError("process escape denied")
            if event == "open":
                path, mode, flags = args
                writing = isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
                if writing and not isinstance(path, int):
                    self.validate_output_path(path=Path(str(path)).absolute())
            if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"}:
                self.validate_output_path(path=Path(str(args[0])).absolute())
            if event in {"os.rename", "os.link", "os.symlink"}:
                for path in args[:2]:
                    self.validate_output_path(path=Path(str(path)).absolute())

        sys.addaudithook(audit)

    def _validate_streams(self, *, kwargs: dict[str, object]) -> None:
        """Require every named child output target to remain under the owned root."""
        for key in ("stdout", "stderr"):
            target: object = kwargs.get(key)
            if hasattr(target, "name") and isinstance(target.name, str):
                self.validate_output_path(path=Path(target.name))
