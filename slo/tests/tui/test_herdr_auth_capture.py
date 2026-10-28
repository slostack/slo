"""Captured auth dismissal must not act on a replacement session."""

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.tui.app import SloTUI


@pytest.mark.parametrize("cutoff", ["replacement", "unmount"])
@pytest.mark.parametrize("success", [False, True])
async def test_captured_auth_callback_refuses_displaced_owner(
    tmp_path: Path, cutoff: str, success: bool
) -> None:
    """Invoke the actual registered callback after public replacement or close."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "push_screen") as push:
                app._push_auth_modal()
            callback = push.call_args.kwargs["callback"]
            if cutoff == "replacement":
                await app._start_new_session(requested_name=None)
                assert app._session is not session
            else:
                await app.on_unmount()
            selected = app._session
            token = selected.set_operator_attention(reason="Run failed; review Slo")
            value = (
                CredentialDAO(
                    provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
                )
                if success
                else None
            )
            with (
                patch("src.tui.app.ModelSuggestionProjection.refresh_authentication") as projection,
                patch.object(app, "_start_session_preparation") as preparation,
                patch.object(selected, "switch_model") as switch,
                patch.object(selected, "clear_operator_attention") as clear,
            ):
                callback(value)
                projection.assert_not_called()
                preparation.assert_not_called()
                switch.assert_not_called()
                clear.assert_not_called()
                assert selected._operator_attention is not None
                assert selected._operator_attention.token == token


@pytest.mark.parametrize("outcome", ["success", "cancel_missing", "cancel_present", "newer"])
async def test_auth_attention_clears_only_matching_request(tmp_path: Path, outcome: str) -> None:
    """Cancellation preserves missing credentials; completion cannot clear newer attention."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="offline")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path))
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            with patch.object(app, "push_screen") as push:
                app._push_auth_modal()
            attention = session._operator_attention
            assert attention is not None and attention.reason == "Authentication required"
            if outcome == "newer":
                session.set_operator_attention(reason="Run failed; review Slo")
            expected = session._operator_attention
            value = (
                CredentialDAO(
                    provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
                )
                if outcome in {"success", "newer"}
                else None
            )
            with patch.object(
                app, "_has_credential_for_active_model", return_value=outcome == "cancel_present"
            ):
                push.call_args.kwargs["callback"](value)
            if outcome in {"success", "cancel_present"}:
                assert session._operator_attention is None
            else:
                assert session._operator_attention is expected
