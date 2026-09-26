"""Tests for the ``find`` tool (sub-spec 01.e §5.2)."""

from pathlib import Path

import pytest

from src.agents.tools.find import find_tool


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Tiny repo with two src files and one gitignored output dir."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("dist/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "src" / "b.py").write_text("")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "out.py").write_text("")
    return tmp_path


@pytest.mark.asyncio
async def test_find_matches_glob(repo: Path) -> None:
    result = await find_tool.ainvoke({"pattern": "**/*.py", "path": str(repo)})
    assert "src/a.py" in result
    assert "src/b.py" in result
    assert "dist/out.py" not in result  # gitignored


@pytest.mark.asyncio
async def test_find_when_pattern_is_basename_matches_nested_files(repo: Path) -> None:
    """Regression: '*.py' used to match only the search root's direct children."""
    result = await find_tool.ainvoke({"pattern": "*.py", "path": str(repo)})
    assert "src/a.py" in result
    assert "src/b.py" in result
    assert "dist/out.py" not in result  # gitignored


@pytest.mark.asyncio
async def test_find_when_pattern_has_directory_part_matches_only_that_level(repo: Path) -> None:
    (repo / "src" / "deep").mkdir()
    (repo / "src" / "deep" / "c.py").write_text("")
    result = await find_tool.ainvoke({"pattern": "src/*.py", "path": str(repo)})
    assert "src/a.py" in result
    assert "src/deep/c.py" not in result


@pytest.mark.asyncio
async def test_find_empty_returns_message(repo: Path) -> None:
    result = await find_tool.ainvoke({"pattern": "**/*.rs", "path": str(repo)})
    assert "no files matching" in result


@pytest.mark.asyncio
async def test_find_not_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("")
    result = await find_tool.ainvoke({"pattern": "*", "path": str(file)})
    assert "not a directory" in result


def test_find_tool_metadata() -> None:
    assert find_tool.name == "find"
    assert "Search for files by glob pattern" in find_tool.description
