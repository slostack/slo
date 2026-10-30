"""Pre-import fail-closed guards for the two-process offline acceptance harness."""

import os
from pathlib import Path
import sys
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.state_isolation import FakeHerdrSpawnGuard


@dataclass
class OwnedDescriptor:
    """Retain one captured descriptor identity, never permission to close a reused slot."""

    fd: int | None
    identity: tuple[int, int] | None = None
    ambiguous: bool = False

    @classmethod
    def capture(cls, *, fd: int) -> "OwnedDescriptor":
        """Capture device/inode immediately after allocation."""
        metadata = os.fstat(fd)
        return cls(fd=fd, identity=(metadata.st_dev, metadata.st_ino))

    def close(self) -> None:
        """Attempt close once; reconcile later without retrying an ambiguous syscall.

        Raises:
            RuntimeError: The original identity remains after an ambiguous close.
            OSError: Identity inspection or the first close failed.
        """
        import errno

        if self.fd is None:
            return
        try:
            metadata = os.fstat(self.fd)
        except OSError as error:
            if error.errno != errno.EBADF:
                raise
            self.fd = None
            return
        if self.identity is None:
            self.identity = (metadata.st_dev, metadata.st_ino)
        if (metadata.st_dev, metadata.st_ino) != self.identity:
            self.fd = None
            return
        if self.ambiguous:
            raise RuntimeError("ambiguous descriptor close retained")
        self.ambiguous = True
        os.close(self.fd)
        self.fd = None


@dataclass
class RetainedSupervisor:
    """Keep capture paths and the exact child reachable until a successful join."""

    directory: Path
    process: subprocess.Popen[str] | None = None
    descriptors: list[OwnedDescriptor] = field(default_factory=list)
    receipts: dict[str, int] = field(default_factory=dict)

    def adopt_descriptors(self, *, fds: tuple[int, ...]) -> tuple[OwnedDescriptor, ...]:
        """Publish raw FDs before identity inspection; caller transfers exclusive slots.

        Missing identity denotes partial acquisition only: no prior close or external
        descriptor mutation is permitted before this owner's disposal.
        """
        owners = tuple(OwnedDescriptor(fd=fd) for fd in fds)
        self.descriptors.extend(owners)
        for owner in owners:
            assert owner.fd is not None
            metadata = os.fstat(owner.fd)
            owner.identity = (metadata.st_dev, metadata.st_ino)
        return owners

    def close_descriptors(self) -> None:
        """Attempt every owned FD, preserving the first disposal failure."""
        failure: BaseException | None = None
        for descriptor in self.descriptors:
            try:
                descriptor.close()
            except BaseException as error:
                failure = failure or error
        if failure is not None:
            raise failure


class RetainedResourceError(RuntimeError):
    """Transfer strong cleanup ownership without decorating an arbitrary exception."""

    def __init__(
        self,
        *,
        first_error: BaseException,
        owner: "OwnedProcessRun | OwnedSupervisor",
        resource: RetainedSupervisor,
    ) -> None:
        """Keep the first failure and exact capture/child owner until explicit release."""
        super().__init__("owned resources require a later join")
        self.first_error = first_error
        self.owner = owner
        self.resource = resource

    def release(self, *, timeout: float) -> None:
        """Join through the retained owner before removing its captures.

        Raises:
            Exception: Join or removal failed; this capability remains usable.
        """
        if self.owner.retained is not None and self.owner.retained is not self.resource:
            raise PermissionError("retained resource identity changed")
        self.owner.drain_supervisor(timeout=timeout)


class OwnedSupervisor:
    """Disposable Linux adopter; retain the workload leader until group teardown.

    Invoke only in a fresh isolated interpreter, never the pytest/agent process.
    The unreaped child pins its PID/group even after application exit. Only this
    supervisor reaps it, after the final group signal, then waits all adoptees.
    Descendants must not escape their inherited session/group.
    """

    def __init__(self, *, root: Path) -> None:
        """Bind the contained receipt root without changing process state."""
        self.root = root
        self._stop_requested = False
        self.retained: RetainedSupervisor | None = None

    def request_stop(self, signum: int, frame: object) -> None:
        """Convert parent TERM into cleanup; never kill the adopter with its workload."""
        self._stop_requested = True

    def run_entry(self, *, args: list[str], timeout: float, ready_fd: int | None = None) -> int:
        """Keep this interpreter and exact capability alive until local drain proves closure.

        The generated wrapper calls this once. Retention never retries invocation,
        signals, or remote work. Each local join is bounded; persistent failure
        keeps ownership pending rather than returning a false success status.
        """
        import signal
        import time

        # This disposable interpreter must not unwind between cleanup iterations.
        # Install before invocation so even the retention handoff has no SIGINT gap.
        previous = signal.signal(signal.SIGINT, self.request_stop)
        try:
            try:
                return self.invoke(args=args, timeout=timeout, ready_fd=ready_fd)
            except RetainedResourceError as retained:
                try:
                    os.write(2, b"SUPERVISOR_RETAINED\n")
                except BaseException:
                    pass
                while True:
                    try:
                        time.sleep(0.1)
                        retained.release(timeout=0.25)
                    except BaseException:
                        continue
                    return 125
        finally:
            signal.signal(signal.SIGINT, previous)

    def invoke(self, *, args: list[str], timeout: float, ready_fd: int | None = None) -> int:
        """Run a validated workload and publish actual waitpid results after cleanup."""
        import ctypes
        import signal
        import time

        self.retained = RetainedSupervisor(directory=self.root)
        failure: BaseException | None = None
        try:
            if ready_fd is not None:
                self.retained.adopt_descriptors(fds=(ready_fd,))
            if sys.platform != "linux":
                raise RuntimeError("descendant adoption unavailable")
            if os.getsid(0) != os.getpid():
                raise RuntimeError("supervisor requires a fresh isolated session")
            owner = OwnedProcessRun(root=self.root)
            owner.validate_launch(args=args, env={})
            if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                raise OSError("cannot enable isolated descendant adoption")
            signal.signal(signal.SIGTERM, self.request_stop)
            if ready_fd is not None:
                os.write(ready_fd, f"READY:{os.getpid()}\n".encode())
        except BaseException as error:
            failure = error
        try:
            self.retained.close_descriptors()
        except BaseException as error:
            first = failure or error
            raise RetainedResourceError(first_error=first, owner=self, resource=self.retained) from first
        if failure is not None:
            self.retained = None
            raise failure
        if self._stop_requested:
            self.retained = None
            return 124
        try:
            process = subprocess.Popen(args=args, start_new_session=True, text=True)
        except BaseException:
            self.retained = None
            raise
        self.retained.process = process
        deadline = time.monotonic() + timeout
        expired = False
        failure = None
        try:
            while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if self._stop_requested or time.monotonic() >= deadline:
                    expired = True
                    break
                time.sleep(0.005)
        except BaseException as error:
            failure = error
        for signum in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
                    raise PermissionError("workload anchor identity changed")
                os.killpg(process.pid, signum)
                time.sleep(0.1)
            except BaseException as error:
                failure = failure or error
        try:
            self.drain_supervisor(timeout=0.25)
        except BaseException as error:
            assert self.retained is not None
            first = failure or error
            raise RetainedResourceError(first_error=first, owner=self, resource=self.retained) from first
        if failure is not None:
            raise failure
        assert process.returncode is not None
        return 124 if expired else process.returncode

    def drain_supervisor(self, *, timeout: float) -> None:
        """Boundedly reap adoptees; keep receipts and ownership until ECHILD proves closure."""
        import time
        import json

        resource = self.retained
        if resource is None:
            return
        deadline = time.monotonic() + timeout
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid:
                resource.receipts[str(pid)] = os.waitstatus_to_exitcode(status)
            elif time.monotonic() >= deadline:
                raise TimeoutError("owned descendants remain")
            else:
                time.sleep(0.005)
        resource.close_descriptors()
        if resource.process is None:
            self.retained = None
            return
        resource.process.returncode = resource.receipts[str(resource.process.pid)]
        receipt = self.root / "reaped.json"
        ProcessSafety(root=self.root).contained(path=receipt)
        receipt.write_text(json.dumps(resource.receipts))
        self.retained = None


class OwnedProcessRun:
    """Own one fresh session; retain its unreaped leader as the process-group pin.

    Only run-created children may be passed to cleanup. Descendants must retain
    the inherited group; escaped sessions are not covered by this accident guard.
    """

    def __init__(self, *, root: Path) -> None:
        """Bind the test-owned capture directory without starting work."""
        self.safety = ProcessSafety(root=root)
        self._process: subprocess.Popen[str] | None = None
        self._supervisor_ready = False
        self.retained: RetainedSupervisor | None = None
        self._capture_admission = Lock()

    def run_supervised(
        self, *, args: list[str], env: dict[str, str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Join the disposable adopter, whose deadline includes descendant cleanup.

        Parent does not signal a saved workload PID. The supervisor alone owns
        that unreaped anchor. Missing cleanup evidence fails closed, not READY.
        """
        import tempfile

        self.validate_launch(args=args, env=env)
        if self._process is not None:
            raise RuntimeError("supervised owner is single use")
        with self.supervisor_resources() as directory:
            wrapper = Path(directory) / "supervisor.py"
            self.safety.contained(path=wrapper)
            ready_read, ready_write = os.pipe()
            assert self.retained is not None
            read_owner, write_owner = self.retained.adopt_descriptors(fds=(ready_read, ready_write))
            wrapper.write_text(
                "import sys\nfrom pathlib import Path\n"
                f"sys.path.insert(0,{str(Path(__file__).resolve().parents[2])!r})\n"
                "from tests.integration.herdr_restore_process_bootstrap import OwnedSupervisor\n"
                f"raise SystemExit(OwnedSupervisor(root=Path({str(self.safety.root)!r})).run_entry("
                f"args={args!r},timeout={timeout + 5!r},ready_fd={ready_write}))\n"
            )
            out, err = Path(directory) / "stdout", Path(directory) / "stderr"
            self.safety.contained(path=out)
            self.safety.contained(path=err)
            with self.capture_descriptors(out=out, err=err) as (stdout, stderr):
                process = subprocess.Popen(
                    args=[sys.executable, "-I", "-B", str(wrapper)],
                    env={**env, "SLO_HERDR_DISABLED": "1", "SLO_AUTO_VISUALIZE": "0"},
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    pass_fds=(ready_write,),
                    start_new_session=True,
                )
                self._process = process
                assert self.retained is not None
                self.retained.process = process
                try:
                    write_owner.close()
                    self.await_supervisor_ready(process=process, fd=ready_read, timeout=timeout)
                    process.wait(timeout=timeout)
                except BaseException as failure:
                    try:
                        try:
                            if self._supervisor_ready:
                                self.request_supervisor_stop(process=process)
                        except BaseException:
                            # Even a second interrupt must not bypass the owned join.
                            pass
                        process.wait(timeout=10)
                        if isinstance(failure, subprocess.TimeoutExpired):
                            failure.output = self.read_capture(fd=stdout)
                            failure.stderr = self.read_capture(fd=stderr)
                    except BaseException:
                        raise RetainedResourceError(
                            first_error=failure, owner=self, resource=self.retained
                        ) from failure
                    raise
            if process.returncode == 124:
                raise subprocess.TimeoutExpired(
                    cmd=args,
                    timeout=timeout,
                    output=self.read_capture(fd=stdout),
                    stderr=self.read_capture(fd=stderr),
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=process.returncode,
                stdout=self.read_capture(fd=stdout).decode(),
                stderr=self.read_capture(fd=stderr).decode(),
            )

    def read_capture(self, *, fd: int) -> bytes:
        """Read the still-owned capture after join without allocating a second handle."""
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)

    @contextmanager
    def capture_descriptors(self, *, out: Path, err: Path) -> Iterator[tuple[int, int]]:
        """Keep capture FDs in the retained resource, not auto-closing stream wrappers.

        Resource finalization owns both closes, including partial-open failures.
        No Python file finalizer may later close a reused numeric descriptor.
        """
        assert self.retained is not None
        descriptors: list[int] = []
        for path in (out, err):
            self.safety.contained(path=path)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            self.retained.adopt_descriptors(fds=(fd,))
            descriptors.append(fd)
        yield descriptors[0], descriptors[1]

    @contextmanager
    def supervisor_resources(self) -> Iterator[Path]:
        """Admit one capture lifetime without overwriting a pending retained owner."""
        if not self._capture_admission.acquire(blocking=False):
            raise RuntimeError("capture owner busy")
        try:
            if self.retained is not None:
                raise RuntimeError("capture owner busy")
            with self._supervisor_resources() as directory:
                yield directory
        finally:
            self._capture_admission.release()

    @contextmanager
    def _supervisor_resources(self) -> Iterator[Path]:
        """Never finalize a temporary directory while its child may still use it."""
        import tempfile
        import shutil

        self.retained = RetainedSupervisor(directory=Path(tempfile.mkdtemp(dir=self.safety.root)))
        failure: BaseException | None = None
        try:
            yield self.retained.directory
        except BaseException as error:
            failure = error
            raise
        finally:
            resource = self.retained
            if resource is not None:
                try:
                    resource.close_descriptors()
                except BaseException as cleanup_failure:
                    if isinstance(failure, RetainedResourceError):
                        raise failure
                    first = failure or cleanup_failure
                    raise RetainedResourceError(first_error=first, owner=self, resource=resource) from first
            if resource is not None and (resource.process is None or resource.process.returncode is not None):
                try:
                    self.safety.contained(path=resource.directory)
                    shutil.rmtree(resource.directory)
                    self.retained = None
                except BaseException as cleanup_failure:
                    if isinstance(failure, RetainedResourceError):
                        raise failure
                    first = failure or cleanup_failure
                    raise RetainedResourceError(first_error=first, owner=self, resource=resource) from first

    def drain_supervisor(self, *, timeout: float) -> None:
        """Serialize explicit drain against the complete active run and other drains."""
        if not self._capture_admission.acquire(blocking=False):
            raise RuntimeError("capture owner busy")
        try:
            self._drain_supervisor(timeout=timeout)
        finally:
            self._capture_admission.release()

    def _drain_supervisor(self, *, timeout: float) -> None:
        """Retry a bounded join without killing an adopter that lacks READY evidence."""
        import shutil

        resource = self.retained
        if resource is None:
            return
        failure: BaseException | None = None
        try:
            if resource.process is not None:
                resource.process.wait(timeout=timeout)
        except BaseException as error:
            failure = error
        try:
            resource.close_descriptors()
        except BaseException as error:
            failure = failure or error
        if failure is not None:
            raise failure
        self.safety.contained(path=resource.directory)
        shutil.rmtree(resource.directory)
        self.retained = None

    def await_supervisor_ready(self, *, process: subprocess.Popen[str], fd: int, timeout: float) -> None:
        """Admit TERM only after the private inherited pipe identifies the handler owner."""
        import select
        import time

        expected = f"READY:{process.pid}\n".encode()
        received = b""
        deadline = time.monotonic() + timeout
        while received != expected:
            remaining = max(0.0, deadline - time.monotonic())
            if not select.select([fd], [], [], remaining)[0]:
                raise subprocess.TimeoutExpired(cmd=process.args, timeout=timeout)
            fragment = os.read(fd, 64)
            received += fragment
            if not fragment or not expected.startswith(received):
                raise RuntimeError("supervisor startup failed before READY")
        self._supervisor_ready = True

    def request_supervisor_stop(self, *, process: subprocess.Popen[str]) -> None:
        """Signal only this still-owned supervisor session; it owns workload cleanup."""
        import signal

        if process is not self._process:
            raise PermissionError("unowned supervisor")
        if not self._supervisor_ready:
            raise PermissionError("supervisor not ready")
        try:
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            return
        if os.getpgid(process.pid) != process.pid or os.getsid(process.pid) != process.pid:
            raise PermissionError("supervisor identity changed")
        os.killpg(process.pid, signal.SIGTERM)

    def validate_launch(self, *, args: list[str], env: dict[str, str]) -> None:
        """Admit only this Python with an isolated, contained regular script and explicit env."""
        if len(args) < 4 or args[:3] != [sys.executable, "-I", "-B"]:
            raise PermissionError("only isolated current Python is approved")
        script = Path(args[3])
        self.safety.contained(path=script)
        if not stat.S_ISREG(script.stat().st_mode):
            raise PermissionError("script must be regular")
        self.safety.validate_environment(env=env)


class ProcessSafety:
    """Confine child mutations and deny networking and all unregistered child execution."""

    _shim_guard: "FakeHerdrSpawnGuard | None"

    def validate_environment(self, *, env: dict[str, str]) -> None:
        """Admit explicit settings; PATH grants discovery only of the registered regular slo shim."""
        permitted = {"HOME", "SLO_HOME", "T6_ROOT", "T6_POLICY", "T6_CAPABILITY", "PATH"}
        if set(env) - permitted:
            raise PermissionError("unapproved child environment")
        for name in ("HOME", "SLO_HOME", "T6_ROOT"):
            if name in env:
                self.contained(path=env[name])
        if "PATH" in env:
            self.require_shim_path(value=env["PATH"])

    def register_shim(self, *, path: Path) -> None:
        """Capture the parent-created shim identity before it becomes discoverable."""
        from tests.state_isolation import FakeHerdrSpawnGuard

        guard = FakeHerdrSpawnGuard(root=self.root)
        guard.register(executable=path, files=())
        if path != self.root / "slo":
            raise PermissionError("unexpected shim pathname")
        self._shim_guard = guard

    def require_shim_path(self, *, value: str) -> None:
        """Revalidate exact owned PATH and immutable registration before discovery/launch."""
        if value != str(self.root) or self._shim_guard is None:
            raise PermissionError("unregistered shim PATH")
        self._shim_guard.require_registered(path=self.root / "slo")

    def __init__(self, *, root: Path, stdio: tuple[int, ...] = ()) -> None:
        """Bind an existing test root before any application imports."""
        self.root = root.resolve(strict=True)
        self.executable: Path | None = None
        self.identity: tuple[int, int] | None = None
        self._stdio = {fd: self._fd_identity(fd=fd) for fd in stdio}
        self.retained_captures: list[OwnedDescriptor] = []
        self._shim_guard = None

    def install(self) -> None:
        """Install bounded accident guards in a disposable child, never a sandbox."""
        wrappers = self.descriptor_wrappers()
        wrappers["open"] = self.open_wrapper()
        for name, wrapper in wrappers.items():
            setattr(os, name, wrapper)
        sys.addaudithook(self.audit)

    def capture_script(self, *, path: Path) -> str:
        """Generate the sole fake writer with a pre-registered immutable identity."""
        self.contained(path=path)
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise PermissionError("nonregular capture")
        identity = (metadata.st_dev, metadata.st_ino)
        repo = Path(__file__).resolve().parents[2]
        return (
            f"#!{sys.executable} -IB\nimport json,sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(repo)!r})\n"
            "from tests.integration.herdr_restore_process_bootstrap import ProcessSafety\n"
            f"safety=ProcessSafety(root=Path({str(self.root)!r}), stdio=(1,2))\n"
            "safety.install()\n"
            f"safety.append_capture(path=Path({str(path)!r}), identity={identity!r}, "
            "payload=(json.dumps(sys.argv[1:])+'\\n').encode())\n"
        )

    def append_capture(self, *, path: Path, identity: tuple[int, int], payload: bytes) -> None:
        """Append only after opened regular single-link identity matches registration.

        Open never creates or truncates. Refusal leaves both original and substituted
        bytes untouched. Write/close failures may leave appended bytes. Failed close
        retains its identity owner on this safety instance; ambiguous closes are never
        retried. The disposable writer's process exit ultimately releases retained FDs.
        """
        self.contained(path=path)
        fd = os.open(path=path, flags=os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK)
        owner = OwnedDescriptor(fd=fd)
        primary: BaseException | None = None
        try:
            metadata = os.fstat(fd)
            owner.identity = (metadata.st_dev, metadata.st_ino)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise PermissionError("unsafe capture descriptor")
            if (metadata.st_dev, metadata.st_ino) != identity:
                raise PermissionError("substituted capture descriptor")
            opened_path = self.descriptor_path(fd=fd)
            if opened_path != path.absolute():
                raise PermissionError("capture pathname changed")
            remaining = memoryview(payload)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("capture write made no progress")
                remaining = remaining[written:]
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                if owner.identity is None:
                    # Initial inspection failed; allocation is still exclusively owned.
                    owner.ambiguous = True
                    os.close(fd)
                    owner.fd = None
                else:
                    owner.close()
            except BaseException:
                self.retained_captures.append(owner)
                if primary is None:
                    raise

    def descriptor_path(self, *, fd: int) -> Path:
        """Resolve a Linux descriptor and compare open identity before admission."""
        opened = os.fstat(fd)
        if not (stat.S_ISREG(opened.st_mode) or stat.S_ISDIR(opened.st_mode)):
            raise PermissionError("special opened descriptor")
        if stat.S_ISREG(opened.st_mode) and opened.st_nlink != 1:
            raise PermissionError("multiply linked opened descriptor")
        target = Path(os.readlink(f"/proc/self/fd/{fd}"))
        self.contained(path=target)
        current = target.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise PermissionError("substituted descriptor")
        return target

    def contained(self, *, path: str | bytes | os.PathLike[str] | int) -> None:
        """Refuse links, traversal, special files and mutations outside the owned root."""
        if isinstance(path, int):
            self.descriptor_path(fd=path)
            return
        target = Path(os.fsdecode(path)).absolute()
        if ".." in target.parts:
            raise PermissionError("test mutation through traversal")
        if not target.resolve().is_relative_to(self.root):
            raise PermissionError(f"test mutation outside owned root: {target}")
        if any(part.is_symlink() for part in (target, *target.parents)):
            raise PermissionError("test mutation through symbolic link")
        if target.exists():
            metadata = target.stat()
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                raise PermissionError("special mutation target")
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
                raise PermissionError("multiply linked mutation target")

    def mutation(self, *, path: object, dir_fd: object = None) -> None:
        """Validate a mutation relative to its actual directory capability."""
        if isinstance(path, int):
            self.contained(path=path)
            return
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise PermissionError("unknown mutation target")
        target = Path(os.fsdecode(path))
        if not target.is_absolute() and dir_fd not in (None, -1):
            if not isinstance(dir_fd, int):
                raise PermissionError("invalid directory descriptor")
            parent = self.descriptor_path(fd=dir_fd)
            if not parent.is_dir():
                raise PermissionError("non-directory capability")
            target = parent / target
        self.contained(path=target)

    @staticmethod
    def _fd_identity(*, fd: int) -> tuple[int, int, int]:
        """Capture descriptor identity without trusting its numeric slot."""
        metadata = os.fstat(fd)
        return metadata.st_dev, metadata.st_ino, metadata.st_mode

    def open_wrapper(self) -> Callable[..., int]:
        """Validate dir_fd before os.open can create or truncate a target."""
        original = os.open

        def guarded(
            path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
        ) -> int:
            """Apply directory-aware admission before the open syscall."""
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                self.mutation(path=path, dir_fd=dir_fd)
                # Audit omits dir_fd. Forward the validated absolute spelling rather
                # than granting an ambient bypass token to unrelated audit events.
                if dir_fd is not None and not Path(os.fsdecode(path)).is_absolute():
                    path = self.descriptor_path(fd=dir_fd) / os.fsdecode(path)
                    dir_fd = None
            return original(path=path, flags=flags, mode=mode, dir_fd=dir_fd)

        return guarded

    def descriptor_wrappers(self) -> dict[str, Callable[..., object]]:
        """Build reversible syscall patches; private descriptors require rooted identity."""
        names = ("write", "writev", "pwrite", "pwritev", "ftruncate", "fchmod", "fchown")
        return {
            name: self._descriptor_wrapper(operation=getattr(os, name)) for name in names if hasattr(os, name)
        }

    def _descriptor_wrapper(self, *, operation: Callable[..., object]) -> Callable[..., object]:
        """Validate before the original syscall, including functions without audit events."""

        def guarded(fd: int, *args: object, **kwargs: object) -> object:
            """Refuse unowned descriptors before forwarding positional-only syscall arguments."""
            stream_write = operation.__name__ in {"write", "writev"} and fd in self._stdio
            if stream_write:
                if self._fd_identity(fd=fd) != self._stdio[fd]:
                    raise PermissionError("substituted stdio")
            else:
                self.descriptor_path(fd=fd)
            return operation(fd, *args, **kwargs)

        return guarded

    def audit(self, event: str, arguments: tuple[object, ...]) -> None:
        """Apply process-wide safety even when application code bypasses mocks."""
        if event in {
            "socket.connect",
            "socket.connect_ex",
            "socket.bind",
            "os.system",
            "os.posix_spawn",
            "os.exec",
            "os.fork",
            "os.forkpty",
        }:
            raise PermissionError("offline boundary")
        if event == "subprocess.Popen":
            if self.executable is None or str(arguments[0]) != str(self.executable):
                raise PermissionError("unregistered child")
            self.contained(path=self.executable)
            metadata = self.executable.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PermissionError("nonregular executable")
            if (metadata.st_dev, metadata.st_ino) != self.identity:
                raise PermissionError("substituted child")
        if event == "open":
            path, _, flags = arguments
            if isinstance(path, (str, bytes, int)) and isinstance(flags, int):
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    self.contained(path=path)
        directory_indices = {"os.mkdir": 2, "os.remove": 1, "os.rmdir": 1, "os.chmod": 2}
        if event in directory_indices:
            index = directory_indices[event]
            self.mutation(path=arguments[0], dir_fd=arguments[index] if len(arguments) > index else None)
        if event in {"os.chown", "os.utime"}:
            self.mutation(path=arguments[0], dir_fd=arguments[3] if len(arguments) > 3 else None)
        if event in {"os.setxattr", "os.removexattr"}:
            self.mutation(path=arguments[0])
        if event == "os.truncate":
            self.mutation(path=arguments[0])
        if event in {"os.rename", "os.link"}:
            self.mutation(path=arguments[0], dir_fd=arguments[2])
            self.mutation(path=arguments[1], dir_fd=arguments[3])
        if event == "os.symlink":
            raise PermissionError("child link creation denied")

    def probe(self, *, victim: Path) -> None:
        """Probe only a precreated regular sibling inside the parent test root."""
        import stat

        if victim != self.root.parent / "forbidden-write" or victim.is_symlink():
            raise PermissionError("unsafe probe victim")
        metadata = victim.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise PermissionError("unsafe probe victim")
        # Only the owned victim mutation reaches a real syscall. Policy checks
        # for networking/execution must remain inert even if admission regresses.
        operations = (
            lambda: victim.write_text("never"),
            lambda: self.audit(event="socket.connect", arguments=()),
            lambda: self.audit(event="subprocess.Popen", arguments=("unregistered",)),
        )
        for operation in operations:
            try:
                operation()
            except PermissionError:
                continue
            raise AssertionError("missing safety boundary")
        print("safety-probe-ok")


if __name__ == "__main__":
    safety = ProcessSafety(root=Path(sys.argv[1]))
    sys.addaudithook(safety.audit)
    safety.probe(victim=Path(sys.argv[2]))
