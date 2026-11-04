"""Unsafe native boundaries must not reach the real graph executor."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.cli.headless import HeadlessRunner


class InvalidBoundaryTransport(ScriptedClaudeTransport):
    """Emit malformed native responses through the official SDK parser."""

    def __init__(self, *, fault: str) -> None:
        """Select a finite protocol violation, without opening native I/O."""
        super().__init__()
        self.fault = fault

    async def write(self, data: str) -> None:
        """Answer control requests but never dispatch a real filesystem callback."""
        message = json.loads(data)
        if message["type"] != "user":
            await super().write(data=data)
            return
        self.prompts.append(message["message"]["content"])
        start = {"type": "message_start", "message": {"id": "response", "role": "assistant"}}
        block = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "native-call",
                "name": "mcp__slo__read",
                "input": {"path": "missing"},
            },
        }
        events: list[dict[str, Any]] = [start, block]
        if self.fault.startswith("nonfinite-"):
            number = self.fault.removeprefix("nonfinite-")
            events.extend([
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta",
                           "partial_json": '{"path": "missing", "nested": [' + number + ']}'}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ])
        elif self.fault == "retention-limit":
            events.append({
                "type": "content_block_stop", "index": 0,
            })
            events.append({
                "type": "content_block_start", "index": 1,
                "content_block": {"type": "thinking", "thinking": "", "signature": "x" * (8 * 1024 * 1024)},
            })
        elif self.fault == "malformed-delta":
            events.append({"type": "content_block_delta", "index": 0, "delta": None})
        elif self.fault in {
            "unknown-raw-block", "mixed-raw-block", "malformed-raw-content", "malformed-raw-block",
        }:
            events.extend([
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ])
        elif self.fault == "overlap":
            events.append(start)
        elif self.fault == "duplicate-index":
            events.append(block)
        elif self.fault == "delta-after-stop":
            events.extend(
                [
                    {"type": "content_block_stop", "index": 0},
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "input_json_delta", "partial_json": "{}"},
                    },
                ]
            )
        elif self.fault == "unknown-stop":
            events.append({"type": "content_block_stop", "index": 9})
        elif self.fault == "max-tokens":
            events.extend(
                [
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
                    {"type": "message_stop"},
                ]
            )
        elif self.fault in {"malformed-json", "duplicate-id", "forbidden-mixed"}:
            if self.fault == "malformed-json":
                events.append(
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "input_json_delta", "partial_json": "{"},
                    }
                )
            events.append({"type": "content_block_stop", "index": 0})
            if self.fault != "malformed-json":
                events.extend(
                    [
                        {
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {
                                "type": "tool_use",
                                "id": "native-call" if self.fault == "duplicate-id" else "forbidden",
                                "name": "mcp__slo__read" if self.fault == "duplicate-id" else "Bash",
                                "input": {},
                            },
                        },
                        {"type": "content_block_stop", "index": 1},
                    ]
                )
            events.extend(
                [{"type": "message_delta", "delta": {"stop_reason": "tool_use"}}, {"type": "message_stop"}]
            )
        elif self.fault == "unfinished-block":
            events.append({"type": "message_stop"})
        elif self.fault in {
            "identity-false", "identity-zero", "identity-list", "identity-dict",
            "boolean-true", "boolean-false", "wire-stopped", "wire-partial",
            "stream-session", "stream-parent", "echo-session", "echo-parent",
        }:
            if self.fault.startswith("wire-"):
                field = "stopped" if self.fault == "wire-stopped" else "partial_json"
                block["content_block"][field] = True if self.fault == "wire-stopped" else "{}"
            if self.fault.startswith("boolean-"):
                block["content_block"]["input"] = {"nested": [self.fault == "boolean-true"]}
            events.extend([
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ])
        elif self.fault != "terminal-before-stop":
            raise AssertionError(self.fault)
        for event in events:
            envelope = {
                "type": "stream_event", "uuid": "synthetic", "session_id": "native-test", "event": event,
            }
            if event["type"] == "message_stop":
                if self.fault in {
                    "unknown-raw-block", "mixed-raw-block", "malformed-raw-content", "malformed-raw-block",
                }:
                    content = [{"type": "future_block", "payload": "not corroborated"}]
                    if self.fault == "mixed-raw-block":
                        content.insert(0, block["content_block"])
                    if self.fault == "malformed-raw-content":
                        content = None
                    if self.fault == "malformed-raw-block":
                        content = [None]
                    await self.messages.put({
                        "type": "assistant", "uuid": "raw-echo",
                        "message": {"id": "response", "model": "claude", "content": content},
                    })
                if self.fault.startswith("identity-"):
                    identities: dict[str, Any] = {
                        "identity-false": False, "identity-zero": 0,
                        "identity-list": [], "identity-dict": {},
                    }
                    await self.messages.put({
                        "type": "assistant", "uuid": "invalid-identity",
                        "message": {"id": identities[self.fault], "model": "claude",
                                    "content": [block["content_block"]]},
                    })
                if self.fault == "stream-session":
                    envelope["session_id"] = "wrong-native"
                if self.fault == "stream-parent":
                    envelope["parent_tool_use_id"] = "child"
                if self.fault.startswith(("boolean-", "echo-")):
                    echoed = dict(block["content_block"])
                    if self.fault.startswith("boolean-"):
                        echoed["input"] = {"nested": [1 if self.fault == "boolean-true" else 0]}
                    await self.messages.put({
                        "type": "assistant", "uuid": "echo",
                        "session_id": "wrong-native" if self.fault == "echo-session" else "native-test",
                        "parent_tool_use_id": "child" if self.fault == "echo-parent" else None,
                        "message": {"id": "response", "model": "claude", "content": [echoed]},
                    })
            await self.messages.put(envelope)
        await self.messages.put(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 1,
                "duration_api_ms": 1,
                "num_turns": 1,
                "session_id": "native-test",
                "result": "",
            }
        )


@pytest.mark.parametrize(
    "fault",
    [
        "identity-false", "identity-zero", "identity-list", "identity-dict",
        "nonfinite-NaN", "nonfinite-Infinity", "nonfinite--Infinity",
        "nonfinite-1e400", "nonfinite--1e400",
        "retention-limit", "malformed-delta", "unknown-raw-block", "mixed-raw-block",
        "malformed-raw-content", "malformed-raw-block",
        "boolean-true", "boolean-false", "wire-stopped", "wire-partial",
        "stream-session", "stream-parent", "echo-session", "echo-parent",
        "overlap",
        "duplicate-index",
        "delta-after-stop",
        "unknown-stop",
        "max-tokens",
        "unfinished-block",
        "terminal-before-stop",
        "malformed-json",
        "duplicate-id",
        "forbidden-mixed",
    ],
)
async def test_incomplete_tool_response_never_executes_or_completes(
    fault: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """EF14-01: entry/graph/history observe failure and zero executable publication."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = InvalidBoundaryTransport(fault=fault)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="invalid-boundary",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Preserve the real factory, model, graph, executor and persistence."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(prompt="Read project")
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="invalid-boundary"
    )
    assert not any(e.kind in {"tool_call", "tool_result", "run_completed"} for e in events), events
    assert not any(e["kind"] in {"tool_call", "tool_result", "run_completed"} for e in output), output
    if fault.startswith(("identity-", "nonfinite-")):
        failure = next(e.payload.error_message for e in events if e.kind == "run_failed")
        assert "Malformed or unfinished Claude response." in failure
        assert len(failure) < 256
    assert code != 0
    assert sum(e.kind == "run_failed" for e in events) == 1
    if fault == "retention-limit":
        assert "reconciliation limit" in next(e.payload.error_message for e in events if e.kind == "run_failed")
    assert transport.prompts == ["Read project"]
    assert transport.close_calls == 1
