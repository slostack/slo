"""Coding-tool journeys through the Claude bridge (101.a.3): real Slo, scripted native wire."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.dao import ClaudeSessionOptionsDAO
from src.cli.headless import HeadlessRunner
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class

LOCAL_TOOL_NAMES: list[str] = [
    "read",
    "write",
    "edit",
    "bash",
    "grep",
    "find",
    "ls",
    "read_pdf",
    "now",
    "show_git_diff",
]

BUGGY_CALC: str = "def add(left: int, right: int) -> int:\n    return left - right\n"
FIXED_CALC: str = "def add(left: int, right: int) -> int:\n    return left + right\n"
EXISTING_TEST: str = (
    "import unittest\n"
    "from calc import add\n\n\n"
    "class AddTest(unittest.TestCase):\n"
    "    def test_add(self) -> None:\n"
    "        self.assertEqual(add(2, 3), 5)\n\n\n"
    "if __name__ == '__main__':\n"
    "    unittest.main()\n"
)
REGRESSION_TEST: str = (
    "import unittest\n"
    "from calc import add\n\n\n"
    "class AddRegressionTest(unittest.TestCase):\n"
    "    def test_add_is_not_subtract(self) -> None:\n"
    "        self.assertEqual(add(10, 4), 14)\n"
)


class CodingRoundsTransport(ScriptedClaudeTransport):
    """Script one native tool request per round, then a final text answer.

    Only the native wire is scripted; Slo's graph, executor and tools run for real.
    """

    def __init__(
        self,
        *,
        rounds: list[tuple[str, str, dict[str, Any]]],
        round_usages: list[tuple[Any, Any]] | None = None,
    ) -> None:
        """Hold (tool_use_id, tool_name, arguments) per round and optional (start, delta) usage."""
        super().__init__()
        self.rounds = rounds
        self.round_usages = round_usages or []
        self.round = 0
        self.tool_results: list[dict[str, Any]] = []

    async def write(self, data: str) -> None:
        """Advance the script on the prompt and on each returned MCP result."""
        message = json.loads(data)
        if message["type"] == "control_response":
            await self._on_control_response(response=message["response"])
            return
        if message["type"] != "user":
            await super().write(data=data)
            return
        self.prompts.append(message["message"]["content"])
        self.submitted.set()
        await self._emit_round()
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

    async def _on_control_response(self, *, response: dict[str, Any]) -> None:
        """Answer the MCP handshake, then drive rounds from returned tool results."""
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
            await self._request_current_tool()
        elif response["request_id"].startswith("tool-rpc"):
            self.tool_results.append(response)
            if self.round < len(self.rounds):
                await self._emit_round()
                await self._request_current_tool()
                return
            prior = list(self.prompts)
            await super().write(data=json.dumps({"type": "user", "message": {"content": "internal-final"}}))
            self.prompts = prior

    async def _emit_round(self) -> None:
        """Emit one complete tool_use response with its exact native id."""
        tool_id, name, arguments = self.rounds[self.round]
        self.round += 1
        start_usage, delta_usage = (
            self.round_usages[self.round - 1] if self.round <= len(self.round_usages) else (None, None)
        )
        events: list[dict[str, Any]] = [
            {
                "type": "message_start",
                "message": {
                    "id": f"coding-response-{self.round}",
                    "role": "assistant",
                    **({} if start_usage is None else {"usage": start_usage}),
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": f"mcp__slo__{name}",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                **({} if delta_usage is None else {"usage": delta_usage}),
            },
            {"type": "message_stop"},
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
                        {"type": "tool_use", "id": tool_id, "name": f"mcp__slo__{name}", "input": arguments}
                    ],
                },
            }
        )

    async def _request_current_tool(self) -> None:
        """Send the native MCP tools/call that carries the current round's exact id."""
        tool_id, name, arguments = self.rounds[self.round - 1]
        await self.messages.put(
            {
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
                            "arguments": arguments,
                            "_meta": {"claudecode/toolUseId": tool_id},
                        },
                    },
                },
            }
        )


async def test_fix_code_add_test_and_run_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance journey: bash (fail), edit, write, bash (pass), answer; Slo ran every call."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "project"
    project.mkdir()
    calc = project / "calc.py"
    existing_test = project / "test_calc.py"
    new_test = project / "test_regression.py"
    for target in (calc, existing_test, new_test):
        assert target.resolve().is_relative_to(tmp_path.resolve())
    calc.write_text(BUGGY_CALC)
    existing_test.write_text(EXISTING_TEST)
    # -B: the same-size edit lands within one mtime second, so a cached .pyc would go stale.
    run_tests = {"command": f"cd {project} && python3 -B -m unittest discover -s {project} 2>&1"}
    transport = CodingRoundsTransport(
        rounds=[
            ("exact-bash-fail", "bash", run_tests),
            (
                "exact-edit",
                "edit",
                {"path": str(calc), "edits": [{"oldText": "left - right", "newText": "left + right"}]},
            ),
            ("exact-write", "write", {"path": str(new_test), "content": REGRESSION_TEST}),
            ("exact-bash-pass", "bash", run_tests),
        ]
    )
    session_options: list[ClaudeSessionOptionsDAO] = []
    config = SessionConfigDAO(
        workdir=project,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="coding-journey",
        enable_history=True,
        history_root=tmp_path / "history",
    )

    async def prepare(config: SessionConfigDAO) -> SloAgentSession:
        """Keep real session admission, graph, executor and store."""
        return await SloAgentSession.prepare(
            config=config,
            bridge_adapter_class=scripted_adapter_class(transport=transport, session_options=session_options),
        )

    async with asyncio.timeout(30):
        code = await HeadlessRunner(config=config, session_preparer=prepare).invoke(
            prompt="Fix calc.py, add a regression test and run the tests"
        )
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0, output
    assert [tool.name for tool in session_options[0].tools] == sorted(LOCAL_TOOL_NAMES)
    assert calc.read_text() == FIXED_CALC
    assert new_test.read_text() == REGRESSION_TEST
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="coding-journey"
    )
    calls = [e.payload.model_dump() for e in events if e.kind == "tool_call"]
    results = [e.payload.model_dump() for e in events if e.kind == "tool_result"]
    ordered_ids = ["exact-bash-fail", "exact-edit", "exact-write", "exact-bash-pass"]
    assert [c["tool_call_id"] for c in calls] == ordered_ids
    assert [r["tool_call_id"] for r in results] == ordered_ids
    assert [c["tool_name"] for c in calls] == ["bash", "edit", "write", "bash"]
    first_exit = re.match(r"exit_code: (\d+)", results[0]["tool_output"])
    last_exit = re.match(r"exit_code: (\d+)", results[3]["tool_output"])
    assert first_exit is not None and int(first_exit.group(1)) != 0
    assert "FAIL" in results[0]["tool_output"] or "AssertionError" in results[0]["tool_output"]
    assert last_exit is not None and int(last_exit.group(1)) == 0
    assert sum(e.kind == "run_completed" for e in events) == 1
    assert transport.close_calls == 1


async def test_coding_tools_are_the_local_bundle_without_connectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bridge route lists the ten local tools before and after the agent is built."""
    from src.agents.tools.bundles import create_extended_tools

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.setenv(name="SLO_CONNECTORS_DIR", value=str(tmp_path / "connectors"))
    monkeypatch.setenv(name="SLO_ATLASSIAN_SITE_URL", value="https://x.atlassian.net")
    monkeypatch.setenv(name="SLO_ATLASSIAN_EMAIL", value="x@x.com")
    monkeypatch.setenv(name="SLO_ATLASSIAN_API_TOKEN", value="token")
    extended_names = [tool.name for tool in create_extended_tools()]
    assert len(extended_names) == 15
    bridge_session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="bridge-tools",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=ScriptedClaudeTransport()),
    )
    try:
        assert bridge_session._agent is None
        assert bridge_session._runtime_tool_names() == LOCAL_TOOL_NAMES
        assert [tool.name for tool in bridge_session.agent.tools] == LOCAL_TOOL_NAMES
        assert bridge_session._runtime_tool_names() == LOCAL_TOOL_NAMES
    finally:
        await bridge_session.close_agent_resources()
    direct_session = SloAgentSession(
        workdir=tmp_path,
        session_id="direct-tools",
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="gpt-5.4", reasoning_level="off", session_id="direct-tools"
        ),
        enable_history=False,
    )
    assert direct_session._runtime_tool_names() == extended_names
