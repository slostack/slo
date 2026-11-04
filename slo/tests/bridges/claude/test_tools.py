"""Metadata carrier and exact-ID delivery through the real local MCP server."""

import asyncio

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    RequestParams,
    ClientRequest,
    TextContent,
)

from src.bridges.claude.sdk.dao import (
    ClaudeInteractionBindingDAO,
    ClaudeToolDefinitionDAO,
    ClaudeToolCallDAO,
    ClaudeToolResultDAO,
    ClaudeToolResultBatchDAO,
    ClaudeTextDAO,
)
from src.bridges.claude.sdk.tool_bridge import ClaudeToolBridge


def tool_bridge() -> ClaudeToolBridge:
    """Assemble an inert portable owner without filesystem or native activity."""
    return ClaudeToolBridge.register(
        binding=ClaudeInteractionBindingDAO(
            session_id="session", invocation_id="invocation", binding_version=0
        ),
        tools=(
            ClaudeToolDefinitionDAO(
                name="read",
                description="Read",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            ),
        ),
    )


@pytest.mark.parametrize("results_first", [False, True])
async def test_callback_result_order_and_exact_ids(results_first: bool) -> None:
    """A4/A8/A17/A18: identical reads correlate by metadata, never RPC ID/order."""
    bridge = tool_bridge()
    server = bridge.build_mcp_server()["instance"]
    calls = tuple(
        ClaudeToolCallDAO(tool_call_id=i, name="read", arguments={"path": "same"})
        for i in ("native-a", "native-b")
    )
    bridge.publish_tool_batch(response_id="response", tool_calls=calls)
    batch = ClaudeToolResultBatchDAO(
        response_id="response",
        results=tuple(
            ClaudeToolResultDAO(tool_call_id=i, content=(ClaudeTextDAO(text=i),), is_error=False)
            for i in ("native-b", "native-a")
        ),
    )
    try:
        async with create_connected_server_and_client_session(server=server) as client:
            inventory = await client.list_tools()
            assert inventory.tools[0].inputSchema == bridge.tools[0].input_schema
            if results_first:
                await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)

            async def call(native_id: str) -> CallToolResult:
                """Use the public client request path with a distinct JSON-RPC identity."""
                return await client.send_request(
                    request=ClientRequest(
                        CallToolRequest(
                            method="tools/call",
                            params=CallToolRequestParams(
                                name="read",
                                arguments={"path": "same"},
                                _meta=RequestParams.Meta.model_validate({"claudecode/toolUseId": native_id}),
                            ),
                        )
                    ),
                    result_type=CallToolResult,
                )

            tasks = [asyncio.create_task(coro=call(native_id=i)) for i in ("native-b", "native-a")]
            if not results_first:

                async def await_callbacks() -> None:
                    """Yield until real MCP dispatch admits both parked callbacks."""
                    while len(bridge.pending_calls) != 2:
                        await asyncio.sleep(0)

                async with asyncio.timeout(5):
                    await await_callbacks()
                assert not any(task.done() for task in tasks)
                await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            async with asyncio.timeout(5):
                results = await asyncio.gather(*tasks)
            assert all(isinstance(r.content[0], TextContent) for r in results)
            assert [r.content[0].text for r in results if isinstance(r.content[0], TextContent)] == [
                "native-b",
                "native-a",
            ]
            await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            assert not bridge.pending_calls and not bridge.pending_results
    finally:
        await bridge.close()


@pytest.mark.parametrize("metadata", [{}, {"claudecode/toolUseId": 17}, {"claudecode/toolUseId": ""}])
async def test_mcp_native_id_metadata_is_required(metadata: dict[str, object]) -> None:
    """A17: MCP preserves invalid metadata but our owner fails closed, not by arguments."""
    bridge = tool_bridge()
    try:
        async with create_connected_server_and_client_session(
            server=bridge.build_mcp_server()["instance"]
        ) as client:
            result = await client.send_request(
                request=ClientRequest(
                    CallToolRequest(
                        method="tools/call",
                        params=CallToolRequestParams(
                            name="read",
                            arguments={"path": "same"},
                            _meta=RequestParams.Meta.model_validate(metadata),
                        ),
                    )
                ),
                result_type=CallToolResult,
            )
            assert result.isError
            assert bridge.failure.done()
            assert not bridge.pending_calls and not bridge.pending_results
    finally:
        await bridge.close()


@pytest.mark.parametrize("fault", ["provisional", "overlapping", "cancelled"])
async def test_fatal_callback_state_releases_no_result(fault: str) -> None:
    """EF14-02: reject the entire delivery before any waiter observes success."""
    from src.bridges.claude.sdk.exceptions import ClaudeBridgeError

    bridge = tool_bridge()
    calls = tuple(ClaudeToolCallDAO(tool_call_id=i, name="read", arguments={}) for i in ("a", "b"))
    tasks: list[asyncio.Task[ClaudeToolResultDAO]] = []
    try:
        if fault == "provisional":
            tasks.append(
                asyncio.create_task(
                    coro=bridge.wait_for_tool_result(tool_call_id="foreign", name="read", arguments={})
                )
            )
            await asyncio.sleep(0)
            with pytest.raises(ClaudeBridgeError):
                bridge.publish_tool_batch(response_id="response", tool_calls=calls)
        elif fault == "overlapping":
            bridge.publish_tool_batch(response_id="first", tool_calls=calls)
            with pytest.raises(ClaudeBridgeError):
                bridge.publish_tool_batch(
                    response_id="second",
                    tool_calls=(ClaudeToolCallDAO(tool_call_id="c", name="read", arguments={}),),
                )
        else:
            bridge.publish_tool_batch(response_id="response", tool_calls=calls)
            tasks = [
                asyncio.create_task(
                    coro=bridge.wait_for_tool_result(tool_call_id=i, name="read", arguments={})
                )
                for i in ("a", "b")
            ]
            await asyncio.sleep(0)
            # cancel() cancels the awaited future synchronously, before task finally runs.
            tasks[1].cancel()
            batch = ClaudeToolResultBatchDAO(
                response_id="response",
                results=tuple(
                    ClaudeToolResultDAO(tool_call_id=i, content=(ClaudeTextDAO(text=i),), is_error=False)
                    for i in ("a", "b")
                ),
            )
            with pytest.raises(ClaudeBridgeError):
                await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
        assert bridge.failure.done()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert not any(isinstance(value, ClaudeToolResultDAO) for value in outcomes)
        assert not bridge.pending_results
    finally:
        await bridge.close()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("encoded", ["not base64!", "YQ==="])
def test_image_payload_requires_canonical_base64(encoded: str) -> None:
    """EF14-04: reject invalid image bytes before a result can release a callback."""
    from pydantic import ValidationError
    from src.bridges.claude.sdk.dao import ClaudeImageDAO

    with pytest.raises(ValidationError):
        ClaudeImageDAO(media_type="image/png", data=encoded)
