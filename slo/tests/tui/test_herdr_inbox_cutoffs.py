"""Shutdown admission regression: a late ordinary prompt inserts no channel row."""

from pathlib import Path
from unittest.mock import patch


from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI


async def test_prompt_registration_shutdown_refuses_channel_send(tmp_path: Path) -> None:
    """Public shutdown refuses a late ordinary prompt: no queue row is inserted."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="must not execute")]),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.on_unmount()
            assert app._app_closing
            await app._submit_or_queue_prompt(text="late prompt")
            adapter = app.channel_adapter
            assert adapter is not None
            assert await adapter.queued() == []
