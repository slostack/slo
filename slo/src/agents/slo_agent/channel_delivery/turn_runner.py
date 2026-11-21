"""TurnRunner port and its outcome DAO (108.1).

A ``TurnRunner`` runs one accepted prompt row as one agent turn. The TUI
provides the production implementation; tests inject recording stubs through
the poller's constructor.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, Field

from src.channels.dao import ChannelMessageDAO

__all__ = ["TurnOutcomeDAO", "TurnRunner"]


class TurnOutcomeDAO(BaseModel):
    """How one channel-driven turn ended."""

    status: Literal["completed", "failed", "aborted", "not_started"] = Field(
        description="How the turn ended; 'not_started' means invoke() never yielded an event."
    )
    final_text: str = Field(
        default="",
        description="Last assistant text of the run, used as the reply contents.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Short error line when the turn failed or did not start.",
    )


class TurnRunner(Protocol):
    """Runs one channel prompt row as one agent turn."""

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Run the message and report the outcome.

        Implementations must call ``on_started()`` once the underlying
        ``invoke()`` has yielded its first event; the poller uses that
        callback to stamp ``accepted_at``.

        Args:
            message (ChannelMessageDAO): The accepted prompt row to run.
            on_started (Callable[[], Awaitable[None]]): First-event callback.

        Returns:
            TurnOutcomeDAO: How the run ended and its final text.
        """
        ...
