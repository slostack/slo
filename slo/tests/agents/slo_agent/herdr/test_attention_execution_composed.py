"""Offline config-backed attention evidence through real graph and local tools."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
from src.agents.slo_agent.herdr.service import HerdrSnapshotProjector
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO
from src.agents.tools.echo import EchoTool, echo_tool
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


def _responses() -> list[AIMessage]:
    """Script one local tool and a final answer, with distinct completed usage."""
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "echo", "args": {"text": "Approval required"}, "id": "one"}],
            usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        ),
        AIMessage(content="done", usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}),
    ]


def _credential() -> CredentialDAO:
    """Keep config-backed admission entirely synthetic."""
    return CredentialDAO(provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic")


@pytest.mark.parametrize(argnames="outcome", argvalues=["complete", "abort", "cancel"])
@pytest.mark.parametrize(argnames="attention", argvalues=["none", "auth", "stale"])
async def test_tool_barrier_terminal_usage_and_busy_refusal(
    tmp_path: Path, outcome: str, attention: str
) -> None:
    """Real accepted work stays working through busy refusal and terminal cleanup."""
    entered, release = asyncio.Event(), asyncio.Event()
    publications: list[HerdrPublicationDAO] = []
    refresh_states: list[str] = []
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=_responses()), supports_explicit_caching=False
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=_credential()),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", extra_tools=[echo_tool])
        )
        session._herdr_reporting_started = True
        original_refresh = session.refresh_usage_snapshot
        old_token = (
            session.set_operator_attention(reason="Authentication required") if attention != "none" else None
        )
        if attention == "stale":
            session.set_operator_attention(reason="Model preparation required")
        current_attention = session._operator_attention

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Record actual immutable projection, not a substitute state machine."""
            publications.append(publication)

        def refresh() -> SessionUsageSnapshotDAO:
            """Delegate accounting while recording ordering before settlement."""
            refresh_states.append(session._reporting_state().state)
            return original_refresh()

        async def echo(*, text: str) -> str:
            """Hold the real executor at its local tool boundary."""
            entered.set()
            await release.wait()
            if attention == "stale":
                assert old_token is not None
                session.clear_operator_attention(token=old_token)
                assert session._operator_attention is current_attention
            return text

        async def consume() -> list[str]:
            """Drain the actual session, preserving existing cancellation translation."""
            return [event.kind async for event in session.invoke(text="echo then finish")]

        with (
            patch.object(EchoTool, "invoke", side_effect=echo),
            patch.object(session._herdr_reporter, "publish", side_effect=publish),
            patch.object(session, "refresh_usage_snapshot", side_effect=refresh),
        ):
            task = asyncio.create_task(coro=consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert session._reporting_state().state == "working"
                with pytest.raises(RuntimeError, match="already processing"):
                    await consume()
                assert session._operation_serial == 1
                if outcome == "abort":
                    session.abort()
                if outcome == "cancel":
                    task.cancel()
                release.set()
                events = await asyncio.wait_for(task, timeout=5)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert events[-1] == ("run_completed" if outcome == "complete" else "run_aborted")
    assert refresh_states and set(refresh_states) == {"working"}
    assert publications and all(item.snapshot.state == "working" for item in publications[:-1])
    assert publications[-1].snapshot.state == ("idle" if attention == "none" else "blocked")
    assert session._operator_attention is current_attention and not session._reporting_operations
    expected_total = 8 if outcome == "complete" else 3
    assert session.usage_snapshot().session_totals.total_tokens == expected_total
    assert {token.key: token.value for token in publications[-1].snapshot.tokens}["session_tokens"] == str(
        expected_total
    )
    assert {token.key: token.value for token in publications[-2].snapshot.tokens}["session_tokens"] == str(
        expected_total
    )


@pytest.mark.parametrize(argnames="fallback", argvalues=[False, True])
async def test_config_pool_route_preserves_working_and_numeric_projection(
    tmp_path: Path, fallback: bool
) -> None:
    """The real factory builds/binds/routes a pool; fallback is display, not policy."""
    pool_config = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name=name, provider=ProviderName.OPENAI, priority=index)
            for index, name in enumerate(("gpt-5.4", "gpt-4.1"))
        ]
    )
    original_stream = FauxChatModel._astream
    original_observer = SloAgentSession._on_herdr_event
    observed_routes: list[str] = []
    forbidden_calls: list[int] = []
    route_transitions: list[tuple[str, str]] = []

    async def observe_without_io(owner: SloAgentSession, event: AgentStreamEventDAO) -> None:
        """Guard only the real observer, leaving legitimate admission I/O outside it."""
        before = owner.usage_snapshot().active_model_name
        with (
            patch.object(Path, "resolve", side_effect=AssertionError("observer path I/O")) as resolve,
            patch.object(
                CredentialResolver, "resolve", side_effect=AssertionError("observer auth I/O")
            ) as auth,
            patch.object(owner, "_build_agent", side_effect=AssertionError("observer model build")) as build,
            patch.object(
                owner, "_sync_usage_snapshot_commit", side_effect=AssertionError("observer accounting")
            ) as commit,
            patch.object(
                owner._history_store, "read_metadata", side_effect=AssertionError("observer metadata I/O")
            ) as metadata,
        ):
            await original_observer(owner, event=event)
        # Retain counts outside both failure-isolated observer and subscriber dispatch.
        forbidden_calls.extend(item.call_count for item in (resolve, auth, build, commit, metadata))
        after = owner.usage_snapshot().active_model_name
        observed_routes.append(after)
        if before != after:
            route_transitions.append((before, after))

    calls: list[str] = []
    publications: list[HerdrPublicationDAO] = []

    async def stream(
        model: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Fail only the primary at the provider boundary; execute all other Faux work."""
        calls.append(model.queue[0].id or "")
        if fallback and model.queue[0].id == "primary":
            raise RuntimeError("429 rate limit")
        async for chunk in original_stream(
            model, messages=messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    def build(*, model_name: str, **kwargs: object) -> LLMBuildResult:
        """Supply scripted member models to the unchanged create_pool implementation."""
        messages = _responses()
        messages[0].id = "primary" if model_name == "gpt-5.4" else "secondary"
        return LLMBuildResult(llm=FauxChatModel(responses=messages), supports_explicit_caching=False)

    with (
        patch("src.agents.slo_agent.graph.LLMFactory.create", side_effect=build),
        patch.object(CredentialResolver, "resolve", return_value=_credential()),
        patch.object(FauxChatModel, "_astream", new=stream),
        patch.object(SloAgentSession, "_on_herdr_event", new=observe_without_io),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_pool_dao=pool_config, extra_tools=[echo_tool])
        )
        session._herdr_reporting_started = True

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Record actual route-aware projections without launching Herdr."""
            publications.append(publication)

        with patch.object(session._herdr_reporter, "publish", side_effect=publish):
            events = [event.kind async for event in session.invoke(text="echo then finish")]
        assert isinstance(session.agent.llm, ModelPool)
        assert session.agent.llm.active_model_name == ("gpt-4.1" if fallback else "gpt-5.4")
    assert forbidden_calls and not any(forbidden_calls)
    assert route_transitions == ([("gpt-5.4", "gpt-4.1")] if fallback else [])
    assert observed_routes and observed_routes[-1] == ("gpt-4.1" if fallback else "gpt-5.4")
    assert calls[0] == "primary" and ("secondary" in calls) == fallback
    assert "tool_result" in events and events[-1] == "run_completed"
    assert session.active_model_name == "gpt-5.4" and session.model_pool_dao == pool_config
    assert session._operation_serial == 1 and not session._reporting_operations
    assert all(item.snapshot.state == "working" for item in publications[:-1])
    assert publications[-1].snapshot.state == "idle" and session._operator_attention is None
    assert session.usage_snapshot().session_totals.total_tokens == 8
    tokens = {token.key: token.value for token in publications[-1].snapshot.tokens}
    assert tokens["session_tokens"] == "8"
    detail = HerdrSnapshotProjector.build(
        session_id=session.session_id,
        state="idle",
        history_enabled=False,
        usage=session.usage_snapshot(),
        metadata_profile="detail",
    )
    detail_tokens = {token.key: token.value for token in detail.tokens}
    assert detail_tokens["turn"] == "5"
    assert detail_tokens["rpm"] == str(session.usage_snapshot().requests_per_minute_limit)
    assert "context" not in detail_tokens
    assert not {"model", "provider", "session", "effort"} & (tokens.keys() | detail_tokens.keys())


@pytest.mark.parametrize(argnames="failure", argvalues=["retry", "recovery", "fatal"])
@pytest.mark.parametrize(argnames="reporter_fault", argvalues=[False, True])
async def test_provider_failure_continuity(tmp_path: Path, failure: str, reporter_fault: bool) -> None:
    """Actual policy retries/recovers before output; reporting cannot alter the result."""
    original_stream = FauxChatModel._astream
    attempts = 0
    error = (
        ValueError("credential refused")
        if failure == "fatal"
        else RuntimeError(
            "429 rate limit retry after 1 seconds" if failure == "retry" else "local recoverable failure"
        )
    )
    publications: list[HerdrPublicationDAO] = []
    observed: list[str] = []
    ordering: list[str] = []

    async def stream(
        model: FauxChatModel,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Inject one pre-output failure, then delegate to the real scripted model."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error
        async for chunk in original_stream(
            model, messages=messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=_responses()), supports_explicit_caching=False
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=_credential()),
        patch.object(FauxChatModel, "_astream", new=stream),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", extra_tools=[echo_tool])
        )
        session._herdr_reporting_started = True

        original_refresh = session.refresh_usage_snapshot
        original_end = session._end_reporting_operation

        def refresh() -> SessionUsageSnapshotDAO:
            """Record the actual final accounting gateway while operation remains active."""
            assert session._reporting_state().state == "working"
            ordering.append("refresh")
            result = original_refresh()
            ordering.append("refreshed")
            return result

        def end(*, token: int) -> None:
            """Retain exact retirement ordering without replacing its implementation."""
            ordering.append("end")
            original_end(token=token)

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Observe before optionally failing the reporter boundary."""
            ordering.append(publication.snapshot.state)
            publications.append(publication)
            if reporter_fault:
                raise RuntimeError("optional reporter fault")

        async def observe(event: AgentStreamEventDAO) -> None:
            """Check continuity on every real event, including retry and recovery."""
            assert session._reporting_state().state == "working"
            assert len(session._reporting_operations) == 1
            observed.append(event.kind)

        session.subscribe(handler=observe)
        with (
            patch.object(session._herdr_reporter, "publish", side_effect=publish),
            patch.object(session, "refresh_usage_snapshot", side_effect=refresh),
            patch.object(session, "_end_reporting_operation", side_effect=end),
        ):
            if failure == "fatal":
                with pytest.raises(ValueError) as caught:
                    _ = [event async for event in session.invoke(text="echo")]
                assert caught.value is error
            else:
                _ = [event async for event in session.invoke(text="echo")]
    assert all(item.snapshot.state == "working" for item in publications[:-1])
    assert session._operation_serial == 1 and not session._reporting_operations
    if failure == "fatal":
        assert attempts == 1 and "tool_result" not in observed
        assert publications[-1].snapshot.block_reason == "Run failed; review Slo"
        assert ordering[-5:] == ["refresh", "working", "refreshed", "end", "blocked"]
        assert ordering.count("end") == 1
        assert publications[-2].snapshot.tokens == publications[-1].snapshot.tokens
        assert session.usage_snapshot().session_totals.total_tokens is None
        assert "session_tokens" not in {token.key for token in publications[-1].snapshot.tokens}
    else:
        assert attempts == 3 and observed[-1] == "run_completed" and "tool_result" in observed
        assert ("run_retrying" if failure == "retry" else "recovery_started") in observed
        assert publications[-1].snapshot.state == "idle" and session._operator_attention is None
        assert session.usage_snapshot().session_totals.total_tokens == 8


@pytest.mark.parametrize(argnames="action", argvalues=["abort", "cancel"])
async def test_retry_wait_interruption_does_not_create_attention(tmp_path: Path, action: str) -> None:
    """Interrupt a genuine pre-output retry wait; passive cooldown is never blocked."""
    entered, release = asyncio.Event(), asyncio.Event()
    publications: list[HerdrPublicationDAO] = []

    async def fail(
        model: FauxChatModel, messages: list[BaseMessage], **kwargs: object
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Fail at the model boundary before output or tool execution."""
        raise RuntimeError("429 rate limit retry after 1 seconds")
        yield  # Async-generator protocol; the failure precedes all output.

    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=_responses()), supports_explicit_caching=False
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=_credential()),
        patch.object(FauxChatModel, "_astream", new=fail),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", extra_tools=[echo_tool])
        )
        session._herdr_reporting_started = True

        async def observe(event: AgentStreamEventDAO) -> None:
            """Pause the retry event after real cooldown accounting, before waiting."""
            if event.kind == "run_retrying":
                entered.set()
                await release.wait()

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Retain each actual report for semantic lifecycle assertions."""
            publications.append(publication)

        async def consume() -> list[str]:
            """Keep original session cancellation translation intact."""
            return [event.kind async for event in session.invoke(text="echo")]

        session.subscribe(handler=observe)
        with patch.object(session._herdr_reporter, "publish", side_effect=publish):
            task = asyncio.create_task(coro=consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert session.usage_snapshot().cooldown_seconds_remaining is not None
                assert session._reporting_state().state == "working"
                assert session._operator_attention is None
                if action == "abort":
                    session.abort()
                else:
                    task.cancel()
                release.set()
                events = await asyncio.wait_for(task, timeout=5)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            session.refresh_usage_snapshot()
    assert "tool_result" not in events and events[-1] == "run_aborted"
    assert session._operator_attention is None and not session._reporting_operations
    assert session._operation_serial == 1 and publications[-1].snapshot.state == "idle"
    assert not any(item.snapshot.state == "blocked" for item in publications)
