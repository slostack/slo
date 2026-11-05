"""Incomplete append-order logical record and plain-notice display."""

from __future__ import annotations

import asyncio

from typing import Self, Protocol

from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO


class TranscriptNoticeMountTarget(Protocol):
    """Specialized mount leaf used only after transcript admission."""

    async def mount_transcript_notice(self, *, notice: TranscriptNoticeDAO) -> None:
        """Mount without reentering public transcript locks."""
        ...


class TranscriptNoticeDisplayAdapter:
    """Send notice text to the transcript and keep its text record up to date.

    Keep recording text separate from drawing widgets so callers can use the
    operation they need. Use the supplied transcript interface without owning
    or closing the transcript itself."""

    TURN_SEPARATOR: str = "─" * 18

    def __init__(self, *, tui: TranscriptNoticeMountTarget) -> None:
        """Save the supplied notice destination without taking ownership of it."""
        self._tui = tui
        self.lines: list[tuple[str, str]] = []
        self._delivery_closed = False
        self._delivery_lock = asyncio.Lock()
        self._notice_version = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    async def handle(self, *, event: TranscriptNoticeDAO) -> None:
        """Display the notice, then record its text. Report display failures to the caller."""
        self._ensure_notice_adapter_open()
        self._update_delivery_loop()
        notice_version = self._notice_version
        async with self._delivery_lock:
            self._ensure_notice_adapter_open()
            self._update_delivery_loop()
            if notice_version != self._notice_version:
                raise RuntimeError("Notice delivery belongs to a retired presentation")
            if not isinstance(event, TranscriptNoticeDAO):
                raise TypeError(f"Unsupported transcript notice: {type(event).__name__}")
            await self._tui.mount_transcript_notice(notice=event)
            self.lines.append((event.content, event.classes))

    def _ensure_notice_adapter_open(self) -> None:
        """Raise RuntimeError after close, before loop capture or target access."""
        if self._delivery_closed:
            raise RuntimeError("Transcript notice adapter is closed")

    def _update_delivery_loop(self) -> None:
        """Store the first delivery/reset loop; later calls must use that same loop.

        Registration is inert. The mounted owner, not this adapter, establishes
        UI-loop authority. Raise RuntimeError before changing a borrowed target
        when a later call arrives on a different loop.
        """
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        self._ensure_delivery_loop(loop=loop)

    def _ensure_delivery_loop(self, *, loop: asyncio.AbstractEventLoop) -> None:
        """Require the running loop to match this adapter's stored delivery loop."""
        if loop is not self._loop:
            raise RuntimeError("Transcript adapter delivery requires the UI loop")

    async def reset(self) -> None:
        """Wait for earlier notices, clear recorded text, and keep the destination available for reuse."""
        self._ensure_notice_adapter_open()
        self._update_delivery_loop()
        await self._retire(close=False)

    async def close(self) -> None:
        """Stop accepting notices and wait for current delivery without closing the destination."""
        await self._retire(close=True)

    async def _retire(self, *, close: bool) -> None:
        """Keep cleanup running if the caller is cancelled and reject queued updates from the old state."""
        self._delivery_closed = self._delivery_closed or close
        task = asyncio.create_task(self._finish_retirement())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _finish_retirement(self) -> None:
        """Wait for accepted notices to finish before advancing the version used to reject old updates."""
        async with self._delivery_lock:
            self._notice_version += 1
            self.lines.clear()

    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self:
        """Return a fresh inactive display borrowing the transcript's mount leaf.

        Called before native mount. Construction neither mounts notices nor pins
        an event loop; the first delivery/reset owns that loop selection.

        Args:
            tui: Specialized mounting destination, not a command reentry point.

        Returns:
            An independent display and logical record; close leaves ``tui`` alive.
        """
        return cls(tui=tui)

    def record(self, *, content: str, classes: str) -> None:
        """Record text that is already displayed without adding a second widget."""
        if self._delivery_closed:
            raise RuntimeError("Transcript notice adapter is closed")
        self.lines.append((content, classes))

    def is_prior_turn_content_present(self) -> bool:
        """Check for recorded message text, ignoring turn separators."""
        return any(classes != "turn-separator" for _content, classes in self.lines)
