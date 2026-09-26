"""Glob matching rule shared by the ``find`` and ``grep`` tools.

``Path.glob("*.py")`` only matches the search root's direct children, while
agents write ``*.py`` expecting ``find -name`` / ``rg -g`` semantics: match the
file name at any depth. A pattern with no ``/`` is therefore matched at every
depth; a pattern with a ``/`` (``src/*.py``, ``**/*.json``) keeps ``Path.glob``
semantics relative to the search root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

__all__ = ["GlobMatcher"]


class GlobMatcher:
    """Stateless namespace that resolves a tool glob pattern against a search root."""

    @classmethod
    def iter_matches(cls, *, root: Path, pattern: str) -> Iterator[Path]:
        """Yield every path under ``root`` that the tool glob ``pattern`` selects.

        WHO: Called by ``FindTool._invoke_sync`` and ``GrepTool._iter_files``.
        WHEN: Once per tool call, before gitignore filtering and truncation.

        Args:
            root (Path): Directory the search is rooted at.
            pattern (str): Tool glob pattern supplied by the model.

        Returns:
            Iterator[Path]: Matching files and directories, unfiltered.
        """
        if cls.is_basename_pattern(pattern=pattern):
            return root.rglob(pattern)
        return root.glob(pattern)

    @classmethod
    def is_basename_pattern(cls, *, pattern: str) -> bool:
        """Return True when ``pattern`` names files only, with no directory part.

        Args:
            pattern (str): Tool glob pattern supplied by the model.

        Returns:
            bool: True when the pattern contains no ``/`` separator.
        """
        return "/" not in pattern
