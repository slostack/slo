"""Deterministic native admission races at the external authentication boundary."""

import asyncio
from pathlib import Path

import pytest

from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
)
from tests.cli.test_claude_bridge import ScriptedClaudeTransport


@pytest.mark.parametrize("close_session", [False, True])
async def test_close_during_session_auth_prevents_late_configuration(
    tmp_path: Path, close_session: bool,
) -> None:
    """Closing either lifetime while authentication waits forbids later native start."""
    entered = asyncio.Event()
    release = asyncio.Event()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Hold the external check until the test has closed admission."""
        entered.set()
        await release.wait()
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="ready")

    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=status,
    )
    task = asyncio.create_task(coro=adapter.start_session(session_options=ClaudeSessionOptionsDAO(
        session_id="host", model_id="claude-bridge:claude-haiku-5-5",
        working_directory=tmp_path, instructions="host",
    )))
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            if close_session:
                await adapter.close_session()
            else:
                await adapter.close()
            release.set()
            with pytest.raises(RuntimeError, match="closed|closure|changed"):
                await task
        assert not transport.connected
        assert transport.prompts == []
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()


@pytest.mark.parametrize("closure", ["none", "session", "adapter"])
async def test_invocation_reserves_admission_across_authentication(
    tmp_path: Path, closure: str,
) -> None:
    """A competing invoke fails immediately; session close prevents the reserved start."""
    entered = asyncio.Event()
    release = asyncio.Event()
    checks = 0

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Block only invocation authentication, after session setup completed."""
        nonlocal checks
        checks += 1
        if checks > 1:
            entered.set()
            await release.wait()
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="ready")

    transport = ScriptedClaudeTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=status,
    )
    await adapter.start_session(session_options=ClaudeSessionOptionsDAO(
        session_id="host", model_id="claude-bridge:claude-haiku-5-5",
        working_directory=tmp_path, instructions="host",
    ))
    task = asyncio.create_task(coro=adapter.invoke_agent(invocation_options=ClaudeInvocationOptionsDAO(
        invocation_id="one", text="first",
    )))
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            with pytest.raises(RuntimeError, match="admission|progress|conflict"):
                await adapter.invoke_agent(invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="two", text="must not send",
                ))
            if closure == "session":
                await adapter.close_session()
            if closure == "adapter":
                await adapter.close()
                assert adapter._authentication_task.done()
            release.set()
            if closure != "none":
                with pytest.raises(RuntimeError, match="closed|closure|changed"):
                    await task
            else:
                await task
                _ = [event async for event in adapter.read_response(invocation_id="one")]
        assert transport.prompts == (["first"] if closure == "none" else [])
        assert checks == 2
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await adapter.close()
