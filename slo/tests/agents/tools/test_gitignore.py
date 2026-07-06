"""Tests for ``src.agents.tools._gitignore`` (sub-spec 01.c §5.2)."""
import pytest

from src.agents.tools._gitignore import GitignoreFilter
from pathlib import Path


@pytest.fixture
def repo_tree(tmp_path: Path):
    """Build a small repo:

    tmp_path/
      .git/                                 (sentinel marker)
      .gitignore                            ('node_modules/', '*.pyc')
      src/
        .gitignore                          ('local_*.py')
        keep.py
        local_secret.py
        also.pyc
      node_modules/
        foo.txt
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / ".gitignore").write_text("local_*.py\n")
    (tmp_path / "src" / "keep.py").write_text("")
    (tmp_path / "src" / "local_secret.py").write_text("")
    (tmp_path / "src" / "also.pyc").write_text("")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "foo.txt").write_text("")
    return tmp_path


def test_top_level_gitignore_applies(repo_tree: Path) -> None:
    filt = GitignoreFilter.load_for(search_root=repo_tree)
    assert filt.is_ignored(path=repo_tree / "node_modules" / "foo.txt") is True
    assert filt.is_ignored(path=repo_tree / "src" / "also.pyc") is True
    assert filt.is_ignored(path=repo_tree / "src" / "keep.py") is False


def test_nested_gitignore_applies(repo_tree: Path) -> None:
    filt = GitignoreFilter.load_for(search_root=repo_tree / "src")
    assert filt.is_ignored(path=repo_tree / "src" / "local_secret.py") is True
    assert filt.is_ignored(path=repo_tree / "src" / "keep.py") is False


def test_dot_git_always_ignored(repo_tree: Path) -> None:
    filt = GitignoreFilter.load_for(search_root=repo_tree)
    assert filt.is_ignored(path=repo_tree / ".git" / "HEAD") is True
