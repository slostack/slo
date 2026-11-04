"""Resumed SDK lifetime and stale-result boundaries with controlled native I/O."""

import asyncio
from pathlib import Path

import pytest

from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeTextDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
)
from src.bridges.claude.sdk.events import ClaudeResponseCompletedDAO
from tests.bridges.claude.test_lifecycle import ready_status
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport


async def test_stale_invocation_results_cannot_release_resumed_waiters(tmp_path: Path) -> None:
    """Repeated response/call IDs do not grant a prior invocation delivery authority."""

    class RepeatedTransport(ToolRoundTransport):
        """Repeat native IDs while preserving wire receipts across connections."""

        async def connect(self) -> None:
            """Reset script turn state, not recorded prompts/results."""
            self.closed = False
            self.round = 0
            await super().connect()

    transport = RepeatedTransport(path=tmp_path / "unused.txt")
    transport.initialized_tools = ["mcp__slo__read"]
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host",
            model_id="claude-bridge:claude-haiku-5-5",
            working_directory=tmp_path,
            instructions="host",
            tools=(
                ClaudeToolDefinitionDAO(
                    name="read",
                    description="Read",
                    input_schema={"type": "object"},
                ),
            ),
        )
    )
    previous_batch: ClaudeToolResultBatchDAO | None = None
    try:
        async with asyncio.timeout(5):
            for invocation_id in ("first", "second"):
                await adapter.invoke_agent(
                    invocation_options=ClaudeInvocationOptionsDAO(
                        invocation_id=invocation_id,
                        text=invocation_id,
                    )
                )
                async for event in adapter.read_response(invocation_id=invocation_id):
                    if not isinstance(event, ClaudeResponseCompletedDAO) or not event.tool_calls:
                        continue
                    bridge = adapter._runtime._tool_bridge
                    assert bridge is not None
                    while not bridge.pending_calls:
                        await asyncio.sleep(0)
                    batch = ClaudeToolResultBatchDAO(
                        response_id=event.response_id,
                        results=tuple(
                            ClaudeToolResultDAO(
                                tool_call_id=call.tool_call_id,
                                content=(ClaudeTextDAO(text="current receipt"),),
                                is_error=False,
                            )
                            for call in event.tool_calls
                        ),
                    )
                    if previous_batch is not None:
                        assert batch == previous_batch
                        waiters = tuple(bridge.pending_calls.values())
                        with pytest.raises(RuntimeError, match="Unknown.*invocation"):
                            await adapter.submit_tool_results(
                                invocation_id="first",
                                tool_result_batch=previous_batch,
                            )
                        assert tuple(bridge.pending_calls.values()) == waiters
                        assert all(not waiter.done() for waiter in waiters)
                        assert not bridge.pending_results
                        assert len(transport.tool_results) == 1
                    await adapter.submit_tool_results(
                        invocation_id=invocation_id,
                        tool_result_batch=batch,
                    )
                    previous_batch = batch
                terminal = [event async for event in adapter.read_response(invocation_id=invocation_id)]
                assert isinstance(terminal[-1], ClaudeResponseCompletedDAO)
                assert terminal[-1].stop_reason == "stop"
            assert transport.prompts == ["first", "second"]
            assert len(transport.tool_results) == 2
            assert transport.close_calls == 2
    finally:
        await adapter.close()


@pytest.mark.parametrize("stage", ["connect", "response"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_close_resumed_work_retains_cleanup_owner_without_replay(
    tmp_path: Path,
    stage: str,
    cleanup_fails: bool,
) -> None:
    """Resumed startup/response cancellation joins or retains a retryable cleanup owner."""
    entered = asyncio.Event()

    class ResumedTransport(ScriptedClaudeTransport):
        """Block only the resumed connection and optionally reject its first close."""

        def __init__(self) -> None:
            """Retain close attempts separately from successful native closure."""
            super().__init__()
            self.close_attempts = 0
            self.failed_close = False

        async def connect(self) -> None:
            """Expose a deterministic partial-startup barrier on the second turn."""
            self.closed = False
            if self.prompts:
                self.block_response = True
                entered.set()
                if stage == "connect":
                    await asyncio.Event().wait()
            await super().connect()

        async def close(self) -> None:
            """Fail resumed cleanup once without discarding the retained transport."""
            self.close_attempts += 1
            if cleanup_fails and entered.is_set() and not self.failed_close:
                self.failed_close = True
                raise OSError("synthetic cleanup failure")
            await super().close()

    transport = ResumedTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host",
            model_id="claude-bridge:claude-haiku-5-5",
            working_directory=tmp_path,
            instructions="host",
        )
    )
    try:
        async with asyncio.timeout(5):
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="first",
                    text="first",
                )
            )
            _ = [event async for event in adapter.read_response(invocation_id="first")]
            first_owner = adapter._runtime._owner
            assert first_owner is not None
            transport.submitted.clear()
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="second",
                    text="second",
                )
            )
            await entered.wait()
            assert first_owner.done()
            if stage == "response":
                await transport.submitted.wait()
            runtime = adapter._runtime
            assert runtime._owner is not None and runtime._tool_bridge is not None
            if cleanup_fails:
                with pytest.raises(RuntimeError, match="cleanup"):
                    await adapter.close()
                assert adapter._runtime is runtime
                assert not runtime._owner.done()
                with pytest.raises(RuntimeError, match="closed"):
                    await adapter.invoke_agent(
                        invocation_options=ClaudeInvocationOptionsDAO(
                            invocation_id="forbidden",
                            text="must not send",
                        )
                    )
            await adapter.close()
            assert runtime._owner.done()
            assert not runtime._tool_bridge.pending_calls
            assert transport.closed
            attempts = transport.close_attempts
            await adapter.close()
            assert transport.close_attempts == attempts
            assert transport.prompts == (["first", "second"] if stage == "response" else ["first"])
    finally:
        await adapter.close()
