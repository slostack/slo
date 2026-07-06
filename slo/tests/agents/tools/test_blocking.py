"""Tests for ``src.agents.tools._blocking``."""

from __future__ import annotations

import asyncio
import threading
import time
from weakref import WeakKeyDictionary

import pytest

import src.agents.tools._blocking as blocking


def _add(*, left: int, right: int) -> int:
    """Return the sum of two integers."""
    return left + right


def _recording_sleep(
    *,
    state: dict[str, int],
    lock: threading.Lock,
    delay: float,
) -> int:
    """Sleep while recording concurrent worker-thread occupancy."""
    with lock:
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
    time.sleep(delay)
    with lock:
        state["active"] -= 1
    return 1


@pytest.mark.asyncio
async def test_run_blocking_tool_call_returns_callable_result() -> None:
    """The helper should return the blocking callable's result."""
    result: int = await blocking.run_blocking_tool_call(
        func=_add,
        left=2,
        right=3,
    )

    assert result == 5


@pytest.mark.asyncio
async def test_run_blocking_tool_call_limits_concurrent_offloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper should cap concurrent thread offloads with one semaphore."""
    monkeypatch.setattr(blocking, "BLOCKING_TOOL_THREAD_LIMIT", 2)
    monkeypatch.setattr(blocking, "_LOOP_SEMAPHORES", WeakKeyDictionary())

    state: dict[str, int] = {"active": 0, "max_active": 0}
    lock: threading.Lock = threading.Lock()
    tasks: list[asyncio.Task[int]] = [
        asyncio.create_task(
            blocking.run_blocking_tool_call(
                func=_recording_sleep,
                state=state,
                lock=lock,
                delay=0.05,
            )
        )
        for _ in range(6)
    ]

    results: list[int] = await asyncio.gather(*tasks)

    assert sum(results) == 6
    assert state["max_active"] == 2
