"""Provider settlement guard at the real graph/session entry (96.a.2 §5.1, §6.1, §6.5).

The strict live guard runs after before-agent plugin messages and before every
direct or pool-bound provider request. A settlement failure is terminal: no
retry, reconnect, compaction, messaging claim, boundary advance or extra plugin
iteration may follow it.

These tests drive the real graph, the real ``ModelPool`` router and a real
``SloAgentSession`` (nonmessaging and real local-client/SQLite/history messaging)
with an injected external provider double. No internal owner, store, plugin
dispatcher or graph collaborator is replaced.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Optional, cast
from uuid import uuid4

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field

from src.agents.providers import FauxChatModel
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.providers.stream_recovery.dao import (
    ProviderStreamFailure,
    StreamRecoveryAction,
    StreamRecoveryDecisionDAO,
)
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.graph import SloAgentStateDAO, build_slo_agent
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.message_contract_reconciler import UnsettledToolGroupError
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageApplicationMetadataDAO,
    MessageErrorDAO,
    MessageIdentityDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
)
from src.agents.slo_agent.messaging.delivery import AgentMessageSource
from src.agents.slo_agent.messaging.store import MessageStore
from src.agents.slo_agent.rate_limit.dao import RateLimitRetryPlanDAO
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import (
    PromptAttemptPlanDAO,
    PromptAttemptResultDAO,
    SloAgentSession,
)
from src.auth.credential_dao import ProviderName

_TERMINAL_STREAM_KINDS: frozenset[str] = frozenset({"run_completed", "run_aborted", "run_failed"})
_FORBIDDEN_RECOVERY_STREAM_KINDS: frozenset[str] = frozenset(
    {
        "run_retrying",
        "recovery_started",
        "recovery_succeeded",
        "recovery_exhausted",
        "stream_reconnecting",
        "compaction_started",
        "compaction_completed",
        "compaction_failed",
        "compaction_retrying",
        "compaction_advised",
    }
)

_UNSETTLED_PLUGIN: str = '''
from langchain_core.messages import ToolMessage


def register(slo):
    """Inject a tool result that answers no declared call."""

    def inject(iteration):
        from src.agents.slo_agent.plugins.dao import BeforeAgentTurnDecisionDAO

        return BeforeAgentTurnDecisionDAO(
            inject_messages=[
                ToolMessage(content="orphan result", name="echo", tool_call_id="missing-call")
            ]
        )

    slo.on_before_agent_turn(handler=inject)
'''

_COUNTING_UNSETTLED_PLUGIN: str = '''
from pathlib import Path

from langchain_core.messages import ToolMessage


def register(slo):
    """Inject an orphan result and record each before-agent turn iteration."""

    def inject(iteration):
        from src.agents.slo_agent.plugins.dao import BeforeAgentTurnDecisionDAO

        with Path({counter_path!r}).open("a", encoding="utf-8") as handle:
            handle.write(f"{{iteration}}\\n")
        return BeforeAgentTurnDecisionDAO(
            inject_messages=[
                ToolMessage(content="orphan result", name="echo", tool_call_id="missing-call")
            ]
        )

    slo.on_before_agent_turn(handler=inject)
'''


class SettlementFailingProvider(FauxChatModel):
    """External provider double that reports a settlement failure on first entry."""

    attempts: int = Field(default=0, description="Provider requests that reached the external boundary.")

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Retain explicit external provider construction."""
        super().__init__(responses=responses)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "SettlementFailingProvider":
        """Keep the counting instance when the graph binds tools.

        Args:
            tools (Sequence[object]): Tools the graph would bind.
            tool_choice (Optional[str]): Unused upstream option.
            **kwargs (object): Unused LangChain passthrough.

        Returns:
            SettlementFailingProvider: This same counter-bearing double.
        """
        self.bound_tools = list(tools)
        return self

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Count one streaming request, then raise the terminal settlement error.

        Args:
            messages (list[BaseMessage]): Provider request messages.
            stop (Optional[list[str]]): Unused stop sequences.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): Unused callbacks.
            **kwargs (Any): Unused LangChain passthrough.

        Raises:
            UnsettledToolGroupError: Always, on the first provider entry.
        """
        self.attempts += 1
        raise UnsettledToolGroupError()
        if False:  # pragma: no cover - keeps this method an async generator
            yield ChatGenerationChunk(message=AIMessageChunk(content=""))


class RecordingProvider(FauxChatModel):
    """External provider double that counts both LangChain entry modes publicly."""

    provider_calls: int = Field(
        default=0, description="Number of requests that reached the external provider boundary."
    )

    def __init__(
        self,
        *,
        responses: Sequence[AIMessage],
        chunk_scripts: Optional[Sequence[Sequence[AIMessageChunk]]] = None,
    ) -> None:
        """Retain explicit completed and streaming external provider scripts."""
        super().__init__(responses=responses, chunk_scripts=chunk_scripts)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "RecordingProvider":
        """Keep this recording instance as the bound provider double.

        Args:
            tools (Sequence[object]): Tools the graph would bind.
            tool_choice (Optional[str]): Unused upstream option.
            **kwargs (object): Unused LangChain passthrough.

        Returns:
            RecordingProvider: This same double, so the call counter is shared.
        """
        self.bound_tools = list(tools)
        return self

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Count one non-streaming request, then delegate to the scripted result.

        Args:
            messages (list[BaseMessage]): Provider request messages.
            stop (Optional[list[str]]): Unused stop sequences.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): Unused callbacks.
            **kwargs (Any): Unused LangChain passthrough.

        Returns:
            ChatResult: The scripted provider result.
        """
        self.provider_calls += 1
        return await super()._agenerate(messages=messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Count one streaming request, then delegate to the scripted stream.

        Args:
            messages (list[BaseMessage]): Provider request messages.
            stop (Optional[list[str]]): Unused stop sequences.
            run_manager (Optional[AsyncCallbackManagerForLLMRun]): Unused callbacks.
            **kwargs (Any): Unused LangChain passthrough.

        Yields:
            ChatGenerationChunk: Scripted provider chunks.
        """
        self.provider_calls += 1
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class RecordingAgentFactory:
    """Compose the real messaging agent around the injected external model."""

    def __init__(self, *, model: RecordingProvider, workdir: Path) -> None:
        """Retain only the external model and workspace root.

        Args:
            model (RecordingProvider): External model double.
            workdir (Path): Real session workspace.
        """
        self.model: RecordingProvider = model
        self.workdir: Path = workdir

    def __call__(self, *, message_source: AgentMessageSource) -> SloAgent:
        """Bind the real session source and let the session own its plugin dispatcher.

        Args:
            message_source (AgentMessageSource): The real session message source.

        Returns:
            SloAgent: Real agent wired to the session source.
        """
        return SloAgent(
            llm=self.model,
            tools=[],
            cwd=str(self.workdir),
            system_prompt="Test system",
            message_source=message_source,
        )


def _write_plugin(*, directory: Path) -> Path:
    """Write one regular Python plugin file below the test root.

    Args:
        directory (Path): Test-owned directory.

    Returns:
        Path: The written plugin path.
    """
    path: Path = directory / "unsettled_injector.py"
    assert path.resolve().is_relative_to(directory.resolve())
    path.write_text(_UNSETTLED_PLUGIN, encoding="utf-8")
    return path


def _write_counting_plugin(*, directory: Path, counter: Path) -> Path:
    """Write a plugin that injects an orphan and records each iteration.

    Args:
        directory (Path): Test-owned directory.
        counter (Path): Test-owned iteration counter file.

    Returns:
        Path: The written plugin path.
    """
    path: Path = directory / "counting_unsettled_injector.py"
    assert path.resolve().is_relative_to(directory.resolve())
    assert counter.resolve().is_relative_to(directory.resolve())
    path.write_text(
        _COUNTING_UNSETTLED_PLUGIN.format(counter_path=str(counter)),
        encoding="utf-8",
    )
    return path


def _two_member_pool(*, primary: RecordingProvider, secondary: RecordingProvider) -> ModelPool:
    """Build a real two-member fallback pool over external doubles.

    Args:
        primary (RecordingProvider): Priority-0 OpenAI member.
        secondary (RecordingProvider): Priority-1 Anthropic member.

    Returns:
        ModelPool: Validated pool router.
    """
    return ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
                ),
            ]
        ),
        models={"gpt-5.4": primary, "claude-sonnet-4-6": secondary},
    )


def _permissive_retry_policy(retry_calls: list[tuple[type[BaseException], int]]) -> Any:
    """Return a policy that would retry the first failure if asked.

    Args:
        retry_calls (list[tuple[type[BaseException], int]]): Receives every ask.

    Returns:
        IterationRetryPolicy: One-shot permissive retry decision.
    """
    remaining: list[int] = [1]

    def decide(exc: BaseException, saw_visible_output: bool, attempt_number: int) -> RateLimitRetryPlanDAO:
        retry_calls.append((type(exc), attempt_number))
        if remaining[0] <= 0:
            return RateLimitRetryPlanDAO(retryable=False, wait_seconds=0, message="stop")
        remaining[0] -= 1
        return RateLimitRetryPlanDAO(retryable=True, wait_seconds=0, message="retry")

    return decide


def _permissive_recovery_policy(recovery_calls: list[type[BaseException]]) -> Any:
    """Return a policy that would call every failure LLM-recoverable if asked.

    Args:
        recovery_calls (list[type[BaseException]]): Receives every ask.

    Returns:
        IterationRecoveryPolicy: Always-recoverable decision.
    """

    def decide(exc: BaseException, recoveries_used: int) -> RecoveryDecisionDAO:
        recovery_calls.append(type(exc))
        return RecoveryDecisionDAO(
            recovery_class=RecoveryClass.LLM_RECOVERABLE,
            reason="Permissive test policy.",
        )

    return decide


def _read_closed_application_row(
    *, database_path: Path, temporary_root: Path
) -> tuple[str, int, str, int, str]:
    """Read the one closed application's state, boundary and run identity read-only.

    Args:
        database_path (Path): Closed ``messaging.v1.sqlite3`` path.
        temporary_root (Path): Test-owned root that must contain the database.

    Returns:
        tuple[str, int, str, int, str]: Message ID, retained flag, state,
            boundary index and run ID for the single stored message.
    """
    assert database_path.resolve().is_relative_to(temporary_root.resolve())
    connection: sqlite3.Connection = sqlite3.connect(database=f"{database_path.as_uri()}?mode=ro", uri=True)
    try:
        rows: list[tuple[str, int, str, int, str]] = connection.execute(
            "SELECT message_id, retained, state, boundary_index, run_id FROM messages" " ORDER BY sequence"
        ).fetchall()
        assert len(rows) == 1
        return rows[0]
    finally:
        connection.close()


def _failed_attempt_result(
    *,
    error: BaseException,
    overflow_recovery_eligible: bool = False,
    stream_failure: Optional[ProviderStreamFailure] = None,
) -> PromptAttemptResultDAO:
    """Build a failed attempt result for the session planner decision.

    Args:
        error (BaseException): Captured terminal failure.
        overflow_recovery_eligible (bool): Whether generic overflow recovery would apply.
        stream_failure (Optional[ProviderStreamFailure]): Generic stream recovery evidence.

    Returns:
        PromptAttemptResultDAO: Frozen failed-attempt result.
    """
    return PromptAttemptResultDAO(
        turn_id="turn-1",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=error,
        overflow_recovery_eligible=overflow_recovery_eligible,
        stream_failure=stream_failure,
    )


@pytest.mark.asyncio
async def test_graph_blocks_provider_before_unsettled_context() -> None:
    """A graph invocation with an orphan result never reaches the provider."""
    provider: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    graph = build_slo_agent(llm=provider, tools=[]).graph
    state: SloAgentStateDAO = SloAgentStateDAO(
        messages=[
            HumanMessage(content="question"),
            ToolMessage(content="orphan", name="echo", tool_call_id="missing-call"),
        ]
    )
    with pytest.raises(UnsettledToolGroupError):
        await graph.ainvoke(input=state)
    assert provider.provider_calls == 0


@pytest.mark.asyncio
async def test_pool_blocks_every_member_before_unsettled_context() -> None:
    """The shared guard runs before the real ModelPool can select any member."""
    primary: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    secondary: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    graph = build_slo_agent(llm=_two_member_pool(primary=primary, secondary=secondary), tools=[]).graph
    state: SloAgentStateDAO = SloAgentStateDAO(
        messages=[HumanMessage(content="question"), ToolMessage(content="orphan", tool_call_id="orphan")]
    )
    with pytest.raises(UnsettledToolGroupError):
        await graph.ainvoke(input=state)
    assert primary.provider_calls == 0
    assert secondary.provider_calls == 0


@pytest.mark.asyncio
async def test_pool_reaches_active_member_for_valid_settled_context() -> None:
    """A settled provider context reaches exactly the active pool member."""
    primary: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="pool ok")]
    )
    secondary: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    graph = build_slo_agent(llm=_two_member_pool(primary=primary, secondary=secondary), tools=[]).graph
    await graph.ainvoke(input=SloAgentStateDAO(messages=[HumanMessage(content="question")]))
    assert primary.provider_calls == 1
    assert secondary.provider_calls == 0


@pytest.mark.asyncio
async def test_recording_provider_observes_both_entry_modes() -> None:
    """The recorder is sensitive to ``_agenerate`` and ``_astream`` alike."""
    provider: RecordingProvider = RecordingProvider(
        responses=[
            FauxChatModel.assistant_message(content="one"),
            FauxChatModel.assistant_message(content="two"),
        ],
        chunk_scripts=[[AIMessageChunk(content="streamed")]],
    )
    awaited = await provider.ainvoke([HumanMessage(content="non-streaming")])
    streamed: list[AIMessageChunk] = [
        cast(AIMessageChunk, chunk) async for chunk in provider.astream([HumanMessage(content="streaming")])
    ]
    assert provider.provider_calls == 2
    assert isinstance(awaited, AIMessage)
    assert "".join(str(chunk.content) for chunk in streamed) == "streamed"


@pytest.mark.asyncio
async def test_agent_settlement_failure_bypasses_permissive_retry_and_recovery() -> None:
    """The agent never asks a permissive retry or recovery policy about settlement."""
    provider: SettlementFailingProvider = SettlementFailingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    agent: SloAgent = SloAgent(llm=provider, tools=[])
    retry_calls: list[tuple[type[BaseException], int]] = []
    recovery_calls: list[type[BaseException]] = []
    events: list[AgentStreamEventDAO] = []
    with pytest.raises(UnsettledToolGroupError):
        async for event in agent.invoke(
            query="settle before retry",
            iteration_retry_policy=_permissive_retry_policy(retry_calls),
            iteration_recovery_policy=_permissive_recovery_policy(recovery_calls),
        ):
            events.append(event)
    kinds: list[str] = [event.kind for event in events]
    assert provider.attempts == 1
    assert retry_calls == []
    assert recovery_calls == []
    assert "run_failed" in kinds
    assert "run_retrying" not in kinds
    assert "recovery_started" not in kinds
    assert "recovery_succeeded" not in kinds
    assert "recovery_exhausted" not in kinds


@pytest.mark.asyncio
async def test_session_planner_skips_reconnect_and_compaction_for_settlement_failure(
    tmp_path: Path,
) -> None:
    """The session planner returns no retry plan before its generic planners run."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        enable_history=True,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    reconnect: ProviderStreamFailure = ProviderStreamFailure(
        decision=StreamRecoveryDecisionDAO(
            action=StreamRecoveryAction.RETRY_FRESH_CONNECTION,
            reason_code="synthetic_unsettled",
        ),
        partial_output_committed=False,
        attempt_number=1,
    )
    plan: PromptAttemptPlanDAO = PromptAttemptPlanDAO(attempt_kind="initial", text="settle")
    result: PromptAttemptResultDAO = _failed_attempt_result(
        error=UnsettledToolGroupError(),
        overflow_recovery_eligible=True,
        stream_failure=reconnect,
    )
    assert await session._derive_next_attempt_plan(plan=plan, result=result) is None


@pytest.mark.asyncio
async def test_real_messaging_session_settlement_failure_is_terminal(tmp_path: Path) -> None:
    """A real client/session/SQLite/history run stops once with zero provider calls."""
    root: Path = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    counter: Path = tmp_path / "before_agent_turns.txt"
    plugin: Path = _write_counting_plugin(directory=tmp_path, counter=counter)
    model: RecordingProvider = RecordingProvider(
        responses=[FauxChatModel.assistant_message(content="must not run")]
    )
    history: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=root)
    session_id: str = str(uuid4())
    session: SloAgentSession = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        enable_history=True,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RecordingAgentFactory(model=model, workdir=tmp_path),
        plugin_paths=[plugin],
    )
    await session.start_messaging()
    observed: list[AgentStreamEventDAO] = []
    try:
        async with asyncio.timeout(delay=10):
            with pytest.raises(UnsettledToolGroupError):
                async for event in session.invoke(text="settle this request"):
                    observed.append(event)
    finally:
        # Join the owner close before reading any durable terminal evidence.
        await session.close_messaging()

    kinds: list[str] = [event.kind for event in observed]
    terminal_kinds: list[str] = [kind for kind in kinds if kind in _TERMINAL_STREAM_KINDS]
    assert terminal_kinds == ["run_failed"]
    assert not any(kind in kinds for kind in _FORBIDDEN_RECOVERY_STREAM_KINDS)
    assert model.provider_calls == 0
    assert counter.read_text(encoding="utf-8").splitlines() == ["0"]

    database_path: Path = root / session_id / "messaging.v1.sqlite3"
    closed_row: tuple[str, int, str, int, str] = await asyncio.to_thread(
        _read_closed_application_row,
        database_path=database_path,
        temporary_root=tmp_path,
    )
    message_id, retained, stored_state, boundary_index, stored_run_id = closed_row
    assert retained == 0
    assert stored_state == "applied"
    assert boundary_index == 0

    events: list[SessionHistoryEventDAO] = await history.load_events(session_id=session_id)
    history_kinds: list[str] = [event.kind for event in events]
    assert history_kinds.count("run_started") == 1
    assert history_kinds.count("run_failed") == 1
    openings: list[SessionHistoryEventDAO] = [event for event in events if event.kind == "run_started"]
    failures: list[SessionHistoryEventDAO] = [event for event in events if event.kind == "run_failed"]
    assert len(openings) == 1
    assert len(failures) == 1
    opening: SessionHistoryEventDAO = openings[0]
    failure: SessionHistoryEventDAO = failures[0]
    # The attempt ``turn_id`` is not the logical message run id asserted below.
    assert opening.turn_id is not None
    assert failure.turn_id == opening.turn_id
    assert opening.session_id == session_id
    assert failure.session_id == session_id
    assert opening.sequence < failure.sequence
    assert history_kinds.count("run_completed") == 0
    assert history_kinds.count("run_aborted") == 0
    assert not any(
        kind in history_kinds
        for kind in (
            "run_recovering",
            "recovery_observation",
            "run_retrying",
            "stream_reconnecting",
            "compaction_started",
            "compaction_completed",
            "compaction_retrying",
        )
    )
    applications: list[SessionHistoryEventDAO] = [
        event
        for event in events
        if event.kind == "workflow_update" and "messaging_v1" in event.payload.metadata
    ]
    assert len(applications) == 1
    application: SessionHistoryEventDAO = applications[0]
    metadata: MessageApplicationMetadataDAO = MessageApplicationMetadataDAO.model_validate(
        application.payload.metadata["messaging_v1"]
    )
    assert metadata.message_id == message_id
    assert metadata.sequence == 1
    assert metadata.run_id == stored_run_id
    assert application.turn_id == stored_run_id

    target: MessageAddressDAO | None = session._messaging_target
    assert target is not None
    store: MessageStore = await MessageStore.open(
        path=database_path, limits=session.messaging_limits, target=target
    )
    try:
        identities: tuple[MessageIdentityDAO, ...] = await store.read_identities()
        assert len(identities) == 1
        identity: MessageIdentityDAO = identities[0]
        assert identity.kind == "agent_input"
        assert identity.receipt.state == "applied"
        assert identity.receipt.message_id == message_id
        assert identity.receipt.run_id == stored_run_id
        assert identity.history_event_id == application.event_id
        assert identity.event_sha256 is not None
        journaled: SessionHistoryEventDAO = await store.load_application_event(message_id=message_id)
        assert journaled.event_id == identity.history_event_id
        assert journaled.turn_id == stored_run_id
        assert journaled.payload.metadata["messaging_v1"] == application.payload.metadata["messaging_v1"]
    finally:
        await store.close()
