"""Commands for the queued-messages display (108.1 §5.5).

The app fetches the pending rows from the channel adapter and pushes one
snapshot per refresh; the component owns rendering only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.channels.dao import ChannelMessageDAO

__all__ = ["ClearQueuedDAO", "ShowQueuedDAO"]


class ShowQueuedDAO(BaseModel):
    """Refresh the queued-messages display with one pending-row snapshot."""

    model_config = ConfigDict(frozen=True)

    rows: list[ChannelMessageDAO] = Field(
        description="Pending prompt rows in display order; pending_inbound(S).",
    )
    paused: bool = Field(
        description="Whether the channel poller is paused; shows the resume hint.",
    )


class ClearQueuedDAO(BaseModel):
    """Clear the queued-messages display; the queue is empty."""

    model_config = ConfigDict(frozen=True)
