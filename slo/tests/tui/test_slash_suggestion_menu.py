"""Tests for the slash suggestion menu renderer."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.slash_suggestion_engine import SlashSuggestionRowDAO, SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu


def _build_session(*, responses: list[AIMessage]) -> SloAgentSession:
    """Build a ``SloAgentSession`` driven by a Faux LLM.

    Args:
        responses (list[AIMessage]): Scripted Faux responses.

    Returns:
        SloAgentSession: A session ready to drive a ``SloTUI``.
    """
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=responses))
    return SloAgentSession(
        agent=agent,
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestSlashSuggestionMenuNoOpGuard:
    """update_state must not touch the DOM when state is unchanged (spec 59, Bug #1)."""

    def test_equal_state_is_noop(self) -> None:
        """A second update with a value-equal state performs no re-render.

        The initial ``_state`` is ``SlashSuggestionStateDAO(visible=False)``,
        so a call with an equal state returns immediately and leaves ``_state``
        unchanged — verified by identity comparison against the original.
        """
        menu = SlashSuggestionMenu()
        original_state = menu._state
        # The initial state is already visible=False; calling with an equal
        # value must hit the guard and leave _state at the original object.
        menu.update_state(state=SlashSuggestionStateDAO(visible=False))
        assert menu._state is original_state

    @pytest.mark.asyncio
    async def test_changed_state_renders(self) -> None:
        """A value-different state advances ``_state`` and writes the DOM.

        The menu is mounted inside a real pilot so ``query_one`` resolves, then
        the production ``update_state`` is called with a visible state that
        differs from the seeded ``visible=False`` default. This drives the
        changed branch (``slash_suggestion_menu.py`` lines 65-67): ``_state`` is
        advanced to the new value and the ``-hidden`` class is cleared. Unlike
        the prior version, no production guard logic is reimplemented in the
        test body — the real method under test is invoked directly.
        """
        app: SloTUI = SloTUI(session=_build_session(responses=[AIMessage(content="ok")]))
        async with app.run_test() as pilot:
            await pilot.pause()
            menu: SlashSuggestionMenu | None = app._suggestion_menu
            assert menu is not None
            visible: SlashSuggestionStateDAO = SlashSuggestionStateDAO(
                visible=True,
                rows=[SlashSuggestionRowDAO(insert_text="/help", label="/help")],
                highlighted_index=0,
            )
            menu.update_state(state=visible)
            assert menu._state == visible
            assert not menu.has_class("-hidden")


class TestSlashSuggestionMenu:
    """Visible rendering guarantees for the slash suggestion menu."""

    def test_render_lines_includes_all_visible_rows(self) -> None:
        """The menu renders every suggestion row instead of truncating after eight."""
        rows: list[SlashSuggestionRowDAO] = [
            SlashSuggestionRowDAO(insert_text=f"/cmd{i}", label=f"/cmd{i}")
            for i in range(11)
        ]
        state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(
            visible=True,
            rows=rows,
            highlighted_index=0,
        )

        rendered: str = SlashSuggestionMenu._render_lines(state=state)

        assert "/cmd0" in rendered
        assert "/cmd10" in rendered
        assert rendered.count("/cmd") == 11
