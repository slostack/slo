"""WorkflowRelauncher — resume a dead detached workflow in place.

Builds a resume command from one durable workflow handle, then spawns the
orchestrator against append-mode capture files. Sub-spec 71.a.8.
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, IO, Optional, Protocol

from pydantic import BaseModel, ConfigDict

from src.agents.slo_agent.orchestrator.capture_writer import WorkflowCaptureCompletionContext
from src.agents.slo_agent.orchestrator.spawn_env import (
    AgentLaunchPolicy,
    open_capture_file_append,
)
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO

__all__ = ["RelaunchOutcomeDAO", "WorkflowRelauncher"]


class _ProcessLike(Protocol):
    """Minimal subprocess result surface used by the relauncher."""

    pid: int


class RelaunchSpawn(Protocol):
    """Process creation boundary; capture ownership stays with the relauncher."""

    async def __call__(
        self,
        *argv: str,
        start_new_session: bool,
        stdout: IO[bytes],
        stderr: IO[bytes],
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Create a workload with the supplied command and owned capture endpoints."""
        ...


class RelaunchOutcomeDAO(BaseModel):
    """Result of one detached-workflow relaunch attempt."""

    model_config = ConfigDict(frozen=True)

    pid: int | None = None
    error: str | None = None
    warning: str | None = None


class _RelaunchCaptureOwnership:
    """Private relaunch capture endpoints retained until command-owned durable adoption."""

    def __init__(
        self,
        *,
        process: _ProcessLike,
        capture_files: contextlib.ExitStack,
        capture_endpoints: list[IO[bytes]],
    ) -> None:
        """Bind a workload process and explicit private capture lifetime."""
        self.process = process
        self._capture_files = capture_files
        self._capture_endpoints = capture_endpoints

    def activate(self, *, expected_pid: int) -> Awaitable[None] | None:
        """Forward durable adoption to every private capture endpoint.

        Args:
            expected_pid (int): Durable workload identity being adopted.

        Returns:
            Awaitable[None] | None: Optional endpoint activation completion.
        """
        for endpoint in self._capture_endpoints:
            activate = getattr(endpoint, "activate", None)
            if activate is not None:
                activate(expected_pid=expected_pid)
        return None

    async def close(self) -> None:
        """Close private endpoints off the async caller loop."""
        await asyncio.to_thread(self._capture_files.close)


class WorkflowRelauncher:
    """Spawn a resumed orchestrator for one terminal workflow handle."""

    @classmethod
    @asynccontextmanager
    async def spawn_for_adoption(
        cls,
        *,
        handle: WorkflowHandleDAO,
        history_root: Path,
        spawn: Optional[RelaunchSpawn] = None,
    ) -> AsyncIterator[_RelaunchCaptureOwnership]:
        """Yield a workload with capture lifetime retained until command-owned adoption.

        Args:
            handle (WorkflowHandleDAO): Original workflow identity and resume inputs.
            history_root (Path): Existing capture root.
            spawn (Optional[RelaunchSpawn]): Process boundary override; defaults to asyncio.

        Yields:
            _RelaunchCaptureOwnership: Workload and endpoints closed on context exit.
        """
        launch_policy = AgentLaunchPolicy()
        child_env = launch_policy.build_environment(workflow_id=handle.workflow_id)
        capture_files = contextlib.ExitStack()
        try:
            stdout_file = await cls._open_capture_for_adoption(
                history_root=history_root,
                handle=handle,
                name="stdout.jsonl",
                credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                capture_files=capture_files,
            )
            stderr_file = await cls._open_capture_for_adoption(
                history_root=history_root,
                handle=handle,
                name="stderr.log",
                credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                capture_files=capture_files,
            )
            process = await (spawn or asyncio.create_subprocess_exec)(
                *cls._build_argv(handle=handle, launch_policy=launch_policy),
                start_new_session=True,
                stdout=stdout_file,
                stderr=stderr_file,
                env=child_env,
            )
            yield _RelaunchCaptureOwnership(
                process=process,
                capture_files=capture_files,
                capture_endpoints=[stdout_file, stderr_file],
            )
        finally:
            await asyncio.to_thread(capture_files.close)

    @classmethod
    async def _open_capture_for_adoption(
        cls,
        *,
        history_root: Path,
        handle: WorkflowHandleDAO,
        name: str,
        credential: str,
        capture_files: contextlib.ExitStack,
    ) -> IO[bytes]:
        """Await one off-loop opener and retain late success until it is closed.

        WHAT: Makes cancellation wait for the worker's eventual result so a
            successful late capture endpoint is always closed before cancellation
            propagates to the resume command.
        WHO: ``spawn_for_adoption`` calls this once for stdout and once for stderr.
        WHEN: Before the replacement workload can be spawned.

        Args:
            history_root (Path): Root containing capture directories.
            handle (WorkflowHandleDAO): Reserved workflow identity.
            name (str): Capture filename.
            credential (str): Writer-only credential.
            capture_files (contextlib.ExitStack): Lifetime owner for adopted endpoints.

        Returns:
            IO[bytes]: Open endpoint registered in ``capture_files``.
        """
        opener: asyncio.Task[IO[bytes]] = asyncio.create_task(
            asyncio.to_thread(
                cls._open_capture_file,
                history_root=history_root,
                handle=handle,
                name=name,
                credential=credential,
            )
        )
        try:
            endpoint: IO[bytes] = await asyncio.shield(opener)
        except asyncio.CancelledError:
            await cls._await_late_capture_cleanup(opener=opener)
            raise
        except BaseException:
            await cls._close_late_capture_result(opener=opener)
            raise
        capture_files.enter_context(endpoint)
        return endpoint

    @staticmethod
    async def _await_late_capture_cleanup(*, opener: asyncio.Task[IO[bytes]]) -> None:
        """Finish late endpoint cleanup under a fresh task cancellation budget.

        Args:
            opener (asyncio.Task[IO[bytes]]): Off-loop opener retained by the
                cancelled caller until its result can be closed.
        """
        current_task = asyncio.current_task()
        if current_task is not None and hasattr(current_task, "uncancel"):
            current_task.uncancel()
        await asyncio.shield(WorkflowRelauncher._close_late_capture_result(opener=opener))

    @staticmethod
    async def _close_late_capture_result(*, opener: asyncio.Task[IO[bytes]]) -> None:
        """Await an off-loop opener after cancellation and close a late endpoint.

        Args:
            opener (asyncio.Task[IO[bytes]]): Worker task that may return one
                fully initialized capture pipe after its original await was cancelled.
        """
        try:
            endpoint: IO[bytes] = await opener
        except (asyncio.CancelledError, OSError):
            return
        await asyncio.to_thread(endpoint.close)

    @staticmethod
    def _open_capture_file(
        *,
        history_root: Path,
        handle: WorkflowHandleDAO,
        name: str,
        credential: str,
    ) -> IO[bytes]:
        """Open one append capture outside the event loop.

        WHAT: Runs bounded sibling-lease acquisition and writer readiness in a
            worker thread, allowing cancellation of the awaiting relaunch task.
        WHO: ``spawn_for_adoption`` uses this private helper for each capture.
        WHEN: Before a replacement workload can be spawned or adopted.

        Args:
            history_root (Path): Root containing the workflow capture directory.
            handle (WorkflowHandleDAO): Durable workflow identity for reporting.
            name (str): Capture filename to open.
            credential (str): Captured credential used solely by the redacting writer.

        Returns:
            IO[bytes]: Child-facing capture endpoint after writer readiness.
        """
        return open_capture_file_append(
            history_root=history_root,
            session_id=handle.orchestrator_session_id,
            name=name,
            credential=credential,
            completion_context=WorkflowCaptureCompletionContext(
                history_root=history_root,
                owner_session_id=handle.owner_session_id,
                workflow_id=handle.workflow_id,
                expected_pid=0,
            ),
        )

    @classmethod
    async def invoke(
        cls,
        *,
        handle: WorkflowHandleDAO,
        history_root: Path,
        completion_context: Optional[WorkflowCaptureCompletionContext] = None,
        spawn: Optional[RelaunchSpawn] = None,
    ) -> RelaunchOutcomeDAO:
        """Spawn a fresh process that resumes the handle's orchestrator session.

        WHAT: Opens the existing orchestrator captures for append and starts the
            same workflow with its durable history reference.
        WHO: WorkflowCommandService.resume calls this after it validates a dead handle.
        WHEN: Once for each operator-requested workflow relaunch.

        Args:
            handle (WorkflowHandleDAO): Terminal handle carrying workflow identity and brief.
            history_root (Path): Root directory containing orchestrator captures.
            completion_context (Optional[WorkflowCaptureCompletionContext]): Private
                adoption identity supplied after the resume reservation.
            spawn (Optional[RelaunchSpawn]): Process boundary override; defaults to asyncio.

        Returns:
            RelaunchOutcomeDAO: New pid on success or safe error text on failure.
        """
        launch_policy = AgentLaunchPolicy()
        child_env = launch_policy.build_environment(workflow_id=handle.workflow_id)
        process: _ProcessLike | None = None
        try:
            capture_files = contextlib.ExitStack()
            try:
                stdout_file: IO[bytes] = capture_files.enter_context(
                    open_capture_file_append(
                        history_root=history_root,
                        session_id=handle.orchestrator_session_id,
                        name="stdout.jsonl",
                        credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                        completion_context=completion_context,
                    )
                )
                stderr_file: IO[bytes] = capture_files.enter_context(
                    open_capture_file_append(
                        history_root=history_root,
                        session_id=handle.orchestrator_session_id,
                        name="stderr.log",
                        credential=child_env.get("SLO_OPENROUTER_API_KEY", ""),
                        completion_context=completion_context,
                    )
                )
                process = await (spawn or asyncio.create_subprocess_exec)(
                    *cls._build_argv(handle=handle, launch_policy=launch_policy),
                    start_new_session=True,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=child_env,
                )
            finally:
                # Writer drain waits must not stall the parent event loop.
                await asyncio.to_thread(capture_files.close)
        except OSError:
            if process is None:
                return RelaunchOutcomeDAO(error="workflow resume failed")
            return RelaunchOutcomeDAO(pid=process.pid, warning="capture writer failed")
        return RelaunchOutcomeDAO(pid=process.pid)

    @staticmethod
    def _build_argv(
        *, handle: WorkflowHandleDAO, launch_policy: Optional[AgentLaunchPolicy] = None
    ) -> list[str]:
        """Build a resumed orchestrator argv from the durable workflow handle.

        WHAT: Keeps the original brief, owner notification target, and working
            directory while using --resume instead of --session-id. The shared
            policy owns default isolation and explicit development imports.
        WHO: WorkflowRelauncher.invoke passes this argv to the subprocess API.
        WHEN: Immediately before a resumed orchestrator is spawned.

        Args:
            handle (WorkflowHandleDAO): Handle carrying the original launch inputs.
            launch_policy (Optional[AgentLaunchPolicy]): Snapshot paired with child env.

        Returns:
            list[str]: Argument vector for the resumed headless orchestrator.
        """
        arguments: list[str] = [
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
        return (launch_policy or AgentLaunchPolicy()).build_argv(arguments=arguments)
