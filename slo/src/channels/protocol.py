"""Channel adapter protocol (108.1 minimal; extended in 108.5).

A channel adapter is code that connects one platform (TUI, CLI, Telegram, …)
to the queue: it sends inbound rows on behalf of its user and delivers
outbound rows back to the platform.
"""

from __future__ import annotations

from typing import Protocol

from src.channels.dao import ChannelMessageDAO

__all__ = ["ChannelAdapter"]


class ChannelAdapter(Protocol):
    """Minimal contract every channel adapter satisfies (extended in 108.5)."""

    async def start(self) -> None:
        """Register the channel and its user, and start delivery."""
        ...

    async def stop(self) -> None:
        """Stop delivery and release adapter resources."""
        ...

    async def deliver(self, *, message: ChannelMessageDAO) -> None:
        """Deliver one outbound message to the platform user.

        Args:
            message (ChannelMessageDAO): Outbound row addressed to this
                adapter's user.
        """
        ...
