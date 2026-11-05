"""Recovery journeys: _consumed means only what Claude actually saw; thinking never breaks tools."""

import asyncio
import json
from contextlib import aclosing
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeSDKClient

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk import sdk_runtime
from src.bridges.claude.sdk.exceptions import ClaudeSubmissionNotStartedError
from tests.bridges.claude.test_followups import FollowupTransport
from tests.bridges.claude.test_shared_history import ROUTE, AnswerTransport, _seed_gpt_history
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


class ThinkingFollowupTransport(FollowupTransport):
    """Start every tool round with a thinking block, as Claude does."""

    async def _emit_tool_round(self) -> None:
        """Emit thinking then one read call, with its native echo."""
        self.round += 1
        args = {"path": str(self.path)}
        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": f"tool-response-{self.round}", "role": "assistant"}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "plan read"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "tid", "name": "mcp__slo__read", "input": {}},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)},
            },
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "s", "session_id": "native-test", "event": event}
            )
        await self.messages.put(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [
                        {"type": "thinking", "thinking": "plan read", "signature": "sig"},
                        {"type": "tool_use", "id": "tid", "name": "mcp__slo__read", "input": args},
                    ],
                },
            }
        )
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
                    "params": {"name": "read", "arguments": args, "_meta": {"claudecode/toolUseId": "tid"}},
                },
            },
        }


async def test_thinking_before_tool_call_completes_and_follow_up_continues_natively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thinking, tool call, result, answer, then a follow-up that still resumes the native session."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "answer.txt"
    target.write_text("orchid-73", encoding="utf-8")
    transport = ThinkingFollowupTransport(path=target)

    class RecordingSDKClient(ClaudeSDKClient):
        """Record the real resume option."""

        def __init__(self, **kwargs: Any) -> None:
            """Record and delegate."""
            transport.resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id="think-tool",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            first = [event async for event in session.invoke(text="Read answer.txt")]
            assert first[-1].kind == "run_completed", [e.kind for e in first[-4:]]
            second = [event async for event in session.invoke(text="What did that tool find?")]
            assert second[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    assert transport.resumes == [None, "native-test"]
    assert transport.prompts[-1] == "What did that tool find?"


async def test_proven_unsent_handoff_retry_still_carries_the_whole_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A handoff Claude never received must not be recorded as seen."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await _seed_gpt_history(store=store, tmp_path=tmp_path, session_id="shared")
    transport = AnswerTransport()
    base = scripted_adapter_class(transport=transport)
    failures = [True]

    class FailingOnce(base):  # type: ignore[misc,valid-type]
        """Fail the first submission before anything is sent."""

        async def invoke_agent(self, *, invocation_options: Any) -> None:
            """Raise the typed proven-unsent error once."""
            if failures and failures.pop():
                raise ClaudeSubmissionNotStartedError(code="authentication_required", safe_message="login")
            await super().invoke_agent(invocation_options=invocation_options)

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id="shared",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=FailingOnce,
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeSubmissionNotStartedError):
                _ = [event async for event in session.invoke(text="p1")]
            retry = [event async for event in session.invoke(text="p2")]
            assert retry[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    [content] = transport.recorded
    assert isinstance(content, list)
    rendered = "".join(block.get("text", "") for block in content[:-1])
    assert "orchid-73" in rendered and "What is in notes.txt?" in rendered
    assert content[-1] == {"type": "text", "text": "p2"}


async def test_next_prompt_after_abort_hands_off_from_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a cancelled turn the session builds a fresh bridge and replays Slo history."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    transport = ToolRoundTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id="aborted",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            async with aclosing(session.invoke(text="Read a.txt")) as stream:
                async for event in stream:
                    if event.kind == "tool_call_start":
                        session.abort()
            transport.block_response = False
            follow_up = [event async for event in session.invoke(text="again")]
            assert follow_up[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    final = transport.prompts[-1]
    assert isinstance(final, list)
    assert "Read a.txt" in "".join(block.get("text", "") for block in final[:-1])
    assert final[-1] == {"type": "text", "text": "again"}


def test_assembly_reports_thinking_with_its_native_block_index() -> None:
    """Interleaved thinking blocks keep distinct positions instead of merging."""
    from src.bridges.claude.sdk.response import NativeResponseAssembly

    assembly = NativeResponseAssembly()
    assembly.consume(event={"type": "message_start", "message": {"id": "r"}})
    assembly.consume(
        event={"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "a"}}
    )
    assembly.consume(event={"type": "content_block_stop", "index": 0})
    assembly.consume(
        event={
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "thinking", "thinking": ""},
        }
    )
    fragment = assembly.consume(
        event={
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "thinking_delta", "thinking": "hmm"},
        }
    )
    assert (fragment.text, fragment.thinking, fragment.thinking_index) == ("", "hmm", 1)


async def test_second_invoke_while_first_run_is_finishing_leaves_the_agent_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retired bridge is replaced only between runs, never while a run is still publishing."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "a.txt"
    target.write_text("hello\n", encoding="utf-8")
    transport = ToolRoundTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id="concurrent",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    original = session.agent
    try:
        async with asyncio.timeout(10):
            async with aclosing(session.invoke(text="Read a.txt")) as stream:
                async for event in stream:
                    if event.kind == "tool_call_start":
                        session.abort()
                    if event.kind == "run_aborted":
                        with pytest.raises(RuntimeError, match="already"):
                            _ = [e async for e in session.invoke(text="too soon")]
                        assert session._agent is original
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("trigger", ["manual", "threshold"])
async def test_compaction_on_a_bridge_conversation_starts_a_fresh_native_session_with_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trigger: str
) -> None:
    """Spec 8.4: /compact runs the shared path; the next Claude call hands off summary plus kept tail."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    resumes: list[Any] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Record the real resume option."""

        def __init__(self, **kwargs: Any) -> None:
            """Record and delegate."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    transport = AnswerTransport()
    native_options: list[Any] = []
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="high",
            session_id="compacting",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport, session_options=native_options),
    )
    filler = "lorem ipsum " * 8000
    try:
        async with asyncio.timeout(20):
            for marker in ("MARK-ONE", "MARK-TWO", "MARK-THREE"):
                _ = [event async for event in session.invoke(text=f"{marker} {filler}")]
            if trigger == "manual":
                compacted = await session.compact_context()
                assert compacted.status == "compacted", compacted.detail
            else:
                from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

                await FilesystemSessionHistoryStore(root=tmp_path / "history").append_event(
                    event=SessionHistoryEventDAO.model_validate(
                        {
                            "session_id": "compacting",
                            "kind": "slash_command",
                            "payload": {"token_usage": 10_000_000},
                        }
                    )
                )
                assert await session._run_compaction_if_needed(turn_id="threshold")
            summarised = transport.answers
            after = [event async for event in session.invoke(text="fourth")]
            assert after[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="compacting"
    )
    summaries = [e for e in stored if e.kind == "compaction_summary"]
    assert summaries[0].payload.content == f"answer-{summarised}"
    handoff = transport.recorded[summarised]
    assert isinstance(handoff, list) and handoff[-1] == {"type": "text", "text": "fourth"}
    replayed = "".join(block.get("text", "") for block in handoff[:-1])
    assert f"answer-{summarised}" in replayed and "MARK-THREE" in replayed and "MARK-ONE" not in replayed
    assert resumes[summarised] is None
    # The summary ran on its own tool-free native session whose system channel holds the brief.
    summary_options = native_options[summarised - 1 + 0]
    assert "conversation compactor" in summary_options.instructions
    assert summary_options.tools == ()
    assert native_options[0].effort is not None
    assert summary_options.effort == native_options[0].effort
    assert resumes[summarised - 1] is None
    assert all("conversation compactor" not in o.instructions for o in native_options[: summarised - 1])
    assert isinstance(transport.recorded[summarised - 1], str)
    assert "[instructions for this request]" not in str(transport.recorded[summarised - 1])


async def test_summary_tool_use_fails_compaction_and_leaves_the_live_session_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool call during summarisation is refused; nothing empty is stored; the conversation goes on."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    resumes: list[Any] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Record the real resume option."""

        def __init__(self, **kwargs: Any) -> None:
            """Record and delegate."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)

    class ToolUseOnSummary(AnswerTransport):
        """Answer the third native request (the summary) with a tool call instead of text."""

        async def write(self, data: str) -> None:
            """Emit a tool_use block for the summary request only."""
            message: dict[str, Any] = json.loads(data)
            if message["type"] != "user" or self.answers != 2:
                await super().write(data=data)
                return
            self.answers += 1
            self.prompts.append(message["message"]["content"])
            self.recorded.append(message["message"]["content"])
            self.submitted.set()
            args = {"path": "x"}
            for event in [
                {"type": "message_start", "message": {"id": "summary-tool", "role": "assistant"}},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "tid", "name": "mcp__slo__read", "input": {}},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)},
                },
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
                {"type": "message_stop"},
            ]:
                await self.messages.put(
                    {"type": "stream_event", "uuid": "s", "session_id": "native-test", "event": event}
                )

    transport = ToolUseOnSummary()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id="summary-tool",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    filler = "lorem ipsum " * 8000
    try:
        async with asyncio.timeout(20):
            for marker in ("MARK-ONE", "MARK-TWO"):
                _ = [event async for event in session.invoke(text=f"{marker} {filler}")]
            compacted = await session.compact_context()
            assert compacted.status == "failed"
            after = [event async for event in session.invoke(text="still here")]
            assert after[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
        session_id="summary-tool"
    )
    assert not any(e.kind == "compaction_summary" for e in stored)
    assert resumes[-1] == "native-test"
    assert transport.recorded[-1] == "still here"
