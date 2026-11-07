"""Urgent fallback and local routing preserve editor intent and normal key behavior."""

from pathlib import Path

import pytest

from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui.test_prompt_component_protocol import build_session


@pytest.mark.parametrize(argnames="key", argvalues=["ctrl+enter", "alt+u", "palette"])
async def test_unsupported_urgent_keeps_draft_and_slash_is_local(tmp_path: Path, key: str) -> None:
    """Legacy sessions refuse urgent ordinary text without downgrading; slash still works."""
    session = build_session(tmp_path=tmp_path)
    app = SloTUI(session=session)
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(PromptInputComponent)
        prompt.insert(text="keep me")
        if key == "palette":
            command = next(c for c in app.get_system_commands(app.screen) if c.title == "Send urgently")
            await command.callback()
        else:
            await pilot.press(key)
        await pilot.pause()
        assert prompt.text == "keep me"
        assert not session.is_running
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Urgent input is unsupported" in painted
        prompt.load_text("/help")
        await pilot.press("ctrl+enter")
        await pilot.pause()
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Ctrl+Enter / Alt+U: Send urgently" in painted
        assert prompt.text == ""
        assert session.history_store is not None
        assert await session.history_store.load_events(session_id=session.session_id) == []


async def test_modified_newlines_and_tab_unchanged(tmp_path: Path) -> None:
    """Shift/Meta enter remain newline and Tab accepts the existing slash completion."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one(PromptInputComponent)
        await pilot.press("a", "shift+enter", "b", "meta+enter", "c")
        assert prompt.text == "a\nb\nc"
        prompt.load_text("/he")
        await pilot.pause()
        await pilot.press("tab")
        assert prompt.text == "/help"
        prompt.load_text("")
        await pilot.press("alt+u")
        await pilot.pause()
        assert prompt.text == ""
