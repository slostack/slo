"""Tests for identity-verified fleet child reaping."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.agents.slo_agent.orchestrator.reaper import FleetReaper, ProcessArgvReader

OwnedSleeperFactory = Callable[..., subprocess.Popen[bytes]]
"""Start a test-owned sleeping process whose argv ends with the given arguments."""


@pytest.fixture
def owned_sleeper() -> Iterator[OwnedSleeperFactory]:
    """Yield a factory for real sleeping processes this test owns and always reaps.

    Identity checks only read argv; no test here signals any pid except its own
    sleepers, which the fixture kills and waits for in ``finally``. Each sleeper
    prints one ready line once running, because its argv is briefly empty while
    ``execve`` is still installing the new image.
    """
    processes: list[subprocess.Popen[bytes]] = []

    def start(*argv_tail: str) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [sys.executable, "-c", "import time; print(flush=True); time.sleep(60)", *argv_tail],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        assert process.stdout is not None and process.stdout.readline() == b"\n"
        return process

    try:
        yield start
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            if process.stdout is not None:
                process.stdout.close()


class TestFleetReaperIdentityOfRealProcesses:
    """Identity is read from a live process's real argv, whatever the terminal width.

    A wide ``COLUMNS`` is the default so each test isolates argv-boundary
    handling; the narrow-terminal test overrides it to isolate truncation.
    """

    @pytest.fixture(autouse=True)
    def _wide_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Keep width-limited argv readers from hiding boundary mistakes."""
        monkeypatch.setenv("COLUMNS", "4096")

    def test_long_prompt_before_session_id_matches_under_a_narrow_terminal(
        self, owned_sleeper: OwnedSleeperFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A >300-char prompt ahead of --session-id must not truncate the identity away."""
        monkeypatch.setenv("COLUMNS", "120")
        session_id: str = str(uuid4())
        child: subprocess.Popen[bytes] = owned_sleeper("-p", "review " * 60, "--session-id", session_id)

        assert FleetReaper.child_identity_outcome(pid=child.pid, session_id=session_id) == "matching"

    def test_prompt_with_an_unbalanced_quote_still_matches(self, owned_sleeper: OwnedSleeperFactory) -> None:
        """Prompt punctuation such as an apostrophe never misclassifies the owned child."""
        session_id: str = str(uuid4())
        child: subprocess.Popen[bytes] = owned_sleeper("-p", "don't stop", "--session-id", session_id)

        assert FleetReaper.child_identity_outcome(pid=child.pid, session_id=session_id) == "matching"

    def test_session_option_inside_a_prompt_does_not_authorize_a_signal(
        self, owned_sleeper: OwnedSleeperFactory
    ) -> None:
        """A prompt that merely mentions the expected session option is a foreign process."""
        session_id: str = str(uuid4())
        foreign: subprocess.Popen[bytes] = owned_sleeper("-p", f"say --session-id {session_id}")

        assert FleetReaper.child_identity_outcome(pid=foreign.pid, session_id=session_id) == "recycled_pid"

    def test_prompt_session_option_is_overridden_by_the_real_option(
        self, owned_sleeper: OwnedSleeperFactory
    ) -> None:
        """The effective (last) --session-id decides identity, not one quoted in a prompt."""
        expected_session_id: str = str(uuid4())
        foreign: subprocess.Popen[bytes] = owned_sleeper(
            "-p", f"--session-id {expected_session_id}", "--session-id", str(uuid4())
        )

        assert (
            FleetReaper.child_identity_outcome(pid=foreign.pid, session_id=expected_session_id)
            == "recycled_pid"
        )

    def test_equals_form_session_option_matches(self, owned_sleeper: OwnedSleeperFactory) -> None:
        """The --session-id=<id> spelling identifies the child too."""
        session_id: str = str(uuid4())
        child: subprocess.Popen[bytes] = owned_sleeper(f"--session-id={session_id}")

        assert FleetReaper.child_identity_outcome(pid=child.pid, session_id=session_id) == "matching"

    def test_prefixed_foreign_session_id_is_rejected(self, owned_sleeper: OwnedSleeperFactory) -> None:
        """A session id that only starts with the expected id is another child."""
        foreign: subprocess.Popen[bytes] = owned_sleeper("--session-id", "child-123")

        assert FleetReaper.child_identity_outcome(pid=foreign.pid, session_id="child-1") == "recycled_pid"


class LinuxCmdlineProcargs2Source:
    """Emulate macOS ``KERN_PROCARGS2`` from a real Linux process's exact argv.

    Builds the Darwin layout (native ``int`` argc, NUL-terminated exec path,
    NUL alignment padding, argc NUL-terminated arguments, then environment)
    from ``/proc/<pid>/cmdline``, so the Darwin decoder and identity rule run
    on a live process's real argument boundaries. This is not native Darwin
    proof; ``test_native_darwin_sysctl_reads_a_real_child`` covers that on macOS.
    """

    def read(self, *, pid: int) -> Optional[bytes]:
        """Return a KERN_PROCARGS2-shaped buffer for one live Linux pid."""
        raw_argv: bytes = Path(f"/proc/{pid}/cmdline").read_bytes()
        argc: int = raw_argv.count(b"\0")
        exec_path: bytes = raw_argv.split(b"\0", 1)[0]
        return (
            argc.to_bytes(length=ctypes.sizeof(ctypes.c_int), byteorder=sys.byteorder, signed=True)
            + exec_path
            + b"\0" * 4
            + raw_argv
            + b"HOME=/nonexistent\0"
        )


class FixedProcargs2Source:
    """Return one scripted KERN_PROCARGS2 result, standing in for the libc sysctl."""

    def __init__(self, *, buffer: Optional[bytes]) -> None:
        """Store the scripted sysctl result (None models a failed sysctl)."""
        self._buffer: Optional[bytes] = buffer

    def read(self, *, pid: int) -> Optional[bytes]:
        """Return the scripted buffer for any pid."""
        return self._buffer


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="emulation reads Linux /proc argv")
class TestFleetReaperIdentityWithoutProc:
    """Platforms without /proc must keep argv boundaries or refuse to authorize a signal."""

    @pytest.fixture
    def darwin_reader(self) -> ProcessArgvReader:
        """Return the Darwin argv path fed by a real process's emulated KERN_PROCARGS2."""
        return ProcessArgvReader(platform="darwin", procargs2_source=LinuxCmdlineProcargs2Source())

    def test_darwin_session_option_inside_a_prompt_does_not_authorize_a_signal(
        self, owned_sleeper: OwnedSleeperFactory, darwin_reader: ProcessArgvReader
    ) -> None:
        """A prompt that merely mentions the expected session option is a foreign process."""
        session_id: str = str(uuid4())
        foreign: subprocess.Popen[bytes] = owned_sleeper("-p", f"say --session-id {session_id}")

        assert (
            FleetReaper.child_identity_outcome(
                pid=foreign.pid, session_id=session_id, argv_reader=darwin_reader
            )
            == "recycled_pid"
        )

    def test_darwin_real_option_after_a_long_quoted_prompt_matches(
        self,
        owned_sleeper: OwnedSleeperFactory,
        darwin_reader: ProcessArgvReader,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A long prompt full of apostrophes never hides the genuine trailing option."""
        monkeypatch.setenv("COLUMNS", "120")
        session_id: str = str(uuid4())
        child: subprocess.Popen[bytes] = owned_sleeper("-p", "don't " * 60, "--session-id", session_id)

        assert (
            FleetReaper.child_identity_outcome(
                pid=child.pid, session_id=session_id, argv_reader=darwin_reader
            )
            == "matching"
        )

    def test_darwin_prompt_session_option_is_overridden_by_the_real_option(
        self, owned_sleeper: OwnedSleeperFactory, darwin_reader: ProcessArgvReader
    ) -> None:
        """The effective (last) real --session-id decides identity on Darwin too."""
        expected_session_id: str = str(uuid4())
        foreign: subprocess.Popen[bytes] = owned_sleeper(
            "-p", f"--session-id {expected_session_id}", "--session-id", str(uuid4())
        )

        assert (
            FleetReaper.child_identity_outcome(
                pid=foreign.pid, session_id=expected_session_id, argv_reader=darwin_reader
            )
            == "recycled_pid"
        )

    @pytest.mark.parametrize("prompt_mentions_session", [False, True])
    def test_platform_without_boundary_preserving_argv_fails_closed(
        self, owned_sleeper: OwnedSleeperFactory, prompt_mentions_session: bool
    ) -> None:
        """Without /proc or KERN_PROCARGS2 no argv is trusted, so no pid is signal-eligible."""
        session_id: str = str(uuid4())
        argv_tail: tuple[str, ...] = (
            ("-p", f"say --session-id {session_id}")
            if prompt_mentions_session
            else ("--session-id", session_id)
        )
        process: subprocess.Popen[bytes] = owned_sleeper(*argv_tail)

        assert (
            FleetReaper.child_identity_outcome(
                pid=process.pid, session_id=session_id, argv_reader=ProcessArgvReader(platform="freebsd14")
            )
            == "unreadable"
        )

    @pytest.mark.parametrize(
        "buffer",
        [
            None,
            b"",
            (2).to_bytes(length=ctypes.sizeof(ctypes.c_int), byteorder=sys.byteorder)
            + b"/bin/x\0\0x\0--sess",
            (0).to_bytes(length=ctypes.sizeof(ctypes.c_int), byteorder=sys.byteorder) + b"/bin/x\0\0",
        ],
        ids=["sysctl_failed", "empty", "truncated_argument", "no_arguments"],
    )
    def test_darwin_unreadable_or_malformed_procargs_fails_closed(
        self, owned_sleeper: OwnedSleeperFactory, buffer: Optional[bytes]
    ) -> None:
        """A failed sysctl or a buffer without argc complete arguments is never trusted."""
        session_id: str = str(uuid4())
        child: subprocess.Popen[bytes] = owned_sleeper("--session-id", session_id)
        reader: ProcessArgvReader = ProcessArgvReader(
            platform="darwin", procargs2_source=FixedProcargs2Source(buffer=buffer)
        )

        assert (
            FleetReaper.child_identity_outcome(pid=child.pid, session_id=session_id, argv_reader=reader)
            == "unreadable"
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="native KERN_PROCARGS2 exists only on macOS")
def test_native_darwin_sysctl_reads_a_real_child(owned_sleeper: OwnedSleeperFactory) -> None:
    """On macOS the real libc sysctl keeps an embedded option inside its prompt argument."""
    session_id: str = str(uuid4())
    child: subprocess.Popen[bytes] = owned_sleeper(
        "-p", f"say --session-id {session_id}", "--session-id", session_id
    )
    foreign: subprocess.Popen[bytes] = owned_sleeper("-p", f"say --session-id {session_id}")

    assert FleetReaper.child_identity_outcome(pid=child.pid, session_id=session_id) == "matching"
    assert FleetReaper.child_identity_outcome(pid=foreign.pid, session_id=session_id) == "recycled_pid"


class TestFleetReaperIdentity:
    """FleetReaper identity verification guards pid signals."""

    def test_verify_identity_rejects_dead_pid(self, monkeypatch) -> None:
        """A dead pid is rejected without reading its command line."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: False
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1") is False

    def test_verify_identity_rejects_unreadable_args(self, monkeypatch) -> None:
        """A live pid with unreadable argv is not safe to signal."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        reader: ProcessArgvReader = ProcessArgvReader(
            platform="darwin", procargs2_source=FixedProcargs2Source(buffer=None)
        )

        assert FleetReaper.verify_child_identity(pid=123, session_id="child-1", argv_reader=reader) is False


class TestFleetReaperReap:
    """FleetReaper terminate protocol outcomes."""

    async def test_reap_returns_graceful_when_term_suffices(self, monkeypatch) -> None:
        """A child exiting during SIGTERM grace is reported graceful."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(return_value=True))

        assert await FleetReaper.reap(pid=123) == "graceful"
        signal.assert_called_once()

    async def test_reap_returns_killed_when_kill_required(self, monkeypatch) -> None:
        """A child surviving SIGTERM grace is reported killed after SIGKILL."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(side_effect=[False, True]))

        assert await FleetReaper.reap(pid=123) == "killed"
        assert signal.call_count == 2

    async def test_reap_returns_unresolved_when_kill_does_not_confirm_exit(self, monkeypatch) -> None:
        """A PID surviving SIGKILL grace remains unresolved, never reaped."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: True
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)
        monkeypatch.setattr(FleetReaper, "_await_exit", AsyncMock(side_effect=[False, False]))

        assert await FleetReaper.reap(pid=123) == "unresolved"
        assert signal.call_count == 2

    async def test_reap_returns_already_dead(self, monkeypatch) -> None:
        """A missing pid produces no signal and reports already dead."""
        monkeypatch.setattr(
            "src.agents.slo_agent.orchestrator.reaper.ProcessProbe.is_alive", lambda *, pid: False
        )
        signal: MagicMock = MagicMock()
        monkeypatch.setattr(FleetReaper, "_signal", signal)

        assert await FleetReaper.reap(pid=123) == "already_dead"
        signal.assert_not_called()
