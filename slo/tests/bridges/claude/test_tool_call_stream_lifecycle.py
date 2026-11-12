"""Spec107 A19: real session/graph/projector and SDK MCP batch continuation."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any, Self

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.plugins.dao import AfterToolResultPatchDAO, BeforeToolCallDecisionDAO
from src.agents.slo_agent.plugins.dispatcher import PluginDispatcher
from src.agents.slo_agent.plugins.registry import PluginRegistry
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.now import now_tool
from src.agents.tools.read import read_tool
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import (
    ClaudeAuthenticationStatusDAO,
    ClaudeSessionOptionsDAO,
    ClaudeBridgeConfigurationDAO,
    ClaudeToolResultBatchDAO,
    ClaudeToolResultSubmissionDAO,
)
from src.bridges.dao import SloBridgeSessionOptionsDAO
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
from tests.cli.test_claude_bridge import (
    ScriptedClaudeTransport,
    ToolRoundTransport,
)
from tests.tui.test_transcript_projector import FakeHost


class ParallelToolRoundTransport(ToolRoundTransport):
    """Emit one parallel read/now response and retain every SDK callback receipt."""

    def __init__(self, *, path: Path) -> None:
        """Retain the temporary read target and native callback requests.

        Args:
            path (Path): Existing file owned by the journey's tmp_path.
        """
        super().__init__(path=path)
        self.callback_requests: list[dict[str, Any]] = []

    async def _emit_tool_round(self) -> None:
        """Supply corroborated native tools before MCP dispatch, including empty args."""
        calls: list[dict[str, Any]] = [
            {
                "type": "tool_use",
                "id": "native-read",
                "name": "mcp__slo__read",
                "input": {"path": str(self.path)},
            },
            {"type": "tool_use", "id": "native-now", "name": "mcp__slo__now", "input": {}},
        ]
        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": "parallel-response", "role": "assistant"}}
        ]
        for index, call in enumerate(calls):
            events.extend(
                [
                    {"type": "content_block_start", "index": index, "content_block": call},
                    {"type": "content_block_stop", "index": index},
                ]
            )
            self.callback_requests.append(
                {
                    "type": "control_request",
                    "request_id": f"tool-rpc-{call['id']}",
                    "request": {
                        "subtype": "mcp_message",
                        "server_name": "slo",
                        "message": {
                            "jsonrpc": "2.0",
                            "id": index + 42,
                            "method": "tools/call",
                            "params": {
                                "name": call["name"].removeprefix("mcp__slo__"),
                                "arguments": call["input"],
                                "_meta": {"claudecode/toolUseId": call["id"]},
                            },
                        },
                    },
                }
            )
        events.extend(
            [
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ]
        )
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "scripted", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "assistant",
                "message": {"role": "assistant", "model": "claude-sonnet-4-6", "content": calls},
            }
        )

    async def write(self, data: str) -> None:
        """Release the final answer only after both real MCP callbacks respond.

        Args:
            data (str): JSON control/user frame written by the official SDK.
        """
        message: dict[str, Any] = json.loads(data)
        if message["type"] != "control_response":
            await super().write(data=data)
            return
        response: dict[str, Any] = message["response"]
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
            for callback_request in self.callback_requests:
                await self.messages.put(callback_request)
            return
        if not response["request_id"].startswith("tool-rpc-"):
            return
        self.tool_results.append(response)
        if len(self.tool_results) == len(self.callback_requests):
            prior_prompts: list[str] = list(self.prompts)
            await ScriptedClaudeTransport.write(
                self, data=json.dumps({"type": "user", "message": {"content": "internal-final"}})
            )
            self.prompts = prior_prompts


class RecordingToolDispatcher(PluginDispatcher):
    """Observe real executor invocations without replacing the canonical tools."""

    def __init__(self) -> None:
        """Create an inert dispatcher with per-journey execution records."""
        super().__init__(registry=PluginRegistry(registrations=[]))
        self.started: list[str] = []
        self.completed: dict[str, str] = {}
        self.completion_ids: list[str] = []

    async def run_before_tool_call(
        self, *, tool_name: str, tool_call_id: str, tool_input: dict[str, Any]
    ) -> BeforeToolCallDecisionDAO:
        """Record each actual invocation at the supported executor interception seam.

        Args:
            tool_name (str): Canonical registered tool about to execute.
            tool_call_id (str): Native call identity.
            tool_input (dict[str, Any]): Unmodified call arguments.

        Returns:
            BeforeToolCallDecisionDAO: Production admission decision, unchanged.
        """
        self.started.append(tool_call_id)
        return await super().run_before_tool_call(
            tool_name=tool_name, tool_call_id=tool_call_id, tool_input=tool_input
        )

    async def run_after_tool_result(
        self, *, tool_name: str, tool_call_id: str, content: str, is_error: bool
    ) -> AfterToolResultPatchDAO:
        """Retain successful real outputs before graph result publication.

        Args:
            tool_name (str): Canonical tool that executed.
            tool_call_id (str): Native call identity.
            content (str): Real executor output.
            is_error (bool): Executor error state.

        Returns:
            AfterToolResultPatchDAO: Production result decision, unchanged.
        """
        assert not is_error
        self.completion_ids.append(tool_call_id)
        self.completed[tool_call_id] = content
        return await super().run_after_tool_result(
            tool_name=tool_name, tool_call_id=tool_call_id, content=content, is_error=is_error
        )


class TestClaudeToolCallStreamJourney:
    """Protect A19 across display, native callbacks, execution and durable history."""

    async def test_attaches_one_result_per_call_when_parallel_batch_includes_empty_args(
        self, *, tmp_path: Path
    ) -> None:
        """A19: one SDK query, one result batch, one callback/execution/block per call.

        Args:
            tmp_path (Path): Isolated project and real session history root.
        """
        project: Path = tmp_path / "model.txt"
        assert project.resolve().is_relative_to(tmp_path.resolve())
        project.write_text("lifecycle fixture\n", encoding="utf-8")
        transport = ParallelToolRoundTransport(path=project)
        submissions: list[ClaudeToolResultSubmissionDAO] = []

        async def ready_status() -> ClaudeAuthenticationStatusDAO:
            """Supply synthetic native readiness without inspecting real credentials.

            Returns:
                ClaudeAuthenticationStatusDAO: Ready status for scripted SDK I/O only.
            """
            return ClaudeAuthenticationStatusDAO(state="ready", safe_message="Synthetic native readiness.")

        class RecordingAdapter(SloClaudeBridgeAdapter):
            """Observe public submissions while retaining real SDK batch delivery."""

            @classmethod
            def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
                """Inject native wire/auth only, leaving all result delivery real.

                Args:
                    configuration (ClaudeBridgeConfigurationDAO): Trusted bridge settings.

                Returns:
                    Self: Inert production adapter with per-journey external I/O.
                """
                return cls(
                    configuration=configuration, transport=transport, authentication_check=ready_status
                )

            async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
                """Report exactly the offered test inventory at native initialization.

                Args:
                    session_options (ClaudeSessionOptionsDAO): Final host-owned tools and context.
                """
                transport.initialized_tools = [f"mcp__slo__{tool.name}" for tool in session_options.tools]
                await super().start_session(session_options=session_options)

            async def submit_tool_results(
                self, *, invocation_id: str, tool_result_batch: ClaudeToolResultBatchDAO
            ) -> None:
                """Record a whole batch before delegating to production delivery.

                Args:
                    invocation_id (str): Active native invocation.
                    tool_result_batch (ClaudeToolResultBatchDAO): Complete response result set.
                """
                submissions.append(
                    ClaudeToolResultSubmissionDAO(
                        invocation_id=invocation_id, tool_result_batch=tool_result_batch
                    )
                )
                await super().submit_tool_results(
                    invocation_id=invocation_id, tool_result_batch=tool_result_batch
                )

        model = SloClaudeBridge(
            model_name="claude-bridge:claude-haiku-5-5",
            bridge_adapter=RecordingAdapter.register(configuration=ClaudeBridgeConfigurationDAO()),
        )
        dispatcher = RecordingToolDispatcher()
        agent = SloAgent(
            llm=model, tools=[read_tool, now_tool], cwd=str(tmp_path), plugin_dispatcher=dispatcher
        )
        model.configure_session(
            session_options=SloBridgeSessionOptionsDAO(
                session_id="lifecycle", working_directory=tmp_path, instructions="Inspect the project."
            )
        )
        history_root: Path = tmp_path / "history"
        assert history_root.resolve().is_relative_to(tmp_path.resolve())
        store = FilesystemSessionHistoryStore(root=history_root)
        session = SloAgentSession(
            agent=agent, workdir=tmp_path, session_id="lifecycle", history_store=store, enable_history=True
        )
        host = FakeHost()
        projector = TranscriptProjectionAdapter(host=host)
        stream_events: list[AgentStreamEventDAO] = []
        try:
            async with asyncio.timeout(10):
                async for event in session.invoke(text="Read model.txt and report the time."):
                    stream_events.append(event)
                    await projector.handle(event=event)
        finally:
            await session.close_agent_resources()

        call_ids: set[str] = {"native-read", "native-now"}
        assert transport.prompts == ["Read model.txt and report the time."]
        assert transport.close_calls == 1
        assert Counter(dispatcher.started) == Counter({call_id: 1 for call_id in call_ids})
        assert Counter(dispatcher.completion_ids) == Counter({call_id: 1 for call_id in call_ids})
        assert dispatcher.completed["native-read"] == "lifecycle fixture\n"
        assert dispatcher.completed["native-now"]
        assert len(submissions) == 1
        batch: ClaudeToolResultBatchDAO = submissions[0].tool_result_batch
        assert batch.response_id == "parallel-response"
        assert Counter(result.tool_call_id for result in batch.results) == Counter(call_ids)
        assert all(not result.is_error for result in batch.results)
        assert Counter(receipt["request_id"] for receipt in transport.tool_results) == Counter(
            {"tool-rpc-native-read": 1, "tool-rpc-native-now": 1}
        )
        for receipt in transport.tool_results:
            call_id: str = receipt["request_id"].removeprefix("tool-rpc-")
            mcp_response: dict[str, Any] = receipt["response"]["mcp_response"]
            assert mcp_response["id"] == (42 if call_id == "native-read" else 43)
            assert mcp_response["result"]["content"] == [
                {"type": "text", "text": dispatcher.completed[call_id]}
            ]
            assert not mcp_response["result"].get("isError", False)
        assert host.mount_order.count("tool") == 2
        assert set(host.tool_blocks) == call_ids
        for call_id in call_ids:
            assert host.tool_blocks[call_id].result_output == dispatcher.completed[call_id]
            call_events: list[AgentStreamEventDAO] = [
                event for event in stream_events if event.tool_call_id == call_id
            ]
            assert Counter(event.kind for event in call_events) == Counter(
                {"tool_call_start": 1, "tool_call_delta": 1, "tool_call_end": 1, "tool_result": 1}
            )
            assert call_events[0].kind == "tool_call_start"
            assert call_events[-1].kind == "tool_result"
        now_end: list[AgentStreamEventDAO] = [
            event
            for event in stream_events
            if event.kind == "tool_call_end" and event.tool_call_id == "native-now"
        ]
        assert [event.tool_input for event in now_end] == [{}]
        assert stream_events[-1].kind == "run_completed"
        assert stream_events[-1].content == "Hello bridge"
        history: list[SessionHistoryEventDAO] = await store.load_events(session_id=session.session_id)
        assert {
            event.payload.tool_call_id: event.payload.tool_output
            for event in history
            if event.kind == "tool_result"
        } == dispatcher.completed
        for kind in ("tool_call", "tool_result"):
            assert Counter(event.payload.tool_call_id for event in history if event.kind == kind) == Counter(
                call_ids
            )
        assert [event.payload.content for event in history if event.kind == "assistant_message"] == [
            "Hello bridge"
        ]
