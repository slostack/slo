"""Completion fences for finite, non-streaming selection fixture mutations."""

from __future__ import annotations

import asyncio
from functools import partial, wraps
from typing import Callable

import pytest
from textual._callback import invoke
from textual.message_pump import MessagePump
from textual.widget import Widget

from src.tui.app import SloTUI


class SelectionFixtureFence:
    """Track real app/viewport refresh callbacks, including their descendants.

    Install before fixture writes. The fixture has no ongoing stream: finalize()
    and set_thinking() flush synchronously. Mount completion and bottom-up message
    fences deliver their Rendered messages before callback quiescence is tested.
    This does not wait for unrelated workers or change follow policy.
    """

    def __init__(self, *, app: SloTUI, monkeypatch: pytest.MonkeyPatch) -> None:
        """Observe the two owners of the fixture's deferred follow chain."""
        self.app = app
        self.pending = 0
        self.completed = asyncio.Event()
        self.completed.set()
        assert app._transcript_scroll is not None
        for owner in (app, app._transcript_scroll):
            self._observe(owner=owner, monkeypatch=monkeypatch)

    def _observe(self, *, owner: MessagePump, monkeypatch: pytest.MonkeyPatch) -> None:
        """Count callbacks until execution, not merely until enqueue or latch clear."""
        original = owner.call_after_refresh

        def enqueue(callback: Callable, *args: object, **kwargs: object) -> bool:
            """Retain the original callback and count descendants before parent completion."""
            self.pending += 1
            self.completed.clear()

            @wraps(callback)
            async def execute() -> None:
                """Delegate the real callback, then release this completion obligation."""
                try:
                    await invoke(partial(callback, *args, **kwargs))
                finally:
                    self._complete()

            accepted = original(execute)
            if not accepted:
                self._complete()
            return accepted

        monkeypatch.setattr(owner, "call_after_refresh", enqueue)

    def _complete(self) -> None:
        """Signal only when every observed callback and descendant has executed."""
        self.pending -= 1
        if self.pending == 0:
            self.completed.set()

    @staticmethod
    async def _messages_processed(*, owner: MessagePump) -> None:
        """Fence one message queue after its current messages have been dispatched."""
        processed = asyncio.Event()
        assert owner.call_later(processed.set)
        await processed.wait()

    async def paint_committed(self) -> None:
        """Wait for callback descendants and the layout/paint they requested."""
        while True:
            await self.completed.wait()
            painted = asyncio.Event()
            assert self.app.call_after_refresh(painted.set)
            await painted.wait()
            if self.pending == 0:
                return

    async def fixture_completed(self) -> None:
        """Await mounted fixture widgets, bubbled Rendered messages, then final paint."""
        assert self.app._transcript_content is not None
        widgets: list[Widget] = list(self.app._transcript_content.walk_children(Widget, with_self=True))
        for widget in reversed(widgets):
            await widget._mounted_event.wait()
            await self._messages_processed(owner=widget)
        # Rendered bubbles through each ancestor queue before reaching the app.
        for ancestor in self.app._transcript_content.ancestors:
            await self._messages_processed(owner=ancestor)
        await self.paint_committed()
