"""Manual Compaction session-operation tests (spec 62.a.2)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.providers.openai_codex import build_chatgpt_backed_chat_openai
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName


def _viable_events() -> list[SessionHistoryEventDAO]:
    """Build two turns whose older event lies outside the retained token tail.

    Returns:
        list[SessionHistoryEventDAO]: Events with one valid manual cut point.
    """
    return [
        SessionHistoryEventDAO(
            session_id="session",
            kind="user_message",
            turn_id="old",
            sequence=1,
            payload=SessionHistoryEventPayloadDAO(content="old", token_usage=25_000),
        ),
        SessionHistoryEventDAO(
            session_id="session",
            kind="user_message",
            turn_id="recent",
            sequence=2,
            payload=SessionHistoryEventPayloadDAO(content="recent", token_usage=25_000),
        ),
        SessionHistoryEventDAO(
            session_id="session",
            kind="run_completed",
            turn_id="recent",
            sequence=3,
            payload=SessionHistoryEventPayloadDAO(token_usage=0),
        ),
    ]


def _session(
    *, events: list[SessionHistoryEventDAO], enabled: bool = True
) -> tuple[SloAgentSession, MagicMock]:
    """Build a history-backed session test fixture.

    Args:
        events (list[SessionHistoryEventDAO]): Events returned by the store.
        enabled (bool): Whether session history is enabled.

    Returns:
        tuple[SloAgentSession, MagicMock]: Session and its store mock.
    """
    store: MagicMock = MagicMock()
    store.session_exists = AsyncMock(return_value=True)
    store.load_events = AsyncMock(return_value=events)
    store.compact_to_boundary = AsyncMock()
    store.append_event = AsyncMock()
    store.ensure_session = AsyncMock(
        return_value=SessionHistoryMetadataDAO(session_id="session", workdir=Path("/tmp"))
    )
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="summary")]), tools=[])
    return (
        SloAgentSession(
            agent=agent,
            workdir=Path("/tmp"),
            session_id="session",
            history_store=store if enabled else None,
            enable_history=enabled,
        ),
        store,
    )


@pytest.mark.asyncio
async def test_compact_context_rejects_when_session_lock_is_held() -> None:
    """Manual Compaction rejects before touching the store while a prompt owns the lock."""
    session, store = _session(events=[])
    await session._lock.acquire()
    try:
        result = await session.compact_context()
    finally:
        session._lock.release()

    assert result.status == "unavailable"
    assert result.detail == "cannot compact while a prompt is in flight; run /abort first"
    store.session_exists.assert_not_awaited()
    store.load_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_returns_nothing_to_compact_for_empty_history() -> None:
    """An empty durable session is a successful no-op."""
    session, store = _session(events=[])

    result = await session.compact_context()

    assert result.status == "nothing_to_compact"
    store.compact_to_boundary.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_window_snapshot_reports_capacity_when_history_is_disabled() -> None:
    """Capacity remains visible when no durable estimate can be made."""
    session, _ = _session(events=[], enabled=False)

    snapshot = await session.context_window_snapshot()

    assert snapshot.estimate_available is False
    assert snapshot.context_window_tokens > 0


@pytest.mark.asyncio
async def test_compact_context_reports_exact_disabled_history_detail_without_io() -> None:
    """Disabled history is unavailable and never touches the injected store."""
    session, store = _session(events=[], enabled=False)

    result = await session.compact_context()

    assert result.status == "unavailable"
    assert result.detail == "session history is disabled; there is nothing to compact"
    store.session_exists.assert_not_awaited()
    store.load_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_returns_noop_for_absent_session_without_creating_history() -> None:
    """A brand-new session remains byte-free after Manual Compaction no-ops."""
    session, store = _session(events=[])
    store.session_exists = AsyncMock(return_value=False)

    result = await session.compact_context()

    assert result.status == "nothing_to_compact"
    store.load_events.assert_not_awaited()
    store.ensure_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_context_reports_unreadable_history_with_exact_detail() -> None:
    """Parse/load failure is an unavailable result before model preparation."""
    session, store = _session(events=[])
    store.load_events = AsyncMock(side_effect=OSError("broken log"))

    result = await session.compact_context()

    assert result.status == "unavailable"
    assert result.detail == "session history is unavailable; try again after repairing the session"


@pytest.mark.asyncio
async def test_compact_context_ensures_history_after_viable_cut_before_model_readiness() -> None:
    """The viable manual path establishes durable metadata before waking the model."""
    viable_events: list[SessionHistoryEventDAO] = _viable_events()
    session, store = _session(events=viable_events)
    calls: list[str] = []
    session._ensure_history_session = AsyncMock(side_effect=lambda: calls.append("history"))
    session._ensure_manual_compaction_agent_ready = AsyncMock(side_effect=lambda: calls.append("model"))
    session._run_manual_compaction = AsyncMock(return_value=MagicMock(status="compacted"))

    await session.compact_context()

    assert calls == ["history", "model"]


@pytest.mark.asyncio
async def test_compact_context_passes_validated_events_without_a_second_load() -> None:
    """The forced pipeline receives exactly the one measured durable event list."""
    viable_events: list[SessionHistoryEventDAO] = _viable_events()
    session, store = _session(events=viable_events)
    session._run_compaction_if_needed = AsyncMock()

    result = await session.compact_context()

    assert result.status == "compacted"
    kwargs = session._run_compaction_if_needed.await_args.kwargs
    assert kwargs["events"] is viable_events
    assert kwargs["force"] is True
    assert store.load_events.await_count == 2  # validated handoff plus one post-operation refresh


@pytest.mark.parametrize(
    ("authorization_scheme", "authorization_credential"),
    [
        ("Bearer", "opaque-bearer-credential"),
        ("Basic", "dXNlcjpwYXNz"),
        ("Token", "opaque-provider-token"),
    ],
)
@pytest.mark.asyncio
async def test_manual_compaction_failure_redacts_authorization_credentials_on_every_surface(
    authorization_scheme: str,
    authorization_credential: str,
) -> None:
    """A failed /compact redacts every supported authorization credential everywhere."""
    secrets: tuple[str, ...] = (
        authorization_credential,
        "signed-url-signature",
        "AKIA-signed-url-credential",
        "signed-url-security-token",
    )
    session, store = _session(events=_viable_events())
    captured: list[AgentStreamEventDAO] = []

    async def _capture(event: AgentStreamEventDAO) -> None:
        """Append one dispatched event."""
        captured.append(event)

    session.subscribe(handler=_capture)

    with patch.object(
        session,
        "_run_compaction_if_needed",
        new=AsyncMock(
            side_effect=RuntimeError(
                "Unsupported parameter: max_output_tokens; "
                f"Authorization: {authorization_scheme} {secrets[0]}; rewrite failed "
                f"https://bucket.example/a?X-Amz-Signature={secrets[1]}&"
                f"X-Amz-Credential={secrets[2]}&X-Amz-Security-Token={secrets[3]}"
            )
        ),
    ):
        result = await session.compact_context()

    assert result.status == "failed"
    assert result.detail is not None
    assert "RuntimeError" in result.detail
    assert "Unsupported parameter: max_output_tokens" in result.detail
    for secret in secrets:
        assert secret not in result.detail

    failed_events = [event for event in captured if event.kind == "compaction_failed"]
    assert len(failed_events) == 1
    failed_event: AgentStreamEventDAO = failed_events[0]
    assert failed_event.content == result.detail
    assert failed_event.content is not None
    assert failed_event.metadata["failure_scope"] == "compaction"
    assert failed_event.metadata["error_class"] == "RuntimeError"
    for secret in secrets:
        assert secret not in failed_event.content
        assert secret not in str(failed_event.metadata)

    audits = [
        call.kwargs["event"]
        for call in store.append_event.await_args_list
        if call.kwargs["event"].kind == "run_failed"
    ]
    assert len(audits) == 1
    assert audits[0].payload.metadata["failure_scope"] == "compaction"
    assert audits[0].payload.error_message == failed_event.metadata["safe_message"]
    for secret in secrets:
        assert secret not in str(audits[0].payload.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_manual_compaction_failure_survives_audit_persistence_error() -> None:
    """An audit write failure never hides the live event or leaks its text."""
    session, store = _session(events=_viable_events())
    store.append_event = AsyncMock(side_effect=RuntimeError("disk secret sk-ant-leak-me"))
    captured: list[AgentStreamEventDAO] = []

    async def _capture(event: AgentStreamEventDAO) -> None:
        """Append one dispatched event."""
        captured.append(event)

    session.subscribe(handler=_capture)

    with (
        patch.object(
            session,
            "_run_compaction_if_needed",
            new=AsyncMock(side_effect=ValueError("boom")),
        ),
        patch("src.agents.slo_agent.sessions.service.log_error") as mock_log_error,
    ):
        result = await session.compact_context()

    assert result.status == "failed"
    assert result.detail == "ValueError: boom"
    assert len([event for event in captured if event.kind == "compaction_failed"]) == 1

    audit_failures = [
        call
        for call in mock_log_error.call_args_list
        if call.kwargs.get("msg") == "compaction_failure_audit_failed"
    ]
    assert len(audit_failures) == 1
    assert audit_failures[0].kwargs.get("error_class") == "RuntimeError"
    assert "sk-ant-leak-me" not in str(mock_log_error.call_args_list)


def test_no_new_compaction_failure_structure_is_introduced() -> None:
    """Feature 85.a.3 adds no history kind or failure DAO."""
    assert "compaction_failed" not in get_args(HistoryEventKind)
    source = Path("src/agents/slo_agent/sessions/service.py").read_text(encoding="utf-8")
    assert "CompactionFailureDAO" not in source
    assert "CompactionOutcomeDAO" not in source


def test_feature_85_closeout_source_review_finds_no_prohibited_structures() -> None:
    """The whole ``src/`` tree contains only the sanctioned feature-85 additions.

    Enforces the 85.a.4 §4 prohibited-change review: no absolute input ceiling,
    no alternate policy/outcome/failure DAO, no request-shaping gateway, no pool
    capacity planner, no new history kind, and exactly the one new stream literal.
    """
    source_text: str = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    for forbidden in (
        "SLO_COMPACTION_MAX_INPUT_TOKENS",
        "CompactionPolicyDAO",
        "CompactionOutcomeDAO",
        "CompactionFailureDAO",
        "request_shaping",
        "invoke_provider_request",
        "CompactionInputCapacityService",
        "request_candidate_model_names",
    ):
        assert forbidden not in source_text
    assert ".decide(" not in source_text
    assert "compaction_failed" not in get_args(HistoryEventKind)
    assert "compaction_advised" in get_args(StreamEventKind)
    checker = Path("src/agents/slo_agent/compaction/compaction_checker.py").read_text(encoding="utf-8")
    assert "int(effective_window * 0.70)" in checker


class TestSafeCompactionFailureMessage:
    """Decision-point coverage for the local redaction helper."""

    @pytest.mark.parametrize(
        ("raw", "secret"),
        [
            (
                "token eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c failed",
                "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c",
            ),
            ("key sk-proj-abc123XYZ rejected", "sk-proj-abc123XYZ"),
            ("key sk-ant-api03-secret-value rejected", "sk-ant-api03-secret-value"),
            ("Authorization: Bearer abc.def.ghi-123", "abc.def.ghi-123"),
            ("api_key=hunter2secret refused", "hunter2secret"),
            ("password: open-sesame-123", "open-sesame-123"),
            ("https://files.example.com/x?sig=abc123secret&ok=1", "abc123secret"),
            (
                "https://bucket.example/a?X-Amz-Signature=secret-signature",
                "secret-signature",
            ),
            (
                "https://bucket.example/a?X-Amz-Credential=AKIA-signed-credential",
                "AKIA-signed-credential",
            ),
            (
                "https://bucket.example/a?X-Amz-Security-Token=secret-security-token",
                "secret-security-token",
            ),
            ("https://user:p%40ssw0rd@example.com/path", "user:p%40ssw0rd@"),
        ],
    )
    def test_redacts_each_secret_shape(self, raw: str, secret: str) -> None:
        """Every ordered redaction rule removes its secret fragment."""
        safe: str = SloAgentSession._safe_compaction_failure_message(error=RuntimeError(raw))

        assert secret not in safe
        assert "<redacted>" in safe

    def test_collapses_whitespace_into_one_line(self) -> None:
        """Newlines and runs of whitespace collapse to single spaces."""
        safe: str = SloAgentSession._safe_compaction_failure_message(
            error=RuntimeError("line one\n\n  line\t two   end")
        )

        assert safe == "line one line two end"

    def test_truncates_to_the_message_limit(self) -> None:
        """A message longer than 300 characters is bounded."""
        safe: str = SloAgentSession._safe_compaction_failure_message(error=RuntimeError("x" * 1_000))

        assert len(safe) == 300

    def test_falls_back_to_class_name_when_no_text_remains(self) -> None:
        """An empty exception message yields the exception class name."""
        safe: str = SloAgentSession._safe_compaction_failure_message(error=RuntimeError())

        assert safe == "RuntimeError"

    def test_failure_text_prefixes_the_exception_class(self) -> None:
        """Operator-facing text is '<ExceptionClass>: <safe message>'."""
        text: str = SloAgentSession._compaction_failure_text(error=ValueError("bad cut"))

        assert text == "ValueError: bad cut"


class TestCompactionFailureMetadata:
    """Decision-point coverage for the shared safe metadata bag."""

    def test_includes_provider_and_status_when_available(self) -> None:
        """A recognized model and status-bearing error surface safe facts."""
        session, _ = _session(events=[])
        error = RuntimeError("rate limited")
        error.status_code = 429  # type: ignore[attr-defined]

        metadata: dict[str, object] = session._compaction_failure_metadata(
            error=error,
            safe_message="rate limited",
        )

        assert metadata == {
            "failure_scope": "compaction",
            "error_class": "RuntimeError",
            "safe_message": "rate limited",
            "provider_name": "openai",
            "status_code": 429,
        }

    def test_omits_provider_facts_for_an_unknown_model(self) -> None:
        """An unrecognized model yields null provider and status fields."""
        session, _ = _session(events=[])
        session._active_model_name = "totally-unknown-model"

        metadata: dict[str, object] = session._compaction_failure_metadata(
            error=ValueError("boom"),
            safe_message="boom",
        )

        assert metadata["provider_name"] is None
        assert metadata["status_code"] is None
        assert metadata["failure_scope"] == "compaction"
        assert metadata["error_class"] == "ValueError"


# ---------------------------------------------------------------------------
# Composed OAuth manual-compaction path (85.a.4 §3.1)
# ---------------------------------------------------------------------------


def _build_jwt(*, claims: dict[str, Any]) -> str:
    """Build a fake unsigned JWT carrying ``claims`` in its payload segment.

    Called by ``_oauth_cred`` to fabricate a ChatGPT account id inside the
    access token without touching a real credential store.

    Args:
        claims (dict[str, Any]): JWT payload claims.

    Returns:
        str: Three-part token suitable for the OAuth builder.
    """
    header_b64: str = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload_b64: str = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode("ascii")
    )
    return f"{header_b64}.{payload_b64}.signature"


def _oauth_cred() -> CredentialDAO:
    """Build an OAuth OpenAI credential yielding a ChatGPT account id.

    Called by the composed OAuth manual-compaction test to feed the real
    ``build_chatgpt_backed_chat_openai`` builder.

    Returns:
        CredentialDAO: In-memory OAuth credential with no live token.
    """
    return CredentialDAO(
        provider=ProviderName.OPENAI,
        auth_type=AuthType.OAUTH,
        access_token=_build_jwt(
            claims={"https://api.openai.com/auth": {"chatgpt_account_id": "acct-summary"}},
        ),
        refresh_token="rt-test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="openid profile email offline_access",
    )


def _completed_response_body(*, summary: str) -> dict[str, Any]:
    """Build a minimal non-streaming Responses API completion carrying ``summary``.

    Called by ``test_oauth_manual_compaction_persists_and_projects_summary`` so
    the ChatGPT backend returns a parseable summary instead of a streamed SSE
    payload.

    Args:
        summary (str): Summary text the model should appear to return.

    Returns:
        dict[str, Any]: Responses API response body with one assistant message.
    """
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-5",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": summary, "annotations": []}],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


@pytest.mark.asyncio
async def test_oauth_manual_compaction_persists_and_projects_summary(tmp_path: Path) -> None:
    """A real ChatGPT-backend /compact persists one replayable summary end to end.

    Drives ``SloAgentSession.compact_context()`` over a real
    ``FilesystemSessionHistoryStore`` and a real OAuth ``ChatOpenAI`` wired to an
    ``httpx.MockTransport``. The captured request must carry ``instructions`` and
    no output-token field; the reloaded store must hold exactly one
    ``compaction_summary`` that the projector surfaces in replay.
    """
    session_id: str = "sess-oauth"
    captured: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        """Capture the outbound body and return a completed summary response."""
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json=_completed_response_body(summary="compacted summary"),
        )

    chat = build_chatgpt_backed_chat_openai(
        model_name="gpt-5",
        cred=_oauth_cred(),
        session_id=session_id,
        streaming=False,
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
    )
    store: FilesystemSessionHistoryStore = FilesystemSessionHistoryStore(root=tmp_path)
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5")
    for event in _viable_events():
        await store.append_event(
            event=event.model_copy(update={"session_id": session_id}),
        )

    session = SloAgentSession(
        agent=SloAgent(llm=chat, cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id,
        history_store=store,
        enable_history=True,
    )

    result = await session.compact_context()

    assert result.status == "compacted"
    body: dict[str, Any] = captured["body"]
    assert "max_tokens" not in body
    assert "max_output_tokens" not in body
    assert "max_completion_tokens" not in body
    assert isinstance(body.get("instructions"), str)
    assert "You are a conversation compactor" in body["instructions"]

    reloaded: list[SessionHistoryEventDAO] = await store.load_events(session_id=session_id)
    summaries: list[SessionHistoryEventDAO] = [
        event for event in reloaded if event.kind == "compaction_summary"
    ]
    assert len(summaries) == 1
    assert summaries[0].payload.content == "compacted summary"

    messages = await SessionHistoryProjector.build_message_history(events=reloaded)
    replayed: str = " ".join(
        message.content if isinstance(message.content, str) else str(message.content) for message in messages
    )
    assert "compacted summary" in replayed
