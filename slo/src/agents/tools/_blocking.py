"""Shared thread-offload helpers for blocking local tool work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar
from weakref import WeakKeyDictionary

__all__ = [
    "BLOCKING_TOOL_THREAD_LIMIT",
    "run_blocking_tool_call",
]


BLOCKING_TOOL_THREAD_LIMIT: int = 4
"""Maximum number of concurrent blocking local-tool offloads per event loop.

The coding tools are mostly filesystem/PDF/image bound, so a small fixed cap keeps
Textual responsive without spawning an unbounded pile of worker threads during a
large read-only tool batch.
"""


T = TypeVar("T")


_LOOP_SEMAPHORES: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


async def run_blocking_tool_call(
    *,
    func: Callable[..., T],
    **kwargs: Any,
) -> T:
    """Run one blocking local-tool callable in a bounded worker thread.

    Args:
        func (Callable[..., T]): Synchronous callable to execute off the event loop.
        **kwargs (Any): Keyword arguments forwarded to ``func``.

    Returns:
        T: The callable's return value.
    """
    semaphore: asyncio.Semaphore = _semaphore_for_current_loop()
    async with semaphore:
        return await asyncio.to_thread(func, **kwargs)


def _semaphore_for_current_loop() -> asyncio.Semaphore:
    """Return the blocking-tool semaphore for the current event loop.

    ``asyncio.Semaphore`` instances bind to the first loop that awaits them,
    so the helper keeps one semaphore per loop rather than one process-global
    instance. That keeps pytest's per-test event loops and the interactive TUI
    loop isolated from each other while still enforcing a shared cap inside one
    loop.

    Returns:
        asyncio.Semaphore: The semaphore shared by blocking local-tool offloads
            on the current event loop.
    """
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    semaphore: asyncio.Semaphore | None = _LOOP_SEMAPHORES.get(loop)
    if semaphore is not None:
        return semaphore
    semaphore = asyncio.Semaphore(value=BLOCKING_TOOL_THREAD_LIMIT)
    _LOOP_SEMAPHORES[loop] = semaphore
    return semaphore
