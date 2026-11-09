"""Unsafe native boundaries must not reach the real graph executor."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport, scripted_adapter_class
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.cli.headless import HeadlessRunner

BUILTIN_INPUT: dict[str, Any] = {"command": "ls"}


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
        block: dict[str, Any] = {
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
            events.extend(
                [
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": '{"path": "missing", "nested": [' + number + "]}",
                        },
                    },
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                    {"type": "message_stop"},
                ]
            )
        elif self.fault == "retention-limit":
            events.append(
                {
                    "type": "content_block_stop",
                    "index": 0,
                }
            )
            events.append(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "thinking",
                        "thinking": "",
                        "signature": "x" * (8 * 1024 * 1024),
                    },
                }
            )
        elif self.fault == "malformed-delta":
            events.append({"type": "content_block_delta", "index": 0, "delta": None})
        elif self.fault in {
            "unknown-raw-block",
            "mixed-raw-block",
            "malformed-raw-content",
            "malformed-raw-block",
        }:
            events.extend(
                [
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                    {"type": "message_stop"},
                ]
            )
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
        elif self.fault in {"malformed-json", "duplicate-id"}:
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
                                "id": "native-call",
                                "name": "mcp__slo__read",
                                "input": {},
                            },
                        },
                        {"type": "content_block_stop", "index": 1},
                    ]
                )
            events.extend(
                [{"type": "message_delta", "delta": {"stop_reason": "tool_use"}}, {"type": "message_stop"}]
            )
        elif self.fault in {"mixed-malformed-builtin", "mixed-conflicting-builtin-echo"}:
            # A valid Slo read plus a Bash attempt that makes the whole response unsafe.
            malformed = self.fault == "mixed-malformed-builtin"
            events.extend(
                [
                    {"type": "content_block_stop", "index": 0},
                    {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {
                            "type": "tool_use",
                            "id": "builtin-call",
                            "name": "Bash",
                            "input": {} if malformed else BUILTIN_INPUT,
                        },
                    },
                    *(
                        [
                            {
                                "type": "content_block_delta",
                                "index": 1,
                                "delta": {"type": "input_json_delta", "partial_json": "{"},
                            }
                        ]
                        if malformed
                        else []
                    ),
                    {"type": "content_block_stop", "index": 1},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                    {"type": "message_stop"},
                ]
            )
        elif self.fault == "unfinished-block":
            events.append({"type": "message_stop"})
        elif self.fault in {
            "identity-false",
            "identity-zero",
            "identity-list",
            "identity-dict",
            "boolean-true",
            "boolean-false",
            "wire-stopped",
            "wire-partial",
            "stream-session",
            "stream-parent",
            "echo-session",
            "echo-parent",
        }:
            if self.fault.startswith("wire-"):
                field = "stopped" if self.fault == "wire-stopped" else "partial_json"
                block["content_block"][field] = True if self.fault == "wire-stopped" else "{}"
            if self.fault.startswith("boolean-"):
                block["content_block"]["input"] = {"nested": [self.fault == "boolean-true"]}
            events.extend(
                [
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                    {"type": "message_stop"},
                ]
            )
        elif self.fault != "terminal-before-stop":
            raise AssertionError(self.fault)
        for event in events:
            envelope = {
                "type": "stream_event",
                "uuid": "synthetic",
                "session_id": "native-test",
                "event": event,
            }
            if event["type"] == "message_stop":
                if self.fault in {
                    "unknown-raw-block",
                    "mixed-raw-block",
                    "malformed-raw-content",
                    "malformed-raw-block",
                }:
                    content: list[dict[str, Any] | None] | None = [
                        {"type": "future_block", "payload": "not corroborated"}
                    ]
                    if self.fault == "mixed-raw-block":
                        content = [
                            block["content_block"],
                            {"type": "future_block", "payload": "not corroborated"},
                        ]
                    if self.fault == "malformed-raw-content":
                        content = None
                    if self.fault == "malformed-raw-block":
                        content = [None]
                    await self.messages.put(
                        {
                            "type": "assistant",
                            "uuid": "raw-echo",
                            "message": {"id": "response", "model": "claude", "content": content},
                        }
                    )
                if self.fault.startswith("identity-"):
                    identities: dict[str, Any] = {
                        "identity-false": False,
                        "identity-zero": 0,
                        "identity-list": [],
                        "identity-dict": {},
                    }
                    await self.messages.put(
                        {
                            "type": "assistant",
                            "uuid": "invalid-identity",
                            "message": {
                                "id": identities[self.fault],
                                "model": "claude",
                                "content": [block["content_block"]],
                            },
                        }
                    )
                if self.fault == "mixed-conflicting-builtin-echo":
                    conflicting = {
                        "type": "tool_use",
                        "id": "builtin-call",
                        "name": "Bash",
                        "input": {"command": "pwd"},
                    }
                    await self.messages.put(
                        {
                            "type": "assistant",
                            "uuid": "mixed-echo",
                            "message": {
                                "id": "response",
                                "model": "claude",
                                "content": [block["content_block"], conflicting],
                            },
                        }
                    )
                if self.fault == "stream-session":
                    envelope["session_id"] = "wrong-native"
                if self.fault == "stream-parent":
                    envelope["parent_tool_use_id"] = "child"
                if self.fault.startswith(("boolean-", "echo-")):
                    echoed = dict(block["content_block"])
                    if self.fault.startswith("boolean-"):
                        echoed["input"] = {"nested": [1 if self.fault == "boolean-true" else 0]}
                    await self.messages.put(
                        {
                            "type": "assistant",
                            "uuid": "echo",
                            "session_id": "wrong-native" if self.fault == "echo-session" else "native-test",
                            "parent_tool_use_id": "child" if self.fault == "echo-parent" else None,
                            "message": {"id": "response", "model": "claude", "content": [echoed]},
                        }
                    )
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
        "identity-false",
        "identity-zero",
        "identity-list",
        "identity-dict",
        "nonfinite-NaN",
        "nonfinite-Infinity",
        "nonfinite--Infinity",
        "nonfinite-1e400",
        "nonfinite--1e400",
        "retention-limit",
        "malformed-delta",
        "unknown-raw-block",
        "mixed-raw-block",
        "malformed-raw-content",
        "malformed-raw-block",
        "boolean-true",
        "boolean-false",
        "wire-stopped",
        "wire-partial",
        "stream-session",
        "stream-parent",
        "echo-session",
        "echo-parent",
        "overlap",
        "duplicate-index",
        "delta-after-stop",
        "unknown-stop",
        "max-tokens",
        "unfinished-block",
        "terminal-before-stop",
        "malformed-json",
        "duplicate-id",
        "mixed-malformed-builtin",
        "mixed-conflicting-builtin-echo",
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
    if fault.startswith(("identity-", "nonfinite-", "mixed-")):
        failure = next(e.payload.error_message for e in events if e.kind == "run_failed")
        assert failure is not None
        assert "Malformed or unfinished Claude response." in failure
        assert len(failure) < 256
    assert code != 0
    assert sum(e.kind == "run_failed" for e in events) == 1
    if fault == "retention-limit":
        failure = next(e.payload.error_message for e in events if e.kind == "run_failed")
        assert failure is not None and "reconciliation limit" in failure
    assert transport.prompts == ["Read project"]
    assert transport.close_calls == 1


class RefusedBuiltinTransport(ScriptedClaudeTransport):
    """Script a refused built-in attempt, the CLI's error tool result, then a text answer."""

    async def write(self, data: str) -> None:
        """Answer control requests; on the user prompt emit the refusal then continuation."""
        message = json.loads(data)
        if message["type"] != "user":
            await super().write(data=data)
            return
        self.prompts.append(message["message"]["content"])
        refused: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": "refused", "role": "assistant"}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "builtin-call", "name": "Bash", "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"command": "ls"}'},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
        answered: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": "answered", "role": "assistant"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "NO_BASH"},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        for event in refused:
            await self.messages.put(
                {"type": "stream_event", "uuid": "refused", "session_id": "native-test", "event": event}
            )
        # The native CLI itself answers the refused attempt; the SDK parses this as a UserMessage.
        await self.messages.put(
            {
                "type": "user",
                "uuid": "refusal-result",
                "session_id": "native-test",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "builtin-call",
                            "content": "No such tool available: bash",
                            "is_error": True,
                        }
                    ],
                },
            }
        )
        for event in answered:
            await self.messages.put(
                {"type": "stream_event", "uuid": "answered", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 1,
                "duration_api_ms": 1,
                "num_turns": 2,
                "session_id": "native-test",
                "result": "NO_BASH",
                "stop_reason": "end_turn",
                "terminal_reason": "completed",
            }
        )


async def test_refused_builtin_attempt_completes_run_without_tool_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A1/A3: a refused built-in attempt is not a Slo call; the run continues and completes once."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = RefusedBuiltinTransport()
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="refused-builtin",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Preserve the real factory, model, graph, executor and persistence."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(prompt="Run ls")
    stdout = capsys.readouterr().out
    output = [json.loads(line) for line in stdout.splitlines()]
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="refused-builtin"
    )
    assert code == 0, stdout
    assert not any(e.kind in {"tool_call", "tool_result", "run_failed"} for e in events), events
    assert not any(e["kind"] in {"tool_call", "tool_result", "run_failed"} for e in output), output
    assert sum(e.kind == "run_completed" for e in events) == 1
    assert [e.payload.content for e in events if e.kind == "assistant_message"] == ["NO_BASH"]
    assert "NO_BASH" in stdout
    assert transport.prompts == ["Run ls"]
    assert transport.close_calls == 1


class BuiltinAttemptToolRoundTransport(ToolRoundTransport):
    """Script native refusal behavior around one real Slo ``read`` round.

    ``mixed`` streams a built-in ``Bash`` attempt and the Slo read in one response.
    ``refusal-then-slo`` streams the refused ``Bash`` response first, then a second
    response whose only call is the Slo read. Both echo every block through the SDK
    and answer the built-in with the CLI's error ``tool_result``.
    """

    BUILTIN_ID = "builtin-call"
    SLO_ID = "slo-call"

    def __init__(self, *, path: Path, scenario: str, sentinel: Path) -> None:
        """Record the real file to read and a path the refused Bash command would create."""
        super().__init__(path=path)
        self.scenario = scenario
        self.sentinel = sentinel

    async def _emit_tool_round(self) -> None:
        """Emit the scripted native responses, echoes and CLI refusal before the MCP call."""
        self.round += 1
        builtin = {
            "type": "tool_use",
            "id": self.BUILTIN_ID,
            "name": "Bash",
            "input": {"command": f"touch {self.sentinel}"},
        }
        args = {"path": str(self.path)}
        slo = {"type": "tool_use", "id": self.SLO_ID, "name": "mcp__slo__read", "input": args}
        if self.scenario == "mixed":
            await self._emit_response(response_id="mixed", blocks=[builtin, slo])
            await self._emit_refusal()
        else:
            await self._emit_response(response_id="refused", blocks=[builtin])
            await self._emit_refusal()
            await self._emit_response(response_id="read", blocks=[slo])
        self._tool_request = {
            "type": "control_request",
            "request_id": "tool-rpc-1",
            "request": {
                "subtype": "mcp_message",
                "server_name": "slo",
                "message": {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tools/call",
                    "params": {
                        "name": "read",
                        "arguments": args,
                        "_meta": {"claudecode/toolUseId": self.SLO_ID},
                    },
                },
            },
        }

    async def _emit_response(self, *, response_id: str, blocks: list[dict[str, Any]]) -> None:
        """Stream complete tool_use blocks, then one SDK assistant echo per block."""
        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": response_id, "role": "assistant"}}
        ]
        for index, block in enumerate(blocks):
            events += [
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {**block, "input": {}},
                },
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
                },
                {"type": "content_block_stop", "index": index},
            ]
        events += [{"type": "message_delta", "delta": {"stop_reason": "tool_use"}}, {"type": "message_stop"}]
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "scripted", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "assistant",
                "uuid": f"echo-{response_id}",
                "message": {"id": response_id, "role": "assistant", "model": "claude", "content": blocks},
            }
        )

    async def _emit_refusal(self) -> None:
        """Emit the native CLI's error result for the refused built-in attempt."""
        await self.messages.put(
            {
                "type": "user",
                "uuid": f"refusal-{self.round}-{self.messages.qsize()}",
                "session_id": "native-test",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": self.BUILTIN_ID,
                            "content": "No such tool available: bash",
                            "is_error": True,
                        }
                    ],
                },
            }
        )


@pytest.mark.parametrize("scenario", ["mixed", "refusal-then-slo"])
async def test_refused_builtin_with_real_slo_read_executes_only_the_slo_call(
    scenario: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ER106-01/02: a Bash attempt beside a real Slo read never executes or persists; the read does."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "model.txt"
    sentinel = tmp_path / "bash-ran"
    assert project.resolve().is_relative_to(tmp_path.resolve())
    project.write_text("default-model = synthetic-model\n")
    transport = BuiltinAttemptToolRoundTransport(path=project, scenario=scenario, sentinel=sentinel)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="builtin-with-slo",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Preserve the real factory, model, graph, executor and persistence."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(prompt="Read model.txt")
    stdout = capsys.readouterr().out
    output = [json.loads(line) for line in stdout.splitlines()]
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="builtin-with-slo"
    )
    assert code == 0, stdout
    assert not sentinel.exists()
    assert transport.prompts == ["Read model.txt"]
    assert [r["request_id"] for r in transport.tool_results] == ["tool-rpc-1"]
    assert transport.tool_results[0]["response"]["mcp_response"]["result"]["content"] == [
        {"type": "text", "text": "default-model = synthetic-model\n"}
    ]
    calls = [e.payload for e in events if e.kind == "tool_call"]
    results = [e.payload for e in events if e.kind == "tool_result"]
    assert [(c.tool_call_id, c.tool_name) for c in calls] == [("slo-call", "read")]
    assert [(r.tool_call_id, r.tool_output) for r in results] == [
        ("slo-call", "default-model = synthetic-model\n")
    ]
    assert "builtin-call" not in json.dumps([e.model_dump(mode="json") for e in events])
    assert not any(e.kind == "run_failed" for e in events), events
    assert sum(e.kind == "run_completed" for e in events) == 1
    assert [e.payload.content for e in events if e.kind == "assistant_message"] == ["Hello bridge"]
    streamed_tool_ids = {e["tool_call_id"] for e in output if e["kind"].startswith("tool_call")}
    assert streamed_tool_ids == {"slo-call"}, output
    assert not any(e["kind"] == "run_failed" for e in output), output
    assert transport.close_calls == 1
