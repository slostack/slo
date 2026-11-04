"""Real headless journeys with the official SDK and a scripted wire transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Self

import pytest
from claude_agent_sdk._internal.transport import Transport

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeSessionOptionsDAO,
)
from src.cli.headless import HeadlessRunner


class ScriptedClaudeTransport(Transport):
    """Replace only native wire I/O; keep official SDK parsing/control and Slo real."""

    def __init__(
        self,
        *,
        block_response: bool = False,
        initialized_tools: tuple[str, ...] = (),
        pause_terminal: bool = False,
        model_unavailable: bool = False,
    ) -> None:
        """Allocate a bounded script and observable native submission record."""
        self.messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        self.prompts: list[str] = []
        self.connected = False
        self.closed = False
        self.block_response = block_response
        self.model_unavailable = model_unavailable
        self.submitted = asyncio.Event()
        self.fragments_sent = asyncio.Event()
        self.release_terminal = asyncio.Event()
        self.pause_terminal = pause_terminal
        self.interrupt_calls = 0
        self.close_calls = 0
        self.initialized_tools: list[str] = list(initialized_tools)
        self._emit_initialization = False

    async def connect(self) -> None:
        """Acknowledge SDK startup without launching a native executable."""
        self.connected = True

    async def write(self, data: str) -> None:
        """Answer SDK control requests and emit actual vendor wire-shaped messages."""
        message: dict[str, Any] = json.loads(data)
        if message["type"] == "control_request":
            if message["request"].get("subtype") == "interrupt":
                self.interrupt_calls += 1
            if message["request"].get("subtype") == "initialize":
                self._emit_initialization = True
            await self.messages.put(
                {
                    "type": "control_response",
                    "response": {"subtype": "success", "request_id": message["request_id"], "response": {}},
                }
            )
            return
        if message["type"] != "user":
            return
        self.prompts.append(message["message"]["content"])
        self.submitted.set()
        if self.block_response:
            return
        if self.model_unavailable:
            await self.messages.put(
                {
                    "type": "result",
                    "subtype": "error_during_execution",
                    "is_error": True,
                    "duration_ms": 1,
                    "duration_api_ms": 1,
                    "num_turns": 1,
                    "session_id": "native-test",
                    "api_error_status": 404,
                    "errors": ["Synthetic upstream model is unavailable"],
                }
            )
            return
        await self.messages.put(
            {
                "type": "stream_event",
                "uuid": "message-start",
                "session_id": "native-test",
                "event": {"type": "message_start", "message": {"id": "response-test", "role": "assistant"}},
            }
        )
        await self.messages.put(
            {
                "type": "stream_event",
                "uuid": "block-start",
                "session_id": "native-test",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            }
        )
        for text in ("Hello ", "bridge"):
            await self.messages.put(
                {
                    "type": "stream_event",
                    "uuid": "fragment",
                    "session_id": "native-test",
                    "event": {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    },
                }
            )
        await self.messages.put(
            {
                "type": "stream_event",
                "uuid": "block-stop",
                "session_id": "native-test",
                "event": {"type": "content_block_stop", "index": 0},
            }
        )
        await self.messages.put(
            {
                "type": "stream_event",
                "uuid": "message-stop",
                "session_id": "native-test",
                "event": {"type": "message_stop"},
            }
        )
        self.fragments_sent.set()
        await self.messages.put(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": "Hello bridge"}],
                },
            }
        )
        await self.messages.put(
            {
                "type": "result",
                "subtype": "success",
                "duration_ms": 1,
                "duration_api_ms": 1,
                "is_error": False,
                "num_turns": 1,
                "session_id": "native-test",
                "result": "Hello bridge",
                "stop_reason": "end_turn",
                "terminal_reason": "completed",
            }
        )

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Keep the SDK reader live until SDK-owned disconnect cancels it."""
        while True:
            message = await self.messages.get()
            if self._emit_initialization and message["type"] in {
                "stream_event",
                "assistant",
                "result",
                "system",
            }:
                self._emit_initialization = False
                initialized = self.initialization_message()
                if initialized is not None:
                    yield initialized
            if self.pause_terminal and message["type"] == "result":
                await self.release_terminal.wait()
            yield message

    def initialization_message(self) -> dict[str, Any] | None:
        """Supply pinned SDK system/init metadata, not connect-reply capabilities.

        This fixture reports requested test inventory only; it is not evidence
        that a real native process honored any isolation option.
        """
        return {
            "type": "system",
            "subtype": "init",
            "uuid": "synthetic-init",
            "session_id": "native-test",
            "tools": list(self.initialized_tools),
            "mcp_servers": (
                [{"name": "slo", "status": "connected", "source": "sdk"}] if self.initialized_tools else []
            ),
            "skills": [],
            "plugins": [],
        }

    async def close(self) -> None:
        """Record supported transport closure, not native process reap proof."""
        self.close_calls += 1
        self.closed = True

    def is_ready(self) -> bool:
        """Report the scripted connection state to the SDK."""
        return self.connected and not self.closed

    async def end_input(self) -> None:
        """Accept SDK input closure without manufacturing more output."""


def scripted_adapter_class(
    *,
    transport: ScriptedClaudeTransport,
    session_options: list[ClaudeSessionOptionsDAO] | None = None,
) -> type[SloClaudeBridgeAdapter]:
    """Inject just native auth observation and wire transport into the concrete adapter."""

    async def subscription_status() -> ClaudeAuthenticationStatusDAO:
        """Supply a synthetic positive native status; never inspect an account."""
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Native login ready.")

    recorded_options = session_options

    class ScriptedAdapter(SloClaudeBridgeAdapter):
        """Assemble the production adapter against the SDK's documented test seam."""

        async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
            """Record final host context while retaining production native admission."""
            if recorded_options is not None:
                recorded_options.append(session_options)
            transport.initialized_tools = [f"mcp__slo__{tool.name}" for tool in session_options.tools]
            await super().start_session(session_options=session_options)

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Retain the same concrete implementation with controlled external I/O."""
            return cls(
                configuration=configuration, transport=transport, authentication_check=subscription_status
            )

    return ScriptedAdapter


class ToolRoundTransport(ScriptedClaudeTransport):
    """Script native wire only; real SDK MCP dispatch parks on real Slo results."""

    def __init__(self, *, path: Path, multiple_rounds: bool = False) -> None:
        """Record one synthetic project target and returned native MCP receipts."""
        super().__init__()
        self.path = path
        self.multiple_rounds = multiple_rounds
        self.round = 0
        self.tool_results: list[dict[str, Any]] = []

    async def write(self, data: str) -> None:
        """Emit complete tool boundaries and native MCP requests, not host tool calls."""
        message = json.loads(data)
        if message["type"] == "control_response":
            response = message["response"]
            if response["request_id"] == "mcp-init":
                await self.messages.put(
                    {
                        "type": "control_request",
                        "request_id": "mcp-ready",
                        "request": {
                            "subtype": "mcp_message",
                            "server_name": "slo",
                            "message": {"jsonrpc": "2.0", "method": "notifications/initialized"},
                        },
                    }
                )
                await self.messages.put(self._tool_request)
            if response["request_id"].startswith("tool-rpc"):
                self.tool_results.append(response)
                if self.multiple_rounds and response["request_id"] == "tool-rpc-3":
                    await self.messages.put(
                        {
                            "type": "control_request",
                            "request_id": "tool-rpc-read",
                            "request": {
                                "subtype": "mcp_message",
                                "server_name": "slo",
                                "message": {
                                    "jsonrpc": "2.0",
                                    "id": 43,
                                    "method": "tools/call",
                                    "params": {
                                        "name": "read",
                                        "arguments": {"path": str(self.path)},
                                        "_meta": {"claudecode/toolUseId": "exact-read"},
                                    },
                                },
                            },
                        }
                    )
                    return
                if self.multiple_rounds and self.round < 3:
                    await self._emit_tool_round()
                    await self.messages.put(self._tool_request)
                    return
                self.block_response = False
                # Reuse the text script without manufacturing a second SDK query.
                prior = list(self.prompts)
                await super().write(
                    data=json.dumps({"type": "user", "message": {"content": "internal-final"}})
                )
                self.prompts = prior
            return
        if message["type"] != "user":
            await super().write(data=data)
            return
        self.prompts.append(message["message"]["content"])
        self.submitted.set()
        await self._emit_tool_round()
        await self.messages.put(
            {
                "type": "control_request",
                "request_id": "mcp-init",
                "request": {
                    "subtype": "mcp_message",
                    "server_name": "slo",
                    "message": {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "synthetic-native", "version": "1"},
                        },
                    },
                },
            }
        )

    async def _emit_tool_round(self) -> None:
        """Script three responses with four canonical tools and exact native IDs."""
        self.round += 1
        name = "read"
        args = {"path": str(self.path)}
        if self.multiple_rounds:
            name = {1: "ls", 2: "find", 3: "grep"}[self.round]
            args = {"path": str(self.path.parent)}
            if name == "find":
                args["pattern"] = "*.txt"
            if name == "grep":
                args["pattern"] = "default-model"
        identity = f"exact-native-id-{self.round}" if self.multiple_rounds else "exact-native-id"
        events = [
            {"type": "message_start", "message": {"id": f"tool-response-{self.round}", "role": "assistant"}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": identity,
                    "name": f"mcp__slo__{name}",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
        extra_read = self.multiple_rounds and self.round == 3
        if extra_read:
            events[-2:-2] = [
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "exact-read",
                        "name": "mcp__slo__read",
                        "input": {"path": str(self.path)},
                    },
                },
                {"type": "content_block_stop", "index": 1},
            ]
        response_text = f"Inspect round {self.round}." if self.multiple_rounds else ""
        if response_text:
            # Text follows the tool blocks so existing native block indices stay fixed.
            text_index = 2 if extra_read else 1
            events[-2:-2] = [
                {
                    "type": "content_block_start",
                    "index": text_index,
                    "content_block": {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": text_index,
                    "delta": {"type": "text_delta", "text": response_text},
                },
                {"type": "content_block_stop", "index": text_index},
            ]
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "scripted", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [
                        {"type": "tool_use", "id": identity, "name": f"mcp__slo__{name}", "input": args},
                        *(
                            [
                                {
                                    "type": "tool_use",
                                    "id": "exact-read",
                                    "name": "mcp__slo__read",
                                    "input": {"path": str(self.path)},
                                }
                            ]
                            if extra_read
                            else []
                        ),
                        *([{"type": "text", "text": response_text}] if response_text else []),
                    ],
                },
            }
        )
        self._tool_request: dict[str, Any] = {
            "type": "control_request",
            "request_id": f"tool-rpc-{self.round}",
            "request": {
                "subtype": "mcp_message",
                "server_name": "slo",
                "message": {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": args,
                        "_meta": {"claudecode/toolUseId": identity},
                    },
                },
            },
        }


async def test_headless_project_question_uses_slo_read_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A2 runnable: entry → graph/executor → real read → same query → real history."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "model.txt"
    assert project.resolve().is_relative_to(tmp_path.resolve())
    project.write_text("default-model = synthetic-model\n")
    transport = ToolRoundTransport(path=project)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="read-project",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare_session(config: SessionConfigDAO) -> SloAgentSession:
        """Keep real session admission, graph, executor and store."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare_session).invoke(
            prompt="Read model.txt"
        )
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0, output
    assert transport.prompts == ["Read model.txt"]
    assert len(transport.tool_results) == 1
    assert "synthetic-model" in json.dumps(transport.tool_results)
    assert transport.close_calls == 1
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="read-project"
    )
    assert sum(e.kind == "user_message" for e in events) == 1
    assert sum(e.kind == "tool_call" for e in events) == 1
    assert sum(e.kind == "tool_result" for e in events) == 1
    assert sum(e.kind == "run_completed" for e in events) == 1
    assert any(e["kind"] == "run_completed" for e in output)


async def test_headless_prompt_finishes_after_sdk_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A2/A4/A5: real headless entry streams once and persists its final answer."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    session_options: list[ClaudeSessionOptionsDAO] = []
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="bridge-headless",
        enable_history=True,
        history_root=tmp_path / "history",
        system_prompt="Final host instructions.",
    )

    async def prepare_session(config: SessionConfigDAO) -> SloAgentSession:
        """Build a real lazy session; do not replace factory, graph or persistence."""
        session = SloAgentSession.build(
            config=config,
            bridge_adapter_class=scripted_adapter_class(transport=transport, session_options=session_options),
        )
        await session.prepare_startup()
        assert not transport.connected
        assert session.preparation_status == "ready"
        return session

    exit_code: int = await HeadlessRunner(config=config, session_preparer=prepare_session).invoke(
        prompt="hello"
    )

    output: list[dict[str, Any]] = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert exit_code == 0, output
    assert [event["delta"] for event in output if event["kind"] == "text_delta"] == ["Hello ", "bridge"]
    assert [event["content"] for event in output if event["kind"] == "run_completed"] == ["Hello bridge"]
    assert transport.prompts == ["hello"]
    assert len(session_options) == 1
    assert session_options[0].model_id == "claude-bridge:claude-haiku-5-5"
    assert session_options[0].working_directory == tmp_path
    assert session_options[0].instructions == "Final host instructions."
    assert transport.closed
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    events = await store.load_events(session_id="bridge-headless")
    assert [event.payload.content for event in events if event.kind == "assistant_message"] == [
        "Hello bridge"
    ]
    assert sum(event.kind == "run_completed" for event in events) == 1
    assert [event.payload.content for event in events if event.kind == "user_message"] == ["hello"]


async def test_unavailable_native_model_is_one_failure_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A locally selectable name preserves upstream rejection and never retries direct."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport(model_unavailable=True)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        session_id="unavailable-native-model",
        history_root=tmp_path / "history",
        enable_history=True,
    )

    async def prepare_session(config: SessionConfigDAO) -> SloAgentSession:
        """Prepare real owners with only native I/O substituted."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    code = await HeadlessRunner(config=config, session_preparer=prepare_session).invoke(prompt="hello")
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    failures = [event for event in output if event["kind"] == "run_failed"]
    assert code != 0
    assert len(failures) == 1
    assert "404" in failures[0]["content"]
    assert "error_during_execution" in failures[0]["content"]
    assert not any(event["kind"] == "run_completed" for event in output)
    assert transport.prompts == ["hello"]
    assert transport.close_calls == 1


async def test_default_headless_bridge_preparation_failure_has_native_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default preparation preserves the native route and emits one actionable failure."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()

    async def unavailable() -> ClaudeAuthenticationStatusDAO:
        """Supply safe native status without invoking an executable."""
        return ClaudeAuthenticationStatusDAO(state="login_required", safe_message="Use Claude Code /login.")

    class UnavailableAdapter(SloClaudeBridgeAdapter):
        """Replace only native status and wire operations."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register an inert concrete adapter at the SDK boundary."""
            return cls(configuration=configuration, transport=transport, authentication_check=unavailable)

    code = await HeadlessRunner(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5"),
        bridge_adapter_class=UnavailableAdapter,
    ).invoke(prompt="hello")
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 1
    assert len(output) == 1 and output[0]["kind"] == "run_failed"
    assert "Claude Code" in output[0]["content"] and "/login" in output[0]["content"]
    assert "OpenRouter" not in output[0]["content"]
    assert not transport.connected and not transport.prompts


async def test_abort_interrupts_blocked_native_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A7: real session abort wakes a stalled SDK response and persists one aborted outcome."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport(block_response=True)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-sonnet-4-6",
        session_id="bridge-abort",
        history_root=tmp_path / "history",
        enable_history=True,
    )
    session = SloAgentSession.build(
        config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
    )

    async def collect() -> list[str]:
        """Drain the real host run while another caller requests synchronous abort."""
        return [event.kind async for event in session.invoke(text="hello")]

    task = asyncio.create_task(coro=collect())
    try:
        async with asyncio.timeout(5):
            await transport.submitted.wait()
            session.abort()
            kinds = await task
        assert kinds == ["run_aborted"]
        assert transport.closed
        assert transport.interrupt_calls == 1
        assert transport.close_calls == 1
        assert transport.prompts == ["hello"]
        store = FilesystemSessionHistoryStore(root=tmp_path / "history")
        events = await store.load_events(session_id="bridge-abort")
        assert sum(event.kind == "run_aborted" for event in events) == 1
        assert not any(event.kind == "run_completed" for event in events)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await session.close_agent_resources()


async def test_three_rounds_all_four_tools_preserve_history_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A2/A5: one query crosses three real graph rounds and all canonical tools."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "model.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("default-model = synthetic-model\n")
    transport = ToolRoundTransport(path=target, multiple_rounds=True)
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="three-rounds",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Keep real lazy factory, graph, tools and store."""
        return await SloAgentSession.prepare(
            config=config, bridge_adapter_class=scripted_adapter_class(transport=transport)
        )

    async with asyncio.timeout(10):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(
            prompt="Locate and read default model"
        )
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0, output
    assert transport.prompts == ["Locate and read default model"]
    assert transport.round == 3 and len(transport.tool_results) == 4
    assert transport.close_calls == 1
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="three-rounds"
    )
    calls = [e.payload.model_dump() for e in events if e.kind == "tool_call"]
    results = [e.payload.model_dump() for e in events if e.kind == "tool_result"]
    assert len(calls) == len(results) == 4
    assert {c["tool_name"] for c in calls} == {"ls", "find", "grep", "read"}
    assert (
        {c["tool_call_id"] for c in calls}
        == {r["tool_call_id"] for r in results}
        == {"exact-native-id-1", "exact-native-id-2", "exact-native-id-3", "exact-read"}
    )
    ordered_ids = ["exact-native-id-1", "exact-native-id-2", "exact-native-id-3", "exact-read"]
    assert [c["tool_call_id"] for c in calls] == ordered_ids
    assert [r["tool_call_id"] for r in results] == ordered_ids
    assert [r["request_id"] for r in transport.tool_results] == [
        "tool-rpc-1",
        "tool-rpc-2",
        "tool-rpc-3",
        "tool-rpc-read",
    ]
    for result, receipt in zip(results, transport.tool_results, strict=True):
        native = receipt["response"]["mcp_response"]["result"]
        assert native == {"content": [{"type": "text", "text": result["tool_output"]}], "isError": False}
    assert "model.txt" in results[0]["tool_output"]
    assert "model.txt" in results[1]["tool_output"]
    assert "default-model = synthetic-model" in results[2]["tool_output"]
    assert results[3]["tool_output"] == "default-model = synthetic-model\n"
    assert [c["content"] for c in calls] == [
        "Inspect round 1.",
        "Inspect round 2.",
        "Inspect round 3.",
        "Inspect round 3.",
    ]
    assert [e.payload.content for e in events if e.kind == "assistant_message"] == ["Hello bridge"]
    assert [e["content"] for e in output if e["kind"] == "run_completed"] == ["Hello bridge"]
    assert [e.payload.content for e in events if e.kind == "run_completed"] == ["Hello bridge"]
    assert transport.closed
    assert (
        sum(e.kind == "user_message" for e in events) == sum(e.kind == "run_completed" for e in events) == 1
    )
