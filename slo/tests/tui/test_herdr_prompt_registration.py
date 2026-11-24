"""Mounted prompt-admission cutoff regressions with an offline real session."""

import asyncio
from src.tui.components.chat_transcript.component import ChatTranscriptComponent

from pathlib import Path
from unittest.mock import patch
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent


@pytest.fixture
async def mounted_app(tmp_path: Path) -> AsyncIterator[SloTUI]:
    """Mount a real session with only the model boundary replaced by Faux."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(
                responses=[AIMessage(content="completed"), AIMessage(content="successor completed")]
            ),
            supports_explicit_caching=False,
        ),
    ):
        session = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")
        )
        app = SloTUI(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            yield app
            if app._in_flight_task is not None:
                await asyncio.wait_for(app._in_flight_task, timeout=5)


async def test_ordinary_entry_closed(tmp_path: Path) -> None:
    """A closed mounted app neither echoes nor records an ordinary submission."""
    with patch(
        "src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
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
            assert app._input is not None
            with (
                patch.object(app._chat_transcript, "echo_user", wraps=app._chat_transcript.echo_user) as echo,
                patch.object(
                    app._input._prompt_history, "record", wraps=app._input._prompt_history.record
                ) as record,
            ):
                await app.on_prompt_input_component_submitted(
                    event=PromptInputComponent.Submitted(text="late")
                )
                assert app._in_flight_task is None
                echo.assert_not_called()
                record.assert_not_called()


@pytest.mark.parametrize("entry", ["submitted_slash", "direct_slash"])
async def test_prompt_registration_shutdown_slash(mounted_app: SloTUI, entry: str) -> None:
    """Slash routing remains available and does not register an ordinary run."""
    app = mounted_app
    await app.on_unmount()
    with patch.object(app, "_run_prompt", wraps=app._run_prompt) as run:
        if entry == "direct_slash":
            await app._dispatch_slash_command(line="/help")
        else:
            await app.on_prompt_input_component_submitted(event=PromptInputComponent.Submitted(text="/help"))
        run.assert_not_called()
    assert app._input is not None
    assert app._input._prompt_history._entries == []
    assert app._in_flight_task is None
