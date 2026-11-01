"""Session semantic operation/attention tokens, independent of execution authority."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.agents.slo_agent.sessions.dao import SessionConfigDAO, OperatorAttentionReason
from src.agents.slo_agent.sessions.service import SloAgentSession


def test_attention_tokens_and_operation_precedence(tmp_path: Path) -> None:
    """Only matching completions clear attention; unrelated live work still wins."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    assert session._reporting_state().state == "idle"
    first = session.set_operator_attention(reason="Authentication required")
    newer = session.set_operator_attention(reason="Model preparation required")
    session.clear_operator_attention(token=first)
    assert session._reporting_state().block_reason == "Model preparation required"
    work = session._begin_reporting_operation()
    assert session._reporting_state().state == "working"
    session._suspend_reporting_operation(token=work)
    assert session._reporting_state().state == "blocked"
    other = session._begin_reporting_operation()
    session._end_reporting_operation(token=work)
    session._end_reporting_operation(token=work)
    assert session._reporting_state().state == "working"
    session._end_reporting_operation(token=other)
    assert session._reporting_state().state == "blocked"
    session.clear_operator_attention(token=newer)
    assert session._reporting_state().state == "idle"
    session.clear_operator_attention(token=newer)
    session._suspend_reporting_operation(token=work)
    assert not session._reporting_operations
    assert not session.is_running


def test_attention_publication_and_closing(tmp_path: Path) -> None:
    """Actual public projection carries fixed state/reason; close suppresses publication."""
    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._herdr_reporting_started = True
    with patch.object(session._herdr_reporter, "publish") as publish:
        token = session.set_operator_attention(reason="Authentication required")
        snapshot = publish.call_args.kwargs["publication"].snapshot
        assert snapshot.state == "blocked" and snapshot.block_reason == "Authentication required"
        work = session._begin_reporting_operation()
        snapshot = publish.call_args.kwargs["publication"].snapshot
        assert snapshot.state == "working" and snapshot.block_reason is None
        session.clear_operator_attention(token=token)
        session._suspend_reporting_operation(token=work)
        assert session._reporting_state().state == "working"
        session.begin_external_reporting_close()
        publish.reset_mock()
        session._end_reporting_operation(token=work)
        publish.assert_not_called()
    invalid: OperatorAttentionReason = "Authentication required"
    with patch(
        "src.agents.slo_agent.sessions.service.OperatorAttentionDAO",
        side_effect=ValidationError.from_exception_data("attention", []),
    ):
        with pytest.raises(ValidationError):
            session.set_operator_attention(reason=invalid)
    assert session._operator_attention is None


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_actual_run_scope_brackets_preparation_and_final_usage(tmp_path: Path, outcome: str) -> None:
    """The real lock scope owns one token across preparation and final usage refresh."""
    import asyncio

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session.set_operator_attention(reason="Run failed; review Slo")
    seen: list[str] = []

    async def prepare() -> None:
        """Observe admission before any preparation work."""
        assert session.is_running
        assert session._reporting_state().state == "working"
        assert session._operator_attention is None
        seen.append("prepare")

    def refresh() -> None:
        """Observe final metadata while the operation still owns working state."""
        assert session._reporting_state().state == "working"
        seen.append("usage")

    error = RuntimeError("original") if outcome == "error" else asyncio.CancelledError()
    with (
        patch.object(session, "_prepare_run_snapshot", side_effect=prepare),
        patch.object(session, "refresh_usage_snapshot", side_effect=refresh),
    ):
        try:
            async with session._session_run_scope():
                seen.append("body")
                if outcome != "success":
                    raise error
        except (RuntimeError, asyncio.CancelledError) as caught:
            assert outcome != "success" and caught is error
    assert seen == ["prepare", "body", "usage"]
    assert not session.is_running and not session._reporting_operations
    assert session._reporting_state().state == ("blocked" if outcome == "error" else "idle")


async def test_manual_compaction_keeps_working_through_final_refresh(tmp_path: Path) -> None:
    """Manual compaction owns one token through its existing post-result refresh."""
    from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    result = ManualCompactionResultDAO(status="nothing_to_compact")

    async def compact() -> ManualCompactionResultDAO:
        """Observe the actual lock admission."""
        assert session._lock.locked()
        assert session._reporting_state().state == "working"
        return result

    async def refresh(*, result: ManualCompactionResultDAO) -> ManualCompactionResultDAO:
        """Final usage must precede the settled publication."""
        assert session._reporting_state().state == "working"
        return result

    with (
        patch.object(session, "_compact_context_locked", side_effect=compact),
        patch.object(session, "_with_refreshed_context_window", side_effect=refresh),
    ):
        assert await session.compact_context() is result
    assert session._reporting_state().state == "idle"
    assert not session._reporting_operations


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "newer", "stale"])
async def test_startup_operation_owns_matching_attention(tmp_path: Path, outcome: str) -> None:
    """Actual startup retires its operation and never clears a newer requirement."""
    from src.agents.model_catalog.service import ModelCatalogService, ModelPreparationRequiredError
    from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._preparation_status = "pending"
    session.set_operator_attention(reason="Model preparation required")
    error = RuntimeError("original") if outcome == "failure" else asyncio.CancelledError()

    async def prepare(*, model_names: tuple[str, ...]) -> ModelCatalogSnapshotDAO:
        """Observe the actual preparation await without constructing a provider."""
        assert session._reporting_state().state == "working"
        assert len(session._reporting_operations) == 1
        if outcome == "newer":
            session.set_operator_attention(reason="Authentication required")
        if outcome == "stale":
            assert session._config is not None
            session._config = session._config.model_copy()
        if outcome in {"failure", "cancel"}:
            raise error
        return ModelCatalogService.load()

    with patch.object(ModelCatalogService, "prepare_models", side_effect=prepare):
        if outcome in {"failure", "cancel"}:
            with pytest.raises(
                ModelPreparationRequiredError if outcome == "failure" else asyncio.CancelledError
            ):
                await session.prepare_startup()
        else:
            await session.prepare_startup()
    assert not session._reporting_operations
    expected = {"success": None, "newer": "Authentication required"}.get(
        outcome, "Model preparation required"
    )
    assert session._reporting_state().block_reason == expected


@pytest.mark.parametrize("busy", [False, True])
async def test_readiness_rejection_never_accepts_work(tmp_path: Path, busy: bool) -> None:
    """Rejection publishes preparation attention but does not overwrite active work."""
    from src.agents.model_catalog.service import ModelPreparationRequiredError

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    session._preparation_status = "pending"
    old = session.set_operator_attention(reason="Authentication required")
    operation = session._begin_reporting_operation() if busy else None
    session._is_running = busy
    with pytest.raises(ModelPreparationRequiredError):
        _ = [event async for event in session.invoke(text="not accepted")]
    assert session._operation_serial == int(busy)
    if busy:
        assert session._operator_attention is not None
        assert operation is not None
        assert session._operator_attention.token == old
        assert session._reporting_state().state == "working"
        session._end_reporting_operation(token=operation)
    else:
        assert session._reporting_state().block_reason == "Model preparation required"


@pytest.mark.parametrize("status", ["compacted", "nothing_to_compact", "unavailable", "failed"])
@pytest.mark.parametrize("fault", ["none", "cancel", "error", "refresh"])
async def test_manual_terminal_matrix(tmp_path: Path, status: str, fault: str) -> None:
    """Manual outcomes retain original failures and commit usage before settlement."""
    from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    result = ManualCompactionResultDAO.model_validate({"status": status})
    error = asyncio.CancelledError() if fault == "cancel" else RuntimeError("original")
    seen: list[str] = []

    async def compact() -> ManualCompactionResultDAO:
        """Inject a terminal outcome at the existing manual boundary."""
        assert session._reporting_state().state == "working"
        if fault in {"cancel", "error"}:
            raise error
        return result

    def usage() -> None:
        """Record final usage while the exact operation remains active."""
        assert session._reporting_state().state == "working"
        seen.append("usage")
        if fault == "refresh":
            raise RuntimeError("optional")

    with (
        patch.object(session, "_compact_context_locked", side_effect=compact),
        patch.object(session, "refresh_usage_snapshot", side_effect=usage),
    ):
        if fault in {"cancel", "error"}:
            with pytest.raises(type(error)) as caught:
                await session.compact_context()
            assert caught.value is error
        else:
            assert (await session.compact_context()).status == status
    assert seen
    assert not session._reporting_operations
    expected = fault == "error" or (fault not in {"cancel", "error"} and status == "failed")
    assert session._reporting_state().state == ("blocked" if expected else "idle")


@pytest.mark.parametrize(
    "kind,child,observe",
    [
        ("text_start", False, True),
        ("tool_result", False, True),
        ("run_retrying", False, True),
        ("run_failed", False, True),
        ("text_delta", False, False),
        ("thinking_delta", False, False),
        ("tool_call_delta", False, False),
        ("tool_output_update", False, False),
        ("text_end", True, False),
        ("sub_agent_completed", False, False),
    ],
)
async def test_route_observation_ignores_deltas_and_children(
    tmp_path: Path,
    kind: str,
    child: bool,
    observe: bool,
) -> None:
    """Normalized parent boundaries rebuild changed routes without committing usage."""
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    event = AgentStreamEventDAO.model_validate(
        {
            "kind": kind,
            "sub_agent_id": "child" if child else None,
            "content": "Approval required Authentication required",
        }
    )
    with (
        patch.object(session, "_resolve_active_model_name", return_value="claude-sonnet-4-6"),
        patch.object(session, "_sync_usage_snapshot_commit", side_effect=AssertionError("no commit")),
        patch.object(session, "_rebuild_usage_snapshot", wraps=session._rebuild_usage_snapshot) as rebuild,
    ):
        await session._dispatch_event(event=event)
        await session._dispatch_event(event=event)
    assert rebuild.call_count == int(observe)
    assert session._operator_attention is None
    assert not session._reporting_operations


async def test_auth_requirement_preserves_original_lazy_error(tmp_path: Path) -> None:
    """The existing credential-required boundary reports auth, not an inferred run failure."""
    from src.auth.credential_resolver import CredentialResolver

    session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
    error = ValueError("original missing credential")
    with patch.object(CredentialResolver, "require", side_effect=error):
        with pytest.raises(ValueError) as caught:
            _ = [event async for event in session.invoke(text="not authenticated")]
    assert caught.value is error
    assert session._reporting_state().block_reason == "Authentication required"
    assert not session._reporting_operations


@pytest.mark.parametrize("chunked_usage", [False, True])
@pytest.mark.parametrize("first_total", [12, 23])
@pytest.mark.parametrize("refresh_each_event", [False, True])
@pytest.mark.parametrize("auth", [False, True])
@pytest.mark.parametrize("publication_fault", [False, True])
async def test_real_faux_tool_submission_keeps_working_and_commits_totals(
    tmp_path: Path,
    auth: bool,
    publication_fault: bool,
    first_total: int,
    refresh_each_event: bool,
    chunked_usage: bool,
) -> None:
    """Actual config/factory/graph/tool execution retains one operation through final usage."""
    from langchain_core.messages import AIMessage, AIMessageChunk
    from src.agents.base import LLMBuildResult
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO
    from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
    from src.agents.tools.echo import echo_tool
    from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
    from src.auth.credential_resolver import CredentialResolver

    messages = [
        AIMessage(
            content="",
            tool_calls=[{"name": "echo", "args": {"text": "Approval required"}, "id": "one"}],
            usage_metadata={"input_tokens": first_total - 3, "output_tokens": 3, "total_tokens": first_total},
        ),
        AIMessage(
            content="done", usage_metadata={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23}
        ),
    ]
    chunks = None
    if chunked_usage:
        chunks = [
            [
                AIMessageChunk(content="", tool_calls=messages[0].tool_calls),
                AIMessageChunk(content="", usage_metadata=messages[0].usage_metadata),
            ],
            [
                AIMessageChunk(
                    content="do", usage_metadata={"input_tokens": 20, "output_tokens": 1, "total_tokens": 21}
                ),
                AIMessageChunk(
                    content="ne", usage_metadata={"input_tokens": 0, "output_tokens": 2, "total_tokens": 2}
                ),
            ],
        ]
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    publications: list[HerdrPublicationDAO] = []
    events: list[str] = []
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(
                llm=FauxChatModel(responses=messages, chunk_scripts=chunks), supports_explicit_caching=False
            ),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                extra_tools=[echo_tool],
            )
        )
        if auth:
            session.set_operator_attention(reason="Authentication required")
        session._herdr_reporting_started = True

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Retain the immutable handoff and optionally fail the integration."""
            publications.append(publication)
            if publication_fault:
                raise RuntimeError("optional reporter")

        async def observe(event: AgentStreamEventDAO) -> None:
            """All streamed work including terminal events still belongs to the scope."""
            assert session._reporting_state().state == "working"
            assert len(session._reporting_operations) == 1
            events.append(event.kind)
            if refresh_each_event:
                session.refresh_usage_snapshot()

        session.subscribe(handler=observe)
        with patch.object(session._herdr_reporter, "publish", side_effect=publish):
            _ = [event async for event in session.invoke(text="echo then finish")]
    assert "tool_result" in events and "run_completed" in events
    assert session._operation_serial == 1 and not session._reporting_operations
    assert session.usage_snapshot().session_totals.total_tokens == first_total + 23
    assert publications[-1].snapshot.state == ("blocked" if auth else "idle")
    assert all(item.snapshot.state == "working" for item in publications[:-1])
    assert session._reporting_state().block_reason == ("Authentication required" if auth else None)
