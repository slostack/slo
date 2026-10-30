"""Editor requests are drained by the existing session replacement transaction."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from src.agents.base import LLMBuildResult
from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.editor_launcher import EditorLauncher
from tests.tui.test_code_command import EditorLookup, RecordingEditorTerminal, transcript_lines
from tests.tui.test_code_lifetime import local_file
from tests.tui._scroll_settle import pump_until


async def test_new_session_drains_captured_editor_and_suppresses_late_notice(tmp_path: Path) -> None:
    """Keyboard /new cannot redirect an old editor request or leave its worker behind."""
    local_file(root=tmp_path, name="one.py")
    terminal = RecordingEditorTerminal(hold=True)
    with patch(
        target="src.agents.slo_agent.graph.LLMFactory.create",
        return_value=LLMBuildResult(
            llm=FauxChatModel(responses=[]),
            supports_explicit_caching=False,
        ),
    ):
        old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"))
        app = SloTUI(
            session=old,
            editor_launcher=EditorLauncher(
                terminal=terminal,
                executable_lookup=EditorLookup(),
            ),
        )
        async with app.run_test() as pilot:
            prompt = app.query_one(PromptInput)
            prompt.load_text("/code one.py")
            await pilot.press("enter")
            await asyncio.wait_for(fut=terminal.entered.wait(), timeout=2)
            prompt.load_text("/new")
            await pilot.press("enter")
            await pump_until(pilot=pilot, predicate=lambda: app._session is not old)
            assert app._session is not old
            assert terminal.finished.is_set()
            assert not app._editor_launch_tasks
            assert not any("readiness" in text for text, _ in transcript_lines(app=app))
            prompt.load_text("/cwd")
            await pilot.press("enter")
            await pump_until(
                pilot=pilot, predicate=lambda: any(str(tmp_path) in t for t, _ in transcript_lines(app=app))
            )
            assert any(str(tmp_path) in t for t, _ in transcript_lines(app=app))
