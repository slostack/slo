"""QueuedMessagesComponent rendering tests (108.1 §5.5; 108.2 ⚡ style).

The component is the persistent queued-list surface the 108.1 spec defined
(``src/tui/components/queued_messages/``) — the ⚡ marker belongs here, not
only in the ``/queue`` slash listing. Tests drive the component inside a
minimal host app against a real channel gateway, mirroring the agent-composer
test pattern.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID, uuid4

import pytest
from textual.app import App, ComposeResult

from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.components.queued_messages.component import QueuedMessagesComponent
from src.tui.components.queued_messages.commands import ClearQueuedDAO, ShowQueuedDAO


class _QueueHost(App):
    """Minimal host app that mounts the queue component once."""

    async def on_queued_messages_component_cancel_requested(
        self, event: QueuedMessagesComponent.CancelRequested
    ) -> None:
        """Record cancel requests raised by the mounted component.

        Args:
            event (QueuedMessagesComponent.CancelRequested): The request.
        """
        self._cancelled.append(event.message_id)

    def __init__(self, factory: Callable[[], QueuedMessagesComponent]) -> None:
        """Bind the component factory.

        Args:
            factory (Callable[[], QueuedMessagesComponent]): Builds the
                component once the app (and its theme variables) exist.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name
        self._factory = factory
        self._cancelled: list[UUID] = []

    def compose(self) -> ComposeResult:
        """Yield the queue component."""
        yield self._factory()


def _row(*, text: str, forced: bool = False) -> ChannelMessageDAO:
    """Build one pending prompt row for the display.

    Args:
        text (str): The message body.
        forced (bool): Whether the row was sent forced (⚡ marker).

    Returns:
        ChannelMessageDAO: A pending prompt row.
    """
    now: datetime = datetime.now(timezone.utc)
    return ChannelMessageDAO(
        id=uuid4(),
        agent_session_id=uuid4(),
        sender_id=uuid4(),
        sender_name="you",
        recipient_id=uuid4(),
        recipient_name="slo",
        sent_at=now,
        accepted_at=None,
        message_contents=text,
        created_at=now,
        message_index=1,
        forced_at=now if forced else None,
        message_type="prompt",
        channel_id=None,
        in_reply_to_id=None,
        cancelled_at=None,
        cancel_reason=None,
        coalesce_key=None,
    )


async def _settle(pilot, cycles: int = 4) -> None:  # type: ignore[no-untyped-def]
    """Pump a few refresh cycles so Textual settles."""
    for _cycle in range(cycles):
        await pilot.pause()
        await asyncio.sleep(0.02)


def _row_texts(*, component: QueuedMessagesComponent) -> str:
    """Concatenate the text of every row/hint static inside the component.

    Args:
        component (QueuedMessagesComponent): The rendered queue display.

    Returns:
        str: The joined text of ``.queued-row-text``, ``.queued-overflow``
            and ``.queued-paused`` children.
    """
    parts: list[str] = []
    for child in component.children:
        if child.children:
            for nested in child.children:
                parts.append(str(nested.render()))
        else:
            parts.append(str(child.render()))
    return "".join(parts)


class TestQueuedMessagesComponent:
    """The queued-list widget renders rows, ⚡ markers, and the paused notice."""

    async def test_show_renders_rows_with_forced_marker_and_overflow(self) -> None:
        """Seven rows render as five rows plus a ``+2 more`` line; forced rows show ⚡."""
        app: _QueueHost = _QueueHost(factory=QueuedMessagesComponent)
        async with app.run_test() as pilot:
            await _settle(pilot)
            component: QueuedMessagesComponent = app.query_one(QueuedMessagesComponent)
            rows: list[ChannelMessageDAO] = [
                _row(text=f"row {index}", forced=(index == 1)) for index in range(7)
            ]
            component.handle(command=ShowQueuedDAO(rows=rows, paused=False))
            await _settle(pilot)

            rendered: str = _row_texts(component=component)
            assert "row 0" in rendered
            assert "row 4" in rendered
            assert "row 5" not in rendered
            assert "⚡" in rendered
            assert "+2 more" in rendered
            assert component.display

    async def test_paused_rows_show_resume_hint(self) -> None:
        """A paused queue shows the ``paused — /queue resume`` hint line."""
        app: _QueueHost = _QueueHost(factory=QueuedMessagesComponent)
        async with app.run_test() as pilot:
            await _settle(pilot)
            component: QueuedMessagesComponent = app.query_one(QueuedMessagesComponent)
            component.handle(command=ShowQueuedDAO(rows=[_row(text="held")], paused=True))
            await _settle(pilot)

            rendered: str = _row_texts(component=component)
            assert "held" in rendered
            assert "paused — /queue resume" in rendered

    async def test_clear_hides_the_component(self) -> None:
        """An empty queue hides the whole component."""
        app: _QueueHost = _QueueHost(factory=QueuedMessagesComponent)
        async with app.run_test() as pilot:
            await _settle(pilot)
            component: QueuedMessagesComponent = app.query_one(QueuedMessagesComponent)
            component.handle(command=ShowQueuedDAO(rows=[_row(text="held")], paused=False))
            await _settle(pilot)
            assert component.display

            component.handle(command=ClearQueuedDAO())
            await _settle(pilot)
            assert not component.display

    async def test_row_cancel_click_posts_cancel_requested(self) -> None:
        """Pressing a row's cancel affordance posts ``CancelRequested`` with its id."""
        app: _QueueHost = _QueueHost(factory=QueuedMessagesComponent)
        async with app.run_test() as pilot:
            await _settle(pilot)
            component: QueuedMessagesComponent = app.query_one(QueuedMessagesComponent)
            row: ChannelMessageDAO = _row(text="held")
            component.handle(command=ShowQueuedDAO(rows=[row], paused=False))
            await _settle(pilot)
            cancel_label = component.query_one(".queued-row-cancel")
            await pilot.click(cancel_label)
            await _settle(pilot)
            assert app._cancelled == [row.id]
