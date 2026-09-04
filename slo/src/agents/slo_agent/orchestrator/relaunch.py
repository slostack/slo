"""WorkflowRelauncher — resume a dead detached workflow in place.

Builds a resume command from one durable workflow handle, then spawns the
orchestrator against append-mode capture files. Sub-spec 71.a.8.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import IO, Protocol

from pydantic import BaseModel, ConfigDict

from src.agents.slo_agent.orchestrator.spawn_env import (
    build_headless_child_env,
    open_capture_file_append,
)
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO

__all__ = ["RelaunchOutcomeDAO", "WorkflowRelauncher"]


class _ProcessLike(Protocol):
    """Minimal subprocess result surface used by the relauncher."""

    pid: int


class RelaunchOutcomeDAO(BaseModel):
    """Result of one detached-workflow relaunch attempt."""

    model_config = ConfigDict(frozen=True)

    pid: int | None = None
    error: str | None = None


class WorkflowRelauncher:
    """Spawn a resumed orchestrator for one terminal workflow handle."""

    @classmethod
    async def invoke(cls, *, handle: WorkflowHandleDAO, history_root: Path) -> RelaunchOutcomeDAO:
        """Spawn a fresh process that resumes the handle's orchestrator session.

        WHAT: Opens the existing orchestrator captures for append and starts the
            same workflow with its durable history reference.
        WHO: WorkflowCommandService.resume calls this after it validates a dead handle.
        WHEN: Once for each operator-requested workflow relaunch.

        Args:
            handle (WorkflowHandleDAO): Terminal handle carrying workflow identity and brief.
            history_root (Path): Root directory containing orchestrator captures.

        Returns:
            RelaunchOutcomeDAO: New pid on success or safe error text on failure.
        """
        with contextlib.ExitStack() as capture_files:
            try:
                stdout_file: IO[bytes] = capture_files.enter_context(
                    open_capture_file_append(
                        history_root=history_root,
                        session_id=handle.orchestrator_session_id,
                        name="stdout.jsonl",
                    )
                )
                stderr_file: IO[bytes] = capture_files.enter_context(
                    open_capture_file_append(
                        history_root=history_root,
                        session_id=handle.orchestrator_session_id,
                        name="stderr.log",
                    )
                )
                process: _ProcessLike = await asyncio.create_subprocess_exec(
                    *cls._build_argv(handle=handle),
                    start_new_session=True,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=build_headless_child_env(workflow_id=handle.workflow_id),
                )
            except OSError as exc:
                return RelaunchOutcomeDAO(error=f"workflow resume failed: {exc}")
        return RelaunchOutcomeDAO(pid=process.pid)

    @staticmethod
    def _build_argv(*, handle: WorkflowHandleDAO) -> list[str]:
        """Build a resumed orchestrator argv from the durable workflow handle.

        WHAT: Keeps the original brief, owner notification target, and working
            directory while using --resume instead of --session-id.
        WHO: WorkflowRelauncher.invoke passes this argv to the subprocess API.
        WHEN: Immediately before a resumed orchestrator is spawned.

        Args:
            handle (WorkflowHandleDAO): Handle carrying the original launch inputs.

        Returns:
            list[str]: Argument vector for the resumed headless orchestrator.
        """
        return [
            sys.executable,
            "-m",
            "src.cli",
            "run",
            "--orchestrator",
            "--json",
            "--enable-history",
            "-p",
            handle.brief,
            "--resume",
            handle.orchestrator_session_id,
            "--notify-session",
            handle.owner_session_id,
            "--cwd",
            handle.cwd,
        ]
