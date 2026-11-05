"""Real session/graph recovery journeys with a scripted external model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession


class AdvancingRecoveryClock:
    """Record waits and advance elapsed time without sleeping or patching internals."""

    def __init__(self) -> None:
        """Start a deterministic episode clock at zero."""
        self.seconds: float = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        """Return the test's elapsed recovery clock."""
        return self.seconds

    async def wait(self, delay: float) -> None:
        """Advance the clock by the requested wait and record its ordering."""
        self.waits.append(delay)
        self.seconds += delay


class DisconnectThenAnswerModel(FauxChatModel):
    """Fail at the provider boundary before output, then return a streamed answer."""

    failures: int = 2
    calls: list[float] = Field(default_factory=list)
    recovery_clock: Any = None

    def __init__(self, *, recovery_clock: AdvancingRecoveryClock) -> None:
        """Bind the scripted external provider to the injected test clock."""
        super().__init__(responses=[], recovery_clock=recovery_clock)

    def bind_tools(self, tools: Any, **kwargs: Any) -> DisconnectThenAnswerModel:
        """Retain the single scripted provider across graph tool binding."""
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Record dispatch and fail without committing output until the script succeeds."""
        self.calls.append(self.recovery_clock())
        if len(self.calls) <= self.failures:
            raise httpx.RemoteProtocolError("private token=never-persist-this")
        yield ChatGenerationChunk(message=AIMessageChunk(content="recovered"))


@pytest.mark.asyncio
async def test_session_recovers_repeated_disconnects_with_escalating_waits_and_real_history(
    tmp_path: Path,
) -> None:
    """A real session/agent/graph retries the same submission and persists safe audits."""
    root: Path = tmp_path.resolve(strict=True)
    history_root: Path = root / "history"
    assert history_root.resolve().is_relative_to(root)
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    store = FilesystemSessionHistoryStore(root=history_root)
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(root), tools=[]),
        workdir=root,
        session_id="sleep-recovery",
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )

    events = [event async for event in session.invoke(text="hello")]
    persisted = await store.load_events(session_id=session.session_id)

    assert events[-1].kind == "run_completed"
    assert events[-1].content == "recovered"
    assert model.calls == [0.0, 1.0, 3.0]
    assert clock.waits == [1.0, 2.0]
    assert [event.kind for event in events].count("stream_reconnecting") == 2
    assert [event.kind for event in persisted].count("stream_reconnecting") == 2
    assert [event.kind for event in persisted].count("user_message") == 1
    assert persisted[-1].kind == "run_completed"
    history_file = history_root / session.session_id / "events.jsonl"
    assert history_file.resolve().is_relative_to(root)
    assert "never-persist-this" not in history_file.read_text()


@pytest.mark.asyncio
async def test_reconnect_audit_reports_session_ordinal_and_delay(tmp_path: Path) -> None:
    """Persisted and public planned retries use session pacing, not local resets."""
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    store = FilesystemSessionHistoryStore(root=tmp_path.resolve() / "history")
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="audit",
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    events = [event async for event in session.invoke(text="hello")]
    persisted = await store.load_events(session_id="audit")
    public = [event.metadata for event in events if event.kind == "stream_reconnecting"]
    audits = [event.payload.metadata for event in persisted if event.kind == "stream_reconnecting"]
    assert public == audits
    assert [(item["attempt"], item["retry_delay_seconds"]) for item in public] == [(1, 1.0), (2, 2.0)]


@pytest.mark.asyncio
async def test_abort_during_recovery_wait_has_aborted_outcome(tmp_path: Path) -> None:
    """An operator abort during pacing must not resurrect the last stream failure."""
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)

    async def abort_wait(delay: float) -> None:
        """Request abort through the real session entry during the wait."""
        await clock.wait(delay)
        session.abort()

    store = FilesystemSessionHistoryStore(root=tmp_path.resolve() / "history")
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="abort",
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=abort_wait,
    )
    events = [event async for event in session.invoke(text="hello")]
    persisted = await store.load_events(session_id="abort")
    assert events[-1].kind == "run_aborted"
    assert persisted[-1].kind == "run_aborted"
    assert model.calls == [0.0]
    assert not session.is_running


@pytest.mark.asyncio
@pytest.mark.parametrize("abort", [False, True])
async def test_preflight_after_reconnect_wait_cannot_admit_late_or_aborted_dispatch(
    tmp_path: Path,
    abort: bool,
) -> None:
    """A real local rate preflight crosses the deadline/abort after retry planning."""
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.agents.providers.stream_recovery.dao import ProviderStreamFailure

    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"]
    entry = entry.model_copy(
        update={"runtime_profile": entry.runtime_profile.model_copy(update={"requests_per_minute": 1})}
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, "gpt-5.4": entry}})
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="preflight",
        enable_history=False,
        catalog_snapshot=snapshot,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )

    async def observe(event: Any) -> None:
        """Cross admission only when real preflight publishes its rate-window event."""
        if event.kind == "run_retrying":
            clock.seconds = 300.0
            if abort:
                session.abort()

    session.subscribe(handler=observe)
    # Stop the generator at the yielded preflight event, avoiding its real sleep.
    stream = session.invoke(text="hello")
    seen = []
    try:
        async for event in stream:
            seen.append(event)
            if event.kind == "run_retrying":
                break
        assert seen[-1].kind == "run_retrying"
        # Closing preflight would not exercise admission: the injected wait is
        # used for the real preflight in production as well as recovery pacing.
        if abort:
            remaining = [event async for event in stream]
            assert remaining[-1].kind == "run_aborted"
        else:
            with pytest.raises(ProviderStreamFailure):
                _ = [event async for event in stream]
        assert model.calls == [0.0]
    finally:
        await stream.aclose()


class CommittedThenAnswerModel(DisconnectThenAnswerModel):
    """Interrupt visible output, then inspect a fresh continuation request."""

    inputs: list[list[BaseMessage]] = Field(default_factory=list)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Commit a partial response before each scripted transport failure."""
        self.calls.append(self.recovery_clock())
        self.inputs.append(messages)
        if len(self.calls) <= self.failures:
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial work"))
            raise httpx.ReadError("private token=never-persist-this")
        yield ChatGenerationChunk(message=AIMessageChunk(content="finished"))


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, "false", "true"])
async def test_openrouter_continuation_is_paced_inspect_first_and_keeps_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flag: str | None,
) -> None:
    """OpenRouter has no enable flag and continues committed work without replay."""
    if flag is not None:
        monkeypatch.setenv("SLO_OPENROUTER_STREAM_CONTINUATION_ENABLED", flag)
    clock = AdvancingRecoveryClock()
    model = CommittedThenAnswerModel(recovery_clock=clock)
    model.model_name = "openrouter:vendor/test"
    from src.agents.model_catalog.seed import SeedModelCatalog
    from src.auth.credential_dao import ProviderName
    from src.agents.model_catalog.dao import ModelCapabilitiesDAO

    snapshot = SeedModelCatalog.load()
    entry = snapshot.entries["gpt-5.4"].model_copy(
        update={
            "model_name": model.model_name,
            "provider": ProviderName.OPENROUTER,
            "capabilities": ModelCapabilitiesDAO(
                input_modalities=("text",), output_modalities=("text",), supported_parameters=("tools",)
            ),
        }
    )
    snapshot = snapshot.model_copy(update={"entries": {**snapshot.entries, model.model_name: entry}})
    store = FilesystemSessionHistoryStore(root=tmp_path.resolve() / "history")
    session = SloAgentSession(
        agent=SloAgent(llm=model, model_name="openrouter:vendor/test", cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="continuation",
        config=SessionConfigDAO(workdir=tmp_path, model_name="openrouter:vendor/test"),
        catalog_snapshot=snapshot,
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    assert session.routed_model_name == "openrouter:vendor/test"
    events = [event async for event in session.invoke(text="complete task")]
    persisted = await store.load_events(session_id="continuation")
    assert events[-1].content == "finished"
    assert clock.waits == [1.0, 2.0]
    assert model.calls == [0.0, 1.0, 3.0]
    assert "inspect the current worktree, git diff" in str(model.inputs[1][-1].content)
    assert "Continuation attempt 2/10" in str(model.inputs[1][-1].content)
    assert "partial work" in str(model.inputs[1])
    assert [event.kind for event in persisted].count("run_retrying") == 2
    assert not any(event.kind == "stream_reconnecting" for event in persisted)
    assert "never-persist-this" not in (tmp_path / "history/continuation/events.jsonl").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("base,expected_calls,expected_time", [("1", 10, 300.0), ("0.000000001", 31, None)])
async def test_reconnect_exhaustion_enforces_independent_window_and_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: str,
    expected_calls: int,
    expected_time: float | None,
) -> None:
    """Default pacing clips at 300; a tiny base admits exactly thirty extra calls."""
    from src.agents.providers.stream_recovery.dao import ProviderStreamFailure

    monkeypatch.setenv("SLO_PROVIDER_STREAM_RECONNECT_DELAY_SECONDS", base)
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    model.failures = 100
    store = FilesystemSessionHistoryStore(root=tmp_path.resolve() / "history")
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="exhaustion",
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    with pytest.raises(ProviderStreamFailure) as caught:
        _ = [event async for event in session.invoke(text="hello")]
    assert not caught.value.partial_output_committed
    assert len(model.calls) == expected_calls
    if expected_time is not None:
        assert clock.seconds == expected_time
        assert model.calls == [0, 1, 3, 7, 15, 31, 63, 127, 191, 255]
        assert clock.waits[-1] == 45
    persisted = await store.load_events(session_id="exhaustion")
    terminal = [event for event in persisted if event.kind == "run_failed"][-1]
    assert terminal.payload.metadata["partial_output_committed"] is False
    assert not session.is_running


@pytest.mark.asyncio
async def test_continuation_default_budget_is_ten_total_submissions(tmp_path: Path) -> None:
    """Nine independent continuation waits total 255, without reconnect accounting."""
    from src.agents.providers.stream_recovery.dao import ProviderStreamFailure

    clock = AdvancingRecoveryClock()
    model = CommittedThenAnswerModel(recovery_clock=clock)
    model.failures = 100
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="continuation-budget",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    with pytest.raises(ProviderStreamFailure):
        _ = [event async for event in session.invoke(text="hello")]
    assert len(model.calls) == 10
    assert clock.waits == [1, 2, 4, 8, 16, 32, 64, 64, 64]
    assert sum(clock.waits) == 255


@pytest.mark.asyncio
async def test_successful_prompt_resets_reconnect_episode(tmp_path: Path) -> None:
    """Repeated invocations have fresh ordinals and deadlines after success."""
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="reset",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    _ = [event async for event in session.invoke(text="first")]
    clock.seconds = 1000
    model.failures = len(model.calls) + 2
    _ = [event async for event in session.invoke(text="second")]
    assert model.calls == [0, 1, 3, 1000, 1001, 1003]
    assert clock.waits == [1, 2, 1, 2]


class ToolThenInterruptedModel(CommittedThenAnswerModel):
    """Execute one real temporary-file tool, then reconnect a fresh continuation."""

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Require preserved tool history and inspect-first input, never repeat the tool."""
        self.calls.append(self.recovery_clock())
        self.inputs.append(messages)
        number = len(self.calls)
        if number == 1:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "write_artifact",
                            "args": "{}",
                            "id": "effect-1",
                            "index": 0,
                        }
                    ],
                )
            )
            return
        if number == 2:
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial after artifact"))
            raise httpx.ReadError("interrupted")
        if number in (3, 4):
            raise httpx.ConnectError("before continuation output")
        yield ChatGenerationChunk(message=AIMessageChunk(content="verified artifact; finished"))


@pytest.mark.asyncio
async def test_committed_tool_effect_is_not_replayed_when_continuation_reconnects(tmp_path: Path) -> None:
    """Actual model inputs keep committed work, omit failed turns, and execute one effect."""
    from langchain_core.tools import tool

    root = tmp_path.resolve(strict=True)
    artifact = root / "artifact.txt"
    effects: list[str] = []

    @tool
    def write_artifact() -> str:
        """Write the task artifact exactly once inside the test-owned root."""
        assert artifact.resolve().is_relative_to(root)
        effects.append("write")
        artifact.write_text("completed effect", encoding="utf-8")
        return "artifact written"

    clock = AdvancingRecoveryClock()
    model = ToolThenInterruptedModel(recovery_clock=clock)
    store = FilesystemSessionHistoryStore(root=root / "history")
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(root), tools=[write_artifact]),
        workdir=root,
        session_id="tool-effect",
        history_store=store,
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    events = [event async for event in session.invoke(text="write artifact then finish")]
    assert events[-1].kind == "run_completed"
    assert effects == ["write"]
    assert artifact.read_text() == "completed effect"
    assert model.calls == [0, 0, 1, 2, 4]
    assert clock.waits == [1, 1, 2]
    for messages in model.inputs[2:]:
        assert "artifact written" in str(messages)
        assert "partial after artifact" in str(messages)
        assert "Continuation attempt 2/10" in str(messages[-1].content)
        assert "stream_reconnecting" not in str(messages)
    replay = [
        [(message.type, message.content, getattr(message, "tool_calls", None)) for message in messages]
        for messages in model.inputs[2:]
    ]
    assert replay[0] == replay[1] == replay[2]
    persisted = await store.load_events(session_id="tool-effect")
    assert [event.kind for event in persisted].count("tool_result") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("jump", [0.5, 300.0, 301.0])
async def test_reconnect_wait_handles_early_wake_and_suspend_jump(tmp_path: Path, jump: float) -> None:
    """Early wake finishes the delay; deadline and late wake never dispatch."""
    from src.agents.providers.stream_recovery.dao import ProviderStreamFailure

    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    model.failures = 1
    waits: list[float] = []

    async def wake(delay: float) -> None:
        """Return early on first wait or simulate suspended/event-loop time."""
        waits.append(delay)
        clock.seconds += jump if len(waits) == 1 else delay

    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="wake",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=wake,
    )
    if jump < 1:
        _ = [event async for event in session.invoke(text="hello")]
        assert model.calls == [0, 1]
        assert waits == [1, 0.5]
    else:
        with pytest.raises(ProviderStreamFailure):
            _ = [event async for event in session.invoke(text="hello")]
        assert model.calls == [0]
        assert waits == [1]


@pytest.mark.asyncio
async def test_abort_after_retry_audit_prevents_wait_and_dispatch(tmp_path: Path) -> None:
    """An abort from an audit subscriber must produce cleanup and the aborted result."""
    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="audit-abort",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )

    async def observe(event: Any) -> None:
        """Abort at the persisted/subscribed planned reconnect boundary."""
        if event.kind == "stream_reconnecting":
            session.abort()

    session.subscribe(handler=observe)
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_aborted"
    assert model.calls == [0]
    assert clock.waits == []
    assert not session.is_running


@pytest.mark.asyncio
@pytest.mark.parametrize("request_finish", [299.0, 300.0, 301.0])
async def test_admitted_request_can_finish_after_episode_deadline(
    tmp_path: Path, request_finish: float
) -> None:
    """The recovery deadline limits admission, not completion of a healthy request."""

    class SlowAnswerModel(DisconnectThenAnswerModel):
        """Advance simulated provider time only after the admitted second dispatch."""

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """First request fails, second finishes at the scripted elapsed time."""
            self.calls.append(self.recovery_clock())
            if len(self.calls) == 1:
                self.recovery_clock.seconds = 1000.0
                raise httpx.ReadError("initial failure outside episode")
            self.recovery_clock.seconds = 1000.0 + request_finish
            yield ChatGenerationChunk(message=AIMessageChunk(content="finished"))

    clock = AdvancingRecoveryClock()
    model = SlowAnswerModel(recovery_clock=clock)
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="inflight",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].content == "finished"
    assert model.calls == [0, 1001]
    assert clock.waits == [1]


@pytest.mark.asyncio
async def test_cancel_during_wait_ends_recovery_without_another_request(tmp_path: Path) -> None:
    """Cancellation retains the established aborted session outcome and cleanup."""
    import asyncio

    clock = AdvancingRecoveryClock()
    model = DisconnectThenAnswerModel(recovery_clock=clock)

    async def cancelled(delay: float) -> None:
        """Simulate cancellation at the asynchronous pacing boundary."""
        raise asyncio.CancelledError()

    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="cancel",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=cancelled,
    )
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_aborted"
    assert model.calls == [0]
    assert not session.is_running


@pytest.mark.asyncio
async def test_continuation_pacing_uses_submission_ordinal_after_reconnects(tmp_path: Path) -> None:
    """Two reconnects do not turn the first continuation's wait into ordinal three."""

    class ReconnectThenCommitModel(CommittedThenAnswerModel):
        """Fail before output twice, commit once, then finish a new submission."""

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Script both kinds of failure across the real agent/session boundary."""
            self.calls.append(self.recovery_clock())
            self.inputs.append(messages)
            if len(self.calls) <= 2:
                raise httpx.ConnectError("precommit")
            if len(self.calls) == 3:
                yield ChatGenerationChunk(message=AIMessageChunk(content="committed"))
                raise httpx.ReadError("committed failure")
            yield ChatGenerationChunk(message=AIMessageChunk(content="finished"))

    clock = AdvancingRecoveryClock()
    model = ReconnectThenCommitModel(recovery_clock=clock)
    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="independent",
        history_store=FilesystemSessionHistoryStore(root=tmp_path.resolve() / "history"),
        enable_history=True,
        recovery_clock=clock,
        recovery_wait=clock.wait,
    )
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].content == "finished"
    assert clock.waits == [1, 2, 1]
    assert model.calls == [0, 1, 3, 4]
    assert "Continuation attempt 2/10" in str(model.inputs[-1][-1].content)
    assert [message.content for message in model.inputs[-1] if message.type == "human"] == [
        model.inputs[-1][-1].content
    ]


@pytest.mark.asyncio
async def test_abort_during_continuation_wait_prevents_new_submission(tmp_path: Path) -> None:
    """Committed work is not replayed when the operator aborts its paced continuation."""
    clock = AdvancingRecoveryClock()
    model = CommittedThenAnswerModel(recovery_clock=clock)

    async def abort_wait(delay: float) -> None:
        """Abort through the session while the continuation is waiting."""
        session.abort()

    session = SloAgentSession(
        agent=SloAgent(llm=model, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id="continuation-abort",
        enable_history=False,
        recovery_clock=clock,
        recovery_wait=abort_wait,
    )
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_aborted"
    assert model.calls == [0]
    assert not session.is_running
