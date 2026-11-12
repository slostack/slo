"""Journey tests for the streamed tool-call lifecycle (spec 107, A1 and A20).

Each scenario drives the real ``SloAgent`` graph with ``FauxChatModel`` at the
provider boundary. The first scripted response streams one provider-shaped tool
request; the real ``ToolNode`` runs the recording tools; the second response is
a plain answer. The chunk builders mirror the shapes produced by the LangChain
provider adapters Slo routes through (spec §5.1).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import BaseTool, tool

from src.agents.providers import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from textual.app import App, ComposeResult
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.chat_transcript.commands import PresentAgentEventDAO
from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptProjectionAdapter
from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from tests.tui.test_transcript_projector import FakeHost

ChunkScriptBuilder = Callable[[], list[AIMessageChunk]]

TOOL_EVENT_KINDS: frozenset[str] = frozenset(
    {"tool_call_start", "tool_call_delta", "tool_call_end", "tool_output_update", "tool_result"}
)


def chat_completions_parallel_chunks() -> list[AIMessageChunk]:
    """Build an OpenRouter/Kimi Chat Completions stream with two parallel calls.

    Opening fragments carry id, name and slot; follow-ups carry only slot and
    argument text, interleaved across slots 0 and 1.

    Returns:
        list[AIMessageChunk]: Chunks whose tool data sits only in ``tool_call_chunks``.
    """
    fragments: list[tuple[str | None, str | None, str, int]] = [
        ("call_a", "read_file", "", 0),
        ("call_b", "grep_files", "", 1),
        (None, None, '{"pa', 0),
        (None, None, '{"pat', 1),
        (None, None, 'th": "a.py"}', 0),
        (None, None, 'tern": "todo"}', 1),
    ]
    return [
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"id": call_id, "name": name, "args": args, "index": index}],
        )
        for call_id, name, args, index in fragments
    ]


def anthropic_tool_use_chunks() -> list[AIMessageChunk]:
    """Build a ChatAnthropic stream: text, ``tool_use`` placeholder, ``input_json_delta``.

    Every tool fragment is carried twice, once as a content block and once as a
    ``tool_call_chunks`` entry, exactly as ``langchain_anthropic`` emits it.

    Returns:
        list[AIMessageChunk]: Chunks carrying the call in both sources.
    """
    return [
        AIMessageChunk(content=[{"type": "text", "text": "Reading.", "index": 0}]),
        AIMessageChunk(
            content=[{"type": "tool_use", "id": "toolu_01", "name": "read_file", "input": {}, "index": 1}],
            tool_call_chunks=[{"id": "toolu_01", "name": "read_file", "args": "", "index": 1}],
        ),
        AIMessageChunk(
            content=[{"type": "input_json_delta", "partial_json": '{"path": ', "index": 1}],
            tool_call_chunks=[{"id": None, "name": None, "args": '{"path": ', "index": 1}],
        ),
        AIMessageChunk(
            content=[{"type": "input_json_delta", "partial_json": '"b.py"}', "index": 1}],
            tool_call_chunks=[{"id": None, "name": None, "args": '"b.py"}', "index": 1}],
        ),
    ]


def responses_v1_function_call_chunks() -> list[AIMessageChunk]:
    """Build an OpenAI Responses ``responses/v1`` stream for one function call.

    The opening content block carries ``call_id`` (the call id) and ``id`` (the
    output item id); follow-ups carry only slot and argument text in both sources.

    Returns:
        list[AIMessageChunk]: Chunks carrying the call in both sources.
    """
    opening: AIMessageChunk = AIMessageChunk(
        content=[
            {
                "type": "function_call",
                "name": "read_file",
                "arguments": "",
                "call_id": "call_r1",
                "id": "fc_item_1",
                "index": 0,
            }
        ],
        tool_call_chunks=[{"id": "call_r1", "name": "read_file", "args": "", "index": 0}],
    )
    follow_ups: list[AIMessageChunk] = [
        AIMessageChunk(
            content=[{"type": "function_call", "arguments": arguments, "index": 0}],
            tool_call_chunks=[{"id": None, "name": None, "args": arguments, "index": 0}],
        )
        for arguments in ('{"path"', ': "c.py"}')
    ]
    return [opening, *follow_ups]


def faux_single_chunk() -> list[AIMessageChunk]:
    """Build the faux/Claude-bridge shape: one chunk carrying a complete call.

    LangChain derives ``tool_call_chunks`` from ``tool_calls`` with ``index=None``.

    Returns:
        list[AIMessageChunk]: One chunk with the whole call.
    """
    return [
        AIMessageChunk(
            content="",
            tool_calls=[
                {"id": "call_f1", "name": "read_file", "args": {"path": "d.py"}, "type": "tool_call"}
            ],
        )
    ]


def late_named_call_chunks() -> list[AIMessageChunk]:
    """Build a stream whose call name reaches the normalizer only on the completed message.

    The named fragment arrives before any id at slot 1, so the normalizer drops it
    (no id, unknown slot). The id-only fragment then opens ``call_late`` at slot 1
    without a name. LangChain merges both by slot, so the completed message carries
    the named call and its ``tool_call_start`` is emitted from the updates channel.

    Returns:
        list[AIMessageChunk]: Two chunks for one late-named call at a nonzero slot.
    """
    return [
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"id": None, "name": "read_file", "args": '{"path": "e.py"}', "index": 1}],
        ),
        AIMessageChunk(
            content="",
            tool_call_chunks=[{"id": "call_late", "name": None, "args": "", "index": 1}],
        ),
    ]


ROUTE_SCENARIOS: list[object] = [
    pytest.param(chat_completions_parallel_chunks, ("call_a", "call_b"), id="chat_completions_parallel"),
    pytest.param(anthropic_tool_use_chunks, ("toolu_01",), id="anthropic_tool_use"),
    pytest.param(responses_v1_function_call_chunks, ("call_r1",), id="responses_v1_function_call"),
    pytest.param(faux_single_chunk, ("call_f1",), id="faux_single_chunk"),
]


def build_recording_tools(*, executed_tool_names: list[str]) -> list[BaseTool]:
    """Build every tool the fixtures call, each recording its execution.

    Args:
        executed_tool_names (list[str]): Receives one tool name per execution.

    Returns:
        list[BaseTool]: ``read_file`` and ``grep_files`` tools.
    """

    @tool
    def read_file(*, path: str) -> str:
        """Record execution and return synthetic file contents to the scripted graph.

        Args:
            path (str): Fixture path recorded through the returned content.

        Returns:
            str: Fixed synthetic contents identifying the requested path.
        """
        executed_tool_names.append("read_file")
        return f"contents of {path}"

    @tool
    def grep_files(*, pattern: str) -> str:
        """Record execution and return synthetic matches to the scripted graph.

        Args:
            pattern (str): Search pattern represented in the synthetic result.

        Returns:
            str: Fixed no-match result identifying the requested pattern.
        """
        executed_tool_names.append("grep_files")
        return f"no matches for {pattern}"

    return [read_file, grep_files]


def build_scripted_model(*, chunk_script_builder: ChunkScriptBuilder) -> FauxChatModel:
    """Script one streamed tool request followed by a plain final answer.

    Args:
        chunk_script_builder (ChunkScriptBuilder): Builder of the tool-request chunks.

    Returns:
        FauxChatModel: Model with two scripted responses and their chunk scripts.
    """
    return FauxChatModel(
        responses=[AIMessage(content=""), FauxChatModel.assistant_message(content="done")],
        chunk_scripts=[chunk_script_builder(), [AIMessageChunk(content="done")]],
    )


def tool_events_for_call(
    *, stream_events: list[AgentStreamEventDAO], tool_call_id: str
) -> list[AgentStreamEventDAO]:
    """Select one call's tool events in stream order.

    Args:
        stream_events (list[AgentStreamEventDAO]): Every event of the run.
        tool_call_id (str): Call id to select.

    Returns:
        list[AgentStreamEventDAO]: Tool events carrying that call id.
    """
    return [
        stream_event
        for stream_event in stream_events
        if stream_event.kind in TOOL_EVENT_KINDS and stream_event.tool_call_id == tool_call_id
    ]


class TestToolCallStreamJourney:
    """A1: a scripted turn's stream describes each call once, ending before its result."""

    @pytest.mark.parametrize(("chunk_script_builder", "expected_tool_call_ids"), ROUTE_SCENARIOS)
    async def test_emits_one_end_before_result_when_turn_calls_tools(
        self,
        *,
        chunk_script_builder: ChunkScriptBuilder,
        expected_tool_call_ids: tuple[str, ...],
        tmp_path: Path,
    ) -> None:
        """A1: one ``tool_call_end`` per id, before its ``tool_result``, nothing after it.

        Args:
            chunk_script_builder (ChunkScriptBuilder): Builds the selected provider-shaped tool request.
            expected_tool_call_ids (tuple[str, ...]): Original call ids expected in the stream and history.
            tmp_path (Path): Owned temporary root for the real session and history files.
        """
        executed_tool_names: list[str] = []
        agent: SloAgent = SloAgent(
            llm=build_scripted_model(chunk_script_builder=chunk_script_builder),
            cwd=str(tmp_path),
            tools=build_recording_tools(executed_tool_names=executed_tool_names),
        )

        stream_events: list[AgentStreamEventDAO] = [
            stream_event async for stream_event in agent.invoke(query="inspect the files")
        ]

        tool_event_ids: set[str | None] = {
            stream_event.tool_call_id
            for stream_event in stream_events
            if stream_event.kind in TOOL_EVENT_KINDS
        }
        assert tool_event_ids == set(expected_tool_call_ids)
        assert len(executed_tool_names) == len(expected_tool_call_ids)
        for tool_call_id in expected_tool_call_ids:
            call_kinds: list[str] = [
                stream_event.kind
                for stream_event in tool_events_for_call(
                    stream_events=stream_events, tool_call_id=tool_call_id
                )
            ]
            assert call_kinds.count("tool_call_end") == 1, (tool_call_id, call_kinds)
            assert call_kinds.count("tool_result") == 1, (tool_call_id, call_kinds)
            assert call_kinds.index("tool_call_end") < call_kinds.index("tool_result")
            assert call_kinds[-1] == "tool_result", (tool_call_id, call_kinds)
        assert stream_events[-1].kind == "run_completed"
        assert stream_events[-1].content == "done"

        host: FakeHost = FakeHost()
        projector: TranscriptProjectionAdapter = TranscriptProjectionAdapter.register(host=host)
        for stream_event in stream_events:
            await projector.handle(event=stream_event)
        assert host.mount_order.count("tool") == len(expected_tool_call_ids)
        assert set(host.tool_blocks) == set(expected_tool_call_ids)
        expected_results: dict[str, str | None] = {
            stream_event.tool_call_id: stream_event.content
            for stream_event in stream_events
            if stream_event.kind == "tool_result" and stream_event.tool_call_id is not None
        }
        assert {
            tool_call_id: tool_block.result_output for tool_call_id, tool_block in host.tool_blocks.items()
        } == expected_results
        await projector.close()


class TestToolCallWatchdogJourney:
    """A17: a late-named call keeps provider timing paused until its slow tool returns."""

    async def test_keeps_watchdog_paused_until_result_when_late_named_tool_is_slow(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A17: the tool outlives the idle deadline several times; the run still completes.

        Args:
            monkeypatch (pytest.MonkeyPatch): Scopes provider timeout settings to this test.
            tmp_path (Path): Owned temporary root for the real session and history files.
        """
        monkeypatch.setenv(name="SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS", value="0.05")
        monkeypatch.setenv(name="SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS", value="2")
        tool_started: asyncio.Event = asyncio.Event()
        tool_released: asyncio.Event = asyncio.Event()
        executed_paths: list[str] = []

        @tool
        async def read_file(*, path: str) -> str:
            """Return contents after the test releases this real tool execution.

            Args:
                path (str): Requested fixture file.

            Returns:
                str: Fixed contents once the controlled awaitable is released.
            """
            executed_paths.append(path)
            tool_started.set()
            await tool_released.wait()
            return f"contents of {path}"

        agent: SloAgent = SloAgent(
            llm=build_scripted_model(chunk_script_builder=late_named_call_chunks),
            cwd=str(tmp_path),
            tools=[read_file],
        )

        async def collect_stream_events() -> list[AgentStreamEventDAO]:
            """Drain the real graph until terminal completion; joined below after tool release.

            Returns:
                list[AgentStreamEventDAO]: Every event from the bounded run.
            """
            return [stream_event async for stream_event in agent.invoke(query="read e.py")]

        run_task: asyncio.Task[list[AgentStreamEventDAO]] = asyncio.create_task(collect_stream_events())
        try:
            async with asyncio.timeout(5.0):
                while not tool_started.is_set() and not run_task.done():
                    await asyncio.sleep(0.01)
            assert tool_started.is_set(), "tool never started"
            # Stay inside the tool for several idle deadlines.
            await asyncio.sleep(0.3)
            run_ended_during_tool: bool = run_task.done()
        finally:
            tool_released.set()
            async with asyncio.timeout(5.0):
                stream_events: list[AgentStreamEventDAO] = await run_task

        assert not run_ended_during_tool, "run ended while the local tool was still executing"
        assert executed_paths == ["e.py"]
        call_kinds: list[str] = [
            stream_event.kind
            for stream_event in tool_events_for_call(stream_events=stream_events, tool_call_id="call_late")
        ]
        assert call_kinds == ["tool_call_start", "tool_call_end", "tool_result"]
        assert not [
            stream_event for stream_event in stream_events if stream_event.kind.startswith("recovery")
        ]
        assert stream_events[-1].kind == "run_completed"
        assert stream_events[-1].content == "done"
        host: FakeHost = FakeHost()
        projector: TranscriptProjectionAdapter = TranscriptProjectionAdapter.register(host=host)
        for stream_event in stream_events:
            await projector.handle(event=stream_event)
        assert host.mount_order.count("tool") == 1
        assert host.tool_blocks["call_late"].tool_input == {"path": "e.py"}
        assert host.tool_blocks["call_late"].result_output == "contents of e.py"
        # EF4: completed-message starts use metadata index 0 even when slot 1 was mapped.
        assert next(event for event in stream_events if event.kind == "tool_call_start").content_index == 0
        await projector.close()


class TestToolCallMountedJourney:
    """A1/A20: the real session presents completed calls in a mounted Textual transcript."""

    async def test_shows_one_visible_block_per_call_when_session_runs_parallel_tools(
        self, *, tmp_path: Path
    ) -> None:
        """A1/A20: Pilot observes two painted blocks with results and durable read-back.

        Args:
            tmp_path (Path): Owned root for the real session and history files.
        """
        executed_tool_names: list[str] = []
        history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(
            root=tmp_path / "history"
        )
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=build_scripted_model(chunk_script_builder=chat_completions_parallel_chunks),
                cwd=str(tmp_path),
                tools=build_recording_tools(executed_tool_names=executed_tool_names),
            ),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=history_store,
            enable_history=True,
        )
        transcript: ChatTranscriptComponent = ChatTranscriptComponent(
            history_reader=session.hydrate_transcript_entries
        )

        class TranscriptApp(App[None]):
            """Mount the production transcript without unrelated authentication/startup flows."""

            def compose(self) -> ComposeResult:
                """Yield the real transcript for this Pilot lifetime.

                Yields:
                    ChatTranscriptComponent: The session's presentation destination.
                """
                yield transcript

        async def present_event(event: AgentStreamEventDAO) -> None:
            """Forward session events through the mounted component's public delivery entry.

            Args:
                event (AgentStreamEventDAO): Normalized event dispatched by the real session.
            """
            await transcript.handle(command=PresentAgentEventDAO(event=event))

        app: TranscriptApp = TranscriptApp()
        app.register_theme(theme=SLO_DEFAULT_THEME)
        app.theme = SLO_DEFAULT_THEME.name
        async with app.run_test(size=(120, 40)) as pilot:
            session.subscribe(handler=present_event)
            async with asyncio.timeout(10):
                async for _event in session.invoke(text="inspect files"):
                    pass
            await pilot.pause()
            blocks: list[ToolExecutionBlock] = list(app.query(ToolExecutionBlock))
            assert len(blocks) == 2
            assert {block.tool_call_id for block in blocks} == {"call_a", "call_b"}
            assert all(block.is_attached and block.visible and block.region.height > 0 for block in blocks)
            assert {block.result_output for block in blocks} == {"contents of a.py", "no matches for todo"}
            painted_text: str = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert painted_text.count("⏺") == 2
            assert "contents of a.py" in painted_text
            assert "no matches for todo" in painted_text
        history_events: list[SessionHistoryEventDAO] = await history_store.load_events(
            session_id=session.session_id
        )
        assert Counter(event.kind for event in history_events)["tool_call"] == 2
        assert Counter(event.kind for event in history_events)["tool_result"] == 2
        await session.close_agent_resources()


class TestToolCallSessionHistoryJourney:
    """A20: durable history keeps one request and one result per call id."""

    @pytest.mark.parametrize(("chunk_script_builder", "expected_tool_call_ids"), ROUTE_SCENARIOS)
    async def test_records_one_call_and_result_per_id_when_session_runs_tools(
        self,
        *,
        chunk_script_builder: ChunkScriptBuilder,
        expected_tool_call_ids: tuple[str, ...],
        tmp_path: Path,
    ) -> None:
        """A20: history read-back holds one ``tool_call`` and one ``tool_result`` per id.

        Args:
            chunk_script_builder (ChunkScriptBuilder): Builds the selected provider-shaped tool request.
            expected_tool_call_ids (tuple[str, ...]): Original call ids expected in the stream and history.
            tmp_path (Path): Owned temporary root for the real session and history files.
        """
        executed_tool_names: list[str] = []
        history_store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(
            root=tmp_path / "history"
        )
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=build_scripted_model(chunk_script_builder=chunk_script_builder),
                cwd=str(tmp_path),
                tools=build_recording_tools(executed_tool_names=executed_tool_names),
            ),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=history_store,
            enable_history=True,
        )

        async for _stream_event in session.invoke(text="inspect the files"):
            pass

        history_events: list[SessionHistoryEventDAO] = await history_store.load_events(
            session_id=session.session_id
        )
        recorded_call_ids: list[str | None] = [
            history_event.payload.tool_call_id
            for history_event in history_events
            if history_event.kind == "tool_call"
        ]
        recorded_result_ids: list[str | None] = [
            history_event.payload.tool_call_id
            for history_event in history_events
            if history_event.kind == "tool_result"
        ]
        assert Counter(recorded_call_ids) == Counter(expected_tool_call_ids)
        assert Counter(recorded_result_ids) == Counter(expected_tool_call_ids)
        assert len(executed_tool_names) == len(expected_tool_call_ids)
