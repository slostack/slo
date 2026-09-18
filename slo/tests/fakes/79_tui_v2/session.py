"""Deterministic external-session fake used only by b.2 headless characterization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = ["BaselineSession"]


AgentEventSubscriber = Callable[[AgentStreamEventDAO], Awaitable[None]]


class BaselineSession:
    """Emit a configured stream and expose the HeadlessRunner abort seam."""

    def __init__(
        self,
        *,
        events: list[AgentStreamEventDAO],
        session_id: str,
        wait_for_abort_before_terminal: bool = False,
    ) -> None:
        """Store the deterministic model/network-boundary event script.

        WHAT: Creates a minimal session double with the public methods consumed
            by HeadlessRunner.
        WHO: The b.2 headless exercise injects it at session construction.
        WHEN: For one test only; it is not a reusable generic harness.

        Args:
            events (list[AgentStreamEventDAO]): Ordered stream events to relay.
            session_id (str): Stable session identity used in lifecycle output.
            wait_for_abort_before_terminal (bool, optional): Hold the terminal
                event until HeadlessRunner calls abort. Defaults to False.
        """
        self.session_id: str = session_id
        self._events: list[AgentStreamEventDAO] = events
        self._subscribers: list[AgentEventSubscriber] = []
        self._wait_for_abort_before_terminal: bool = wait_for_abort_before_terminal
        self._abort_requested: asyncio.Event = asyncio.Event()
        self.abort_calls: int = 0

    def subscribe(self, *, handler: AgentEventSubscriber) -> None:
        """Register one runner subscriber.

        WHAT: Preserves the session callback ordering HeadlessRunner depends on.
        WHO: HeadlessRunner.invoke calls it before consuming the stream.
        WHEN: Once for the baseline headless capture.

        Args:
            handler (AgentEventSubscriber): Coroutine recipient for each event.
        """
        self._subscribers.append(handler)

    def abort(self) -> None:
        """Record a cooperative abort request.

        WHAT: Exposes the normal session abort behavior without provider work.
        WHO: HeadlessRunner watchdog/signal control calls it when requested.
        WHEN: Available for the baseline's abort semantics assertion.
        """
        self.abort_calls += 1
        self._abort_requested.set()

    async def invoke(self, *, text: str) -> AsyncIterator[AgentStreamEventDAO]:
        """Relay every configured event in source order.

        WHAT: Invokes subscribers before yielding each event, matching the live
            Slo session ordering consumed by HeadlessRunner.
        WHO: HeadlessRunner's session-drain task consumes this async generator.
        WHEN: Once per baseline headless prompt.

        Args:
            text (str): Prompt supplied by HeadlessRunner; retained as part of
                the public contract but does not alter this fixed script.

        Yields:
            AgentStreamEventDAO: Configured stream event in original order.
        """
        del text
        for event in self._events:
            await self._wait_for_abort_before_terminal_event(event=event)
            for subscriber in self._subscribers:
                await subscriber(event)
            yield event

    async def _wait_for_abort_before_terminal_event(self, *, event: AgentStreamEventDAO) -> None:
        """Hold the scripted terminal event until the runner requests abort.

        Args:
            event (AgentStreamEventDAO): Next scripted event to evaluate.
        """
        if not self._wait_for_abort_before_terminal or not event.is_terminal:
            return
        await self._abort_requested.wait()
