"""QueuedMessagesComponent — the persistent queued-prompt list (108.1 §5.5).

The 108.1 spec defines this component as the queued-list surface: pending
prompts appear here (with the ⚡ forced marker from 108.2) until their run
starts, so the transcript keeps the model's context order. Max five rows plus
an overflow line; the paused state shows ``paused — /queue resume``. Hidden
while the queue is empty.
"""

from __future__ import annotations

from typing import Optional, Union
from uuid import UUID

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from src.channels.dao import ChannelMessageDAO
from src.tui.components.queued_messages.commands import ClearQueuedDAO, ShowQueuedDAO

__all__ = ["QueuedMessagesComponent", "QueuedRow", "QueuedRowCancel"]

_MAX_ROWS: int = 5
_PAUSED_HINT: str = "paused — /queue resume"
_FORCED_MARKER: str = "⚡"
_IDLE_MARKER: str = " "


class QueuedRowCancel(Static):
    """One queued row's cancel affordance; carries its message id."""

    def __init__(self, *, message_id: UUID) -> None:
        """Store the row id the cancel click will report.

        Args:
            message_id (UUID): The queued row's id.
        """
        self.message_id: UUID = message_id
        super().__init__("×", classes="queued-row-cancel")

    def on_click(self, event: events.Click) -> None:
        """Post ``CancelRequested`` for this row's message id (108.1 §5.5).

        Args:
            event (events.Click): The click on this affordance.
        """
        event.stop()
        self.post_message(QueuedMessagesComponent.CancelRequested(message_id=self.message_id))


class QueuedRow(Horizontal):
    """One queued prompt row: forced marker, preview, and cancel affordance."""

    def __init__(self, *, row: ChannelMessageDAO) -> None:
        """Compose one row from its pending message.

        Args:
            row (ChannelMessageDAO): The pending row to render.
        """
        marker: str = _FORCED_MARKER if row.forced_at is not None else _IDLE_MARKER
        text: str = row.message_contents
        preview: str = text if len(text) <= 60 else (text[:57] + "…")
        super().__init__(
            Static(f"{marker} {preview}", classes="queued-row-text"),
            QueuedRowCancel(message_id=row.id),
            classes="queued-row",
        )


class QueuedMessagesComponent(Vertical):
    """Render the pending channel-queue rows below the prompt input.

    CSS comes from the component's own ``css.tcss``.

    Refreshed by the app on local send, on poller state change, and every
    poll tick while non-empty (108.1 §5.5). A row's cancel affordance posts
    ``CancelRequested``; the app routes it to ``gateway.cancel``.
    """

    class CancelRequested(Message):
        """The operator asked to cancel one queued row."""

        def __init__(self, *, message_id: UUID) -> None:
            """Carry the queued row's id."""
            self.message_id: UUID = message_id
            super().__init__()

    DEFAULT_CSS = """
    QueuedMessagesComponent {
        height: auto;
        max-height: 12;
        margin: 0 1 0 1;
        padding: 0 1 0 1;
        border: round $primary 30%;
        background: $surface;
        display: none;
    }

    QueuedMessagesComponent.visible {
        display: block;
    }

    QueuedMessagesComponent .queued-row {
        height: 1;
    }

    QueuedMessagesComponent .queued-row-text {
        width: 1fr;
        color: $text-muted;
    }

    QueuedMessagesComponent .queued-row-cancel {
        width: auto;
        color: $error;
        text-style: bold;
    }

    QueuedMessagesComponent .queued-overflow {
        height: 1;
        color: $text-disabled;
        text-style: italic;
    }

    QueuedMessagesComponent .queued-paused {
        height: 1;
        color: $warning;
        text-style: italic;
    }
    """

    def __init__(self) -> None:
        """Build the hidden-by-default queue display."""
        super().__init__(id="queued-messages")
        self._rows: list[ChannelMessageDAO] = []
        self._paused: bool = False
        self._pending_command: Optional[Union[ShowQueuedDAO, ClearQueuedDAO]] = None

    def handle(self, *, command: Union[ShowQueuedDAO, ClearQueuedDAO]) -> None:
        """Apply one queue-display command (108.1 §5.5).

        Args:
            command (ShowQueuedDAO | ClearQueuedDAO): The snapshot to render
                or the clear order.
        """
        self._pending_command = command
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        """Render the current snapshot: rows, overflow line, and pause hint."""
        command = self._pending_command
        if isinstance(command, ClearQueuedDAO):
            self._rows = []
            self._paused = False
        elif isinstance(command, ShowQueuedDAO):
            self._rows = list(command.rows)
            self._paused = command.paused
        if not self._rows:
            self.display = False
            self.remove_children()
            return
        self.display = True
        self.can_focus = False
        self.remove_children()
        shown: list[ChannelMessageDAO] = self._rows[:_MAX_ROWS]
        overflow: int = len(self._rows) - len(shown)
        self.mount(*self._compose_rows(shown=shown, overflow=overflow, paused=self._paused))

    def _compose_rows(self, *, shown: list[ChannelMessageDAO], overflow: int, paused: bool) -> ComposeResult:
        """Yield the row widgets, the overflow line, and the pause hint.

        Args:
            shown (list[ChannelMessageDAO]): The first five rows to render.
            overflow (int): How many rows beyond the cap exist.
            paused (bool): Whether the poller is paused.

        Yields:
            ComposeResult: The queued-row widgets and hint lines.
        """
        for row in shown:
            yield QueuedRow(row=row)
        if overflow > 0:
            yield Static(f"+{overflow} more", classes="queued-overflow")
        if paused:
            yield Static(_PAUSED_HINT, classes="queued-paused")
