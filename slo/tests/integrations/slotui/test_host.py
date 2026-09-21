"""Pure non-runtime tests for v2 Slotui control IPC, mapping, and parent policy."""

from __future__ import annotations

import asyncio
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
        del mutation_id

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
        with patch.object(process, "_drain_stderr", new_callable=AsyncMock):
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


async def test_slo_owned_socket_transport_buffers_editor_frame_during_ordered_startup(tmp_path: Path) -> None:
    """Preserve an early editor frame while startup consumes launch, attestation, and active in order."""
    process, peer, server = await _build_slo_owned_socket_transport(tmp_path=tmp_path)
    declaration: str = "slotui.adapter.launch"
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
