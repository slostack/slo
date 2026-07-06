"""``bash`` tool — cwd-bound shell with timeout + truncation + spill (sub-spec 01.d §4.4).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Description text is
lifted verbatim from pi ``bash.ts:279``.
"""
from __future__ import annotations

BASH_PROMPT_SNIPPET: str = (
    "run a bash command in the working directory with optional timeout "
    "(output is truncated)"
)

import asyncio
import os
import signal
import tempfile
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.cfg import cfg
from config.logger import log_error, log_info
from src.agents.tools._truncate import Truncator


__all__ = [
    "BashSchemaDAO",
    "BashTool",
    "bash_tool",
]


_DEFAULT_BASH_TIMEOUT_SECONDS: float = 600.0
"""Effective timeout applied when a bash call supplies no explicit timeout.

A command issued with ``timeout=None`` that orphans a long-lived descendant
would otherwise block until that descendant dies (potentially forever). This
conservative ceiling caps that risk while staying well under the agent stream
inactivity watchdog. Set ``SLO_BASH_DEFAULT_TIMEOUT_SECONDS=0`` to disable the
ceiling and restore the run-forever behaviour.
"""

_DEFAULT_BASH_TEARDOWN_GRACE_SECONDS: float = 5.0
"""Hard ceiling on the post-kill reap.

Even after a process-group SIGKILL, an exotic descendant could resist reaping;
this bounds how long the tool waits before returning regardless, so a single
bash call can never block the agent event loop beyond ``timeout + grace``.
"""


def _default_bash_timeout_seconds() -> Optional[float]:
    """Return the effective timeout to apply when a bash call passes no timeout.

    Reads ``SLO_BASH_DEFAULT_TIMEOUT_SECONDS``. A non-positive configured value
    disables the ceiling (returns ``None``), preserving the run-forever
    behaviour for operators who explicitly opt out.

    Returns:
        Optional[float]: Positive ceiling in seconds, or ``None`` when the
            ceiling is disabled (configured non-positive).
    """
    raw_value: object = cfg(key="SLO_BASH_DEFAULT_TIMEOUT_SECONDS")
    if raw_value is None:
        return _DEFAULT_BASH_TIMEOUT_SECONDS
    try:
        parsed: float = float(raw_value)  # type: ignore[arg-type]  # intentional broad coercion
    except (TypeError, ValueError):
        return _DEFAULT_BASH_TIMEOUT_SECONDS
    if parsed <= 0:
        return None
    return parsed


def _bash_teardown_grace_seconds() -> float:
    """Return the bounded post-kill reap window.

    Reads ``SLO_BASH_TEARDOWN_GRACE_SECONDS``. Invalid or non-positive values
    fall back to the built-in default — the grace window is never disableable,
    because an unbounded reap is the exact failure this guard removes.

    Returns:
        float: Seconds to wait for the killed process group to reap before the
            tool returns regardless.
    """
    raw_value: object = cfg(key="SLO_BASH_TEARDOWN_GRACE_SECONDS")
    if raw_value is None:
        return _DEFAULT_BASH_TEARDOWN_GRACE_SECONDS
    try:
        parsed: float = float(raw_value)  # type: ignore[arg-type]  # intentional broad coercion
    except (TypeError, ValueError):
        return _DEFAULT_BASH_TEARDOWN_GRACE_SECONDS
    if parsed <= 0:
        return _DEFAULT_BASH_TEARDOWN_GRACE_SECONDS
    return parsed


class BashSchemaDAO(BaseModel):
    """LangChain args schema for the bash tool."""

    command: str = Field(description="Bash command to execute")
    timeout: Optional[float] = Field(
        default=None,
        description="Timeout in seconds (optional, no default timeout)",
    )

    model_config = ConfigDict(
        title="BashSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class BashTool:
    """Cwd-bound shell tool with process-group termination, timeout, and output spill."""

    @classmethod
    async def invoke(cls, command: str, timeout: Optional[float] = None) -> str:
        """Run ``command`` under ``/bin/bash -c`` in its own process group.

        Captures stdout and stderr interleaved. On timeout, the entire process
        group is SIGKILLed (shell plus every descendant) and reaped within a
        bounded grace window, so an orphaned child that holds the stdout pipe
        can never block the agent loop.

        Args:
            command (str): Shell command line, executed in the current working
                directory via ``/bin/bash -c``.
            timeout (Optional[float]): Seconds before the process group is
                killed. ``None`` resolves to the configured default ceiling
                (``SLO_BASH_DEFAULT_TIMEOUT_SECONDS``); a disabled ceiling means
                no timeout.

        Returns:
            str: ``"exit_code: <code>\\n<output>"`` (possibly tail-truncated with
                a spill footer), or ``"Error: ..."`` on spawn or timeout failure.
        """
        effective_timeout: Optional[float] = cls._resolve_effective_timeout(timeout=timeout)
        try:
            try:
                process: asyncio.subprocess.Process = await cls._spawn(command=command)
            except OSError as exc:
                return f"Error: failed to spawn shell: {exc}"

            try:
                stdout_bytes: bytes = await cls._communicate_with_timeout(
                    process=process,
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                await cls._terminate_process_group(process=process)
                return f"Error: command exceeded {effective_timeout}s timeout"

            return cls._format_result(process=process, stdout_bytes=stdout_bytes)
        except Exception as exc:  # noqa: BLE001 — surface to model, never raise into the graph
            log_error(msg=f"BashTool failed for command: {command[:80]!r}", e=exc, stack_trace=False)
            return f"Error: bash failed: {exc}"

    @classmethod
    def _resolve_effective_timeout(cls, *, timeout: Optional[float]) -> Optional[float]:
        """Return the timeout to enforce: the caller's value, or the default ceiling.

        Called by ``invoke`` before spawning. A caller-supplied timeout always
        wins; only ``None`` falls back to the configured default ceiling.

        Args:
            timeout (Optional[float]): Caller-supplied timeout, or ``None``.

        Returns:
            Optional[float]: Effective timeout in seconds, or ``None`` when no
                ceiling applies.
        """
        if timeout is not None:
            return timeout
        return _default_bash_timeout_seconds()

    @classmethod
    async def _spawn(cls, *, command: str) -> asyncio.subprocess.Process:
        """Spawn ``command`` under ``/bin/bash -c`` in a fresh process group.

        ``start_new_session=True`` (POSIX ``setsid``) gives the shell and all of
        its descendants a distinct process-group id, which
        ``_terminate_process_group`` later signals as a unit. Called once by
        ``invoke``.

        Args:
            command (str): Shell command line to execute.

        Returns:
            asyncio.subprocess.Process: The spawned shell process.

        Raises:
            OSError: If the shell cannot be spawned.
        """
        return await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
            executable="/bin/bash",
            start_new_session=True,
        )

    @classmethod
    async def _communicate_with_timeout(
        cls,
        *,
        process: asyncio.subprocess.Process,
        timeout: Optional[float],
    ) -> bytes:
        """Read the process to completion, optionally under a timeout.

        Called by ``invoke``. When ``timeout`` is ``None`` the read runs
        unbounded (the opt-out escape hatch); otherwise it is wrapped in
        ``asyncio.wait_for`` and raises ``asyncio.TimeoutError`` on overrun.

        Args:
            process (asyncio.subprocess.Process): The spawned shell process.
            timeout (Optional[float]): Seconds before raising, or ``None``.

        Returns:
            bytes: The interleaved stdout/stderr bytes.

        Raises:
            asyncio.TimeoutError: When the command overruns ``timeout``.
        """
        if timeout is None:
            stdout_bytes, _ = await process.communicate()
            return stdout_bytes
        stdout_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return stdout_bytes

    @classmethod
    async def _terminate_process_group(cls, *, process: asyncio.subprocess.Process) -> None:
        """SIGKILL the whole process group, then reap within a bounded window.

        Sends SIGKILL to the negative pgid so the shell AND every descendant die
        and release the inherited stdout pipe — without this, ``process.wait()``
        blocks until the pipe reaches EOF, which a lingering descendant can defer
        indefinitely. The reap is bounded so even an unkillable descendant cannot
        hang the tool. Called by ``invoke`` when a command overruns its timeout.

        Args:
            process (asyncio.subprocess.Process): The process group leader.
        """
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            # Group already exited between the timeout firing and the kill.
            pass

        grace_seconds: float = _bash_teardown_grace_seconds()
        try:
            await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        except asyncio.TimeoutError:
            log_error(
                msg="BashTool: process group did not reap within grace window",
                grace_seconds=grace_seconds,
                pid=process.pid,
                stack_trace=False,
            )

    @classmethod
    def _format_result(
        cls,
        *,
        process: asyncio.subprocess.Process,
        stdout_bytes: bytes,
    ) -> str:
        """Frame and truncate the command output.

        Called by ``invoke`` on the success path. Decodes the captured bytes,
        prepends the ``exit_code:`` line, then tail-truncates with a spill footer
        when the body exceeds the truncation budget.

        Args:
            process (asyncio.subprocess.Process): The completed process (for its
                return code).
            stdout_bytes (bytes): The interleaved stdout/stderr bytes.

        Returns:
            str: The framed, possibly-truncated output string.
        """
        raw: str = stdout_bytes.decode("utf-8", errors="replace")
        exit_code: int = process.returncode if process.returncode is not None else -1
        body: str = f"exit_code: {exit_code}\n{raw}"

        result = Truncator.tail(text=body)
        if not result.truncated:
            return result.text

        spill_path: str = cls._spill_to_tempfile(body=body)
        return result.text + f"\n\n[full output spilled to: {spill_path}]"

    @classmethod
    def _spill_to_tempfile(cls, *, body: str) -> str:
        """Write the full output to a temp file and return its path.

        Args:
            body (str): The full, untruncated output to persist.

        Returns:
            str: Absolute path to the spill file.
        """
        fd, temp_path = tempfile.mkstemp(prefix="slo-bash-", suffix=".txt", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        return temp_path


@tool(name_or_callable="bash", args_schema=BashSchemaDAO)
async def bash_tool(command: str, timeout: Optional[float] = None) -> str:
    """Execute a bash command in the current working directory. Returns stdout and stderr. Output is truncated to last 2000 lines or 64KB (whichever is hit first). If truncated, full output is saved to a temp file. Optionally provide a timeout in seconds.

    Args:
        command (str): Shell command to execute under ``/bin/bash -c``.
        timeout (Optional[float]): Seconds before the subprocess is killed.
            None means no timeout (matches pi default).

    Returns:
        str: ``"exit_code: <code>\\n<output>"`` (possibly truncated), or an
            error message on spawn / timeout failure.
    """
    log_info(msg=f"Using Bash Tool with command: {command[:80]!r}")
    return await BashTool.invoke(command=command, timeout=timeout)


if __name__ == "__main__":
    # Quick test harness: exercises BashTool against five scenarios.
    import asyncio as _asyncio

    async def main() -> None:
        # Scenario 1 — happy path with stdout.
        print("---[ scenario 1: echo ]---")
        print(await BashTool.invoke(command="echo hello from slo bash tool"))

        # Scenario 2 — non-zero exit code is surfaced.
        print("\n---[ scenario 2: non-zero exit (`false`) ]---")
        print(await BashTool.invoke(command="false"))

        # Scenario 3 — stderr interleaved with stdout.
        print("\n---[ scenario 3: stderr + stdout interleaved ]---")
        print(await BashTool.invoke(command="echo out; echo err >&2"))

        # Scenario 4 — timeout terminates a long-running command.
        print("\n---[ scenario 4: timeout (sleep 2 with timeout=0.1) ]---")
        print(await BashTool.invoke(command="sleep 2", timeout=0.1))

        # Scenario 5 — orphan holds the pipe; the process-group kill releases it.
        print("\n---[ scenario 5: orphan holds pipe, group kill (timeout=2) ]---")
        print(await BashTool.invoke(command="sleep 30 && echo done", timeout=2))

    _asyncio.run(main())
