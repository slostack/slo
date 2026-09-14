"""Integration tests: compaction wiring in SloAgentSession.invoke().

Tests verify:
  1. _is_context_overflow_error correctly classifies provider exceptions.
  2. _run_compaction_if_needed is a no-op when history is disabled.
  3. _run_compaction_if_needed is a no-op when _agent is None.
  4. _run_compaction_if_needed is a no-op when CompactionChecker returns False.
  5. _run_compaction_if_needed calls the full pipeline when threshold is crossed.
  6. _run_compaction_if_needed can force compaction by bypassing the checker.
  7. _run_compaction_if_needed is called after every successful turn.
  8. _run_compaction_if_needed is called on context overflow errors, not other errors.
  9. Overflow-triggered compaction failures do not mask the original provider error.
  10. After compaction, the next _load_message_history() returns projector-aware history.
  11-18. Overflow-recovery retry path (spec 46.a.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
    SessionHistoryMetadataDAO,
)
from src.agents.providers import FauxChatModel
from src.auth.credential_dao import ProviderName
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.projector import SessionHistoryProjector
from src.agents.providers.credit_exhaustion_policy import ProviderErrorClassifier, ProviderErrorKind
from src.agents.slo_agent.sessions.dao import PreflightDecisionDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    kind: HistoryEventKind,
    session_id: str = "sess-test",
    turn_id: Optional[str] = None,
    token_usage: Optional[int] = None,
    content: str = "",
    sequence: int = 0,
) -> SessionHistoryEventDAO:
    """Build a minimal SessionHistoryEventDAO for testing.

    Args:
        kind (str): Event kind.
        session_id (str): Session owner.
        turn_id (Optional[str]): Owning turn id.
        token_usage (Optional[int]): Pre-set token weight.
        content (str): Payload content.
        sequence (int): Sequence number.

    Returns:
        SessionHistoryEventDAO: Minimal event suitable for unit testing.
    """
    return SessionHistoryEventDAO(
        session_id=session_id,
        kind=kind,
        turn_id=turn_id,
        sequence=sequence,
        payload=SessionHistoryEventPayloadDAO(
            content=content,
            token_usage=token_usage,
        ),
    )


def _build_session(
    *,
    enable_history: bool = True,
    events: Optional[list[SessionHistoryEventDAO]] = None,
) -> tuple[SloAgentSession, MagicMock]:
    """Build a SloAgentSession with a mocked store and agent.

    Args:
        enable_history (bool): Whether to enable history on the session.
        events (Optional[list[SessionHistoryEventDAO]]): Events the mock
            store returns from ``load_events``.

    Returns:
        tuple[SloAgentSession, MagicMock]: The session and its mock store.
    """
    mock_store = MagicMock()
    mock_store.load_events = AsyncMock(return_value=events or [])
    mock_store.append_event = AsyncMock(side_effect=lambda *, event: event)
    mock_store.append_compaction_summary = AsyncMock(
        return_value=_make_event(kind="compaction_summary"),
    )
    metadata = SessionHistoryMetadataDAO(
        session_id="sess-test",
        workdir=Path("/tmp"),
    )
    mock_store.ensure_session = AsyncMock(return_value=metadata)
    mock_store.read_metadata = AsyncMock(return_value=metadata)
    mock_store.write_metadata = AsyncMock()
    mock_store.update_metadata_model_name = AsyncMock()
    mock_store.session_exists = AsyncMock(return_value=True)
    mock_store.truncate_to_compaction_boundary = AsyncMock()
    mock_store.compact_to_boundary = AsyncMock()

    # A real SloAgent backed by a FauxChatModel — mirrors the established
    # session-test pattern. A bare MagicMock agent breaks construction because
    # ``_resolve_active_model_name`` picks up the mock's auto-generated
    # ``llm.active_model_name`` attribute, which is not a supported model.
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        cwd="/tmp",
        tools=[],
    )

    session = SloAgentSession(
        session_id="sess-test",
        workdir=Path("/tmp"),
        enable_history=enable_history,
        history_store=mock_store if enable_history else None,
        agent=agent,
    )
    return session, mock_store


# ---------------------------------------------------------------------------
# Tests for the canonical provider-error classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected_kind"),
    [
        ("anthropic: prompt is too long for this model", ProviderErrorKind.CONTEXT_OVERFLOW),
        ("openai error: context_length_exceeded — reduce your input", ProviderErrorKind.CONTEXT_OVERFLOW),
        ("maximum context length is 200000 tokens, got 201000", ProviderErrorKind.CONTEXT_OVERFLOW),
        ("PROMPT IS TOO LONG — please shorten your input", ProviderErrorKind.CONTEXT_OVERFLOW),
        ("429 rate limit reached", ProviderErrorKind.RATE_LIMITED),
        ("bash: command not found: mycommand", ProviderErrorKind.OTHER),
    ],
)
def test_provider_error_classifier_inspects_context_markers(
    message: str,
    expected_kind: ProviderErrorKind,
) -> None:
    """The canonical classifier replaces the removed session-private matcher."""
    signal = ProviderErrorClassifier.inspect(
        error=RuntimeError(message),
        provider=ProviderName.OPENAI,
    )

    assert signal.kind is expected_kind


# ---------------------------------------------------------------------------
# Tests for _run_compaction_if_needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_compaction_skipped_when_history_disabled() -> None:
    """No store load or compaction when history is disabled."""
    session, _ = _build_session(enable_history=False)

    with patch(
        "src.agents.slo_agent.compaction.compaction_checker.CompactionChecker.should_compact",
        return_value=False,
    ) as mock_check:
        await session._run_compaction_if_needed(turn_id="turn-1")
        mock_check.assert_not_called()


@pytest.mark.asyncio
async def test_run_compaction_skipped_when_agent_is_none() -> None:
    """No compaction attempt when _agent is not yet built."""
    session, _ = _build_session()
    session._agent = None  # type: ignore[assignment]

    with patch(
        "src.agents.slo_agent.compaction.compaction_checker.CompactionChecker.should_compact",
        return_value=False,
    ) as mock_check:
        await session._run_compaction_if_needed(turn_id="turn-1")
        mock_check.assert_not_called()


@pytest.mark.asyncio
async def test_run_compaction_skipped_when_threshold_not_crossed() -> None:
    """Compacter is NOT called when CompactionChecker returns False."""
    events = [_make_event(kind="user_message", token_usage=100)]
    session, _ = _build_session(events=events)

    with (
        patch(
            "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
            return_value=False,
        ) as mock_check,
        patch(
            "src.agents.slo_agent.sessions.service.Compacter.compact",
            new_callable=AsyncMock,
        ) as mock_compact,
    ):
        await session._run_compaction_if_needed(turn_id="turn-1")
        mock_check.assert_called_once()
        mock_compact.assert_not_called()


@pytest.mark.asyncio
async def test_run_compaction_calls_full_pipeline_when_threshold_crossed() -> None:
    """Compacter.compact and CompactedSessionUpdater.update are called when threshold crossed."""
    from src.agents.slo_agent.compaction.compacter import CompactionResult

    events = [_make_event(kind="user_message", token_usage=185_000)]
    session, _ = _build_session(events=events)

    fake_result = CompactionResult(
        summary_text="summary text",
        first_kept_entry_id="e-kept",
        cut_point_entry_id="e-cut",
        tokens_before=185_000,
        tokens_after=50,
    )

    with (
        patch(
            "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
            return_value=True,
        ),
        patch(
            "src.agents.slo_agent.sessions.service.Compacter.compact",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_compact,
        patch(
            "src.agents.slo_agent.sessions.service.CompactedSessionUpdater.update",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        await session._run_compaction_if_needed(turn_id="turn-1")
        mock_compact.assert_awaited_once()
        mock_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_compaction_calls_truncate_after_updater() -> None:
    """truncate_to_compaction_boundary is called with the stamped summary and events."""
    from src.agents.slo_agent.compaction.compacter import CompactionResult
    from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO

    events = [_make_event(kind="user_message", token_usage=185_000)]
    session, mock_store = _build_session(events=events)

    fake_result = CompactionResult(
        summary_text="summary text",
        first_kept_entry_id="e-kept",
        cut_point_entry_id="e-cut",
        tokens_before=185_000,
        tokens_after=50,
    )
    stamped_summary = SessionHistoryEventDAO(
        session_id="sess-test",
        kind="compaction_summary",
        sequence=42,
        payload=SessionHistoryEventPayloadDAO(content="summary text", token_usage=50),
    )

    with (
        patch(
            "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
            return_value=True,
        ),
        patch(
            "src.agents.slo_agent.sessions.service.Compacter.compact",
            new_callable=AsyncMock,
            return_value=fake_result,
        ),
        patch(
            "src.agents.slo_agent.sessions.service.CompactedSessionUpdater.update",
            new_callable=AsyncMock,
            return_value=stamped_summary,
        ),
    ):
        await session._run_compaction_if_needed(turn_id="turn-1")

    mock_store.compact_to_boundary.assert_awaited_once()
    call_kwargs = mock_store.compact_to_boundary.call_args.kwargs
    assert call_kwargs["session_id"] == "sess-test"
    assert call_kwargs["result"] is fake_result
    assert call_kwargs["turn_id"] == "turn-1"
    assert call_kwargs["events"] is events


@pytest.mark.asyncio
async def test_run_compaction_does_not_call_truncate_when_threshold_not_crossed() -> None:
    """truncate_to_compaction_boundary is not called when compaction is skipped."""
    events = [_make_event(kind="user_message", token_usage=100)]
    session, mock_store = _build_session(events=events)

    with patch(
        "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
        return_value=False,
    ):
        await session._run_compaction_if_needed(turn_id="turn-1")

    mock_store.compact_to_boundary.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_compaction_force_bypasses_threshold_checker() -> None:
    """Forced compaction skips the threshold gate and runs the pipeline immediately."""
    from src.agents.slo_agent.compaction.compacter import CompactionResult

    events = [_make_event(kind="user_message", token_usage=1, sequence=1)] * 2
    session, _ = _build_session(events=events)

    fake_result = CompactionResult(
        summary_text="forced summary",
        first_kept_entry_id="e-kept",
        cut_point_entry_id="e-cut",
        tokens_before=2,
        tokens_after=4,
    )

    with (
        patch(
            "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
            new_callable=AsyncMock,
        ) as mock_check,
        patch(
            "src.agents.slo_agent.sessions.service.Compacter.compact",
            new_callable=AsyncMock,
            return_value=fake_result,
        ) as mock_compact,
        patch(
            "src.agents.slo_agent.sessions.service.CompactedSessionUpdater.update",
            new_callable=AsyncMock,
        ) as mock_update,
    ):
        await session._run_compaction_if_needed(turn_id="turn-1", force=True)
        mock_check.assert_not_called()
        mock_compact.assert_awaited_once()
        mock_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_compaction_passes_model_name_to_checker() -> None:
    """CompactionChecker receives the session's resolved active model name."""
    session, _ = _build_session()

    with patch(
        "src.agents.slo_agent.sessions.service.CompactionChecker.should_compact",
        return_value=False,
    ) as mock_check:
        await session._run_compaction_if_needed(turn_id="turn-1")
        call_kwargs = mock_check.call_args.kwargs
        assert call_kwargs["model_name"] == session._resolve_active_model_name()


# ---------------------------------------------------------------------------
# Tests for wiring in invoke()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compaction_called_after_successful_turn() -> None:
    """_run_compaction_if_needed is awaited after a run_completed turn."""
    session, _ = _build_session()
    session._context_window_dirty = False  # isolate the post-turn check

    async def _fake_stream_with_retries(**kwargs):
        yield AgentStreamEventDAO(kind="run_completed", iteration=0, content="done")

    with (
        patch.object(
            session,
            "_stream_prompt_with_retries",
            _fake_stream_with_retries,
        ),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(
            session,
            "_run_compaction_if_needed",
            new_callable=AsyncMock,
        ) as mock_compact,
    ):
        async for _ in session.invoke(text="hello"):
            pass
        mock_compact.assert_awaited_once()


@pytest.mark.asyncio
async def test_compaction_not_triggered_on_non_overflow_error() -> None:
    """_run_compaction_if_needed is NOT called on a non-overflow exception."""
    session, _ = _build_session()
    session._context_window_dirty = False  # isolate the failure-path check

    async def _failing_stream(**kwargs):
        raise RuntimeError("tool crashed: file not found")
        yield  # noqa: unreachable

    with (
        patch.object(
            session,
            "_stream_prompt_with_retries",
            _failing_stream,
        ),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(
            session,
            "_run_compaction_if_needed",
            new_callable=AsyncMock,
        ) as mock_compact,
    ):
        with pytest.raises(RuntimeError, match="tool crashed"):
            async for _ in session.invoke(text="hello"):
                pass
        mock_compact.assert_not_awaited()


@pytest.mark.asyncio
async def test_compaction_triggered_on_context_overflow_error() -> None:
    """_run_compaction_if_needed is called when a context overflow exception fires."""
    session, _ = _build_session()
    session._context_window_dirty = False  # isolate the failure-path check

    async def _overflow_stream(**kwargs):
        raise RuntimeError("prompt is too long for this model")
        yield  # noqa: unreachable

    with (
        patch.object(
            session,
            "_stream_prompt_with_retries",
            _overflow_stream,
        ),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(
            session,
            "_run_compaction_if_needed",
            new_callable=AsyncMock,
        ) as mock_compact,
    ):
        with pytest.raises(RuntimeError, match="prompt is too long"):
            async for _ in session.invoke(text="hello"):
                pass
        mock_compact.assert_awaited_once()
        await_args = mock_compact.await_args
        assert await_args is not None
        assert await_args.kwargs["force"] is True


@pytest.mark.asyncio
async def test_overflow_compaction_failure_preserves_original_provider_error() -> None:
    """A failed overflow compaction attempt does not mask the original overflow.

    Compaction now runs inside ``_derive_next_attempt_plan`` (not
    ``_finalize_failed_attempt``).  When it fails there the method returns
    ``None``, ``_raise_if_attempt_failed`` re-raises the original overflow
    error, and the log message is ``"overflow_compaction_failed_before_retry"``.
    """
    session, _ = _build_session()
    session._context_window_dirty = False

    async def _overflow_stream(**kwargs):
        raise RuntimeError("Your request exceeded model token limit: 262144")
        yield  # noqa: unreachable

    with (
        patch.object(
            session,
            "_stream_prompt_with_retries",
            _overflow_stream,
        ),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(
            session,
            "_run_compaction_if_needed",
            new_callable=AsyncMock,
            side_effect=ValueError("no viable cut point"),
        ),
        patch("src.agents.slo_agent.sessions.service.log_error") as mock_log_error,
    ):
        with pytest.raises(RuntimeError, match="exceeded model token limit"):
            async for _ in session.invoke(text="hello"):
                pass

    assert any(
        call.kwargs.get("msg") == "overflow_compaction_failed_before_retry"
        for call in mock_log_error.call_args_list
    )


# ---------------------------------------------------------------------------
# Post-compaction projector integration
# ---------------------------------------------------------------------------


async def test_projector_skips_pre_cut_events_after_compaction() -> None:
    """After compaction, build_message_history skips pre-cut events.

    Exercises the projector (01.a.5) with a synthetic event list containing
    a compaction_summary. Verifies the contract this sub-spec relies on: the
    projector surfaces the summary as a [Previous conversation summary]
    HumanMessage and excludes all pre-cut events.
    """
    compaction_event = SessionHistoryEventDAO(
        session_id="sess-test",
        kind="compaction_summary",
        sequence=5,
        payload=SessionHistoryEventPayloadDAO(
            content="The assistant read foo.py and wrote bar.py.",
            token_usage=10,
            metadata={
                "first_kept_entry_id": "entry-6",
                "cut_point_entry_id": "entry-4",
                "tokens_before": 45_000,
                "tokens_after": 10,
            },
        ),
    )
    pre_cut_user = _make_event(
        kind="user_message",
        sequence=1,
        turn_id="t-1",
        content="old pre-compaction message",
        token_usage=5,
    )
    pre_cut_completed = _make_event(
        kind="run_completed",
        sequence=2,
        turn_id="t-1",
    )
    retained_user = _make_event(
        kind="user_message",
        sequence=6,
        turn_id="t-2",
        content="what did you change?",
        token_usage=5,
    )
    retained_assistant = _make_event(
        kind="assistant_message",
        sequence=7,
        turn_id="t-2",
        content="I added error handling to bar.py.",
        token_usage=9,
    )
    run_completed = _make_event(
        kind="run_completed",
        sequence=8,
        turn_id="t-2",
    )

    events = [
        pre_cut_user,
        pre_cut_completed,
        compaction_event,
        retained_user,
        retained_assistant,
        run_completed,
    ]

    messages = await SessionHistoryProjector.build_message_history(events=events)

    assert messages, "build_message_history must return a non-empty list"

    first = messages[0]
    assert isinstance(
        first, HumanMessage
    ), f"First message after compaction must be HumanMessage, got {type(first)}"
    first_content: str = first.content if isinstance(first.content, str) else str(first.content)
    assert (
        "[Previous conversation summary]" in first_content
    ), "Summary HumanMessage must begin with '[Previous conversation summary]'"
    assert (
        "foo.py" in first_content or "bar.py" in first_content
    ), "Summary text must appear in the HumanMessage content"

    all_contents = " ".join(m.content if isinstance(m.content, str) else str(m.content) for m in messages)
    assert (
        "old pre-compaction message" not in all_contents
    ), "Pre-cut user message must be excluded from projected history"
    assert "what did you change?" in all_contents, "Retained user message must appear in projected history"
    assert "error handling" in all_contents, "Retained assistant message must appear in projected history"


# ---------------------------------------------------------------------------
# Pre-flight compaction (dirty-flag) — model switch / resume gap
# ---------------------------------------------------------------------------


def test_new_session_starts_context_window_dirty() -> None:
    """A freshly built session is dirty so the first turn validates once."""
    session, _ = _build_session()

    assert session._context_window_dirty is True


# ---------------------------------------------------------------------------
# Overflow-recovery retry path (spec 46.a.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overflow_recovery_eligible_set_on_overflow_failure() -> None:
    """_finalize_failed_attempt sets overflow_recovery_eligible=True for overflow errors."""
    from src.agents.slo_agent.sessions.service import PromptAttemptTrackerDAO

    session, _ = _build_session()
    tracker = PromptAttemptTrackerDAO(turn_id="t-overflow")
    overflow_exc = RuntimeError("prompt is too long for this model")

    with patch.object(session, "_append_history_event", new_callable=AsyncMock):
        with patch.object(session, "_drain_and_persist_route_switches", new_callable=AsyncMock):
            with patch.object(session, "_persist_routed_model_if_changed", new_callable=AsyncMock):
                await session._finalize_failed_attempt(
                    tracker=tracker,
                    turn_id="t-overflow",
                    error=overflow_exc,
                )

    assert tracker.overflow_recovery_eligible is True


@pytest.mark.asyncio
async def test_overflow_recovery_eligible_not_set_on_non_overflow_failure() -> None:
    """_finalize_failed_attempt leaves overflow_recovery_eligible=False for non-overflow errors."""
    from src.agents.slo_agent.sessions.service import PromptAttemptTrackerDAO

    session, _ = _build_session()
    tracker = PromptAttemptTrackerDAO(turn_id="t-rate-limit")
    rate_limit_exc = RuntimeError("rate_limit_error: too many requests per minute")

    with patch.object(session, "_append_history_event", new_callable=AsyncMock):
        with patch.object(session, "_drain_and_persist_route_switches", new_callable=AsyncMock):
            with patch.object(session, "_persist_routed_model_if_changed", new_callable=AsyncMock):
                await session._finalize_failed_attempt(
                    tracker=tracker,
                    turn_id="t-rate-limit",
                    error=rate_limit_exc,
                )

    assert tracker.overflow_recovery_eligible is False


@pytest.mark.asyncio
async def test_derive_next_attempt_plan_returns_retry_plan_for_eligible_result() -> None:
    """_derive_next_attempt_plan returns a valid retry plan for an overflow-eligible initial attempt."""
    from src.agents.slo_agent.sessions.service import (
        PromptAttemptPlanDAO,
        PromptAttemptResultDAO,
    )

    session, _ = _build_session()
    overflow_exc = RuntimeError("context_length_exceeded")
    plan = PromptAttemptPlanDAO(attempt_kind="initial", text="hello")
    result = PromptAttemptResultDAO(
        turn_id="t-failed",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=overflow_exc,
        overflow_recovery_eligible=True,
    )

    with (
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock),
        patch.object(session, "_append_history_event", new_callable=AsyncMock),
        patch.object(session, "_dispatch_event", new_callable=AsyncMock),
    ):
        retry_plan = await session._derive_next_attempt_plan(plan=plan, result=result)

    assert retry_plan is not None
    assert retry_plan.attempt_kind == "overflow_retry"
    assert retry_plan.persist_user_message is False
    assert retry_plan.excluded_turn_ids == frozenset({"t-failed"})
    assert retry_plan.preflight_compaction_mode == "skip"
    assert retry_plan.source_failed_turn_id == "t-failed"
    assert retry_plan.text == "hello"


@pytest.mark.asyncio
async def test_derive_next_attempt_plan_returns_none_for_non_overflow_result() -> None:
    """_derive_next_attempt_plan returns None and skips compaction for non-overflow results."""
    from src.agents.slo_agent.sessions.service import (
        PromptAttemptPlanDAO,
        PromptAttemptResultDAO,
    )

    session, _ = _build_session()
    plan = PromptAttemptPlanDAO(attempt_kind="initial", text="hello")
    result = PromptAttemptResultDAO(
        turn_id="t-rate-limit",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=RuntimeError("rate_limit_error"),
        overflow_recovery_eligible=False,
    )

    with patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock) as mock_compact:
        retry_plan = await session._derive_next_attempt_plan(plan=plan, result=result)

    assert retry_plan is None
    mock_compact.assert_not_awaited()


@pytest.mark.asyncio
async def test_derive_next_attempt_plan_returns_none_when_budget_spent() -> None:
    """_derive_next_attempt_plan returns None when attempt_kind is already overflow_retry."""
    from src.agents.slo_agent.sessions.service import (
        PromptAttemptPlanDAO,
        PromptAttemptResultDAO,
    )

    session, _ = _build_session()
    overflow_exc = RuntimeError("prompt is too long for this model")
    retry_plan_input = PromptAttemptPlanDAO(attempt_kind="overflow_retry", text="hello")
    result = PromptAttemptResultDAO(
        turn_id="t-retry-overflow",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=overflow_exc,
        overflow_recovery_eligible=True,
    )

    with patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock) as mock_compact:
        next_plan = await session._derive_next_attempt_plan(plan=retry_plan_input, result=result)

    assert next_plan is None
    mock_compact.assert_not_awaited()


@pytest.mark.asyncio
async def test_derive_next_attempt_plan_returns_none_when_compaction_fails() -> None:
    """_derive_next_attempt_plan returns None when forced compaction raises, not the compaction error."""
    from src.agents.slo_agent.sessions.service import (
        PromptAttemptPlanDAO,
        PromptAttemptResultDAO,
    )

    session, _ = _build_session()
    overflow_exc = RuntimeError("context_length_exceeded")
    plan = PromptAttemptPlanDAO(attempt_kind="initial", text="hello")
    result = PromptAttemptResultDAO(
        turn_id="t-compact-fail",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=overflow_exc,
        overflow_recovery_eligible=True,
    )

    persist_mock = AsyncMock()
    dispatch_mock = AsyncMock()

    with (
        patch.object(
            session,
            "_run_compaction_if_needed",
            new_callable=AsyncMock,
            side_effect=RuntimeError("no viable cut point"),
        ),
        patch.object(session, "_persist_overflow_retry_diagnostic_event", persist_mock),
        patch.object(session, "_dispatch_event", dispatch_mock),
    ):
        next_plan = await session._derive_next_attempt_plan(plan=plan, result=result)

    assert next_plan is None
    persist_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_attempt_does_not_persist_duplicate_user_message() -> None:
    """The overflow retry attempt does not write a second user_message event."""
    session, mock_store = _build_session()
    session._context_window_dirty = False

    overflow_exc = RuntimeError("prompt is too long for this model")
    call_count = 0

    async def _stream_that_overflows_then_succeeds(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise overflow_exc
        yield AgentStreamEventDAO(kind="run_completed", iteration=0, content="done after retry")

    with (
        patch.object(session, "_stream_prompt_with_retries", _stream_that_overflows_then_succeeds),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock),
        patch.object(session, "_dispatch_event", new_callable=AsyncMock),
    ):
        events = []
        async for event in session.invoke(text="retry-me"):
            events.append(event)

    appended_kinds = [call.kwargs["event"].kind for call in mock_store.append_event.call_args_list]
    user_message_count = appended_kinds.count("user_message")
    assert (
        user_message_count == 1
    ), f"Expected exactly one user_message, got {user_message_count}: {appended_kinds}"


@pytest.mark.asyncio
async def test_retry_attempt_loads_history_excluding_failed_turn() -> None:
    """The retry attempt calls _load_message_history with excluded_turn_ids containing the failed turn."""
    session, _ = _build_session()
    session._context_window_dirty = False

    overflow_exc = RuntimeError("prompt is too long for this model")
    call_count = 0
    load_calls: list[set] = []
    original_load = session._load_message_history

    async def _capturing_load_message_history(*, excluded_turn_ids=None):
        load_calls.append(set(excluded_turn_ids or set()))
        return await original_load(excluded_turn_ids=excluded_turn_ids)

    async def _stream_that_overflows_then_succeeds(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise overflow_exc
        yield AgentStreamEventDAO(kind="run_completed", iteration=0, content="done after retry")

    with (
        patch.object(session, "_stream_prompt_with_retries", _stream_that_overflows_then_succeeds),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock),
        patch.object(session, "_load_message_history", side_effect=_capturing_load_message_history),
        patch.object(session, "_dispatch_event", new_callable=AsyncMock),
    ):
        async for _ in session.invoke(text="retry-me"):
            pass

    assert len(load_calls) == 2, f"Expected 2 history loads (initial + retry), got {len(load_calls)}"
    assert load_calls[0] == set(), "Initial attempt must load history with empty excluded set"
    assert len(load_calls[1]) == 1, "Retry attempt must exclude exactly one turn id"


@pytest.mark.asyncio
async def test_preflight_runs_compaction_and_clears_flag_when_dirty() -> None:
    """When dirty, the pre-flight runs one compaction check and clears the flag."""
    session, _ = _build_session()
    session._context_window_dirty = True

    with patch.object(
        session,
        "_run_compaction_if_needed",
        new_callable=AsyncMock,
    ) as mock_compact:
        await session._preflight_compaction_if_dirty(turn_id="turn-1")

    mock_compact.assert_awaited_once_with(turn_id="turn-1")
    assert session._context_window_dirty is False


@pytest.mark.asyncio
async def test_preflight_noop_when_not_dirty() -> None:
    """When not dirty, the pre-flight does not check compaction at all."""
    session, _ = _build_session()
    session._context_window_dirty = False

    with patch.object(
        session,
        "_run_compaction_if_needed",
        new_callable=AsyncMock,
    ) as mock_compact:
        await session._preflight_compaction_if_dirty(turn_id="turn-1")

    mock_compact.assert_not_awaited()
    assert session._context_window_dirty is False


@pytest.mark.asyncio
async def test_preflight_swallows_compaction_error_and_clears_flag() -> None:
    """A compaction failure during pre-flight never propagates or loops."""
    session, _ = _build_session()
    session._context_window_dirty = True

    with patch.object(
        session,
        "_run_compaction_if_needed",
        new_callable=AsyncMock,
        side_effect=RuntimeError("summarizer unavailable"),
    ) as mock_compact:
        # Must not raise.
        await session._preflight_compaction_if_dirty(turn_id="turn-1")

    mock_compact.assert_awaited_once()
    assert session._context_window_dirty is False


# ---------------------------------------------------------------------------
# Canonical provider-error classifier — OpenAI / Codex markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Your input exceeds the context window of this model. Please reduce your input and try again.",
        "BadRequestError(400): The request exceeds the context window of the model.",
        "YOUR INPUT EXCEEDS THE CONTEXT WINDOW.",
    ],
)
def test_provider_error_classifier_inspects_openai_context_markers(message: str) -> None:
    """OpenAI/Codex context text belongs to the canonical classifier."""
    signal = ProviderErrorClassifier.inspect(
        error=RuntimeError(message),
        provider=ProviderName.OPENAI,
    )

    assert signal.kind is ProviderErrorKind.CONTEXT_OVERFLOW


# ---------------------------------------------------------------------------
# Tests for _persist_routed_model_if_changed — dirty flag (Bug 1 fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_routed_model_sets_dirty_flag_when_model_changes() -> None:
    """When the pool switches models, _context_window_dirty becomes True.

    A pool-internal model change (e.g., gpt-5.4 → gpt-5-codex after rate-limit
    exhaustion) must mark the context-window state dirty so the preflight
    compaction check re-evaluates the threshold on the next turn.
    """
    session, mock_store = _build_session()
    # Simulate: pool now routes to a different model than what session.json shows.
    mock_store.read_metadata = AsyncMock(
        return_value=SessionHistoryMetadataDAO(
            session_id="sess-test",
            workdir=Path("/tmp"),
            model_name="gpt-5.4",
        )
    )
    # Make the session think the agent is using a different model now.
    with patch.object(
        session,
        "_resolve_active_model_name",
        return_value="gpt-5-codex",
    ):
        session._context_window_dirty = False  # reset from __init__

        await session._persist_routed_model_if_changed()

    assert session._context_window_dirty is True
    mock_store.update_metadata_model_name.assert_awaited_once_with(
        session_id="sess-test",
        model_name="gpt-5-codex",
    )


@pytest.mark.asyncio
async def test_persist_routed_model_does_not_set_dirty_flag_when_model_unchanged() -> None:
    """No dirty flag change when the pool is still using the same model.

    If the pool has not switched models, _context_window_dirty must not be
    disturbed — setting it spuriously would trigger an unnecessary compaction
    check on every turn.
    """
    session, mock_store = _build_session()
    mock_store.read_metadata = AsyncMock(
        return_value=SessionHistoryMetadataDAO(
            session_id="sess-test",
            workdir=Path("/tmp"),
            model_name="faux",  # FauxChatModel.active_model_name
        )
    )
    with patch.object(
        session,
        "_resolve_active_model_name",
        return_value="faux",
    ):
        session._context_window_dirty = False

        await session._persist_routed_model_if_changed()

    assert session._context_window_dirty is False
    mock_store.update_metadata_model_name.assert_not_called()


@pytest.mark.asyncio
async def test_persist_routed_model_no_op_when_history_disabled() -> None:
    """_persist_routed_model_if_changed exits early when history is disabled.

    The dirty flag must not be touched — there is no routed model to compare
    against when history tracking is off.
    """
    session, _ = _build_session(enable_history=False)
    session._context_window_dirty = False

    await session._persist_routed_model_if_changed()

    assert session._context_window_dirty is False


@pytest.mark.asyncio
async def test_preflight_runs_on_first_turn_not_on_second() -> None:
    """Pre-flight checks once on the dirty turn, never on steady-state turns.

    First turn (dirty from build): pre-flight + post-turn = 2 checks.
    Second turn (clean): post-turn only = 1 check. This proves the steady
    state keeps doing exactly one (post-turn) check — no double-checking.
    """
    session, _ = _build_session()
    assert session._context_window_dirty is True

    async def _fake_stream_with_retries(**kwargs):
        yield AgentStreamEventDAO(kind="run_completed", iteration=0, content="done")

    with (
        patch.object(session, "_stream_prompt_with_retries", _fake_stream_with_retries),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock) as mock_compact,
        # Isolate from model-change detection: _persist_routed_model_if_changed
        # would set _context_window_dirty=True when the mock store's metadata
        # model_name (None) doesn't match FauxChatModel's model name ("faux").
        # That behavior is correct and tested separately in
        # test_persist_routed_model_sets_dirty_flag_when_model_changes.
        patch.object(session, "_persist_routed_model_if_changed", new_callable=AsyncMock),
    ):
        async for _ in session.invoke(text="first"):
            pass
        assert mock_compact.await_count == 2  # pre-flight + post-turn
        assert session._context_window_dirty is False

        async for _ in session.invoke(text="second"):
            pass
        assert mock_compact.await_count == 3  # only the post-turn check added


# ---------------------------------------------------------------------------
# Spec 77.a.3 provider-size recovery state machine
# ---------------------------------------------------------------------------


def _decision(*, estimated_tokens: int = 123) -> PreflightDecisionDAO:
    """Build a successful preflight decision for provider-observation tests."""
    return PreflightDecisionDAO(estimated_tokens=estimated_tokens, now_seconds=1.0, wait_seconds=0)


@pytest.mark.asyncio
async def test_overflow_retries_once_when_compaction_commits() -> None:
    """A first confirmed overflow gets exactly one retry after committed compaction."""
    from src.agents.slo_agent.sessions.service import PromptAttemptPlanDAO, PromptAttemptResultDAO

    session, _ = _build_session()
    result = PromptAttemptResultDAO(
        turn_id="turn-1",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=RuntimeError("context_length_exceeded"),
        overflow_recovery_eligible=True,
    )
    with patch.object(
        session, "_run_compaction_if_needed", new_callable=AsyncMock, return_value=True
    ) as compact:
        plan = await session._derive_next_attempt_plan(
            plan=PromptAttemptPlanDAO(attempt_kind="initial", text="hello"), result=result
        )

    assert plan is not None
    assert plan.attempt_kind == "overflow_retry"
    compact.assert_awaited_once_with(turn_id="turn-1", force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("compaction_result", [False, None])
async def test_overflow_retains_original_error_when_compaction_does_not_commit(
    compaction_result: object,
) -> None:
    """False/no-op compaction produces no overflow retry plan."""
    from src.agents.slo_agent.sessions.service import PromptAttemptPlanDAO, PromptAttemptResultDAO

    session, _ = _build_session()
    error = RuntimeError("context_length_exceeded")
    result = PromptAttemptResultDAO(
        turn_id="turn-1",
        terminal_kind="run_failed",
        final_response="",
        aborted=False,
        error=error,
        overflow_recovery_eligible=True,
    )
    with patch.object(
        session, "_run_compaction_if_needed", new_callable=AsyncMock, return_value=compaction_result
    ):
        plan = await session._derive_next_attempt_plan(
            plan=PromptAttemptPlanDAO(attempt_kind="initial", text="hello"), result=result
        )

    assert plan is None
    with pytest.raises(RuntimeError, match="context_length_exceeded"):
        session._raise_if_attempt_failed(result=result)


@pytest.mark.asyncio
@pytest.mark.parametrize("visible_event", ["text_delta", "thinking_delta", "tool_result"])
async def test_visible_output_then_overflow_is_terminal_without_compaction(
    visible_event: str,
) -> None:
    """Committed stream output makes a later overflow terminal in the real session lifecycle."""
    session, _ = _build_session()
    invocation_count = 0

    async def _stream(**_kwargs):
        nonlocal invocation_count
        invocation_count += 1
        yield AgentStreamEventDAO(kind=visible_event, delta="visible", content="visible")
        raise RuntimeError("context_length_exceeded")

    with (
        patch.object(session, "_stream_prompt_with_retries", _stream),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock) as compact,
    ):
        with pytest.raises(RuntimeError, match="context_length_exceeded"):
            _ = [event async for event in session.invoke(text="hello")]

    assert invocation_count == 1
    assert not any(call.kwargs.get("force") is True for call in compact.await_args_list)


@pytest.mark.asyncio
async def test_request_body_too_large_is_terminal_through_real_session_lifecycle() -> None:
    """HTTP 413 does not trigger LLM recovery, compaction, retry, or a second provider call."""
    from src.agents.slo_agent.recovery.service import RecoveryPolicy

    session, _ = _build_session()
    invocation_count = 0
    error = RuntimeError("HTTP 413 request body too large")
    error.status_code = 413  # type: ignore[attr-defined]

    async def _stream(**_kwargs):
        nonlocal invocation_count
        invocation_count += 1
        raise error
        yield  # noqa: unreachable

    with (
        patch.object(session, "_stream_prompt_with_retries", _stream),
        patch.object(session, "_ensure_agent_ready", new_callable=AsyncMock),
        patch.object(session, "_run_compaction_if_needed", new_callable=AsyncMock) as compact,
    ):
        with pytest.raises(RuntimeError, match="413"):
            _ = [event async for event in session.invoke(text="hello")]

    decision = RecoveryPolicy.classify(exc=error, provider=ProviderName.OPENAI)
    assert invocation_count == 1
    assert decision.recovery_class.name == "FATAL"
    assert not any(call.kwargs.get("force") is True for call in compact.await_args_list)


@pytest.mark.asyncio
async def test_pool_failed_lane_observation_persists_once_and_uses_decision_estimate() -> None:
    """A drained pool record yields one redacted audit from its original decision."""
    from src.agents.providers.credit_exhaustion_policy import ProviderErrorSignalDAO
    from src.agents.providers.model_pool import RouteSwitchRecordDAO

    session, store = _build_session()
    decision = _decision(estimated_tokens=777)
    session._preflight_decisions_by_turn["turn-pool"] = decision
    record = RouteSwitchRecordDAO(
        from_model_name="gpt-5.4",
        to_model_name="gpt-5.6-terra",
        kind="RATE_LIMITED",
        error_text="rate limited",
        provider=ProviderName.OPENAI,
        signal=ProviderErrorSignalDAO(kind=ProviderErrorKind.RATE_LIMITED),
    )
    pool = MagicMock()
    pool.drain_route_switch_log.side_effect = [[record], []]
    session.agent._llm = pool

    await session._drain_and_persist_route_switches(turn_id="turn-pool")
    await session._drain_and_persist_route_switches(turn_id="turn-pool")

    appended = [call.kwargs["event"] for call in store.append_event.call_args_list]
    observations = [event for event in appended if event.kind == "provider_limit_observed"]
    switches = [event for event in appended if event.kind == "route_switched"]
    assert len(observations) == 1
    assert len(switches) == 1
    assert observations[0].payload.metadata["observation"]["estimated_request_tokens"] == 777
