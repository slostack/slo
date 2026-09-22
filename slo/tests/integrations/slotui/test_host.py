"""Pure non-runtime tests for v2 Slotui control IPC, mapping, and parent policy."""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.integrations.slotui.host import (
    InstalledSlotuiHostProcess,
    SlotuiCoreHostError,
    SlotuiCoreHostService,
    SlotuiTerminalBridge,
    _clean_child_environment,
    _slo_source_root,
)
from src.integrations.slotui.dao import SlotuiCoreVerificationReceiptDAO
from src.integrations.slotui.host_protocol import (
    SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
    SlotuiHostCommandDAO,
    SlotuiHostEventDAO,
    SlotuiHostLaunchConfigDAO,
    SlotuiStreamEventMapper,
)


class _NonRuntimeFakeSession:
    """Deliberately non-candidate session fake with real-shaped normalized events."""

    def __init__(self, *, events: tuple[AgentStreamEventDAO, ...], error: Exception | None = None) -> None:
        """Store deterministic event/error behavior.

        Args:
            events (tuple[AgentStreamEventDAO, ...]): Events to yield for one accepted prompt.
            error (Exception | None): Error to raise after yielding. Defaults to ``None``.
        """
        self.session_id: str = "fake-session"
        self.prompts: list[str] = []
        self._events: tuple[AgentStreamEventDAO, ...] = events
        self._error: Exception | None = error

    async def invoke(self, *, text: str) -> AsyncIterator[AgentStreamEventDAO]:
        """Record and emit configured parent stream behavior.

        Args:
            text (str): Accepted editor text.

        Yields:
            AgentStreamEventDAO: Configured normalized event.

        Raises:
            Exception: Configured test exception.
        """
        self.prompts.append(text)
        for event in self._events:
            yield event
        if self._error is not None:
            raise self._error


class _NonRuntimeFakeHostProcess:
    """Clearly labelled fake control port; it never imports, installs, or emulates Slotui."""

    def __init__(self, *, events: tuple[SlotuiHostEventDAO, ...], settle_on_receive: bool = True) -> None:
        """Store lifecycle input and command observations.

        Args:
            events (tuple[SlotuiHostEventDAO, ...]): Candidate events to yield.
            settle_on_receive (bool): Yield between inputs so prompt task runs. Defaults to ``True``.
        """
        self._events: tuple[SlotuiHostEventDAO, ...] = events
        self._settle_on_receive: bool = settle_on_receive
        self.started_config: SlotuiHostLaunchConfigDAO | None = None
        self.commands: list[SlotuiHostCommandDAO] = []
        self.acknowledged_mutation_ids: list[str] = []
        self.closed: bool = False

    async def start(self, *, config: SlotuiHostLaunchConfigDAO) -> None:
        """Record launch configuration supplied by parent service.

        Args:
            config (SlotuiHostLaunchConfigDAO): Parent launch facts.
        """
        self.started_config = config

    async def receive(self) -> AsyncIterator[SlotuiHostEventDAO]:
        """Yield deterministic host events with a scheduling boundary.

        Yields:
            SlotuiHostEventDAO: Configured candidate lifecycle/editor event.
        """
        for event in self._events:
            yield event
            if self._settle_on_receive:
                await __import__("asyncio").sleep(0)

    async def require_transcript_ack(self, *, mutation_id: str) -> None:
        """Accept a fake-port acknowledgement without representing candidate runtime evidence.

        Args:
            mutation_id (str): Parent mutation key intentionally not emulated by this fake.
        """
        self.acknowledged_mutation_ids.append(mutation_id)

    async def send(self, *, command: SlotuiHostCommandDAO) -> None:
        """Record parent control command.

        Args:
            command (SlotuiHostCommandDAO): Parent command.
        """
        self.commands.append(command)

    async def aclose(self) -> None:
        """Record cleanup after every terminal lifecycle path."""
        self.closed = True


@pytest.mark.parametrize("event_kind", StreamEventKind.__args__)
def test_mapper_maps_every_actual_stream_kind_with_identity_and_explicit_operation(event_kind: str) -> None:
    """Map the complete canonical event enum without accidental generic drop behavior."""
    event = AgentStreamEventDAO(
        kind=event_kind,
        iteration=7,
        block_id="block",
        content_index=3,
        delta="delta",
        content="content",
        tool_name="bash",
        tool_call_id="call",
        tool_input={"command": "pwd"},
        tool_arguments_delta='{"command":',
        redacted=True,
        metadata={"origin": "test"},
        sub_agent_id="child",
        task_id="task",
    )

    mutation = SlotuiStreamEventMapper.invoke(event=event)

    assert mutation.block_id == "block"
    assert mutation.iteration == 7
    assert mutation.content_index == 3
    assert mutation.tool_name == "bash"
    assert mutation.tool_call_id == "call"
    assert mutation.metadata["stream_kind"] == event_kind
    assert mutation.metadata["event_metadata"] == {"origin": "test"}
    assert mutation.kind in {"create", "append", "update", "end", "notice", "failed"}


def test_mapper_when_parent_text_ends_uses_nonterminal_notice() -> None:
    """Keep a closed assistant text block distinct from the canonical run terminal."""
    mutation = SlotuiStreamEventMapper.invoke(event=AgentStreamEventDAO(kind="text_end"))

    assert mutation.kind == "notice"
    assert mutation.text == "text end"


def test_mapper_when_parent_run_completes_uses_terminal_end() -> None:
    """Map successful canonical completion to the candidate terminal mutation."""
    mutation = SlotuiStreamEventMapper.invoke(event=AgentStreamEventDAO(kind="run_completed"))

    assert mutation.kind == "end"
    assert mutation.text == "run completed"


@pytest.mark.parametrize("event_kind", ("run_aborted", "run_failed"))
def test_mapper_when_parent_run_fails_uses_terminal_failure(event_kind: StreamEventKind) -> None:
    """Retain explicit terminal failure mutations for unsuccessful canonical runs."""
    mutation = SlotuiStreamEventMapper.invoke(event=AgentStreamEventDAO(kind=event_kind))

    assert mutation.kind == "failed"
    assert mutation.text == event_kind.replace("_", " ")


async def test_host_lifecycle_forwards_one_submission_to_actual_session_and_closes_cleanly(
    tmp_path: Path,
) -> None:
    """Relay a real deterministic SloAgentSession through the non-runtime control port."""
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="actual")])),
        workdir=tmp_path,
        session_id="slotui-real-session",
    )
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="editor_submit", prompt="repair"
            ),
            SlotuiHostEventDAO(protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"),
        )
    )
    service = SlotuiCoreHostService(
        session=session,  # type: ignore[arg-type]  # Intentional protocol-only fake.
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id="resumed-session",
    )

    await service.invoke()

    assert process.started_config is not None
    assert process.started_config.protocol_version == SLOTUI_HOST_CONTROL_PROTOCOL_VERSION
    assert any(
        command.kind == "stream_event" and command.mutation.text == "actual" for command in process.commands
    )
    assert [command.kind for command in process.commands[:3]] == [
        "session_notice",
        "session_notice",
        "session_notice",
    ]
    assert all(command.kind == "stream_event" for command in process.commands[3:])
    assert process.closed is True


async def test_host_lifecycle_when_text_end_precedes_terminal_run_forwards_and_acknowledges_both() -> None:
    """Keep forwarding after a text block closes until the parent emits its run terminal event."""
    session = _NonRuntimeFakeSession(
        events=(
            AgentStreamEventDAO(kind="text_end", content="answer"),
            AgentStreamEventDAO(kind="run_completed"),
        )
    )
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="editor_submit",
                prompt="complete the run",
            ),
            SlotuiHostEventDAO(protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"),
        )
    )
    service = SlotuiCoreHostService(
        session=session,  # type: ignore[arg-type]  # Intentional protocol-only fake.
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id=None,
    )

    await asyncio.wait_for(service.invoke(), timeout=1.0)

    stream_commands: list[SlotuiHostCommandDAO] = [
        command for command in process.commands if command.kind == "stream_event"
    ]
    assert [command.mutation.metadata["stream_kind"] for command in stream_commands] == [
        "text_end",
        "run_completed",
    ]
    assert [command.mutation.kind for command in stream_commands] == ["notice", "end"]
    assert [command.mutation_id for command in stream_commands] == [
        "slotui-mutation-1",
        "slotui-mutation-2",
    ]
    assert process.acknowledged_mutation_ids == ["slotui-mutation-1", "slotui-mutation-2"]
    assert process.closed is True


@pytest.mark.parametrize("terminal_kind", ("run_aborted", "run_failed"))
async def test_host_lifecycle_when_text_end_precedes_unsuccessful_terminal_forwards_and_acknowledges_terminal(
    terminal_kind: StreamEventKind,
) -> None:
    """Forward and acknowledge every canonical terminal outcome after a text block closes."""
    session = _NonRuntimeFakeSession(
        events=(
            AgentStreamEventDAO(kind="text_end", content="partial answer"),
            AgentStreamEventDAO(kind=terminal_kind),
        )
    )
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="editor_submit",
                prompt="end unsuccessfully",
            ),
            SlotuiHostEventDAO(protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"),
        )
    )
    service = SlotuiCoreHostService(
        session=session,  # type: ignore[arg-type]  # Intentional protocol-only fake.
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id=None,
    )

    await asyncio.wait_for(service.invoke(), timeout=1.0)

    stream_commands: list[SlotuiHostCommandDAO] = [
        command for command in process.commands if command.kind == "stream_event"
    ]
    assert [command.mutation.metadata["stream_kind"] for command in stream_commands] == [
        "text_end",
        terminal_kind,
    ]
    assert [command.mutation.kind for command in stream_commands] == ["notice", "failed"]
    assert process.acknowledged_mutation_ids == ["slotui-mutation-1", "slotui-mutation-2"]


async def test_host_lifecycle_when_rapid_submissions_rejects_second_without_background_exception() -> None:
    """Apply explicit reject-while-busy policy rather than queueing or racing session calls."""
    session = _NonRuntimeFakeSession(events=(AgentStreamEventDAO(kind="text_delta", delta="one"),))
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="editor_submit", prompt="one"
            ),
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="editor_submit", prompt="two"
            ),
            SlotuiHostEventDAO(protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"),
        ),
        settle_on_receive=False,
    )
    service = SlotuiCoreHostService(
        session=session,  # type: ignore[arg-type]
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id=None,
    )

    await service.invoke()

    assert session.prompts == ["one"]
    assert any(command.notice and "rejected" in command.notice for command in process.commands)


async def test_host_lifecycle_when_session_raises_maps_failure_to_transcript_and_closes() -> None:
    """Contain prompt task errors as explicit failure commands, never unobserved task errors."""
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="editor_submit", prompt="fail"
            ),
            SlotuiHostEventDAO(protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"),
        )
    )
    service = SlotuiCoreHostService(
        session=_NonRuntimeFakeSession(events=(), error=RuntimeError("provider down")),  # type: ignore[arg-type]
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id=None,
    )

    await service.invoke()

    assert any(
        command.kind == "session_failed" and command.notice and "provider down" in command.notice
        for command in process.commands
    )
    assert process.closed is True


async def test_installed_host_process_when_child_exits_before_socket_connect_reports_return_code_and_stderr(
    tmp_path: Path,
) -> None:
    """Include child diagnostics in early readiness failure instead of waiting blindly for the socket."""
    process = InstalledSlotuiHostProcess(
        receipt=cast(SlotuiCoreVerificationReceiptDAO, SimpleNamespace(manifest=SimpleNamespace()))
    )
    child = MagicMock()
    child.returncode = 17
    process._process = child
    process._stderr_tail.extend(b"candidate import exploded")

    with pytest.raises(SlotuiCoreHostError, match=r"returncode=17; stderr=candidate import exploded"):
        await process._await_control_connection()


async def test_installed_host_process_spawns_verified_runner_module_with_exact_host_flags(
    tmp_path: Path,
) -> None:
    """Invoke only the manifested module bridge with the exact static-contract CLI arguments."""
    receipt = SimpleNamespace(
        manifest=SimpleNamespace(
            candidate_adapter=SimpleNamespace(module="slotui.slo_adapter", symbol="launch_tui_app"),
            candidate_runner=SimpleNamespace(module="slotui._slo_candidate_adapter_runner"),
        )
    )
    process = InstalledSlotuiHostProcess(receipt=cast(SlotuiCoreVerificationReceiptDAO, receipt))
    process._runtime_root = tmp_path
    subprocess: MagicMock = MagicMock()
    with patch(
        "src.integrations.slotui.host.asyncio.create_subprocess_exec", new_callable=AsyncMock
    ) as spawn:
        spawn.return_value = subprocess
        with (
            patch.object(process, "_drain_stderr", new_callable=AsyncMock),
            patch("src.integrations.slotui.host._inspect_child_terminal_fds"),
        ):
            await process._spawn_candidate(
                interpreter_path=Path("/isolated/venv/bin/python"),
                socket_path=Path("/isolated/control.sock"),
            )

    positional_arguments, keyword_arguments = spawn.await_args
    assert positional_arguments == (
        "/isolated/venv/bin/python",
        "-I",
        "-m",
        "slotui._slo_candidate_adapter_runner",
        "--control-socket",
        "/isolated/control.sock",
        "--adapter-module",
        "slotui.slo_adapter",
        "--adapter-symbol",
        "launch_tui_app",
        "--protocol-version",
        SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
    )
    assert keyword_arguments["cwd"] == str(tmp_path)
    assert keyword_arguments["env"] == _clean_child_environment()
    assert keyword_arguments["stdin"] == keyword_arguments["stdout"]
    assert isinstance(keyword_arguments["stdin"], int)
    assert keyword_arguments["stderr"] == asyncio.subprocess.PIPE
    assert process._terminal_master_fd is not None
    assert process._terminal_slave_fd is None
    process._close_terminal_pty()


async def test_installed_host_process_writes_hash_locked_offline_resolver_input(tmp_path: Path) -> None:
    """Allow pip to resolve only direct URLs from the exact verified receipt closure."""
    core_wheel: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    dependency_wheel: Path = tmp_path / "runtime_dependency-0.1.0-py3-none-any.whl"
    core_wheel.write_bytes(b"verified core bytes")
    dependency_wheel.write_bytes(b"verified dependency bytes")
    process = InstalledSlotuiHostProcess(
        receipt=cast(
            SlotuiCoreVerificationReceiptDAO,
            SimpleNamespace(verified_wheel_paths=(core_wheel, dependency_wheel)),
        )
    )

    requirements_path: Path = process._write_verified_requirements(runtime_root=tmp_path)

    lines: list[str] = requirements_path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        f"{core_wheel.as_uri()} --hash=sha256:{__import__('hashlib').sha256(core_wheel.read_bytes()).hexdigest()}",
        (
            f"{dependency_wheel.as_uri()} "
            f"--hash=sha256:{__import__('hashlib').sha256(dependency_wheel.read_bytes()).hexdigest()}"
        ),
    ]


async def test_installed_host_process_when_resolver_reports_incomplete_dependency_fails_closed(
    tmp_path: Path,
) -> None:
    """Reject pip's offline failure rather than continuing with an incomplete installed closure."""
    core_wheel: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    core_wheel.write_bytes(b"verified core bytes")
    process = InstalledSlotuiHostProcess(
        receipt=cast(
            SlotuiCoreVerificationReceiptDAO,
            SimpleNamespace(verified_wheel_paths=(core_wheel,)),
        )
    )
    interpreter_path: Path = tmp_path / "venv" / "bin" / "python"
    interpreter_path.parent.mkdir(parents=True)
    interpreter_path.touch()
    with (
        patch("src.integrations.slotui.host._run_checked_command", new_callable=AsyncMock) as run_checked,
        patch.object(process, "_write_verified_requirements", return_value=tmp_path / "requirements.txt"),
    ):
        run_checked.side_effect = (
            None,
            SlotuiCoreHostError("Slotui isolated setup failed: unresolved dependency"),
        )

        with pytest.raises(SlotuiCoreHostError, match="unresolved dependency"):
            await process._create_and_install(runtime_root=tmp_path)

    assert run_checked.await_count == 2
    resolver_command: tuple[str, ...] = run_checked.await_args_list[1].kwargs["command"]
    assert "--require-hashes" in resolver_command
    assert "--no-deps" not in resolver_command


async def test_terminal_bridge_when_real_terminal_is_available_forwards_input_output_resizes_and_restores_once() -> (
    None
):
    """Bridge a real invoking PTY to a retained child PTY without using JSON IPC.

    The test proves the parent terminal is raw only during the bridge, terminal
    bytes flow in both directions, a resize reaches the child PTY, and duplicate
    close requests restore the exact original attributes once.
    """
    host_master_fd, host_slave_fd = pty.openpty()
    child_master_fd, child_slave_fd = pty.openpty()
    original_host_attributes = termios.tcgetattr(host_slave_fd)
    child_attributes = termios.tcgetattr(child_slave_fd)
    child_attributes[3] &= ~(termios.ICANON | termios.ECHO)
    termios.tcsetattr(child_slave_fd, termios.TCSANOW, child_attributes)
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=host_slave_fd,
        host_stdout_fd=host_slave_fd,
        process_group_id=os.getpgrp(),
    )
    original_signal = signal.signal(signal.SIGWINCH, signal.SIG_IGN)
    try:
        await bridge.start()
        assert termios.tcgetattr(host_slave_fd) != original_host_attributes
        await asyncio.sleep(0)

        os.write(host_master_fd, b"host input")
        await _wait_for_terminal_bytes(fd=child_slave_fd, expected=b"host input")
        os.write(child_slave_fd, b"candidate output")
        await _wait_for_terminal_bytes(fd=host_master_fd, expected=b"candidate output")

        fcntl.ioctl(host_master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 31, 117, 0, 0))
        os.kill(os.getpid(), signal.SIGWINCH)
        await asyncio.sleep(0.01)
        child_rows, child_columns, _, _ = struct.unpack(
            "HHHH", fcntl.ioctl(child_master_fd, termios.TIOCGWINSZ, bytes(8))
        )
        assert (child_rows, child_columns) == (31, 117)

        await bridge.aclose()
        await bridge.aclose()
        assert termios.tcgetattr(host_slave_fd) == original_host_attributes
        assert signal.getsignal(signal.SIGWINCH) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGWINCH, original_signal)
        for file_descriptor in (host_master_fd, host_slave_fd, child_master_fd, child_slave_fd):
            os.close(file_descriptor)


@pytest.mark.parametrize("signal_number", (signal.SIGINT, signal.SIGTERM))
async def test_terminal_bridge_when_interrupt_signal_requests_full_host_close_and_restores_terminal(
    signal_number: int,
) -> None:
    """Delegate each terminal interrupt to the owning installed-host close/reap callback."""
    host_master_fd, host_slave_fd = pty.openpty()
    child_master_fd, child_slave_fd = pty.openpty()
    original_host_attributes = termios.tcgetattr(host_slave_fd)
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=host_slave_fd,
        host_stdout_fd=host_slave_fd,
        process_group_id=os.getpgrp(),
    )
    close_requested = asyncio.Event()
    original_signal = signal.signal(signal_number, signal.SIG_IGN)
    try:
        bridge.bind_close_callback(close_callback=close_requested.set)
        await bridge.start()
        os.kill(os.getpid(), signal_number)
        await asyncio.wait_for(close_requested.wait(), timeout=1.0)
        await bridge.aclose()
        assert termios.tcgetattr(host_slave_fd) == original_host_attributes
        assert signal.getsignal(signal_number) == signal.SIG_IGN
    finally:
        signal.signal(signal_number, original_signal)
        for file_descriptor in (host_master_fd, host_slave_fd, child_master_fd, child_slave_fd):
            os.close(file_descriptor)


async def test_terminal_bridge_when_child_pty_eof_requests_full_host_close_and_restores_terminal() -> None:
    """Treat child PTY EOF as a host lifecycle failure, not a detached task exit."""
    host_master_fd, host_slave_fd = pty.openpty()
    child_master_fd, child_slave_fd = pty.openpty()
    original_host_attributes = termios.tcgetattr(host_slave_fd)
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=host_slave_fd,
        host_stdout_fd=host_slave_fd,
        process_group_id=os.getpgrp(),
    )
    close_requested = asyncio.Event()
    try:
        bridge.bind_close_callback(close_callback=close_requested.set)
        await bridge.start()
        os.close(child_slave_fd)
        await asyncio.wait_for(close_requested.wait(), timeout=1.0)
        await bridge.aclose()
        assert termios.tcgetattr(host_slave_fd) == original_host_attributes
    finally:
        for file_descriptor in (host_master_fd, host_slave_fd, child_master_fd):
            with __import__("contextlib").suppress(OSError):
                os.close(file_descriptor)


async def test_terminal_bridge_when_start_is_cancelled_restores_all_flags_and_termios() -> None:
    """Roll back raw mode and nonblocking changes when startup is cancelled mid-transaction."""
    host_master_fd, host_slave_fd = pty.openpty()
    child_master_fd, child_slave_fd = pty.openpty()
    original_host_attributes = termios.tcgetattr(host_slave_fd)
    original_host_input_flags = fcntl.fcntl(host_slave_fd, fcntl.F_GETFL)
    original_child_flags = fcntl.fcntl(child_master_fd, fcntl.F_GETFL)
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=host_slave_fd,
        host_stdout_fd=host_slave_fd,
        process_group_id=os.getpgrp(),
    )
    try:
        with patch.object(bridge, "_copy_host_terminal_size_to_child", side_effect=asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await bridge.start()
        assert termios.tcgetattr(host_slave_fd) == original_host_attributes
        assert fcntl.fcntl(host_slave_fd, fcntl.F_GETFL) == original_host_input_flags
        assert fcntl.fcntl(child_master_fd, fcntl.F_GETFL) == original_child_flags
    finally:
        for file_descriptor in (host_master_fd, host_slave_fd, child_master_fd, child_slave_fd):
            os.close(file_descriptor)


async def test_terminal_bridge_when_input_queue_is_full_requests_full_close_without_dropping_owned_tasks() -> (
    None
):
    """Bound queued host input instead of overwriting detached write tasks."""
    child_master_fd, child_slave_fd = pty.openpty()
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=-1,
        host_stdout_fd=-1,
        process_group_id=os.getpgrp(),
    )
    close_requested = asyncio.Event()
    try:
        bridge.bind_close_callback(close_callback=close_requested.set)
        for _ in range(bridge._input_queue.maxsize):
            bridge._enqueue_input_chunk(data=b"x")
        bridge._enqueue_input_chunk(data=b"overflow")
        await asyncio.wait_for(close_requested.wait(), timeout=1.0)
        assert bridge._input_queue.qsize() == bridge._input_queue.maxsize
    finally:
        await bridge.aclose()
        os.close(child_master_fd)
        os.close(child_slave_fd)


async def test_terminal_bridge_when_invoking_streams_are_not_ttys_leaves_them_unmodified() -> None:
    """Retain the private child PTY without taking over captured test stdio."""
    child_master_fd, child_slave_fd = pty.openpty()
    bridge = SlotuiTerminalBridge(
        child_terminal_fd=child_master_fd,
        host_stdin_fd=-1,
        host_stdout_fd=-1,
        process_group_id=os.getpgrp(),
    )
    try:
        await bridge.start()
        assert bridge._host_terminal_active is False
        assert bridge._child_read_task is None
        assert bridge._input_pump_task is None
    finally:
        await bridge.aclose()
        os.close(child_master_fd)
        os.close(child_slave_fd)


async def test_installed_host_process_when_closed_terminates_the_candidate_process_group(
    tmp_path: Path,
) -> None:
    """Escalate a failed candidate shutdown to the isolated child process group."""
    process = InstalledSlotuiHostProcess(
        receipt=cast(SlotuiCoreVerificationReceiptDAO, SimpleNamespace(manifest=SimpleNamespace()))
    )
    child = MagicMock()
    child.pid = 4321
    child.returncode = None
    child.wait = AsyncMock(return_value=None)
    process._process = child

    with patch("src.integrations.slotui.host.os.killpg") as kill_process_group:
        await process._stop_process(force=True)

    kill_process_group.assert_called_once_with(4321, signal.SIGTERM)
    assert process._process is None


async def test_installed_host_process_when_bridge_requests_close_reaps_every_owned_resource() -> None:
    """Route bridge EOF/signals through the installed process's full idempotent close sequence."""
    process = InstalledSlotuiHostProcess(
        receipt=cast(SlotuiCoreVerificationReceiptDAO, SimpleNamespace(manifest=SimpleNamespace()))
    )
    request_orderly_shutdown = AsyncMock(return_value=False)
    close_terminal_bridge = AsyncMock()
    close_writer = AsyncMock()
    stop_process = AsyncMock()
    stop_server = AsyncMock()
    await_stderr_task = AsyncMock()
    close_terminal_pty = MagicMock()
    remove_runtime_root = MagicMock()

    with (
        patch.object(process, "_request_orderly_shutdown", request_orderly_shutdown),
        patch.object(process, "_close_terminal_bridge", close_terminal_bridge),
        patch.object(process, "_close_writer", close_writer),
        patch.object(process, "_stop_process", stop_process),
        patch.object(process, "_stop_server", stop_server),
        patch.object(process, "_await_stderr_task", await_stderr_task),
        patch.object(process, "_close_terminal_pty", close_terminal_pty),
        patch.object(process, "_remove_runtime_root", remove_runtime_root),
    ):
        process._schedule_close()
        assert process._close_task is not None
        await process._close_task

    close_terminal_bridge.assert_awaited()
    close_writer.assert_awaited()
    stop_process.assert_awaited_with(force=True)
    stop_server.assert_awaited()
    await_stderr_task.assert_awaited()
    close_terminal_pty.assert_called_once()
    remove_runtime_root.assert_called_once()
    assert process._closed is True


async def _wait_for_terminal_bytes(*, fd: int, expected: bytes) -> bytes:
    """Read a PTY endpoint until it contains an expected bridged partial payload.

    Args:
        fd (int): PTY master or slave endpoint expected to receive terminal bytes.
        expected (bytes): Exact byte sequence that proves the bridge direction.

    Returns:
        bytes: All bytes read through the expected payload.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    original_flags: int = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
    received: bytearray = bytearray()
    deadline: float = loop.time() + 1.0
    try:
        while expected not in received:
            if loop.time() >= deadline:
                raise AssertionError(f"missing {expected!r} from terminal payload {bytes(received)!r}")
            try:
                received.extend(os.read(fd, 65_536))
            except BlockingIOError:
                await asyncio.sleep(0.01)
        return bytes(received)
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, original_flags)


def test_installed_host_environment_disables_pip_config_and_source_inheritance() -> None:
    """Pin the isolated-child configuration without treating a fake as candidate evidence."""
    environment = _clean_child_environment()

    assert environment["PIP_CONFIG_FILE"] == "/dev/null"
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONPATH" not in environment
    assert _slo_source_root().name == "slo"


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            {"kind": "launch", "protocol_version": SLOTUI_HOST_CONTROL_PROTOCOL_VERSION},
            "invalid for launch",
        ),
        (
            {
                "kind": "stream_event",
                "protocol_version": SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                "notice": "not a mutation",
            },
            "invalid for stream_event",
        ),
    ],
)
def test_host_command_when_kind_payloads_are_mixed_rejects(payload: dict[str, object], match: str) -> None:
    """Reject command payloads that could cross launch and stream protocol boundaries."""
    with pytest.raises(ValueError, match=match):
        SlotuiHostCommandDAO.model_validate(payload)


async def test_slo_owned_socket_transport_serializes_null_optional_protocol_fields_for_candidate_contract(
    tmp_path: Path,
) -> None:
    """Preserve explicit nulls required by the candidate's closed launch and mutation shapes."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="launch",
                launch=SlotuiHostLaunchConfigDAO(
                    protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                    workdir="/tmp",
                    resume_session_id=None,
                    session_id="session",
                    control_socket_path="/tmp/control.sock",
                    adapter_declaration="slotui.adapter.launch",
                ),
            )
        )
        launch_command: SlotuiHostCommandDAO = await peer.receive_command()
        assert launch_command.launch is not None
        assert launch_command.launch.resume_session_id is None
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(event=AgentStreamEventDAO(kind="run_completed")),
                mutation_id="terminal",
            )
        )
        stream_command: SlotuiHostCommandDAO = await peer.receive_command()
        assert stream_command.mutation is not None
        assert stream_command.mutation.block_id is None
        assert stream_command.mutation.tool_name is None
        assert stream_command.mutation.tool_call_id is None
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


def test_host_event_when_editor_submit_carries_lifecycle_field_rejects() -> None:
    """Reject a candidate editor event that smuggles a lifecycle readiness field."""
    with pytest.raises(ValueError, match="invalid for editor_submit"):
        SlotuiHostEventDAO(
            protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
            kind="editor_submit",
            prompt="submit",
            terminal_ready=True,
        )


async def test_host_lifecycle_when_candidate_fails_reaps_process_without_textual_fallback() -> None:
    """Fail closed when candidate reports failure."""
    process = _NonRuntimeFakeHostProcess(
        events=(
            SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="host_failed",
                detail="terminal crashed",
            ),
        )
    )
    service = SlotuiCoreHostService(
        session=_NonRuntimeFakeSession(events=()),  # type: ignore[arg-type]
        process=process,
        workdir=Path("/tmp/workdir"),
        resume_session_id=None,
    )

    with pytest.raises(SlotuiCoreHostError, match="terminal crashed"):
        await service.invoke()

    assert process.closed is True


class _SloOwnedSocketPeer:
    """Tiny local Unix peer that tests Slo's transport only, never a Slotui runtime."""

    def __init__(self, *, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Store a local test-only socket endpoint.

        Args:
            reader (asyncio.StreamReader): Parent-to-peer JSONL reader.
            writer (asyncio.StreamWriter): Peer-to-parent JSONL writer.
        """
        self.reader: asyncio.StreamReader = reader
        self.writer: asyncio.StreamWriter = writer

    async def send_event(self, *, event: SlotuiHostEventDAO) -> None:
        """Send one typed candidate-shaped event to Slo's socket router.

        Args:
            event (SlotuiHostEventDAO): Validated Slo-owned transport fixture frame.
        """
        self.writer.write((event.model_dump_json() + "\n").encode("utf-8"))
        await self.writer.drain()

    async def receive_command(self) -> SlotuiHostCommandDAO:
        """Read one parent command from the local transport peer.

        Returns:
            SlotuiHostCommandDAO: Validated command emitted by Slo.
        """
        line: bytes = await self.reader.readline()
        assert line
        payload: dict[str, object] = __import__("json").loads(line)
        return SlotuiHostCommandDAO.model_validate(payload)

    async def aclose(self) -> None:
        """Close the local test peer socket."""
        self.writer.close()
        await self.writer.wait_closed()


async def _build_slo_owned_socket_transport(
    tmp_path: Path,
) -> tuple[InstalledSlotuiHostProcess, _SloOwnedSocketPeer, asyncio.AbstractServer]:
    """Connect a local Slo-owned socket peer to an installed-host transport instance.

    This is concrete Unix-socket transport coverage. It deliberately bypasses
    wheel setup, candidate imports, and candidate TUI behavior.

    Args:
        tmp_path (Path): Isolated test socket directory.

    Returns:
        tuple[InstalledSlotuiHostProcess, _SloOwnedSocketPeer, asyncio.AbstractServer]:
            Connected parent transport, local peer, and its server owner.
    """
    connected: asyncio.Future[_SloOwnedSocketPeer] = asyncio.get_running_loop().create_future()

    async def accept_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Capture the single Slo-owned local test peer connection."""
        connected.set_result(_SloOwnedSocketPeer(reader=reader, writer=writer))

    socket_path: Path = tmp_path / "slo-owned-transport.sock"
    server: asyncio.AbstractServer = await asyncio.start_unix_server(accept_peer, path=str(socket_path))
    receipt = SimpleNamespace(
        manifest=SimpleNamespace(candidate_adapter=SimpleNamespace(declaration="slotui.adapter.launch"))
    )
    process = InstalledSlotuiHostProcess(
        receipt=cast(SlotuiCoreVerificationReceiptDAO, receipt), readiness_timeout_seconds=0.1
    )
    parent_reader, parent_writer = await asyncio.open_unix_connection(path=str(socket_path))
    await process._on_control_connection(reader=parent_reader, writer=parent_writer)
    peer: _SloOwnedSocketPeer = await connected
    return process, peer, server


async def _close_slo_owned_socket_transport(
    *, process: InstalledSlotuiHostProcess, peer: _SloOwnedSocketPeer, server: asyncio.AbstractServer
) -> None:
    """Close a concrete local transport fixture without process/wheel behavior.

    Args:
        process (InstalledSlotuiHostProcess): Parent transport under test.
        peer (_SloOwnedSocketPeer): Local Slo-owned socket peer.
        server (asyncio.AbstractServer): Unix socket server owner.
    """
    await peer.aclose()
    await process.aclose()
    server.close()
    await server.wait_closed()


async def test_slo_owned_socket_transport_routes_interleaved_editor_and_exact_acknowledgements(
    tmp_path: Path,
) -> None:
    """Route an editor submit while an exact stream acknowledgement resolves its own waiter."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(
                    event=AgentStreamEventDAO(kind="text_delta", delta="x")
                ),
                mutation_id="one",
            )
        )
        await peer.receive_command()
        acknowledgement: asyncio.Task[None] = asyncio.create_task(
            process.require_transcript_ack(mutation_id="one")
        )
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="editor_submit",
                prompt="interleaved editor input",
            )
        )
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="transcript_ack",
                mutation_id="one",
            )
        )

        assert (await process.receive().__anext__()).prompt == "interleaved editor input"
        await acknowledgement
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_acknowledgement_arrives_before_waiter_is_registered(
    tmp_path: Path,
) -> None:
    """Consume an already-routed exact acknowledgement without leaving stale protocol state."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(event=AgentStreamEventDAO(kind="run_completed")),
                mutation_id="terminal",
            )
        )
        await peer.receive_command()
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="transcript_ack",
                mutation_id="terminal",
            )
        )
        await asyncio.sleep(0)

        await process.require_transcript_ack(mutation_id="terminal")

        assert process._sent_mutation_ids == set()
        assert process._acknowledged_mutation_ids == set()
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_acknowledgement_is_mismatched_fans_out_failure(
    tmp_path: Path,
) -> None:
    """Fail pending acknowledgement and receive consumers after an unknown mutation acknowledgement."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(
                    event=AgentStreamEventDAO(kind="text_delta", delta="x")
                ),
                mutation_id="expected",
            )
        )
        await peer.receive_command()
        acknowledgement: asyncio.Task[None] = asyncio.create_task(
            process.require_transcript_ack(mutation_id="expected")
        )
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="transcript_ack",
                mutation_id="wrong",
            )
        )

        with pytest.raises(SlotuiCoreHostError, match="unknown transcript mutation"):
            await acknowledgement
        with pytest.raises(SlotuiCoreHostError, match="unknown transcript mutation"):
            await process.receive().__anext__()
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_no_outstanding_acknowledgement_is_requested_fails_closed(
    tmp_path: Path,
) -> None:
    """Reject an acknowledgement wait for a mutation that Slo never emitted."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        with pytest.raises(SlotuiCoreHostError, match="unsent mutation"):
            await process.require_transcript_ack(mutation_id="missing")
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_acknowledgement_times_out_fails_router_and_tears_down(
    tmp_path: Path,
) -> None:
    """Turn an unacknowledged mutation into one terminal router failure, never a hang."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(
                    event=AgentStreamEventDAO(kind="text_delta", delta="x")
                ),
                mutation_id="timeout",
            )
        )
        await peer.receive_command()

        with pytest.raises(SlotuiCoreHostError, match="timeout"):
            await process.require_transcript_ack(mutation_id="timeout")
        with pytest.raises(SlotuiCoreHostError, match="timeout"):
            await process.receive().__anext__()
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_blocked_receive_gets_peer_host_closed_once(
    tmp_path: Path,
) -> None:
    """Wake a blocked receive with the peer's one orderly close event, not a timeout."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        waiting_for_close: asyncio.Task[SlotuiHostEventDAO] = asyncio.create_task(
            process.receive().__anext__()
        )
        await asyncio.sleep(0)
        assert waiting_for_close.done() is False

        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="host_closed",
            )
        )

        closed_event: SlotuiHostEventDAO = await asyncio.wait_for(waiting_for_close, timeout=1.0)
        assert closed_event.kind == "host_closed"
        assert process._event_queue.empty()
        assert process._router_task is not None and process._router_task.done()
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_active_candidate_is_idle_waits_for_editor_input(
    tmp_path: Path,
) -> None:
    """Keep the live interactive socket open beyond the bounded startup deadline."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await asyncio.sleep(process._readiness_timeout_seconds * 2)
        waiting_for_editor: asyncio.Task[SlotuiHostEventDAO] = asyncio.create_task(
            process.receive().__anext__()
        )
        await asyncio.sleep(0)
        assert waiting_for_editor.done() is False
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="editor_submit",
                prompt="after idle interval",
            )
        )

        assert (await asyncio.wait_for(waiting_for_editor, timeout=1.0)).prompt == "after idle interval"
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_invalid_event_fans_out_ack_failure(tmp_path: Path) -> None:
    """Fan invalid-control diagnostics to a pending exact acknowledgement waiter."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(
                    event=AgentStreamEventDAO(kind="text_delta", delta="x")
                ),
                mutation_id="one",
            )
        )
        await peer.receive_command()
        acknowledgement: asyncio.Task[None] = asyncio.create_task(
            process.require_transcript_ack(mutation_id="one")
        )
        peer.writer.write(b'{"kind":"invalid"}\n')
        await peer.writer.drain()

        with pytest.raises(SlotuiCoreHostError, match="invalid control JSON"):
            await acknowledgement
        with pytest.raises(SlotuiCoreHostError, match="invalid control JSON"):
            await process.receive().__anext__()
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_when_peer_eof_fans_out_ack_failure(tmp_path: Path) -> None:
    """Fan bounded EOF diagnostics to a pending exact acknowledgement waiter."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    try:
        await process.send(
            command=SlotuiHostCommandDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="stream_event",
                mutation=SlotuiStreamEventMapper.invoke(
                    event=AgentStreamEventDAO(kind="text_delta", delta="x")
                ),
                mutation_id="one",
            )
        )
        await peer.receive_command()
        acknowledgement: asyncio.Task[None] = asyncio.create_task(
            process.require_transcript_ack(mutation_id="one")
        )
        await peer.aclose()

        with pytest.raises(SlotuiCoreHostError, match="control channel closed"):
            await acknowledgement
        with pytest.raises(SlotuiCoreHostError, match="control channel closed"):
            await process.receive().__anext__()
    finally:
        await process.aclose()
        server.close()
        await server.wait_closed()


async def test_installed_host_process_when_connected_candidate_is_silent_during_handshake_times_out_and_cleans_up(
    tmp_path: Path,
) -> None:
    """Apply one startup deadline to a connected peer that never acknowledges launch readiness."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    process._start_startup_deadline()
    try:
        with pytest.raises(SlotuiCoreHostError, match="startup handshake timed out"):
            await process._next_startup_event()
        assert process._router_failure is None
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)

    assert process._closed is True
    assert process._reader is None
    assert process._writer is None


async def test_slo_owned_socket_transport_buffers_editor_frame_during_ordered_startup(tmp_path: Path) -> None:
    """Preserve an early editor frame while startup consumes launch, attestation, and active in order."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    declaration: str = "slotui.adapter.launch"
    process._start_startup_deadline()
    try:
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="editor_submit",
                prompt="early editor input",
            )
        )
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="launch_ack",
                adapter_declaration=declaration,
            )
        )
        await process._send_launch(
            config=SlotuiHostLaunchConfigDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                workdir="/tmp",
                resume_session_id=None,
                session_id="session",
                control_socket_path="ignored",
                adapter_declaration="ignored",
            ),
            socket_path=tmp_path / "control.sock",
        )
        await peer.receive_command()
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="attestation",
                adapter_declaration=declaration,
                imported_module_path="/tmp/venv/site-packages/slotui/adapter.py",
                source_paths_absent=True,
            )
        )
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION,
                kind="host_active",
                adapter_declaration=declaration,
                terminal_ready=True,
                root_ready=True,
                editor_ready=True,
                transcript_ready=True,
            )
        )

        await process._require_active_attestation()
        assert (await process.receive().__anext__()).prompt == "early editor input"
    finally:
        await _close_slo_owned_socket_transport(process=process, peer=peer, server=server)


async def test_slo_owned_socket_transport_sends_shutdown_and_waits_for_host_closed(tmp_path: Path) -> None:
    """Send shutdown before closing IPC and allow an orderly peer close without forced process control."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    close_task: asyncio.Task[None] = asyncio.create_task(process.aclose())
    try:
        shutdown: SlotuiHostCommandDAO = await peer.receive_command()
        assert shutdown.kind == "shutdown"
        await peer.send_event(
            event=SlotuiHostEventDAO(
                protocol_version=SLOTUI_HOST_CONTROL_PROTOCOL_VERSION, kind="host_closed"
            )
        )
        await close_task
        await process.aclose()
    finally:
        if not close_task.done():
            close_task.cancel()
            await close_task
        await peer.aclose()
        server.close()
        await server.wait_closed()
