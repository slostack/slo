"""Shared-history journeys: the bridge translates Slo history like any model adapter.

Only the native wire transport is scripted; session, graph, bridge, adapter and the
filesystem history store are real.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import pytest
from claude_agent_sdk import ClaudeSDKClient

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk import sdk_runtime
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class

ROUTE = "claude-bridge:claude-haiku-5-5"


class AnswerTransport(ScriptedClaudeTransport):
    """Answer every native prompt with scripted thinking and text; record exact content."""

    def __init__(self, *, thinking: Optional[str] = None) -> None:
        """Keep the optional thinking text and a per-turn answer counter."""
        super().__init__()
        self.thinking = thinking
        self.answers = 0
        self.recorded: list[Any] = []

    async def connect(self) -> None:
        """Reopen the scripted connection for each native turn."""
        self.closed = False
        await super().connect()

    async def write(self, data: str) -> None:
        """Emit a thinking block (when scripted) and a text block for each user prompt."""
        message: dict[str, Any] = json.loads(data)
        if message["type"] != "user":
            await super().write(data=data)
            return
        self.answers += 1
        self.prompts.append(message["message"]["content"])
        self.recorded.append(message["message"]["content"])
        self.submitted.set()
        answer = f"answer-{self.answers}"
        blocks: list[dict[str, Any]] = []
        if self.thinking is not None:
            blocks.append({"type": "thinking", "thinking": "", "signature": ""})
        blocks.append({"type": "text", "text": ""})
        events: list[dict[str, Any]] = [
            {"type": "message_start", "message": {"id": f"response-{self.answers}", "role": "assistant"}}
        ]
        index = 0
        if self.thinking is not None:
            events += [
                {"type": "content_block_start", "index": index, "content_block": blocks[0]},
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "thinking_delta", "thinking": self.thinking},
                },
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "signature_delta", "signature": "sig"},
                },
                {"type": "content_block_stop", "index": index},
            ]
            index += 1
        events += [
            {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": answer},
            },
            {"type": "content_block_stop", "index": index},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        for event in events:
            await self.messages.put(
                {"type": "stream_event", "uuid": "u", "session_id": "native-test", "event": event}
            )
        echo: list[dict[str, Any]] = [{"type": "text", "text": answer}]
        if self.thinking is not None:
            echo.insert(0, {"type": "thinking", "thinking": self.thinking, "signature": "sig"})
        await self.messages.put(
            {
                "type": "assistant",
                "message": {"role": "assistant", "model": "claude-sonnet-4-6", "content": echo},
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
                "result": answer,
                "stop_reason": "end_turn",
                "terminal_reason": "completed",
            }
        )


async def _prepare_session(
    *, tmp_path: Path, transport: AnswerTransport, session_id: str = "shared"
) -> SloAgentSession:
    """Open a real bridge session over the shared filesystem history store."""
    return await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name=ROUTE,
            reasoning_level="off",
            session_id=session_id,
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )


async def _seed_gpt_history(*, store: FilesystemSessionHistoryStore, tmp_path: Path, session_id: str) -> None:
    """Persist one finished gpt turn that includes a tool call and its result."""
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    call = {"name": "read", "args": {"path": "notes.txt"}, "id": "call_1", "type": "tool_call"}
    payloads: list[tuple[str, SessionHistoryEventPayloadDAO]] = [
        ("user_message", SessionHistoryEventPayloadDAO(content="What is in notes.txt?")),
        (
            "tool_call",
            SessionHistoryEventPayloadDAO(
                content="",
                tool_name="read",
                tool_call_id="call_1",
                tool_input={"path": "notes.txt"},
                tool_calls=[call],
            ),
        ),
        (
            "tool_result",
            SessionHistoryEventPayloadDAO(tool_name="read", tool_call_id="call_1", tool_output="orchid-73"),
        ),
        ("assistant_message", SessionHistoryEventPayloadDAO(content="It holds orchid-73.")),
    ]
    for kind, payload in payloads:
        await store.append_event(
            event=SessionHistoryEventDAO.model_validate(
                {"session_id": session_id, "turn_id": "gpt-turn", "kind": kind, "payload": payload}
            )
        )
    await store.append_event(
        event=SessionHistoryEventDAO.model_validate(
            {"session_id": session_id, "turn_id": "gpt-turn", "kind": "run_completed", "payload": {}}
        )
    )


async def test_resume_gpt_history_on_bridge_sends_ordered_transcript_then_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 8.1: a gpt-written session resumes on Claude with its whole history."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await _seed_gpt_history(store=store, tmp_path=tmp_path, session_id="shared")
    transport = AnswerTransport()
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    try:
        async with asyncio.timeout(10):
            events = [event async for event in session.invoke(text="And the colour?")]
        assert events[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()
    [content] = transport.recorded
    assert isinstance(content, list)
    *transcript, prompt = content
    assert prompt == {"type": "text", "text": "And the colour?"}
    rendered = "".join(block["text"] for block in transcript)
    order = [
        rendered.index(fragment)
        for fragment in ("What is in notes.txt?", "name=read", "call_1", '"path": "notes.txt"', "orchid-73")
    ]
    assert order == sorted(order)
    assert rendered.rindex("It holds orchid-73.") > order[-1]
    stored = await store.load_events(session_id="shared")
    answers = [e.payload.content for e in stored if e.kind == "assistant_message"]
    assert answers == ["It holds orchid-73.", "answer-1"]


async def test_bridge_written_history_replays_to_direct_model_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 8.2: bridge output is ordinary history. Checks projector output only, not a live direct-model call."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = AnswerTransport()
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    try:
        async with asyncio.timeout(10):
            _ = [event async for event in session.invoke(text="hello")]
    finally:
        await session.close_agent_resources()
    stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(session_id="shared")
    messages = await SessionHistoryProjector.build_message_history(events=stored)
    assert [(m.type, m.content) for m in messages] == [("human", "hello"), ("ai", "answer-1")]


async def test_mixed_turn_continues_natively_and_sends_only_unseen_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 8.3: Claude, another model, Claude: native resume plus the unseen delta."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = AnswerTransport()
    resumes: list[Optional[str]] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe the real resume option handed to the SDK."""

        def __init__(self, **kwargs: Any) -> None:
            """Record resume identity and delegate unchanged."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    try:
        async with asyncio.timeout(10):
            _ = [event async for event in session.invoke(text="first")]
            for kind, text in (("user_message", "from gpt"), ("assistant_message", "gpt answered")):
                await store.append_event(
                    event=SessionHistoryEventDAO.model_validate(
                        {
                            "session_id": "shared",
                            "turn_id": "gpt-turn",
                            "kind": kind,
                            "payload": SessionHistoryEventPayloadDAO(content=text),
                        }
                    )
                )
            await store.append_event(
                event=SessionHistoryEventDAO.model_validate(
                    {"session_id": "shared", "turn_id": "gpt-turn", "kind": "run_completed", "payload": {}}
                )
            )
            _ = [event async for event in session.invoke(text="second")]
    finally:
        await session.close_agent_resources()
    assert resumes == [None, "native-test"]
    assert transport.recorded[0] == "first"
    *transcript, prompt = transport.recorded[1]
    assert prompt == {"type": "text", "text": "second"}
    rendered = "".join(block["text"] for block in transcript)
    assert "from gpt" in rendered and "gpt answered" in rendered
    assert "first" not in rendered and "answer-1" not in rendered


async def test_claude_thinking_is_stored_and_streamed_like_other_reasoning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 8.5: Claude thinking becomes the standard thinking events and stored deltas."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = AnswerTransport(thinking="weighing options")
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    try:
        async with asyncio.timeout(10):
            streamed = [event async for event in session.invoke(text="hello")]
    finally:
        await session.close_agent_resources()
    thinking = [e for e in streamed if e.kind == "thinking_delta"]
    assert "".join(e.delta or "" for e in thinking) == "weighing options"
    stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(session_id="shared")
    deltas = [e.payload.delta for e in stored if e.payload.delta_kind == "thinking_delta"]
    assert "".join(delta or "" for delta in deltas) == "weighing options"
    assert [e.payload.content for e in stored if e.kind == "assistant_message"] == ["answer-1"]


async def test_bridge_translates_exactly_the_projected_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 8.6: the bridge receives the shared projector's messages. Images are text-only here: history stores tool output as strings."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await _seed_gpt_history(store=store, tmp_path=tmp_path, session_id="shared")
    seen: list[list[Any]] = []
    original = SloClaudeBridge.plan_submission

    def spy(self: SloClaudeBridge, *, messages: list[Any]) -> Any:
        """Record the translated list and delegate to the real planner."""
        seen.append(list(messages))
        return original(self, messages=messages)

    monkeypatch.setattr(target=SloClaudeBridge, name="plan_submission", value=spy)
    transport = AnswerTransport()
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    try:
        async with asyncio.timeout(10):
            _ = [event async for event in session.invoke(text="next")]
    finally:
        await session.close_agent_resources()
    events = await store.load_events(session_id="shared")
    projected = await SessionHistoryProjector.build_message_history(
        events=[e for e in events if e.turn_id == "gpt-turn"]
    )
    [received] = seen
    translated = [m for m in received if m.type != "system"][:-1]
    assert [(m.type, m.content, getattr(m, "tool_calls", None)) for m in translated] == [
        (m.type, m.content, getattr(m, "tool_calls", None)) for m in projected
    ]


async def test_adapter_carries_ordered_text_and_image_content_and_can_start_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordered content reaches the wire; start_fresh_conversation drops the resume id."""
    import base64

    from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
    from src.bridges.claude.sdk.dao import (
        ClaudeBridgeConfigurationDAO,
        ClaudeImageDAO,
        ClaudeInvocationOptionsDAO,
        ClaudeSessionOptionsDAO,
        ClaudeTextDAO,
    )
    from tests.bridges.claude.test_lifecycle import ready_status

    resumes: list[Optional[str]] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe the real resume option handed to the SDK."""

        def __init__(self, **kwargs: Any) -> None:
            """Record resume identity and delegate unchanged."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    transport = AnswerTransport()
    adapter = SloClaudeBridgeAdapter(
        configuration=ClaudeBridgeConfigurationDAO(), transport=transport, authentication_check=ready_status
    )
    pixel = base64.b64encode(b"\x89PNG-synthetic").decode()
    await adapter.start_session(
        session_options=ClaudeSessionOptionsDAO(
            session_id="host", model_id=ROUTE, working_directory=tmp_path, instructions="host"
        )
    )
    try:
        async with asyncio.timeout(10):
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(
                    invocation_id="one",
                    content=(
                        ClaudeTextDAO(text="before"),
                        ClaudeImageDAO(media_type="image/png", data=pixel),
                        ClaudeTextDAO(text="after"),
                    ),
                )
            )
            _ = [event async for event in adapter.read_response(invocation_id="one")]
            adapter.start_fresh_conversation()
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(invocation_id="two", text="plain")
            )
            _ = [event async for event in adapter.read_response(invocation_id="two")]
            await adapter.invoke_agent(
                invocation_options=ClaudeInvocationOptionsDAO(invocation_id="three", text="plain again")
            )
            _ = [event async for event in adapter.read_response(invocation_id="three")]
    finally:
        await adapter.close()
    assert transport.recorded[0] == [
        {"type": "text", "text": "before"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": pixel}},
        {"type": "text", "text": "after"},
    ]
    assert transport.recorded[1:] == ["plain", "plain again"]
    assert resumes == [None, None, "native-test"]
