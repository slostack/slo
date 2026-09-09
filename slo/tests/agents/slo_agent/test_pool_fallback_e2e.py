"""End-to-end pool-fallback + history-aware retry regression suite (spec 37.a.6).

These tests drive the real ``SloAgent`` -> ``SloAgentSession`` seams with a
``ModelPool`` assembled from custom test chat models, covering the overview's
acceptance criteria across the composed (not per-file) behaviour:

- AC1: a 429 on the primary succeeds through the secondary.
- AC2: token deltas reach the consumer through a pooled member (no downgrade).
- AC3: a transient 5xx switches; a malformed (OTHER) error propagates.
- AC4: all members cooling -> terminal ``run_failed`` naming the members.
- AC7: ``route_switched`` / routed-model identity persisted; ``run_retrying``
  persisted; single-model sessions persist no ``route_switched``.

Audit kinds are diagnostic-only and must never project into model context.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from src.agents.providers.credit_exhaustion_policy import AllModelsExhaustedError
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import (
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import ProviderName

# ---------------------------------------------------------------------------
# Test chat models
# ---------------------------------------------------------------------------


class _StatusError(Exception):
    """Provider exception carrying an HTTP ``status_code`` for classification."""

    def __init__(self, *, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.code: Optional[str] = None


class _StreamingModel(BaseChatModel):
    """Streams scripted text chunks, then completes with the joined content."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, chunks: list[str], **data: Any) -> None:
        super().__init__(**data)
        self._chunks = chunks

    @property
    def _llm_type(self) -> str:
        return "streaming-e2e"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="".join(self._chunks)))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="".join(self._chunks)))])

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        for text in self._chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_StreamingModel":
        return self


class _RaiseStreamModel(BaseChatModel):
    """Raises ``error`` before any output on every generate/stream path."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, error: Exception, **data: Any) -> None:
        super().__init__(**data)
        self._error = error
        self._calls = 0

    @property
    def _llm_type(self) -> str:
        return "raise-stream-e2e"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise self._error

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise self._error

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        self._calls += 1
        raise self._error
        yield  # pragma: no cover — marks this coroutine an async generator

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RaiseStreamModel":
        return self


class _RaiseThenStreamModel(BaseChatModel):
    """Raises ``error`` on the first stream, then streams ``content`` thereafter."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, error: Exception, content: str = "done", **data: Any) -> None:
        super().__init__(**data)
        self._error = error
        self._content = content
        self._calls = 0

    @property
    def _llm_type(self) -> str:
        return "raise-then-stream-e2e"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls += 1
        if self._calls == 1:
            raise self._error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._content))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls += 1
        if self._calls == 1:
            raise self._error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._content))])

    async def _astream(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> AsyncIterator[ChatGenerationChunk]:
        self._calls += 1
        if self._calls == 1:
            raise self._error
        yield ChatGenerationChunk(message=AIMessageChunk(content=self._content))

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RaiseThenStreamModel":
        return self


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _pool(*, primary: BaseChatModel, secondary: BaseChatModel) -> ModelPool:
    """Build a two-member pool (gpt-5.4 primary OpenAI, claude-sonnet-4-6 Anthropic)."""
    dao = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={"gpt-5.4": primary, "claude-sonnet-4-6": secondary},
    )


def _pooled_session(*, pool: ModelPool, tmp_path: Path) -> SloAgentSession:
    """Wrap a pre-built pool agent in a history-enabled session."""
    agent = SloAgent(llm=pool, cwd=str(tmp_path), tools=[])
    return SloAgentSession(
        agent=agent,
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path),
        enable_history=True,
    )


def _single_model_session(
    *,
    model: BaseChatModel,
    tmp_path: Path,
    model_name: str = "gpt-5.6-terra",
) -> SloAgentSession:
    """Wrap a pre-built single-model agent in a history-enabled session.

    Args:
        model (BaseChatModel): The scripted provider model for the session.
        tmp_path (Path): Isolated history-store root and session workdir.
        model_name (str, optional): Configured active model identity. Defaults to
            "gpt-5.6-terra".

    Returns:
        SloAgentSession: A persisted single-model session with a known provider.
    """
    agent = SloAgent(llm=model, cwd=str(tmp_path), tools=[])
    config: SessionConfigDAO = SessionConfigDAO(
        workdir=tmp_path,
        model_name=model_name,
        enable_history=True,
    )
    return SloAgentSession(
        agent=agent,
        config=config,
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path),
        enable_history=True,
    )


async def _collect(session: SloAgentSession, *, text: str) -> list:
    """Drain ``invoke`` into a list of events (sleeps patched out)."""
    with patch("src.agents.slo_agent.agent.asyncio.sleep", new=AsyncMock()):
        return [event async for event in session.invoke(text=text)]


async def _collect_response(*, session: SloAgentSession, text: str) -> str:
    """Drain ``invoke`` and return the final assistant text.

    Args:
        session (SloAgentSession): Session under test.
        text (str): Prompt text.

    Returns:
        str: Final response text.
    """
    events: list = await _collect(session, text=text)
    completed = [event for event in events if event.kind == "run_completed"]
    return completed[-1].content or ""


def _store(session: SloAgentSession) -> FilesystemSessionHistoryStore:
    """Return the session's history store, asserting it is enabled (test sessions)."""
    store = session.history_store
    assert store is not None
    return store


# ---------------------------------------------------------------------------
# AC1–AC4: pool fallback behaviour through the real seams
# ---------------------------------------------------------------------------


class TestPoolFallbackEndToEnd:
    @pytest.mark.asyncio
    async def test_primary_429_succeeds_through_secondary(self, tmp_path: Path) -> None:
        """AC1: a 429 on the primary yields one clean answer from the secondary."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=429)),
            secondary=_StreamingModel(chunks=["ok"]),
        )
        result: str = await _collect_response(
            session=_pooled_session(pool=pool, tmp_path=tmp_path),
            text="go",
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_streaming_preserved_through_pooled_member(self, tmp_path: Path) -> None:
        """AC2: token deltas reach the consumer through a pooled member."""
        pool = _pool(
            primary=_StreamingModel(chunks=["o", "k"]),
            secondary=FauxChatModel(responses=[AIMessage(content="unused")]),
        )
        events = await _collect(_pooled_session(pool=pool, tmp_path=tmp_path), text="go")
        deltas = [e for e in events if e.kind == "text_delta"]
        assert deltas  # streaming not downgraded to a single thread-wrapped call

    @pytest.mark.asyncio
    async def test_transient_failure_switches(self, tmp_path: Path) -> None:
        """AC3a: a 503 transient failure switches to the secondary."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=503)),
            secondary=_StreamingModel(chunks=["recovered"]),
        )
        result: str = await _collect_response(
            session=_pooled_session(pool=pool, tmp_path=tmp_path),
            text="go",
        )
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_openai_overload_message_switches_pool_before_output(self, tmp_path: Path) -> None:
        """The status-less OpenAI overload message cools and switches the primary lane."""
        pool: ModelPool = _pool(
            primary=_RaiseStreamModel(
                error=RuntimeError("APIError: Our servers are currently overloaded. Please try again later.")
            ),
            secondary=_StreamingModel(chunks=["recovered"]),
        )

        result: str = await _collect_response(
            session=_pooled_session(pool=pool, tmp_path=tmp_path),
            text="go",
        )

        assert result == "recovered"
        assert "gpt-5.4" in pool._cooldowns

    @pytest.mark.asyncio
    async def test_malformed_error_propagates_without_switch(self, tmp_path: Path) -> None:
        """AC3b: a 400 (OTHER) propagates as run_failed without switching."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=400)),
            secondary=_StreamingModel(chunks=["never"]),
        )
        session = _pooled_session(pool=pool, tmp_path=tmp_path)
        events: list = []
        with pytest.raises(_StatusError):
            async for event in session.invoke(text="go"):
                events.append(event)
        assert any(e.kind == "run_failed" for e in events)
        stored = await _store(session).load_events(session_id=session.session_id)
        assert not any(e.kind == "route_switched" for e in stored)

    @pytest.mark.asyncio
    async def test_all_models_exhausted_surfaces_named_failure(self, tmp_path: Path) -> None:
        """AC4: every member cooling → terminal run_failed naming the members."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=429)),
            secondary=_RaiseStreamModel(error=_StatusError(status_code=429)),
        )
        session = _pooled_session(pool=pool, tmp_path=tmp_path)
        events: list = []
        with pytest.raises(AllModelsExhaustedError):
            with patch("src.agents.slo_agent.agent.asyncio.sleep", new=AsyncMock()):
                async for event in session.invoke(text="go"):
                    events.append(event)
        failed = [e for e in events if e.kind == "run_failed"][-1]
        assert "cooldown" in (failed.content or "").lower()


# ---------------------------------------------------------------------------
# AC7 + observability: persisted identity / audit
# ---------------------------------------------------------------------------


class TestPoolObservabilityPersistence:
    @pytest.mark.asyncio
    async def test_persists_one_route_switched_event_per_switch(self, tmp_path: Path) -> None:
        """One route_switched event is persisted per pool switch, with from/to/kind."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=429)),
            secondary=_StreamingModel(chunks=["ok"]),
        )
        session = _pooled_session(pool=pool, tmp_path=tmp_path)
        await _collect_response(session=session, text="go")
        events = await _store(session).load_events(session_id=session.session_id)
        switches = [e for e in events if e.kind == "route_switched"]
        assert len(switches) == 1
        assert switches[0].payload.metadata["from_model"] == "gpt-5.4"
        assert switches[0].payload.model_name == "claude-sonnet-4-6"
        assert switches[0].payload.metadata["kind"] == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_routed_model_persisted_on_run_and_metadata(self, tmp_path: Path) -> None:
        """AC7: session.json model_name follows the route after a switch."""
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=429)),
            secondary=_StreamingModel(chunks=["ok"]),
        )
        session = _pooled_session(pool=pool, tmp_path=tmp_path)
        await _collect_response(session=session, text="go")
        meta = await _store(session).read_metadata(session_id=session.session_id)
        assert meta.model_name == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_routed_model_persisted_on_failure_path(self, tmp_path: Path) -> None:
        """A turn that route-switches and then fails still persists the routed model."""
        # primary 429 → switch to secondary; secondary 400 (OTHER) → propagate → run_failed.
        pool = _pool(
            primary=_RaiseStreamModel(error=_StatusError(status_code=429)),
            secondary=_RaiseStreamModel(error=_StatusError(status_code=400)),
        )
        session = _pooled_session(pool=pool, tmp_path=tmp_path)
        with pytest.raises(_StatusError):
            with patch("src.agents.slo_agent.agent.asyncio.sleep", new=AsyncMock()):
                async for _ in session.invoke(text="go"):
                    pass
        meta = await _store(session).read_metadata(session_id=session.session_id)
        assert meta.model_name == "claude-sonnet-4-6"  # routed to secondary before failing

    @pytest.mark.asyncio
    async def test_single_model_session_persists_no_route_switched(self, tmp_path: Path) -> None:
        """A single-model session persists no route_switched events."""
        session = _single_model_session(
            model=FauxChatModel(responses=[AIMessage(content="hi")]), tmp_path=tmp_path
        )
        await _collect_response(session=session, text="go")
        events = await _store(session).load_events(session_id=session.session_id)
        assert not any(e.kind == "route_switched" for e in events)

    @pytest.mark.asyncio
    async def test_persists_run_retrying_when_wait_occurs(self, tmp_path: Path) -> None:
        """A wait-and-retry persists a run_retrying history event."""
        session = _single_model_session(
            model=_RaiseThenStreamModel(error=_StatusError(status_code=429), content="done"),
            tmp_path=tmp_path,
        )
        events = await _collect(session, text="go")
        assert any(e.kind == "run_completed" for e in events)
        stored = await _store(session).load_events(session_id=session.session_id)
        assert any(e.kind == "run_retrying" for e in stored)

    @pytest.mark.asyncio
    async def test_openai_overload_retries_without_recovery_observation(self, tmp_path: Path) -> None:
        """The status-less OpenAI overload error retries mechanically before recovery."""
        model: _RaiseThenStreamModel = _RaiseThenStreamModel(
            error=RuntimeError("APIError: Our servers are currently overloaded. Please try again later."),
            content="done",
        )
        session: SloAgentSession = _single_model_session(model=model, tmp_path=tmp_path)

        events: list = await _collect(session, text="go")
        stored: list[SessionHistoryEventDAO] = await _store(session).load_events(
            session_id=session.session_id
        )

        assert model._calls == 2
        assert any(event.kind == "run_retrying" for event in events)
        assert any(event.kind == "run_retrying" for event in stored)
        assert not any(event.kind == "recovery_started" for event in events)
        assert not any(event.kind in {"run_recovering", "recovery_observation"} for event in stored)

    @pytest.mark.asyncio
    async def test_openai_overload_stops_after_configured_retry_budget(self, tmp_path: Path) -> None:
        """The configured two retries yield three provider attempts, then one terminal failure."""
        model: _RaiseStreamModel = _RaiseStreamModel(
            error=RuntimeError("APIError: Our servers are currently overloaded. Please try again later.")
        )
        session: SloAgentSession = _single_model_session(model=model, tmp_path=tmp_path)
        events: list = []

        with pytest.raises(RuntimeError, match="currently overloaded"):
            with patch("src.agents.slo_agent.agent.asyncio.sleep", new=AsyncMock()):
                async for event in session.invoke(text="go"):
                    events.append(event)

        stored: list[SessionHistoryEventDAO] = await _store(session).load_events(
            session_id=session.session_id
        )
        retry_events: list[AgentStreamEventDAO] = [event for event in events if event.kind == "run_retrying"]

        assert model._calls == 3
        assert len(retry_events) == 2
        assert any(event.kind == "run_failed" for event in events)
        assert any(event.kind == "run_failed" for event in stored)
        assert not any(event.kind in {"run_recovering", "recovery_observation"} for event in stored)

    @pytest.mark.asyncio
    async def test_single_model_session_unchanged(self, tmp_path: Path) -> None:
        """Regression guard: no model_pool_dao ⇒ ordinary single-model completion."""
        session = _single_model_session(
            model=FauxChatModel(responses=[AIMessage(content="plain answer")]), tmp_path=tmp_path
        )
        result: str = await _collect_response(session=session, text="go")
        assert result == "plain answer"


# ---------------------------------------------------------------------------
# Projector excludes audit kinds (AC: never inflate model context)
# ---------------------------------------------------------------------------


def _event(*, kind: str, payload: SessionHistoryEventPayloadDAO) -> SessionHistoryEventDAO:
    """Build one canonical event in completed turn ``t1``."""
    return SessionHistoryEventDAO(
        session_id="s1",
        turn_id="t1",
        kind=kind,  # type: ignore[arg-type]
        payload=payload,
    )


def _completed_turn_with(*, audit_kind: str) -> list[SessionHistoryEventDAO]:
    """Build a completed turn carrying a user message and one audit event."""
    return [
        _event(kind="user_message", payload=SessionHistoryEventPayloadDAO(content="hi")),
        _event(
            kind=audit_kind,
            payload=SessionHistoryEventPayloadDAO(model_name="claude-sonnet-4-6", message="x"),
        ),
        _event(kind="run_completed", payload=SessionHistoryEventPayloadDAO(content="done")),
    ]


class TestProjectorExcludesAuditKinds:
    async def test_route_switched_not_projected(self) -> None:
        """A route_switched event is excluded while the user message still projects."""
        from langchain_core.messages import HumanMessage

        msgs = await SessionHistoryProjector.build_message_history(
            events=_completed_turn_with(audit_kind="route_switched")
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)

    @pytest.mark.asyncio
    async def test_run_retrying_not_projected(self) -> None:
        """A run_retrying event is excluded while the user message still projects."""
        from langchain_core.messages import HumanMessage

        msgs = await SessionHistoryProjector.build_message_history(
            events=_completed_turn_with(audit_kind="run_retrying")
        )
        assert len(msgs) == 1
        assert isinstance(msgs[0], HumanMessage)
