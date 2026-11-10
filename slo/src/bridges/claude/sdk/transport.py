"""Reject unsupported assistant blocks before the SDK can silently discard them."""

import asyncio
from collections.abc import AsyncIterator

# Match the SDK Transport's heterogeneous raw JSON interface before typed parsing.
from typing import Any

from claude_agent_sdk._internal.transport import Transport

from .exceptions import ClaudeBridgeError


class ValidatedClaudeTransport(Transport):
    """Guard raw assistant content; leave control routing and lifetime to the SDK.

    Only text, thinking and tool_use belong to this bridge's response contract.
    Unknown fields on supported blocks remain vendor metadata, not corroborated
    payload. Unknown block kinds must not become vacuously valid empty echoes.
    """

    def __init__(self, *, transport: Transport) -> None:
        """Retain the runtime-owned transport without starting native I/O."""
        self._transport = transport
        self._failure: asyncio.Future[ClaudeBridgeError] | None = None

    @property
    def failure(self) -> asyncio.Future[ClaudeBridgeError]:
        """Wake the runtime when the SDK swallows a failed control-response write."""
        if self._failure is None:
            self._failure = asyncio.get_running_loop().create_future()
        return self._failure

    async def connect(self) -> None:
        """Let the SDK open its underlying transport."""
        try:
            await self._transport.connect()
        except (ConnectionError, TimeoutError):
            # Only this pre-query transport operation proves a transient connect
            # failure. Arbitrary OSError/config/auth errors do not qualify, nor
            # do failures after a write might have delivered a query or receipt.
            raise ClaudeBridgeError(
                code="transient_connect_failed",
                safe_message="Claude native connection temporarily unavailable.",
            ) from None

    async def write(self, data: str) -> None:
        """Forward unchanged frames and signal uncertain writes without replay.

        SDK MCP control handlers may catch write exceptions. The runtime also
        observes this control future so such a failure cannot leave it parked.
        """
        if self.failure.done():
            raise self.failure.result()
        try:
            await self._transport.write(data=data)
        except Exception:
            error = ClaudeBridgeError(
                code="provider_unavailable",
                safe_message="Claude native delivery failed; start a new session.",
            )
            if not self.failure.done():
                self.failure.set_result(error)
            raise error from None

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Validate each raw assistant before SDK parsing, until SDK cancellation.

        Raises:
            ClaudeBridgeError: Unsupported or malformed assistant content.
        """
        async for message in self._transport.read_messages():
            self._validate_assistant(message=message)
            yield message

    @staticmethod
    def _validate_assistant(*, message: dict[str, Any]) -> None:
        """Reject lossy block parsing without interpreting unrelated control frames."""
        if message.get("type") != "assistant":
            return
        payload = message.get("message")
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise ClaudeBridgeError.protocol_error()
        for block in payload["content"]:
            if not isinstance(block, dict) or block.get("type") not in ("text", "thinking", "tool_use"):
                raise ClaudeBridgeError.protocol_error()

    async def close(self) -> None:
        """Preserve SDK-owned underlying cleanup, without a second lifetime."""
        await self._transport.close()

    def is_ready(self) -> bool:
        """Report underlying readiness without maintaining parallel state."""
        return self._transport.is_ready()

    async def end_input(self) -> None:
        """Preserve the SDK's input closure protocol."""
        await self._transport.end_input()
