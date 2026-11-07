"""Bounded session-owned best-effort callback mailbox, never a history writer."""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Optional

from config.logger import log_error
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


class PresentationMailbox:
    """Own one subscriber worker with FIFO snapshots and a monotonic callback budget."""

    def __init__(self, *, handler: Callable[[AgentStreamEventDAO], Awaitable[None]]) -> None:
        """Retain the observer without starting work outside an active event loop."""
        self.handler = handler
        self._pending: deque[tuple[AgentStreamEventDAO, int, Optional[asyncio.Future[None]]]] = deque()
        self._bytes = 0
        self._ready = asyncio.Event()
        self._worker: Optional[asyncio.Task[None]] = None
        self._budget: Optional[asyncio.TimerHandle] = None
        self._retired = False
        self._cancel_requested = False
        self.diagnostic: Optional[str] = None

    def publish(self, *, event: AgentStreamEventDAO) -> None:
        """Admit a detached bounded snapshot without awaiting an observer."""
        if self._retired:
            return
        size = len(event.model_dump_json().encode("utf-8"))
        if len(self._pending) >= 256 or self._bytes + size > 1024 * 1024:
            self.retire(reason="presentation_replay_gap")
            return
        self._pending.append((event.model_copy(deep=True), size, None))
        self._bytes += size
        self._ready.set()
        self.start()

    async def deliver(self, *, event: AgentStreamEventDAO) -> None:
        """Join legacy callback completion without a best-effort observation budget.

        Session relay callers use this before messaging activation. The same
        retained worker owns delivery across activation, unsubscribe and close;
        switching publication policy never creates a second callback worker.

        Args:
            event (AgentStreamEventDAO): Legacy event whose callback must finish.
        """
        if self._retired:
            return
        completed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending.append((event, 0, completed))
        self._ready.set()
        self.start()
        cancelled = False
        while not completed.done():
            try:
                await asyncio.shield(arg=completed)
            except asyncio.CancelledError:
                cancelled = True
                self.retire()
        if cancelled or completed.cancelled():
            await self.join()
            raise asyncio.CancelledError() from None

    def is_active(self) -> bool:
        """Report publication eligibility without exposing mutable lifecycle state."""
        return not self._retired

    def is_joined(self) -> bool:
        """Report retired ownership whose worker has actually terminated."""
        return self._retired and (self._worker is None or self._worker.done())

    def start(self) -> None:
        """Retain the sole worker before returning from active-loop registration."""
        if self._worker is None and not self._retired:
            self._worker = asyncio.create_task(coro=self._run())

    def retire(self, *, reason: Optional[str] = None) -> None:
        """Seal once, discard queued snapshots and request worker cancellation once."""
        if self._retired:
            return
        self._retired = True
        self.diagnostic = reason
        for _, _, completed in self._pending:
            if completed is not None and not completed.done():
                completed.set_result(None)
        self._pending.clear()
        self._bytes = 0
        self._ready.set()
        if self._budget is not None:
            self._budget.cancel()
            self._budget = None
        if self._worker is not None and not self._worker.done() and not self._cancel_requested:
            self._cancel_requested = True
            self._worker.cancel()

    async def join(self) -> None:
        """Retire and join exact ownership despite repeated waiter cancellation."""
        self.retire()
        if self._worker is None:
            return
        joined = asyncio.gather(self._worker, return_exceptions=True)
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                continue
        joined.result()

    def _expire(self) -> None:
        """Retire the current callback on its one-second observation budget."""
        self.retire(reason="presentation_replay_gap")

    async def _run(self) -> None:
        """Await each callback on the same worker; suppression retains actual ownership."""
        try:
            while not self._retired:
                await self._ready.wait()
                if not self._pending:
                    self._ready.clear()
                    continue
                event, size, completed = self._pending.popleft()
                self._bytes -= size
                if not self._pending:
                    self._ready.clear()
                await self._deliver_callback(event=event, completed=completed)
        except asyncio.CancelledError:
            # Cancellation before first callback or while idle owns no leaf.
            return

    async def _deliver_callback(
        self, *, event: AgentStreamEventDAO, completed: Optional[asyncio.Future[None]]
    ) -> None:
        """Complete one owned callback; only messaging observations may expire.

        Args:
            event (AgentStreamEventDAO): Next FIFO event for the sole worker.
            completed (Optional[asyncio.Future[None]]): Legacy completion barrier,
                or None for best-effort messaging publication.
        """
        if completed is None:
            self._budget = asyncio.get_running_loop().call_later(1.0, self._expire)
        try:
            await self.handler(event)
        except asyncio.CancelledError:
            # Owner-requested retirement completes legacy delivery after joining;
            # callback-origin cancellation must instead reach the legacy caller.
            if completed is not None and not self._cancel_requested:
                completed.cancel()
            self.retire(reason="presentation_replay_gap")
        except Exception as error:
            if completed is None:
                self.retire(reason="presentation_replay_gap")
            else:
                log_error(msg="SloAgentSession: legacy subscriber raised", e=error, stack_trace=False)
        finally:
            if self._budget is not None:
                self._budget.cancel()
                self._budget = None
            if completed is not None and not completed.done():
                completed.set_result(None)
