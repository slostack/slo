"""Per-response usage, host translation and ping/cut-off rules (101.a.3 steps 2)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.bridges.claude.host_usage import ClaudeHostUsage
from src.bridges.claude.sdk.dao import ClaudeUsageDAO
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.sdk.response import NativeFragment, NativeResponseAssembly

FULL_USAGE: dict[str, int] = {
    "input_tokens": 10,
    "output_tokens": 1,
    "cache_creation_input_tokens": 2,
    "cache_read_input_tokens": 5,
}


def start(*, assembly: NativeResponseAssembly, identity: str, usage: Optional[dict[str, Any]]) -> None:
    """Open one response, with or without start-time usage."""
    message: dict[str, Any] = {"id": identity, "role": "assistant"}
    if usage is not None:
        message["usage"] = usage
    assembly.consume(event={"type": "message_start", "message": message})


def test_message_delta_overwrites_only_the_fields_it_carries() -> None:
    """Counts are cumulative: the last value per field wins, absent fields stay."""
    assembly = NativeResponseAssembly()
    start(assembly=assembly, identity="one", usage=FULL_USAGE)
    assert assembly.usage == ClaudeUsageDAO(
        input_tokens=10, output_tokens=1, cache_read_tokens=5, cache_write_tokens=2
    )
    assembly.consume(
        event={"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 40}}
    )
    assert assembly.usage == ClaudeUsageDAO(
        input_tokens=10, output_tokens=40, cache_read_tokens=5, cache_write_tokens=2
    )


def test_present_but_malformed_delta_field_becomes_unknown_absent_field_is_kept() -> None:
    """A bad cumulative value must not leave a stale start placeholder reported as a real count."""
    assembly = NativeResponseAssembly()
    start(assembly=assembly, identity="one", usage=FULL_USAGE)
    assembly.consume(
        event={
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": -1, "cache_read_input_tokens": "x"},
        }
    )
    assert assembly.usage == ClaudeUsageDAO(input_tokens=10, cache_write_tokens=2)


def test_usage_resets_for_every_response() -> None:
    """A response that reports nothing never inherits the previous response's counts."""
    assembly = NativeResponseAssembly()
    start(assembly=assembly, identity="one", usage=FULL_USAGE)
    assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
    assembly.consume(event={"type": "message_stop"})
    start(assembly=assembly, identity="two", usage=None)
    assert assembly.usage == ClaudeUsageDAO()


@pytest.mark.parametrize("bad", [-1, "x", True, 1.5, None, [1]])
def test_malformed_values_stay_unknown_without_error(bad: Any) -> None:
    """Usage is telemetry: a bad field is None, other fields survive, nothing raises."""
    assembly = NativeResponseAssembly()
    start(assembly=assembly, identity="one", usage={**FULL_USAGE, "input_tokens": bad})
    assert assembly.usage == ClaudeUsageDAO(output_tokens=1, cache_read_tokens=5, cache_write_tokens=2)
    assembly.consume(
        event={"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": "not-an-object"}
    )
    assert assembly.usage.output_tokens == 1


def test_host_usage_counts_cache_inside_input_like_direct_anthropic() -> None:
    """input_tokens includes cache read and write; details carry only the known keys."""
    usage = ClaudeUsageDAO(input_tokens=10, output_tokens=7, cache_read_tokens=5, cache_write_tokens=2)
    assert ClaudeHostUsage.translate(usage=usage) == {
        "input_tokens": 17,
        "output_tokens": 7,
        "total_tokens": 24,
        "input_token_details": {"cache_read": 5, "cache_creation": 2},
    }
    assert ClaudeHostUsage.translate(usage=ClaudeUsageDAO(input_tokens=10, output_tokens=7)) == {
        "input_tokens": 10,
        "output_tokens": 7,
        "total_tokens": 17,
    }
    assert ClaudeHostUsage.translate(
        usage=ClaudeUsageDAO(input_tokens=10, output_tokens=7, cache_read_tokens=0)
    ) == {
        "input_tokens": 10,
        "output_tokens": 7,
        "total_tokens": 17,
        "input_token_details": {"cache_read": 0},
    }


@pytest.mark.parametrize(
    "usage",
    [None, ClaudeUsageDAO(), ClaudeUsageDAO(input_tokens=1), ClaudeUsageDAO(output_tokens=1)],
)
def test_host_usage_is_absent_when_input_or_output_is_unknown(usage: Optional[ClaudeUsageDAO]) -> None:
    """Honest 'unavailable': no partial usage_metadata is invented."""
    assert ClaudeHostUsage.translate(usage=usage) is None


def test_ping_is_ignored_before_between_and_after_responses() -> None:
    """A ping never changes openness, text or usage, wherever it lands."""
    assembly = NativeResponseAssembly()
    ignored = NativeFragment(text="", boundary=False)
    assert assembly.consume(event={"type": "ping"}) == ignored
    start(assembly=assembly, identity="one", usage=FULL_USAGE)
    assert assembly.consume(event={"type": "ping"}) == ignored
    assembly.consume(
        event={"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    assembly.consume(
        event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}
    )
    assert assembly.consume(event={"type": "ping"}) == ignored
    assembly.consume(event={"type": "content_block_stop", "index": 0})
    assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
    assembly.consume(event={"type": "message_stop"})
    assert assembly.consume(event={"type": "ping"}) == ignored
    assert assembly.text == "hi"
    assert assembly.usage.input_tokens == 10


@pytest.mark.parametrize("kind", ["text", "tool_use"])
def test_stop_without_message_delta_fails_closed_without_calls_or_usage(kind: str) -> None:
    """A cut-off response (text-only or tool_use) is a protocol failure: nothing committed."""
    assembly = NativeResponseAssembly()
    start(assembly=assembly, identity="one", usage=FULL_USAGE)
    block: dict[str, Any] = (
        {"type": "text", "text": ""}
        if kind == "text"
        else {"type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {}}
    )
    assembly.consume(event={"type": "content_block_start", "index": 0, "content_block": block})
    if kind == "text":
        assembly.consume(
            event={"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}
        )
    assembly.consume(event={"type": "content_block_stop", "index": 0})
    with pytest.raises(ClaudeBridgeError) as caught:
        assembly.consume(event={"type": "message_stop"})
    assert caught.value.code == "stream_protocol_failed"
    assert assembly.calls == ()
    with pytest.raises(ClaudeBridgeError):
        assembly.validate_terminal()
