"""AgentTabStrip — horizontal strip of per-agent pane tabs with status icons."""

from __future__ import annotations

from dataclasses import dataclass

from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button

__all__ = ["AgentTabDAO", "AgentTabStrip"]

_STATUS_ICONS: dict[str, str] = {
    "pending": "○",
    "running": "⏳",
    "completed": "✓",
    "failed": "✗",
    "aborted": "✗",
}
"""Status icon glyphs keyed by lifecycle status string."""


@dataclass
class AgentTabDAO:
    """Descriptor for one tab button in the strip.

    Attributes:
        index (int): Pane index this tab selects.
        label (str): Base label (task id or "orchestrator").
        status (str): One of ``pending``, ``running``, ``completed``, ``failed``.
    """

    index: int
    label: str
    status: str = "running"

    @property
    def display_label(self) -> str:
        """Return the status-decorated label shown on the button.

        Returns:
            str: Icon + label, e.g. ``"⏳ task-A"``.
        """
        return f"{_STATUS_ICONS.get(self.status, '○')} {self.label}"


class AgentTabStrip(Horizontal):
    """Horizontal strip rendering one button per registered pane.

    ``SloTUI`` mounts one strip above the panes container, calls ``add_tab``
    when a pane is registered, ``set_status`` when a lifecycle event arrives,
    and ``set_active`` when the active pane changes. The strip starts hidden
    (``display = False``) and becomes visible on the first ``add_tab`` call.
    """

    DEFAULT_CSS = """
    AgentTabStrip {
        height: 3;
        width: 100%;
        background: $surface;
        border-bottom: solid $primary;
    }
    AgentTabStrip Button {
        min-width: 12;
        margin: 0 1 0 0;
    }
    AgentTabStrip Button.-active {
        background: $primary;
        color: $background;
    }
    """

    class TabSelected(Message):
        """Posted when the user clicks a tab.

        Attributes:
            index (int): Pane index to activate.
        """

        def __init__(self, *, index: int) -> None:
            """Carry the requested pane index.

            Args:
                index (int): Selected pane index.
            """
            self.index: int = index
            super().__init__()

    def __init__(self) -> None:
        """Compose an empty strip, initially hidden."""
        super().__init__()
        self._tabs: list[AgentTabDAO] = []
        self._active_index: int = 0
        self.display = False

    async def add_tab(self, *, tab: AgentTabDAO) -> None:
        """Append a tab, make the strip visible, and mount its button.

        Called by ``SloTUI._register_sub_agent_pane`` after a pane is
        registered. Makes the strip visible on the first call. Each tab
        is mounted incrementally so no remove/remount cycle is needed.

        Args:
            tab (AgentTabDAO): The new tab descriptor.
        """
        self._tabs.append(tab)
        self.display = True
        button: Button = Button(
            label=tab.display_label,
            id=f"agent-tab-{tab.index}",
        )
        if tab.index == self._active_index:
            button.add_class("-active")
        await self.mount(button)

    def set_status(self, *, index: int, status: str) -> None:
        """Update one tab's status icon in place.

        Updates the DAO and rewrites the matching button's label via
        ``query_one``. A no-op when ``index`` is out of range or the
        widget is not yet mounted (defensive for test paths).

        Args:
            index (int): Tab index to update.
            status (str): New status string.
        """
        if index < 0 or index >= len(self._tabs):
            return
        self._tabs[index].status = status
        try:
            button: Button = self.query_one(f"#agent-tab-{index}", Button)
            button.label = self._tabs[index].display_label
        except NoMatches:
            pass  # button not yet in the DOM; a subsequent _rebuild will sync

    def set_active(self, *, index: int) -> None:
        """Highlight the newly active tab by toggling the ``-active`` class.

        Removes ``-active`` from all buttons and adds it only to the target.
        A no-op for buttons not yet in the DOM (defensive for test paths).

        Args:
            index (int): Newly active pane index.
        """
        self._active_index = index
        for tab in self._tabs:
            try:
                button: Button = self.query_one(f"#agent-tab-{tab.index}", Button)
                if tab.index == index:
                    button.add_class("-active")
                else:
                    button.remove_class("-active")
            except NoMatches:
                pass  # button not yet in the DOM; skip silently

    async def reset(self) -> None:
        """Remove all tab buttons and hide the strip for the next run.

        Called by ``SloTUI._cleanup_sub_agent_state`` at run end. Removes every
        button from the DOM, clears the tab list, resets the active index, and
        hides the strip so the layout returns to the pre-sub-agent appearance.
        """
        await self.remove_children()
        self._tabs.clear()
        self._active_index = 0
        self.display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate a tab button press into a ``TabSelected`` message.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        button_id: str = event.button.id or ""
        if button_id.startswith("agent-tab-"):
            suffix: str = button_id[len("agent-tab-") :]
            if suffix.isdigit():
                self.post_message(self.TabSelected(index=int(suffix)))
