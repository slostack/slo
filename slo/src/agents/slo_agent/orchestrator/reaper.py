"""Identity-verified termination for recorded sub-agent processes.

FleetReaper owns the per-pid SIGTERM, grace, SIGKILL protocol. The pool,
headless runner, and terminal workflow sweep share this stateless utility.

Sub-spec 71.a.6.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
from typing import Literal, Optional

from config.logger import log_info
from config.timeout_resolver import positive_float_env
from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe

__all__ = ["FleetReaper", "IdentityVerificationOutcome", "ReapOutcome"]

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
