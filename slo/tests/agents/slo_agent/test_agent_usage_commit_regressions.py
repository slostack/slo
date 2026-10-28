"""Usage-owner regressions across real Faux graph/session commit boundaries."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.rate_limit.dao import RateLimitRetryPlanDAO
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO


@pytest.mark.parametrize(argnames="refresh_each_event", argvalues=[False, True])
async def test_equal_completed_usage_across_submissions(tmp_path: Path, refresh_each_event: bool) -> None:
    """Each accepted response counts once, independently of UI refresh cadence."""
    response = AIMessage(
        content="done",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )
    agent = SloAgent(llm=FauxChatModel(responses=[response, response]), tools=[], cwd=str(tmp_path))
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-regression")
    for count in (1, 2):
        events = []
        async for event in session.invoke(text="hello"):
            events.append(event)
            if refresh_each_event:
                session.refresh_usage_snapshot()
        assert events[-1].kind == "run_completed"
        assert agent.usage_capture_version == count
        for _ in range(2):
            snapshot = session.refresh_usage_snapshot()
            assert snapshot.latest_turn.total_tokens == 15
            assert snapshot.session_totals.total_tokens == count * 15


async def test_incremental_chunks_commit_only_completed_sum(tmp_path: Path) -> None:
    """Chunk deltas and their completed aggregate must not both be charged."""
    chunks = [
        AIMessageChunk(
            content=text,
            usage_metadata={
                "input_tokens": 2,
                "output_tokens": 1,
                "total_tokens": 3,
            },
        )
        for text in ("a", "b")
    ]
    agent = SloAgent(
        llm=FauxChatModel(responses=[AIMessage(content="ab")], chunk_scripts=[chunks]),
        tools=[],
        cwd=str(tmp_path),
    )
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-chunks")
    async for _ in session.invoke(text="hello"):
        session.refresh_usage_snapshot()
    assert agent.usage_capture_version == 1
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 6


@pytest.mark.parametrize(argnames="completed", argvalues=[False, True])
@pytest.mark.parametrize(argnames="cancelled", argvalues=[False, True])
async def test_usage_at_interrupted_graph_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: bool, cancelled: bool
) -> None:
    """A completed update survives interruption; an uncompleted chunk is not a completion."""
    message = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": 2,
            "output_tokens": 1,
            "total_tokens": 3,
        },
    )
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))
    failure = asyncio.CancelledError() if cancelled else RuntimeError("boundary failure")

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Inject interruption after the selected real parser boundary, without provider I/O."""
        if completed:
            yield ("updates", {"agent": {"messages": [message]}})
        else:
            yield ("messages", (AIMessageChunk(content="", usage_metadata=message.usage_metadata), {}))
        raise failure

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    events = []
    with pytest.raises(type(failure)) as raised:
        async for event in agent.invoke(query="hello"):
            events.append(event)
    assert raised.value is failure
    assert agent.usage_capture_version == int(completed)
    assert agent.last_usage_totals.total_tokens == (3 if completed else None)
    assert [event.kind for event in events].count("run_failed") == int(not cancelled)
    assert not any(event.kind == "run_completed" for event in events)


@pytest.mark.parametrize(argnames="recover", argvalues=[False, True])
async def test_precompletion_failure_then_success_charges_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recover: bool
) -> None:
    """Retry in-place and recovery in the next iteration commit only successful usage."""
    message = AIMessage(
        content="done",
        usage_metadata={
            "input_tokens": 2,
            "output_tokens": 1,
            "total_tokens": 3,
        },
    )
    agent = SloAgent(llm=FauxChatModel(responses=[message]), tools=[], cwd=str(tmp_path))
    original_stream = agent._graph.astream
    attempts = 0

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Fail before output once, then delegate to the actual Faux graph."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("retryable test failure")
        async for item in original_stream(args[0], stream_mode=["messages", "updates"]):
            yield item

    def retry(exc: BaseException, visible: bool, attempt: int) -> RateLimitRetryPlanDAO:
        """Permit exactly one pre-output retry."""
        assert not visible and attempt == 1
        return RateLimitRetryPlanDAO(retryable=True, wait_seconds=0, message="retry")

    def recovery(exc: BaseException, used: int) -> RecoveryDecisionDAO:
        """Permit the one failed iteration to become a recovery observation."""
        assert used == 0
        return RecoveryDecisionDAO(recovery_class=RecoveryClass.LLM_RECOVERABLE, reason="recover")

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    events = [
        event
        async for event in agent.invoke(
            query="hello",
            iteration_retry_policy=None if recover else retry,
            iteration_recovery_policy=recovery if recover else None,
        )
    ]
    assert attempts == 2
    assert agent.usage_capture_version == 1
    assert agent.last_usage_totals.total_tokens == 3
    assert events[-1].kind == "run_completed"
    assert sum(event.kind == ("recovery_started" if recover else "run_retrying") for event in events) == 1
    assert not any(event.kind == "run_failed" for event in events)


@pytest.mark.parametrize(argnames="fail_tool", argvalues=[False, True])
async def test_equal_usage_across_tool_iterations(tmp_path: Path, fail_tool: bool) -> None:
    """Local tool success/error results do not lose or duplicate either completed response."""
    calls: list[str] = []

    @tool
    def local_usage_probe() -> str:
        """Return a local value or a tool error without touching external resources."""
        calls.append("called")
        if fail_tool:
            raise ValueError("local tool failure")
        return "local result"

    usage = {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    responses = [
        AIMessage(
            content="",
            usage_metadata=usage,
            tool_calls=[
                FauxChatModel.tool_call_dict(name="local_usage_probe", args={}, call_id="usage-call")
            ],
        ),
        AIMessage(content="done", usage_metadata=usage),
    ]
    agent = SloAgent(llm=FauxChatModel(responses=responses), tools=[local_usage_probe], cwd=str(tmp_path))
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-tools")
    events = [event async for event in session.invoke(text="hello")]
    assert calls == ["called"]
    assert len([event for event in events if event.kind == "tool_result"]) == 1
    assert events[-1].kind == "run_completed"
    assert agent.usage_capture_version == 2
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 6


async def test_eventless_completed_response_commits_at_terminal_event(tmp_path: Path) -> None:
    """An empty response still reports known zero exactly once at normal completion."""
    response = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    )
    agent = SloAgent(llm=FauxChatModel(responses=[response]), tools=[], cwd=str(tmp_path))
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-empty")
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_completed"
    assert agent.usage_capture_version == 1
    snapshot = session.refresh_usage_snapshot()
    assert snapshot.usage_available
    assert snapshot.session_totals.total_tokens == 0


async def test_distinct_completed_messages_in_one_update_are_not_deduplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct completed messages cannot be identified solely by equal usage totals."""
    messages = [
        AIMessage(
            id=identity,
            content="",
            usage_metadata={
                "input_tokens": 2,
                "output_tokens": 1,
                "total_tokens": 3,
            },
        )
        for identity in ("first", "second")
    ]
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Supply two completed messages through the existing update parser."""
        yield ("updates", {"agent": {"messages": messages}})

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-distinct")
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_completed"
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 6


@pytest.mark.parametrize(argnames="completed", argvalues=[False, True])
@pytest.mark.parametrize(argnames="outcome", argvalues=["failure", "cancel", "abort"])
async def test_interrupted_session_preserves_completed_usage_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: bool, outcome: str
) -> None:
    """Actual session invocation persists one terminal without charging partial chunks."""
    message = AIMessage(content="", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Interrupt immediately after an eventless completion or an incomplete chunk."""
        if completed:
            yield ("updates", {"agent": {"messages": [message]}})
        else:
            yield ("messages", (AIMessageChunk(content="", usage_metadata=message.usage_metadata), {}))
        if outcome == "cancel":
            raise asyncio.CancelledError()
        if outcome == "failure":
            raise ValueError("credential terminal usage probe")
        agent.abort()
        yield ("updates", {"agent": {"messages": []}})

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=agent,
        workdir=tmp_path,
        session_id="usage-interrupted",
        history_store=store,
        enable_history=True,
    )
    events = []
    try:
        async for event in session.invoke(text="hello"):
            events.append(event)
    except ValueError as exc:
        assert outcome == "failure" and str(exc) == "credential terminal usage probe"
    else:
        assert outcome != "failure"
    terminal = "run_failed" if outcome == "failure" else "run_aborted"
    persisted = await store.load_events(session_id=session.session_id)
    assert [
        event.kind for event in persisted if event.kind in ("run_completed", "run_failed", "run_aborted")
    ] == [terminal]
    assert sum(event.kind == "assistant_message" for event in persisted) == int(completed)
    assert not any(event.kind == "run_completed" for event in events)
    for _ in range(2):
        snapshot = session.refresh_usage_snapshot()
        assert snapshot.session_totals.total_tokens == (3 if completed else None)
        assert snapshot.latest_turn.total_tokens == (3 if completed else None)
    assert agent.usage_capture_version == int(completed)


@pytest.mark.parametrize(argnames="completed_before_failure", argvalues=[False, True])
async def test_session_recovery_retains_charged_completion_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed_before_failure: bool
) -> None:
    """Recovery carries earlier completed usage, not incomplete stream metadata."""
    message = AIMessage(content="", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    agent = SloAgent(llm=FauxChatModel(responses=[message]), tools=[], cwd=str(tmp_path))
    original = agent._graph.astream
    attempts = 0

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Inject one recoverable fault and then run the real Faux graph."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if completed_before_failure:
                yield ("updates", {"agent": {"messages": [message]}})
            raise RuntimeError("recoverable usage probe")
        async for item in original(args[0], stream_mode=["messages", "updates"]):
            yield item

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=agent, workdir=tmp_path, session_id="usage-recovered", history_store=store, enable_history=True
    )
    events = [event async for event in session.invoke(text="hello")]
    assert attempts == 2
    assert sum(event.kind == "recovery_started" for event in events) == 1
    assert events[-1].kind == "run_completed"
    persisted = await store.load_events(session_id=session.session_id)
    assert sum(event.kind == "assistant_message" for event in persisted) == 1 + int(completed_before_failure)
    assert sum(event.kind == "run_completed" for event in persisted) == 1
    assert not any(event.kind in ("run_failed", "run_aborted") for event in persisted)
    assert agent.usage_capture_version == 1 + int(completed_before_failure)
    assert session.refresh_usage_snapshot().latest_turn.total_tokens == 3
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 3 * (
        1 + int(completed_before_failure)
    )


async def test_cumulative_stream_metadata_is_not_added_to_completed_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completion-only accounting ignores cumulative usage on messages-mode chunks."""
    message = AIMessage(
        content="ab", usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    )
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Deliver cumulative snapshots, followed by the authoritative completed message."""
        for text in ("a", "b"):
            yield ("messages", (AIMessageChunk(content=text, usage_metadata=message.usage_metadata), {}))
        yield ("updates", {"agent": {"messages": [message]}})

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-cumulative")
    async for _ in session.invoke(text="hello"):
        session.refresh_usage_snapshot()
    assert agent.usage_capture_version == 1
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 6


@pytest.mark.parametrize(argnames="refresh_between", argvalues=[False, True])
async def test_separate_eventless_completed_updates_preserve_all_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refresh_between: bool
) -> None:
    """The parser also supports separate completed deltas without visible events."""
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Deliver distinct completed node deltas before the next public event."""
        for identity in ("first", "second"):
            message = AIMessage(
                id=identity,
                content="",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            )
            yield ("updates", {"agent": {"messages": [message]}})
            if refresh_between:
                session.refresh_usage_snapshot()

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    session = SloAgentSession(agent=agent, workdir=tmp_path, session_id="usage-separate")
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_completed"
    assert session.refresh_usage_snapshot().session_totals.total_tokens == 6


@pytest.mark.parametrize(argnames="completed", argvalues=[False, True])
async def test_committed_output_refuses_retry_with_usage_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: bool
) -> None:
    """A rate-limit failure after visible output never replays or charges partial usage."""
    import httpx
    from openai import RateLimitError

    message = AIMessage(
        content="visible", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    )
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path))
    attempts = 0

    async def stream(*args: object, **kwargs: object) -> AsyncIterator[object]:
        """Commit visible output, optionally complete, then reject with a rate limit."""
        nonlocal attempts
        attempts += 1
        yield ("messages", (AIMessageChunk(content="visible", usage_metadata=message.usage_metadata), {}))
        if completed:
            yield ("updates", {"agent": {"messages": [message]}})
        raise RateLimitError(
            message="rate limit usage probe",
            response=httpx.Response(
                status_code=429, request=httpx.Request(method="POST", url="https://example.invalid")
            ),
            body=None,
        )

    monkeypatch.setattr(target=agent._graph, name="astream", value=stream)
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        agent=agent, workdir=tmp_path, session_id="usage-no-replay", history_store=store, enable_history=True
    )
    events = []
    with pytest.raises(RateLimitError):
        async for event in session.invoke(text="hello"):
            events.append(event)
    assert attempts == 1
    assert not any(event.kind in ("run_retrying", "recovery_started", "run_completed") for event in events)
    persisted = await store.load_events(session_id=session.session_id)
    assert sum(event.kind == "run_failed" for event in persisted) == 1
    assert sum(event.kind == "assistant_message" for event in persisted) == int(completed)
    for _ in range(2):
        assert session.refresh_usage_snapshot().session_totals.total_tokens == (3 if completed else None)
    assert agent.consume_completed_usage().total_tokens is None


async def test_pending_handoff_survives_reset_and_drains_independently_of_latest(tmp_path: Path) -> None:
    """Run reuse resets display, not undelivered usage; drain detaches its mutable value."""
    message = AIMessage(content="", usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
    agent = SloAgent(
        llm=FauxChatModel(responses=[message, AIMessage(content="")]), tools=[], cwd=str(tmp_path)
    )
    for _ in range(2):
        async for _event in agent.invoke(query="hello"):
            pass
    assert agent.last_usage_totals.total_tokens is None
    assert agent.usage_capture_version == 2
    drained = agent.consume_completed_usage()
    assert drained.total_tokens == 3
    drained.total_tokens = 999
    assert agent.consume_completed_usage().total_tokens is None
    assert agent.last_usage_totals.total_tokens is None
