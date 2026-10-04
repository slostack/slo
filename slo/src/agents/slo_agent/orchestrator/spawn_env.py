"""Shared environment and capture-file policy for ``slo run`` children.

Sub-spec 71.a.0.
"""

from __future__ import annotations

import io
import os
import select
import time
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO, Optional

from src.agents.slo_agent.orchestrator.capture_writer import WorkflowCaptureCompletionContext
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.auth.credential_dao import ProviderName
from src.auth.credential_resolver import CredentialResolver

__all__ = ["build_headless_child_env", "open_capture_file_append", "redact_openrouter_credential"]

# Includes the explicit Feature 75 kill switch ``SLO_PLUGINS_DISABLED`` so
# headless children deterministically inherit the parent's plugin policy.
_ENV_ALLOWLIST_PREFIXES: tuple[str, ...] = ("SLO_",)
_ENV_ALLOWLIST_EXACT: tuple[str, ...] = ("PATH", "HOME", "LANG", "TERM", "PYENV_ROOT", "PYENV_VERSION")
_ENV_SECRET_MARKERS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def build_headless_child_env(
    *,
    workflow_id: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build the non-secret environment for a spawned headless child.

    WHAT: Keeps exact process basics and non-secret SLO settings, then adds
        caller-supplied workflow and per-spawn identity values.
    WHO: Called by detached workflow and sub-agent process spawn owners.
    WHEN: Immediately before a ``slo run`` child is created.

    Args:
        workflow_id (Optional[str]): Workflow identifier to inject when set.
        extra (Optional[dict[str, str]]): Additional non-empty child variables.

    Returns:
        dict[str, str]: Sanitized child environment.
    """
    child_env: dict[str, str] = _allowlisted_parent_env()
    _add_workflow_id(child_env=child_env, workflow_id=workflow_id)
    _add_nonempty_extra(child_env=child_env, extra=extra)
    return child_env


_CAPTURE_WRITER_STARTUP_TIMEOUT_SECONDS: float = 1.0
_CAPTURE_WRITER_CLOSE_WAIT_SECONDS: float = 1.0
_CAPTURE_WRITER_STARTUP_ACKNOWLEDGEMENT: bytes = b"capture-writer-ready\n"
_CAPTURE_WRITER_FAILURE_ACKNOWLEDGEMENT: bytes = b"capture-writer-failed\n"
_CAPTURE_WRITER_FAILURE_MESSAGE: str = "capture writer failed"


class _CapturePipe(io.BufferedWriter):
    """Named child-facing pipe; closing it never terminates a live capture writer."""

    def __init__(
        self,
        *,
        fd: int,
        path: Path,
        process: subprocess.Popen[bytes],
        acknowledgement_fd: int,
        control_fd: int,
        completion_context: Optional[WorkflowCaptureCompletionContext] = None,
    ) -> None:
        """Own parent endpoints and reap only this writer after workload EOF.

        Args:
            fd (int): Parent write endpoint inherited by the workload at spawn.
            path (Path): Safe destination named in diagnostics only.
            process (subprocess.Popen[bytes]): Independently started writer process.
            acknowledgement_fd (int): Parent read endpoint for writer failure evidence.
            completion_context (WorkflowCaptureCompletionContext): Inactive private
                identity handoff activated only after workload PID persistence.
        """
        super().__init__(io.FileIO(fd, mode="wb"))
        self._path = path
        self._process = process
        self._acknowledgement_fd = acknowledgement_fd
        self._control_fd = control_fd
        self._completion_context = completion_context
        self._activation_lock = threading.Lock()
        self._is_activated = False
        self._failure_pending = False

    @property
    def name(self) -> str:
        """Expose the destination for capture diagnostics, not the anonymous FD."""
        return str(self._path)

    def activate(self, *, expected_pid: int) -> None:
        """Adopt a ready writer after its workload PID is durably persisted.

        Args:
            expected_pid (int): Persisted workload PID that identifies this run.

        Raises:
            ValueError: If the supplied PID differs from this writer's private context.
        """
        if self._completion_context is None:
            raise ValueError("capture writer activation context is unavailable")
        if self._completion_context.expected_pid not in {0, expected_pid}:
            raise ValueError("capture writer activation pid does not match")
        self._completion_context = WorkflowCaptureCompletionContext(
            history_root=self._completion_context.history_root,
            owner_session_id=self._completion_context.owner_session_id,
            workflow_id=self._completion_context.workflow_id,
            expected_pid=expected_pid,
        )
        self._send_activation_control()
        with self._activation_lock:
            self._is_activated = True
            failure_pending = self._failure_pending
            self._failure_pending = False
        if failure_pending:
            self._report_failure()

    def _send_activation_control(self) -> None:
        """Send exactly one bounded private adoption frame and close the parent control end."""
        if self._control_fd < 0:
            raise OSError("capture writer activation control is unavailable")
        try:
            payload = (
                self._completion_context.writer_payload() if self._completion_context is not None else {}
            )
            encoded = __import__("json").dumps(payload, separators=(",", ":")).encode("utf-8")
            os.write(self._control_fd, encoded)
        finally:
            self._close_control_fd()

    def close(self) -> None:
        """Close the pipe, drain the writer, and report a safe writer failure.

        WHAT: Closes only the parent's endpoint, then waits briefly for the
            independent writer to flush all workload-owned pipe bytes. A live
            workload retains its inherited endpoint, so a daemon reaper owns
            the later wait without changing its PID or process group.
        WHO: ``ExitStack`` in detached launch/relaunch owns this close boundary.
        WHEN: After subprocess creation or a pre-spawn capture-open failure.

        Raises:
            OSError: If the acknowledged writer exits nonzero before or during
                the owner's bounded drain wait.
        """
        if self.closed:
            return
        self._close_control_fd()
        close_failed = self._close_parent_pipe()
        exit_code: Optional[int] = self._wait_for_writer_close()
        close_failed = self._observe_writer_exit(close_failed=close_failed, exit_code=exit_code)
        if exit_code is None:
            self._start_writer_reaper()
        if close_failed:
            raise OSError(_CAPTURE_WRITER_FAILURE_MESSAGE) from None

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Close and drain the capture writer at the owning launch boundary.

        Args:
            exc_type (object): Active exception type from the enclosing context.
            exc_value (object): Active exception value from the enclosing context.
            traceback (object): Active exception traceback from the enclosing context.

        """
        self.close()

    def _close_parent_pipe(self) -> bool:
        """Close the parent pipe endpoint and return whether buffered close failed."""
        try:
            super().close()
        except OSError:
            return True
        return False

    def _wait_for_writer_close(self) -> Optional[int]:
        """Return the writer exit code when it drains within the close wait."""
        try:
            return self._process.wait(timeout=_CAPTURE_WRITER_CLOSE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            return None

    def _observe_writer_exit(self, *, close_failed: bool, exit_code: Optional[int]) -> bool:
        """Combine close-time writer evidence without exposing private writer details.

        Args:
            close_failed (bool): Whether the buffered parent close already failed.
            exit_code (Optional[int]): Reaped writer status, if it exited promptly.

        Returns:
            bool: Whether the capture boundary has fixed safe failure evidence.
        """
        if exit_code is None:
            return close_failed
        failed = close_failed or exit_code != 0 or self._consume_failure_acknowledgement()
        self._close_acknowledgement_fd()
        return failed

    def _consume_failure_acknowledgement(self) -> bool:
        """Read fixed writer failure evidence without blocking the launch path."""
        try:
            ready, _, _ = select.select([self._acknowledgement_fd], [], [], 0)
            if not ready:
                return False
            acknowledgement = os.read(
                self._acknowledgement_fd,
                len(_CAPTURE_WRITER_FAILURE_ACKNOWLEDGEMENT),
            )
            return acknowledgement == _CAPTURE_WRITER_FAILURE_ACKNOWLEDGEMENT
        finally:
            self._close_acknowledgement_fd()

    def _start_writer_reaper(self) -> None:
        """Start a writer-only reaper that retains late fixed failure evidence."""
        threading.Thread(target=self._reap_writer_after_workload, daemon=True).start()

    def _reap_writer_after_workload(self) -> None:
        """Reap one owned writer and consume its fixed terminal failure signal."""
        exit_code = self._process.wait()
        failed = exit_code != 0 or self._consume_failure_acknowledgement()
        if failed:
            self._handle_failure()
        self._close_acknowledgement_fd()

    def _handle_failure(self) -> None:
        """Buffer one safe failure until the owning launcher adopts this writer."""
        with self._activation_lock:
            if not self._is_activated:
                self._failure_pending = True
                return
        self._report_failure()

    def _report_failure(self) -> None:
        """Persist fixed-safe failure evidence through the sole handle owner."""
        if self._completion_context is None:
            return
        try:
            WorkflowCaptureCompletionContext.report_failure_context(context=self._completion_context)
        except (FileNotFoundError, RuntimeError, OSError):
            return

    def _close_control_fd(self) -> None:
        """Close the parent-only activation control endpoint exactly once."""
        if self._control_fd < 0:
            return
        try:
            os.close(self._control_fd)
        except OSError:
            pass
        self._control_fd = -1

    def _close_acknowledgement_fd(self) -> None:
        """Close the parent control endpoint once its writer can no longer report."""
        if self._acknowledgement_fd < 0:
            return
        try:
            os.close(self._acknowledgement_fd)
        except OSError:
            pass
        self._acknowledgement_fd = -1


def open_capture_file_append(
    *,
    history_root: Path,
    session_id: str,
    name: str,
    credential: str = "",
    completion_context: Optional[WorkflowCaptureCompletionContext] = None,
) -> IO[bytes]:
    """Open an append capture, interposing an independent writer for a known key.

    WHAT: Only the writer receives the disk FD; the workload receives a pipe.
        Redaction precedes every disk write, with no raw spool or later scrub.
    WHO: Launch and relaunch pass the exact credential from their captured env.
    WHEN: Before spawn. EOF ends the writer; parent exit does not end capture.
        A local daemon waiter reaps a writer that outlives the parent's endpoint;
        after parent exit the OS adopts it. No workflow PID/group is replaced.

    Args:
        history_root (Path): Root containing session history directories.
        session_id (str): Session owning the capture.
        name (str): Capture file name.
        credential (str): Literal forwarded key. When empty, the canonical
            resolver supplies the stored effective key without adding it to the
            workload environment. Direct capture is used only with no key.
        completion_context (Optional[WorkflowCaptureCompletionContext]): Private
            run identity used to report activated writer failures.

    Returns:
        IO[bytes]: Child-facing binary handle; its name identifies the destination.

    Raises:
        OSError: If the destination, pipe, or independent writer cannot be opened.
    """
    if not credential:
        resolved = CredentialResolver.resolve(provider=ProviderName.OPENROUTER)
        credential = resolved.access_token if resolved is not None else ""
    capture_path: Path = OrchestrationLayout.capture_path(
        history_root=history_root,
        session_id=session_id,
        name=name,
    )
    _create_capture_parent_if_missing(capture_parent=capture_path.parent)
    append_lock_fd: int = _acquire_capture_append_lease(capture_path=capture_path)
    if not credential:
        try:
            return _open_private_capture_append(capture_path=capture_path)
        finally:
            _close_owned_fd(descriptor=append_lock_fd)
    return _open_redacting_capture_pipe(
        capture_path=capture_path,
        credential=credential,
        append_lock_fd=append_lock_fd,
        completion_context=completion_context,
    )


def _open_redacting_capture_pipe(
    *,
    capture_path: Path,
    credential: str,
    append_lock_fd: int,
    completion_context: Optional[WorkflowCaptureCompletionContext],
) -> IO[bytes]:
    """Create one writer-owned append lease and return its workload-facing pipe.

    Args:
        capture_path (Path): Private capture destination.
        credential (str): Literal credential retained only by the writer.
        append_lock_fd (int): Acquired sibling lease transferred to the writer.
        completion_context (Optional[WorkflowCaptureCompletionContext]): Deferred
            failure-report identity activated after workload PID persistence.

    Returns:
        IO[bytes]: Parent pipe endpoint inherited by the workload.

    Raises:
        OSError: If setup cannot complete after closing every owned endpoint.
    """
    owned_fds: set[int] = {append_lock_fd}
    writer: Optional[subprocess.Popen[bytes]] = None
    try:
        read_fd, write_fd = _open_and_track_pipe(owned_fds=owned_fds)
        acknowledgement_read_fd, acknowledgement_write_fd = _open_and_track_pipe(owned_fds=owned_fds)
        control_read_fd, control_write_fd = _open_and_track_pipe(owned_fds=owned_fds)
        with _open_private_capture_append(capture_path=capture_path) as destination:
            writer = _spawn_capture_writer(
                credential=credential,
                read_fd=read_fd,
                destination=destination,
                acknowledgement_write_fd=acknowledgement_write_fd,
                control_read_fd=control_read_fd,
                append_lock_fd=append_lock_fd,
            )
        _close_tracked_fd(descriptor=acknowledgement_write_fd, owned_fds=owned_fds)
        _close_tracked_fd(descriptor=control_read_fd, owned_fds=owned_fds)
        _require_capture_writer_acknowledgement(
            acknowledgement_read_fd=acknowledgement_read_fd,
            writer=writer,
        )
        capture = _build_capture_pipe(
            write_fd=write_fd,
            capture_path=capture_path,
            writer=writer,
            acknowledgement_read_fd=acknowledgement_read_fd,
            control_write_fd=control_write_fd,
            completion_context=completion_context,
        )
        owned_fds.difference_update((write_fd, acknowledgement_read_fd, control_write_fd))
        _close_tracked_fd(descriptor=read_fd, owned_fds=owned_fds)
        # The writer retains a duplicate inherited descriptor. Closing the parent
        # copy does not release its flock while it drains its workload pipe.
        _close_tracked_fd(descriptor=append_lock_fd, owned_fds=owned_fds)
        return capture
    except BaseException:
        if writer is not None:
            _reap_unhanded_writer(writer=writer)
        raise
    finally:
        _close_all_owned_fds(owned_fds=owned_fds)


def _open_and_track_pipe(*, owned_fds: set[int]) -> tuple[int, int]:
    """Allocate one pipe and add both endpoints to the caller cleanup set."""
    read_fd, write_fd = _open_pipe_pair()
    owned_fds.update((read_fd, write_fd))
    return read_fd, write_fd


def _spawn_capture_writer(
    *,
    credential: str,
    read_fd: int,
    destination: IO[bytes],
    acknowledgement_write_fd: int,
    control_read_fd: int,
    append_lock_fd: int,
) -> subprocess.Popen[bytes]:
    """Start the isolated writer with its acknowledgement, control, and lease FDs."""
    return subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("capture_writer.py"))],
        stdin=read_fd,
        stdout=destination,
        stderr=subprocess.DEVNULL,
        env={
            "SLO_OPENROUTER_API_KEY": credential,
            "SLO_CAPTURE_WRITER_ACK_FD": str(acknowledgement_write_fd),
            "SLO_CAPTURE_CONTROL_FD": str(control_read_fd),
            "SLO_CAPTURE_APPEND_LOCK_FD": str(append_lock_fd),
        },
        start_new_session=True,
        close_fds=True,
        pass_fds=(acknowledgement_write_fd, control_read_fd, append_lock_fd),
    )


def _build_capture_pipe(
    *,
    write_fd: int,
    capture_path: Path,
    writer: subprocess.Popen[bytes],
    acknowledgement_read_fd: int,
    control_write_fd: int,
    completion_context: Optional[WorkflowCaptureCompletionContext],
) -> _CapturePipe:
    """Transfer parent endpoints into the one capture-pipe lifecycle owner."""
    return _CapturePipe(
        fd=write_fd,
        path=capture_path,
        process=writer,
        acknowledgement_fd=acknowledgement_read_fd,
        control_fd=control_write_fd,
        completion_context=completion_context,
    )


def _close_tracked_fd(*, descriptor: int, owned_fds: set[int]) -> None:
    """Close one currently owned descriptor and remove it from cleanup ownership."""
    _close_owned_fd(descriptor=descriptor)
    owned_fds.discard(descriptor)


def _close_all_owned_fds(*, owned_fds: set[int]) -> None:
    """Close each remaining setup descriptor after failed ownership transfer."""
    for descriptor in tuple(owned_fds):
        _close_tracked_fd(descriptor=descriptor, owned_fds=owned_fds)


def _close_owned_fd(*, descriptor: int) -> None:
    """Close one descriptor while treating a prior close as cleanup completion."""
    try:
        os.close(descriptor)
    except OSError:
        return


def _create_capture_parent_if_missing(*, capture_parent: Path) -> None:
    """Create only missing capture ancestors with private directory permissions.

    Existing directories are deliberately left unchanged because this capture owner
    must not chmod a path it did not create.
    """
    missing: list[Path] = []
    candidate: Path = capture_parent
    while not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)


def _open_private_capture_append(*, capture_path: Path) -> IO[bytes]:
    """Open a capture append destination with private creation permissions.

    Existing destinations retain their mode and content; only a newly created
    capture file receives mode ``0600``.
    """
    descriptor: int = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    return os.fdopen(descriptor, mode="ab")


def _open_pipe_pair() -> tuple[int, int]:
    """Allocate one pipe pair or raise after releasing no caller-owned descriptor."""
    return os.pipe()


def _acquire_capture_append_lease(*, capture_path: Path) -> int:
    """Acquire the narrow append lease shared by independent capture writers.

    WHAT: Serializes append-writer ownership of one capture destination so a
        resumed writer cannot emit before an older writer drains its final tail.
    WHO: ``open_capture_file_append`` invokes it before writer readiness.
    WHEN: Each credential-redacting capture opener holds it until the writer exits.

    Args:
        capture_path (Path): Capture destination whose sibling lease is acquired.

    Returns:
        int: Owned descriptor that releases the lease when closed.

    Raises:
        OSError: If the bounded lease wait cannot obtain exclusive ownership.
    """
    lock_path: Path = capture_path.with_suffix(capture_path.suffix + ".append.lock")
    lock_fd: int = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        deadline: float = time.monotonic() + _CAPTURE_WRITER_CLOSE_WAIT_SECONDS
        while True:
            try:
                import fcntl

                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock_fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OSError("capture append drain did not complete") from None
                time.sleep(0.01)
    except BaseException:
        _close_owned_fd(descriptor=lock_fd)
        raise


def _reap_unhanded_writer(*, writer: subprocess.Popen[bytes]) -> None:
    """Close no workload pipe and reap a writer whose ownership handoff failed.

    Args:
        writer (subprocess.Popen[bytes]): Writer started before acknowledgement
            validation or parent-handle construction failed.
    """
    # Input has already closed: the owned writer can observe EOF independently.
    # Never spend a synchronous close timeout on the launch event-loop thread.
    threading.Thread(target=writer.wait, daemon=True).start()


def _require_capture_writer_acknowledgement(
    *, acknowledgement_read_fd: int, writer: subprocess.Popen[bytes]
) -> None:
    """Require writer readiness before a workload receives a capture pipe.

    Args:
        acknowledgement_read_fd (int): Parent read endpoint for the startup signal.
        writer (subprocess.Popen[bytes]): Independent writer whose health is checked.

    Raises:
        OSError: If the writer exits, times out, or emits an invalid acknowledgement.
    """
    ready, _, _ = select.select(
        [acknowledgement_read_fd],
        [],
        [],
        _CAPTURE_WRITER_STARTUP_TIMEOUT_SECONDS,
    )
    if not ready:
        raise OSError("capture writer did not acknowledge startup")
    acknowledgement: bytes = os.read(acknowledgement_read_fd, len(_CAPTURE_WRITER_STARTUP_ACKNOWLEDGEMENT))
    if acknowledgement != _CAPTURE_WRITER_STARTUP_ACKNOWLEDGEMENT:
        raise OSError("capture writer did not acknowledge startup")


def redact_openrouter_credential(*, raw: bytes, credential: bytes) -> bytes:
    """Replace only the literal forwarded OpenRouter credential in captured bytes.

    WHAT: Applies the narrow credential redaction required for parent-owned
        detached stdout/stderr file-descriptor captures.
    WHO: Compatibility callers with complete buffers only. Production FD capture
        uses StreamingCredentialRedactor in its independent writer instead.
    WHEN: The caller already owns a complete buffer, never arbitrary FD chunks.

    Args:
        raw (bytes): One captured stdout or stderr chunk.
        credential (bytes): Exact UTF-8 credential forwarded to that process.

    Returns:
        bytes: Original bytes when no credential was forwarded, otherwise bytes
        with the literal credential replaced by ``[REDACTED]``.
    """
    if not credential:
        return raw
    return raw.replace(credential, b"[REDACTED]")


def _allowlisted_parent_env() -> dict[str, str]:
    """Return allowed non-secret values from the current process environment."""
    child_env: dict[str, str] = {}
    for name, value in os.environ.items():
        if name in _ENV_ALLOWLIST_EXACT:
            child_env[name] = value
            continue
        if _is_forwarded_slo_setting(name=name):
            child_env[name] = value
    return child_env


def _is_forwarded_slo_setting(*, name: str) -> bool:
    """Return whether a Slo setting is safe to inherit into a child process.

    Args:
        name (str): Parent environment variable name.

    Returns:
        bool: True for non-secret ``SLO_*`` settings, including the explicit
        ``SLO_PLUGINS_DISABLED`` policy switch.
    """
    if name in {"SLO_PLUGINS_DISABLED", "SLO_OPENROUTER_API_KEY"}:
        return True
    return name.startswith(_ENV_ALLOWLIST_PREFIXES) and not _is_secret_env_name(name=name)


def _add_workflow_id(*, child_env: dict[str, str], workflow_id: Optional[str]) -> None:
    """Add the workflow identifier when the spawn is workflow-owned."""
    if workflow_id is not None:
        child_env["SLO_WORKFLOW_ID"] = workflow_id


def _add_nonempty_extra(*, child_env: dict[str, str], extra: Optional[dict[str, str]]) -> None:
    """Add only non-empty caller-supplied child environment values."""
    for name, value in (extra or {}).items():
        if value:
            child_env[name] = value


def _is_secret_env_name(*, name: str) -> bool:
    """Return whether an environment variable name contains a secret marker."""
    upper_name: str = name.upper()
    return any(marker in upper_name for marker in _ENV_SECRET_MARKERS)
