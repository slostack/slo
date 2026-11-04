"""Raw-schema MCP carrier; Slo alone executes calls published by the native stream."""

import asyncio
import json
from typing import Any, Self, NoReturn

from claude_agent_sdk import McpSdkServerConfig
from mcp.server import Server
from mcp.types import CallToolResult, ImageContent, TextContent, Tool
from pydantic import JsonValue, TypeAdapter, ValidationError

from .dao import (
    ClaudeInteractionBindingDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolCallDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
    ClaudeTextDAO,
)
from .exceptions import ClaudeBridgeError


class ClaudeToolBridge:
    """Own exact-ID callbacks, early results and retained duplicate protection."""

    def __init__(
        self, *, binding: ClaudeInteractionBindingDAO, tools: tuple[ClaudeToolDefinitionDAO, ...]
    ) -> None:
        """Store fixed definitions inertly; capture the loop only when used."""
        self.binding = binding
        self.tools = tools
        self.pending_calls: dict[str, asyncio.Future[ClaudeToolResultDAO]] = {}
        self.pending_results: dict[str, ClaudeToolResultDAO] = {}
        self.expected_calls: dict[str, ClaudeToolCallDAO] = {}
        self._callback_calls: dict[str, ClaudeToolCallDAO] = {}
        self._accepted: dict[str, ClaudeToolResultDAO] = {}
        self._batches: dict[str, tuple[str, ...]] = {}
        self._closed = False
        self._server: Server | None = None
        self._failure: asyncio.Future[ClaudeBridgeError] | None = None

    @classmethod
    def register(
        cls, *, binding: ClaudeInteractionBindingDAO, tools: tuple[ClaudeToolDefinitionDAO, ...]
    ) -> Self:
        """Register one immutable invocation association without I/O."""
        return cls(binding=binding, tools=tools)

    @property
    def failure(self) -> asyncio.Future[ClaudeBridgeError]:
        """Wake the runtime even when MCP converts handler exceptions to error results."""
        if self._failure is None:
            self._failure = asyncio.get_running_loop().create_future()
        return self._failure

    def _fail(self, *, code: str = "tool_correlation_failed") -> NoReturn:
        """Seal corrupted correlation and signal the receive owner independently."""
        error = ClaudeBridgeError(code=code, safe_message="Claude tool correlation failed.")
        self._closed = True
        if not self.failure.done():
            self.failure.set_result(error)
        for waiter in self.pending_calls.values():
            waiter.cancel()
        raise error

    def build_mcp_server(self) -> McpSdkServerConfig:
        """Assemble public low-level MCP handlers with unchanged JSON schemas."""
        if self._server is None:
            self._server = Server(name="slo")
            self._server.list_tools()(self._list_tools)
            self._server.call_tool(validate_input=False)(self._handle_tool_call)
        return McpSdkServerConfig(type="sdk", name="slo", instance=self._server)

    async def _list_tools(self) -> list[Tool]:
        """Advertise only the fixed raw host inventory."""
        return [Tool(name=t.name, description=t.description, inputSchema=t.input_schema) for t in self.tools]

    async def _handle_tool_call(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Read Claude metadata at the vendor boundary and park, never execute."""
        assert self._server is not None
        meta = self._server.request_context.meta
        native_id = (meta.model_extra or {}).get("claudecode/toolUseId") if meta is not None else None
        if not isinstance(native_id, str) or not 1 <= len(native_id) <= 256:
            self._fail()
        try:
            validated = TypeAdapter(dict[str, JsonValue]).validate_python(arguments)
        except ValidationError:
            self._fail()
        result = await self.wait_for_tool_result(tool_call_id=native_id, name=name, arguments=validated)
        return CallToolResult(
            content=[
                (
                    TextContent(type="text", text=b.text)
                    if isinstance(b, ClaudeTextDAO)
                    else ImageContent(type="image", mimeType=b.media_type, data=b.data)
                )
                for b in result.content
            ],
            isError=result.is_error,
        )

    async def wait_for_tool_result(
        self, *, tool_call_id: str, name: str, arguments: dict[str, JsonValue]
    ) -> ClaudeToolResultDAO:
        """Admit a callback once and match only its native ID and complete emitted call."""
        if self._closed or name not in {t.name for t in self.tools} or tool_call_id in self._callback_calls:
            self._fail()
        try:
            call = ClaudeToolCallDAO(tool_call_id=tool_call_id, name=name, arguments=arguments)
        except ValidationError:
            self._fail()
        if len(json.dumps(arguments).encode()) > 1024 * 1024 or len(self._callback_calls) >= 10000:
            self._fail(code="buffer_limit_exceeded")
        expected = self.expected_calls.get(tool_call_id)
        if expected is not None and expected != call:
            self._fail()
        if len(set(self.expected_calls) | set(self._callback_calls) | {tool_call_id}) > 10000:
            self._fail(code="buffer_limit_exceeded")
        self._callback_calls[tool_call_id] = call
        if tool_call_id in self.pending_results:
            return self.pending_results.pop(tool_call_id)
        waiter: asyncio.Future[ClaudeToolResultDAO] = asyncio.get_running_loop().create_future()
        self.pending_calls[tool_call_id] = waiter
        try:
            return await waiter
        except asyncio.CancelledError:
            if not self._closed:
                self._fail()
            raise
        finally:
            self.pending_calls.pop(tool_call_id, None)

    def publish_tool_batch(self, *, response_id: str, tool_calls: tuple[ClaudeToolCallDAO, ...]) -> None:
        """Validate the whole stream batch before committing executable identities."""
        ids = tuple(c.tool_call_id for c in tool_calls)
        if self._closed or not 1 <= len(ids) <= 128 or len(set(ids)) != len(ids):
            self._fail()
        if response_id in self._batches or any(i in self.expected_calls for i in ids):
            self._fail()
        if set(self.expected_calls) != set(self._accepted):
            self._fail()
        provisional = set(self._callback_calls) - set(self.expected_calls)
        if not provisional.issubset(ids):
            self._fail()
        if len(set(self.expected_calls) | set(self._callback_calls) | set(ids)) > 10000:
            self._fail(code="buffer_limit_exceeded")
        if sum(len(c.model_dump_json().encode()) for c in tool_calls) > 32 * 1024 * 1024:
            self._fail(code="buffer_limit_exceeded")
        for call in tool_calls:
            if call.name not in {t.name for t in self.tools}:
                self._fail()
            if len(json.dumps(call.arguments).encode()) > 1024 * 1024:
                self._fail(code="buffer_limit_exceeded")
            callback = self._callback_calls.get(call.tool_call_id)
            if callback is not None and callback != call:
                self._fail()
        self._batches[response_id] = ids
        self.expected_calls.update({c.tool_call_id: c for c in tool_calls})

    async def submit_tool_results(
        self, *, invocation_id: str, tool_result_batch: ClaudeToolResultBatchDAO
    ) -> None:
        """Reserve a complete set without await, then release exact matching callbacks."""
        if self._closed or invocation_id != self.binding.invocation_id:
            self._fail()
        expected = self._batches.get(tool_result_batch.response_id)
        results = {r.tool_call_id: r for r in tool_result_batch.results}
        if (
            expected is None
            or set(expected) != set(results)
            or len(results) != len(tool_result_batch.results)
        ):
            raise ClaudeBridgeError(
                code="tool_result_mismatch", safe_message="Expected the complete Claude tool result set."
            )
        if len(tool_result_batch.model_dump_json().encode()) > 32 * 1024 * 1024:
            self._fail(code="buffer_limit_exceeded")
        for identity, result in results.items():
            if identity in self._accepted and self._accepted[identity] != result:
                self._fail()
        new = {i: r for i, r in results.items() if i not in self._accepted}
        # No await may split preflight/reservation/release. A cancelled future
        # invalidates the whole set before another callback can observe success.
        if any(self.pending_calls[i].done() for i in new if i in self.pending_calls):
            self._fail()
        self._accepted.update(new)
        for identity, result in new.items():
            waiter = self.pending_calls.get(identity)
            if waiter is not None:
                waiter.set_result(result)
            else:
                self.pending_results[identity] = result

    def validate_terminal(self) -> None:
        """Reject native success with unbound callbacks or undelivered accepted results."""
        if (
            set(self.expected_calls) != set(self._accepted)
            or set(self.expected_calls) != set(self._callback_calls)
            or self.pending_results
        ):
            self._fail()

    async def close(self) -> None:
        """Seal callbacks and cancel parked waits; SDK owns actual server shutdown."""
        self._closed = True
        for waiter in self.pending_calls.values():
            waiter.cancel()
        self.pending_calls.clear()
        self.pending_results.clear()
