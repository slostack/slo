"""Mounted local urgency through the real session, SQLite and history owners."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from textual.widgets import Static
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory
from tests.integration.test_messaging_yield import InterruptedProvider, isolated_journey_tasks
from tests.tui.test_durable_composer import _wait_until


@pytest.mark.parametrize(argnames="theme", argvalues=["slo-default", "slo-dark"])
@pytest.mark.parametrize(argnames="size", argvalues=[(60, 20), (80, 24), (120, 40)])
@pytest.mark.parametrize(argnames="key", argvalues=["ctrl+enter", "alt+u", "palette"])
@pytest.mark.parametrize(argnames="partial", argvalues=[False, True])
async def test_mounted_urgent_interrupts_provider(
    tmp_path: Path, key: str, partial: bool, theme: str, size: tuple[int, int], isolated_journey_tasks: None
) -> None:
    """An urgent editor intent joins a silent provider and paints an interruption, not abort."""
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    model = InterruptedProvider(responses=[FauxChatModel.assistant_message(content="Urgent answer")])
    model.partial = partial
    model.thinking = partial
    history = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    app = SloTUI(session=session, messaging_enabled=True)
    app.theme = theme
    try:
        async with app.run_test(size=size) as pilot:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            prompt.insert(text="Original")
            await pilot.press("enter")
            await _wait_until(predicate=model.entered.is_set)
            if partial:
                await _wait_until(predicate=lambda: bool(list(app.query(AssistantStreamBlock))))
            prompt.insert(text="Urgent")
            if key == "palette":
                command = next(c for c in app.get_system_commands(app.screen) if c.title == "Send urgently")
                await command.callback()
            else:
                await pilot.press(key)
            await _wait_until(predicate=model.resumed.is_set)
            await _wait_until(predicate=lambda: not session.is_running)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Urgent answer" in painted
            marker = next(
                widget
                for widget in app.query(Static)
                if "Response interrupted for urgent input." in str(widget.render())
            )
            marker.scroll_visible(animate=False)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Response interrupted for urgent input." in painted, painted
            assert "(aborted)" not in painted
            assert prompt.has_focus
            assert not model.release.is_set()
            if partial:
                blocks = list(app.query(AssistantStreamBlock))
                blocks[0].scroll_visible(animate=False)
                await pilot.pause()
                painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "Partial audit only" in painted
                assert blocks[0].finalized
                assert blocks[0].answer_text == "Partial audit only"
            events = await history.load_events(session_id=session_id)
            assert sum("messaging_v1" in e.payload.metadata for e in events) == 2
    finally:
        model.release.set()
        await session.close_messaging()
    database = root / session_id / "messaging.v1.sqlite3"
    assert database.resolve().is_relative_to(tmp_path.resolve())
    with sqlite3.connect(database=f"{database.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT priority,state FROM messages ORDER BY sequence").fetchall()
    assert rows == [("normal", "applied"), ("urgent", "applied")]
