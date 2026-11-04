"""SDK lifecycle regressions using only the vendor transport injection seam."""

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


class FailingCloseTransport(ScriptedClaudeTransport):
    """Keep the SDK's transport usable after its first explicit cleanup failure."""

    def __init__(self) -> None:
        """Record close attempts and block the native response."""
        super().__init__(block_response=True)
        self.close_attempts = 0

    async def close(self) -> None:
        """Fail once, then acknowledge supported closure without resubmission."""
        self.close_attempts += 1
        if self.close_attempts == 1:
            raise OSError("synthetic cleanup failure")
        await super().close()


async def ready_status() -> ClaudeAuthenticationStatusDAO:
    """Observe a synthetic native login without an account operation."""
    return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Synthetic ready.")


async def test_explicit_close_retries_raised_sdk_cleanup_without_query_replay(tmp_path: Path) -> None:
    """ER-04: a raised SDK disconnect retains a usable owner for explicit close."""
    transport = FailingCloseTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
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
    async with asyncio.timeout(3):
        await transport.submitted.wait()
        with pytest.raises(RuntimeError, match="cleanup"):
            await adapter.close()
        await adapter.close()
    assert transport.closed
    assert transport.close_attempts == 2
    assert transport.prompts == ["hi"]


async def test_cancel_joins_sdk_when_content_delivery_is_saturated(tmp_path: Path) -> None:
    """ER-03: cancellation must not wait behind an abandoned full response queue."""
    transport = ScriptedClaudeTransport(block_response=True)
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

    async def publish_fragments() -> None:
        """Saturate delivery independently of the caller requesting closure."""
        for index in range(300):
            await transport.messages.put(
                {
                    "type": "stream_event",
                    "uuid": f"fragment-{index}",
                    "session_id": "native-test",
                    "event": {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "x"},
                    },
                }
            )

    publisher = asyncio.create_task(coro=publish_fragments())
    try:
        async with asyncio.timeout(3):
            await transport.submitted.wait()
            await asyncio.sleep(0.05)
            await adapter.close()
        assert transport.closed
        assert transport.prompts == ["hi"]
    finally:
        publisher.cancel()
        await asyncio.gather(publisher, return_exceptions=True)
        await adapter.close()
