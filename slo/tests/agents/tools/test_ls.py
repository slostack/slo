"""Tests for the ``ls`` tool (sub-spec 01.e §5.3)."""
from pathlib import Path

import pytest

from src.agents.tools.ls import ls_tool


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "a.py").write_text("")
    (tmp_path / ".env").write_text("")
    return tmp_path


@pytest.mark.asyncio
async def test_ls_includes_dotfiles_and_dir_suffix(repo: Path) -> None:
    result = await ls_tool.ainvoke({"path": str(repo)})
    lines = result.splitlines()
    assert ".env" in lines
    assert "a.py" in lines
    assert "src/" in lines


@pytest.mark.asyncio
async def test_ls_sorted(repo: Path) -> None:
    result = await ls_tool.ainvoke({"path": str(repo)})
    lines = result.splitlines()
    assert lines == sorted(lines)


@pytest.mark.asyncio
async def test_ls_missing_returns_error(tmp_path: Path) -> None:
    result = await ls_tool.ainvoke({"path": str(tmp_path / "nope")})
    assert "not found" in result


@pytest.mark.asyncio
async def test_ls_not_a_directory_returns_error(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("")
    result = await ls_tool.ainvoke({"path": str(file)})
    assert "not a directory" in result


def test_ls_tool_metadata() -> None:
    assert ls_tool.name == "ls"
    assert "List directory contents" in ls_tool.description
