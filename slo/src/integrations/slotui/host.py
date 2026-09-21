"""Persistent isolated Slotui candidate-adapter lifecycle.

The candidate receives a Unix control socket; its terminal stdio is never used
for JSON.  Slo never imports Slotui and never assumes candidate constructors.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
import termios
import tempfile
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.integrations.slotui.dao import SlotuiCoreVerificationReceiptDAO
from src.integrations.slotui.host_protocol import (
    SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
    SlotuiHostCommandDAO,
    SlotuiHostEventDAO,
    SlotuiHostLaunchConfigDAO,
    SlotuiStreamEventMapper,
)

__all__ = [
    "InstalledSlotuiHostProcess",
    "InstalledSlotuiHostProcessFactory",
    "SlotuiCoreHostError",
    "SlotuiCoreHostService",
    "SlotuiHostProcess",
    "SlotuiHostProcessFactory",
]

_STARTUP_TIMEOUT_SECONDS: float = 20.0
_SHUTDOWN_TIMEOUT_SECONDS: float = 3.0
_STDERR_LIMIT_BYTES: int = 8_192
_FORBIDDEN_SLOTUI_SOURCE: Path = Path("/root/Code/slo-tui/src")


class SlotuiCoreHostError(RuntimeError):
    """Report a fail-closed candidate host lifecycle failure."""


class SlotuiHostProcess(Protocol):
    """Port for an installed candidate process connected only by control IPC."""

    async def start(self, *, config: SlotuiHostLaunchConfigDAO) -> None:
        """Start the child and wait for a verified active lifecycle event."""

    def receive(self) -> AsyncIterator[SlotuiHostEventDAO]:
        """Yield candidate lifecycle/editor events from control IPC."""

    async def require_transcript_ack(self, *, mutation_id: str) -> None:
        """Require candidate acknowledgement of one exact parent stream mutation."""

    async def send(self, *, command: SlotuiHostCommandDAO) -> None:
        """Send a parent command on the isolated control channel."""

    async def aclose(self) -> None:
        """Close the control channel and reap all child resources."""


class SlotuiHostProcessFactory(Protocol):
    """Factory seam that permits process-free lifecycle tests."""

    def build(self, *, receipt: SlotuiCoreVerificationReceiptDAO) -> SlotuiHostProcess:
        """Build a host process for one statically verified candidate receipt."""


class SlotuiCoreHostService:
    """Coordinate one actual parent Slo session and one candidate adapter host."""

    def __init__(
        self,
        *,
        session: SloAgentSession,
        process: SlotuiHostProcess,
        workdir: Path,
        resume_session_id: str | None,
    ) -> None:
        """Store parent session and candidate control-port collaborators.

        Args:
            session (SloAgentSession): Real Slo session that owns all agent invocation.
            process (SlotuiHostProcess): Isolated candidate adapter process port.
            workdir (Path): Resolved Slo working directory.
            resume_session_id (str | None): Canonical requested resume identifier.
        """
        self._session: SloAgentSession = session
        self._process: SlotuiHostProcess = process
        self._workdir: Path = workdir
        self._resume_session_id: str | None = resume_session_id
        self._prompt_task: asyncio.Task[None] | None = None
        self._mutation_sequence: int = 0

    async def invoke(self) -> None:
        """Run the candidate host until it exits, fails, or is closed.

        Raises:
            SlotuiCoreHostError: If startup, submission, or candidate lifecycle fails.
        """
        try:
            await self._start_process()
            await self._send_startup_notices()
            await self._consume_host_events()
            await self._await_prompt_task()
        finally:
            await self._cancel_prompt_task()
            await self._process.aclose()

    async def _start_process(self) -> None:
        """Start the candidate against exact resolved parent-session facts."""
        await self._process.start(
            config=SlotuiHostLaunchConfigDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                workdir=str(self._workdir),
                resume_session_id=self._resume_session_id,
                session_id=self._session.session_id,
                control_socket_path="provided-by-process",
                adapter_declaration="provided-by-process",
            )
        )

    async def _send_startup_notices(self) -> None:
        """Send explicit unavailable/fallback notices after candidate readiness."""
        for notice in SlotuiStreamEventMapper.unsupported_surface_notices():
            await self._process.send(
                command=SlotuiHostCommandDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    kind="session_notice",
                    notice=notice,
                )
            )

    async def _consume_host_events(self) -> None:
        """Apply reject-while-busy editor policy and consume terminal lifecycle events.

        Raises:
            SlotuiCoreHostError: If candidate reports failure or an impossible lifecycle event.
        """
        async for event in self._process.receive():
            if event.kind == "editor_submit":
                await self._accept_or_reject_prompt(prompt=event.prompt)
                continue
            if event.kind == "host_closed":
                await self._await_prompt_task()
                return
            if event.kind == "host_failed":
                raise SlotuiCoreHostError(event.detail or "candidate adapter reported host failure")
            raise SlotuiCoreHostError(f"candidate adapter emitted unexpected lifecycle event: {event.kind}")

    async def _accept_or_reject_prompt(self, *, prompt: str | None) -> None:
        """Start one prompt or send a visible rejection rather than queueing it.

        Args:
            prompt (str | None): Editor text received over control IPC.
        """
        if prompt is None or not prompt.strip():
            return
        if self._is_prompt_active():
            await self._process.send(
                command=SlotuiHostCommandDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    kind="session_notice",
                    notice="Slotui rejected this editor submission because a Slo prompt is already active.",
                )
            )
            return
        self._prompt_task = asyncio.create_task(self._forward_session_events(prompt=prompt))

    def _is_prompt_active(self) -> bool:
        """Determine whether the single allowed parent prompt is still executing.

        Returns:
            bool: Whether a previous editor submission owns the session.
        """
        return self._prompt_task is not None and not self._prompt_task.done()

    async def _forward_session_events(self, *, prompt: str) -> None:
        """Forward one parent invocation and surface errors as transcript failure.

        Args:
            prompt (str): Accepted non-empty editor submission.
        """
        try:
            async for event in self._session.invoke(text=prompt):
                mutation_id: str = self._next_mutation_id()
                await self._process.send(
                    command=SlotuiHostCommandDAO(
                        protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                        kind="stream_event",
                        mutation=SlotuiStreamEventMapper.invoke(event=event),
                        mutation_id=mutation_id,
                    )
                )
                await self._require_transcript_ack(mutation_id=mutation_id)
                if event.kind in {"run_completed", "text_end"}:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._process.send(
                command=SlotuiHostCommandDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    kind="session_failed",
                    notice=f"Slo session failed: {type(error).__name__}: {error}",
                )
            )

    def _next_mutation_id(self) -> str:
        """Allocate one monotonic acknowledgement key for a parent stream mutation.

        Returns:
            str: Process-local mutation identifier that the candidate must acknowledge.
        """
        self._mutation_sequence += 1
        return f"slotui-mutation-{self._mutation_sequence}"

    async def _require_transcript_ack(self, *, mutation_id: str) -> None:
        """Require the candidate control port to acknowledge one streamed mutation.

        The concrete installed process routes acknowledgement frames through a
        dedicated queue, so this wait cannot steal an editor/lifecycle event
        from the host-event consumer. Test-only control ports implement the
        same protocol method only as a non-runtime architecture seam.

        Args:
            mutation_id (str): Parent-generated control mutation identifier.

        Raises:
            SlotuiCoreHostError: If the candidate does not acknowledge this exact mutation.
        """
        await self._process.require_transcript_ack(mutation_id=mutation_id)

    async def _await_prompt_task(self) -> None:
        """Await the one tracked prompt and preserve a useful host failure.

        Raises:
            SlotuiCoreHostError: If an unexpected task failure escaped forwarding.
        """
        if self._prompt_task is None:
            return
        try:
            await self._prompt_task
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise SlotuiCoreHostError("Slotui prompt forwarding failed") from error

    async def _cancel_prompt_task(self) -> None:
        """Cancel and consume one in-flight prompt task during teardown."""
        if self._prompt_task is None:
            return
        if not self._prompt_task.done():
            self._prompt_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._prompt_task


class InstalledSlotuiHostProcess:
    """Launch the verified candidate adapter in a fresh external installed-wheel venv."""

    def __init__(
        self,
        *,
        receipt: SlotuiCoreVerificationReceiptDAO,
        setup_timeout_seconds: float = _STARTUP_TIMEOUT_SECONDS,
        readiness_timeout_seconds: float = _STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        """Store immutable static receipt and bounded lifecycle timing.

        Args:
            receipt (SlotuiCoreVerificationReceiptDAO): Exact wheel and adapter manifest proof.
            setup_timeout_seconds (float): Venv/pip setup timeout. Defaults to 20 seconds.
            readiness_timeout_seconds (float): Socket/attestation readiness timeout. Defaults to 20 seconds.
        """
        self._receipt: SlotuiCoreVerificationReceiptDAO = receipt
        self._setup_timeout_seconds: float = setup_timeout_seconds
        self._readiness_timeout_seconds: float = readiness_timeout_seconds
        self._runtime_root: Path | None = None
        self._server: asyncio.AbstractServer | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: bytearray = bytearray()
        self._launch_acknowledged: bool = False
        self._event_queue: asyncio.Queue[SlotuiHostEventDAO] = asyncio.Queue()
        self._startup_events: deque[SlotuiHostEventDAO] = deque()
        self._ack_waiters: dict[str, asyncio.Future[None]] = {}
        self._sent_mutation_ids: set[str] = set()
        self._acknowledged_mutation_ids: set[str] = set()
        self._router_task: asyncio.Task[None] | None = None
        self._router_terminal: asyncio.Future[None] | None = None
        self._host_closed: asyncio.Future[None] | None = None
        self._router_failure: SlotuiCoreHostError | None = None
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._closing: bool = False
        self._closed: bool = False
        self._shutdown_sent: bool = False
        self._terminal_master_fd: int | None = None
        self._terminal_slave_fd: int | None = None
        self._terminal_original_attributes: list[int | list[bytes | int]] | None = None

    async def start(self, *, config: SlotuiHostLaunchConfigDAO) -> None:
        """Create, install, connect, and verify the candidate adapter transactionally.

        Args:
            config (SlotuiHostLaunchConfigDAO): Resolved parent facts; socket facts are replaced internally.

        Raises:
            SlotuiCoreHostError: If setup, readiness, attestation, or lifecycle readiness fails.
        """
        if self._closed or self._closing:
            raise SlotuiCoreHostError("Slotui candidate process cannot be started after close")
        try:
            runtime_root: Path = self._create_runtime_root()
            interpreter_path: Path = await self._create_and_install(runtime_root=runtime_root)
            socket_path: Path = runtime_root / "control.sock"
            await self._open_control_server(socket_path=socket_path)
            await self._spawn_candidate(interpreter_path=interpreter_path, socket_path=socket_path)
            await self._await_control_connection()
            await self._send_launch(config=config, socket_path=socket_path)
            await self._require_active_attestation()
        except Exception as error:
            await self.aclose()
            if isinstance(error, SlotuiCoreHostError):
                raise
            raise SlotuiCoreHostError("Slotui candidate startup failed") from error

    def receive(self) -> AsyncIterator[SlotuiHostEventDAO]:
        """Yield post-readiness candidate events until control EOF.

        Returns:
            AsyncIterator[SlotuiHostEventDAO]: Candidate lifecycle/editor stream.
        """
        return self._receive_events()

    async def _receive_events(self) -> AsyncIterator[SlotuiHostEventDAO]:
        """Yield router-owned lifecycle/editor frames after startup validation.

        Yields:
            SlotuiHostEventDAO: Candidate lifecycle or editor event received after readiness.

        Raises:
            SlotuiCoreHostError: If the dedicated socket reader fails before candidate closure.
        """
        while True:
            event: SlotuiHostEventDAO = await self._next_receive_event()
            yield event
            if event.kind == "host_closed":
                return

    async def require_transcript_ack(self, *, mutation_id: str) -> None:
        """Wait for the exact candidate acknowledgement assigned to one stream mutation.

        The dedicated socket reader owns all ``StreamReader`` access. It resolves
        this waiter's future by mutation ID while lifecycle/editor frames remain
        available to ``receive``.

        Args:
            mutation_id (str): Parent mutation key emitted with a stream command.

        Raises:
            SlotuiCoreHostError: If the mutation was not sent, is mismatched, or is not acknowledged in time.
        """
        if mutation_id not in self._sent_mutation_ids:
            raise SlotuiCoreHostError(
                "Slotui transcript acknowledgement was requested for an unsent mutation"
            )
        if mutation_id in self._acknowledged_mutation_ids:
            self._consume_acknowledgement(mutation_id=mutation_id)
            return
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        acknowledgement: asyncio.Future[None] = loop.create_future()
        self._ack_waiters[mutation_id] = acknowledgement
        try:
            await asyncio.wait_for(asyncio.shield(acknowledgement), timeout=self._readiness_timeout_seconds)
        except asyncio.TimeoutError as error:
            failure: SlotuiCoreHostError = SlotuiCoreHostError(
                f"Slotui candidate did not acknowledge transcript mutation {mutation_id} before timeout"
            )
            self._fail_socket_router(error=failure)
            raise failure from error
        finally:
            self._ack_waiters.pop(mutation_id, None)
            if acknowledgement.done():
                with contextlib.suppress(SlotuiCoreHostError, asyncio.CancelledError):
                    acknowledgement.exception()
        self._consume_acknowledgement(mutation_id=mutation_id)

    async def send(self, *, command: SlotuiHostCommandDAO) -> None:
        """Write one validated JSON line through the Unix control socket.

        Args:
            command (SlotuiHostCommandDAO): Parent command for the candidate adapter.

        Raises:
            SlotuiCoreHostError: If the lifecycle is closing or control IPC has failed.
        """
        await self._write_command(command=command, permit_during_close=False)

    async def aclose(self) -> None:
        """Request typed shutdown, then clean up every socket, task, process, and temp resource.

        The method is idempotent. It never competes with ``receive`` for a socket
        frame: the router resolves ``host_closed`` independently before a forced
        terminate is considered.
        """
        if self._closed:
            return
        self._closing = True
        orderly_closed: bool = await self._request_orderly_shutdown()
        await self._close_writer()
        await self._stop_process(force=not orderly_closed)
        await self._stop_server()
        await self._await_stderr_task()
        self._close_terminal_pty()
        self._remove_runtime_root()
        self._closed = True

    def _create_runtime_root(self) -> Path:
        """Create an isolated runtime root outside Slo and forbidden candidate source trees.

        Returns:
            Path: Fresh absolute runtime root.

        Raises:
            SlotuiCoreHostError: If a safe external directory cannot be established.
        """
        _require_parent_isolation()
        root: Path = Path(tempfile.mkdtemp(prefix="slo-slotui-host-")).resolve()
        slo_root: Path = _slo_source_root()
        if _is_within(path=root, parent=slo_root) or _is_within(path=root, parent=_FORBIDDEN_SLOTUI_SOURCE):
            shutil.rmtree(root, ignore_errors=True)
            raise SlotuiCoreHostError(
                "Slotui runtime root must be outside Slo and protected Slotui source trees"
            )
        self._runtime_root = root
        return root

    async def _create_and_install(self, *, runtime_root: Path) -> Path:
        """Create a fresh venv and install only the verified local wheel.

        Args:
            runtime_root (Path): Fresh root owning the new venv.

        Returns:
            Path: Installed-wheel interpreter path.
        """
        await _run_checked_command(
            command=(sys.executable, "-m", "venv", str(runtime_root / "venv")),
            cwd=runtime_root,
            timeout_seconds=self._setup_timeout_seconds,
        )
        interpreter: Path = runtime_root / "venv" / "bin" / "python"
        if not interpreter.is_file():
            raise SlotuiCoreHostError("Slotui candidate venv did not create a Python interpreter")
        verified_wheel_paths: tuple[Path, ...] = self._receipt.verified_wheel_paths
        await _run_checked_command(
            command=(
                str(interpreter),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-input",
                "--no-deps",
                *(str(wheel_path) for wheel_path in verified_wheel_paths),
            ),
            cwd=runtime_root,
            timeout_seconds=self._setup_timeout_seconds,
        )
        await _run_checked_command(
            command=(str(interpreter), "-I", "-m", "pip", "check"),
            cwd=runtime_root,
            timeout_seconds=self._setup_timeout_seconds,
        )
        return interpreter

    async def _open_control_server(self, *, socket_path: Path) -> None:
        """Listen on a private Unix socket for exactly one candidate connection.

        Args:
            socket_path (Path): Runtime-local Unix socket pathname.
        """
        self._server = await asyncio.start_unix_server(self._on_control_connection, path=str(socket_path))

    async def _spawn_candidate(self, *, interpreter_path: Path, socket_path: Path) -> None:
        """Spawn the candidate-defined adapter runner while leaving terminal streams untouched.

        Args:
            interpreter_path (Path): Fresh installed-wheel Python executable.
            socket_path (Path): Private parent control socket.
        """
        runner = self._receipt.manifest.candidate_runner
        command: tuple[str, ...] = (
            str(interpreter_path),
            "-I",
            "-m",
            runner.module,
            "--control-socket",
            str(socket_path),
            "--adapter-module",
            self._receipt.manifest.candidate_adapter.module,
            "--adapter-symbol",
            self._receipt.manifest.candidate_adapter.symbol,
            "--protocol-version",
            SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
        )
        _, terminal_slave_fd = self._open_terminal_pty()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self._runtime_root),
                env=_clean_child_environment(),
                stdin=terminal_slave_fd,
                stdout=terminal_slave_fd,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception:
            self._close_terminal_pty()
            raise
        os.close(terminal_slave_fd)
        self._terminal_slave_fd = None
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    def _open_terminal_pty(self) -> tuple[int, int]:
        """Allocate a private pseudo-terminal for the candidate terminal lifecycle.

        The candidate requires terminal ownership.  Pytest workers commonly have
        pipes for standard streams, so inheriting them would make the verified
        installed runner fail before its protocol hook can run.

        Returns:
            tuple[int, int]: Parent-read master descriptor and child stdio slave descriptor.
        """
        master_fd, slave_fd = __import__("pty").openpty()
        self._terminal_master_fd = master_fd
        self._terminal_slave_fd = slave_fd
        self._terminal_original_attributes = termios.tcgetattr(slave_fd)
        return master_fd, slave_fd

    def _close_terminal_pty(self) -> None:
        """Restore then close the host-owned pseudo-terminal descriptors exactly once."""
        if self._terminal_slave_fd is not None and self._terminal_original_attributes is not None:
            with contextlib.suppress(termios.error):
                termios.tcsetattr(
                    self._terminal_slave_fd,
                    termios.TCSADRAIN,
                    self._terminal_original_attributes,
                )
        for descriptor_name in ("_terminal_slave_fd", "_terminal_master_fd"):
            descriptor: int | None = getattr(self, descriptor_name)
            if descriptor is not None:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
                setattr(self, descriptor_name, None)
        self._terminal_original_attributes = None

    async def _on_control_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Accept one connection and immediately start the sole socket-reader task.

        Args:
            reader (asyncio.StreamReader): Candidate-to-parent socket reader.
            writer (asyncio.StreamWriter): Parent-to-candidate socket writer.
        """
        if self._reader is not None:
            writer.close()
            await writer.wait_closed()
            return
        self._reader = reader
        self._writer = writer
        self._start_socket_router()

    def _start_socket_router(self) -> None:
        """Start the sole reader that demultiplexes all candidate JSONL frames."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._router_terminal = loop.create_future()
        self._host_closed = loop.create_future()
        self._router_task = asyncio.create_task(self._consume_socket_events())

    async def _consume_socket_events(self) -> None:
        """Read every socket frame once and route it to typed consumers.

        WHAT: Owns the only ``StreamReader.readline`` loop and routes acknowledgements
        by mutation ID while publishing lifecycle/editor frames to the event queue.
        WHO: Started by ``_on_control_connection`` before launch is sent.
        WHEN: Lives from socket acceptance through peer EOF or host teardown.
        """
        try:
            while True:
                event: SlotuiHostEventDAO = await self._read_event()
                self._route_socket_event(event=event)
                if event.kind == "host_closed":
                    self._complete_socket_router()
                    return
        except asyncio.CancelledError:
            raise
        except SlotuiCoreHostError as error:
            self._fail_socket_router(error=error)
        except Exception as error:
            self._fail_socket_router(error=SlotuiCoreHostError("Slotui candidate socket router failed"))

    async def _await_control_connection(self) -> None:
        """Wait boundedly for socket connection while detecting child failure immediately.

        Raises:
            SlotuiCoreHostError: If candidate exits or does not establish control IPC.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        deadline: float = loop.time() + self._readiness_timeout_seconds
        while self._reader is None:
            if self._process is not None and self._process.returncode is not None:
                await self._await_stderr_task()
                raise SlotuiCoreHostError(
                    self._eof_message(prefix="candidate exited before control socket connect")
                )
            if loop.time() >= deadline:
                raise SlotuiCoreHostError(
                    "Slotui candidate did not connect to its control socket before readiness timeout"
                )
            await asyncio.sleep(0.01)
        if self._router_task is None:
            raise SlotuiCoreHostError("Slotui candidate control router did not start")

    async def _send_launch(self, *, config: SlotuiHostLaunchConfigDAO, socket_path: Path) -> None:
        """Send the exact launch configuration and require its ordered acknowledgement.

        Args:
            config (SlotuiHostLaunchConfigDAO): Parent-resolved Slo launch facts.
            socket_path (Path): Actual private socket location.
        """
        await self.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="launch",
                launch=SlotuiHostLaunchConfigDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    workdir=config.workdir,
                    resume_session_id=config.resume_session_id,
                    session_id=config.session_id,
                    control_socket_path=str(socket_path),
                    adapter_declaration=self._receipt.manifest.candidate_adapter.declaration,
                ),
            )
        )
        launch_ack: SlotuiHostEventDAO = await self._next_startup_event()
        if (
            launch_ack.kind != "launch_ack"
            or launch_ack.adapter_declaration != self._receipt.manifest.candidate_adapter.declaration
        ):
            raise SlotuiCoreHostError("Slotui candidate did not acknowledge the typed launch command")
        self._launch_acknowledged = True

    async def _require_active_attestation(self) -> None:
        """Require ordered attestation then all-ready host activation without consuming editor frames.

        Raises:
            SlotuiCoreHostError: If candidate does not attest isolation and full lifecycle readiness.
        """
        if not self._launch_acknowledged:
            raise SlotuiCoreHostError("Slotui candidate attestation requires acknowledged typed launch")
        attestation: SlotuiHostEventDAO = await self._next_startup_event()
        self._validate_attestation(event=attestation)
        active: SlotuiHostEventDAO = await self._next_startup_event()
        self._validate_active(event=active)

    async def _next_startup_event(self) -> SlotuiHostEventDAO:
        """Return the next lifecycle startup frame while preserving early editor submissions.

        Returns:
            SlotuiHostEventDAO: Ordered lifecycle frame for launch validation.

        Raises:
            SlotuiCoreHostError: If the peer fails, closes, or violates lifecycle ordering.
        """
        while True:
            event: SlotuiHostEventDAO = await self._next_routed_event()
            if event.kind == "editor_submit":
                self._startup_events.append(event)
                continue
            if event.kind == "host_closed":
                raise SlotuiCoreHostError("Slotui candidate closed before startup completed")
            if event.kind == "host_failed":
                raise SlotuiCoreHostError(event.detail or "Slotui candidate failed during startup")
            return event

    def _validate_attestation(self, *, event: SlotuiHostEventDAO) -> None:
        """Validate candidate installation and forbidden-source isolation attestation.

        Args:
            event (SlotuiHostEventDAO): Ordered candidate lifecycle message.

        Raises:
            SlotuiCoreHostError: If it does not prove installed-wheel isolation.
        """
        site_packages_marker: str = "site-packages"
        if (
            event.kind != "attestation"
            or event.adapter_declaration != self._receipt.manifest.candidate_adapter.declaration
            or event.source_paths_absent is not True
            or event.imported_module_path is None
            or site_packages_marker not in Path(event.imported_module_path).parts
            or _is_within(path=Path(event.imported_module_path), parent=_FORBIDDEN_SLOTUI_SOURCE)
        ):
            raise SlotuiCoreHostError("Slotui candidate adapter failed installed-wheel isolation attestation")

    def _validate_active(self, *, event: SlotuiHostEventDAO) -> None:
        """Accept active only after candidate reports a mounted TuiApp lifecycle.

        Args:
            event (SlotuiHostEventDAO): Ordered candidate lifecycle readiness event.

        Raises:
            SlotuiCoreHostError: If terminal/root/editor/transcript readiness is incomplete.
        """
        if (
            event.kind != "host_active"
            or event.adapter_declaration != self._receipt.manifest.candidate_adapter.declaration
            or not all((event.terminal_ready, event.root_ready, event.editor_ready, event.transcript_ready))
        ):
            raise SlotuiCoreHostError("Slotui candidate adapter did not report a ready TuiApp lifecycle")

    async def _next_receive_event(self) -> SlotuiHostEventDAO:
        """Return one buffered startup editor event or the next router lifecycle event.

        Returns:
            SlotuiHostEventDAO: Candidate lifecycle/editor event for the host service.
        """
        if self._startup_events:
            return self._startup_events.popleft()
        return await self._next_routed_event()

    async def _next_routed_event(self) -> SlotuiHostEventDAO:
        """Wait for lifecycle/editor input without ever reading the socket directly.

        Returns:
            SlotuiHostEventDAO: Next routed lifecycle/editor event.

        Raises:
            SlotuiCoreHostError: If the socket reader reached EOF or invalid JSON.
        """
        if self._router_failure is not None:
            raise self._router_failure
        if not self._event_queue.empty():
            return self._event_queue.get_nowait()
        try:
            return await asyncio.wait_for(self._event_queue.get(), timeout=self._readiness_timeout_seconds)
        except asyncio.TimeoutError as error:
            if self._router_failure is not None:
                raise self._router_failure from error
            raise SlotuiCoreHostError("Slotui candidate did not send a lifecycle event") from error

    async def _write_command(self, *, command: SlotuiHostCommandDAO, permit_during_close: bool) -> None:
        """Serialize validated control writes and register stream acknowledgements before peer receipt.

        Args:
            command (SlotuiHostCommandDAO): Parent command to encode as JSONL.
            permit_during_close (bool): Whether this is the one shutdown command during teardown.

        Raises:
            SlotuiCoreHostError: If control IPC is unavailable or cannot write.
        """
        if self._closed or (self._closing and not permit_during_close):
            raise SlotuiCoreHostError("Slotui candidate control channel is closing")
        if self._writer is None:
            raise SlotuiCoreHostError("Slotui candidate control channel is unavailable")
        async with self._write_lock:
            if self._writer is None:
                raise SlotuiCoreHostError("Slotui candidate control channel is unavailable")
            self._register_sent_mutation(command=command)
            payload: dict[str, object] = command.model_dump(exclude_none=True)
            if command.kind == "launch" and command.launch is not None:
                payload["launch"] = command.launch.model_dump()
            if command.kind == "stream_event" and command.mutation is not None:
                payload["mutation"] = command.mutation.model_dump()
            self._writer.write(
                (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
                ).encode("utf-8")
            )
            try:
                await self._writer.drain()
            except (ConnectionError, BrokenPipeError) as error:
                failure: SlotuiCoreHostError = SlotuiCoreHostError(
                    self._eof_message(prefix="control write failed")
                )
                self._fail_socket_router(error=failure)
                raise failure from error

    def _register_sent_mutation(self, *, command: SlotuiHostCommandDAO) -> None:
        """Record a stream mutation before its acknowledgement can arrive.

        Args:
            command (SlotuiHostCommandDAO): Encoded parent command.
        """
        if command.kind == "stream_event" and command.mutation_id is not None:
            self._sent_mutation_ids.add(command.mutation_id)

    def _route_socket_event(self, *, event: SlotuiHostEventDAO) -> None:
        """Demultiplex one validated candidate event from the sole socket reader.

        Args:
            event (SlotuiHostEventDAO): Candidate event read exactly once from JSONL.
        """
        if event.kind == "transcript_ack":
            self._route_transcript_ack(event=event)
            return
        if event.kind == "host_closed":
            self._resolve_host_closed()
        if event.kind == "host_failed":
            self._fail_host_lifecycle(detail=event.detail)
        self._event_queue.put_nowait(event)

    def _route_transcript_ack(self, *, event: SlotuiHostEventDAO) -> None:
        """Resolve the exact pending mutation acknowledgement or fail all consumers.

        Args:
            event (SlotuiHostEventDAO): Candidate acknowledgement event.
        """
        mutation_id: str = event.mutation_id or ""
        if mutation_id not in self._sent_mutation_ids:
            self._fail_socket_router(
                error=SlotuiCoreHostError("Slotui candidate acknowledged an unknown transcript mutation")
            )
            return
        acknowledgement: asyncio.Future[None] | None = self._ack_waiters.get(mutation_id)
        if acknowledgement is None:
            self._acknowledged_mutation_ids.add(mutation_id)
            return
        if not acknowledgement.done():
            acknowledgement.set_result(None)

    def _consume_acknowledgement(self, *, mutation_id: str) -> None:
        """Retire one matched acknowledgement so duplicates are protocol errors.

        Args:
            mutation_id (str): Successfully acknowledged stream mutation identifier.
        """
        self._acknowledged_mutation_ids.discard(mutation_id)
        self._sent_mutation_ids.discard(mutation_id)

    def _resolve_host_closed(self) -> None:
        """Notify teardown waiters without competing with lifecycle queue consumption."""
        host_closed: asyncio.Future[None] | None = self._host_closed
        if host_closed is not None and not host_closed.done():
            host_closed.set_result(None)

    def _fail_host_lifecycle(self, *, detail: str | None) -> None:
        """Fail acknowledgement and close waiters when the candidate reports host failure.

        Args:
            detail (str | None): Candidate-provided failure detail.
        """
        failure: SlotuiCoreHostError = SlotuiCoreHostError(detail or "Slotui candidate reported host failure")
        self._fail_waiters(error=failure)
        host_closed: asyncio.Future[None] | None = self._host_closed
        if host_closed is not None and not host_closed.done():
            host_closed.set_result(None)

    def _complete_socket_router(self) -> None:
        """Mark the dedicated reader complete after a typed orderly host closure."""
        router_terminal: asyncio.Future[None] | None = self._router_terminal
        if router_terminal is not None and not router_terminal.done():
            router_terminal.set_result(None)

    def _fail_socket_router(self, *, error: SlotuiCoreHostError) -> None:
        """Fan one EOF or invalid-frame error out to every router consumer.

        Args:
            error (SlotuiCoreHostError): Bounded diagnostic failure from the socket reader.
        """
        self._router_failure = error
        self._event_queue.put_nowait(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="host_failed",
                detail=str(error),
            )
        )
        router_terminal: asyncio.Future[None] | None = self._router_terminal
        if router_terminal is not None and not router_terminal.done():
            router_terminal.set_result(None)
        self._fail_waiters(error=error)
        host_closed: asyncio.Future[None] | None = self._host_closed
        if host_closed is not None and not host_closed.done():
            host_closed.set_result(None)

    def _fail_waiters(self, *, error: SlotuiCoreHostError) -> None:
        """Complete every exact-ack waiter with a shared router failure.

        Args:
            error (SlotuiCoreHostError): Failure propagated to all pending acknowledgement waits.
        """
        for acknowledgement in self._ack_waiters.values():
            if not acknowledgement.done():
                acknowledgement.set_exception(error)

    def _require_host_closed(self) -> asyncio.Future[None]:
        """Return the independent host-closure future used by teardown.

        Returns:
            asyncio.Future[None]: Completion signal for candidate orderly closure.

        Raises:
            SlotuiCoreHostError: If no accepted control connection started routing.
        """
        if self._host_closed is None:
            raise SlotuiCoreHostError("Slotui candidate control router is unavailable")
        return self._host_closed

    async def _read_event(self) -> SlotuiHostEventDAO:
        """Read and validate one JSONL event for the dedicated router only.

        Returns:
            SlotuiHostEventDAO: Validated candidate event.

        Raises:
            SlotuiCoreHostError: If control input is unavailable, closes, or emits invalid JSON.
        """
        if self._reader is None:
            raise SlotuiCoreHostError("Slotui candidate control channel is unavailable")
        line: bytes = await self._reader.readline()
        if not line:
            raise SlotuiCoreHostError(self._eof_message(prefix="candidate control channel closed"))
        try:
            return SlotuiHostEventDAO.model_validate_json(line)
        except ValueError as error:
            raise SlotuiCoreHostError("Slotui candidate emitted invalid control JSON") from error

    async def _request_orderly_shutdown(self) -> bool:
        """Send shutdown and wait through the router for candidate host closure.

        Returns:
            bool: Whether the candidate confirmed orderly closure before the bound.
        """
        if self._writer is None:
            return False
        host_closed: asyncio.Future[None] = self._require_host_closed()
        if host_closed.done():
            with contextlib.suppress(SlotuiCoreHostError):
                host_closed.result()
                return True
            return False
        try:
            await self._write_command(
                command=SlotuiHostCommandDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    kind="shutdown",
                ),
                permit_during_close=True,
            )
            self._shutdown_sent = True
            await asyncio.wait_for(asyncio.shield(host_closed), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            return True
        except (asyncio.TimeoutError, SlotuiCoreHostError):
            return False

    async def _drain_stderr(self) -> None:
        """Continuously drain bounded child stderr so process pipes cannot deadlock."""
        if self._process is None or self._process.stderr is None:
            return
        while chunk := await self._process.stderr.read(1024):
            self._stderr_tail.extend(chunk)
            del self._stderr_tail[:-_STDERR_LIMIT_BYTES]

    def _eof_message(self, *, prefix: str) -> str:
        """Build a useful bounded process/diagnostic message.

        Args:
            prefix (str): Lifecycle failure context.

        Returns:
            str: Error with child return code and capped stderr tail.
        """
        returncode: str = "unknown" if self._process is None else str(self._process.returncode)
        stderr: str = self._stderr_tail.decode("utf-8", errors="replace").strip()
        return f"Slotui {prefix} (returncode={returncode}; stderr={stderr[-_STDERR_LIMIT_BYTES:] or 'empty'})"

    async def _close_writer(self) -> None:
        """Close parent output and stop the sole router without a dangling read task."""
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError):
                await self._writer.wait_closed()
            self._writer = None
        if self._router_task is not None and not self._router_task.done():
            self._router_task.cancel()
        if self._router_task is not None:
            with contextlib.suppress(asyncio.CancelledError, SlotuiCoreHostError):
                await self._router_task
        self._router_task = None
        self._reader = None

    async def _stop_process(self, *, force: bool) -> None:
        """Reap the child, escalating only after failed or timed-out orderly closure.

        Args:
            force (bool): Whether protocol shutdown failed and termination is required.
        """
        if self._process is None:
            return
        process: asyncio.subprocess.Process = self._process
        if process.returncode is None and not force:
            try:
                await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                force = True
        if process.returncode is None and force:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._process = None

    async def _stop_server(self) -> None:
        """Close the Unix server and await its socket cleanup."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _await_stderr_task(self) -> None:
        """Await stderr drain after child reaping to avoid a pipe-reader leak."""
        if self._stderr_task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await self._stderr_task
        self._stderr_task = None

    def _remove_runtime_root(self) -> None:
        """Remove all temp venv/socket/script state after every startup outcome."""
        if self._runtime_root is not None:
            shutil.rmtree(self._runtime_root, ignore_errors=True)
            self._runtime_root = None


class InstalledSlotuiHostProcessFactory:
    """Build installed candidate process ports after static verification."""

    def build(self, *, receipt: SlotuiCoreVerificationReceiptDAO) -> SlotuiHostProcess:
        """Build one concrete host process.

        Args:
            receipt (SlotuiCoreVerificationReceiptDAO): Exact candidate verification receipt.

        Returns:
            SlotuiHostProcess: Fresh unstarted installed-wheel process port.
        """
        return InstalledSlotuiHostProcess(receipt=receipt)


async def _run_checked_command(*, command: tuple[str, ...], cwd: Path, timeout_seconds: float) -> None:
    """Run bounded venv/pip setup with no source or registry inheritance.

    Args:
        command (tuple[str, ...]): Explicit executable and arguments.
        cwd (Path): Isolated runtime directory.
        timeout_seconds (float): Maximum setup duration.

    Raises:
        SlotuiCoreHostError: If setup exits unsuccessfully or times out.
    """
    process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=_clean_child_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as error:
        process.kill()
        _, stderr = await process.communicate()
        raise SlotuiCoreHostError(
            f"Slotui isolated setup timed out: {stderr.decode('utf-8', errors='replace')[-_STDERR_LIMIT_BYTES:]}"
        ) from error
    if process.returncode != 0:
        message: str = stderr.decode("utf-8", errors="replace")[-_STDERR_LIMIT_BYTES:]
        raise SlotuiCoreHostError(f"Slotui isolated setup failed: {message}")


def _clean_child_environment() -> dict[str, str]:
    """Return a minimal allowlist required for the child executable and terminal.

    Returns:
        dict[str, str]: Child environment with pip configuration disabled.
    """
    allowed: tuple[str, ...] = ("HOME", "LANG", "LC_ALL", "TERM", "COLORTERM", "TZ")
    environment: dict[str, str] = {key: os.environ[key] for key in allowed if key in os.environ}
    protocol_test_prompt: str | None = os.environ.get("SLO_SLOTUI_PROTOCOL_TEST_PROMPT")
    if protocol_test_prompt is not None:
        environment["SLO_SLOTUI_PROTOCOL_TEST_PROMPT"] = protocol_test_prompt
    environment.update(
        {
            "PATH": os.defpath,
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _require_parent_isolation() -> None:
    """Reject inherited source paths that would invalidate installed-wheel isolation.

    Raises:
        SlotuiCoreHostError: If parent environment can inject Python source.
    """
    if os.environ.get("PYTHONPATH"):
        raise SlotuiCoreHostError("Slotui candidate runtime rejects PYTHONPATH to prevent source imports")


def _slo_source_root() -> Path:
    """Determine Slo source root from this installed source file, never process cwd.

    Returns:
        Path: Repository/source root containing ``src``.
    """
    return Path(__file__).resolve().parents[3]


def _is_within(*, path: Path, parent: Path) -> bool:
    """Determine whether a path is equal to or nested below another path.

    Args:
        path (Path): Candidate resolved path.
        parent (Path): Resolved hierarchy root.

    Returns:
        bool: Whether path lies under parent.
    """
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
