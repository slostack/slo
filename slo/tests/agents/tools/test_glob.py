"""Tests for ``src.agents.tools._glob`` — the glob rule shared by find and grep."""

from pathlib import Path

import pytest

from src.agents.tools._glob import GlobMatcher


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Build a small nested tree:

    tmp_path/
      top.py
      src/
        a.py
        notes.txt
        deep/
          b.py
    """
    (tmp_path / "top.py").write_text("")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "src" / "notes.txt").write_text("")
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "deep" / "b.py").write_text("")
    return tmp_path


def _relative_paths(*, root: Path, matches: list[Path]) -> set[str]:
    """Render matches as POSIX paths relative to ``root`` for set comparison."""
    return {match.relative_to(root).as_posix() for match in matches}


def test_iter_matches_when_pattern_is_basename_matches_every_depth(tree: Path) -> None:
    matches: list[Path] = list(GlobMatcher.iter_matches(root=tree, pattern="*.py"))

    assert _relative_paths(root=tree, matches=matches) == {"top.py", "src/a.py", "src/deep/b.py"}


def test_iter_matches_when_pattern_has_directory_part_matches_relative_to_root(tree: Path) -> None:
    matches: list[Path] = list(GlobMatcher.iter_matches(root=tree, pattern="src/*.py"))

    assert _relative_paths(root=tree, matches=matches) == {"src/a.py"}


def test_iter_matches_when_pattern_has_double_star_keeps_recursive_semantics(tree: Path) -> None:
    matches: list[Path] = list(GlobMatcher.iter_matches(root=tree, pattern="**/*.py"))

    assert _relative_paths(root=tree, matches=matches) == {"top.py", "src/a.py", "src/deep/b.py"}


def test_is_basename_pattern_when_pattern_has_no_separator() -> None:
    assert GlobMatcher.is_basename_pattern(pattern="*.py") is True


def test_is_basename_pattern_when_pattern_has_separator() -> None:
    assert GlobMatcher.is_basename_pattern(pattern="src/*.py") is False
