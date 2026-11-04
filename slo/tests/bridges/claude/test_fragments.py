"""Response fragment regressions through the official SDK parser."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from claude_agent_sdk import AssistantMessage
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.cli.headless import HeadlessRunner
from claude_agent_sdk._internal.message_parser import parse_message
import pytest

from src.bridges.claude.sdk.response import NativeResponseAssembly
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError


def echo(*, response_id: Any, content: list[dict[str, Any]], uuid: str = "fragment") -> AssistantMessage:
    """Parse native identity and block fields rather than inventing SDK attributes."""
    message = parse_message(
        {
            "type": "assistant",
            "uuid": uuid,
            "message": {
                "id": response_id,
                "model": "claude",
                "content": content,
            },
        }
    )
    assert isinstance(message, AssistantMessage)
    return message


def test_early_fragments_validate_once_at_complete_boundary() -> None:
    """CF01/02/03: individual blocks, duplicate echoes and late echoes add no output."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    blocks = [
        {"type": "thinking", "thinking": "plan", "signature": "signed"},
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {"path": "a"}},
        {"type": "tool_use", "id": "b", "name": "mcp__slo__read", "input": {"path": "b"}},
    ]
    for index, block in enumerate(blocks):
        assembly.consume(event={"type": "content_block_start", "index": index, "content_block": block})
        fragment = echo(response_id="one", content=[block], uuid=str(index))
        assembly.reconcile_echo(message=fragment)
        assembly.reconcile_echo(message=fragment)
        assert assembly.calls == ()
        assembly.consume(event={"type": "content_block_stop", "index": index})
    assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
    assert assembly.consume(event={"type": "message_stop"}) == ("", True)
    assert [call.tool_call_id for call in assembly.calls] == ["a", "b"]
    assert assembly.text == "hello"
    assembly.consume(event={"type": "message_start", "message": {"id": "two"}})
    assembly.reconcile_echo(message=echo(response_id="one", content=blocks, uuid="late"))
    assert assembly.calls == ()
    assert assembly.text == ""


@pytest.mark.parametrize("fault", ["text", "identity", "uuid", "unfinished"])
def test_conflicting_or_unfinished_fragments_do_not_publish_calls(fault: str) -> None:
    """CF04: deferred reconciliation never makes incomplete streams executable."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    block = {"type": "text", "text": "hello"}
    assembly.consume(event={"type": "content_block_start", "index": 0, "content_block": block})
    with pytest.raises(ClaudeBridgeError):
        assembly.reconcile_echo(message=echo(response_id="one", content=[block]))
        if fault == "unfinished":
            assembly.validate_terminal()
        else:
            assembly.reconcile_echo(
                message=echo(
                    response_id="unknown" if fault == "identity" else "one",
                    content=[{"type": "text", "text": "wrong"}],
                    uuid="fragment" if fault == "uuid" else "other",
                )
            )
            assembly.consume(event={"type": "content_block_stop", "index": 0})
            assembly.consume(event={"type": "message_stop"})
    assert assembly.calls == ()


@pytest.mark.parametrize("response_id", [False, 0, [], {}, True, 1, ["one"], {"id": "one"}])
def test_supplied_non_string_echo_identity_rejects(response_id: Any) -> None:
    """R4: official parsing must not turn malformed identity into current-response fallback."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    with pytest.raises(ClaudeBridgeError) as caught:
        assembly.reconcile_echo(message=echo(response_id=response_id, content=[]))
    assert caught.value.code == "stream_protocol_failed"
    assert assembly.calls == ()


@pytest.mark.parametrize("response_id", [None, ""])
def test_legacy_echo_identity_falls_back_to_current_response(response_id: Any) -> None:
    """R4: absent and empty identities retain legacy compatibility."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    block = {"type": "text", "text": "hello"}
    assembly.consume(event={"type": "content_block_start", "index": 0, "content_block": block})
    assembly.reconcile_echo(message=echo(response_id=response_id, content=[block]))
    assembly.consume(event={"type": "content_block_stop", "index": 0})
    assert assembly.consume(event={"type": "message_stop"}) == ("", True)
    assert assembly.text == "hello"


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
def test_nonfinite_delta_arguments_reject_without_echo(number: str) -> None:
    """R5: nested nonfinite JSON must never become executable, even without an echo."""
    assembly = streamed_tool_arguments(partial_json='{"nested": [{"value": ' + number + '}]}')
    with pytest.raises(ClaudeBridgeError) as caught:
        assembly.consume(event={"type": "message_stop"})
    assert caught.value.code == "stream_protocol_failed"
    assert str(caught.value) == "Malformed or unfinished Claude response."
    assert assembly.calls == ()


def test_finite_delta_arguments_publish_without_echo() -> None:
    """R5: strict validation preserves nested finite JSON values and types."""
    arguments = {"nested": [None, True, False, 0, 1.25, 1e300, "NaN", {"value": -2}]}
    assembly = streamed_tool_arguments(partial_json=json.dumps(arguments))
    assert assembly.consume(event={"type": "message_stop"}) == ("", True)
    assert len(assembly.calls) == 1
    assert assembly.calls[0].arguments == arguments


def streamed_tool_arguments(*, partial_json: str) -> NativeResponseAssembly:
    """Build a stopped tool block with no assistant echo, awaiting publication."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    assembly.consume(event={
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {}},
    })
    assembly.consume(event={
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": partial_json},
    })
    assembly.consume(event={"type": "content_block_stop", "index": 0})
    assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
    assert assembly.calls == ()
    return assembly


class FragmentTransport(ToolRoundTransport):
    """Add early native echoes to the existing multi-tool SDK wire journey."""

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Echo each completed payload before block stop, including duplicate delivery."""
        response_id = ""
        block: dict[str, Any] = {}
        partial = ""
        async for message in super().read_messages():
            event = message.get("event", {})
            if event.get("type") == "message_start":
                response_id = event["message"]["id"]
            if event.get("type") == "content_block_start":
                block = dict(event["content_block"])
                partial = ""
            if event.get("type") == "content_block_delta":
                delta = event["delta"]
                partial += delta.get("partial_json", "")
                if delta["type"] == "text_delta":
                    block["text"] += delta["text"]
            if event.get("type") == "content_block_stop":
                if partial:
                    block["input"] = json.loads(partial)
                # Supported block metadata is intentionally outside corroboration.
                block["vendor_metadata"] = {"opaque": True}
                fragment = {
                    "type": "assistant",
                    "uuid": f"{response_id}-{event['index']}",
                    "message": {"id": response_id, "model": "claude", "content": [block]},
                }
                yield fragment
                yield fragment
            yield message


async def test_early_fragments_cross_sdk_graph_tools_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CF05: one query, three responses, four real tools, no duplicate persisted calls."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "model.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("default-model = synthetic-model\n")
    transport = FragmentTransport(path=target, multiple_rounds=True)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="fragments",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Retain production orchestration and persistence; replace vendor I/O only."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(prompt="Read project")
    output = capsys.readouterr().out
    assert code == 0, output
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="fragments"
    )
    assert sum(e.kind == "tool_call" for e in events) == 4
    assert sum(e.kind == "tool_result" for e in events) == 4
    assert sum(e.kind == "run_completed" for e in events) == 1
    assert [e.payload.content for e in events if e.kind == "assistant_message"] == ["Hello bridge"]
    assert len(transport.tool_results) == 4
    assert transport.prompts == ["Read project"]
    assert transport.close_calls == 1


@pytest.mark.parametrize("value,changed", [(True, 1), (False, 0)])
@pytest.mark.parametrize("replay", [False, True])
def test_json_boolean_conflict(value: bool, changed: int, replay: bool) -> None:
    """CF04/R1: nested JSON booleans are not numbers, including UUID replays."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    block = {"type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {"nested": [value]}}
    assembly.consume(event={"type": "content_block_start", "index": 0, "content_block": block})
    assembly.reconcile_echo(message=echo(response_id="one", content=[block]))
    changed_block = {**block, "input": {"nested": [changed]}}
    with pytest.raises(ClaudeBridgeError):
        assembly.reconcile_echo(
            message=echo(
                response_id="one", content=[changed_block], uuid="fragment" if replay else "other"
            )
        )
        assembly.consume(event={"type": "content_block_stop", "index": 0})
        assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
        assembly.consume(event={"type": "message_stop"})
    assert assembly.calls == ()


@pytest.mark.parametrize("field,value", [("stopped", True), ("partial_json", "{}")])
def test_wire_cannot_set_bookkeeping(field: str, value: object) -> None:
    """CF04/R3: wire fields cannot manufacture internal completion state."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    with pytest.raises(ClaudeBridgeError):
        assembly.consume(
            event={
                "type": "content_block_start", "index": 0,
                "content_block": {
                    "type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {}, field: value,
                },
            }
        )
    assert assembly.calls == ()


@pytest.mark.parametrize("source", ["snapshot", "pending", "uuid", "thinking", "signature"])
def test_retention_budget_rejects_before_publication(source: str) -> None:
    """CF06: all retained data shares a finite invocation admission budget."""
    assembly = NativeResponseAssembly(max_retained_bytes=2048)
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    with pytest.raises(ClaudeBridgeError, match="limit"):
        if source in {"pending", "uuid"}:
            for index in range(30):
                assembly.reconcile_echo(
                    message=echo(
                        response_id="one", content=[{"type": "text", "text": "x" * 100}],
                        uuid=str(index) if source == "uuid" else "",
                    )
                )
        elif source == "snapshot":
            for index in range(30):
                assembly.consume(
                    event={"type": "content_block_start", "index": 0,
                           "content_block": {"type": "text", "text": "x" * 100}}
                )
                assembly.consume(event={"type": "content_block_stop", "index": 0})
                assembly.consume(event={"type": "message_stop"})
                assembly.consume(event={"type": "message_start", "message": {"id": str(index)}})
        else:
            assembly.consume(
                event={"type": "content_block_start", "index": 0,
                       "content_block": {"type": "thinking", "thinking": "", "signature": ""}}
            )
            assembly.consume(
                event={"type": "content_block_delta", "index": 0,
                       "delta": {"type": source + "_delta", source: "x" * 2048}}
            )
    assert assembly.calls == ()


def test_missing_metadata_does_not_clear_native_scope() -> None:
    """CF06/R2: legacy omissions bind current response, never reset native scope."""
    assembly = NativeResponseAssembly()
    assembly.validate_scope(session_id=None, parent_tool_use_id=None)
    assembly.validate_scope(session_id="native", parent_tool_use_id=None)
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    assembly.reconcile_echo(message=echo(response_id="", content=[], uuid=""))
    assembly.validate_scope(session_id=None, parent_tool_use_id=None)
    assembly.validate_scope(session_id="native", parent_tool_use_id=None)
    with pytest.raises(ClaudeBridgeError):
        assembly.validate_scope(session_id="other", parent_tool_use_id=None)


@pytest.mark.parametrize(
    "fault", ["name", "arguments", "thinking", "signature", "order", "multiplicity", "late", "missing-id"]
)
def test_fragment_conflict_matrix(fault: str) -> None:
    """CF03/04: exact ordered block corroboration rejects changed or misbound echoes."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    blocks = [
        {"type": "thinking", "thinking": "plan", "signature": "signed"},
        {"type": "text", "text": "same"},
        {"type": "text", "text": "same"},
        {"type": "tool_use", "id": "a", "name": "mcp__slo__read", "input": {"path": "a"}},
    ]
    for index, block in enumerate(blocks):
        assembly.consume(event={"type": "content_block_start", "index": index, "content_block": block})
        assembly.consume(event={"type": "content_block_stop", "index": index})
        # Individual then cumulative echoes, including identical content blocks.
        assembly.reconcile_echo(message=echo(response_id="one", content=[block], uuid=f"single-{index}"))
        assembly.reconcile_echo(
            message=echo(response_id="one", content=blocks[: index + 1], uuid=f"cumulative-{index}")
        )
    changed = [dict(block) for block in blocks]
    if fault == "name":
        changed[-1]["name"] = "mcp__slo__ls"
    elif fault == "arguments":
        changed[-1]["input"] = {"path": "different"}
    elif fault in {"thinking", "signature"}:
        changed[0][fault] = "different"
    elif fault == "order":
        changed.reverse()
    elif fault == "multiplicity":
        changed.insert(1, blocks[1])
    else:
        changed[1]["text"] = "different"
    if fault in {"late", "missing-id"}:
        assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
        assembly.consume(event={"type": "message_stop"})
        assembly.consume(event={"type": "message_start", "message": {"id": "two"}})
    with pytest.raises(ClaudeBridgeError):
        assembly.reconcile_echo(
            message=echo(response_id="" if fault == "missing-id" else "one", content=changed, uuid="changed")
        )
        if fault != "missing-id":
            assembly.consume(event={"type": "message_delta", "delta": {"stop_reason": "tool_use"}})
        assembly.consume(event={"type": "message_stop"})
    assert assembly.calls == ()


def test_completed_snapshots_share_budget_across_responses() -> None:
    """CF06: two individually admissible snapshots exhaust one invocation budget."""
    assembly = NativeResponseAssembly(max_retained_bytes=6000)
    for identity in ("one", "two"):
        assembly.consume(event={"type": "message_start", "message": {"id": identity}})
        assembly.consume(event={"type": "content_block_start", "index": 0,
                                "content_block": {"type": "text", "text": "x" * 100}})
        assembly.consume(event={"type": "content_block_stop", "index": 0})
        assert assembly.consume(event={"type": "message_stop"}) == ("", True)
    # Old snapshots still corroborate after the second response, without eviction.
    assembly.reconcile_echo(
        message=echo(response_id="one", content=[{"type": "text", "text": "x" * 100}], uuid="")
    )
    with pytest.raises(ClaudeBridgeError, match="limit"):
        assembly.reconcile_echo(
            message=echo(response_id="two", content=[{"type": "text", "text": "x" * 100}], uuid="")
        )
    assert assembly.calls == ()


def test_distinct_pending_fragments_share_budget_without_uuid() -> None:
    """CF06: unique pending content accumulates independently of delivery IDs."""
    assembly = NativeResponseAssembly(max_retained_bytes=4000)
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    for text in ("a" * 100, "b" * 100):
        assembly.reconcile_echo(
            message=echo(response_id="one", content=[{"type": "text", "text": text}], uuid="")
        )
    assert assembly.calls == ()
    with pytest.raises(ClaudeBridgeError, match="limit"):
        assembly.reconcile_echo(
            message=echo(response_id="one", content=[{"type": "text", "text": "c" * 100}], uuid="")
        )


@pytest.mark.parametrize("kind,delta", [
    ("text", None), ("text", []), ("text", {}),
    ("text", {"type": "text_delta", "text": 1}),
    ("tool_use", {"type": "input_json_delta", "partial_json": {}}),
    ("thinking", {"type": "thinking_delta", "thinking": None}),
    ("thinking", {"type": "signature_delta", "signature": []}),
    ("text", {"type": "input_json_delta", "partial_json": "{}"}),
])
def test_malformed_block_deltas_are_protocol_failures(kind: str, delta: Any) -> None:
    """CF04: malformed containers, payloads and cross-kind deltas fail boundedly."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    assembly.consume(event={"type": "content_block_start", "index": 0, "content_block": {"type": kind}})
    with pytest.raises(ClaudeBridgeError) as failure:
        assembly.consume(event={"type": "content_block_delta", "index": 0, "delta": delta})
    assert failure.value.code == "stream_protocol_failed"
    assert assembly.calls == ()


@pytest.mark.parametrize("delta", [None, [], {}, {"stop_reason": []}, {"stop_reason": 7}])
def test_malformed_message_deltas_are_protocol_failures(delta: Any) -> None:
    """CF04: message delta shapes reject before completing a response."""
    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "one"}})
    with pytest.raises(ClaudeBridgeError) as failure:
        assembly.consume(event={"type": "message_delta", "delta": delta})
    assert failure.value.code == "stream_protocol_failed"
