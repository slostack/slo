"""Supported custom SDK transport with directly owned, bounded child cleanup."""

import asyncio
import json
import os
from pathlib import Path
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, Transport, __version__

from .exceptions import ClaudeBridgeError


class ClaudeNativeTransport(Transport):
    """Own native pipes/process, leaving protocol routing entirely to the SDK.

    Only the fixed read-only runtime option profile is encoded here. No SDK
    process fields or command-builder methods are read or patched. The custom
    Transport owns the child handle needed for forced termination and reap.
    """

    def __init__(
        self,
        *,
        options: ClaudeAgentOptions,
        process_factory: Callable[
            ..., Awaitable[asyncio.subprocess.Process]
        ] = asyncio.create_subprocess_exec,
        grace_seconds: float = 5,
        force_seconds: float = 5,
    ) -> None:
        """Retain inert options and an optional disposable process-launch seam."""
        self._options = options
        self._process_factory = process_factory
        self._grace_seconds = grace_seconds
        self._force_seconds = force_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._starting: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._closing = False
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Start one child using pinned SDK option encoding, never PATH resolution."""
        if self._process is not None or self._starting is not None or self._closing:
            raise RuntimeError("Claude transport cannot reconnect before closure.")
        command = self._build_command()
        environment = {key: value for key, value in os.environ.items() if key != "CLAUDECODE"}
        environment.update(self._options.env)
        environment["CLAUDE_CODE_ENTRYPOINT"] = "sdk-py"
        environment["CLAUDE_CODE_SDK_READS_SESSION_STATE"] = "1"
        environment["CLAUDE_AGENT_SDK_VERSION"] = __version__
        self._starting = asyncio.create_task(
            coro=self._start_process(command=command, environment=environment)
        )
        self._process = await asyncio.shield(self._starting)
        self._starting = None

    async def _start_process(
        self, *, command: list[str], environment: dict[str, str]
    ) -> asyncio.subprocess.Process:
        """Acquire the child in the task retained by connect and joined during cleanup.

        Adapt the factory's general awaitable to create_task's coroutine contract;
        cancellation of the connect caller must not discard the acquisition.

        Args:
            command (list[str]): Validated absolute executable and fixed SDK arguments.
            environment (dict[str, str]): Native environment assembled by connect.

        Returns:
            asyncio.subprocess.Process: Child whose pipes and reap remain transport-owned.

        Raises:
            OSError: The injected factory cannot acquire a process.
        """
        return await self._process_factory(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self._options.cwd,
            env=environment,
            limit=32 * 1024 * 1024,
        )

    def _build_command(self) -> list[str]:
        """Encode the bridge's fixed supported CLI profile, not arbitrary SDK options."""
        options = self._options
        if not options.cli_path or not Path(options.cli_path).is_absolute():
            raise ValueError("Claude transport requires an absolute executable.")
        command = [
            str(options.cli_path),
            "--output-format",
            "stream-json",
            "--verbose",
            "--input-format",
            "stream-json",
            "--include-partial-messages",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources=",
        ]
        if options.model:
            command.extend(["--model", options.model])
        if isinstance(options.system_prompt, dict):
            append = options.system_prompt.get("append")
            if isinstance(append, str):
                command.extend(["--append-system-prompt", append])
        if options.allowed_tools:
            command.extend(["--allowedTools", ",".join(options.allowed_tools)])
        if isinstance(options.mcp_servers, dict) and options.mcp_servers:
            servers = {
                name: {key: value for key, value in config.items() if key != "instance"}
                for name, config in options.mcp_servers.items()
                if isinstance(config, dict)
            }
            command.extend(["--mcp-config", json.dumps({"mcpServers": servers})])
        if options.resume:
            command.append(f"--resume={options.resume}")
        if options.effort is not None:
            command.extend(["--effort", options.effort, "--thinking", "adaptive"])
        else:
            command.extend(["--thinking", "disabled"])
        return command

    async def write(self, data: str) -> None:
        """Serialize wire writes; sealed transports never admit another receipt."""
        async with self._write_lock:
            if not self.is_ready() or self._process is None or self._process.stdin is None:
                raise RuntimeError("Claude transport is closed.")
            self._process.stdin.write(data.encode())
            await self._process.stdin.drain()

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Decode bounded newline frames without interpreting SDK control messages."""
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Claude transport is not connected.")
        while line := await self._process.stdout.readline():
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Claude wire frame is not an object.")
            yield message

    async def end_input(self) -> None:
        """Send EOF without waiting behind an undrained pipe."""
        if self._process is not None and self._process.stdin is not None:
            self._process.stdin.close()

    def is_ready(self) -> bool:
        """Report readiness only while the owned child is live and admission open."""
        return not self._closing and self._process is not None and self._process.returncode is None

    async def _claim_starting_process(self) -> None:
        """Recover a pending acquisition without cancelling or forgetting its handle."""
        if self._starting is None:
            return
        try:
            async with asyncio.timeout(self._force_seconds):
                self._process = await asyncio.shield(self._starting)
        except TimeoutError:
            raise ClaudeBridgeError(
                code="cleanup_failed", safe_message="Claude process acquisition is unconfirmed."
            ) from None
        except Exception:
            # A completed factory failure acquired no handle. The original
            # connect caller observes that failure; cleanup must retire it.
            self._starting = None
            return
        self._starting = None

    async def close(self) -> None:
        """Allow five seconds after EOF, then kill/reap within five more seconds."""
        self._closing = True
        await self._claim_starting_process()
        await self.end_input()
        if self._process is None:
            return
        try:
            async with asyncio.timeout(self._grace_seconds):
                await self._wait_reaped()
        except TimeoutError:
            await self.force_close()
        self._process = None
        self._closing = False

    async def _wait_reaped(self) -> None:
        """Drain abandoned stdout so a full pipe cannot prevent asyncio child reap."""
        assert self._process is not None
        drain = asyncio.create_task(coro=self._discard_output())
        try:
            await self._process.wait()
        finally:
            drain.cancel()
            await asyncio.gather(drain, return_exceptions=True)

    async def _discard_output(self) -> None:
        """Discard bounded chunks only after the SDK receive task has retired."""
        assert self._process is not None
        if self._process.stdout is not None:
            while await self._process.stdout.read(65536):
                pass

    async def force_close(self) -> None:
        """Kill only the directly owned child and confirm reap; retain failed ownership."""
        self._closing = True
        await self._claim_starting_process()
        if self._process is None:
            return
        try:
            if self._process.returncode is None:
                self._process.kill()
            async with asyncio.timeout(self._force_seconds):
                await self._wait_reaped()
        except (OSError, TimeoutError):
            raise ClaudeBridgeError(
                code="cleanup_failed", safe_message="Claude native process closure is unconfirmed."
            ) from None
        self._process = None
        self._closing = False
