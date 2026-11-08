"""Failure cutoffs through injected history and native wire seams, never internal patches."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class
from tests.bridges.claude.test_lifecycle import ready_status
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeBridgeConfigurationDAO,
    ClaudeInvocationOptionsDAO,
    ClaudeSessionOptionsDAO,
    ClaudeToolDefinitionDAO,
)
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError


class RefusingHistoryStore(FilesystemSessionHistoryStore):
    """Persist real history except one explicitly selected write boundary."""

    def __init__(self, *, root: Path, refused_kind: str) -> None:
        """Retain the failure policy through the public history-store injection seam."""
        super().__init__(root=root)
        self.refused_kind = refused_kind
        self.refused: list[SessionHistoryEventDAO] = []

    async def append_event(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Refuse one kind before disk mutation; all other events use the real writer."""
        if event.kind == self.refused_kind:
            self.refused.append(event)
            raise OSError("synthetic history write refusal")
        return await super().append_event(event=event)


class RefusingDeliveryTransport(ToolRoundTransport):
    """Fail the first MCP receipt write before the scripted native side advances."""

    def __init__(self, *, path: Path) -> None:
        """Record attempted receipt writes separately from accepted native receipts."""
        super().__init__(path=path, multiple_rounds=True)
        self.receipt_attempts = 0
        self.receipt_frames: list[dict[str, Any]] = []

    async def write(self, data: str) -> None:
        """Refuse native result delivery, retaining real official SDK error propagation."""
        message = json.loads(data)
        if message["type"] == "control_response" and message["response"]["request_id"].startswith("tool-rpc"):
            self.receipt_attempts += 1
            self.receipt_frames.append(message)
            raise OSError("synthetic result delivery refusal")
        await super().write(data=data)


@pytest.mark.parametrize("failure_at", ["user_message", "tool_result", "delivery"])
async def test_tool_round_failure_stops_advancement_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_at: str,
) -> None:
    """A12: history and delivery failure never permit a later native round or success."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "model.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text(data="default-model = synthetic-model\n")
    transport = (
        RefusingDeliveryTransport(path=target)
        if failure_at == "delivery"
        else ToolRoundTransport(path=target, multiple_rounds=True)
    )
    store = RefusingHistoryStore(root=tmp_path / "history", refused_kind=failure_at)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="failure-cutoff",
        history_store=store,
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            enable_history=True,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed: list[str] = []
    try:
        async with asyncio.timeout(8):
            with pytest.raises(Exception):
                async for event in session.invoke(text="Locate and read default model"):
                    observed.append(event.kind)
        assert not session.is_running
        events = await store.load_events(session_id=session.session_id)
        assert not any(e.kind == "run_completed" for e in events)
        assert "run_completed" not in observed and "run_aborted" not in observed
        assert sum(e.kind == "run_failed" for e in events) == 1
        assert not any(e.kind in {"run_retrying", "model_route_changed", "recovery_started"} for e in events)
        assert transport.tool_results == []
        if failure_at == "user_message":
            assert transport.prompts == [] and not transport.connected
            assert not any(e.kind == "tool_call" for e in events)
            assert len(store.refused) == 1
        else:
            assert transport.prompts == ["Locate and read default model"]
            assert transport.round == 1
            assert transport.closed and transport.close_calls == 1
            assert [e.payload.tool_call_id for e in events if e.kind == "tool_call"] == ["exact-native-id-1"]
            assert [e.payload.tool_call_id for e in events if e.kind == "tool_result"] == (
                ["exact-native-id-1"] if failure_at == "delivery" else []
            )
            if isinstance(transport, RefusingDeliveryTransport):
                assert transport.receipt_attempts == 1
                assert transport.receipt_frames[0]["response"]["response"]["mcp_response"]["result"] == {
                    "content": [
                        {
                            "type": "text",
                            "text": next(e.payload.tool_output for e in events if e.kind == "tool_result"),
                        }
                    ],
                    "isError": False,
                }
            else:
                assert len(store.refused) == 1
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize(
    "fault", ["wrong-type", "oversized", "stale", "duplicate", "arguments", "nested-json-identity"]
)
async def test_fatal_mcp_callback_wakes_runtime_without_result_or_fallback(
    tmp_path: Path, fault: str
) -> None:
    """A13/A17/A18: official MCP errors must also stop the independently parked reader."""

    class InvalidCallbackTransport(ToolRoundTransport):
        """Keep native traffic parked after delivering the selected corrupt callback."""

        async def _emit_tool_round(self) -> None:
            """Mutate only native MCP input, never runtime or host state."""
            await super()._emit_tool_round()
            params = self._tool_request["request"]["message"]["params"]
            if fault == "wrong-type":
                params["_meta"]["claudecode/toolUseId"] = 17
            elif fault == "oversized":
                params["_meta"]["claudecode/toolUseId"] = "x" * 257
            elif fault == "stale":
                params["_meta"]["claudecode/toolUseId"] = "old-invocation-call"
            elif fault == "arguments":
                params["arguments"] = {"path": "not-the-emitted-path"}
            elif fault == "nested-json-identity":
                # Change only scripted vendor wire; stream and echo agree on the
                # integer, while the independently dispatched MCP call uses bool.
                queued: list[dict[str, Any]] = []  # Scripted third-party wire is heterogeneous.
                while not self.messages.empty():
                    message = self.messages.get_nowait()
                    event = message.get("event", {})
                    if event.get("type") == "content_block_delta":
                        arguments = json.loads(event["delta"]["partial_json"])
                        arguments["nested"] = [{"value": 1}]
                        event["delta"]["partial_json"] = json.dumps(arguments)
                    if message.get("type") == "assistant":
                        message["message"]["content"][0]["input"]["nested"] = [{"value": 1}]
                    queued.append(message)
                for message in queued:
                    await self.messages.put(message)
                params["arguments"] = {**params["arguments"], "nested": [{"value": True}]}

        async def write(self, data: str) -> None:
            """Return no synthetic final answer on an MCP error; expose duplicate IDs."""
            message = json.loads(data)
            response = message.get("response", {})
            if message["type"] == "control_response" and response["request_id"].startswith("tool-rpc"):
                self.tool_results.append(response)
                return
            await super().write(data=data)
            if fault == "duplicate" and response.get("request_id") == "mcp-init":
                duplicate = deepcopy(self._tool_request)
                duplicate["request_id"] = "tool-rpc-duplicate"
                duplicate["request"]["message"]["id"] = 99
                await self.messages.put(duplicate)

    transport = InvalidCallbackTransport(path=tmp_path / "unused.txt")
    transport.initialized_tools = ["mcp__slo__read"]
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host",
            model_id="claude-bridge:claude-haiku-5-5",
            working_directory=tmp_path,
            instructions="test",
            tools=(
                ClaudeToolDefinitionDAO(
                    name="read",
                    description="Read",
                    input_schema={"type": "object"},
                ),
            ),
        )
    )
    try:
        async with asyncio.timeout(5):
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="current",
                    text="Read once",
                )
            )
            with pytest.raises(ClaudeBridgeError):
                while True:
                    async for event in adapter.read_response(invocation_id="current"):
                        assert getattr(event, "stop_reason", None) not in ("stop", "length")
            assert transport.closed and transport.close_calls == 1
            assert transport.prompts == ["Read once"]
            assert transport.round == 1
            assert not any(
                not receipt["response"]["mcp_response"]["result"].get("isError", False)
                for receipt in transport.tool_results
            )
    finally:
        await adapter.close()
