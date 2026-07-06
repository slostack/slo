"""Tests for the ``echo`` tool (sub-spec 01.e §5.4)."""
import pytest

from src.agents.tools.echo import echo_tool


@pytest.mark.asyncio
async def test_echo_returns_input() -> None:
    assert await echo_tool.ainvoke({"text": "hello"}) == "hello"


@pytest.mark.asyncio
async def test_echo_handles_empty_string() -> None:
    assert await echo_tool.ainvoke({"text": ""}) == ""


@pytest.mark.asyncio
async def test_echo_unicode_passthrough() -> None:
    payload = "résumé · café · 日本語"
    assert await echo_tool.ainvoke({"text": payload}) == payload


def test_echo_tool_metadata() -> None:
    assert echo_tool.name == "echo"
    assert "Echo the input text back unchanged" in echo_tool.description
