"""Headless child-process runner for scheduled fires."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from src.scheduling.dao import FireStatus, ScheduleDefinitionDAO
from src.scheduling.os.executable_locator import ScheduleExecutableLocator
from src.scheduling.runtime.dao import ScheduleSubprocessResultDAO

__all__ = ["ScheduleSubprocessRunner"]


class ScheduleSubprocessRunner:
    """Launch the headless CLI path for fresh and resume deliveries."""

    async def run_fresh(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        explicit_session_id: Optional[str] = None,
        enable_history: bool = False,
    ) -> ScheduleSubprocessResultDAO:
        """Execute a fresh headless run.

        Args:
            definition (ScheduleDefinitionDAO): Schedule definition to run.
            explicit_session_id (Optional[str]): Optional seeded session id.
            enable_history (bool): Whether to persist history for this run.

        Returns:
            ScheduleSubprocessResultDAO: Normalized child-process result.
        """
        argv: list[str] = self._base_argv(definition=definition)
        if enable_history:
            argv.append("--enable-history")
        if explicit_session_id is not None:
            argv.extend(["--session-id", explicit_session_id])
        return await self._run_subprocess(
            argv=argv,
            session_id=explicit_session_id,
            cwd=definition.cwd,
        )

    async def run_resume(
        self,
        *,
        definition: ScheduleDefinitionDAO,
        session_reference: str,
        target_session_id: Optional[str],
    ) -> ScheduleSubprocessResultDAO:
        """Resume an existing session through the headless CLI path.

        Args:
            definition (ScheduleDefinitionDAO): Schedule definition to run.
            session_reference (str): Existing session reference.
            target_session_id (Optional[str]): Canonical target session id, when known.

        Returns:
            ScheduleSubprocessResultDAO: Normalized child-process result.
        """
        argv: list[str] = self._base_argv(definition=definition)
        argv.extend(["--resume", session_reference])
        return await self._run_subprocess(
            argv=argv,
            session_id=target_session_id,
            cwd=definition.cwd,
        )

    def _base_argv(self, *, definition: ScheduleDefinitionDAO) -> list[str]:
        """Build the shared CLI argv prefix for one scheduled run.

        Args:
            definition (ScheduleDefinitionDAO): Schedule definition to project to CLI flags.

        Returns:
            list[str]: Base argv for ``slo run``.
        """
        executable: Path = ScheduleExecutableLocator.locate()
        argv: list[str] = [
            str(executable),
            "run",
            "--prompt",
            definition.prompt,
            "--json",
        ]
        if definition.cwd is not None:
            argv.extend(["--cwd", definition.cwd])
        if definition.model is not None:
            argv.extend(["--model", definition.model])
        return argv

    async def _run_subprocess(
        self,
        *,
        argv: list[str],
        session_id: Optional[str],
        cwd: Optional[str] = None,
    ) -> ScheduleSubprocessResultDAO:
        """Spawn the child process and normalize the result.

        Args:
            argv (list[str]): Child-process argv.
            session_id (Optional[str]): Session id expected from this run.

        Returns:
            ScheduleSubprocessResultDAO: Normalized child-process result.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(cwd).expanduser().resolve()) if cwd is not None else str(Path.cwd()),
        )
        stdout_bytes, stderr_bytes = await process.communicate()
        exit_code: int = process.returncode if process.returncode is not None else 1
        stdout_text: str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text: str = stderr_bytes.decode("utf-8", errors="replace")
        return ScheduleSubprocessResultDAO(
            status=self._status_from_exit_code(exit_code=exit_code),
            exit_code=exit_code,
            session_id=session_id,
            summary=self._summary_from_stdout(stdout_text=stdout_text),
            stdout_summary=self._clip_text(text=stdout_text),
            stderr_summary=self._clip_text(text=stderr_text),
        )

    @staticmethod
    def _status_from_exit_code(*, exit_code: int) -> FireStatus:
        """Map a child exit code to the canonical fire status.

        Args:
            exit_code (int): Child-process exit code.

        Returns:
            FireStatus: Canonical fire status.
        """
        if exit_code == 0:
            return "completed"
        if exit_code == 2:
            return "aborted"
        return "failed"

    @classmethod
    def _summary_from_stdout(cls, *, stdout_text: str) -> str:
        """Extract a short high-level summary from stdout.

        Args:
            stdout_text (str): Full stdout text.

        Returns:
            str: Clipped last non-empty line.
        """
        lines: list[str] = [line.strip() for line in stdout_text.splitlines() if line.strip()]
        if not lines:
            return ""
        return cls._clip_text(text=lines[-1], limit=200)

    @staticmethod
    def _clip_text(*, text: str, limit: int = 500) -> str:
        """Return a clipped single-string summary.

        Args:
            text (str): Text to clip.
            limit (int): Maximum output length.

        Returns:
            str: Clipped text.
        """
        stripped: str = text.strip()
        if len(stripped) <= limit:
            return stripped
        return stripped[: limit - 3] + "..."
