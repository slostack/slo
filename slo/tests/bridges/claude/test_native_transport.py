"""Synthetic process wire evidence for the production custom SDK Transport."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, Transport, create_sdk_mcp_server

from src.bridges.claude.sdk.native_transport import ClaudeNativeTransport
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from src.bridges.claude.sdk.dao import (
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
    ClaudeTextDAO,
)
from src.bridges.claude.sdk.events import ClaudeResponseCompletedDAO

# Reuse the existing vendor script in a disposable child, not another implementation
# of SDK control routing. This child never invokes Claude or reads an account.
WIRE_CHILD = """
import asyncio, json, sys
from pathlib import Path
from tests.cli.test_claude_bridge import ToolRoundTransport
async def main():
    transport = ToolRoundTransport(path=Path("synthetic.txt"))
    transport.initialized_tools = ["mcp__slo__read"]
    async def output():
        async for message in transport.read_messages():
            print(json.dumps(message), flush=True)
    writer = asyncio.create_task(output())
    while line := await asyncio.to_thread(sys.stdin.readline):
        await transport.write(line)
    writer.cancel()
    await asyncio.gather(writer, return_exceptions=True)
asyncio.run(main())
"""


async def test_custom_transport_official_sdk_wire_and_profile(tmp_path: Path) -> None:
    """Official SDK initializes, queries, dispatches MCP, receives and reaps the real child."""
    options = ClaudeSDKRuntime._build_options(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s",
            model_id="claude-bridge:model",
            working_directory=tmp_path,
            instructions="trusted instructions",
            effort="high",
            tools=(
                ClaudeToolDefinitionDAO(name="read", description="Read", input_schema={"type": "object"}),
            ),
        )
    )
    options.cli_path = "/synthetic-not-executed"
    options.resume = "native-resume"
    options.mcp_servers = {"slo": create_sdk_mcp_server(name="slo")}
    spawned: list[asyncio.subprocess.Process] = []
    profiles: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Record actual production argv/env, replacing only the executable boundary."""
        profiles.append((args, kwargs))
        child = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c", WIRE_CHILD, **kwargs)
        spawned.append(child)
        return child

    transport = ClaudeNativeTransport(
        options=options, process_factory=spawn, grace_seconds=1, force_seconds=1
    )
    assert isinstance(transport, Transport)
    runtime = ClaudeSDKRuntime(transport=transport, cleanup_grace_seconds=1, cleanup_force_seconds=1)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="s",
            model_id="claude-bridge:model",
            working_directory=tmp_path,
            instructions="trusted instructions",
            tools=(
                ClaudeToolDefinitionDAO(name="read", description="Read", input_schema={"type": "object"}),
            ),
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="Read once"),
    )
    try:
        async with asyncio.timeout(8):
            events = [event async for event in runtime.read_response()]
            boundary = events[-1]
            assert isinstance(boundary, ClaudeResponseCompletedDAO)
            assert [call.tool_call_id for call in boundary.tool_calls] == ["exact-native-id"]
            await runtime.submit_tool_results(
                invocation_id="i",
                tool_result_batch=ClaudeToolResultBatchDAO(
                    response_id=boundary.response_id,
                    results=(
                        ClaudeToolResultDAO(
                            tool_call_id="exact-native-id",
                            content=(ClaudeTextDAO(text="child receipt"),),
                            is_error=False,
                        ),
                    ),
                ),
            )
            final = [event async for event in runtime.read_response()]
            assert isinstance(final[-1], ClaudeResponseCompletedDAO)
            assert final[-1].stop_reason == "stop"
            assert "".join(getattr(event, "text", "") for event in final) == "Hello bridge"
            await runtime.close()
        assert spawned[0].returncode == 0
        assert runtime._owner is not None and runtime._tool_bridge is not None
        assert runtime._owner.done() and not runtime._tool_bridge.pending_calls
        args, kwargs = profiles[0]
        assert args == (
            "/synthetic-not-executed",
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
            "--model",
            "model",
            "--append-system-prompt",
            "trusted instructions",
            "--allowedTools",
            "mcp__slo__read",
            "--mcp-config",
            json.dumps({"mcpServers": {"slo": {"type": "sdk", "name": "slo"}}}),
            "--resume=native-resume",
            "--effort",
            "high",
            "--thinking",
            "adaptive",
        )
        assert kwargs["cwd"] == tmp_path
        env = kwargs["env"]
        assert env["DISABLE_AUTO_COMPACT"] == "1" and env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "0"
        assert env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-py" and "CLAUDECODE" not in env
        assert not any(value in args for value in ("--bare", "--dangerously-skip-permissions", "--max-turns"))
    finally:
        await runtime.cancel()
        await transport.force_close()


@pytest.mark.parametrize("mode", ["invalid", "eof", "startup-cancel", "full-pipe"])
async def test_synthetic_process_failures_and_partial_start_are_reaped(tmp_path: Path, mode: str) -> None:
    """Malformed/EOF/startup cancellation and full abandoned stdout cannot leak the direct child."""
    scripts = {
        "invalid": "print('not-json', flush=True)",
        "eof": "pass",
        "startup-cancel": "import time; time.sleep(60)",
        "full-pipe": "import sys,time; sys.stdout.write('x'*4000000); sys.stdout.flush(); time.sleep(60)",
    }
    children: list[asyncio.subprocess.Process] = []

    async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
        """Launch only the disposable Python child with production pipe settings."""
        child = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c", scripts[mode], **kwargs)
        children.append(child)
        return child

    transport = ClaudeNativeTransport(
        options=ClaudeAgentOptions(cli_path="/not-executed", cwd=tmp_path),
        process_factory=spawn,
        grace_seconds=0.02,
        force_seconds=1,
    )
    runtime = None
    try:
        if mode == "startup-cancel":
            runtime = ClaudeSDKRuntime(
                transport=transport, cleanup_grace_seconds=0.05, cleanup_force_seconds=1
            )
            runtime.start(
                session_options=ClaudeSessionOptionsDAO(
                    session_id="s",
                    model_id="claude-bridge:model",
                    working_directory=tmp_path,
                    instructions="",
                ),
                invocation_options=ClaudeInvocationOptionsDAO(invocation_id="i", text="must not send"),
            )
            async with asyncio.timeout(3):
                while not children:
                    await asyncio.sleep(0.001)
                await runtime.cancel()
            assert runtime._owner is not None
            assert runtime._owner.done() and children[0].returncode is not None
            assert not runtime._query_attempted
            return
        await transport.connect()
        async with asyncio.timeout(3):
            if mode == "invalid":
                with pytest.raises(ValueError):
                    await anext(transport.read_messages())
            elif mode == "eof":
                assert [frame async for frame in transport.read_messages()] == []
            await transport.close()
        assert children[0].returncode is not None and not transport.is_ready()
    finally:
        if runtime is not None:
            await runtime.cancel()
        await transport.force_close()
