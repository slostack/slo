"""Tests for ``AgentTabDAO`` and ``AgentTabStrip``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tui.widgets.agent_tab_strip import AgentTabDAO, AgentTabStrip


# ---------------------------------------------------------------------------
# TestAgentTabDAO
# ---------------------------------------------------------------------------


class TestAgentTabDAO:
    """``AgentTabDAO`` display-label logic."""

    def test_display_label_running(self) -> None:
        """Running tab label shows ``⏳``."""
        tab: AgentTabDAO = AgentTabDAO(index=0, label="orchestrator", status="running")

        assert "⏳" in tab.display_label
        assert "orchestrator" in tab.display_label

    def test_display_label_completed(self) -> None:
        """Completed tab label shows ``✓``."""
        tab: AgentTabDAO = AgentTabDAO(index=1, label="task-A", status="completed")

        assert "✓" in tab.display_label

    def test_display_label_failed(self) -> None:
        """Failed tab label shows ``✗``."""
        tab: AgentTabDAO = AgentTabDAO(index=1, label="task-A", status="failed")

        assert "✗" in tab.display_label

    def test_display_label_pending(self) -> None:
        """Pending tab label shows ``○``."""
        tab: AgentTabDAO = AgentTabDAO(index=0, label="x", status="pending")

        assert "○" in tab.display_label

    def test_display_label_includes_label(self) -> None:
        """The base label text appears in the display label."""
        tab: AgentTabDAO = AgentTabDAO(index=0, label="my-special-task")

        assert "my-special-task" in tab.display_label


# ---------------------------------------------------------------------------
# TestAgentTabStrip — state logic (no DOM)
# ---------------------------------------------------------------------------


class TestAgentTabStripState:
    """``AgentTabStrip`` state mutations without a mounted DOM."""

    def _strip(self) -> AgentTabStrip:
        return AgentTabStrip()

    def test_initial_display_false(self) -> None:
        """Freshly constructed strip has ``display == False``."""
        strip: AgentTabStrip = self._strip()

        assert strip.display is False

    @pytest.mark.asyncio
    async def test_add_tab_makes_visible(self) -> None:
        """Adding the first tab makes the strip visible."""
        strip: AgentTabStrip = self._strip()

        with patch.object(strip, "mount", new_callable=AsyncMock):
            await strip.add_tab(tab=AgentTabDAO(index=0, label="orchestrator"))

        assert strip.display is True

    def test_set_status_updates_tab_dao(self) -> None:
        """``set_status`` updates the DAO status of the tab at the given index."""
        from textual.css.query import NoMatches

        strip: AgentTabStrip = self._strip()
        strip._tabs = [
            AgentTabDAO(index=0, label="orchestrator", status="running"),
            AgentTabDAO(index=1, label="task-A", status="running"),
        ]

        with patch.object(strip, "query_one", side_effect=NoMatches):
            strip.set_status(index=1, status="completed")

        assert strip._tabs[1].status == "completed"

    def test_set_status_out_of_range_is_noop(self) -> None:
        """``set_status`` with an out-of-range index does nothing."""
        strip: AgentTabStrip = self._strip()
        strip._tabs = [AgentTabDAO(index=0, label="x", status="running")]

        strip.set_status(index=99, status="completed")  # must not raise

        assert strip._tabs[0].status == "running"

    def test_set_active_updates_index(self) -> None:
        """``set_active`` stores the new active index."""
        from textual.css.query import NoMatches

        strip: AgentTabStrip = self._strip()

        with patch.object(strip, "query_one", side_effect=NoMatches):
            strip.set_active(index=2)

        assert strip._active_index == 2

    def test_on_mount_registers_interval(self) -> None:
        """``AgentTabStrip`` constructor stores default tab list as empty."""
        strip: AgentTabStrip = self._strip()

        assert strip._tabs == []
        assert strip._active_index == 0
