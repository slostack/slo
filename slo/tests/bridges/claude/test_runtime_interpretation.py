"""Interpretation rejects invalid stream events without lifecycle side effects."""

import pytest
from claude_agent_sdk import StreamEvent

from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.sdk.response import NativeResponseAssembly
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime


def test_unopened_stream_rejects_stop_before_publication() -> None:
    """A private interpretation seam cannot turn an unstarted response into a boundary."""
    runtime: ClaudeSDKRuntime = ClaudeSDKRuntime()
    assembly: NativeResponseAssembly = NativeResponseAssembly()
    message: StreamEvent = StreamEvent(
        uuid="event", session_id="native", event={"type": "message_stop"}, parent_tool_use_id=None
    )
    with pytest.raises(ClaudeBridgeError) as failure:
        runtime._interpret_stream_event(message=message, assembly=assembly)
    assert failure.value.code == "stream_protocol_failed"
    assert assembly.calls == ()
