"""Independent, stdlib-only capture writer; no parent event-loop dependency."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_STARTUP_ACKNOWLEDGEMENT: bytes = b"capture-writer-ready\n"
_FAILURE_ACKNOWLEDGEMENT: bytes = b"capture-writer-failed\n"


@dataclass(frozen=True, kw_only=True)
class WorkflowCaptureCompletionContext:
    """Private identity-only handoff; never a capture or credential payload."""

    history_root: Path
    owner_session_id: str
    workflow_id: str
    expected_pid: int

    def writer_environment(self) -> dict[str, str]:
        """Encode compatibility completion identity for legacy direct writer callers.

        Returns:
            dict[str, str]: Private inherited environment entries, without secrets.
        """
        return {"SLO_CAPTURE_COMPLETION": json.dumps(self.writer_payload())}

    @classmethod
    def report_failure(cls) -> None:
        """Report a writer-process failure when inherited completion identity exists."""
        serialized_context = os.environ.get("SLO_CAPTURE_COMPLETION")
        if serialized_context is None:
            return
        cls._report_serialized_failure(serialized_context=serialized_context)

    @classmethod
    def report_failure_context(cls, *, context: "WorkflowCaptureCompletionContext") -> None:
        """Report an activated parent-reaper failure through the existing store.

        Args:
            context (WorkflowCaptureCompletionContext): Private identity of the
                durably adopted workload that owns this writer.
        """
        # The parent already has the application runtime. Only the standalone
        # writer needs an isolated reporter interpreter; reapers use the same
        # store boundary directly, without another subprocess lifetime.
        from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore

        store = WorkflowHandleStore(history_root=context.history_root)
        store.record_capture_failure_sync(
            owner_session_id=context.owner_session_id,
            workflow_id=context.workflow_id,
            expected_pid=context.expected_pid,
        )

    @classmethod
    def _report_serialized_failure(cls, *, serialized_context: str) -> None:
        """Run the isolated synchronous store reporter without credentials or FDs."""
        source_root = Path(__file__).resolve().parents[4]
        script = (
            "import json,sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(source_root)!r}); "
            "from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleStore; "
            "data=json.loads(sys.argv[1]); "
            "history_root=Path(data.pop('history_root')); "
            "store=WorkflowHandleStore(history_root=history_root); "
            "store.record_capture_failure_sync(**data)"
        )
        try:
            subprocess.run(
                args=[sys.executable, "-I", "-B", "-c", script, serialized_context],
                env={},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                check=False,
            )
        except OSError:
            return

    def writer_payload(self) -> dict[str, str | int]:
        """Build the private JSON-safe workflow identity used by either reporter.

        Returns:
            dict[str, str | int]: Store location and expected workload identity.
        """
        return {
            "history_root": str(self.history_root.resolve()),
            "owner_session_id": self.owner_session_id,
            "workflow_id": self.workflow_id,
            "expected_pid": self.expected_pid,
        }


class _WriterActivation:
    """Private synchronization state for a writer's one-shot adoption frame."""

    def __init__(self) -> None:
        """Create an inactive writer activation state."""
        self.context: Optional[WorkflowCaptureCompletionContext] = None
        self.control_complete = threading.Event()

    def wait_for_control(self) -> None:
        """Wait for parent adoption or control EOF after a terminal writer failure."""
        self.control_complete.wait()


class StreamingCredentialRedactor:
    """Hold only a possible credential prefix between arbitrary byte chunks."""

    def __init__(self, *, credential: bytes) -> None:
        """Bind the literal captured at spawn, never a later environment value."""
        self._credential = credential
        self._pending = b""

    def feed(self, *, raw: bytes, final: bool = False) -> bytes:
        """Return safe bytes; EOF releases an unmatched partial prefix.

        Args:
            raw (bytes): Next FD chunk.
            final (bool): Whether the input has reached EOF.

        Returns:
            bytes: Bytes safe for immediate persistence.
        """
        data = self._pending + raw
        self._pending = b""
        if not self._credential:
            return data
        data = data.replace(self._credential, b"[REDACTED]")
        if final:
            return data
        for size in range(min(len(data), len(self._credential) - 1), 0, -1):
            if data.endswith(self._credential[:size]):
                self._pending = data[-size:]
                return data[:-size]
        return data

    @classmethod
    def invoke(cls) -> None:
        """Drain capture input while independently accepting one post-adoption control frame.

        WHAT: Starts readiness first, drains workload bytes without waiting for adoption,
            and reports a terminal writer failure only after the parent sends a valid
            durable workload identity.
        WHO: ``open_capture_file_append`` starts this isolated process for each capture.
        WHEN: The writer lives from pre-spawn readiness until input EOF and control
            completion; control EOF without adoption is intentionally silent.
        """
        acknowledgement_fd = cls._acknowledge_startup()
        activation = _WriterActivation()
        append_lock_fd = cls._append_lock_fd()
        control_thread = cls._start_control_reader(activation=activation)
        try:
            cls._drain_capture_input()
        except BaseException:
            cls._acknowledge_failure(acknowledgement_fd=acknowledgement_fd)
            activation.wait_for_control()
            if activation.context is not None:
                WorkflowCaptureCompletionContext._report_serialized_failure(
                    serialized_context=json.dumps(activation.context.writer_payload())
                )
            elif "SLO_CAPTURE_CONTROL_FD" not in os.environ:
                WorkflowCaptureCompletionContext.report_failure()
            raise
        finally:
            with __import__("contextlib").suppress(OSError):
                os.close(acknowledgement_fd)
            control_thread.join()
            cls._close_append_lock_fd(append_lock_fd=append_lock_fd)

    @classmethod
    def _drain_capture_input(cls) -> None:
        """Redact stdin chunks and flush them to the sole capture destination.

        WHAT: Owns the writer's complete read/redact/write/flush lifecycle.
        WHO: ``invoke`` calls it after startup acknowledgement.
        WHEN: Runs until every workload-held pipe endpoint closes.
        """
        redactor = cls(credential=os.environ.get("SLO_OPENROUTER_API_KEY", "").encode())
        while True:
            raw = os.read(0, 65536)
            safe = redactor.feed(raw=raw, final=not raw)
            sys.stdout.buffer.write(safe)
            sys.stdout.buffer.flush()
            if not raw:
                return

    @staticmethod
    def _acknowledge_startup() -> int:
        """Send readiness while retaining the control FD for a later failure signal.

        Returns:
            int: Open acknowledgement descriptor owned until writer exit.
        """
        acknowledgement_fd = int(os.environ["SLO_CAPTURE_WRITER_ACK_FD"])
        os.write(acknowledgement_fd, _STARTUP_ACKNOWLEDGEMENT)
        return acknowledgement_fd

    @classmethod
    def _start_control_reader(cls, *, activation: "_WriterActivation") -> threading.Thread:
        """Read the private one-shot adoption frame without blocking input drain.

        Args:
            activation (_WriterActivation): Shared terminal activation state.

        Returns:
            threading.Thread: Started reader that ends on a frame or clean EOF.
        """
        control_fd_text = os.environ.get("SLO_CAPTURE_CONTROL_FD")
        if control_fd_text is None:
            activation.context = cls._legacy_completion_context()
            activation.control_complete.set()
            completed_thread = threading.Thread(target=lambda: None)
            completed_thread.start()
            return completed_thread
        control_fd = int(control_fd_text)
        thread = threading.Thread(
            target=cls._read_control_frame,
            kwargs={"control_fd": control_fd, "activation": activation},
            daemon=False,
        )
        thread.start()
        return thread

    @classmethod
    def _read_control_frame(cls, *, control_fd: int, activation: "_WriterActivation") -> None:
        """Consume at most one bounded JSON control frame and always close its FD."""
        try:
            payload = b""
            while len(payload) <= 4096:
                ready, _, _ = select.select([control_fd], [], [], None)
                if not ready:
                    return
                chunk = os.read(control_fd, 4097 - len(payload))
                if not chunk:
                    break
                payload += chunk
            activation.context = cls._parse_control_context(payload=payload)
        except OSError:
            # Invalid control is inert; never print its bytes or a traceback.
            activation.context = None
        finally:
            with __import__("contextlib").suppress(OSError):
                os.close(control_fd)
            activation.control_complete.set()

    @classmethod
    def _parse_control_context(cls, *, payload: bytes) -> Optional[WorkflowCaptureCompletionContext]:
        """Return one validated activation context; malformed or duplicate input is inert."""
        if len(payload) > 4096:
            return None
        try:
            decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=cls._unique_control_fields)
            if not isinstance(decoded, dict) or set(decoded) != {
                "history_root",
                "owner_session_id",
                "workflow_id",
                "expected_pid",
            }:
                return None
            if not cls._valid_control_fields(fields=decoded):
                return None
            context = WorkflowCaptureCompletionContext(
                history_root=Path(decoded["history_root"]),
                owner_session_id=decoded["owner_session_id"],
                workflow_id=decoded["workflow_id"],
                expected_pid=decoded["expected_pid"],
            )
            return context if context.expected_pid > 0 else None
        except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _unique_control_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Reject repeated JSON keys before the control reader constructs identity.

        Args:
            pairs (list[tuple[str, object]]): Decoded object pairs in wire order.

        Returns:
            dict[str, object]: Unambiguous fields, retained only in memory.

        Raises:
            ValueError: A field was sent more than once.
        """
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("duplicate control field")
        return fields

    @classmethod
    def _valid_control_fields(cls, *, fields: dict[str, object]) -> bool:
        """Validate workload identity without coercion or filesystem access.

        Args:
            fields (dict[str, object]): Exact-key object from the private reader.

        Returns:
            bool: Whether the identity can safely address the existing store.
        """
        pid = fields["expected_pid"]
        root = fields["history_root"]
        if type(pid) is not int or pid <= 0:
            return False
        if not isinstance(root, str) or "\x00" in root or not Path(root).is_absolute():
            return False
        return all(
            cls._valid_identity_component(value=fields[key]) for key in ("owner_session_id", "workflow_id")
        )

    @staticmethod
    def _valid_identity_component(*, value: object) -> bool:
        """Accept only nonempty single path components from a control frame.

        Args:
            value (object): Untrusted decoded identity component.

        Returns:
            bool: Whether it cannot escape its store directory.
        """
        return (
            isinstance(value, str)
            and bool(value.strip())
            and value not in {".", ".."}
            and not any(character in value for character in ("/", "\\", "\x00"))
        )

    @staticmethod
    def _legacy_completion_context() -> Optional[WorkflowCaptureCompletionContext]:
        """Retain direct-writer compatibility without affecting control-FD production paths."""
        serialized_context = os.environ.get("SLO_CAPTURE_COMPLETION")
        if serialized_context is None:
            return None
        try:
            payload = json.loads(serialized_context)
            return WorkflowCaptureCompletionContext(
                history_root=Path(payload["history_root"]),
                owner_session_id=payload["owner_session_id"],
                workflow_id=payload["workflow_id"],
                expected_pid=payload["expected_pid"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _append_lock_fd() -> int | None:
        """Read the inherited append lease descriptor retained through writer drain."""
        descriptor = os.environ.get("SLO_CAPTURE_APPEND_LOCK_FD")
        return int(descriptor) if descriptor is not None else None

    @staticmethod
    def _close_append_lock_fd(*, append_lock_fd: int | None) -> None:
        """Release the inherited append lease only after the writer's final drain."""
        if append_lock_fd is None:
            return
        with __import__("contextlib").suppress(OSError):
            os.close(append_lock_fd)

    @staticmethod
    def _acknowledge_failure(*, acknowledgement_fd: int) -> None:
        """Report an asynchronous writer failure using fixed non-secret bytes.

        Args:
            acknowledgement_fd (int): Writer-owned control descriptor.
        """
        try:
            os.write(acknowledgement_fd, _FAILURE_ACKNOWLEDGEMENT)
        except OSError:
            pass


if __name__ == "__main__":
    try:
        StreamingCredentialRedactor.invoke()
    except BaseException:
        # Never render exceptions that might contain input or environment bytes.
        # Failed buffered output must not be flushed again by interpreter teardown.
        os._exit(1)
