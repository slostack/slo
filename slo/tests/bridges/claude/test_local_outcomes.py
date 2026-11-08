"""Representative real executor outcomes, identical calls and receive failure cutoffs."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


class OutcomeTransport(ToolRoundTransport):
    """Alter only vendor wire input, preserving real SDK/MCP and host execution."""

    def __init__(
        self, *, path: Path, calls: list[tuple[str, dict[str, Any]]], fail_receive: bool = False
    ) -> None:
        """Retain the desired native batch and optional post-receipt wire failure."""
        super().__init__(path=path)
        self.calls = calls
        self.fail_receive = fail_receive
        self.receipts = asyncio.Event()
        self.requests: list[dict[str, Any]] = []

    async def _emit_tool_round(self) -> None:
        """Publish identical/invalid-argument calls with exact distinct native IDs."""
        self.round += 1
        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": "outcomes", "role": "assistant"}},
        ]
        self.requests = []
        for index, (name, args) in enumerate(self.calls):
            identity = f"call-{index}"
            events.extend(
                [
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": {
                            "type": "tool_use",
                            "id": identity,
                            "name": f"mcp__slo__{name}",
                            "input": args,
                        },
                    },
                    {"type": "content_block_stop", "index": index},
                ]
            )
            self.requests.append(
                {
                    "type": "control_request",
                    "request_id": f"tool-rpc-{index}",
                    "request": {
                        "subtype": "mcp_message",
                        "server_name": "slo",
                        "message": {
                            "jsonrpc": "2.0",
                            "id": 40 + index,
                            "method": "tools/call",
                            "params": {
                                "name": name,
                                "arguments": args,
                                "_meta": {"claudecode/toolUseId": identity},
                            },
                        },
                    },
                }
            )
        events.extend(
            [{"type": "message_delta", "delta": {"stop_reason": "tool_use"}}, {"type": "message_stop"}]
        )
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "outcome", "session_id": "native-test", "event": event}
            )
        self._tool_request = self.requests[-1]

    async def write(self, data: str) -> None:
        """Reverse callback order, hold answer until every exact-ID receipt arrives."""
        message = json.loads(data)
        response = message.get("response", {})
        if message["type"] == "control_response" and response["request_id"].startswith("tool-rpc"):
            self.tool_results.append(response)
            if len(self.tool_results) == len(self.calls):
                self.receipts.set()
                if not self.fail_receive:
                    from tests.cli.test_claude_bridge import ScriptedClaudeTransport

                    prior = list(self.prompts)
                    await ScriptedClaudeTransport.write(
                        self, data=json.dumps({"type": "user", "message": {"content": "internal-final"}})
                    )
                    self.prompts = prior
            return
        await super().write(data=data)
        if response.get("request_id") == "mcp-init":
            for request in reversed(self.requests[:-1]):
                await self.messages.put(deepcopy(request))

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Raise at the external receive boundary after all native receipts are accepted."""
        stream = super().read_messages()
        while True:
            if self.fail_receive and self.receipts.is_set():
                raise OSError("synthetic wire receive failure")
            next_frame = asyncio.ensure_future(coro_or_future=anext(stream))
            receipt = asyncio.create_task(coro=self.receipts.wait())
            try:
                done, _ = await asyncio.wait({next_frame, receipt}, return_when=asyncio.FIRST_COMPLETED)
                if self.fail_receive and receipt in done:
                    raise OSError("synthetic wire receive failure")
                yield await next_frame
            finally:
                next_frame.cancel()
                receipt.cancel()
                await asyncio.gather(next_frame, receipt, return_exceptions=True)


@pytest.mark.parametrize("case", ["missing", "no-match", "arguments", "identical", "receive-failure"])
async def test_real_executor_outcome_reaches_receipt_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """A3/A4/A12: real outputs/status, ordered traces and exact-once receipt or failure."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "source.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("unique real file content\n", encoding="utf-8")
    calls = {
        "missing": [("read", {"path": str(tmp_path / "absent.txt")})],
        "no-match": [("grep", {"path": str(target), "pattern": "not-present"})],
        "arguments": [("read", {"path": str(target), "limit": "invalid-integer"})],
        "identical": [("read", {"path": str(target)})] * 2,
        "receive-failure": [("read", {"path": str(target)})],
    }[case]
    transport = OutcomeTransport(path=target, calls=calls, fail_receive=case == "receive-failure")
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="outcomes",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(8):
            if case == "receive-failure":
                with pytest.raises(Exception):
                    _ = [event async for event in session.invoke(text="Read project")]
            else:
                _ = [event async for event in session.invoke(text="Read project")]
        events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="outcomes"
        )
        results = [e.payload for e in events if e.kind == "tool_result"]
        ids = [f"call-{index}" for index in range(len(calls))]
        assert [e.payload.tool_call_id for e in events if e.kind == "tool_call"] == ids
        assert [result.tool_call_id for result in results] == ids
        assert len(transport.tool_results) == len(calls)
        bodies = {
            receipt["request_id"]: receipt["response"]["mcp_response"]["result"]
            for receipt in transport.tool_results
        }
        for index, result in enumerate(results):
            body = bodies[f"tool-rpc-{index}"]
            assert body["content"] == [{"type": "text", "text": result.tool_output}]
            assert body["isError"] == (case == "arguments")
        output = results[0].tool_output
        assert output is not None
        if case == "missing":
            assert "file not found" in output
        elif case == "no-match":
            assert "no matches" in output
        elif case == "arguments":
            assert "validation error" in output
        else:
            assert all(result.tool_output == "unique real file content\n" for result in results)
        assert sum(e.kind == "run_completed" for e in events) == (0 if case == "receive-failure" else 1)
        if case == "receive-failure":
            assert sum(e.kind == "run_failed" for e in events) == 1
        assert transport.prompts == ["Read project"]
        assert transport.closed and transport.close_calls == 1
    finally:
        await session.close_agent_resources()
