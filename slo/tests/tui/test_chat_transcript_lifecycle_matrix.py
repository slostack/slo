"""Real replay and active execution across presentation lifecycle boundaries."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.transcript import ReplayEntryProjector, TranscriptEntryDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscript
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.tui.test_chat_transcript import (
    FailingOlderTranscript,
    TailNoticeTranscript,
    TranscriptTestApp,
    seed_history,
)


async def test_mixed_replay_and_empty_prepend_preserve_order_and_bytes(tmp_path: Path) -> None:
    """Real user/reasoning/tool records prepend before the unchanged newest tail."""
    store = FilesystemSessionHistoryStore(root=tmp_path)
    await store.ensure_session(session_id="mixed", workdir=tmp_path, model_name=None)
    events = [
        SessionHistoryEventDAO(
            session_id="mixed", kind="user_message", payload=SessionHistoryEventPayloadDAO(content="old user")
        ),
        SessionHistoryEventDAO(
            session_id="mixed",
            kind="assistant_delta",
            payload=SessionHistoryEventPayloadDAO(
                delta_kind="thinking_delta", delta="old thinking", block_id="reason"
            ),
        ),
        SessionHistoryEventDAO(
            session_id="mixed",
            kind="assistant_message",
            payload=SessionHistoryEventPayloadDAO(content="old answer"),
        ),
        SessionHistoryEventDAO(
            session_id="mixed",
            kind="tool_call",
            payload=SessionHistoryEventPayloadDAO(
                tool_call_id="old-tool", tool_name="echo", tool_input={"text": "old"}
            ),
        ),
        SessionHistoryEventDAO(
            session_id="mixed",
            kind="tool_result",
            payload=SessionHistoryEventPayloadDAO(tool_call_id="old-tool", tool_output="old result"),
        ),
        SessionHistoryEventDAO(
            session_id="mixed",
            kind="assistant_message",
            iteration=1,
            payload=SessionHistoryEventPayloadDAO(content=""),
        ),
    ]
    for index in range(30):
        events.append(
            SessionHistoryEventDAO(
                session_id="mixed",
                kind="assistant_message",
                iteration=index + 2,
                payload=SessionHistoryEventPayloadDAO(content=f"tail-{index:02}"),
            )
        )
    for event in events:
        await store.append_event(event=event)
    before = (tmp_path / "mixed" / "events.jsonl").read_bytes()

    async def reader() -> list[TranscriptEntryDAO]:
        """Read actual canonical bytes on every request."""
        return ReplayEntryProjector.build_entries(events=await store.load_events(session_id="mixed"))

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        await transcript.load_older()
        await transcript.load_older()
        await pilot.pause()
        assert [b.get_copyable_text() for b in transcript.query(UserMessageBlock)] == ["old user"]
        assert [b.thinking_text for b in transcript.query(AssistantStreamThinkingBlock)] == ["old thinking"]
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == [
            "old answer",
            *[f"tail-{i:02}" for i in range(30)],
        ]
        tool = transcript.query_one(ToolExecutionBlock)
        assert "old result" in tool.get_copyable_text()
        children = list(transcript.query_one("#transcript-content").children)
        assert (
            children.index(transcript.query_one(AssistantStreamThinkingBlock))
            < children.index(transcript.query(AssistantStreamBlock).first())
            < children.index(tool)
        )
        assert not transcript.query(".transcript-prepend-boundary")
    assert (tmp_path / "mixed" / "events.jsonl").read_bytes() == before


async def test_partial_older_failure_preserves_active_tool_identity(tmp_path: Path) -> None:
    """A retained replay prefix cannot steal or terminate the live tool result target."""
    entries = await seed_history(root=tmp_path, count=65)

    async def reader() -> list[TranscriptEntryDAO]:
        """Return the canonical real-store replay result."""
        return entries

    transcript = FailingOlderTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        transcript.begin_run()
        await transcript.present_event(
            event=AgentStreamEventDAO(
                kind="tool_call_end", tool_call_id="active", tool_name="echo", iteration=1
            )
        )
        active = transcript.query_one(ToolExecutionBlock)
        transcript.fail_older = True
        await transcript.load_older()
        await transcript.present_event(
            event=AgentStreamEventDAO(
                kind="tool_output_update", tool_call_id="active", content="partial", iteration=1
            )
        )
        assert transcript.query_one(ToolExecutionBlock) is active
        assert not active.has_class("-done")
        await transcript.present_event(
            event=AgentStreamEventDAO(
                kind="tool_result",
                tool_call_id="active",
                tool_name="echo",
                content="terminal result",
                iteration=1,
            )
        )
        await pilot.pause()
        assert transcript.query_one(ToolExecutionBlock) is active
        assert "terminal result" in active.get_copyable_text()
        assert active.has_class("-done")
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)][0] == "entry-05"
        await transcript.load_older()
        assert transcript.older_mounts == 2


@pytest.mark.parametrize("operation", ["clear", "hide", "blocked_clear"])
async def test_active_inference_tool_result_survives_presentation_change(
    tmp_path: Path, operation: str
) -> None:
    """Real graph execution remains live while UI is cleared/hidden; result persists once."""
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_tool() -> str:
        """Hold the real graph's harmless tool until the presentation action completes."""
        entered.set()
        await release.wait()
        return "persisted tool result"

    tool = StructuredTool.from_function(coroutine=held_tool, name="held_tool", description="Test barrier")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "held_tool", "args": {}, "id": "call-1", "type": "tool_call"}],
                    ),
                    AIMessage(content="final inference answer"),
                ]
            ),
            cwd=str(tmp_path),
            tools=[tool],
        ),
        workdir=tmp_path,
        session_id="active",
        history_store=store,
        enable_history=True,
    )
    cleanup_entered, cleanup_cancelled, cleanup_release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    result_delivered = asyncio.Event()
    entries = await seed_history(root=tmp_path / "older", count=65)
    reads = 0

    async def held_reader() -> list[TranscriptEntryDAO]:
        """Suppress cancellation until cleanup is explicitly allowed to finish."""
        nonlocal reads
        reads += 1
        if reads > 1:
            cleanup_entered.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                await cleanup_release.wait()
        return entries

    async def observe_result(event: AgentStreamEventDAO) -> None:
        """Observe the real result before the app subscriber awaits presentation."""
        if event.kind == "tool_result":
            result_delivered.set()

    session.subscribe(handler=observe_result)
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await app._submit_or_queue_prompt(text="run the held tool")
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert session.is_running
            if operation == "blocked_clear":
                transcript = app.query_one(ChatTranscript)
                await transcript.bind_history(history_reader=held_reader)
                await transcript.hydrate()
                older = asyncio.create_task(transcript.load_older())
                await asyncio.wait_for(cleanup_entered.wait(), timeout=5)
                clear = asyncio.create_task(app.action_clear())
                await asyncio.wait_for(cleanup_cancelled.wait(), timeout=5)
                release.set()
                await asyncio.wait_for(result_delivered.wait(), timeout=5)
                await asyncio.sleep(0)
                assert not clear.done()
                assert app._in_flight_task is not None and not app._in_flight_task.done()
                assert "persisted tool result" not in transcript.logical_copy_text()
                assert not any(
                    e.kind == "run_completed" for e in await store.load_events(session_id="active")
                )
                cleanup_release.set()
                await asyncio.wait_for(asyncio.gather(older, clear), timeout=5)
            elif operation == "clear":
                await app.action_clear()
            else:
                app.set_transcript_visible(visible=False)
            assert session.is_running
        finally:
            release.set()
            cleanup_release.set()
        if app._in_flight_task is not None:
            await asyncio.wait_for(app._in_flight_task, timeout=10)
        app.set_transcript_visible(visible=True)
        await pilot.pause()
        transcript = app.query_one(ChatTranscript)
        assert transcript.query(AssistantStreamBlock).last().get_copyable_text() == "final inference answer"
        assert "persisted tool result" in transcript.logical_copy_text()
        if operation == "hide":
            assert "persisted tool result" in transcript.query_one(ToolExecutionBlock).get_copyable_text()
    persisted = await store.load_events(session_id="active")
    assert (
        sum(
            event.kind == "tool_result" and event.payload.tool_output == "persisted tool result"
            for event in persisted
        )
        == 1
    )
    assert sum(event.kind == "user_message" for event in persisted) == 1
    assert sum(event.kind == "run_completed" for event in persisted) == 1


async def test_concurrent_clear_bind_close_join_before_live_delivery(tmp_path: Path) -> None:
    """Queued lifecycle operations serialize; terminal close refuses all later admission."""
    entries = await seed_history(root=tmp_path, count=65)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Keep a genuine older read alive until all lifecycle callers are queued."""
        nonlocal reads
        reads += 1
        if reads > 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
        return entries

    async def fresh() -> list[TranscriptEntryDAO]:
        """Reuse genuine history only after the prior lifetime has retired."""
        return entries

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        older = asyncio.create_task(transcript.load_older())
        await asyncio.wait_for(entered.wait(), timeout=5)
        clear = asyncio.create_task(transcript.clear())
        await asyncio.wait_for(cancelled.wait(), timeout=5)
        bind = asyncio.create_task(transcript.bind_history(history_reader=fresh))
        await asyncio.sleep(0)
        close = asyncio.create_task(transcript.close())
        await asyncio.sleep(0)
        delivery = asyncio.create_task(
            transcript.present_event(
                event=AgentStreamEventDAO(
                    kind="tool_result", tool_call_id="late", tool_name="echo", content="closed result"
                )
            )
        )
        try:
            await asyncio.sleep(0)
            assert not any(task.done() for task in (clear, bind, close, delivery))
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(older, clear, bind, close, delivery), timeout=5)
        await pilot.pause()
        assert transcript.logical_copy_text() == ""
        assert not transcript.query_one("#transcript-content").children
        await transcript.bind_history(history_reader=fresh)
        await transcript.present_event(
            event=AgentStreamEventDAO(
                kind="tool_result", tool_call_id="new", tool_name="echo", content="new result"
            )
        )
        await pilot.pause()
        assert transcript.logical_copy_text() == ""
