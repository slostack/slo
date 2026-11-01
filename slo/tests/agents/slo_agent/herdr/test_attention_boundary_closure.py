"""Finite session submission boundaries; mounted callback ownership is separate."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO, OperatorAttentionReason
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.echo import echo_tool
from src.auth.credential_resolver import CredentialResolver
from tests.agents.slo_agent.herdr.test_attention_execution_composed import _credential, _responses


@pytest.mark.parametrize(argnames="reason", argvalues=["Run failed; review Slo", "Authentication required"])
async def test_next_submission_attention_at_real_preparation(
    tmp_path: Path, reason: OperatorAttentionReason
) -> None:
    """A fresh public invoke clears only terminal attention before real preparation."""
    publications: list[HerdrPublicationDAO] = []
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
        if reason == "Authentication required":
            session.set_operator_attention(reason=reason)
        failure = ValueError("first submission failed")
        with patch.object(session, "_prepare_run_snapshot", side_effect=failure):
            with pytest.raises(ValueError) as caught:
                _ = [event async for event in session.invoke(text="first submission")]
        assert caught.value is failure
        assert session._operator_attention is not None
        assert session._operator_attention.reason == reason
        token = session._operator_attention.token
        original_prepare = session._prepare_run_snapshot
        preparations: list[int] = []

        async def prepare() -> None:
            """Observe admission, then execute the unchanged preparation owner."""
            preparations.append(session._operation_serial)
            assert session.is_running and session._reporting_state().state == "working"
            if reason == "Authentication required":
                assert session._operator_attention is not None and session._operator_attention.token == token
            else:
                assert session._operator_attention is None
            await original_prepare()

        with (
            patch.object(session, "_prepare_run_snapshot", side_effect=prepare),
            patch.object(
                session._herdr_reporter,
                "publish",
                side_effect=lambda *, publication: publications.append(publication),
            ),
        ):
            events = [event.kind async for event in session.invoke(text="next submission")]
    assert (
        preparations == [2]
        and session._operation_serial == 2
        and events[-1] == "run_completed"
        and "tool_result" in events
    )
    assert not session._reporting_operations and not session.is_running
    assert publications[-1].snapshot.block_reason == (reason if reason == "Authentication required" else None)
    assert session.usage_snapshot().session_totals.total_tokens == 8


@pytest.mark.parametrize(argnames="auth", argvalues=[False, True])
async def test_early_cancellation_escapes_after_settlement(tmp_path: Path, auth: bool) -> None:
    """Cancellation before agent construction escapes unchanged after retiring accepted work."""
    entered, release = asyncio.Event(), asyncio.Event()
    publications: list[HerdrPublicationDAO] = []
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=_responses()), supports_explicit_caching=False
        ),
    ) as factory:
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        session._herdr_reporting_started = True
        if auth:
            session.set_operator_attention(reason="Authentication required")
        attention = session._operator_attention

        async def prepare() -> None:
            """Pause at accepted preparation before any lazy provider construction."""
            entered.set()
            await release.wait()

        async def consume() -> None:
            """Drive the public generator, not the private scope alone."""
            _ = [event async for event in session.invoke(text="cancel before agent")]

        with (
            patch.object(session, "_prepare_run_snapshot", side_effect=prepare),
            patch.object(
                session._herdr_reporter,
                "publish",
                side_effect=lambda *, publication: publications.append(publication),
            ),
        ):
            task = asyncio.create_task(coro=consume())
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert session._reporting_state().state == "working"
                task.cancel("early cancellation sentinel")
                with pytest.raises(asyncio.CancelledError, match="early cancellation sentinel"):
                    await task
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        factory.assert_not_called()
    assert task.cancelled() and session._operation_serial == 1
    assert not session._reporting_operations and not session.is_running and not session._lock.locked()
    assert session._operator_attention is attention
    assert publications[-1].snapshot.state == ("blocked" if auth else "idle")
    assert all(item.snapshot.state == "working" for item in publications[:-1])
