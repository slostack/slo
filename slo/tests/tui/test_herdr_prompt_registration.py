"""Mounted prompt-admission cutoff regressions with an offline real session."""

import asyncio
import ast
import inspect
import textwrap
from src.tui.components.chat_transcript.component import ChatTranscriptComponent

from pathlib import Path
from unittest.mock import patch
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent


def test_prompt_registration_shutdown_atomic_commit() -> None:
    """The final check has only create/assign and return, with no suspension/hook."""
    module = ast.parse(textwrap.dedent(inspect.getsource(SloTUI._register_prompt_task)))
    method = module.body[0]
    assert isinstance(method, ast.FunctionDef)
    _, guard, assignment, result = method.body
    assert isinstance(guard, ast.If)
    assert ast.unparse(guard.test) == "self._app_closing or self._session_transitioning"
    assert ast.unparse(guard.body[0]) == "return False"
    assert isinstance(assignment, ast.Assign)
    assert ast.unparse(assignment.targets[0]) == "self._in_flight_task"
    assert ast.unparse(assignment.value) == "asyncio.create_task(coro=self._run_prompt(text=text))"
    assert ast.unparse(result) == "return True"
    assert not any(isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom)) for node in ast.walk(method))


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


@pytest.mark.parametrize("entry", ["inbox", "direct"])
@pytest.mark.parametrize("closing", [False, True])
async def test_prompt_registration_shutdown_entry_matrix(
    mounted_app: SloTUI, entry: str, closing: bool
) -> None:
    """All registration callers share refusal without constructing a run coroutine."""
    app = mounted_app
    if closing:
        await app.on_unmount()
    with patch.object(app, "_run_prompt", wraps=app._run_prompt) as run:
        async with app._prompt_submission_lock:
            if entry == "direct":
                assert app._register_prompt_task(text="selected") is (not closing)
            else:
                message = SessionInboxMessageDAO(
                    session_id=app._session.session_id,
                    schedule_id="schedule",
                    run_id="run",
                    kind="system_notice",
                    delivery_mode="chat_turn",
                    text="selected",
                )
                assert await app._start_inbox_chat_turn(message=message) is (not closing)
            task = app._in_flight_task
            assert run.call_count == int(not closing)
        if task is not None:
            await asyncio.wait_for(task, timeout=5)
        assert app._input is not None
        assert app._input._prompt_history._entries == []


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
