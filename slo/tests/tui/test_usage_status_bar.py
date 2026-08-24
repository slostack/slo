"""Tests for the usage status bar."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.usage import SessionUsageSnapshotDAO, TokenUsageTotalsDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.usage_status_bar import UsageStatusBar


class TestUsageStatusBar:
    """Rendering behavior for persistent usage status."""

    def test_renders_unknown_usage_copy(self) -> None:
        """Unknown usage renders an honest fallback string."""
        bar: UsageStatusBar = UsageStatusBar()
        snapshot: SessionUsageSnapshotDAO = SessionUsageSnapshotDAO(
            active_model_name="gpt-5.4",
            active_reasoning_level="high",
            output_cap_tokens=8192,
        )

        rendered: str = bar._render_snapshot(snapshot=snapshot)

        assert "usage unavailable" in rendered
        assert "out 8192" in rendered

    def test_renders_codex_model_name(self) -> None:
        """Codex model names render cleanly in the usage bar."""
        bar: UsageStatusBar = UsageStatusBar()
        snapshot: SessionUsageSnapshotDAO = SessionUsageSnapshotDAO(
            active_model_name="gpt-5-codex",
            active_reasoning_level="xhigh",
            output_cap_tokens=8192,
        )

        rendered: str = bar._render_snapshot(snapshot=snapshot)

        assert "gpt-5-codex" in rendered
        assert "xhigh" in rendered
        assert "out 8192" in rendered

    @pytest.mark.asyncio
    async def test_app_mount_renders_usage_status_bar(self) -> None:
        """The app mounts a persistent usage status bar above the footer."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            bars: list[UsageStatusBar] = list(app.query(selector=UsageStatusBar))

            assert len(bars) == 1
            assert session.active_model_name in str(bars[0].content)

    @pytest.mark.asyncio
    async def test_completed_prompt_refreshes_usage_status_bar(self) -> None:
        """A completed prompt refreshes the persistent usage widget."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(
                llm=FauxChatModel(
                    responses=[
                        AIMessage(
                            content="done",
                            usage_metadata={
                                "input_tokens": 12,
                                "output_tokens": 4,
                                "total_tokens": 16,
                            },
                        )
                    ]
                )
            ),
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._input is not None
            app._input.load_text("hello")
            await pilot.press("enter")
            await pilot.pause()
            while app._in_flight_task is not None:
                await pilot.pause()

            bars: list[UsageStatusBar] = list(app.query(selector=UsageStatusBar))
            assert len(bars) == 1
            assert "turn 16 tok" in str(bars[0].content)
            assert "session 16 tok" in str(bars[0].content)


class TestUsageStatusBarCacheRendering:
    """Cache token counts appear in the usage bar when present."""

    def test_cache_fields_render_when_present(self) -> None:
        """Non-None cache counts produce ``cache write N · cache read N`` segments."""
        bar: UsageStatusBar = UsageStatusBar()
        snapshot: SessionUsageSnapshotDAO = SessionUsageSnapshotDAO(
            active_model_name="claude-sonnet-4-6",
            active_reasoning_level="off",
            usage_available=True,
            session_totals=TokenUsageTotalsDAO(
                total_tokens=120,
                cache_creation_input_tokens=6000,
                cache_read_input_tokens=600,
            ),
            latest_turn=TokenUsageTotalsDAO(total_tokens=120),
        )

        rendered: str = bar._render_snapshot(snapshot=snapshot)

        assert "cache write 6000" in rendered
        assert "cache read 600" in rendered

    def test_cache_fields_absent_when_none(self) -> None:
        """``None`` cache counts do not add cache segments to the usage bar."""
        bar: UsageStatusBar = UsageStatusBar()
        snapshot: SessionUsageSnapshotDAO = SessionUsageSnapshotDAO(
            active_model_name="gpt-5.4",
            active_reasoning_level="off",
            usage_available=True,
            session_totals=TokenUsageTotalsDAO(total_tokens=50),
            latest_turn=TokenUsageTotalsDAO(total_tokens=50),
        )

        rendered: str = bar._render_snapshot(snapshot=snapshot)

        assert "cache write" not in rendered
        assert "cache read" not in rendered
