"""Actual thread leaves retain ownership through wrapper cancellation."""

import asyncio
import threading
from pathlib import Path

from src.agents.tools._blocking import run_blocking_tool_call


async def test_cancelled_offload_joins_actual_leaf(tmp_path: Path) -> None:
    """A cancelled wrapper cannot release its owner before a real file effect finishes."""
    entered = threading.Event()
    release = threading.Event()
    path = tmp_path / "leaf.txt"
    assert path.resolve().is_relative_to(tmp_path.resolve())

    def write_leaf() -> str:
        """Write only in this test's resolved temporary root after release."""
        entered.set()
        release.wait()
        path.write_text(data="completed", encoding="utf-8")
        return "completed"

    task = asyncio.create_task(coro=run_blocking_tool_call(func=write_leaf))
    try:
        async with asyncio.timeout(delay=5):
            while not entered.is_set():
                await asyncio.sleep(delay=0)
        task.cancel()
        await asyncio.sleep(delay=0.01)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(delay=0)
        assert not task.done()
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert path.read_text(encoding="utf-8") == "completed"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_offload_keeps_permit_until_real_leaf_finishes() -> None:
    """Repeated cancellation cannot admit a fifth thread while four real leaves are held."""
    from src.agents.tools._blocking import BLOCKING_TOOL_THREAD_LIMIT

    release = threading.Event()
    started: list[int] = []
    lock = threading.Lock()

    def leaf(*, index: int) -> int:
        """Hold the real worker slot without files, subprocesses or external effects."""
        with lock:
            started.append(index)
        release.wait()
        return index

    tasks = [
        asyncio.create_task(coro=run_blocking_tool_call(func=leaf, index=index))
        for index in range(BLOCKING_TOOL_THREAD_LIMIT + 1)
    ]
    try:
        async with asyncio.timeout(delay=5):
            while len(started) < BLOCKING_TOOL_THREAD_LIMIT:
                await asyncio.sleep(delay=0)
        tasks[0].cancel()
        await asyncio.sleep(delay=0)
        tasks[0].cancel()
        await asyncio.sleep(delay=0)
        assert len(started) == BLOCKING_TOOL_THREAD_LIMIT and not tasks[0].done()
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert len(started) == BLOCKING_TOOL_THREAD_LIMIT + 1
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
