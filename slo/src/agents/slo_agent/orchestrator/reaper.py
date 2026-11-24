"""Identity-verified termination for recorded sub-agent processes.

FleetReaper owns the per-pid SIGTERM, grace, SIGKILL protocol. The pool,
headless runner, and terminal workflow sweep share this stateless utility.
ChildChannelReaper closes the channel participant a child left open (108.4).

Sub-spec 71.a.6.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import sys
from typing import Literal, Optional, Protocol
from uuid import UUID

from config.logger import log_info, log_warning
from config.timeout_resolver import positive_float_env
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe

__all__ = [
    "ABANDONED_CHILD_CLOSE_REASON",
    "ChildChannelGateway",
    "ChildChannelReaper",
    "FleetReaper",
    "DarwinSysctlProcargs2Source",
    "IdentityVerificationOutcome",
    "Procargs2Source",
    "ProcessArgvReader",
    "ReapOutcome",
]

IdentityVerificationOutcome = Literal["matching", "already_dead", "recycled_pid", "unreadable"]
"""Classified evidence for a recorded child process identity."""

ReapOutcome = Literal["graceful", "killed", "already_dead", "recycled_pid", "unresolved"]
"""How one child reap attempt concluded."""


class Procargs2Source(Protocol):
    """Supply one pid's raw macOS ``KERN_PROCARGS2`` buffer."""

    def read(self, *, pid: int) -> Optional[bytes]:
        """Return the raw buffer, or None when the kernel refuses or fails."""
        ...


class DarwinSysctlProcargs2Source:
    """Read ``KERN_PROCARGS2`` through the libc ``sysctl`` call (macOS only).

    The buffer is sized by ``KERN_ARGMAX``, the kernel's argument-space limit,
    so the whole argv fits whatever the prompt length or terminal width.
    """

    _CTL_KERN: int = 1
    _KERN_ARGMAX: int = 8
    _KERN_PROCARGS2: int = 49

    def read(self, *, pid: int) -> Optional[bytes]:
        """Return one pid's raw KERN_PROCARGS2 buffer, or None on any failure.

        Args:
            pid (int): Live process identifier to inspect.

        Returns:
            Optional[bytes]: Raw kernel buffer, or None when libc or sysctl fails.
        """
        try:
            libc: ctypes.CDLL = ctypes.CDLL(None, use_errno=True)
        except OSError:
            return None
        capacity: Optional[int] = self._argument_capacity(libc=libc)
        if capacity is None:
            return None
        buffer: ctypes.Array[ctypes.c_char] = ctypes.create_string_buffer(capacity)
        size: ctypes.c_size_t = ctypes.c_size_t(capacity)
        mib: ctypes.Array[ctypes.c_int] = (ctypes.c_int * 3)(self._CTL_KERN, self._KERN_PROCARGS2, pid)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
            return None
        return buffer.raw[: size.value]

    def _argument_capacity(self, *, libc: ctypes.CDLL) -> Optional[int]:
        """Return the kernel's KERN_ARGMAX byte limit, or None when unavailable."""
        argmax: ctypes.c_int = ctypes.c_int(0)
        size: ctypes.c_size_t = ctypes.c_size_t(ctypes.sizeof(argmax))
        mib: ctypes.Array[ctypes.c_int] = (ctypes.c_int * 2)(self._CTL_KERN, self._KERN_ARGMAX)
        status: int = libc.sysctl(mib, 2, ctypes.byref(argmax), ctypes.byref(size), None, ctypes.c_size_t(0))
        if status != 0 or argmax.value <= 0:
            return None
        return argmax.value


class ProcessArgvReader:
    """Read a live process's argv with argument boundaries intact, or report it unreadable.

    Identity decides whether a pid may be signalled, so only sources that keep
    each argument separate are trusted: Linux ``/proc/<pid>/cmdline`` and macOS
    ``KERN_PROCARGS2``. Space-joined text such as ``ps`` output cannot tell a
    prompt that mentions ``--session-id <id>`` from the real option, so other
    platforms fail closed and their children are never signal-eligible.
    """

    def __init__(
        self, *, platform: str = sys.platform, procargs2_source: Optional[Procargs2Source] = None
    ) -> None:
        """Bind the platform and the macOS argv source.

        Args:
            platform (str): ``sys.platform`` value selecting the argv source.
            procargs2_source (Optional[Procargs2Source]): macOS buffer source;
                defaults to the libc sysctl reader.
        """
        self._platform: str = platform
        self._procargs2_source: Procargs2Source = procargs2_source or DarwinSysctlProcargs2Source()

    def read(self, *, pid: int) -> Optional[list[str]]:
        """Return one process argv, or None when no boundary-preserving source can read it.

        Args:
            pid (int): Live process identifier to inspect.

        Returns:
            Optional[list[str]]: Exact argv, or None when unreadable or unsupported.
        """
        if self._platform.startswith("linux"):
            return self._read_linux_cmdline(pid=pid)
        if self._platform == "darwin":
            return self._read_darwin_procargs2(pid=pid)
        log_warning(msg="fleet_reaper_argv_unsupported_platform", platform=self._platform, pid=pid)
        return None

    @staticmethod
    def _read_linux_cmdline(*, pid: int) -> Optional[list[str]]:
        """Return the exact NUL-separated argv from ``/proc/<pid>/cmdline``."""
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
                raw_argv: bytes = cmdline.read()
        except OSError:
            return None
        return [os.fsdecode(argument) for argument in raw_argv.split(b"\0")[:-1]]

    def _read_darwin_procargs2(self, *, pid: int) -> Optional[list[str]]:
        """Decode argv from a ``KERN_PROCARGS2`` buffer, refusing any incomplete one.

        Layout: native ``int`` argc, NUL-terminated exec path, NUL alignment
        padding, then argc NUL-terminated arguments followed by the environment.
        """
        buffer: Optional[bytes] = self._procargs2_source.read(pid=pid)
        header_size: int = ctypes.sizeof(ctypes.c_int)
        if buffer is None or len(buffer) < header_size:
            return None
        argc: int = int.from_bytes(buffer[:header_size], byteorder=sys.byteorder, signed=True)
        exec_path_end: int = buffer.find(b"\0", header_size)
        if argc <= 0 or exec_path_end < 0:
            return None
        fields: list[bytes] = buffer[exec_path_end:].lstrip(b"\0").split(b"\0")
        if len(fields) <= argc:
            return None
        return [os.fsdecode(argument) for argument in fields[:argc]]


class FleetReaper:
    """Verify and terminate recorded sub-agent processes."""

    @classmethod
    def verify_child_identity(
        cls, *, pid: int, session_id: str, argv_reader: Optional[ProcessArgvReader] = None
    ) -> bool:
        """Return whether a live pid has the exact expected session option.

        WHAT: Reduces classified child identity evidence to the safe signal predicate.
        WHO: Called by per-child cleanup paths before they signal a recorded pid.
        WHEN: Immediately before a cleanup path considers a child signal.

        Args:
            pid (int): Recorded child process identifier.
            session_id (str): Child session identifier expected in its argv.
            argv_reader (Optional[ProcessArgvReader]): Argv source; defaults to this platform's.

        Returns:
            bool: True only when the live process argv identifies that child.
        """
        return (
            cls.child_identity_outcome(pid=pid, session_id=session_id, argv_reader=argv_reader) == "matching"
        )

    @classmethod
    def child_identity_outcome(
        cls, *, pid: int, session_id: str, argv_reader: Optional[ProcessArgvReader] = None
    ) -> IdentityVerificationOutcome:
        """Classify whether a pid still belongs to the recorded child.

        WHAT: Separates dead, unreadable, recycled, and exact-match evidence.
        WHO: Called by process cancellation, drain, and terminal sweep cleanup paths.
        WHEN: Before each per-child cleanup decision.

        Args:
            pid (int): Recorded child process identifier.
            session_id (str): Expected child session identifier.
            argv_reader (Optional[ProcessArgvReader]): Argv source; defaults to this platform's.

        Returns:
            IdentityVerificationOutcome: Safe identity evidence for the recorded pid.
        """
        if not ProcessProbe.is_alive(pid=pid):
            return "already_dead"
        argv: Optional[list[str]] = (argv_reader or ProcessArgvReader()).read(pid=pid)
        if argv is None:
            return "unreadable"
        if cls._effective_session_id(argv=argv) == session_id:
            return "matching"
        return "recycled_pid"

    @staticmethod
    def _effective_session_id(*, argv: list[str]) -> Optional[str]:
        """Return the --session-id value the child's CLI actually resolved, if any.

        WHAT: Takes the last ``--session-id <id>`` or ``--session-id=<id>``
            occurrence, as Click does for a repeated option, so neither a
            prefixed id nor one quoted earlier in a prompt can stand in for it.
        WHO: Called by child_identity_outcome on a live recorded pid's argv.
        WHEN: While classifying a live recorded pid.
        """
        session_id: Optional[str] = None
        for index, argument in enumerate(argv):
            if argument == "--session-id" and index + 1 < len(argv):
                session_id = argv[index + 1]
            elif argument.startswith("--session-id="):
                session_id = argument.removeprefix("--session-id=")
        return session_id

    @classmethod
    async def reap(cls, *, pid: int) -> ReapOutcome:
        """Terminate one pid with SIGTERM, grace, then SIGKILL when needed.

        WHAT: Runs the shared per-pid cleanup protocol without raising to callers.
        WHO: Called by SubAgentProcess.cancel and identity-verified fleet reapers.
        WHEN: After a caller has determined a child needs termination.

        Args:
            pid (int): Child process identifier to terminate.

        Returns:
            ReapOutcome: Whether the child exited gracefully, required SIGKILL, or was gone.
        """
        if not ProcessProbe.is_alive(pid=pid):
            return "already_dead"
        grace_seconds: float = positive_float_env(
            primary_name="SLO_SUBAGENT_TERMINATE_GRACE_SECONDS",
            default=5.0,
        )
        cls._signal(pid=pid, sig=signal.SIGTERM)
        if await cls._await_exit(pid=pid, timeout_seconds=grace_seconds):
            return "graceful"
        cls._signal(pid=pid, sig=signal.SIGKILL)
        if await cls._await_exit(pid=pid, timeout_seconds=grace_seconds):
            return "killed"
        return "unresolved"

    @staticmethod
    def _signal(*, pid: int, sig: int) -> None:
        """Send one signal while tolerating a child that exited mid-sequence."""
        try:
            os.kill(pid, sig)
        except OSError as exc:
            log_info(msg="fleet_reaper_signal_skipped", pid=pid, error=str(exc))

    @staticmethod
    async def _await_exit(*, pid: int, timeout_seconds: float) -> bool:
        """Poll one pid until it exits or its termination grace expires."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        deadline: float = loop.time() + timeout_seconds
        while loop.time() < deadline:
            if not ProcessProbe.is_alive(pid=pid):
                return True
            await asyncio.sleep(0.1)
        return not ProcessProbe.is_alive(pid=pid)


ABANDONED_CHILD_CLOSE_REASON: str = "aborted"
"""Cancel reason for rows pending to a child that ended without closing (108.4 §6)."""


class ChildChannelGateway(Protocol):
    """Consumer-owned slice of ``ChannelGateway`` that the child channel reaper needs."""

    async def close_agent(self, *, session_id: UUID, reason: str) -> int:
        """Close one agent participant and cancel its pending inbound rows atomically."""
        ...


class ChildChannelReaper:
    """Close the channel participant of a child that ended without closing it.

    A healthy child closes itself when it stops its poller. A child that
    crashed, was killed or was reaped leaves its participant ``open``, so
    messages would wait for a listener that is gone. This reaper closes the
    participant and cancels its pending rows (``aborted``) in one transaction.
    Closing is idempotent: a participant the child already closed has no
    pending rows left, and a child that never registered has no participant,
    so neither changes. It never raises: the channel queue is a side channel
    and must not change a child's terminal result.
    """

    def __init__(self, *, gateway: ChildChannelGateway) -> None:
        """Bind the reaper to the shared channel gateway.

        Args:
            gateway (ChildChannelGateway): Shared channel queue gateway.
        """
        self._gateway: ChildChannelGateway = gateway

    async def close_abandoned_participant(self, *, session_id: str) -> int:
        """Close the child's participant and cancel rows still pending to it.

        WHAT: Closes the child's participant with reason ``aborted``; rows the
            child never accepted are cancelled in the same transaction. Queue
            failures are logged and reported as zero cancelled rows.
        WHO: ``SubAgentPool`` once per child incarnation.
        WHEN: After the incarnation's terminal winner is known, before its
            terminal lifecycle event is emitted.

        Args:
            session_id (str): Child session id as assigned by the pool.

        Returns:
            int: Number of pending rows cancelled; zero when the child had
                already closed itself or never registered.
        """
        participant_id: UUID = channel_participant_id_for_session(session_id=session_id)
        try:
            return await self._gateway.close_agent(
                session_id=participant_id, reason=ABANDONED_CHILD_CLOSE_REASON
            )
        except Exception as exc:  # noqa: BLE001 — a broken queue must not change the child's result
            log_warning(msg="child_channel_close_failed", session_id=session_id, error=str(exc))
            return 0
