"""Transport acquisition/cleanup failure contracts at its process factory seam."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from src.bridges.claude.sdk.native_transport import ClaudeNativeTransport


async def test_failed_kill_retains_process_until_explicit_retry(tmp_path: Path) -> None:
    """Refused kill cannot clear ownership or permit reconnect."""

    class RefusingProcess:
        """Minimal process seam whose kill initially fails."""

        returncode: int | None = None
        stdin = None
        stdout = None
        refuse = True

        async def wait(self) -> int:
            """Never claim reap while alive."""
            if self.returncode is None:
                await asyncio.Event().wait()
            assert self.returncode is not None
            return self.returncode

        def kill(self) -> None:
            """Refuse once, then acknowledge direct-child termination."""
            if self.refuse:
                raise PermissionError("synthetic kill refusal")
            self.returncode = -9

    process = RefusingProcess()

    async def spawn(*args: str, **kwargs: Any) -> Any:
        """Return the owned lifecycle stub via the actual factory seam."""
        return process

    transport = ClaudeNativeTransport(
        options=ClaudeAgentOptions(cli_path="/not-executed", cwd=tmp_path),
        process_factory=spawn,
        grace_seconds=0.01,
        force_seconds=0.01,
    )
    await transport.connect()
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await transport.close()
    assert not transport.is_ready()
    with pytest.raises(RuntimeError, match="reconnect"):
        await transport.connect()
    process.refuse = False
    await transport.close()
    assert process.returncode == -9
    await transport.close()


async def test_failed_process_start_can_close_without_replaying_start(tmp_path: Path) -> None:
    """A factory refusal has no child, but remains explicitly closeable."""
    attempts = []

    async def refuse(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Fail before acquisition and never launch a process."""
        attempts.append(args)
        raise OSError("synthetic spawn failure")

    transport = ClaudeNativeTransport(
        options=ClaudeAgentOptions(cli_path="/not-executed", cwd=tmp_path), process_factory=refuse
    )
    with pytest.raises(OSError):
        await transport.connect()
    await transport.close()
    await transport.close()
    assert len(attempts) == 1 and not transport.is_ready()


async def test_cancelled_acquisition_retains_and_reaps_created_child(tmp_path: Path) -> None:
    """Cancellation while a factory is returning a child cannot lose the acquired handle."""
    import sys

    entered, release = asyncio.Event(), asyncio.Event()
    children: list[asyncio.subprocess.Process] = []

    async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Hold the process-return boundary after actual child creation."""
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)", **kwargs
        )
        children.append(child)
        entered.set()
        await release.wait()
        return child

    transport = ClaudeNativeTransport(
        options=ClaudeAgentOptions(cli_path="/not-executed", cwd=tmp_path),
        process_factory=spawn,
        grace_seconds=0.01,
        force_seconds=1,
    )
    connecting = asyncio.create_task(coro=transport.connect())
    try:
        await entered.wait()
        connecting.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await connecting
        await transport.close()
        assert children[0].returncode is not None, "acquired process escaped transport ownership"
    finally:
        release.set()
        await transport.force_close()
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()
