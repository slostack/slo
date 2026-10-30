"""Authentication attention races during an actual lazy Faux/tool submission."""

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.herdr.dao import HerdrPublicationDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools.echo import EchoTool, echo_tool
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.credential_resolver import CredentialResolver


@pytest.mark.parametrize("completion", ["matching", "stale", "cancel"])
async def test_auth_completion_during_tool_keeps_working(tmp_path: Path, completion: str) -> None:
    """Auth completion changes attention, never the unrelated submission lifetime."""
    model = FauxChatModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"name": "echo", "args": {"text": "Approval required"}, "id": "one"}]
            ),
            AIMessage(
                content="done", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
            ),
        ]
    )
    credential = CredentialDAO(
        provider=ProviderName.OPENAI, auth_type=AuthType.API_KEY, access_token="synthetic"
    )
    publications: list[HerdrPublicationDAO] = []
    with (
        patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=model, supports_explicit_caching=False),
        ),
        patch.object(CredentialResolver, "resolve", return_value=credential),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", extra_tools=[echo_tool])
        )
        token = session.set_operator_attention(reason="Authentication required")
        session._herdr_reporting_started = True

        async def echo(*, text: str) -> str:
            """Complete the captured auth token at the real tool execution boundary."""
            assert session.is_running and len(session._reporting_operations) == 1
            if completion == "stale":
                session.set_operator_attention(reason="Model preparation required")
            if completion != "cancel":
                session.clear_operator_attention(token=token)
            assert session._reporting_state().state == "working"
            return text

        def publish(*, publication: HerdrPublicationDAO) -> None:
            """Capture projected facts at the existing reporter seam."""
            publications.append(publication)

        with (
            patch.object(EchoTool, "invoke", side_effect=echo),
            patch.object(session._herdr_reporter, "publish", side_effect=publish),
        ):
            events = [event async for event in session.invoke(text="echo then finish")]
    assert any(event.kind == "tool_result" for event in events)
    assert any(event.kind == "run_completed" for event in events)
    assert session.usage_snapshot().session_totals.total_tokens == 10
    assert session._operation_serial == 1 and not session._reporting_operations
    assert all(item.snapshot.state == "working" for item in publications[:-1])
    expected = {"matching": None, "stale": "Model preparation required", "cancel": "Authentication required"}[
        completion
    ]
    assert publications[-1].snapshot.block_reason == expected
    assert publications[-1].snapshot.state == ("idle" if expected is None else "blocked")
