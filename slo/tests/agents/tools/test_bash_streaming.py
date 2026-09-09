"""Tests for core Bash partial-output streaming."""

from __future__ import annotations

import asyncio

import pytest

from src.agents.tools.bash import BashTool
from src.agents.tools.tool_output import ToolOutputUpdateDAO


@pytest.mark.asyncio
async def test_bash_emits_accumulated_snapshot_before_terminal_result() -> None:
    """A slow command publishes a display snapshot before its final output returns."""
    snapshots: list[ToolOutputUpdateDAO] = []

    async def on_update(*, snapshot: ToolOutputUpdateDAO) -> None:
        """Collect a partial snapshot from the Bash read loop.

        Args:
            snapshot (ToolOutputUpdateDAO): Latest accumulated output state.
        """
        snapshots.append(snapshot)

    terminal_result: asyncio.Task[str] = asyncio.create_task(
        BashTool.invoke(
            command="for i in 1 2 3; do echo $i; sleep 0.06; done",
            on_update=on_update,
            tool_call_id="call-1",
        )
    )

    await asyncio.wait_for(_wait_for_snapshot_count(snapshots=snapshots, minimum_count=1), timeout=1)
    assert not terminal_result.done()
    result: str = await terminal_result

    assert snapshots
    assert snapshots[-1].tool_call_id == "call-1"
    assert snapshots[-1].tool_name == "bash"
    assert "1" in snapshots[-1].content_snapshot
    assert "3" in snapshots[-1].content_snapshot
    assert snapshots[-1].content_snapshot == result


async def _wait_for_snapshot_count(*, snapshots: list[ToolOutputUpdateDAO], minimum_count: int) -> None:
    """Yield until a Bash invocation has published the requested snapshot count.

    WHAT: Polls the in-memory test observer without adding synchronization to
        production Bash code.
    WHO: Used by the mid-run regression test before it awaits terminal output.
    WHEN: While the spawned shell is intentionally still running.

    Args:
        snapshots (list[ToolOutputUpdateDAO]): Snapshots observed by the test sink.
        minimum_count (int): Number of snapshots required before returning.
    """
    while len(snapshots) < minimum_count:
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_bash_without_update_callback_preserves_terminal_output() -> None:
    """The legacy no-subscriber path remains a normal terminal Bash invocation."""
    result: str = await BashTool.invoke(command="printf legacy")

    assert result == "exit_code: 0\nlegacy"


@pytest.mark.asyncio
async def test_bash_does_not_wait_for_slow_update_consumer() -> None:
    """A slow display consumer cannot block subprocess reading or terminal completion."""
    started: asyncio.Event = asyncio.Event()

    async def on_update(*, snapshot: ToolOutputUpdateDAO) -> None:
        """Simulate a slow consumer after proving it received one snapshot.

        Args:
            snapshot (ToolOutputUpdateDAO): Latest accumulated output state.
        """
        started.set()
        await asyncio.sleep(0.4)

    task: asyncio.Task[str] = asyncio.create_task(
        BashTool.invoke(
            command="echo first; sleep 0.02; echo second",
            on_update=on_update,
            tool_call_id="call-2",
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    result: str = await asyncio.wait_for(task, timeout=0.25)

    assert "second" in result
