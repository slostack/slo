"""Mounted quota reporting over the real session and disposable history."""

import asyncio
import html
import xml.etree.ElementTree as ET
from pathlib import Path

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.bridges.claude.test_quota_recovery import QuotaThenSuccessTransport, quota_frame
from tests.cli.test_claude_bridge import scripted_adapter_class


async def test_quota_failure_keeps_prompt_input_usable(tmp_path: Path) -> None:
    """Enter displays readable failure, then a distinct Enter succeeds in the same session."""
    transport = QuotaThenSuccessTransport(frame=quota_frame())
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="quota-pilot",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prompt = app.query_one(PromptInputComponent)
            prompt.text = "inspect once"
            await pilot.press("enter")
            async with asyncio.timeout(15):
                while not transport.closed or session.is_running:
                    await pilot.pause()
            await pilot.pause()
            screenshot = ET.fromstring(app.export_screenshot())
            painted = html.unescape("".join(screenshot.itertext())).replace("\u00a0", " ")
            assert "Claude usage limit reached" in painted
            assert "private native diagnostic" not in painted
            assert "start a new session" not in painted
            assert not prompt.disabled
            prompt.text = "continue explicitly"
            await pilot.press("enter")
            async with asyncio.timeout(15):
                while len(transport.prompts) < 2 or session.is_running:
                    await pilot.pause()
            await pilot.pause()
            screenshot = ET.fromstring(app.export_screenshot())
            painted = html.unescape("".join(screenshot.itertext())).replace("\u00a0", " ")
            assert "Hello bridge" in painted
            assert session.session_id == "quota-pilot"
            assert len(transport.prompts) == 2
        history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id=session.session_id
        )
        users = [event for event in history if event.kind == "user_message"]
        assert [event.payload.content for event in users] == ["inspect once", "continue explicitly"]
        assert users[0].turn_id != users[1].turn_id
        assert sum(event.kind == "run_failed" for event in history) == 1
        assert sum(event.kind == "run_completed" for event in history) == 1
        assert not any(event.kind == "run_retrying" for event in history)
    finally:
        async with asyncio.timeout(10):
            await session.close_agent_resources()
