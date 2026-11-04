"""Actual local limits at their portable owners; no reduced constants or huge matrix."""

import asyncio
import base64
import json

import pytest
from pydantic import JsonValue, ValidationError

from src.bridges.claude.sdk.dao import (
    ClaudeImageDAO,
    ClaudeTextDAO,
    ClaudeToolCallDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultDAO,
)
from src.bridges.claude.sdk.events import ClaudeTextEventDAO
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from tests.bridges.claude.test_tools import tool_bridge


async def test_call_count_input_and_result_bytes_fail_without_partial_acceptance() -> None:
    """128 calls/1MiB JSON pass; oversized input/result sets release nothing."""
    bridge = tool_bridge()
    input_text = "x" * (1024 * 1024 - len(json.dumps({"x": ""}).encode()))
    args: dict[str, JsonValue] = {"x": input_text}
    calls = tuple(
        ClaudeToolCallDAO(tool_call_id=str(index), name="read", arguments=args if index == 0 else {})
        for index in range(128)
    )
    bridge.publish_tool_batch(response_id="at-limit", tool_calls=calls)
    assert len(bridge.expected_calls) == 128
    oversized = ClaudeToolResultBatchDAO(
        response_id="at-limit",
        results=tuple(
            ClaudeToolResultDAO(
                tool_call_id=call.tool_call_id,
                content=(ClaudeTextDAO(text="x" * (256 * 1024)),),
                is_error=False,
            )
            for call in calls
        ),
    )
    with pytest.raises(ClaudeBridgeError) as error:
        await bridge.submit_tool_results(invocation_id="invocation", tool_result_batch=oversized)
    assert error.value.code == "buffer_limit_exceeded"
    assert not bridge.pending_results and not bridge._accepted
    await bridge.close()
    for candidates in (
        calls + (ClaudeToolCallDAO(tool_call_id="129", name="read", arguments={}),),
        (calls[0].model_copy(update={"arguments": {"x": input_text + "x"}}),),
    ):
        bridge = tool_bridge()
        with pytest.raises(ClaudeBridgeError):
            bridge.publish_tool_batch(response_id="too-big", tool_calls=candidates)
        assert not bridge.expected_calls
        await bridge.close()


async def test_duplicate_identity_union_rejects_10001_without_eviction() -> None:
    """Published identities plus disjoint provisional callbacks share the real 10k cap."""
    bridge = tool_bridge()
    for start in range(0, 9984, 128):
        calls = tuple(
            ClaudeToolCallDAO(tool_call_id=str(index), name="read", arguments={})
            for index in range(start, start + 128)
        )
        bridge.publish_tool_batch(response_id=str(start), tool_calls=calls)
        await bridge.submit_tool_results(
            invocation_id="invocation",
            tool_result_batch=ClaudeToolResultBatchDAO(
                response_id=str(start),
                results=tuple(
                    ClaudeToolResultDAO(tool_call_id=call.tool_call_id, content=(), is_error=False)
                    for call in calls
                ),
            ),
        )
    tasks = [
        asyncio.create_task(
            bridge.wait_for_tool_result(tool_call_id=f"provisional-{index}", name="read", arguments={})
        )
        for index in range(16)
    ]
    try:
        await asyncio.sleep(0)
        assert len(set(bridge.expected_calls) | set(bridge._callback_calls)) == 10000
        with pytest.raises(ClaudeBridgeError) as error:
            await bridge.wait_for_tool_result(tool_call_id="10001", name="read", arguments={})
        assert error.value.code == "buffer_limit_exceeded"
        assert "0" in bridge.expected_calls and len(bridge.expected_calls) == 9984
    finally:
        await bridge.close()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_queue_byte_and_decoded_image_actual_boundaries() -> None:
    """8MiB queued bytes and 16MiB decoded images use actual serialized/decoded sizes."""
    runtime = ClaudeSDKRuntime()
    empty = ClaudeTextEventDAO(session_id="s", invocation_id="i", response_id="r", sequence=1, text="")
    event = empty.model_copy(update={"text": "x" * (8 * 1024 * 1024 - len(empty.model_dump_json().encode()))})
    runtime._queue_event(event=event)
    assert runtime._queued_bytes == 8 * 1024 * 1024
    with pytest.raises(ClaudeBridgeError) as error:
        runtime._queue_event(event=empty.model_copy(update={"sequence": 2}))
    assert error.value.code == "buffer_limit_exceeded"
    encoded = base64.b64encode(b"x" * (16 * 1024 * 1024)).decode()
    assert ClaudeImageDAO(media_type="image/png", data=encoded).data == encoded
    with pytest.raises(ValidationError):
        ClaudeImageDAO(media_type="image/png", data=base64.b64encode(b"x" * (16 * 1024 * 1024 + 1)).decode())
