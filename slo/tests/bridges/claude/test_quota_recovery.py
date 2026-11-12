"""Quota failure journeys through real SDK parsing and disposable session history."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, SystemMessage, Message
from claude_agent_sdk._internal.transport import Transport

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError, ClaudeQuotaExceededError
from src.bridges.claude.sdk.dao import ClaudeInvocationOptionsDAO, ClaudeSessionOptionsDAO
from src.bridges.claude.sdk.sdk_runtime import ClaudeSDKRuntime
from src.bridges.claude.sdk.events import ClaudeResponseCompletedDAO
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport, scripted_adapter_class


def quota_frame() -> dict[str, Any]:
    """Build a structured synthetic rejection without ordinary answer fragments."""
    return {
        "type": "assistant",
        "uuid": "quota-notice-1",
        "session_id": "native-test",
        "parent_tool_use_id": None,
        "error": "rate_limit",
        "message": {
            "id": "quota-message-1",
            "role": "assistant",
            "model": "<synthetic>",
            "content": [{"type": "text", "text": "private native diagnostic"}],
        },
    }


class QuotaThenSuccessTransport(ScriptedClaudeTransport):
    """Replace only first-query vendor output, preserving SDK controls and init ordering."""

    def __init__(
        self,
        *,
        frame: dict[str, Any],
        admit_inventory: bool = True,
        invalid_inventory: bool = False,
        pause_cleanup: bool = False,
    ) -> None:
        """Retain synthetic raw input and observable user-query accounting."""
        super().__init__()
        self.frame = frame
        self.admit_inventory = admit_inventory
        self.invalid_inventory = invalid_inventory
        self.pause_cleanup = pause_cleanup
        self.cleanup_entered = asyncio.Event()
        self.release_cleanup = asyncio.Event()

    async def connect(self) -> None:
        """Allow fresh connections without resetting observable query counts."""
        self.closed = False
        await super().connect()

    def initialization_message(self) -> dict[str, Any] | None:
        """Optionally omit init to exercise premature quota admission."""
        if not self.admit_inventory:
            return None
        initialized = super().initialization_message()
        assert initialized is not None
        if self.invalid_inventory:
            initialized["tools"].append("forbidden-native-tool")
        return initialized

    async def close(self) -> None:
        """Allow tests to hold real SDK disconnect before confirmed transport closure."""
        self.cleanup_entered.set()
        if self.pause_cleanup:
            await self.release_cleanup.wait()
        await super().close()

    async def write(self, data: str) -> None:
        """Queue quota immediately after first user write; never call a provider."""
        message: dict[str, Any] = json.loads(data)
        if message["type"] == "user" and not self.prompts:
            self.prompts.append(message["message"]["content"])
            self.submitted.set()
            await self.messages.put(self.frame)
            return
        await super().write(data=data)


@pytest.mark.parametrize(
    "metadata, expected_reset",
    [
        ({}, None),
        ({"quotaLimits": {"resetsAt": 1800000000}}, "2027-01-15T08:00:00+00:00"),
        ({"apiErrorParams": {"rate_limit_info": {"resetsAt": 1800000000}}}, "2027-01-15T08:00:00+00:00"),
        ({"quotaLimits": {"resetsAt": True}}, None),
        ({"quotaLimits": {"resetsAt": "1800000000"}}, None),
        ({"quotaLimits": {"resetsAt": 1800000000.0}}, None),
        ({"quotaLimits": {"resetsAt": -1}}, None),
        ({"quotaLimits": {"resetsAt": 10**100}}, None),
        ({"quotaLimits": {"resetsAt": 0}}, None),
        ({"quotaLimits": "private malformed metadata"}, None),
        (
            {
                "quotaLimits": {"resetsAt": 1800000000},
                "apiErrorParams": {"rate_limit_info": {"resetsAt": 1800000001}},
            },
            None,
        ),
        ({"terminal": True}, None),
        (
            {
                "quotaLimits": {"resetsAt": 1800000000},
                "apiErrorParams": {"rate_limit_info": {"resetsAt": 1800000000}},
            },
            "2027-01-15T08:00:00+00:00",
        ),
        (
            {
                "quotaLimits": {"resetsAt": False},
                "apiErrorParams": {"rate_limit_info": {"resetsAt": 1800000000}},
            },
            "2027-01-15T08:00:00+00:00",
        ),
        ({"message": {"content": []}}, None),
        ({"session_id": None}, None),
    ],
)
async def test_quota_rejection_is_persisted_without_protocol_error(
    tmp_path: Path, metadata: dict[str, Any], expected_reset: str | None
) -> None:
    """A real prepared session exposes one safe failure only after native closure."""
    frame = {**quota_frame(), **metadata}
    if metadata.get("terminal"):
        frame = {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "api_error_status": 429,
            "duration_ms": 1,
            "duration_api_ms": 1,
            "num_turns": 1,
            "session_id": "native-test",
            "errors": ["private native diagnostic"],
        }
    transport = QuotaThenSuccessTransport(frame=frame)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quota",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed: list[AgentStreamEventDAO] = []
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeBridgeError) as raised:
                async for event in session.invoke(text="inspect the workspace"):
                    observed.append(event)
            assert raised.value.code == "quota_exceeded"
            assert isinstance(raised.value, ClaudeQuotaExceededError)
            assert transport.closed
            reset_at = raised.value.reset_at
            assert (reset_at.isoformat() if reset_at is not None else None) == expected_reset
            assert ("Provider reset:" in str(raised.value)) == (expected_reset is not None)
            assert not session.is_running
            assert transport.prompts == ["inspect the workspace"]
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            kinds = [event.kind for event in history]
            assert kinds.count("user_message") == kinds.count("run_failed") == 1
            assert not {"run_completed", "run_retrying", "assistant_message", "tool_call"}.intersection(kinds)
            assert [event.kind for event in observed].count("run_failed") == 1
            assert not {"run_completed", "run_retrying", "assistant_message", "tool_call_start"}.intersection(
                event.kind for event in observed
            )
            failure = next(event for event in history if event.kind == "run_failed")
            assert failure.turn_id == next(event.turn_id for event in history if event.kind == "user_message")
            public_message = next(event.content for event in observed if event.kind == "run_failed")
            assert public_message == failure.payload.error_message
            assert public_message == f"ClaudeQuotaExceededError: {raised.value}"
            assert len(public_message) <= 300
            assert "Claude usage limit reached" in str(raised.value)
            assert "No automatic retry" in str(raised.value)
            assert len(str(raised.value)) <= 300
            for forbidden in ("private native diagnostic", "Malformed", "start a new session"):
                assert forbidden not in str(raised.value)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


@pytest.mark.parametrize(
    "violation",
    [
        "session",
        "parent",
        "empty_parent",
        "session_type",
        "empty_session",
        "oversized_session",
        "unknown_error",
        "status_string",
        "status_float",
        "status_bool",
        "status_alias",
        "parent_type",
        "before_init",
        "inventory",
        "reserved",
        "success_429",
        "tool_error",
        "unknown_block",
        "missing_text",
        "malformed_message",
    ],
)
async def test_quota_does_not_bypass_native_admission(tmp_path: Path, violation: str) -> None:
    """Invalid native admission never exposes the cleanup-settled quota subtype."""
    frame = quota_frame()
    if violation == "session":
        frame["session_id"] = "wrong-native"
    elif violation == "parent":
        frame["parent_tool_use_id"] = "child-call"
    elif violation == "empty_parent":
        frame["parent_tool_use_id"] = ""
    elif violation == "session_type":
        frame["session_id"] = 123
    elif violation == "empty_session":
        frame["session_id"] = ""
    elif violation == "oversized_session":
        frame["session_id"] = "x" * 257
    elif violation == "unknown_error":
        frame["error"] = "unknown_error"
    elif violation.startswith("status_"):
        frame = {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "duration_ms": 1,
            "duration_api_ms": 1,
            "num_turns": 1,
            "session_id": "native-test",
        }
        if violation == "status_alias":
            frame["apiErrorStatus"] = 429
        else:
            frame["api_error_status"] = {"status_string": "429", "status_float": 429.0, "status_bool": True}[
                violation
            ]
    elif violation == "parent_type":
        frame["parent_tool_use_id"] = False
    elif violation == "success_429":
        frame.update(type="result", is_error=False, api_error_status=429)
    elif violation == "tool_error":
        frame["message"]["content"] = [{"type": "tool_use", "id": "bad", "name": "bash", "input": {}}]
    elif violation == "unknown_block":
        frame["message"]["content"] = [{"type": "unknown"}]
    elif violation == "missing_text":
        frame["message"]["content"] = [{"type": "text"}]
    elif violation == "malformed_message":
        frame["message"] = []
    elif violation == "reserved":
        frame = {"type": "system", "subtype": "slo_quota_rejected", "quota_rejection": {}}
    transport = QuotaThenSuccessTransport(
        frame=frame, admit_inventory=violation != "before_init", invalid_inventory=violation == "inventory"
    )
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="admission",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeBridgeError) as raised:
                async for _event in session.invoke(text="inspect"):
                    pass
            assert raised.value.code == "submission_uncertain"
            assert "usage limit reached" not in str(raised.value)
            assert transport.closed and not session.is_running
            assert transport.prompts == ["inspect"]
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert sum(event.kind == "run_failed" for event in history) == 1
            assert not any(event.kind in {"run_completed", "tool_call", "run_retrying"} for event in history)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


@pytest.mark.parametrize(
    "reset_at", [datetime(2027, 1, 1), datetime(2027, 1, 1, tzinfo=timezone(timedelta(hours=1)))]
)
def test_explicit_non_utc_reset_is_rejected(reset_at: datetime) -> None:
    """Normalized values reject naive/non-UTC instants rather than fabricating guidance."""
    from pydantic import ValidationError
    from src.bridges.claude.sdk.dao import ClaudeQuotaRejectionDAO

    with pytest.raises(ValueError, match="UTC"):
        ClaudeQuotaExceededError(reset_at=reset_at)
    with pytest.raises(ValidationError, match="UTC"):
        ClaudeQuotaRejectionDAO(reset_at=reset_at)


async def test_quoted_quota_prose_remains_an_ordinary_answer(tmp_path: Path) -> None:
    """Normal answer text is not classification authority, even when it quotes 429."""

    class QuotedQuotaTransport(ScriptedClaudeTransport):
        """Change vendor answer fragments and echoes consistently, not the parser."""

        async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
            """Supply quota-like prose on the ordinary successful answer path."""
            async for message in super().read_messages():
                if message["type"] == "stream_event":
                    event = message["event"]
                    if event["type"] == "content_block_delta":
                        event["delta"]["text"] = event["delta"]["text"].replace(
                            "Hello ", "Quoted usage limit 429 "
                        )
                elif message["type"] == "assistant":
                    message["message"]["content"][0]["text"] = "Quoted usage limit 429 bridge"
                elif message["type"] == "result":
                    message["result"] = "Quoted usage limit 429 bridge"
                yield message

    transport = QuotedQuotaTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quoted",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            events = [event async for event in session.invoke(text="quote the error")]
            assert events[-1].kind == "run_completed"
            assert events[-1].content == "Quoted usage limit 429 bridge"
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert sum(event.kind == "run_completed" for event in history) == 1
            assert not any(event.kind in {"run_failed", "run_retrying"} for event in history)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_same_bridge_remains_open_after_quota(tmp_path: Path) -> None:
    """Quota releases the native translators without sealing the retained host bridge."""
    from langchain_core.messages import HumanMessage
    from src.bridges.claude.bridge import SloClaudeBridge
    from src.bridges.dao import SloBridgeSessionOptionsDAO
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
    from tests.bridges.claude.test_lifecycle import ready_status

    transport = QuotaThenSuccessTransport(frame=quota_frame())
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    bridge = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=adapter)
    bridge.bind_tools(tools=[])
    bridge.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="bridge-quota",
            working_directory=tmp_path,
            instructions="",
        )
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeQuotaExceededError):
                async for _chunk in bridge.astream([HumanMessage(content="inspect")]):
                    pass
            chunks = [
                chunk
                async for chunk in bridge.astream(
                    [
                        HumanMessage(content="inspect"),
                        HumanMessage(content="continue explicitly"),
                    ]
                )
            ]
            assert "".join(str(chunk.content) for chunk in chunks) == "Hello bridge"
            assert len(transport.prompts) == 2
    finally:
        async with asyncio.timeout(10):
            await bridge.close()


@pytest.mark.parametrize("outcome", ["settled", "cancelled", "failed"])
async def test_quota_translator_closure_controls_reuse(tmp_path: Path, outcome: str) -> None:
    """No quota reuse or successor precedes translator closure; cancellation/failure wins."""
    from langchain_core.messages import HumanMessage
    from src.bridges.claude.bridge import SloClaudeBridge
    from src.bridges.claude.response import AIAgentResponseAdapter
    from src.bridges.dao import SloBridgeSessionOptionsDAO
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
    from tests.bridges.claude.test_lifecycle import ready_status

    entered = asyncio.Event()
    release = asyncio.Event()

    class HeldResponseAdapter(AIAgentResponseAdapter):
        """Keep real translation and hold only its public closure boundary."""

        async def close(self) -> None:
            """Expose a controlled close refusal/cancellation after native retirement."""
            entered.set()
            await release.wait()
            if outcome == "failed":
                raise OSError("synthetic translator closure refused")
            await super().close()

    transport = QuotaThenSuccessTransport(frame=quota_frame())
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    bridge = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=adapter,
        response_adapter_class=HeldResponseAdapter,
    )
    bridge.bind_tools(tools=[])
    bridge.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="translator-quota", working_directory=tmp_path, instructions=""
        )
    )

    async def invoke() -> None:
        """Drain the retained real bridge rather than replacing its stream."""
        async for _chunk in bridge.astream([HumanMessage(content="inspect")]):
            pass

    task = asyncio.create_task(coro=invoke())
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            assert transport.closed and not task.done()
            assert transport.prompts == ["inspect"]
            with pytest.raises(RuntimeError, match="active"):
                await bridge.ainvoke([HumanMessage(content="premature successor")])
            assert transport.prompts == ["inspect"]
            if outcome == "cancelled":
                bridge.request_cancellation(reason="user_abort")
                await asyncio.sleep(0)
            release.set()
            if outcome == "settled":
                with pytest.raises(ClaudeQuotaExceededError):
                    await task
                answer = await bridge.ainvoke([HumanMessage(content="continue explicitly")])
                assert answer.content == "Hello bridge"
                assert len(transport.prompts) == 2
            else:
                expected = asyncio.CancelledError if outcome == "cancelled" else OSError
                with pytest.raises(expected):
                    await task
                with pytest.raises(RuntimeError, match="closed"):
                    await bridge.ainvoke([HumanMessage(content="forbidden successor")])
                assert transport.prompts == ["inspect"]
    finally:
        release.set()
        async with asyncio.timeout(10):
            await asyncio.gather(task, return_exceptions=True)
            if outcome != "failed":
                await bridge.close()
            else:
                with pytest.raises(OSError, match="translator closure"):
                    await bridge.close()


async def test_adapter_retires_quota_invocation_without_cancellation(tmp_path: Path) -> None:
    """The same configured adapter admits a fresh explicit turn after joining quota cleanup."""
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
    from tests.bridges.claude.test_lifecycle import ready_status

    transport = QuotaThenSuccessTransport(frame=quota_frame())
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="adapter-quota",
            model_id="claude-bridge:model",
            working_directory=tmp_path,
            instructions="",
        )
    )
    try:
        async with asyncio.timeout(10):
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="one",
                    text="inspect",
                )
            )
            with pytest.raises(ClaudeQuotaExceededError):
                async for _event in adapter.read_response(invocation_id="one"):
                    pass
            assert transport.closed and transport.prompts == ["inspect"]
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="two",
                    text="continue explicitly",
                )
            )
            events = [event async for event in adapter.read_response(invocation_id="two")]
            completion = events[-1]
            assert isinstance(completion, ClaudeResponseCompletedDAO)
            assert completion.stop_reason == "stop"
            assert transport.prompts == ["inspect", "continue explicitly"]
    finally:
        async with asyncio.timeout(10):
            await adapter.close()


async def test_explicit_prompt_continues_after_quota_failure(tmp_path: Path) -> None:
    """A distinct explicit prompt retains host history but never resumes failed native state."""
    transport = QuotaThenSuccessTransport(frame=quota_frame())
    native_options: list[ClaudeAgentOptions] = []

    def recording_client(*, options: ClaudeAgentOptions, transport: Transport) -> ClaudeSDKClient:
        """Observe actual SDK construction without replacing its parser or lifecycle."""
        native_options.append(options)
        return ClaudeSDKClient(options=options, transport=transport)

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="continue-quota",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport, client_factory=recording_client),
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeQuotaExceededError):
                async for _event in session.invoke(text="inspect the workspace"):
                    pass
            assert transport.prompts == ["inspect the workspace"]
            events = [event async for event in session.invoke(text="continue explicitly")]
            assert events[-1].kind == "run_completed"
            assert session.session_id == "continue-quota"
            assert len(transport.prompts) == 2
            assert len(native_options) == 2
            assert [options.resume for options in native_options] == [None, None]
            assert all(
                options.cwd is not None and Path(options.cwd) == tmp_path for options in native_options
            )
            sent = transport.prompts[-1]
            assert isinstance(sent, list)
            transcript = "".join(block["text"] for block in sent[:-1])
            assert transcript.count("inspect the workspace") == 1
            assert sent[-1]["text"] == "continue explicitly"
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            users = [event for event in history if event.kind == "user_message"]
            assert len(users) == 2 and users[0].turn_id != users[1].turn_id
            assert sum(event.kind == "run_failed" for event in history) == 1
            assert sum(event.kind == "run_completed" for event in history) == 1
            assert not any(event.kind == "run_retrying" for event in history)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_cancel_during_quota_disconnect_wins(tmp_path: Path) -> None:
    """Supported runtime cancellation supersedes a captured quota while disconnect is held."""
    transport = QuotaThenSuccessTransport(frame=quota_frame(), pause_cleanup=True)
    runtime = ClaudeSDKRuntime(transport=transport)
    runtime.start(
        session_options=ClaudeSessionOptionsDAO(
            session_id="cancel-quota",
            model_id="claude-bridge:model",
            working_directory=tmp_path,
            instructions="",
        ),
        invocation_options=ClaudeInvocationOptionsDAO(invocation_id="first", text="inspect"),
    )

    async def drain() -> ClaudeBridgeError:
        """Observe the public runtime outcome without reaching into its owner state."""
        with pytest.raises(ClaudeBridgeError) as raised:
            async for _event in runtime.read_response():
                pass
        return raised.value

    reader = asyncio.create_task(coro=drain())
    cancellation: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(10):
            await transport.cleanup_entered.wait()
            assert not reader.done()
            cancellation = asyncio.create_task(coro=runtime.cancel())
            await asyncio.sleep(0)
            assert not cancellation.done()
            assert not reader.done()
            transport.release_cleanup.set()
            await cancellation
            error = await reader
            assert error.code == "cancelled"
            assert not isinstance(error, ClaudeQuotaExceededError)
            assert transport.closed
            assert transport.prompts == ["inspect"]
            with pytest.raises(RuntimeError, match="uncertain"):
                runtime.completed_session_id()
    finally:
        transport.release_cleanup.set()
        async with asyncio.timeout(10):
            await asyncio.gather(reader, *([cancellation] if cancellation else []), return_exceptions=True)
            await runtime.close()


class CompletedToolQuotaTransport(ToolRoundTransport):
    """Run one canonical append, then replace only the first terminal with quota."""

    async def connect(self) -> None:
        """Reconnect without erasing query or receipt accounting."""
        self.closed = False
        await super().connect()

    async def write(self, data: str) -> None:
        """Keep MCP controls real and answer the later explicit prompt without tools."""
        message: dict[str, Any] = json.loads(data)
        if message["type"] == "user" and self.prompts:
            await ScriptedClaudeTransport.write(self, data=data)
            return
        await super().write(data=data)

    async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Translate the external script's read request to a bounded temp-file append."""
        import shlex

        arguments = {"command": f"printf 'quota-once\\n' >> {shlex.quote(str(self.path))}", "timeout": 5}
        async for message in super().read_messages():
            if len(self.prompts) == 1:
                if message["type"] == "stream_event":
                    event = message["event"]
                    if (
                        event["type"] == "content_block_start"
                        and event["content_block"]["type"] == "tool_use"
                    ):
                        event["content_block"]["name"] = "mcp__slo__bash"
                    if (
                        event["type"] == "content_block_delta"
                        and event["delta"]["type"] == "input_json_delta"
                    ):
                        event["delta"]["partial_json"] = json.dumps(arguments)
                if message["type"] == "assistant":
                    for block in message["message"]["content"]:
                        if block["type"] == "tool_use":
                            block.update(name="mcp__slo__bash", input=arguments)
                if (
                    message["type"] == "control_request"
                    and message["request"].get("subtype") == "mcp_message"
                ):
                    rpc = message["request"]["message"]
                    if rpc.get("method") == "tools/call":
                        rpc["params"].update(name="bash", arguments=arguments)
                if message["type"] == "result":
                    message = quota_frame()
            yield message


async def test_completed_tool_is_not_replayed_after_quota_failure(tmp_path: Path) -> None:
    """Real append and receipt survive quota and remain contextual on explicit continuation."""
    target = tmp_path / "once.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    transport = CompletedToolQuotaTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quota-tool",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(15):
            with pytest.raises(ClaudeQuotaExceededError):
                async for _event in session.invoke(text="append once"):
                    pass
            assert target.read_text(encoding="utf-8") == "quota-once\n"
            assert len(transport.prompts) == len(transport.tool_results) == 1
            store = FilesystemSessionHistoryStore(root=tmp_path / "history")
            before = await store.load_events(session_id=session.session_id)
            assert sum(event.kind == "tool_call" for event in before) == 1
            assert sum(event.kind == "tool_result" for event in before) == 1
            assert [event.payload.content for event in before if event.kind == "assistant_message"] == [
                "Hello bridge"
            ]
            completed = [event async for event in session.invoke(text="continue with text only")]
            assert completed[-1].kind == "run_completed"
            assert target.read_text(encoding="utf-8") == "quota-once\n"
            assert len(transport.prompts) == 2 and len(transport.tool_results) == 1
            sent: object = transport.prompts[-1]
            assert isinstance(sent, list)
            transcript = "".join(block["text"] for block in sent[:-1])
            assert transcript.count("Hello bridge") == 1
            assert "quota-once" in transcript
            after = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert sum(event.kind == "tool_result" for event in after) == 1
            assert sum(event.kind == "run_failed" for event in after) == 1
            assert sum(event.kind == "run_completed" for event in after) == 1
            assert not any(event.kind == "run_retrying" for event in after)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_retained_bridge_rebuilds_completed_tool_context_after_quota(tmp_path: Path) -> None:
    """Retained bridge clears parked and consumed native state, not durable tool context."""
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
    from src.agents.tools.bundles import create_local_tools
    from src.bridges.claude.bridge import SloClaudeBridge
    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
    from src.bridges.dao import SloBridgeSessionOptionsDAO
    from tests.bridges.claude.test_lifecycle import ready_status

    target = tmp_path / "retained-once.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    transport = CompletedToolQuotaTransport(path=target)
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(),
        transport=transport,
        authentication_check=ready_status,
    )
    bridge = SloClaudeBridge(model_name="claude-bridge:claude-haiku-5-5", bridge_adapter=adapter)
    tools = create_local_tools()
    bridge.bind_tools(tools=tools)
    transport.initialized_tools = [f"mcp__slo__{tool.name}" for tool in tools]
    bridge.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="retained-tool", working_directory=tmp_path, instructions=""
        )
    )
    messages: list[BaseMessage] = [HumanMessage(content="append once")]
    try:
        async with asyncio.timeout(15):
            answer = await bridge.ainvoke(messages)
            assert isinstance(answer, AIMessage) and len(answer.tool_calls) == 1
            call = answer.tool_calls[0]
            bash = next(tool for tool in tools if tool.name == "bash")
            receipt = await bash.ainvoke(call["args"])
            messages.extend([answer, ToolMessage(content=receipt, tool_call_id=call["id"])])
            with pytest.raises(ClaudeQuotaExceededError):
                await bridge.ainvoke(messages)
            await bridge.finish_host_turn()
            messages.append(HumanMessage(content="continue with text only"))
            plan = bridge.plan_submission(messages=messages)
            assert plan is not None and plan.fresh_native_session
            assert not plan.abandon_parked_round
            resumed = await bridge.ainvoke(messages)
            assert resumed.content == "Hello bridge"
            assert target.read_text(encoding="utf-8") == "quota-once\n"
            assert len(transport.prompts) == 2 and len(transport.tool_results) == 1
            submitted: object = transport.prompts[-1]
            assert isinstance(submitted, list)
            transcript = "".join(block["text"] for block in submitted[:-1])
            assert "append once" in transcript and "quota-once" in transcript
            assert "[tool result]" in transcript
    finally:
        async with asyncio.timeout(10):
            await bridge.close()


async def test_quota_cleanup_failure_retains_owner_and_refuses_successor(tmp_path: Path) -> None:
    """A known quota cannot replace unconfirmed cleanup or authorize another query."""

    class RefusedCleanupTransport(QuotaThenSuccessTransport):
        """Refuse external closure until the test explicitly restores it."""

        refuse: bool = True

        async def close(self) -> None:
            """Keep transport ownership unconfirmed on the first close."""
            if self.refuse:
                raise OSError("synthetic cleanup refusal")
            await super().close()

    transport = RefusedCleanupTransport(frame=quota_frame())
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quota-cleanup",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(15):
            with pytest.raises(ClaudeBridgeError) as raised:
                async for _event in session.invoke(text="inspect"):
                    pass
            assert raised.value.code == "cleanup_failed"
            assert not transport.closed
            with pytest.raises(RuntimeError):
                async for _event in session.invoke(text="forbidden successor"):
                    pass
            assert transport.prompts == ["inspect"]
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert not any(event.kind in {"run_completed", "run_retrying"} for event in history)
            assert not any(
                "usage limit reached" in (event.payload.error_message or "")
                for event in history
                if event.kind == "run_failed"
            )
    finally:
        transport.refuse = False
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_quota_does_not_override_uncertain_receipt_delivery(tmp_path: Path) -> None:
    """A competing inbound rejection never downgrades the failed result write."""

    class UncertainQuotaReceiptTransport(CompletedToolQuotaTransport):
        """Accept a receipt possibly, enqueue quota, and fail that same external write."""

        async def write(self, data: str) -> None:
            """Expose both external outcomes before the runtime's next wait."""
            message: dict[str, Any] = json.loads(data)
            if message["type"] == "control_response" and message["response"]["request_id"].startswith(
                "tool-rpc"
            ):
                self.tool_results.append(message["response"])
                await self.messages.put(quota_frame())
                raise ConnectionResetError("receipt possibly delivered")
            await super().write(data=data)

    target = tmp_path / "uncertain.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    transport = UncertainQuotaReceiptTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quota-uncertain",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(15):
            with pytest.raises(ClaudeBridgeError) as raised:
                async for _event in session.invoke(text="append once"):
                    pass
            assert raised.value.code == "submission_uncertain"
            assert not isinstance(raised.value, ClaudeQuotaExceededError)
            assert target.read_text(encoding="utf-8") == "quota-once\n"
            assert len(transport.prompts) == len(transport.tool_results) == 1
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert sum(event.kind == "tool_result" for event in history) == 1
            assert sum(event.kind == "run_failed" for event in history) == 1
            assert not any(
                event.kind in {"run_completed", "run_retrying", "stream_reconnecting"} for event in history
            )
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_observed_uncertain_write_wins_over_ready_quota(tmp_path: Path) -> None:
    """A parsed quota and observed failed external write reach the same wait decision."""

    class FailedInterruptTransport(QuotaThenSuccessTransport):
        """Fail one actual control write, with delivery deliberately unknown."""

        async def write(self, data: str) -> None:
            """Raise at the wire boundary before the parsed quota is released."""
            message = json.loads(data)
            if message["type"] == "control_request" and message["request"]["subtype"] == "interrupt":
                raise ConnectionResetError("synthetic uncertain control delivery")
            await super().write(data=data)

    class SimultaneousClient(ClaudeSDKClient):
        """Retain actual SDK parsing; order an external failure before yielding quota."""

        async def receive_response(self) -> AsyncIterator[Message]:
            """Release the parsed frame only after the validated write has failed."""
            async for message in super().receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "slo_quota_rejected":
                    with pytest.raises(ClaudeBridgeError, match="delivery failed"):
                        await self.interrupt()
                yield message

    transport = FailedInterruptTransport(frame=quota_frame())
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="simultaneous-quota",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport, client_factory=SimultaneousClient),
    )
    try:
        async with asyncio.timeout(15):
            with pytest.raises(ClaudeBridgeError) as raised:
                async for _event in session.invoke(text="inspect"):
                    pass
            assert raised.value.code == "submission_uncertain"
            assert not isinstance(raised.value, ClaudeQuotaExceededError)
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            failures = [event for event in history if event.kind == "run_failed"]
            assert len(failures) == 1
            assert "usage limit reached" not in (failures[0].payload.error_message or "")
            assert transport.prompts == ["inspect"] and transport.closed
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()


async def test_quota_failure_waits_for_confirmed_cleanup(tmp_path: Path) -> None:
    """A buffered rejection cannot become a public failure before SDK disconnect settles."""
    transport = QuotaThenSuccessTransport(frame=quota_frame(), pause_cleanup=True)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="closing-quota",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed: list[AgentStreamEventDAO] = []

    async def invoke() -> ClaudeQuotaExceededError:
        """Drain the actual host turn and retain its settled typed failure."""
        with pytest.raises(ClaudeQuotaExceededError) as raised:
            async for event in session.invoke(text="inspect"):
                observed.append(event)
        return raised.value

    task = asyncio.create_task(coro=invoke())
    try:
        async with asyncio.timeout(10):
            await transport.cleanup_entered.wait()
            assert not task.done()
            assert not transport.closed
            assert not any(event.kind == "run_failed" for event in observed)
            history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id=session.session_id
            )
            assert not any(event.kind == "run_failed" for event in history)
            transport.release_cleanup.set()
            error = await task
            assert error.code == "quota_exceeded"
            assert transport.closed
            assert sum(event.kind == "run_failed" for event in observed) == 1
    finally:
        transport.release_cleanup.set()
        async with asyncio.timeout(10):
            await asyncio.gather(task, return_exceptions=True)
            await session.close_agent_resources()
