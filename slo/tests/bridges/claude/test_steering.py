"""Text steering journeys through real sessions, graphs and filesystem history."""

from contextlib import aclosing
from pathlib import Path
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import ClaudeSessionOptionsDAO
from typing import Any

# Any is confined to heterogeneous SDK kwargs and LangChain raw content/option blocks.
import asyncio

import pytest
from claude_agent_sdk import ClaudeSDKClient

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk import sdk_runtime
from tests.bridges.claude.test_shared_history import AnswerTransport, _prepare_session
from tests.cli.test_claude_bridge import ToolRoundTransport, ScriptedClaudeTransport, scripted_adapter_class
from src.bridges.claude.bridge import SloClaudeBridge
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

PROMPT = "Give an answer."
STEER = "Now refine the answer."


async def _steer_text_answer(
    *, session: SloAgentSession, transport: AnswerTransport | None = None
) -> list[AgentStreamEventDAO]:
    """Queue a steer on the first text delta, before the text-only stop decision.

    Args:
        session (SloAgentSession): Real session to drive through its public entry point.
        transport (AnswerTransport | None): Optional held native terminal to release.

    Returns:
        list[AgentStreamEventDAO]: Ordered events from the single revived host run.
    """
    events: list[AgentStreamEventDAO] = []
    queued = False
    try:
        async with asyncio.timeout(10), aclosing(session.invoke(text=PROMPT)) as stream:
            async for event in stream:
                events.append(event)
                if event.kind == "text_delta" and not queued:
                    session.steer(message=STEER)
                    queued = True
                    if transport is not None:
                        transport.release_terminal.set()
    finally:
        if transport is not None:
            transport.release_terminal.set()
        await session.close_agent_resources()
    assert queued
    assert [event.content for event in events if event.kind == "run_completed"] == ["answer-2"]
    assert [event.content for event in events if event.kind == "steering_applied"] == [STEER]
    return events


async def _history_dialogue(
    *, root: Path, session_id: str
) -> list[tuple[str, str | list[str | dict[str, Any]]]]:
    """Read and project the real durable event stream after the host run settles.

    Args:
        root (Path): Test-owned history root.
        session_id (str): Session whose history must contain both answers and the steer.

    Returns:
        list[tuple[str, str | list[str | dict[str, Any]]]]: Ordered role/content pairs from the normal replay projector.
    """
    stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(root=root).load_events(
        session_id=session_id
    )
    assert sum(event.kind == "run_completed" for event in stored) == 1
    assert not any(event.kind in {"run_failed", "run_aborted"} for event in stored)
    messages: list[BaseMessage] = await SessionHistoryProjector.build_message_history(events=stored)
    return [(message.type, message.content) for message in messages]


async def test_steer_after_text_answer_continues_native_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1: a queued steer revives a text answer and resumes native context once."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    resumes: list[str | None] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe vendor resume options without replacing SDK behavior."""

        def __init__(self, **kwargs: Any) -> None:
            """Record each native runtime construction, then delegate unchanged."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    transport = AnswerTransport()
    transport.pause_terminal = True
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    await _steer_text_answer(session=session, transport=transport)
    assert resumes == [None, "native-test"]
    assert transport.recorded == [PROMPT, STEER]
    assert transport.close_calls == 2 and transport.closed
    assert await _history_dialogue(root=tmp_path / "history", session_id="shared") == [
        ("human", PROMPT),
        ("ai", "answer-1"),
        ("human", STEER),
        ("ai", "answer-2"),
    ]


async def test_steering_events_match_a_direct_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A3: the bridge uses the same steering event and durable ordering as FauxChatModel."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = AnswerTransport()
    transport.pause_terminal = True
    bridge = await _prepare_session(tmp_path=tmp_path, transport=transport)
    bridge_events = await _steer_text_answer(session=bridge, transport=transport)
    direct = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(
                responses=[
                    FauxChatModel.assistant_message(content="answer-1"),
                    FauxChatModel.assistant_message(content="answer-2"),
                ]
            ),
            cwd=str(tmp_path),
            tools=[],
        ),
        workdir=tmp_path,
        session_id="direct",
        enable_history=True,
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
    )
    direct_events = await _steer_text_answer(session=direct)
    assert [event.kind for event in bridge_events] == [event.kind for event in direct_events]
    assert await _history_dialogue(root=tmp_path / "history", session_id="shared") == (
        await _history_dialogue(root=tmp_path / "history", session_id="direct")
    )


async def test_mounted_slash_steer_persists_in_native_dialogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enter routes /steer through the real app to the bridge and durable dialogue."""
    from src.tui.app import SloTUI
    from src.tui.components.prompt_input.component import PromptInputComponent

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = AnswerTransport()
    transport.pause_terminal = True
    session = await _prepare_session(tmp_path=tmp_path, transport=transport)
    app = SloTUI(session=session)
    try:
        async with asyncio.timeout(15), app.run_test() as pilot:
            await pilot.pause()
            composer = app.query_one(PromptInputComponent)
            composer.text = PROMPT
            await pilot.press("enter")
            while not transport.recorded or not session.is_running:
                await pilot.pause()
            composer.text = f"/steer {STEER}"
            await pilot.press("enter")
            await pilot.pause()
            transport.release_terminal.set()
            while session.is_running:
                await pilot.pause()
            assert transport.recorded == [PROMPT, STEER]
            assert await _history_dialogue(root=tmp_path / "history", session_id="shared") == [
                ("human", PROMPT),
                ("ai", "answer-1"),
                ("human", STEER),
                ("ai", "answer-2"),
            ]
    finally:
        transport.release_terminal.set()
        await session.close_agent_resources()


class ReconnectingToolRoundTransport(ToolRoundTransport):
    """Park the first connection on a real read; answer subsequent connections with text."""

    async def connect(self) -> None:
        """Permit a new SDK owner after the previous connection was joined."""
        self.closed = False
        await super().connect()

    async def write(self, data: str) -> None:
        """Use the normal tool wire once, then a plain answer without another tool call."""
        import json
        from tests.cli.test_claude_bridge import ScriptedClaudeTransport

        message = json.loads(data)
        if message["type"] == "user" and self.prompts:
            await ScriptedClaudeTransport.write(self, data=data)
            return
        await super().write(data=data)


async def _parked_model(
    *, tmp_path: Path, transport: ReconnectingToolRoundTransport
) -> tuple[SloClaudeBridge, HumanMessage, BaseMessage]:
    """Configure the real bridge and leave its first native read waiting for a result."""
    from src.agents.tools.bundles import create_read_only_tools
    from src.bridges.claude.bridge import SloClaudeBridge
    from src.bridges.claude.sdk.dao import ClaudeBridgeConfigurationDAO
    from src.bridges.dao import SloBridgeSessionOptionsDAO
    from langchain_core.messages import HumanMessage
    from tests.cli.test_claude_bridge import scripted_adapter_class

    model = SloClaudeBridge(
        model_name="claude-bridge:claude-haiku-5-5",
        bridge_adapter=scripted_adapter_class(transport=transport).register(
            configuration=ClaudeBridgeConfigurationDAO()
        ),
    )
    model.bind_tools(tools=create_read_only_tools())
    model.configure_session(
        session_options=SloBridgeSessionOptionsDAO(
            session_id="host", working_directory=tmp_path, instructions="test"
        )
    )
    human = HumanMessage(content="Read project")
    assistant = await model.ainvoke(input=[human])
    return model, human, assistant


@pytest.mark.parametrize("content", ["", [{"type": "audio", "data": "unsupported"}]])
async def test_invalid_steer_leaves_parked_round_untouched(
    tmp_path: Path, content: str | list[str | dict[str, Any]]
) -> None:
    """A4: prompt validation must not cancel a healthy native result waiter."""
    from langchain_core.messages import HumanMessage, ToolMessage

    transport = ReconnectingToolRoundTransport(path=tmp_path / "file.txt")
    model, human, assistant = await _parked_model(tmp_path=tmp_path, transport=transport)
    result = ToolMessage(content="receipt", tool_call_id="exact-native-id")
    try:
        with pytest.raises(ValueError):
            await model.ainvoke(input=[human, assistant, result, HumanMessage(content=content)])
        assert not transport.closed and transport.close_calls == 0
        assert transport.tool_results == []
        final = await model.ainvoke(input=[human, assistant, result])
        assert final.content == "Hello bridge"
        assert len(transport.tool_results) == 1
    finally:
        await model.close()


@pytest.mark.parametrize("options", [{"stop": ["halt"]}, {"temperature": 0.1}])
async def test_invalid_options_on_result_continuation_keep_bridge_open(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    """A4b: unsupported generation options fail outside native admission cleanup."""
    from langchain_core.messages import ToolMessage

    transport = ReconnectingToolRoundTransport(path=tmp_path / "file.txt")
    model, human, assistant = await _parked_model(tmp_path=tmp_path, transport=transport)
    messages: list[BaseMessage] = [
        human,
        assistant,
        ToolMessage(content="receipt", tool_call_id="exact-native-id"),
    ]
    try:
        with pytest.raises(ValueError):
            await model.ainvoke(input=messages, **options)
        assert not transport.closed and transport.close_calls == 0
        assert transport.tool_results == []
        assert (await model.ainvoke(input=messages)).content == "Hello bridge"
        assert len(transport.tool_results) == 1
    finally:
        await model.close()


async def test_steer_after_tool_round_restarts_native_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2: the real executor finishes once before restart transcribes its result and steer."""
    import os
    import threading
    import time

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    resumes: list[str | None] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Record actual SDK resume options without replacing native ownership."""

        def __init__(self, **kwargs: Any) -> None:
            """Observe a new vendor runtime construction and delegate."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)
    target = tmp_path / "held.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    os.mkfifo(target)
    entered = threading.Event()
    release = threading.Event()

    def supply_reads() -> None:
        """Serve the canonical read probes, holding its final open until steering is queued."""
        for index in range(3):
            deadline = time.monotonic() + 5
            while True:
                try:
                    fd = os.open(target, os.O_WRONLY | os.O_NONBLOCK)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError("read did not open FIFO")
                    time.sleep(0.01)
            try:
                if index == 2:
                    entered.set()
                    if not release.wait(timeout=5):
                        raise TimeoutError("steering did not release read")
                os.write(fd, b"unique real receipt\n")
            finally:
                os.close(fd)
            time.sleep(0.05)

    transport = ReconnectingToolRoundTransport(path=target)
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="tool-steer",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    model = session.agent.llm
    assert isinstance(model, SloClaudeBridge)
    assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
    old_runtime = model.bridge_adapter._runtime
    events: list[AgentStreamEventDAO] = []

    async def consume() -> None:
        """Run the real host graph while the controller waits for actual executor I/O."""
        async for event in session.invoke(text="Read held.txt"):
            events.append(event)

    writer = asyncio.create_task(coro=asyncio.to_thread(supply_reads))
    run = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(12):
            assert await asyncio.to_thread(entered.wait, 5)
            session.steer(message=STEER)
            release.set()
            await run
            await writer
        assert resumes == [None, None]
        assert old_runtime._owner is not None and old_runtime._owner.done()
        assert old_runtime._tool_bridge is not None and not old_runtime._tool_bridge.pending_calls
        assert transport.close_calls == 2 and transport.closed
        assert transport.tool_results == []
        assert len(transport.prompts) == 2
        replay = str(transport.prompts[1])
        assert replay.index("exact-native-id") < replay.index("unique real receipt") < replay.index(STEER)
        assert sum(event.kind == "steering_applied" for event in events) == 1
        assert sum(event.kind == "run_completed" for event in events) == 1
        stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
            root=tmp_path / "history"
        ).load_events(session_id="tool-steer")
        assert sum(event.kind == "tool_result" for event in stored) == 1
        assert not any(event.kind in {"run_failed", "run_aborted"} for event in stored)
    finally:
        release.set()
        await session.close_agent_resources()
        await asyncio.gather(run, writer, return_exceptions=True)


@pytest.mark.parametrize("failure", ["close", "auth", "abort"])
async def test_abandon_failure_and_abort_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A5/A5b/A6: teardown failure, unsent rejection and abort retain the correct owner."""
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.bridges.claude.sdk.exceptions import ClaudeSubmissionNotStartedError

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "receipt.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("lifecycle receipt", encoding="utf-8")
    close_entered = asyncio.Event()
    release_close = asyncio.Event()
    resumes: list[str | None] = []

    class RecordingSDKClient(ClaudeSDKClient):
        """Observe real SDK construction without changing its behavior."""

        def __init__(self, **kwargs: Any) -> None:
            """Record native resume identity before delegating."""
            resumes.append(kwargs["options"].resume)
            super().__init__(**kwargs)

    monkeypatch.setattr(target=sdk_runtime, name="ClaudeSDKClient", value=RecordingSDKClient)

    class LifecycleTransport(ReconnectingToolRoundTransport):
        """Fail or hold the first native close at the actual SDK transport boundary."""

        first_close = True

        async def close(self) -> None:
            """Expose abandon entry, then fail once or await the abort controller."""
            if self.first_close:
                self.first_close = False
                close_entered.set()
                if failure == "close":
                    raise OSError("one-shot abandon disconnect failure")
                if failure == "abort":
                    await release_close.wait()
            await super().close()

    transport = LifecycleTransport(path=target)
    base = scripted_adapter_class(transport=transport)

    class ExpiringAdapter(base):  # type: ignore[misc,valid-type]
        """Reject one post-abandon admission at the external authentication boundary."""

        rejected = False

        async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
            """Keep all native work real; simulate login expiration once after teardown."""
            if failure == "auth" and close_entered.is_set() and not self.rejected:
                self.rejected = True
                raise ClaudeSubmissionNotStartedError(
                    code="authentication_required", safe_message="login expired"
                )
            await super().start_session(session_options=session_options)

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="lifecycle",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=ExpiringAdapter,
    )
    model = session.agent.llm
    assert isinstance(model, SloClaudeBridge)
    assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
    old_runtime = model.bridge_adapter._runtime
    events: list[AgentStreamEventDAO] = []

    async def consume() -> None:
        """Queue the steer before the real read executes so it lands after the result."""
        async for event in session.invoke(text="Read receipt.txt"):
            events.append(event)
            if event.kind == "tool_call_start":
                session.steer(message=STEER)

    run = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(12):
            await close_entered.wait()
            if failure == "abort":
                session.abort()
                release_close.set()
                await run
                assert [event.kind for event in events].count("run_aborted") == 1
                assert model.is_retired()
            else:
                with pytest.raises(Exception):
                    await run
                assert any(event.kind == "run_failed" for event in events)
                assert model.is_retired() == (failure == "close")
                if failure == "auth":
                    assert not model._closed
                    assert model._consumed == [] and model._invocation_id is None
            assert resumes == [None]
            assert len(transport.prompts) == 1
            assert old_runtime._owner is not None and old_runtime._owner.done()
            assert old_runtime._tool_bridge is not None and not old_runtime._tool_bridge.pending_calls
            if failure != "abort":
                retry: list[AgentStreamEventDAO] = [
                    event async for event in session.invoke(text="Explicit retry")
                ]
                assert retry[-1].kind == "run_completed"
                assert resumes == [None, None]
                replay = str(transport.prompts[-1])
                assert "Read receipt.txt" in replay and "lifecycle receipt" in replay and STEER in replay
                assert "Explicit retry" in replay
            stored: list[SessionHistoryEventDAO] = await FilesystemSessionHistoryStore(
                root=tmp_path / "history"
            ).load_events(session_id="lifecycle")
            assert sum(event.kind == "run_aborted" for event in stored) == int(failure == "abort")
            assert sum(event.kind == "run_failed" for event in stored) == int(failure != "abort")
    finally:
        release_close.set()
        await asyncio.gather(run, return_exceptions=True)
        await session.close_agent_resources()
