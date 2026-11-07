"""Controlled retry/rebuild identity through real local admission and graph execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from src.agents.tools.echo import echo_tool
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.delivery import AgentMessageSource
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import BoundaryDAO, BoundaryDeliveryDAO, MessageSubmissionDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.tool_execution.yield_policy import ToolExecutionControl, ToolYieldPolicy
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.integration.test_messaging_yield import isolated_journey_tasks
from tests.tui.test_durable_composer import _wait_until


def retained_graph_identity(*, session: SloAgentSession) -> tuple[object, ...]:
    """Observe retained construction handles without replacing any internal collaborator."""
    agent = session.agent
    return (
        agent._llm,
        agent._message_source,
        agent._tool_execution_control,
        agent._tool_yield_policy,
        agent._tool_execution_mode,
        tuple(agent._tools),
        agent._output_update_queue,
        session.sub_agent_pool,
    )


def require_same_graph_identity(*, original: tuple[object, ...], current: tuple[object, ...]) -> None:
    """Require exact retained handles, including every original concrete tool object."""
    assert all(left is right for index, (left, right) in enumerate(zip(original, current)) if index != 5)
    assert isinstance(original[5], tuple) and isinstance(current[5], tuple)
    assert len(original[5]) == len(current[5])
    assert all(left is right for left, right in zip(original[5], current[5]))


class RetryHeldProvider(RecordingModel):
    """Fail an uncommitted request, hold its retry, then complete after urgent cancellation."""

    retry_entered: asyncio.Event = Field(default_factory=asyncio.Event, description="Retry request held.")
    retry_joined: asyncio.Event = Field(default_factory=asyncio.Event, description="Retry reader joined.")
    binds: int = Field(default=0, description="Actual external model tool binds.")

    def __init__(self, *, responses: Sequence[AIMessage]) -> None:
        """Retain the explicit external provider construction contract."""
        super().__init__(responses=responses)

    def bind_tools(
        self, tools: Sequence[object], *, tool_choice: Optional[str] = None, **kwargs: object
    ) -> RecordingModel:
        """Count initial graph bindings; run-control recompilation must not bind again."""
        self.binds += 1
        return super().bind_tools(tools=tools, tool_choice=tool_choice, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Record each real request with deterministic gates around both failure and retry."""
        self.requests.append(list(messages))
        if len(self.requests) == 1:
            self.entered.set()
            await self.release.wait()
            raise httpx.RemoteProtocolError("controlled unsent disconnect")
        if len(self.requests) == 2:
            self.retry_entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.retry_joined.set()
        assert self.retry_joined.is_set()
        async for chunk in FauxChatModel._astream(
            self, messages=messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk


class BindingAgent(SloAgent):
    """Record the real public binding seam without replacing graph or delivery behavior."""

    def __init__(
        self, *, model: RecordingModel, workdir: Path, source: SloAgentSession | None = None
    ) -> None:
        """Build exactly one real graph over the external provider double."""
        super().__init__(
            llm=model, tools=[echo_tool], cwd=str(workdir), system_prompt="Test", message_source=source
        )
        self.bindings: list[tuple[ToolExecutionControl, ToolYieldPolicy | None]] = []

    def bind_tool_execution(
        self,
        *,
        tool_execution_control: ToolExecutionControl,
        tool_yield_policy: ToolYieldPolicy | None = None,
    ) -> None:
        """Record only successful bindings; repeated identical readiness binds remain legal."""
        super().bind_tool_execution(
            tool_execution_control=tool_execution_control, tool_yield_policy=tool_yield_policy
        )
        self.bindings.append((tool_execution_control, tool_yield_policy))


class SelectionSession(SloAgentSession):
    """Record exact public source selections, not private cursor inspection or mutation."""

    selections: list[BoundaryDeliveryDAO]

    async def take_one(self, *, boundary: BoundaryDAO) -> BoundaryDeliveryDAO:
        """Retain each actual cached delivery returned by the session source."""
        delivery = await super().take_one(boundary=boundary)
        self.selections.append(delivery)
        return delivery


@pytest.mark.parametrize(argnames="prebuilt", argvalues=[False, True])
@pytest.mark.parametrize(argnames="rebuild", argvalues=[False, True])
async def test_new_urgent_during_retry_reuses_run_binding_and_delivery(
    tmp_path: Path, prebuilt: bool, rebuild: bool, isolated_journey_tasks: None
) -> None:
    """A joined reconnect preserves control/policy/source and slot identity before new urgency."""
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model = RetryHeldProvider(responses=[AIMessage(content="handled")])
    agents: list[BindingAgent] = []

    def factory(*, message_source: AgentMessageSource) -> SloAgent:
        """Keep the existing one-keyword factory contract and real agent construction."""
        assert isinstance(message_source, SloAgentSession)
        agent = BindingAgent(model=model, workdir=tmp_path, source=message_source)
        agents.append(agent)
        return agent

    injected = BindingAgent(model=model, workdir=tmp_path) if prebuilt else None
    if injected is not None:
        agents.append(injected)
    session = SelectionSession(
        agent=injected,
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=factory,
    )
    session.selections = []
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        original = MessageSubmissionDAO(
            message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
        )
        await client.submit(submission=original)
        await _wait_until(predicate=model.entered.is_set)
        first = session.selections[0]
        first_binding = agents[0].bindings[0]
        if rebuild:
            session.switch_reasoning_level(reasoning_level="low")
        model.release.set()
        await _wait_until(predicate=model.retry_entered.is_set)
        assert session.selections[-1] is first
        assert agents[-1].bindings[-1][0] is first_binding[0]
        assert agents[-1].bindings[-1][1] is first_binding[1]
        first_binding[0].require_source(source=session)
        assert [(m.type, m.content) for m in model.requests[0]] == [
            (m.type, m.content) for m in model.requests[1]
        ]
        assert [m.id for m in model.requests[0] if m.type == "human"] == [
            m.id for m in model.requests[1] if m.type == "human"
        ]
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="urgent",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        await _wait_until(predicate=lambda: len(model.requests) == 3 and not session.is_running)
        assert model.retry_joined.is_set()
        assert len(agents) == (2 if rebuild else 1)
        assert model.binds == len(agents)
        assert all(
            binding[0] is first_binding[0] and binding[1] is first_binding[1]
            for agent in agents
            for binding in agent.bindings
        )
        assert session.selections[-1].boundary.run_id == first.boundary.run_id
        assert session.selections[-1].boundary.boundary_index == first.boundary.boundary_index + 1
        assert session.selections[-1].instruction is not None
        assert session.selections[-1].instruction.envelope.submission.message_id == urgent.message_id
    finally:
        model.release.set()
        session.abort()
        if client is not None:
            await client.close()
        await session.close_messaging()


async def test_production_lazy_retry_then_urgent_preserves_single_model_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_journey_tasks: None
) -> None:
    """Production lazy construction reaches controlled retry/yield without rebuilding a model."""
    from src.agents.base import LLMFactory, LLMBuildResult
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_store import CredentialStore

    model = RetryHeldProvider(responses=[AIMessage(content="handled")])
    builds: list[dict[str, object]] = []

    def external_model(**kwargs: object) -> LLMBuildResult:
        """Substitute only external provider acquisition."""
        builds.append(kwargs)
        return LLMBuildResult(llm=model, supports_explicit_caching=False)

    monkeypatch.setattr(target=LLMFactory, name="create", value=external_model)
    auth_path = tmp_path / "authentication.json"
    assert auth_path.resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setenv(name="SLO_AUTH_FILE", value=str(auth_path))
    credentials = CredentialStore()
    assert credentials.path.resolve().is_relative_to(tmp_path.resolve())
    credentials.persist(
        cred=CredentialDAO(
            provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic-boundary-only"
        )
    )
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=str(uuid4()), model_name="gpt-5.4"
        )
    )
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool
    from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    async def relay(event: AgentStreamEventDAO) -> None:
        """No children are launched in this retained-construction proof."""

    child_pool = SubAgentPool(
        orchestrator_session_id=session.session_id,
        default_model=None,
        relay=relay,
        owner_session_id=session.session_id,
        run_id=str(uuid4()),
        history_root=root,
    )
    spawn = SpawnSubAgentsTool.build(pool=child_pool)
    session.attach_sub_agent_pool(pool=child_pool, spawn_tool=spawn)
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
            )
        )
        await _wait_until(predicate=model.entered.is_set)
        identity = retained_graph_identity(session=session)
        assert identity[1] is session and identity[2] is not None and identity[3] is not None
        assert any(tool is spawn for tool in session.agent._tools)
        assert session.sub_agent_pool is child_pool
        model.release.set()
        await _wait_until(predicate=model.retry_entered.is_set)
        require_same_graph_identity(original=identity, current=retained_graph_identity(session=session))
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()),
                target=session.messaging_target,
                kind="agent_input",
                text="urgent",
                priority="urgent",
            )
        )
        await _wait_until(predicate=lambda: len(model.requests) == 3 and not session.is_running)
        assert model.retry_joined.is_set() and len(builds) == 1 and model.binds == 1
        released = retained_graph_identity(session=session)
        assert released[2] is None  # joined run release, not a replacement active control
        require_same_graph_identity(original=identity[:2] + (None,) + identity[3:], current=released)
        assert session.sub_agent_pool is child_pool
        assert session.orchestration_tools == [spawn]
        assert not child_pool.registry.snapshot()
        assert [(message.type, message.content) for message in model.requests[0]] == [
            (message.type, message.content) for message in model.requests[1]
        ]
        events = await FilesystemSessionHistoryStore(root=root).load_events(session_id=session.session_id)
        assert [event.payload.content for event in events if "messaging_v1" in event.payload.metadata] == [
            "original",
            "urgent",
        ]
        assert sum(event.kind == "run_completed" for event in events) == 1
    finally:
        model.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
            await child_pool.abort_and_drain()


@pytest.mark.parametrize(argnames="slots", argvalues=["empty", "note", "both"])
async def test_active_cached_slot_selection_is_frozen_during_retry(
    tmp_path: Path, slots: str, isolated_journey_tasks: None
) -> None:
    """Empty/note/both at a later active boundary cannot claim newer urgent input on retry."""
    from langchain_core.tools import tool

    tool_entered, tool_release = asyncio.Event(), asyncio.Event()

    @tool
    async def checkpoint() -> str:
        """Hold the first boundary until the intended next slots are admitted."""
        tool_entered.set()
        await tool_release.wait()
        return "checkpoint"

    class LaterRetryProvider(RetryHeldProvider):
        fail_release: asyncio.Event = Field(default_factory=asyncio.Event)
        failed_entered: asyncio.Event = Field(default_factory=asyncio.Event)

        def __init__(self, *, responses: Sequence[AIMessage]) -> None:
            """Retain explicit external script construction."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Fail only the second boundary; hold its retry for newer admission."""
            self.requests.append(list(messages))
            if len(self.requests) == 2:
                self.failed_entered.set()
                await self.fail_release.wait()
                raise httpx.HTTPStatusError(
                    "Rate limit reached; retry in 1s",
                    request=httpx.Request(method="POST", url="https://provider.invalid"),
                    response=httpx.Response(status_code=429, headers={"retry-after": "0"}),
                )
            if len(self.requests) == 3:
                self.retry_entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.retry_joined.set()
            async for chunk in FauxChatModel._astream(
                self, messages=messages, stop=stop, run_manager=run_manager, **kwargs
            ):
                yield chunk

    model = LaterRetryProvider(
        responses=[
            AIMessage(
                content="checkpoint", tool_calls=[{"id": "checkpoint", "name": "checkpoint", "args": {}}]
            ),
            AIMessage(content="done"),
        ]
    )
    agents: list[SloAgent] = []

    def factory(*, message_source: AgentMessageSource) -> SloAgent:
        """Use the real source/agent/graph with a deterministic continuation gate."""
        agent = SloAgent(
            llm=model,
            tools=[checkpoint],
            cwd=str(tmp_path),
            message_source=message_source,
            should_stop_after_turn_hook=lambda _: False,
        )
        agents.append(agent)
        return agent

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session = SelectionSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=factory,
    )
    session.selections = []
    client = None
    try:
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
            )
        )
        await _wait_until(predicate=tool_entered.is_set)
        if slots in {"note", "both"}:
            await client.submit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()), target=session.messaging_target, kind="context_note", text="note"
                )
            )
        if slots == "both":
            await client.submit(
                submission=MessageSubmissionDAO(
                    message_id=str(uuid4()),
                    target=session.messaging_target,
                    kind="agent_input",
                    text="instruction",
                )
            )
        tool_release.set()
        await _wait_until(predicate=model.failed_entered.is_set)
        selected = session.selections[-1]
        assert (selected.note is not None) == (slots != "empty")
        assert (selected.instruction is not None) == (slots == "both")
        model.fail_release.set()
        await _wait_until(predicate=model.retry_entered.is_set)
        assert session.selections[-1] is selected
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="newer urgent",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        await _wait_until(predicate=lambda: len(model.requests) >= 4)
        assert [(m.type, m.content) for m in model.requests[1]] == [
            (m.type, m.content) for m in model.requests[2]
        ]
        assert selected.urgent_high_water == 0
        assert session.selections[-1].boundary.boundary_index == selected.boundary.boundary_index + 1
        assert len(agents) == 1 and model.binds == 1
        session.abort()
    finally:
        tool_release.set()
        model.fail_release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()


async def test_real_pool_exhaustion_retries_low_budget_without_new_claim_or_binding(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """Ordinary switch/exhaustion stays finite and preserves controlled run ownership."""
    from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
    from src.auth.credential_dao import ProviderName
    from src.agents.model_catalog.service import ModelCatalogService
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from tests.integration.test_session_messaging import read_closed_message_rows

    class UnavailableProvider(RecordingModel):
        def __init__(self, *, responses: Sequence[AIMessage]) -> None:
            """Keep provider scripts explicit."""
            super().__init__(responses=responses)

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: Optional[list[str]] = None,
            run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            """Return a switchable external error, never synthetic completion."""
            self.requests.append(list(messages))
            self.entered.set()
            await self.release.wait()
            raise httpx.RemoteProtocolError("retry in 1s")
            if False:
                yield ChatGenerationChunk(message=AIMessage(content="unreachable"))

    snapshot = ModelCatalogService.load()
    entries = dict(snapshot.entries)
    for name in ("gpt-5.4",):
        entry = entries[name]
        entries[name] = entry.model_copy(
            update={
                "runtime_profile": entry.runtime_profile.model_copy(
                    update={"automatic_retry_attempts": 1, "local_retry_wait_cap_seconds": 1}
                )
            }
        )
    entries["gpt-5.4-mini"] = entries["gpt-5.4"].model_copy(update={"model_name": "gpt-5.4-mini"})
    snapshot = snapshot.model_copy(update={"entries": entries})
    primary, fallback = UnavailableProvider(responses=[]), UnavailableProvider(responses=[])
    fallback.release.set()
    pool = ModelPool(
        pool_dao=ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI),
                ModelPoolEntryDAO(model_name="gpt-5.4-mini", provider=ProviderName.OPENAI, priority=1),
            ]
        ),
        models={"gpt-5.4": primary, "gpt-5.4-mini": fallback},
        snapshot=snapshot,
    )
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session = SelectionSession(
        agent=SloAgent(llm=pool, tools=[echo_tool], cwd=str(tmp_path), snapshot=snapshot),
        workdir=tmp_path,
        session_id=str(uuid4()),
        catalog_snapshot=snapshot,
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=FilesystemSessionHistoryStore(root=root),
    )
    session.selections = []
    retry = asyncio.Event()
    retry_identities: list[tuple[object, ...]] = []

    async def observe(event: AgentStreamEventDAO) -> None:
        """Admit a later instruction while the existing finite retry is waiting."""
        if event.kind == "run_retrying":
            retry_identities.append(retained_graph_identity(session=session))
            retry.set()

    client = None
    try:
        session.subscribe(handler=observe)
        await session.start_messaging()
        client = LocalSessionMessagingClient(
            session=session, target=session.messaging_target, principal=session.messaging_owner_principal
        )
        await client.submit(
            submission=MessageSubmissionDAO(
                message_id=str(uuid4()), target=session.messaging_target, kind="agent_input", text="original"
            )
        )
        await _wait_until(predicate=primary.entered.is_set)
        identity = retained_graph_identity(session=session)
        assert isinstance(identity[0], ModelPool) and identity[0] is not pool
        assert identity[1] is session and identity[2] is not None and identity[3] is not None
        primary.release.set()
        await _wait_until(predicate=retry.is_set)
        assert retry_identities
        for observed in retry_identities:
            require_same_graph_identity(original=identity, current=observed)
        urgent = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=session.messaging_target,
            kind="agent_input",
            text="retained",
            priority="urgent",
        )
        await client.submit(submission=urgent)
        await _wait_until(predicate=lambda: not session.is_running)
        assert len(primary.requests) == len(fallback.requests) == 1
        assert len(session.selections) == 1
        released = retained_graph_identity(session=session)
        require_same_graph_identity(original=identity[:2] + (None,) + identity[3:], current=released)
        assert released[7] is None and session.orchestration_tools == []
        events = await FilesystemSessionHistoryStore(root=root).load_events(session_id=session.session_id)
        assert sum(event.kind == "run_failed" for event in events) == 1
        assert not any(event.kind == "run_completed" for event in events)
        assert sum("messaging_v1" in event.payload.metadata for event in events) == 1
    finally:
        primary.release.set()
        fallback.release.set()
        session.abort()
        try:
            if client is not None:
                await client.close()
        finally:
            await session.close_messaging()
    rows = read_closed_message_rows(
        database_path=root / session.session_id / "messaging.v1.sqlite3", temporary_root=tmp_path
    )
    assert (urgent.message_id, 1, "accepted") in rows
