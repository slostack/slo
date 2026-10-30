"""Mounted Escape journeys through real cancellation and disposable history."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from tests.tui._scroll_settle import pump_until
from tests.tui.test_code_command import transcript_lines


@pytest.mark.parametrize(argnames="suggestions", argvalues=[False, True])
async def test_two_escapes_cancel_real_run_and_persist_aborted_history(
    tmp_path: Path, suggestions: bool
) -> None:
    """Pilot keys reach /abort and its escalation, not a patched app cancellation call."""
    entered = asyncio.Event()

    @tool
    async def wait_for_cancel() -> str:
        """Hold a real graph tool until the run is cancelled."""
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    history = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session = SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(
                responses=[
                    AIMessage(content="", tool_calls=[{"name": "wait_for_cancel", "args": {}, "id": "hold"}])
                ]
            ),
            cwd=str(tmp_path),
            tools=[wait_for_cancel],
        ),
        workdir=tmp_path,
        session_id=str(uuid4()),
        history_store=history,
        enable_history=True,
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        prompt.load_text("hold this run")
        await pilot.press("enter")
        await pump_until(pilot=pilot, predicate=entered.is_set)
        if suggestions:
            prompt.load_text("/he")
            await pump_until(pilot=pilot, predicate=lambda: app._slash_suggestion_state.visible)
        await pilot.press("escape")
        await pilot.pause()
        assert session.is_running
        assert not app._slash_suggestion_state.visible
        assert not any("(aborting" in text for text, _ in transcript_lines(app=app))
        await pilot.press("escape")
        await pump_until(pilot=pilot, predicate=lambda: app._in_flight_task is None, max_cycles=100)
        lines = transcript_lines(app=app)
        assert sum("(aborting" in text for text, _ in lines) == 1
        assert app._in_flight_task is None
        assert not session.is_running
    events = await history.load_events(session_id=session.session_id)
    assert [event.kind for event in events].count("run_aborted") == 1
    assert not any(event.kind == "run_completed" for event in events)
