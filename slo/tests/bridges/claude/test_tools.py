"""Metadata carrier and exact-ID delivery through the real local MCP server."""

import asyncio
from collections.abc import Awaitable, Callable

from mcp.server import Server

import pytest
from pydantic import JsonValue
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    RequestParams,
    ClientRequest,
    ListToolsRequest,
    ServerResult,
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
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError


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
async def test_repeated_server_acquisition_preserves_handlers_and_exact_ids(results_first: bool) -> None:
    """RF06: cached acquisition retains handlers and exact-ID results over real MCP."""
    bridge: ClaudeToolBridge = tool_bridge()
    server: Server = bridge.get_or_create_mcp_server()["instance"]
    list_handler: Callable[..., Awaitable[ServerResult]] = server.request_handlers[ListToolsRequest]
    call_handler: Callable[..., Awaitable[ServerResult]] = server.request_handlers[CallToolRequest]
    assert bridge.get_or_create_mcp_server() == {"type": "sdk", "name": "slo", "instance": server}
    assert bridge.get_or_create_mcp_server()["instance"] is server
    assert server.request_handlers[ListToolsRequest] is list_handler
    assert server.request_handlers[CallToolRequest] is call_handler
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


@pytest.mark.parametrize("callback_first", [False, True])
@pytest.mark.parametrize("streamed,callback", [(1, True), (0, False)])
async def test_callback_rejects_nested_boolean_number_identity(
    callback_first: bool, streamed: int, callback: bool
) -> None:
    """CR101-01: both arrival paths reject Python-equal but JSON-distinct arguments."""
    bridge = tool_bridge()
    call = ClaudeToolCallDAO(
        tool_call_id="native", name="read", arguments={"path": "same", "nested": [{"value": streamed}]}
    )
    batch = ClaudeToolResultBatchDAO(
        response_id="response",
        results=(ClaudeToolResultDAO(tool_call_id="native", content=(), is_error=False),),
    )
    request: asyncio.Task[ClaudeToolResultDAO] | None = None
    try:
        if callback_first:
            request = asyncio.create_task(
                coro=bridge.wait_for_tool_result(
                    tool_call_id="native",
                    name="read",
                    arguments={"path": "same", "nested": [{"value": callback}]},
                )
            )
            await asyncio.sleep(0)
            assert "native" in bridge.pending_calls
            with pytest.raises(ClaudeBridgeError, match="correlation"):
                bridge.publish_tool_batch(response_id="response", tool_calls=(call,))
            with pytest.raises(ClaudeBridgeError):
                await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            outcomes = await asyncio.gather(request, return_exceptions=True)
            assert all(isinstance(value, asyncio.CancelledError) for value in outcomes)
        else:
            bridge.publish_tool_batch(response_id="response", tool_calls=(call,))
            await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            with pytest.raises(ClaudeBridgeError, match="correlation"):
                await bridge.wait_for_tool_result(
                    tool_call_id="native",
                    name="read",
                    arguments={"path": "same", "nested": [{"value": callback}]},
                )
        assert bridge.failure.done()
        assert bridge.failure.result().code == "tool_correlation_failed"
    finally:
        await bridge.close()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
    assert not bridge.pending_calls and not bridge.pending_results


@pytest.mark.parametrize("callback_first", [False, True])
async def test_callback_identity_detaches_nested_values_and_ignores_object_key_order(
    callback_first: bool,
) -> None:
    """CR101-01: borrowed nested dictionaries cannot mutate retained correlation."""
    bridge = tool_bridge()
    arguments: dict[str, JsonValue] = {"path": "same", "nested": {"a": [True, 1], "b": False}}
    call = ClaudeToolCallDAO(tool_call_id="native", name="read", arguments=arguments)
    callback_arguments: dict[str, JsonValue] = {"nested": {"b": False, "a": [True, 1]}, "path": "same"}
    request: asyncio.Task[ClaudeToolResultDAO] | None = None
    result = ClaudeToolResultDAO(tool_call_id="native", content=(), is_error=False)
    try:
        if not callback_first:
            bridge.publish_tool_batch(response_id="response", tool_calls=(call,))
            call.arguments["nested"] = "changed after publication"
        request = asyncio.create_task(
            coro=bridge.wait_for_tool_result(tool_call_id="native", name="read", arguments=callback_arguments)
        )
        await asyncio.sleep(0)
        if callback_first:
            nested = callback_arguments["nested"]
            assert isinstance(nested, dict)
            nested["b"] = "changed after callback admission"
            bridge.publish_tool_batch(response_id="response", tool_calls=(call,))
        await bridge.submit_tool_results(
            invocation_id="invocation",
            tool_result_batch=ClaudeToolResultBatchDAO(response_id="response", results=(result,)),
        )
        async with asyncio.timeout(5):
            assert await request == result
        bridge.validate_terminal()
        assert not bridge.failure.done()
    finally:
        await bridge.close()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)


@pytest.mark.parametrize("callback_first", [False, True])
async def test_callback_identity_rejects_nonfinite_json_before_retention(callback_first: bool) -> None:
    """CR101-01: neither admission path may retain nonfinite nested JSON values."""
    bridge = tool_bridge()
    try:
        with pytest.raises(ClaudeBridgeError, match="correlation"):
            if callback_first:
                async with asyncio.timeout(0.1):
                    await bridge.wait_for_tool_result(
                        tool_call_id="native", name="read", arguments={"nested": [float("inf")]}
                    )
            else:
                bridge.publish_tool_batch(
                    response_id="response",
                    tool_calls=(
                        ClaudeToolCallDAO(
                            tool_call_id="native", name="read", arguments={"nested": [float("inf")]}
                        ),
                    ),
                )
        assert bridge.failure.done()
        assert not bridge.expected_calls and not bridge.pending_calls
    finally:
        await bridge.close()


async def test_late_result_and_callback_after_retirement_never_release_success() -> None:
    """A18: a retired MCP owner cannot accept a late result or mutate a new owner."""
    bridge = tool_bridge()
    server = bridge.get_or_create_mcp_server()["instance"]
    bridge.publish_tool_batch(
        response_id="response",
        tool_calls=(ClaudeToolCallDAO(tool_call_id="old", name="read", arguments={"path": "same"}),),
    )
    await bridge.close()
    reacquired_server: Server = bridge.get_or_create_mcp_server()["instance"]
    assert reacquired_server is server
    with pytest.raises(RuntimeError):
        await bridge.submit_tool_results(
            invocation_id="invocation",
            tool_result_batch=ClaudeToolResultBatchDAO(
                response_id="response",
                results=(
                    ClaudeToolResultDAO(
                        tool_call_id="old", content=(ClaudeTextDAO(text="late"),), is_error=False
                    ),
                ),
            ),
        )
    async with create_connected_server_and_client_session(server=reacquired_server) as client:
        result = await client.send_request(
            request=ClientRequest(
                CallToolRequest(
                    method="tools/call",
                    params=CallToolRequestParams(
                        name="read",
                        arguments={"path": "same"},
                        _meta=RequestParams.Meta.model_validate({"claudecode/toolUseId": "old"}),
                    ),
                )
            ),
            result_type=CallToolResult,
        )
        assert result.isError
    assert not bridge.pending_calls and not bridge.pending_results


@pytest.mark.parametrize("metadata", [{}, {"claudecode/toolUseId": 17}, {"claudecode/toolUseId": ""}])
async def test_mcp_native_id_metadata_is_required(metadata: dict[str, object]) -> None:
    """A17: MCP preserves invalid metadata but our owner fails closed, not by arguments."""
    bridge = tool_bridge()
    try:
        async with create_connected_server_and_client_session(
            server=bridge.get_or_create_mcp_server()["instance"]
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


@pytest.mark.parametrize("fault", ["missing", "unknown", "duplicate", "stale-response"])
async def test_result_sets_validate_before_releasing_any_callback(fault: str) -> None:
    """A8: only a missing subset is correctable; corrupted sets seal all waiters."""
    from src.bridges.claude.sdk.exceptions import ClaudeBridgeError

    bridge = tool_bridge()
    calls = tuple(ClaudeToolCallDAO(tool_call_id=i, name="read", arguments={}) for i in ("a", "b"))
    bridge.publish_tool_batch(response_id="response", tool_calls=calls)
    tasks = [
        asyncio.create_task(coro=bridge.wait_for_tool_result(tool_call_id=i, name="read", arguments={}))
        for i in ("a", "b")
    ]
    results = tuple(
        ClaudeToolResultDAO(tool_call_id=i, content=(ClaudeTextDAO(text=i),), is_error=False)
        for i in ("a", "b", "unknown")
    )
    invalid = {
        "missing": results[:1],
        "unknown": results,
        "duplicate": (*results[:2], results[1]),
        "stale-response": results[:2],
    }[fault]
    try:
        await asyncio.sleep(0)
        with pytest.raises(ClaudeBridgeError) as failure:
            await bridge.submit_tool_results(
                invocation_id="invocation",
                tool_result_batch=ClaudeToolResultBatchDAO(
                    response_id="old" if fault == "stale-response" else "response",
                    results=invalid,
                ),
            )
        assert not bridge.pending_results
        if fault == "missing":
            assert failure.value.code == "tool_result_mismatch"
            assert not bridge.failure.done() and not any(task.done() for task in tasks)
            batch = ClaudeToolResultBatchDAO(response_id="response", results=tuple(reversed(results[:2])))
            await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            assert await asyncio.gather(*tasks) == list(results[:2])
            await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
            assert not bridge.pending_results
        else:
            assert failure.value.code == "tool_correlation_failed"
            assert bridge.failure.done()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes)
    finally:
        await bridge.close()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_conflicting_repeat_invalidates_new_round_without_releasing_its_waiters() -> None:
    """A8/A18: retained acceptance protects prior IDs while the next response waits."""
    from src.bridges.claude.sdk.exceptions import ClaudeBridgeError

    bridge = tool_bridge()
    first = ClaudeToolResultDAO(tool_call_id="a", content=(ClaudeTextDAO(text="original"),), is_error=False)
    batch = ClaudeToolResultBatchDAO(response_id="first", results=(first,))
    tasks: list[asyncio.Task[ClaudeToolResultDAO]] = []
    try:
        bridge.publish_tool_batch(
            response_id="first", tool_calls=(ClaudeToolCallDAO(tool_call_id="a", name="read", arguments={}),)
        )
        await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
        assert await bridge.wait_for_tool_result(tool_call_id="a", name="read", arguments={}) == first
        bridge.publish_tool_batch(
            response_id="second", tool_calls=(ClaudeToolCallDAO(tool_call_id="b", name="read", arguments={}),)
        )
        tasks.append(
            asyncio.create_task(
                coro=bridge.wait_for_tool_result(tool_call_id="b", name="read", arguments={}),
            )
        )
        await asyncio.sleep(0)
        await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=batch)
        assert not tasks[0].done() and not bridge.pending_results
        with pytest.raises(ClaudeBridgeError, match="correlation"):
            await bridge.submit_tool_results(
                invocation_id="invocation",
                tool_result_batch=ClaudeToolResultBatchDAO(
                    response_id="first",
                    results=(first.model_copy(update={"is_error": True}),),
                ),
            )
        assert bridge.failure.done() and not bridge.pending_results
        assert isinstance((await asyncio.gather(*tasks, return_exceptions=True))[0], asyncio.CancelledError)
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
