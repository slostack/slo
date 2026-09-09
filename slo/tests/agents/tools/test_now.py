"""Tests for the ``now`` tool (sub-spec 01.e §5.5)."""

import asyncio
import re
from datetime import datetime

import pytest

from src.agents.tools.now import now_tool


@pytest.mark.asyncio
async def test_now_returns_iso_8601() -> None:
    result = await now_tool.ainvoke({})
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result)
    assert "+00:00" in result or result.endswith("Z")


@pytest.mark.asyncio
async def test_now_round_trips_through_fromisoformat() -> None:
    result = await now_tool.ainvoke({})
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_now_monotonic_per_call() -> None:
    t1 = await now_tool.ainvoke({})
    await asyncio.sleep(0.001)
    t2 = await now_tool.ainvoke({})
    assert t2 >= t1


def test_now_tool_metadata() -> None:
    assert now_tool.name == "now"
    assert "current utc timestamp" in now_tool.description.lower()
