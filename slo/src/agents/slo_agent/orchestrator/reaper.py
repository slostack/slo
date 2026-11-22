"""Identity-verified termination for recorded sub-agent processes.

FleetReaper owns the per-pid SIGTERM, grace, SIGKILL protocol. The pool,
headless runner, and terminal workflow sweep share this stateless utility.
ChildChannelReaper closes the channel participant a child left open (108.4).

Sub-spec 71.a.6.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
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
    "IdentityVerificationOutcome",
    "ReapOutcome",
]

IdentityVerificationOutcome = Literal["matching", "already_dead", "recycled_pid", "unreadable"]
"""Classified evidence for a recorded child process identity."""

ReapOutcome = Literal["graceful", "killed", "already_dead", "recycled_pid", "unresolved"]
"""How one child reap attempt concluded."""


class FleetReaper:
    """Verify and terminate recorded sub-agent processes."""

    @classmethod
    def verify_child_identity(cls, *, pid: int, session_id: str) -> bool:
        """Return whether a live pid has the exact expected session option.

        WHAT: Reduces classified child identity evidence to the safe signal predicate.
        WHO: Called by per-child cleanup paths before they signal a recorded pid.
        WHEN: Immediately before a cleanup path considers a child signal.

        Args:
            pid (int): Recorded child process identifier.
            session_id (str): Child session identifier expected in its argv.

        Returns:
            bool: True only when the live process argv identifies that child.
        """
        return cls.child_identity_outcome(pid=pid, session_id=session_id) == "matching"

    @classmethod
    def child_identity_outcome(cls, *, pid: int, session_id: str) -> IdentityVerificationOutcome:
        """Classify whether a pid still belongs to the recorded child.

        WHAT: Separates dead, unreadable, recycled, and exact-match evidence.
        WHO: Called by process cancellation, drain, and terminal sweep cleanup paths.
        WHEN: Before each per-child cleanup decision.

        Args:
            pid (int): Recorded child process identifier.
            session_id (str): Expected child session identifier.

        Returns:
            IdentityVerificationOutcome: Safe identity evidence for the recorded pid.
        """
        if not ProcessProbe.is_alive(pid=pid):
            return "already_dead"
        args: Optional[str] = cls._read_process_args(pid=pid)
        if args is None:
            return "unreadable"
        if cls._argv_has_session_id(args=args, session_id=session_id):
            return "matching"
        return "recycled_pid"

    @staticmethod
    def _argv_has_session_id(*, args: str, session_id: str) -> bool:
        """Return whether parsed argv has the exact expected session-id option.

        WHAT: Rejects substring matches inside prefixes and prompt arguments.
        WHO: Called by child_identity_outcome after ps supplies argv text.
        WHEN: While classifying a live recorded pid.
        """
        try:
            argv: list[str] = shlex.split(args)
        except ValueError:
            return False
        return (
            any(option == "--session-id" and value == session_id for option, value in zip(argv, argv[1:]))
            or f"--session-id={session_id}" in argv
        )

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
    def _read_process_args(*, pid: int) -> Optional[str]:
        """Return one process argv through ps, or None when it cannot be read."""
        try:
            result: subprocess.CompletedProcess[bytes] = subprocess.run(
                ["ps", "-o", "args=", "-p", str(pid)],
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")

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
