"""Offline control-frame and allocation regressions; no workload may spawn."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.agents.slo_agent.orchestrator import capture_writer, spawn_env
from src.auth.credential_resolver import CredentialResolver


@pytest.fixture(autouse=True)
def forbid_external_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed on network, credential lookup, and any subprocess launch."""
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(
        CredentialResolver, "resolve", Mock(side_effect=AssertionError("credentials forbidden"))
    )
    monkeypatch.setattr(spawn_env.subprocess, "Popen", Mock(side_effect=AssertionError("process forbidden")))


def control_payload(**overrides: object) -> bytes:
    """Build synthetic identity bytes without reading or writing any file."""
    fields: dict[str, object] = {
        "history_root": "/synthetic/history",
        "owner_session_id": "owner",
        "workflow_id": "wf-test",
        "expected_pid": 1234,
    }
    fields.update(overrides)
    return json.dumps(fields).encode()


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_pid": True},
        {"expected_pid": 1.5},
        {"expected_pid": "1234"},
        {"expected_pid": 0},
        {"expected_pid": -1},
        {"owner_session_id": 4},
        {"owner_session_id": ""},
        {"owner_session_id": "../outside"},
        {"workflow_id": []},
        {"workflow_id": "wf/other"},
        {"history_root": "relative"},
        {"history_root": "/bad\u0000root"},
    ],
)
def test_invalid_control_fields_are_inert(overrides: dict[str, object]) -> None:
    """Never activate reporting with coerced PIDs or unsafe identity paths."""
    assert (
        capture_writer.StreamingCredentialRedactor._parse_control_context(
            payload=control_payload(**overrides)
        )
        is None
    )


@pytest.mark.parametrize("payload", [b"", b"{", b"[]", b"null", b"\xff", b"{}", control_payload() * 2])
def test_malformed_or_multiple_frames_are_inert(payload: bytes) -> None:
    """Reject nonobjects, missing fields, invalid UTF-8 and concatenated frames."""
    assert capture_writer.StreamingCredentialRedactor._parse_control_context(payload=payload) is None


def test_one_valid_control_frame() -> None:
    """Retain the exact positive workload identity on a valid private frame."""
    context = capture_writer.StreamingCredentialRedactor._parse_control_context(payload=control_payload())
    assert context is not None
    assert context.expected_pid == 1234
    assert context.history_root == Path("/synthetic/history")


def test_duplicate_json_field_is_inert() -> None:
    """A repeated identity key must not silently select its last value."""
    payload = control_payload()[:-1] + b', "expected_pid": 5678}'
    assert capture_writer.StreamingCredentialRedactor._parse_control_context(payload=payload) is None


def test_oversize_valid_prefix_never_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read beyond the cap by one byte rather than accepting a valid 4096-byte prefix."""
    frame = control_payload().ljust(4096, b" ") + b"x"
    pending = bytearray(frame)
    closed: list[int] = []

    def read(fd: int, size: int) -> bytes:
        """Emulate bounded FD reads including the old zero-size false EOF."""
        assert fd == 701
        result = bytes(pending[:size])
        del pending[:size]
        return result

    monkeypatch.setattr(capture_writer.os, "read", read)
    monkeypatch.setattr(capture_writer.os, "close", closed.append)
    monkeypatch.setattr(capture_writer.select, "select", lambda *args: ([701], [], []))
    activation = capture_writer._WriterActivation()
    capture_writer.StreamingCredentialRedactor._read_control_frame(control_fd=701, activation=activation)
    assert activation.context is None
    assert activation.control_complete.is_set()
    assert closed == [701]


@pytest.mark.parametrize("fault", [False, True])
def test_control_eof_or_read_fault_cannot_use_legacy_identity(
    monkeypatch: pytest.MonkeyPatch, fault: bool
) -> None:
    """Control-FD mode never upgrades missing adoption through legacy environment."""
    closed: list[int] = []
    monkeypatch.setenv("SLO_CAPTURE_COMPLETION", control_payload().decode())
    monkeypatch.setattr(capture_writer.select, "select", lambda *args: ([702], [], []))
    monkeypatch.setattr(
        capture_writer.os,
        "read",
        Mock(side_effect=OSError("synthetic fault")) if fault else Mock(return_value=b""),
    )
    monkeypatch.setattr(capture_writer.os, "close", closed.append)
    activation = capture_writer._WriterActivation()
    capture_writer.StreamingCredentialRedactor._read_control_frame(control_fd=702, activation=activation)
    assert activation.context is None
    assert activation.control_complete.is_set()
    assert closed == [702]


@pytest.mark.parametrize("control_mode", [True, False])
def test_failed_drain_without_adoption_never_reports_legacy_health(
    monkeypatch: pytest.MonkeyPatch, control_mode: bool
) -> None:
    """A genuine read failure before control adoption cannot report another identity."""
    reader = capture_writer.StreamingCredentialRedactor
    legacy_report = Mock()
    if control_mode:
        monkeypatch.setenv("SLO_CAPTURE_CONTROL_FD", "702")
    else:
        monkeypatch.delenv("SLO_CAPTURE_CONTROL_FD", raising=False)
    monkeypatch.setattr(reader, "_acknowledge_startup", Mock(return_value=703))
    monkeypatch.setattr(reader, "_acknowledge_failure", Mock())
    monkeypatch.setattr(capture_writer.os, "read", Mock(side_effect=OSError("synthetic read failure")))
    monkeypatch.setattr(capture_writer.os, "close", Mock())
    monkeypatch.setattr(capture_writer.WorkflowCaptureCompletionContext, "report_failure", legacy_report)

    def complete_control(*, activation: capture_writer._WriterActivation) -> Mock:
        """Model control EOF with no thread or descriptor escaping the fixture."""
        activation.control_complete.set()
        return Mock()

    monkeypatch.setattr(reader, "_start_control_reader", complete_control)
    with pytest.raises(OSError, match="synthetic read failure"):
        reader.invoke()
    assert legacy_report.call_count == (0 if control_mode else 1)


@pytest.mark.parametrize("failure_call", [1, 2, 3])
def test_pipe_allocation_failure_closes_every_allocated_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_call: int
) -> None:
    """Fail each allocator with fake descriptors; no writer can fall through."""
    root = tmp_path.resolve()
    assert (root / "capture/stdout.jsonl").resolve().is_relative_to(root)
    allocated: list[int] = []
    closed: list[int] = []
    calls = 0

    def pipe() -> tuple[int, int]:
        """Allocate synthetic endpoints until the chosen fault boundary."""
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError("synthetic allocation failure")
        pair = (800 + calls * 2, 801 + calls * 2)
        allocated.extend(pair)
        return pair

    with monkeypatch.context() as patch:
        patch.setattr(spawn_env, "_acquire_capture_append_lease", Mock(return_value=807))
        patch.setattr(spawn_env.os, "pipe", pipe)
        patch.setattr(spawn_env.os, "close", closed.append)
        with pytest.raises(OSError, match="synthetic allocation failure"):
            spawn_env.open_capture_file_append(
                history_root=root, session_id="capture", name="stdout.jsonl", credential="synthetic-key"
            )
    assert sorted(closed) == sorted([*allocated, 807])


def test_unexpected_flock_failure_closes_lock_descriptor_and_allows_reacquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Close the lease descriptor when flock raises outside its normal refusal branch."""
    import fcntl

    root = tmp_path.resolve()
    target = root / "capture/stdout.jsonl"
    assert target.resolve(strict=False).is_relative_to(root)
    real_flock = fcntl.flock
    calls = 0

    def fail_once(descriptor: int, operation: int) -> None:
        """Raise only for the first test-owned lease acquisition."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic flock failure")
        real_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", fail_once)
    with pytest.raises(OSError, match="synthetic flock failure"):
        spawn_env.open_capture_file_append(
            history_root=root, session_id="capture", name="stdout.jsonl", credential="synthetic"
        )
    lock_path = target.with_suffix(".jsonl.append.lock")
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        real_flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(descriptor)


def test_private_capture_creation_modes_preserve_existing_external_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create only owned paths privately without chmodding existing ancestors or files."""
    import stat

    root = tmp_path.resolve()
    external = root / "existing"
    external.mkdir(mode=0o755)
    existing_file = external / "existing.log"
    existing_file.write_bytes(b"before-")
    os.chmod(external, 0o755)
    os.chmod(existing_file, 0o644)
    prior_umask = os.umask(0)
    try:
        spawn_env._create_capture_parent_if_missing(capture_parent=root / "new/session")
        with spawn_env._open_private_capture_append(
            capture_path=root / "new/session/stdout.jsonl"
        ) as capture:
            capture.write(b"private")
        with spawn_env._open_private_capture_append(capture_path=existing_file) as capture:
            capture.write(b"after")
        lock_path = root / "new/session/stdout.jsonl.append.lock"
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descriptor)
    finally:
        os.umask(prior_umask)
    created_directory = root / "new"
    nested_directory = created_directory / "session"
    created_file = nested_directory / "stdout.jsonl"
    created_lock = created_file.with_suffix(".jsonl.append.lock")
    assert stat.S_IMODE(created_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(nested_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(created_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(created_lock.stat().st_mode) == 0o600
    assert stat.S_IMODE(external.stat().st_mode) == 0o755
    assert stat.S_IMODE(existing_file.stat().st_mode) == 0o644
    assert existing_file.read_bytes() == b"before-after"


def test_destination_open_failure_closes_all_six_fds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Destination failure closes all three pipe pairs and the owned append lease."""
    root = tmp_path.resolve()
    target = root / "capture/stdout.jsonl"
    assert target.resolve().is_relative_to(root)
    closed: list[int] = []
    pairs = iter([(801, 802), (803, 804), (805, 806)])
    with monkeypatch.context() as patch:
        patch.setattr(spawn_env, "_acquire_capture_append_lease", Mock(return_value=807))
        patch.setattr(spawn_env.os, "pipe", lambda: next(pairs))
        patch.setattr(spawn_env.os, "close", closed.append)
        patch.setattr(
            spawn_env, "_open_private_capture_append", Mock(side_effect=OSError("synthetic open failure"))
        )
        with pytest.raises(OSError, match="synthetic open failure"):
            spawn_env.open_capture_file_append(
                history_root=root, session_id="capture", name="stdout.jsonl", credential="synthetic-key"
            )
    assert sorted(closed) == list(range(801, 808))


@pytest.mark.parametrize("size, accepted", [(4096, True), (4097, False)])
def test_control_parser_exact_size_boundary(size: int, accepted: bool) -> None:
    """Bound the complete frame, including trailing JSON whitespace."""
    context = capture_writer.StreamingCredentialRedactor._parse_control_context(
        payload=control_payload().ljust(size, b" ")
    )
    assert (context is not None) is accepted
