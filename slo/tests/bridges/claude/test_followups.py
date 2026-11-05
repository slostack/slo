"""Live-host multi-turn journeys; only native authentication/wire I/O is substituted."""

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from claude_agent_sdk import ClaudeSDKClient
from src.agents.hooks.hook import ShouldStopAfterTurnHookContextDAO
from src.bridges.claude.sdk import sdk_runtime
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError, ClaudeSubmissionNotStartedError

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.cli.test_claude_bridge import ToolRoundTransport, ScriptedClaudeTransport, scripted_adapter_class
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import ClaudeAuthenticationStatusDAO, ClaudeBridgeConfigurationDAO


@pytest.mark.parametrize("later,enable_history", [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize("failure", ["session_auth", "invoke_auth", "connect"])
async def test_proven_unsent_failure_allows_explicit_retry_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    later: bool,
    enable_history: bool,
) -> None:
    """E1: failed host history stays auditable but only the explicit retry reaches native."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    checks = 0
    failure_enabled = not later
    resumes: list[str | None] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe resume identity without replacing SDK behavior."""

        def __init__(self, **kwargs: Any) -> None:
            """Capture each external SDK construction, including failed connects."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Reject once during actual invocation rather than startup preparation."""
        nonlocal checks
        checks += int(failure_enabled)
        reject = checks == {"session_auth": 2, "invoke_auth": 3, "connect": -1}[failure]
        return ClaudeAuthenticationStatusDAO(
            state="login_required" if reject else "ready",
            safe_message="Fix native login and retry.",
        )

    class FailOnceTransport(ScriptedClaudeTransport):
        """Fail before SDK query on the first connection only."""

        def __init__(self) -> None:
            """Track failure independently of completed connection closure."""
            super().__init__(
                initialized_tools=tuple(f"mcp__slo__{name}" for name in ("read", "grep", "find", "ls"))
            )
            self.failed: bool = False

        async def connect(self) -> None:
            """Expose a provably unsent connect failure at the external wire seam."""
            if failure == "connect" and failure_enabled and not self.failed:
                self.failed = True
                raise OSError("synthetic connect failure")
            self.closed = False
            await super().connect()

    transport = FailOnceTransport()

    class Adapter(SloClaudeBridgeAdapter):
        """Keep all owners real, replacing only external native I/O."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> "Adapter":
            """Inject deterministic authentication and wire boundaries."""
            return cls(configuration=configuration, transport=transport, authentication_check=status)

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="retry",
            enable_history=enable_history,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=Adapter,
    )
    try:
        async with asyncio.timeout(10):
            if later:
                first = [event async for event in session.invoke(text="first")]
                assert first[-1].kind == "run_completed"
                failure_enabled = True
                # Startup auth already ran; the next attempt checks session then invoke.
                checks = 1
            with pytest.raises(ClaudeSubmissionNotStartedError) as rejected:
                _ = [event async for event in session.invoke(text="failed prompt")]
            assert isinstance(rejected.value, ClaudeBridgeError)
            assert rejected.value.code == (
                "submission_not_started" if failure == "connect" else "authentication_required"
            )
            assert "synthetic connect failure" not in str(rejected.value)
            assert len(str(rejected.value)) <= 300
            assert transport.prompts == (["first"] if later else [])
            result = [event async for event in session.invoke(text="explicit retry")]
            assert result[-1].kind == "run_completed"
            # Parity with the host: whatever the graph replays reaches Claude, and only once.
            assert transport.prompts[: int(later)] == (["first"] if later else [])
            sent: list[Any] = cast(Any, transport.prompts[-1])
            *transcript, prompt = sent
            assert prompt == {"type": "text", "text": "explicit retry"}
            replayed = "".join(block["text"] for block in transcript)
            assert "failed prompt" in replayed and "first" not in replayed
            assert len(transport.prompts) == 1 + int(later)
            assert resumes == ([None] if later else []) + ["native-test" if later else None] * (
                2 if failure == "connect" else 1
            )
            events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id="retry",
            )
            if not enable_history:
                assert events == []
                return
            assert sum(event.kind == "run_failed" for event in events) == 1
            assert sum(event.kind == "run_completed" for event in events) == 1 + int(later)
            assert [event.payload.content for event in events if event.kind == "user_message"] == (
                (["first"] if later else []) + ["failed prompt", "explicit retry"]
            )
    finally:
        await session.close_agent_resources()


class FollowupTransport(ToolRoundTransport):
    """Represent native transcript memory across SDK resume, not host history replay."""

    def __init__(self, *, path: Path) -> None:
        """Keep the first native tool receipt as the sole source of the follow-up answer."""
        super().__init__(path=path)
        self.resumes: list[str | None] = []

    async def connect(self) -> None:
        """Open another scripted native connection without losing transcript memory."""
        self.closed = False
        await super().connect()

    async def write(self, data: str) -> None:
        """Only a correctly resumed second query can answer from the prior tool result."""
        message: dict[str, Any] = json.loads(data)
        if message["type"] != "user" or not self.prompts:
            await super().write(data=data)
            return
        self.prompts.append(message["message"]["content"])
        assert self.resumes == [None, "native-test"]
        assert len(self.tool_results) == 1
        receipt = json.dumps(self.tool_results[0])
        assert "orchid-73" in receipt
        answer = "The previous tool found orchid-73."
        for event in [
            {"type": "message_start", "message": {"id": "response-test", "role": "assistant"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": answer}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]:
            await self.messages.put(
                {"type": "stream_event", "uuid": "followup", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": 1,
                "duration_api_ms": 1,
                "num_turns": 1,
                "session_id": "native-test",
                "result": answer,
            }
        )


async def test_host_stop_joins_native_tools_before_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E3: a host hook must not leave the SDK waiting for an unsent tool result."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "answer.txt"
    assert project.resolve().is_relative_to(tmp_path.resolve())
    project.write_text("orchid-73", encoding="utf-8")
    transport = ToolRoundTransport(path=project)

    def stop_after_tools(context: ShouldStopAfterTurnHookContextDAO) -> bool:
        """End the host run at its first tool boundary."""
        return True

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="early-stop",
            enable_history=True,
            history_root=tmp_path / "history",
            should_stop_after_turn_hook=stop_after_tools,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            async for event in session.invoke(text="Read answer.txt"):
                if event.kind == "run_completed":
                    assert transport.closed
                    assert transport.close_calls == 1
                    model = session.agent.llm
                    assert isinstance(model, SloClaudeBridge)
                    assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
                    runtime = model.bridge_adapter._runtime
                    assert runtime._owner is not None and runtime._tool_bridge is not None
                    assert runtime._owner.done()
                    assert runtime._tool_bridge.pending_calls == {}
            assert transport.tool_results == []
            assert transport.prompts == ["Read answer.txt"]
            await session.close_agent_resources()
            await session.close_agent_resources()
            assert transport.close_calls == 1
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("enable_history", [True, False])
async def test_followup_retains_native_tool_context_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enable_history: bool,
) -> None:
    """FU01–03/06: real session entry, SDK/MCP/tools and durable two-turn history."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    project = tmp_path / "answer.txt"
    assert project.resolve().is_relative_to(tmp_path.resolve())
    project.write_text("orchid-73", encoding="utf-8")
    transport = FollowupTransport(path=project)

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe external SDK construction; all SDK behavior still runs unchanged."""

        def __init__(self, **kwargs: Any) -> None:
            """Record the real resume option delivered to the external SDK boundary."""
            transport.resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(
        target=sdk_runtime,
        name="ClaudeSDKClient",
        value=RecordingSDKClient,
    )
    config = SessionConfigDAO(
        workdir=tmp_path,
        model_name="claude-bridge:claude-haiku-5-5",
        reasoning_level="off",
        session_id="followups",
        enable_history=enable_history,
        history_root=tmp_path / "history",
    )
    session = await SloAgentSession.prepare(
        config=config,
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            first = [event async for event in session.invoke(text="Read answer.txt")]
            assert any(event.kind == "run_completed" for event in first)
            # A rerun of read cannot recover the original value after this mutation.
            project.write_text("changed", encoding="utf-8")
            second = [event async for event in session.invoke(text="What did that tool find?")]
            assert any(event.kind == "run_completed" for event in second)
    finally:
        await session.close_agent_resources()
    assert transport.prompts == ["Read answer.txt", "What did that tool find?"]
    assert len(transport.tool_results) == 1
    assert transport.close_calls == 2
    events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="followups",
    )
    if not enable_history:
        assert events == []
        return
    assert sum(event.kind == "run_completed" for event in events) == 2
    assert sum(event.kind == "tool_call" for event in events) == 1
    assert sum(event.kind == "tool_result" for event in events) == 1
    answers = [event.payload.content for event in events if event.kind == "assistant_message"]
    assert answers == ["Hello bridge", "The previous tool found orchid-73."]
