"""Tests for the ``grep`` tool (sub-spec 01.e §5.1)."""
from pathlib import Path

import pytest

from src.agents.tools.grep import grep_tool


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Tiny repo with two src files and one gitignored file."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "src" / "b.py").write_text("def bar():\n    return foo()\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "secret.py").write_text("def foo():\n    pass\n")
    return tmp_path


@pytest.mark.asyncio
async def test_grep_finds_matches(repo: Path) -> None:
    result = await grep_tool.ainvoke({"pattern": "def foo", "path": str(repo)})
    assert "a.py" in result
    assert "secret.py" not in result   # gitignored
    assert "b.py" not in result        # no match for 'def foo'


@pytest.mark.asyncio
async def test_grep_literal_mode(repo: Path) -> None:
    result = await grep_tool.ainvoke({
        "pattern": "return 1",
        "path": str(repo),
        "literal": True,
    })
    assert "return 1" in result


@pytest.mark.asyncio
async def test_grep_case_insensitive(repo: Path) -> None:
    (repo / "src" / "c.py").write_text("DEF baz():\n")
    result = await grep_tool.ainvoke({
        "pattern": "def baz",
        "path": str(repo),
        "ignoreCase": True,
    })
    assert "c.py" in result


@pytest.mark.asyncio
async def test_grep_glob_filter(repo: Path) -> None:
    (repo / "src" / "skip.txt").write_text("def foo():\n")
    result = await grep_tool.ainvoke({
        "pattern": "def foo",
        "path": str(repo),
        "glob": "**/*.py",
    })
    assert "a.py" in result
    assert "skip.txt" not in result


@pytest.mark.asyncio
async def test_grep_limit(repo: Path) -> None:
    for i in range(150):
        (repo / "src" / f"f{i}.py").write_text("def foo():\n")
    result = await grep_tool.ainvoke({
        "pattern": "def foo",
        "path": str(repo),
        "limit": 10,
    })
    assert "limit reached" in result


@pytest.mark.asyncio
async def test_grep_invalid_regex_errors() -> None:
    result = await grep_tool.ainvoke({"pattern": "(unclosed"})
    assert "invalid regex" in result


def test_grep_tool_metadata() -> None:
    assert grep_tool.name == "grep"
    assert "Search file contents for a pattern" in grep_tool.description
