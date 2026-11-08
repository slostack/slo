"""Borrow a narrow transcript notice destination without owning workflow decisions."""

import asyncio

from typing import Protocol, Self

from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO


class TranscriptNoticeTarget(Protocol):
    """Admit only formatted notices; lifecycle ownership stays with the component."""

    async def handle(self, *, command: TranscriptNoticeDAO) -> None:
        """Apply a notice or propagate its delivery failure."""
        ...


class WorkflowNoticeAdapter:
    """Send workflow notices to the chat transcript.

    Forward notice text and display styles to the supplied destination.
    Closing this adapter stops its deliveries but does not close that
    destination."""

    def __init__(self, *, tui: TranscriptNoticeTarget) -> None:
        """Save the supplied notice destination without taking ownership of it."""
        self._tui: TranscriptNoticeTarget = tui
        self._delivery_closed: bool = False
        self._delivery_lock: asyncio.Lock = asyncio.Lock()
        self._workflow_notice_version: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def register(cls, *, tui: TranscriptNoticeTarget) -> Self:
        """Return a fresh inactive notice lifetime borrowing the command destination.

        Called by transcript construction before mount; no loop, subscription or
        task is captured. Closing this registration leaves ``tui`` available.

        Args:
            tui: Narrow command receiver that admits formatted notices.

        Returns:
            A new adapter, independent of earlier registrations.
        """
        return cls(tui=tui)

    async def handle(self, *, event: TranscriptNoticeDAO) -> None:
        """Convert a notice into a component command and wait for it to be applied."""
        self._ensure_workflow_notice_adapter_open()
        self._update_delivery_loop()
        workflow_notice_version: int = self._workflow_notice_version
        async with self._delivery_lock:
            self._ensure_workflow_notice_adapter_open()
            self._update_delivery_loop()
            if workflow_notice_version != self._workflow_notice_version:
                raise RuntimeError("Notice delivery belongs to a retired presentation")
            if not isinstance(event, TranscriptNoticeDAO):
                raise TypeError(f"Unsupported workflow notice: {type(event).__name__}")
            await self._tui.handle(command=event)

    def _ensure_workflow_notice_adapter_open(self) -> None:
        """Raise RuntimeError after close, before loop capture or target access."""
        if self._delivery_closed:
            raise RuntimeError("Workflow notice adapter is closed")

    def _update_delivery_loop(self) -> None:
        """Store the first delivery/reset loop; later calls must use that same loop.

        Registration is inert. The mounted owner, not this adapter, establishes
        UI-loop authority. Raise RuntimeError before changing a borrowed target
        when a later call arrives on a different loop.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        self._ensure_delivery_loop(loop=loop)

    def _ensure_delivery_loop(self, *, loop: asyncio.AbstractEventLoop) -> None:
        """Require the running loop to match this adapter's stored delivery loop."""
        if loop is not self._loop:
            raise RuntimeError("Transcript adapter delivery requires the UI loop")

    async def reset(self) -> None:
        """Wait for earlier notices to finish before allowing a new set of updates."""
        self._ensure_workflow_notice_adapter_open()
        self._update_delivery_loop()
        await self._retire(close=False)

    async def close(self) -> None:
        """Stop accepting notices and wait for current delivery without closing the destination."""
        await self._retire(close=True)

    async def _retire(self, *, close: bool) -> None:
        """Keep cleanup running if the caller is cancelled and reject queued updates from the old state."""
        self._delivery_closed = self._delivery_closed or close
        # This is occupancy, not current-task ownership. Keep native acquisition
        # below: an unoccupied lock needs no shielded joining task.
        if not self._delivery_lock.locked():
            await self._finish_retirement()
            return
        task: asyncio.Task[None] = asyncio.create_task(self._finish_retirement())
        cancelled: bool = False
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
            self._workflow_notice_version += 1
