"""Candidate-gated real adapter integration; no toy wheel is runtime evidence."""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import subprocess
import sys
import termios
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.integrations.slotui.dao import SlotuiCoreArtifactReferenceDAO
from src.integrations.slotui.host import (
    InstalledSlotuiHostProcess,
    SlotuiCoreHostService,
    SlotuiTerminalBridge,
)
from src.integrations.slotui.host_protocol import SLOTUI_HOST_CONTROL_PROTOCOL_VERSION
from src.integrations.slotui.verifier import SlotuiCoreWheelVerificationService

_CANDIDATE_REFERENCE_ENV: str = "SLO_SLOTUI_CANDIDATE_REFERENCE"


@pytest.mark.e2e
def test_real_bundle_static_verification_accepts_the_supplied_complete_closure(tmp_path: Path) -> None:
    """Verify the supplied v2 reference and every pinned offline wheel without importing Slotui."""
    reference_path: Path = _require_production_pinned_candidate_reference()
    reference = SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))

    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)

    assert receipt.wheel_path.name == "slotui-0.1.0-py3-none-any.whl"
    assert receipt.wheel_path.parent == reference.manifest_path.parent


@pytest.mark.e2e
@pytest.mark.isolated_pty
def test_real_installed_candidate_bridge_roundtrips_real_terminal_editor_and_slo_response(
    tmp_path: Path,
) -> None:
    """Run parent-PTY proof in a clean subprocess that cannot disturb pytest stdio."""
    reference_path: Path = _require_production_pinned_candidate_reference()
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "tests.integrations.slotui.test_runtime",
            "--parent-pty-proof",
            str(reference_path),
            str(tmp_path),
        ),
        cwd=Path(__file__).resolve().parents[3],
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "parent_pty_proof=passed" in result.stdout


async def _run_parent_pty_proof(*, reference_path: Path, temporary_directory: Path) -> None:
    """Drive an actual installed candidate through a parent terminal PTY bridge.

    Args:
        reference_path (Path): Clean v2 candidate release reference.
        temporary_directory (Path): Test-isolated Slo work directory.
    """
    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(
        reference=SlotuiCoreArtifactReferenceDAO.model_validate_json(
            reference_path.read_text(encoding="utf-8")
        )
    )
    host_master_fd, host_slave_fd = pty.openpty()
    original_attributes = termios.tcgetattr(host_slave_fd)
    original_input_flags = fcntl.fcntl(host_slave_fd, fcntl.F_GETFL)
    original_output_flags = fcntl.fcntl(host_slave_fd, fcntl.F_GETFL)
    original_stdin_flags: int | None = None
    original_stdout_flags: int | None = None
    process = InstalledSlotuiHostProcess(receipt=receipt, setup_timeout_seconds=90.0)
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="parent PTY FauxChatModel response")])),
        workdir=temporary_directory,
        session_id="slotui-parent-pty-session",
        enable_history=False,
    )
    service = SlotuiCoreHostService(
        session=session,
        process=process,
        workdir=temporary_directory,
        resume_session_id=None,
    )
    original_stdin = os.dup(0)
    original_stdout = os.dup(1)
    service_task: asyncio.Task[None] | None = None
    restored_terminal: bool = False
    restored_flags: bool = False
    private_child_stdio: bool = False
    visible_candidate_bytes: bool = False
    forwarded_parent_keystrokes: bool = False
    control_socket_isolated: bool = False
    child_reaped: bool = False
    bridge: SlotuiTerminalBridge | None = None
    try:
        os.dup2(host_slave_fd, 0)
        os.dup2(host_slave_fd, 1)
        original_stdin_flags = fcntl.fcntl(0, fcntl.F_GETFL)
        original_stdout_flags = fcntl.fcntl(1, fcntl.F_GETFL)
        assert original_stdin_flags == original_input_flags
        assert original_stdout_flags == original_output_flags
        service_task = asyncio.create_task(service.invoke())
        await _wait_for_terminal_receipt(process=process, service_task=service_task)
        terminal_receipt = process._terminal_inspection_receipt
        assert terminal_receipt is not None
        parent_terminal_identity = _terminal_identity(fd=host_slave_fd)
        assert terminal_receipt.child_stdin_identity == terminal_receipt.private_slave_identity
        assert terminal_receipt.child_stdout_identity == terminal_receipt.private_slave_identity
        assert terminal_receipt.child_stdin_identity != parent_terminal_identity
        assert terminal_receipt.child_stdout_identity != parent_terminal_identity
        assert terminal_receipt.child_process_group_id == terminal_receipt.child_pid
        assert terminal_receipt.control_socket_path.is_socket()
        assert terminal_receipt.control_socket_path.stat().st_ino not in {
            terminal_receipt.child_stdin_inode,
            terminal_receipt.child_stdout_inode,
        }
        private_child_stdio = True
        control_socket_isolated = True

        bridge = process._terminal_bridge
        assert bridge is not None
        await _wait_for_terminal_bridge_activation(bridge=bridge, service_task=service_task)
        input_before = bridge.parent_to_candidate_bytes_forwarded
        os.write(host_master_fd, b"bridge terminal keystroke receipt\x1b[13;5u")
        await _wait_for_forwarded_input(
            bridge=bridge, minimum=input_before + len(b"bridge terminal keystroke receipt\x1b[13;5u")
        )
        forwarded_parent_keystrokes = True

        response_screen: bytes = await _read_pty_until_contains(
            master_fd=host_master_fd,
            expected=b"parent PTY FauxChatModel response",
            service_task=service_task,
        )
        assert b"Slotui core host failed" not in response_screen
        assert bridge.candidate_to_parent_bytes_forwarded > 0
        visible_candidate_bytes = True
        await process.aclose()
        await asyncio.wait_for(service_task, timeout=20.0)
        child_reaped = True
    finally:
        if service_task is not None and not service_task.done():
            service_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await service_task
        restored_terminal = termios.tcgetattr(host_slave_fd) == original_attributes
        restored_flags = (
            original_stdin_flags is not None
            and original_stdout_flags is not None
            and bridge is not None
            and bridge._host_stdin_flags is None
            and bridge._host_stdout_flags is None
        )
        os.dup2(original_stdin, 0)
        os.dup2(original_stdout, 1)
        os.close(original_stdin)
        os.close(original_stdout)
        os.close(host_master_fd)
        os.close(host_slave_fd)
        await process.aclose()

    assert restored_terminal is True
    assert restored_flags is True
    assert private_child_stdio is True
    assert visible_candidate_bytes is True
    assert forwarded_parent_keystrokes is True
    assert control_socket_isolated is True
    assert child_reaped is True
    assert process._closed is True
    assert process._process is None
    assert process._runtime_root is None
    assert process._terminal_master_fd is None
    assert process._terminal_slave_fd is None
    assert process._sent_mutation_ids == set()
    assert process._acknowledged_mutation_ids == set()


def _terminal_identity(*, fd: int) -> tuple[int, int]:
    """Return the device/inode identity of one parent-side terminal descriptor."""
    descriptor = os.fstat(fd)
    return (descriptor.st_rdev, descriptor.st_ino)


async def _wait_for_terminal_receipt(
    *, process: InstalledSlotuiHostProcess, service_task: asyncio.Task[None]
) -> None:
    """Wait until Slo has OS-inspected the installed child descriptor topology."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 20.0
    while process._terminal_inspection_receipt is None:
        if service_task.done():
            await service_task
        if loop.time() >= deadline:
            raise AssertionError("installed child PTY inspection receipt was not produced")
        await asyncio.sleep(0.01)


async def _wait_for_terminal_bridge_activation(
    *, bridge: SlotuiTerminalBridge, service_task: asyncio.Task[None]
) -> None:
    """Wait until the host has taken the injected parent PTY into raw bridge mode."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 20.0
    while not bridge._host_terminal_active:
        if service_task.done():
            await service_task
        if loop.time() >= deadline:
            raise AssertionError("parent PTY bridge did not become active")
        await asyncio.sleep(0.01)


async def _wait_for_forwarded_input(*, bridge: SlotuiTerminalBridge, minimum: int) -> None:
    """Wait for the host-owned bridge receipt to account for injected parent bytes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while bridge.parent_to_candidate_bytes_forwarded < minimum:
        if loop.time() >= deadline:
            raise AssertionError("parent PTY keystrokes did not reach the private candidate PTY")
        await asyncio.sleep(0.01)


async def _read_pty_until_contains(
    *, master_fd: int, expected: bytes, service_task: asyncio.Task[None]
) -> bytes:
    """Collect rendered PTY bytes until an expected candidate screen fragment appears.

    Args:
        master_fd (int): Invoking terminal PTY master receiving bridge output.
        expected (bytes): Visible literal output that terminates the bounded wait.
        service_task (asyncio.Task[None]): Host lifecycle task checked for an early failure.

    Returns:
        bytes: Complete observed terminal bytes through the expected fragment.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    deadline: float = loop.time() + 20.0
    captured: bytearray = bytearray()
    original_flags: int = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, original_flags | os.O_NONBLOCK)
    try:
        while expected not in captured:
            if service_task.done():
                await service_task
            if loop.time() >= deadline:
                raise AssertionError(f"expected {expected!r} in terminal bytes {bytes(captured)!r}")
            try:
                captured.extend(os.read(master_fd, 65_536))
            except BlockingIOError:
                await asyncio.sleep(0.01)
        return bytes(captured)
    finally:
        fcntl.fcntl(master_fd, fcntl.F_SETFL, original_flags)


async def test_real_candidate_adapter_roundtrips_editor_submit_and_actual_slo_session(
    tmp_path: Path,
) -> None:
    """Run the supplied wheel in a fresh venv and PTY through the candidate's test hook.

    The actual candidate owns the terminal, mounted transcript, test-hook editor
    submission, and acknowledgements.  Slo owns the real deterministic session;
    the assertions below intentionally inspect only Slo's installed-process
    boundary and never import or emulate candidate code.
    """
    reference_path: Path = _require_production_pinned_candidate_reference()
    reference = SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))
    receipt = SlotuiCoreWheelVerificationService.build_verification_receipt(reference=reference)
    process = InstalledSlotuiHostProcess(receipt=receipt)
    session = SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="candidate-gated response")])),
        workdir=tmp_path,
        session_id="slotui-candidate-gated-session",
        enable_history=False,
    )
    service = SlotuiCoreHostService(
        session=session,
        process=process,
        workdir=tmp_path,
        resume_session_id=None,
    )
    original_test_prompt: str | None = os.environ.get("SLO_SLOTUI_PROTOCOL_TEST_PROMPT")
    os.environ["SLO_SLOTUI_PROTOCOL_TEST_PROMPT"] = "candidate-gated editor submission"
    try:
        await service.invoke()
    finally:
        if original_test_prompt is None:
            os.environ.pop("SLO_SLOTUI_PROTOCOL_TEST_PROMPT", None)
        else:
            os.environ["SLO_SLOTUI_PROTOCOL_TEST_PROMPT"] = original_test_prompt
        await process.aclose()

    assert process._shutdown_sent is False
    assert process._closed is True
    assert process._process is None
    assert process._runtime_root is None
    assert process._terminal_master_fd is None
    assert process._terminal_slave_fd is None
    assert process._sent_mutation_ids == set()
    assert process._acknowledged_mutation_ids == set()
    assert process._receipt.wheel_path.parent == reference.manifest_path.parent
    assert receipt.manifest.candidate_adapter.protocol_version == SLOTUI_HOST_CONTROL_PROTOCOL_VERSION


def test_runtime_gate_when_supplied_reference_is_legacy_rejects_without_deriving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep production E2E aligned with selector behavior for missing bundle pins."""
    legacy_reference: Path = tmp_path / "legacy-reference.json"
    legacy_reference.write_text(
        """{
  \"schema_version\": \"slo-slotui-candidate-adapter-v2\",
  \"candidate_label\": \"legacy\",
  \"manifest_path\": \"/absolute/manifest.json\",
  \"manifest_sha256\": \"0000000000000000000000000000000000000000000000000000000000000000\"
}""",
        encoding="utf-8",
    )
    monkeypatch.setenv(_CANDIDATE_REFERENCE_ENV, str(legacy_reference))

    with pytest.raises(pytest.fail.Exception, match="production-compatible v2 reference"):
        _require_production_pinned_candidate_reference()


def _require_production_pinned_candidate_reference() -> Path:
    """Require the exact production v2 release reference without test-local derivation.

    A legacy pointer lacks its independent bundle path and digest, so Slo's
    production selector rejects it. Tests must prove the same input the operator
    could launch; they never manufacture a temporary release reference.

    Returns:
        Path: Existing fully pinned regular v2 reference supplied by release CI.
    """
    reference_path: Path = _require_candidate_reference_path()
    try:
        SlotuiCoreArtifactReferenceDAO.model_validate_json(reference_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as error:
        pytest.fail(
            f"{_CANDIDATE_REFERENCE_ENV} is not a production-compatible v2 reference: {error}. "
            "It must supply bundle_path and bundle_sha256; Slo will not derive those fields at runtime."
        )
    return reference_path


def _run_parent_pty_proof_command() -> None:
    """Run the isolated parent-PTY bridge evidence command from the module CLI."""
    reference_path = Path(sys.argv[2])
    temporary_directory = Path(sys.argv[3])
    asyncio.run(
        _run_parent_pty_proof(
            reference_path=reference_path,
            temporary_directory=temporary_directory,
        )
    )
    print("parent_pty_proof=passed")


def _require_candidate_reference_path() -> Path:
    """Resolve the absolute protected-candidate release reference from the test environment.

    Returns:
        Path: Existing absolute reference supplied by protected CI or the operator.
    """
    reference_text: str | None = os.environ.get(_CANDIDATE_REFERENCE_ENV)
    if reference_text is None:
        pytest.skip(f"set {_CANDIDATE_REFERENCE_ENV} to run protected candidate adapter integration")
    reference_path: Path = Path(reference_text).expanduser()
    if not reference_path.is_absolute():
        pytest.fail("candidate runtime reference must be absolute")
    if not reference_path.is_file() or reference_path.is_symlink():
        pytest.fail("candidate runtime reference must name an existing regular non-symlink file")
    return reference_path


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--parent-pty-proof":
        raise SystemExit("usage: test_runtime.py --parent-pty-proof <reference> <temporary-directory>")
    _run_parent_pty_proof_command()
