"""M2 queue-to-stream bridge test (75.a.5-CORE).

The emission bridge is named concretely here: an ``asyncio.Queue`` owned by the
graph build, whose items the agent loop drains via ``drain_tool_output_updates``
and yields as first-class ``tool_output_update`` stream events — mirroring how
every other event reaches subscribers.
"""

from __future__ import annotations

import asyncio

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.graph.service import drain_tool_output_updates
from src.agents.tools.tool_output import ToolOutputUpdateDAO


@pytest.mark.asyncio
async def test_queue_snapshots_drain_into_tool_output_update_stream_events() -> None:
    """Queued snapshots arrive on the stream as keyed, display-only events."""
    queue: asyncio.Queue[ToolOutputUpdateDAO] = asyncio.Queue()
    await queue.put(
        ToolOutputUpdateDAO(
            tool_call_id="call-1",
            tool_name="bash",
            content_snapshot="exit_code: 0\nworking",
            truncated=True,
            full_output_path="/tmp/spill.txt",
        )
    )
    await queue.put(
        ToolOutputUpdateDAO(
            tool_call_id="call-2",
            tool_name="bash",
            content_snapshot="exit_code: 0\nmore",
        )
    )

    events: list[AgentStreamEventDAO] = [
        event async for event in drain_tool_output_updates(output_update_queue=queue, iteration=3)
    ]

    assert len(events) == 2
    first, second = events
    assert first.kind == "tool_output_update"
    assert first.iteration == 3
    assert first.tool_call_id == "call-1"
    assert first.tool_name == "bash"
    assert first.content == "exit_code: 0\nworking"
    assert first.metadata == {"truncated": True, "full_output_path": "/tmp/spill.txt"}
    assert second.tool_call_id == "call-2"
    assert queue.empty()


@pytest.mark.asyncio
async def test_drain_of_empty_queue_yields_nothing() -> None:
    """An empty bridge queue produces no events."""
    queue: asyncio.Queue[ToolOutputUpdateDAO] = asyncio.Queue()

    events: list[AgentStreamEventDAO] = [
        event async for event in drain_tool_output_updates(output_update_queue=queue, iteration=0)
    ]

    assert events == []
