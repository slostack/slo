"""Tests for ``AgentPaneManager`` and ``AgentPaneDAO``."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.tui.agent_pane_manager import AgentPaneDAO, AgentPaneManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pane(*, task_id: Optional[str] = None, tab_label: str = "pane") -> AgentPaneDAO:
    """Build an ``AgentPaneDAO`` with mocked Textual containers.

    Args:
        task_id (Optional[str]): Sub-task id; ``None`` for orchestrator pane.
        tab_label (str): Tab label text.

    Returns:
        AgentPaneDAO: Pane with mocked scroll/content/projector.
    """
    scroll_mock = MagicMock()
    scroll_mock.display = True
    return AgentPaneDAO(
        scroll=scroll_mock,
        content=MagicMock(),
        projector=MagicMock(),
        tab_label=tab_label,
        task_id=task_id,
    )


# ---------------------------------------------------------------------------
# TestAgentPaneManager
# ---------------------------------------------------------------------------


class TestAgentPaneManager:
    """``AgentPaneManager`` lifecycle and routing."""

    def test_register_pane_returns_sequential_indices(self) -> None:
        """Registered panes receive sequential zero-based indices."""
        manager: AgentPaneManager = AgentPaneManager()
        pane0: AgentPaneDAO = _mock_pane(tab_label="orchestrator")
        pane1: AgentPaneDAO = _mock_pane(task_id="task-A", tab_label="task-A")

        idx0: int = manager.register_pane(pane=pane0)
        idx1: int = manager.register_pane(pane=pane1)

        assert idx0 == 0
        assert idx1 == 1

    def test_pane_zero_starts_visible(self) -> None:
        """The first registered pane has ``scroll.display = True``."""
        manager: AgentPaneManager = AgentPaneManager()
        pane0: AgentPaneDAO = _mock_pane(tab_label="orchestrator")

        manager.register_pane(pane=pane0)

        assert pane0.scroll.display is True

    def test_subsequent_panes_start_hidden(self) -> None:
        """Sub-agent panes start with ``scroll.display = False``."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane(tab_label="orchestrator"))
        sub_pane: AgentPaneDAO = _mock_pane(task_id="task-A", tab_label="task-A")

        manager.register_pane(pane=sub_pane)

        assert sub_pane.scroll.display is False

    def test_switch_to_valid_index_returns_true(self) -> None:
        """Switching to a valid index returns ``True``."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())
        manager.register_pane(pane=_mock_pane(task_id="t1"))

        result: bool = manager.switch_to(index=1)

        assert result is True

    def test_switch_to_out_of_range_returns_false(self) -> None:
        """Switching to an out-of-range index returns ``False`` and changes nothing."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())

        result: bool = manager.switch_to(index=5)

        assert result is False
        assert manager.active_index == 0

    def test_switch_to_toggles_display(self) -> None:
        """After ``switch_to(1)``, pane 1 is visible and pane 0 is hidden."""
        manager: AgentPaneManager = AgentPaneManager()
        pane0: AgentPaneDAO = _mock_pane()
        pane1: AgentPaneDAO = _mock_pane(task_id="t1")
        manager.register_pane(pane=pane0)
        manager.register_pane(pane=pane1)

        manager.switch_to(index=1)

        assert pane0.scroll.display is False
        assert pane1.scroll.display is True
        assert manager.active_index == 1

    def test_projector_for_known_task(self) -> None:
        """``projector_for_task`` returns the projector for a registered task_id."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())
        pane1: AgentPaneDAO = _mock_pane(task_id="task-B")
        manager.register_pane(pane=pane1)

        result = manager.projector_for_task(task_id="task-B")

        assert result is pane1.projector

    def test_projector_for_unknown_task_returns_none(self) -> None:
        """``projector_for_task`` returns ``None`` for an unregistered task_id."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())

        result = manager.projector_for_task(task_id="no-such-task")

        assert result is None

    def test_index_for_known_task(self) -> None:
        """``index_for_task`` returns the correct pane index."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())
        manager.register_pane(pane=_mock_pane(task_id="task-C"))

        result: Optional[int] = manager.index_for_task(task_id="task-C")

        assert result == 1

    def test_index_for_unknown_task_returns_none(self) -> None:
        """``index_for_task`` returns ``None`` for an unregistered task_id."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())

        result: Optional[int] = manager.index_for_task(task_id="unknown")

        assert result is None

    def test_panes_property_returns_snapshot(self) -> None:
        """``panes`` returns a list copy; mutating it does not affect the manager."""
        manager: AgentPaneManager = AgentPaneManager()
        manager.register_pane(pane=_mock_pane())

        snapshot: list = manager.panes
        snapshot.append(_mock_pane(task_id="extra"))

        assert len(manager.panes) == 1
