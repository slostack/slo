"""Real host graph lifecycle with parked MCP callbacks and local filesystem tools."""

import asyncio
from pathlib import Path

import pytest

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.dao import SloBridgeSessionOptionsDAO
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
from tests.bridges.claude.test_lifecycle import ready_status
from tests.cli.test_claude_bridge import ScriptedClaudeTransport


async def test_unfinished_host_stream_close_retires_native_owner(tmp_path: Path) -> None:
    """Closing after a text delta, before completion, is abandonment not a tool boundary."""
    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=ready_status
    )
    bridge = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=adapter)
    bridge.bind_tools([])
    bridge.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="s", working_directory=tmp_path, instructions="host"
        )
    )
    from langchain_core.messages import HumanMessage

    stream = bridge._astream(messages=[HumanMessage(content="hello")])
    try:
        async with asyncio.timeout(3):
            assert (await anext(stream)).message.content == "Hello "
            await stream.aclose()
        runtime = adapter._runtime
        assert runtime._owner is not None and runtime._tool_bridge is not None
        assert transport.closed and runtime._owner.done()
        assert not runtime._tool_bridge.pending_calls
    finally:
        transport.release_terminal.set()
        await bridge.close()
