"""Bounded main-input Escape reset decisions driven by mounted keys."""

from pathlib import Path

import pytest
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input

from src.tui.app import PromptInput, SloTUI
from tests.tui.test_code_command import transcript_lines
from tests.tui.test_path_suggestions_app import build_path_session


class EscapeModal(ModalScreen[None]):
    """Local modal consuming Escape without involving the underlying prompt."""

    BINDINGS = [("escape", "dismiss", "Dismiss")]

    def compose(self) -> ComposeResult:
        """Mount a focusable modal input."""
        yield Input()


@pytest.mark.parametrize(
    argnames="transition",
    argvalues=[
        "left",
        "tab",
        "up",
        "enter",
        "x",
        "edit",
        "cursor",
        "expiry",
        "focus",
        "modal",
        "command",
        "session",
    ],
)
async def test_intervening_input_or_context_requires_two_fresh_escapes(
    tmp_path: Path, transition: str
) -> None:
    """Consumed keys, programmatic input, focus and modal changes revoke the pair."""
    app = SloTUI(session=build_path_session(workdir=tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one(PromptInput)
        await pilot.press("escape")
        if transition == "session":
            from src.agents.slo_agent.herdr.dao import HerdrReporterCloseOutcomeDAO

            app._adopt_replacement_session(
                old_session=app._session,
                candidate=build_path_session(workdir=tmp_path),
                outcome=HerdrReporterCloseOutcomeDAO(replacement="safe", resources="drained"),
            )
        elif transition == "command":
            await app._dispatch_slash_command(line="/cwd")
        elif transition == "edit":
            prompt.load_text("changed")
        elif transition == "cursor":
            prompt.load_text("abc")
            await pilot.pause()
            await pilot.press("escape")
            prompt.move_cursor(location=(0, 1))
        elif transition == "expiry":
            await pilot.pause(delay=0.6)
        elif transition == "focus":
            app.set_focus(None)
            await pilot.pause()
            prompt.focus()
        elif transition == "modal":
            await app.push_screen(EscapeModal())
            await pilot.press("escape")
        else:
            await pilot.press(transition)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not any("(aborting" in text for text, _ in transcript_lines(app=app))
        await pilot.press("escape")
        await pilot.pause()
        assert sum("(aborting" in text for text, _ in transcript_lines(app=app)) == 1
