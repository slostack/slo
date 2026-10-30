"""Controlled child-process stand-in shared by orchestrator arbitration tests.

Replaces only the OS boundary returned by ``asyncio.create_subprocess_exec``; no
subprocess, signal or terminal is created.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = ["FakeChildProcess", "terminal_line"]


class FakeChildProcess:
    """Controlled stand-in for ``asyncio.subprocess.Process``.

    Stdout yields the given lines then EOF; ``wait`` blocks until ``exit`` is
    called, so a test decides exactly when the OS-level exit becomes visible.
    """

    def __init__(self, *, lines: list[bytes], exit_code: int = 0, pid: int = 4242) -> None:
        self.pid: int = pid
        self.returncode: Optional[int] = None
        self._exit_code: int = exit_code
        self._exited: asyncio.Event = asyncio.Event()
        pending: list[bytes] = list(lines)

        async def read_stdout() -> bytes:
            return pending.pop(0) if pending else b""

        self.stdout: MagicMock = MagicMock()
        self.stdout.readline = AsyncMock(side_effect=read_stdout)
        self.stderr: MagicMock = MagicMock()
        self.stderr.readline = AsyncMock(return_value=b"")

    def exit(self) -> None:
        """Make the child's exit observable to every waiter."""
        self.returncode = self._exit_code
        self._exited.set()

    async def wait(self) -> int:
        """Block until ``exit`` is called, then return the configured exit code."""
        await self._exited.wait()
        return self._exit_code


def terminal_line(*, content: str = "final answer") -> bytes:
    """Return one serialized ``run_completed`` stdout line."""
    return (AgentStreamEventDAO(kind="run_completed", content=content).model_dump_json() + "\n").encode(
        "utf-8"
    )
