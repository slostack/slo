"""Tests for retry-status and compaction-status rendering in the TUI."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.thinking_spinner import ThinkingSpinner
from src.tui.widgets.usage_status_bar import UsageStatusBar


def _make_session() -> SloAgentSession:
    """Build a minimal session for TUI spinner tests."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestRetryingStatusRendering:
    """Spinner and status-bar handling for transient retrying events."""

    @pytest.mark.asyncio
    async def test_run_retrying_overrides_spinner_and_refreshes_status_bar(self) -> None:
        """A retrying event updates the fixed spinner and leaves the usage bar mounted."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(
                AgentStreamEventDAO(
                    kind="run_retrying",
                    content="Rate limited by gpt-5.4; retrying in 1s (attempt 2/3).",
                    metadata={"wait_seconds": 1, "attempt": 1},
                )
            )
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            bars: list[UsageStatusBar] = list(app.query(selector=UsageStatusBar))
            assert len(spinners) == 1
            assert len(bars) == 1
            assert "retrying in 1s" in str(spinners[0]._text.content)


class TestCompactionStatusRendering:
    """Spinner handling for compaction lifecycle events (spec 46.a.3)."""

    @pytest.mark.asyncio
    async def test_compaction_started_updates_spinner_text(self) -> None:
        """compaction_started event sets the spinner to the compacting message."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(AgentStreamEventDAO(kind="compaction_started"))
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            assert len(spinners) == 1
            assert "Compacting" in str(spinners[0]._text.content)

    @pytest.mark.asyncio
    async def test_compaction_completed_updates_spinner_text(self) -> None:
        """compaction_completed event sets the spinner to the complete message."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(AgentStreamEventDAO(kind="compaction_completed"))
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            assert len(spinners) == 1
            assert "complete" in str(spinners[0]._text.content).lower()

    @pytest.mark.asyncio
    async def test_compaction_retrying_updates_spinner_text(self) -> None:
        """compaction_retrying event sets the spinner to the retrying message."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(AgentStreamEventDAO(kind="compaction_retrying"))
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            assert len(spinners) == 1
            assert "Retrying" in str(spinners[0]._text.content)

    @pytest.mark.asyncio
    async def test_compaction_failed_updates_spinner_text(self) -> None:
        """compaction_failed event sets the spinner to the failed message."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(AgentStreamEventDAO(kind="compaction_failed"))
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            assert len(spinners) == 1
            assert "failed" in str(spinners[0]._text.content).lower()

    @pytest.mark.asyncio
    async def test_compaction_events_do_not_clear_spinner_override(self) -> None:
        """Compaction events leave the spinner mounted (unlike normal events that clear override)."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._mount_spinner()
            await app._render_event(AgentStreamEventDAO(kind="compaction_started"))
            await pilot.pause()

            spinners: list[ThinkingSpinner] = list(app.query(selector=ThinkingSpinner))
            assert len(spinners) == 1, "spinner must remain mounted during compaction"


class TestPreflightBypassRendering:
    """Fixed presentation for the local TPM bypass audit."""

    @pytest.mark.asyncio
    async def test_preflight_bypass_renders_exact_tool_result_line_without_spinner(self) -> None:
        """The bypass is a terse audit line, not a retry or spinner state."""
        app: SloTUI = SloTUI(session=_make_session())

        async with app.run_test() as pilot:
            await pilot.pause()
            await app._render_event(AgentStreamEventDAO(kind="preflight_bypassed"))
            await pilot.pause()

            rendered_lines = [str(line.render()) for line in app.query(selector=".tool-result")]
            assert rendered_lines.count("(local token preflight bypassed; request sent to provider)") == 1
            assert not list(app.query(selector=ThinkingSpinner))
