"""Integration tests for live slash suggestions in ``SloTUI``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI, PromptInput


def _build_session() -> SloAgentSession:
    """Build a session suitable for slash-suggestion tests.

    Returns:
        SloAgentSession: Session driven by a faux assistant response.
    """
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]),
        ),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _require_prompt_input(*, app: SloTUI) -> PromptInput:
    """Return the mounted prompt input.

    Args:
        app (SloTUI): App under test.

    Returns:
        PromptInput: Mounted prompt input widget.
    """
    assert app._input is not None
    return app._input


class TestSloTUISlashSuggestions:
    """Prompt-level slash suggestion integration."""

    @pytest.mark.asyncio
    async def test_typing_slash_opens_command_menu(self) -> None:
        """A bare slash opens the live command suggestion menu."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text("/")
            await pilot.pause()

            assert app._slash_suggestion_state.visible is True
            assert app._slash_suggestion_state.rows[0].label == "/help"
            assert any(row.label == "/rename" for row in app._slash_suggestion_state.rows)

    @pytest.mark.asyncio
    async def test_bare_slash_menu_renders_all_registered_commands(self) -> None:
        """The visible menu surface includes every registered slash command."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text("/")
            await pilot.pause()

            assert app._suggestion_menu is not None
            rendered_text: str = app._suggestion_menu.query_one(".slash-suggestion-lines").renderable
            assert "/help" in rendered_text
            assert "/reasoning" in rendered_text
            assert "/new" in rendered_text
            assert "/rename" in rendered_text

    @pytest.mark.asyncio
    async def test_tab_accepts_highlighted_command(self) -> None:
        """Tab accepts the highlighted slash command."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text("/mo")
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()

            assert prompt_input.text == "/model "
            assert app._slash_suggestion_state.visible is True

    @pytest.mark.asyncio
    async def test_escape_dismisses_visible_suggestions(self) -> None:
        """Escape closes the suggestion menu without mutating the buffer."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            prompt_input: PromptInput = _require_prompt_input(app=app)

            prompt_input.load_text("/")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            assert prompt_input.text == "/"
            assert app._slash_suggestion_state.visible is False

    @pytest.mark.asyncio
    async def test_model_token_pivots_into_model_rows(self) -> None:
        """A completed ``/model`` token pivots into model suggestions."""
        app: SloTUI = SloTUI(session=_build_session())

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)

                prompt_input.load_text("/model ")
                await pilot.pause()

                assert app._slash_suggestion_state.visible is True
                assert all(not row.label.startswith("/") for row in app._slash_suggestion_state.rows)

    @pytest.mark.asyncio
    async def test_model_menu_renders_all_codex_variants(self) -> None:
        """The visible ``/model`` autocomplete menu includes every Codex variant."""
        app: SloTUI = SloTUI(session=_build_session())

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)

                prompt_input.load_text("/model ")
                await pilot.pause()

                assert app._suggestion_menu is not None
                rendered_text: str = app._suggestion_menu.query_one(
                    ".slash-suggestion-lines"
                ).renderable
                assert "gpt-5-codex" in rendered_text
                assert "gpt-5.3-codex" in rendered_text
                assert "gpt-5.2-codex" in rendered_text
                assert "gpt-5.3-codex-spark" in rendered_text

    @pytest.mark.asyncio
    async def test_down_moves_highlight_within_model_rows(self) -> None:
        """Down arrow retargets the highlighted model row."""
        app: SloTUI = SloTUI(session=_build_session())

        with patch(
            "src.tui.model_catalog.CredentialResolver.resolve",
            side_effect=lambda *, provider: object(),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInput = _require_prompt_input(app=app)

                prompt_input.load_text("/model ")
                await pilot.pause()
                starting_index: int = app._slash_suggestion_state.highlighted_index
                await pilot.press("down")
                await pilot.pause()

                assert app._slash_suggestion_state.highlighted_index != starting_index
