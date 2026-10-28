"""Tests for orchestrator-pane scroll-follow behavior (28.t.1).

The per-pane ``_PaneHost`` adapter has been removed — the orchestrator
transcript is the only transcript. These tests verify that the existing
scroll-follow policy on the orchestrator pane is intact after the
multi-agent simplification.
"""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from tests.tui._scroll_settle import pump_until


def _build_session() -> SloAgentSession:
    """Build a minimal faux-backed session.

    Returns:
        SloAgentSession: Session for scroll-follow tests.
    """
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="ok")]),
        ),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestOrchestratorScrollFollow:
    """Orchestrator-pane scroll-follow behavior is unchanged after the redesign."""

    @pytest.mark.asyncio
    async def test_stream_event_keeps_follow_mode_when_at_bottom(self) -> None:
        """Live events keep the main viewport pinned when already at the bottom."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for idx in range(30):
                app.query_one(ChatTranscript).write_transcript_line(
                    content=f"line {idx}", classes="tool-result"
                )
            await pilot.pause()
            assert app.query_one(ChatTranscript)._transcript_scroll is not None
            app.query_one(ChatTranscript)._transcript_scroll.scroll_end(animate=False)
            # Wait for the scroll to actually land before dispatching. _render_event
            # snapshots _transcript_is_at_bottom() at dispatch time; if scroll_end has
            # not settled, the app correctly preserves position and no later pumping
            # can undo that decision. A bare pause() was the flake.
            await pump_until(
                pilot=pilot,
                predicate=lambda: app.query_one(ChatTranscript)._capture_follow_snapshot().was_following,
            )
            assert app.query_one(ChatTranscript)._capture_follow_snapshot().was_following

            await app._render_event(
                AgentStreamEventDAO(kind="text_delta", delta="new content", iteration=0),
            )
            scroll = app.query_one(ChatTranscript)._transcript_scroll
            await pump_until(
                pilot=pilot,
                predicate=lambda: (scroll.max_scroll_y - scroll.scroll_y) <= 1.0,
            )

            assert (scroll.max_scroll_y - scroll.scroll_y) <= 1.0

    @pytest.mark.asyncio
    async def test_stream_event_does_not_jump_when_scrolled_up(self) -> None:
        """Live events preserve scroll position when the user is reading history."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for idx in range(30):
                app.query_one(ChatTranscript).write_transcript_line(
                    content=f"line {idx}", classes="tool-result"
                )
            await pilot.pause()
            assert app.query_one(ChatTranscript)._transcript_scroll is not None
            app.query_one(ChatTranscript)._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()
            anchored_y: float = app.query_one(ChatTranscript)._transcript_scroll.scroll_y

            await app._render_event(
                AgentStreamEventDAO(kind="text_delta", delta="new content", iteration=0),
            )
            await pilot.pause()

            assert app.query_one(ChatTranscript)._transcript_scroll.scroll_y == anchored_y

    @pytest.mark.asyncio
    async def test_flat_line_write_keeps_follow_mode_at_bottom(self) -> None:
        """``_write_adapter_line`` auto-scrolls when viewport was at the bottom."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for idx in range(40):
                app.query_one(ChatTranscript).write_transcript_line(
                    content=f"line {idx}", classes="tool-result"
                )
            await pilot.pause()
            assert app.query_one(ChatTranscript)._transcript_scroll is not None
            app.query_one(ChatTranscript)._transcript_scroll.scroll_end(animate=False)
            await pilot.pause()

            app.query_one(ChatTranscript).write_transcript_line(content="tail", classes="tool-result")
            await pilot.pause()

            assert (
                app.query_one(ChatTranscript)._transcript_scroll.max_scroll_y
                - app.query_one(ChatTranscript)._transcript_scroll.scroll_y
            ) <= 1.0

    @pytest.mark.asyncio
    async def test_flat_line_write_stays_anchored_when_scrolled_up(self) -> None:
        """``_write_adapter_line`` preserves position when viewport is anchored."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for idx in range(40):
                app.query_one(ChatTranscript).write_transcript_line(
                    content=f"line {idx}", classes="tool-result"
                )
            await pilot.pause()
            assert app.query_one(ChatTranscript)._transcript_scroll is not None
            app.query_one(ChatTranscript)._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()
            previous_scroll_y: float = app.query_one(ChatTranscript)._transcript_scroll.scroll_y

            app.query_one(ChatTranscript).write_transcript_line(content="tail", classes="tool-result")
            await pilot.pause()

            assert app.query_one(ChatTranscript)._transcript_scroll.scroll_y == previous_scroll_y
            assert (
                app.query_one(ChatTranscript)._transcript_scroll.scroll_y
                < app.query_one(ChatTranscript)._transcript_scroll.max_scroll_y
            )
