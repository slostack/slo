"""Tests for the ``edit`` tool (sub-spec 01.d §5.3)."""

import pytest

from src.agents.tools.edit import edit_tool
from pathlib import Path


@pytest.mark.asyncio
async def test_edit_single_unique_match(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("def foo():\n    return 1\n")
    result = await edit_tool.ainvoke(
        {
            "path": str(target),
            "edits": [{"oldText": "return 1", "newText": "return 2"}],
        }
    )
    assert "Applied 1 edit" in result
    assert target.read_text() == "def foo():\n    return 2\n"


@pytest.mark.asyncio
async def test_edit_zero_matches_errors(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("def foo():\n    return 1\n")
    result = await edit_tool.ainvoke(
        {
            "path": str(target),
            "edits": [{"oldText": "missing", "newText": "x"}],
        }
    )
    assert "oldText not found" in result


@pytest.mark.asyncio
async def test_edit_multiple_matches_errors(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\nx = 1\n")
    result = await edit_tool.ainvoke(
        {
            "path": str(target),
            "edits": [{"oldText": "x = 1", "newText": "x = 2"}],
        }
    )
    assert "matches 2 times" in result


@pytest.mark.asyncio
async def test_edit_overlapping_errors(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("alpha beta gamma\n")
    result = await edit_tool.ainvoke(
        {
            "path": str(target),
            "edits": [
                {"oldText": "alpha beta", "newText": "A B"},
                {"oldText": "beta gamma", "newText": "B G"},
            ],
        }
    )
    assert "overlapping edits" in result


@pytest.mark.asyncio
async def test_edit_multiple_non_overlapping(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("line1\nline2\nline3\n")
    result = await edit_tool.ainvoke(
        {
            "path": str(target),
            "edits": [
                {"oldText": "line1", "newText": "LINE1"},
                {"oldText": "line3", "newText": "LINE3"},
            ],
        }
    )
    assert "Applied 2 edit" in result
    assert target.read_text() == "LINE1\nline2\nLINE3\n"


@pytest.mark.asyncio
async def test_edit_missing_file_errors(tmp_path: Path) -> None:
    result = await edit_tool.ainvoke(
        {
            "path": str(tmp_path / "missing.txt"),
            "edits": [{"oldText": "x", "newText": "y"}],
        }
    )
    assert "file not found" in result


@pytest.mark.asyncio
async def test_edit_empty_edits_list_errors(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("content")
    result = await edit_tool.ainvoke({"path": str(target), "edits": []})
    assert "edits list is empty" in result


def test_edit_tool_metadata() -> None:
    assert edit_tool.name == "edit"
    assert "Edit a single file using exact text replacement" in edit_tool.description
