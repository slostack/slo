"""Tests for transcript follow-mode behavior."""

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
    """Build a session suitable for scroll-follow tests.

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


async def _fill_transcript(*, app: SloTUI, pilot, line_count: int = 40) -> None:
    """Write enough transcript lines to create scroll headroom.

    Args:
        app (SloTUI): App under test.
        pilot: Textual pilot.
        line_count (int, optional): Number of lines to append. Defaults to 40.
    """
    for index in range(line_count):
        app.query_one(ChatTranscript).write_transcript_line(content=f"line {index}", classes="tool-result")
    await pilot.pause()


class TestTranscriptFollowMode:
    """Viewport-follow behavior for flat lines and stream events."""

    @pytest.mark.asyncio
    async def test_flat_transcript_write_keeps_follow_mode_when_viewport_was_at_bottom(self) -> None:
        """A flat transcript write keeps the viewport pinned when already at bottom."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await _fill_transcript(app=app, pilot=pilot)

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
    async def test_flat_transcript_write_does_not_jump_when_user_scrolled_up(self) -> None:
        """A flat transcript write preserves scroll position when reading history."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await _fill_transcript(app=app, pilot=pilot)

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

    @pytest.mark.asyncio
    async def test_stream_event_does_not_jump_when_user_scrolled_up(self) -> None:
        """Live stream events respect the user's scroll position."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await _fill_transcript(app=app, pilot=pilot)

            assert app.query_one(ChatTranscript)._transcript_scroll is not None
            app.query_one(ChatTranscript)._transcript_scroll.scroll_to(y=0, animate=False)
            await pilot.pause()
            previous_scroll_y: float = app.query_one(ChatTranscript)._transcript_scroll.scroll_y

            await app._render_event(
                AgentStreamEventDAO(kind="text_delta", delta="hello", iteration=0),
            )
            await pilot.pause()

            assert app.query_one(ChatTranscript)._transcript_scroll.scroll_y == previous_scroll_y
            assert (
                app.query_one(ChatTranscript)._transcript_scroll.scroll_y
                < app.query_one(ChatTranscript)._transcript_scroll.max_scroll_y
            )

    @pytest.mark.asyncio
    async def test_stream_event_keeps_follow_mode_when_viewport_was_at_bottom(self) -> None:
        """Live stream events keep the viewport pinned when already following."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await _fill_transcript(app=app, pilot=pilot)

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
                AgentStreamEventDAO(kind="text_delta", delta="hello", iteration=0),
            )
            scroll = app.query_one(ChatTranscript)._transcript_scroll
            await pump_until(
                pilot=pilot,
                predicate=lambda: (scroll.max_scroll_y - scroll.scroll_y) <= 1.0,
            )

            assert (scroll.max_scroll_y - scroll.scroll_y) <= 1.0
