"""AgentPaneManager — per-agent scroll regions and transcript projectors.

One manager is owned by ``SloTUI`` for the lifetime of the app. Pane ``[0]``
is always the orchestrator. Sub-agent panes are registered dynamically on
``sub_agent_spawned`` events and keyed by ``task_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from textual.containers import Vertical, VerticalScroll

from src.tui.transcript_projector import TranscriptProjectionAdapter

__all__ = ["AgentPaneDAO", "AgentPaneManager"]


@dataclass
class AgentPaneDAO:
    """One agent pane: scroll region, content container, and projector.

    Attributes:
        scroll (VerticalScroll): Scroll container shown/hidden as the pane
            is activated or deactivated.
        content (Vertical): Widget mountpoint the pane's projector targets.
        projector (TranscriptProjectionAdapter): Per-pane event projector.
        tab_label (str): Short label shown on the tab strip.
        task_id (Optional[str]): Sub-task id; ``None`` for the orchestrator pane.
    """

    scroll: VerticalScroll
    content: Vertical
    projector: TranscriptProjectionAdapter
    tab_label: str
    task_id: Optional[str] = None


class AgentPaneManager:
    """Owns pane[0] (orchestrator) and pane[1..N] (sub-agents).

    ``SloTUI`` constructs one manager per app. It registers pane 0 on mount and
    one sub-agent pane per ``sub_agent_spawned`` event. Only the active pane is
    visible; hidden panes stay mounted so switching back is instant.
    """

    def __init__(self) -> None:
        """Initialise an empty manager with no panes."""
        self._panes: list[AgentPaneDAO] = []
        self._active_index: int = 0

    @property
    def panes(self) -> list[AgentPaneDAO]:
        """Return a snapshot of the ordered pane list (index 0 = orchestrator).

        Returns:
            list[AgentPaneDAO]: Ordered pane list.
        """
        return list(self._panes)

    @property
    def active_index(self) -> int:
        """Return the currently visible pane index.

        Returns:
            int: Active pane index.
        """
        return self._active_index

    def register_pane(self, *, pane: AgentPaneDAO) -> int:
        """Append a pane and return its index.

        Called by ``SloTUI`` for pane 0 on mount and once per sub-agent on
        ``sub_agent_spawned``. New panes start hidden unless they are pane 0
        (the only initially-active pane).

        Args:
            pane (AgentPaneDAO): The pane to register.

        Returns:
            int: The new pane's zero-based index.
        """
        index: int = len(self._panes)
        pane.scroll.display = index == self._active_index
        self._panes.append(pane)
        return index

    def switch_to(self, *, index: int) -> bool:
        """Make ``index`` the active pane, hiding the rest.

        Toggles Textual ``display`` so hidden panes avoid re-layout but keep
        receiving events. Invoked by the slash handler, ctrl-number bindings,
        and fleet-row click handling.

        Args:
            index (int): Target pane index.

        Returns:
            bool: True when the index was in range and the switch happened.
        """
        if index < 0 or index >= len(self._panes):
            return False
        self._active_index = index
        for position, pane in enumerate(self._panes):
            pane.scroll.display = position == index
        return True

    def projector_for_task(self, *, task_id: str) -> Optional[TranscriptProjectionAdapter]:
        """Resolve a sub-agent ``task_id`` to its pane projector.

        Called by ``SloTUI._route_sub_agent_event`` to deliver a tagged child
        event to the correct pane.

        Args:
            task_id (str): Sub-task identifier carried on the event.

        Returns:
            Optional[TranscriptProjectionAdapter]: The matching projector, or ``None``.
        """
        for pane in self._panes:
            if pane.task_id == task_id:
                return pane.projector
        return None

    def index_for_task(self, *, task_id: str) -> Optional[int]:
        """Return the pane index for a ``task_id``.

        Used to update tab icons and fleet rows on terminal lifecycle events.

        Args:
            task_id (str): Sub-task identifier.

        Returns:
            Optional[int]: Pane index, or ``None`` if no pane owns the task.
        """
        for position, pane in enumerate(self._panes):
            if pane.task_id == task_id:
                return position
        return None
