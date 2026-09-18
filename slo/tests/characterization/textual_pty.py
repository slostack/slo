"""PTY capture support dedicated to the Slo 79.b.2 Textual baseline tests."""

from __future__ import annotations

import asyncio
import base64
import errno
import fcntl
import hashlib
import os
import select
import signal
import subprocess
import termios
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "PtyChildDAO",
    "PtyChildTimeoutError",
    "PtyInputStepDAO",
    "PtyRawBytesDAO",
    "PtyTerminalCaptureDAO",
    "TextualPtyCapture",
]

_CAPTURE_WIDTH: int = 100
_CAPTURE_HEIGHT: int = 30
_CAPTURE_IDLE_SECONDS: float = 0.05
_CAPTURE_POST_INPUT_SETTLE_SECONDS: float = 0.25
_CAPTURE_TERM_GRACE_SECONDS: float = 0.25
_CAPTURE_KILL_GRACE_SECONDS: float = 0.25
_READ_SIZE: int = 65_536


@dataclass(frozen=True)
class PtyInputStepDAO:
    """Describe one parent-owned PTY write and its real-child readiness barrier."""

    value: bytes
    input_after_bytes: bytes | None = None
    input_after_path: Path | None = None


@dataclass(frozen=True)
class PtyRawBytesDAO:
    """Provide a reversible JSON-safe representation of unfiltered PTY bytes."""

    base64: str
    length: int
    sha256: str

    @classmethod
    def from_bytes(cls, *, value: bytes) -> PtyRawBytesDAO:
        """Build a JSON-safe representation without altering the captured bytes.

        Args:
            value (bytes): Raw PTY output in original emission order.

        Returns:
            PtyRawBytesDAO: Reversible base64 data plus byte length and SHA-256.
        """
        return cls(
            base64=base64.b64encode(value).decode("ascii"),
            length=len(value),
            sha256=hashlib.sha256(value).hexdigest(),
        )


@dataclass(frozen=True)
class PtyChildDAO:
    """Describe the separately executed and reaped CLI child process."""

    command: tuple[str, ...]
    pid: int
    reaped: bool
    return_code: int | None
    cleanup_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class PtyTerminalCaptureDAO:
    """Represent raw emitted terminal bytes and their parsed terminal state."""

    child: PtyChildDAO
    cursor_column: int
    cursor_row: int
    frame: list[str]
    raw: PtyRawBytesDAO
    raw_bytes: bytes
    scrollback: list[str]
    written_input: bytes
    written_inputs: tuple[bytes, ...]


class PtyChildTimeoutError(AssertionError):
    """Report a timed-out PTY child after the harness has reaped it."""

    def __init__(self, *, child: PtyChildDAO, raw_bytes: bytes, timeout_seconds: float) -> None:
        """Build a concise timeout diagnostic retaining process and output evidence.

        Args:
            child (PtyChildDAO): Child status after bounded cleanup/reaping.
            raw_bytes (bytes): Unfiltered emitted bytes captured before cleanup.
            timeout_seconds (float): Original hard run timeout.
        """
        self.child: PtyChildDAO = child
        self.raw_bytes: bytes = raw_bytes
        tail: str = raw_bytes[-400:].decode("utf-8", errors="backslashreplace")
        super().__init__(
            "Textual PTY child exceeded "
            f"{timeout_seconds:.3f}s (pid={child.pid}, return_code={child.return_code}, raw_tail={tail!r})"
        )


class TextualPtyCapture:
    """Run one real Slo CLI process through an OS PTY boundary."""

    @classmethod
    async def invoke(
        cls,
        *,
        command: tuple[str, ...],
        cwd: Path,
        environment: Mapping[str, str] | None = None,
        isolated_environment: bool = False,
        input_after_bytes: bytes | None = None,
        input_after_path: Path | None = None,
        input_bytes: tuple[bytes, ...] = (),
        input_steps: tuple[PtyInputStepDAO, ...] = (),
        terminal_height: int = _CAPTURE_HEIGHT,
        terminal_width: int = _CAPTURE_WIDTH,
        timeout_seconds: float = 5.0,
    ) -> PtyTerminalCaptureDAO:
        """Spawn, drive, collect, parse, close, and reap one CLI PTY process.

        WHAT: Uses ``subprocess.Popen`` with the slave end of a genuine OS PTY
            attached to stdin/stdout/stderr. Parent-side input is always written
            through ``os.write(master_fd, ...)``; no in-process Textual pilot or
            private application state participates in terminal evidence.
        WHO: Focused helper tests use this before the named b.2 baseline cases
            are migrated from their legacy in-process harness.
        WHEN: Any characterization needs terminal bytes from the real CLI/TUI
            dispatch chain rather than a Textual test harness.

        Args:
            command (tuple[str, ...]): Real child command, normally
                ``(sys.executable, "-m", "src.cli")``.
            cwd (Path): Worktree from which the child imports and launches Slo.
            environment (Mapping[str, str] | None): Deterministic child
                environment. It is additive by default and exact when
                ``isolated_environment`` is true.
            isolated_environment (bool): When true, do not inherit parent
                environment variables such as provider credentials.
            input_after_bytes (bytes | None): Wait until these raw bytes arrive
                before writing ``input_bytes``. ``None`` does not require raw-byte readiness.
            input_after_path (Path | None): Wait until this child-owned readiness
                marker exists before writing ``input_bytes``.
            input_bytes (tuple[bytes, ...]): Legacy bytes written by the parent
                after the shared readiness barriers. Do not combine with
                ``input_steps``.
            input_steps (tuple[PtyInputStepDAO, ...]): Ordered parent writes,
                each with its own raw-byte and/or child-file readiness barrier.
                This is the real-child interaction API for multi-stage TUI flows.
            terminal_height (int): Fixed PTY row count for pyte capture.
            terminal_width (int): Fixed PTY column count for pyte capture.
            timeout_seconds (float): Hard bounded run timeout before TERM/KILL.

        Returns:
            PtyTerminalCaptureDAO: Separate-child identity/status, raw evidence,
            pyte frame/scrollback/cursor, and the exact written input bytes.

        Raises:
            AssertionError: If input preconditions are unmet or the child exits
                unsuccessfully.
            PtyChildTimeoutError: If timeout cleanup had to reap the child.
        """
        return await asyncio.to_thread(
            cls._invoke_blocking,
            command=command,
            cwd=cwd,
            environment=environment,
            isolated_environment=isolated_environment,
            input_after_bytes=input_after_bytes,
            input_after_path=input_after_path,
            input_bytes=input_bytes,
            input_steps=input_steps,
            terminal_height=terminal_height,
            terminal_width=terminal_width,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def _invoke_blocking(
        cls,
        *,
        command: tuple[str, ...],
        cwd: Path,
        environment: Mapping[str, str] | None,
        isolated_environment: bool,
        input_after_bytes: bytes | None,
        input_after_path: Path | None,
        input_bytes: tuple[bytes, ...],
        input_steps: tuple[PtyInputStepDAO, ...],
        terminal_height: int,
        terminal_width: int,
        timeout_seconds: float,
    ) -> PtyTerminalCaptureDAO:
        """Execute the complete bounded subprocess PTY lifecycle synchronously.

        Args:
            command (tuple[str, ...]): CLI command executed in the child.
            cwd (Path): Child working directory.
            environment (Mapping[str, str] | None): Additive child environment.
            input_after_bytes (bytes | None): Raw-output write barrier.
            input_bytes (tuple[bytes, ...]): Parent input writes.
            terminal_height (int): PTY/pyte rows.
            terminal_width (int): PTY/pyte columns.
            timeout_seconds (float): Hard process deadline.

        Returns:
            PtyTerminalCaptureDAO: Capture plus reaped child status.
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        master_fd, slave_fd = os.openpty()
        process: subprocess.Popen[bytes] | None = None
        raw_chunks: list[bytes] = []
        written_inputs: tuple[bytes, ...] = ()
        try:
            cls._set_terminal_size(
                terminal_fd=master_fd,
                terminal_height=terminal_height,
                terminal_width=terminal_width,
            )
            cls._set_nonblocking(file_descriptor=master_fd)
            child_environment: dict[str, str] = {} if isolated_environment else dict(os.environ)
            child_environment.update(environment or {})
            child_environment.setdefault("TERM", "xterm-256color")
            process = subprocess.Popen(
                args=command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=child_environment,
                close_fds=True,
                start_new_session=True,
            )
            os.close(slave_fd)
            slave_fd = -1
            written_inputs = cls._collect_and_write_input(
                command=command,
                master_fd=master_fd,
                process=process,
                raw_chunks=raw_chunks,
                input_after_bytes=input_after_bytes,
                input_after_path=input_after_path,
                input_bytes=input_bytes,
                input_steps=input_steps,
                timeout_seconds=timeout_seconds,
            )
            cls._drain_post_input_settle(
                master_fd=master_fd,
                raw_chunks=raw_chunks,
            )
            raw_bytes: bytes = cls._drain_until_exit(
                command=command,
                master_fd=master_fd,
                process=process,
                raw_chunks=raw_chunks,
                timeout_seconds=timeout_seconds,
            )
            child: PtyChildDAO = cls._child_dao(process=process, command=command)
            if child.return_code != 0:
                raise AssertionError(cls._failed_child_message(child=child, raw_bytes=raw_bytes))
            return cls._parse_terminal_bytes(
                child=child,
                raw_bytes=raw_bytes,
                terminal_height=terminal_height,
                terminal_width=terminal_width,
                written_input=b"".join(written_inputs),
                written_inputs=written_inputs,
            )
        except PtyChildTimeoutError:
            raise
        finally:
            if process is not None and process.poll() is None:
                cls._terminate_and_reap(process=process, command=command)
            if slave_fd >= 0:
                os.close(slave_fd)
            os.close(master_fd)

    @classmethod
    def _collect_and_write_input(
        cls,
        *,
        command: tuple[str, ...],
        master_fd: int,
        process: subprocess.Popen[bytes],
        raw_chunks: list[bytes],
        input_after_bytes: bytes | None,
        input_after_path: Path | None,
        input_bytes: tuple[bytes, ...],
        input_steps: tuple[PtyInputStepDAO, ...],
        timeout_seconds: float,
    ) -> tuple[bytes, ...]:
        """Collect startup bytes and write every requested input sequence once.

        Args:
            master_fd (int): Parent PTY master descriptor.
            process (subprocess.Popen[bytes]): Active child process.
            raw_chunks (list[bytes]): Ordered, unfiltered raw output sink.
            input_after_bytes (bytes | None): Raw-output startup barrier before input.
            input_after_path (Path | None): Child readiness-file barrier before input.
            input_bytes (tuple[bytes, ...]): Legacy requested parent writes.
            input_steps (tuple[PtyInputStepDAO, ...]): Explicit staged writes.
            timeout_seconds (float): Shared hard deadline.

        Returns:
            tuple[bytes, ...]: Exact successful parent writes in order.

        Raises:
            ValueError: If callers mix the legacy shared-barrier API and staged writes.
        """
        if input_bytes and input_steps:
            raise ValueError("Textual PTY capture accepts input_bytes or input_steps, not both")
        steps: tuple[PtyInputStepDAO, ...] = input_steps or tuple(
            PtyInputStepDAO(
                value=value,
                input_after_bytes=input_after_bytes,
                input_after_path=input_after_path,
            )
            for value in input_bytes
        )
        deadline: float = time.monotonic() + timeout_seconds
        written_parts: list[bytes] = []
        for step in steps:
            cls._wait_for_input_barrier(
                command=command,
                master_fd=master_fd,
                process=process,
                raw_chunks=raw_chunks,
                input_after_bytes=step.input_after_bytes,
                input_after_path=step.input_after_path,
                deadline=deadline,
                timeout_seconds=timeout_seconds,
            )
            cls._write_all(master_fd=master_fd, value=step.value)
            written_parts.append(step.value)
        return tuple(written_parts)

    @classmethod
    def _wait_for_input_barrier(
        cls,
        *,
        command: tuple[str, ...],
        master_fd: int,
        process: subprocess.Popen[bytes],
        raw_chunks: list[bytes],
        input_after_bytes: bytes | None,
        input_after_path: Path | None,
        deadline: float,
        timeout_seconds: float,
    ) -> None:
        """Wait for one child-observable barrier before a single parent write."""
        while not cls._input_barrier_reached(
            input_after_bytes=input_after_bytes,
            input_after_path=input_after_path,
            raw_bytes=b"".join(raw_chunks),
        ):
            cls._drain_available(
                master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=_CAPTURE_IDLE_SECONDS
            )
            cls._drain_available(master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=0.0)
            if process.poll() is not None:
                raise AssertionError(
                    "Textual PTY child exited before input barrier "
                    f"(return_code={process.returncode}, raw_tail={cls._raw_tail(raw_bytes=b''.join(raw_chunks))!r})"
                )
            if time.monotonic() >= deadline:
                child: PtyChildDAO = cls._terminate_and_reap(process=process, command=command)
                raise PtyChildTimeoutError(
                    child=child,
                    raw_bytes=b"".join(raw_chunks),
                    timeout_seconds=timeout_seconds,
                )

    @staticmethod
    def _input_barrier_reached(
        *,
        input_after_bytes: bytes | None,
        input_after_path: Path | None,
        raw_bytes: bytes,
    ) -> bool:
        """Return whether every requested parent input barrier is satisfied.

        Args:
            input_after_bytes (bytes | None): Required raw PTY marker.
            input_after_path (Path | None): Required child readiness-file marker.
            raw_bytes (bytes): Bytes collected from the real PTY so far.

        Returns:
            bool: True when no barrier was requested or every one has arrived.
        """
        byte_barrier_reached: bool = input_after_bytes is None or input_after_bytes in raw_bytes
        path_barrier_reached: bool = input_after_path is None or input_after_path.is_file()
        return byte_barrier_reached and path_barrier_reached

    @classmethod
    def _drain_post_input_settle(
        cls,
        *,
        master_fd: int,
        raw_chunks: list[bytes],
    ) -> None:
        """Collect terminal bytes scheduled by the final public input action.

        Args:
            master_fd (int): Parent PTY master descriptor.
            raw_chunks (list[bytes]): Ordered raw output sink.
        """
        cls._drain_available(
            master_fd=master_fd,
            raw_chunks=raw_chunks,
            timeout_seconds=_CAPTURE_POST_INPUT_SETTLE_SECONDS,
        )
        cls._drain_available(master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=0.0)

    @classmethod
    def _drain_until_exit(
        cls,
        *,
        command: tuple[str, ...],
        master_fd: int,
        process: subprocess.Popen[bytes],
        raw_chunks: list[bytes],
        timeout_seconds: float,
    ) -> bytes:
        """Collect raw output until normal child exit, then drain residual bytes.

        Args:
            master_fd (int): Parent PTY master descriptor.
            process (subprocess.Popen[bytes]): Active child process.
            raw_chunks (list[bytes]): Ordered raw output sink.
            timeout_seconds (float): Hard deadline from this phase.

        Returns:
            bytes: All bytes received in order before terminal EOF/quiescence.
        """
        deadline: float = time.monotonic() + timeout_seconds
        while process.poll() is None:
            cls._drain_available(
                master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=_CAPTURE_IDLE_SECONDS
            )
            cls._drain_available(master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=0.0)
            if time.monotonic() >= deadline:
                child: PtyChildDAO = cls._terminate_and_reap(process=process, command=command)
                raise PtyChildTimeoutError(
                    child=child,
                    raw_bytes=b"".join(raw_chunks),
                    timeout_seconds=timeout_seconds,
                )
        cls._drain_available(
            master_fd=master_fd, raw_chunks=raw_chunks, timeout_seconds=_CAPTURE_IDLE_SECONDS
        )
        return b"".join(raw_chunks)

    @classmethod
    def _terminate_and_reap(
        cls,
        *,
        process: subprocess.Popen[bytes],
        command: tuple[str, ...],
    ) -> PtyChildDAO:
        """Terminate then kill a process group when needed, always reaping it.

        Args:
            process (subprocess.Popen[bytes]): Child started in its own session.
            command (tuple[str, ...]): Original child command for diagnostic data.

        Returns:
            PtyChildDAO: Final reaped status after bounded TERM/KILL cleanup.
        """
        cleanup_signals: list[str] = []
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            cleanup_signals.append("TERM")
            try:
                process.wait(timeout=_CAPTURE_TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                cleanup_signals.append("KILL")
                process.wait(timeout=_CAPTURE_KILL_GRACE_SECONDS)
        return cls._child_dao(
            process=process,
            command=command,
            cleanup_signals=tuple(cleanup_signals),
        )

    @classmethod
    def _drain_available(
        cls,
        *,
        master_fd: int,
        raw_chunks: list[bytes],
        timeout_seconds: float,
    ) -> None:
        """Append every currently available PTY byte chunk without filtering it.

        Args:
            master_fd (int): Parent PTY master descriptor.
            raw_chunks (list[bytes]): Ordered raw output sink.
            timeout_seconds (float): Select timeout for this bounded poll.
        """
        readable, _, _ = select.select([master_fd], [], [], timeout_seconds)
        if master_fd not in readable:
            return
        while True:
            try:
                emitted: bytes = os.read(master_fd, _READ_SIZE)
            except BlockingIOError:
                return
            except OSError as error:
                if error.errno == errno.EIO:
                    return
                raise
            if not emitted:
                return
            raw_chunks.append(emitted)

    @staticmethod
    def _write_all(*, master_fd: int, value: bytes) -> None:
        """Write one exact input payload to a PTY master through ``os.write``.

        Args:
            master_fd (int): Parent PTY master descriptor.
            value (bytes): Input sequence to deliver exactly once.
        """
        written: int = 0
        while written < len(value):
            written += os.write(master_fd, value[written:])

    @classmethod
    def _parse_terminal_bytes(
        cls,
        *,
        child: PtyChildDAO,
        raw_bytes: bytes,
        terminal_height: int,
        terminal_width: int,
        written_input: bytes,
        written_inputs: tuple[bytes, ...],
    ) -> PtyTerminalCaptureDAO:
        """Feed unmodified raw terminal bytes to pyte and capture final state.

        Args:
            child (PtyChildDAO): Reaped CLI process evidence.
            raw_bytes (bytes): Exact captured PTY bytes.
            terminal_height (int): pyte viewport rows.
            terminal_width (int): pyte viewport columns.
            written_input (bytes): Exact concatenated parent input delivered via the master.
            written_inputs (tuple[bytes, ...]): Individual parent master writes in order.

        Returns:
            PtyTerminalCaptureDAO: Raw, frame, scrollback, and cursor evidence.
        """
        try:
            import pyte
        except ImportError as error:
            raise AssertionError("Textual PTY baseline requires pyte") from error
        screen: pyte.HistoryScreen = pyte.HistoryScreen(
            columns=terminal_width,
            lines=terminal_height,
            history=1_000,
        )
        pyte.Stream(screen).feed(raw_bytes.decode("utf-8", errors="replace"))
        return PtyTerminalCaptureDAO(
            child=child,
            cursor_column=screen.cursor.x,
            cursor_row=screen.cursor.y,
            frame=[line.rstrip() for line in screen.display],
            raw=PtyRawBytesDAO.from_bytes(value=raw_bytes),
            raw_bytes=raw_bytes,
            scrollback=[
                cls._history_line(line=line, terminal_width=terminal_width).rstrip()
                for line in screen.history.top
            ],
            written_input=written_input,
            written_inputs=written_inputs,
        )

    @staticmethod
    def _history_line(*, line: object, terminal_width: int) -> str:
        """Convert one pyte scrollback sparse buffer to a visible fixed-width row.

        Args:
            line (object): pyte history row buffer.
            terminal_width (int): Fixed display width of the capture.

        Returns:
            str: Visible characters in terminal column order.
        """
        cells: Any = line
        return "".join(getattr(cells[index], "data", " ") for index in range(terminal_width))

    @staticmethod
    def _child_dao(
        *,
        process: subprocess.Popen[bytes],
        command: tuple[str, ...],
        cleanup_signals: tuple[str, ...] = (),
    ) -> PtyChildDAO:
        """Build process proof only after normal or cleanup reaping.

        Args:
            process (subprocess.Popen[bytes]): Child process whose status is known.
            command (tuple[str, ...]): Child CLI command.
            cleanup_signals (tuple[str, ...]): Signals sent during timeout cleanup.

        Returns:
            PtyChildDAO: PID, exact command, exit status, and reaped proof.
        """
        return PtyChildDAO(
            command=command,
            pid=process.pid,
            reaped=process.poll() is not None,
            return_code=process.returncode,
            cleanup_signals=cleanup_signals,
        )

    @classmethod
    def _failed_child_message(cls, *, child: PtyChildDAO, raw_bytes: bytes) -> str:
        """Format useful terminal diagnostics for a nonzero child exit.

        Args:
            child (PtyChildDAO): Reaped nonzero child status.
            raw_bytes (bytes): Ordered raw output emitted before exit.

        Returns:
            str: Failure detail with process status and unfiltered output tail.
        """
        return (
            "Textual PTY child exited unsuccessfully "
            f"(pid={child.pid}, return_code={child.return_code}, raw_tail={cls._raw_tail(raw_bytes=raw_bytes)!r})"
        )

    @staticmethod
    def _raw_tail(*, raw_bytes: bytes) -> str:
        """Decode a bounded raw-output tail solely for an error diagnostic.

        Args:
            raw_bytes (bytes): Unfiltered captured terminal bytes.

        Returns:
            str: Lossless escaped diagnostic rendering of the final bytes.
        """
        return raw_bytes[-400:].decode("utf-8", errors="backslashreplace")

    @staticmethod
    def _set_terminal_size(*, terminal_fd: int, terminal_height: int, terminal_width: int) -> None:
        """Apply fixed geometry to the actual PTY master before child startup.

        Args:
            terminal_fd (int): Parent PTY master descriptor.
            terminal_height (int): Desired terminal row count.
            terminal_width (int): Desired terminal column count.
        """
        termios.tcsetwinsize(terminal_fd, (terminal_height, terminal_width))

    @staticmethod
    def _set_nonblocking(*, file_descriptor: int) -> None:
        """Put a parent-owned descriptor into nonblocking collection mode.

        Args:
            file_descriptor (int): Descriptor used by the parent collector.
        """
        flags: int = fcntl.fcntl(file_descriptor, fcntl.F_GETFL)
        fcntl.fcntl(file_descriptor, fcntl.F_SETFL, flags | os.O_NONBLOCK)
