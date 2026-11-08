"""Cancellation barriers at the official SDK transport boundary."""

import asyncio
from pathlib import Path

import pytest

from src.agents.tools.bundles import create_local_tools
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
)
from tests.bridges.claude.test_lifecycle import ready_status
from src.bridges.claude.sdk.events import ClaudeResponseCompletedDAO, ClaudeTextEventDAO
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from tests.cli.test_claude_bridge import ScriptedClaudeTransport

LOCAL_TOOL_NAMES: tuple[str, ...] = tuple(tool.name for tool in create_local_tools())


class BlockedStartupTransport(ScriptedClaudeTransport):
    """Block one SDK startup operation until supported owner cancellation."""

    def __init__(self, *, blocked_operation: str) -> None:
        """Record entry and close count without spawning native work."""
        super().__init__(block_response=True)
        self.blocked_operation = blocked_operation
        self.entered = asyncio.Event()
        self.close_calls = 0

    async def connect(self) -> None:
        """Block connect before SDK query creation when requested."""
        if self.blocked_operation == "connect":
            self.entered.set()
            await asyncio.Event().wait()
        await super().connect()

    async def write(self, data: str) -> None:
        """Block native submission without acknowledging delivery when requested."""
        import json

        if self.blocked_operation == "query" and json.loads(data)["type"] == "user":
            self.entered.set()
            await asyncio.Event().wait()
        await super().write(data)

    async def close(self) -> None:
        """Record SDK closure, not native reap."""
        await super().close()


async def test_close_joins_blocked_auth_and_prevents_late_startup(tmp_path: Path) -> None:
    """An owned auth check cannot publish a session after terminal closure."""
    entered = asyncio.Event()
    finished = asyncio.Event()
    transport = ScriptedClaudeTransport()

    async def blocked_status() -> ClaudeAuthenticationStatusDAO:
        """Hold the external status operation until its owner cancels and joins it."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
        return await ready_status()

    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=blocked_status,
    )
    startup = asyncio.create_task(
        coro=adapter.start_session(
            session_options=ClaudeSessionOptionsDAO(
                session_id="host",
                model_id="claude-bridge:claude-sonnet-4-6",
                working_directory=tmp_path,
                instructions="host",
            )
        )
    )
    async with asyncio.timeout(3):
        await entered.wait()
        await adapter.close()
        assert finished.is_set()
        outcomes = await asyncio.gather(startup, return_exceptions=True)
    assert isinstance(outcomes[0], (asyncio.CancelledError, RuntimeError))
    assert not transport.connected
    assert not transport.prompts


async def test_bridge_abort_during_auth_joins_without_submission(tmp_path: Path) -> None:
    """Synchronous host abort is retained before an invocation ID reaches the adapter."""
    from langchain_core.messages import HumanMessage
    from src.bridges.claude.bridge import SloClaudeBridge
    from src.bridges.dao import SloBridgeSessionOptionsDAO

    entered = asyncio.Event()
    finished = asyncio.Event()
    transport = ScriptedClaudeTransport()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Block only the vendor status boundary."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
        return await ready_status()

    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=status
    )
    bridge = SloClaudeBridge(model_name="claude-bridge:claude-sonnet-4-6", bridge_adapter=adapter)
    bridge.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="host", working_directory=tmp_path, instructions="host"
        )
    )
    invocation = asyncio.create_task(coro=bridge.ainvoke([HumanMessage(content="hello")]))
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            bridge.request_cancellation(reason="user_abort")
            outcomes = await asyncio.gather(invocation, return_exceptions=True)
        assert isinstance(outcomes[0], (RuntimeError, asyncio.CancelledError))
        assert finished.is_set()
        assert not transport.connected
        assert not transport.prompts
    finally:
        await bridge.close()
        invocation.cancel()
        await asyncio.gather(invocation, return_exceptions=True)


async def test_invalid_executable_is_rejected_before_construction() -> None:
    """Relative native overrides fail before any session or SDK work starts."""
    with pytest.raises(ValueError, match="absolute"):
        ClaudeBridgeConfigurationDAO(executable=Path("relative-native"))


async def test_concurrent_authentication_is_single_flight() -> None:
    """Concurrent observers share one status operation, later invocation checks remain fresh."""
    entered = asyncio.Event()
    release = asyncio.Event()
    checks: list[int] = []

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Count vendor checks and expose deterministic completion."""
        checks.append(1)
        entered.set()
        await release.wait()
        return await ready_status()

    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), authentication_check=status
    )
    first = asyncio.create_task(coro=adapter.check_authentication())
    await entered.wait()
    second = asyncio.create_task(coro=adapter.check_authentication())
    # A loop callback is a scheduling barrier, not a wall-clock assumption.
    barrier = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_soon(barrier.set_result, None)
    await barrier
    release.set()
    await asyncio.gather(first, second)
    assert checks == [1]
    await adapter.check_authentication()
    assert checks == [1, 1]
    await adapter.close()


@pytest.mark.parametrize("blocked_operation", ["connect", "query"])
async def test_close_cancels_blocked_sdk_startup_in_its_owner(tmp_path: Path, blocked_operation: str) -> None:
    """ER-03: close joins startup without another native event or query."""
    transport = BlockedStartupTransport(blocked_operation=blocked_operation)
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=ready_status
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host",
            model_id="claude-bridge:claude-sonnet-4-6",
            working_directory=tmp_path,
            instructions="host",
        )
    )
    await adapter.invoke_agent(invocation_options=ClaudeInvocationOptionsDAO(invocation_id="one", text="hi"))
    async with asyncio.timeout(3):
        await transport.entered.wait()
        await adapter.close()
    assert transport.closed
    assert transport.close_calls == 1
    assert transport.prompts == []


async def test_native_startup_failure_does_not_consume_prompt_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure before native acceptance permits a corrected host attempt."""
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from tests.cli.test_claude_bridge import scripted_adapter_class

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    checks: list[str] = []
    transport = ScriptedClaudeTransport(
        initialized_tools=tuple(f"mcp__slo__{name}" for name in LOCAL_TOOL_NAMES)
    )

    async def rejected_once() -> ClaudeAuthenticationStatusDAO:
        """Reject startup once, then admit the same configured session."""
        if not checks:
            checks.append("rejected")
            return ClaudeAuthenticationStatusDAO(state="unavailable", safe_message="Unavailable")
        return await ready_status()

    class FlakyAdapter(SloClaudeBridgeAdapter):
        """Use the real adapter with only the external status boundary replaced."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO):
            """Register the deterministic status sequence."""
            return cls(configuration=configuration, transport=transport, authentication_check=rejected_once)

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-sonnet-4-6"),
        bridge_adapter_class=FlakyAdapter,
    )
    try:
        with pytest.raises(ValueError, match="Unavailable"):
            await session.prepare_startup()
        await session.prepare_startup()
        events = [event async for event in session.invoke(text="hello")]
        assert events[-1].kind == "run_completed"
        followup = [event async for event in session.invoke(text="again")]
        assert followup[-1].kind == "run_completed"
        assert transport.prompts == ["hello", "again"]
    finally:
        await session.close_agent_resources()


async def test_read_response_raises_queued_failure_and_rejects_second_reader(tmp_path: Path) -> None:
    """Queue failures are delivered even when EOF follows in the same drain pass."""
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=ScriptedClaudeTransport(),
        authentication_check=ready_status,
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host",
            model_id="claude-bridge:claude-sonnet-4-6",
            working_directory=tmp_path,
            instructions="host",
        )
    )
    await adapter.invoke_agent(invocation_options=ClaudeInvocationOptionsDAO(invocation_id="one", text="hi"))
    reader = adapter.read_response(invocation_id="one")
    event = await anext(reader)
    assert isinstance(event, ClaudeTextEventDAO)
    assert event.text.startswith("Hello")
    assert event.session_id == "host" and event.invocation_id == "one"
    assert event.response_id == "response-test" and event.sequence == 1
    with pytest.raises(RuntimeError, match="reader"):
        _ = [event async for event in adapter.read_response(invocation_id="one")]
    events = [event async for event in reader]
    assert isinstance(events[-1], ClaudeResponseCompletedDAO)
    assert events[-1].stop_reason == "stop"
    assert [item.sequence for item in [event, *events]] == [1, 2, 3]
    assert all(
        item.session_id == "host" and item.invocation_id == "one" and item.response_id == "response-test"
        for item in events
    )
    await adapter.close()


async def test_auth_status_probe_omits_bare_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the auth probe must not pass --bare, which hides the stored login."""
    from src.bridges.claude.sdk import authentication as auth_mod

    captured: dict[str, tuple[object, ...]] = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return (b'{"loggedIn": true, "authMethod": "claude.ai"}', b"")

        def kill(self) -> None:  # pragma: no cover - not reached on success
            pass

        async def wait(self) -> int:  # pragma: no cover - not reached on success
            return 0

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProc:
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(auth_mod.asyncio, "create_subprocess_exec", fake_exec)
    checker = auth_mod.ClaudeNativeAuthentication(configuration=ClaudeBridgeConfigurationDAO())
    status = await checker.check_authentication()
    argv = [str(a) for a in captured["args"]]
    assert status.state == "ready"
    assert "--bare" not in argv
    assert argv[-2:] == ["auth", "status"]
    assert "--setting-sources" in argv
