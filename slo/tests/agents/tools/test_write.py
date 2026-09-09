"""Tests for the ``write`` tool (sub-spec 01.d §5.2)."""

import pytest

from src.agents.tools.write import write_tool
from pathlib import Path


@pytest.mark.asyncio
async def test_write_creates_new_file(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    result = await write_tool.ainvoke({"path": str(target), "content": "hello"})
    assert "Wrote 5 bytes" in result
    assert target.read_text() == "hello"


@pytest.mark.asyncio
async def test_write_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("old")
    await write_tool.ainvoke({"path": str(target), "content": "new"})
    assert target.read_text() == "new"


@pytest.mark.asyncio
async def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    await write_tool.ainvoke({"path": str(target), "content": "x"})
    assert target.read_text() == "x"


def test_write_tool_metadata() -> None:
    assert write_tool.name == "write"
    assert "Write content to a file" in write_tool.description
    assert "pass the complete file content inline" in write_tool.description


def test_write_schema_content_description_enforces_inline() -> None:
    """The content field description tells the model to pass content inline."""
    from src.agents.tools.write import WriteSchemaDAO

    content_field = WriteSchemaDAO.model_fields["content"]
    assert content_field.description is not None
    assert "inline" in content_field.description
    assert "do not output content as text first" in content_field.description
