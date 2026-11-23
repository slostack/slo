"""``ChannelNoteDisplay`` — shows each note row once per session (108.3 §2).

A note can be met first by either of two concurrent readers of the queue:
the session's poller (a tick sees it pending) or the agent's boundary inbox
(a safe boundary takes it before any tick ran). Both hand the row to the one
``ChannelNoteDisplay`` the session wires into them, which shows it through the
display sink exactly once, whoever arrives first.

Rules:

- A row is *shown* only after the sink returned; an in-flight render is never
  started again, and a second caller does not wait for it.
- The render runs shielded from its caller, so cancelling the caller (an
  aborted run) neither cuts the render short nor leaves it unrecorded.
- A render that fails is *owed*: ``show_owed`` (every poller tick) retries it,
  so a note the boundary already accepted is still shown, once.
- The session's delivery stop owns the render lifetime: ``close`` seals
  admission, cancels every in-flight render and joins it, so no render outlives
  the stopped delivery or publishes into a successor's borrowed UI.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from config.logger import log_warning
from src.channels.dao import ChannelMessageDAO

__all__ = ["ChannelDisplaySink", "ChannelNoteDisplay"]


@runtime_checkable
class ChannelDisplaySink(Protocol):
    """Where the poller hands rows that must be shown but not run (108.3 §5)."""

    async def show(self, *, message: ChannelMessageDAO) -> None:
        """Display one channel row (notice or note) to this channel's user.

        Args:
            message (ChannelMessageDAO): The row being displayed.
        """
        ...


class ChannelNoteDisplay:
    """The session's display-once owner for note rows, shared by poller and boundary."""

    def __init__(self, *, sink: Optional[ChannelDisplaySink]) -> None:
        """Bind the display sink; ``None`` settles notes without rendering anything.

        Args:
            sink (Optional[ChannelDisplaySink]): Where notes are rendered.
        """
        self._sink: Optional[ChannelDisplaySink] = sink
        self._shown_ids: set[UUID] = set()
        self._renders: dict[UUID, asyncio.Task[None]] = {}
        self._owed: dict[UUID, ChannelMessageDAO] = {}
        self._closed: bool = False

    async def show_once(self, *, message: ChannelMessageDAO) -> None:
        """Show one note unless it was already shown or is being shown now.

        Never raises for a sink failure (the note becomes owed). Raises
        ``asyncio.CancelledError`` only when the caller itself is cancelled;
        the render runs on as its own task and is still recorded. A render
        ``close`` retires returns normally here (the note stays unshown), and
        nothing is rendered once closed.

        Args:
            message (ChannelMessageDAO): The note row to show.
        """
        if self._closed or message.id in self._shown_ids or message.id in self._renders:
            return
        render: asyncio.Task[None] = asyncio.ensure_future(self._render(message=message))
        self._renders[message.id] = render
        # ``wait`` (not ``shield``): cancelling the caller leaves the render
        # running, and a render cancelled by ``close`` does not raise into the
        # caller as if the caller itself had been cancelled.
        await asyncio.wait([render])

    async def close(self) -> None:
        """Seal admission, then cancel and join every in-flight render.

        Called by the delivery stop before the borrowed UI is retired, so no
        render survives it. Idempotent; a render that ignores cancellation
        is still joined.
        """
        self._closed = True
        renders: list[asyncio.Task[None]] = list(self._renders.values())
        for render in renders:
            render.cancel()
        await asyncio.gather(*renders, return_exceptions=True)

    async def show_owed(self) -> None:
        """Retry every note whose earlier render failed, oldest first (none once closed)."""
        for message in list(self._owed.values()):
            await self.show_once(message=message)

    async def _render(self, *, message: ChannelMessageDAO) -> None:
        """Render one note through the sink and record the outcome.

        Args:
            message (ChannelMessageDAO): The note row being rendered.
        """
        try:
            if self._sink is not None:
                await self._sink.show(message=message)
        except asyncio.CancelledError:
            self._owed[message.id] = message
            raise
        except Exception as exc:  # noqa: BLE001 -- an unavailable sink must not lose the note
            log_warning(msg=f"channel note display failed; retried on the next tick: {exc}")
            self._owed[message.id] = message
        else:
            self._shown_ids.add(message.id)
            self._owed.pop(message.id, None)
        finally:
            self._renders.pop(message.id, None)
