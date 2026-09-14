"""``.gitignore``-aware path filtering for grep and find.

Walks from the search root up to the repo root (the first directory that
contains a ``.git`` directory), accumulating every ``.gitignore`` along
the way, and returns a ``GitignoreFilter`` callers can query.

Implementation notes:
- We use ``pathspec.GitIgnoreSpec`` (the modern pathspec API) for full
  gitwildmatch semantics including double-star, negation, and
  trailing-slash directory-only rules.
- Each ``.gitignore`` becomes one scoped spec — patterns are interpreted
  relative to the directory that contains the file, exactly as git does it.
  Deeper-nested patterns take precedence by being appended later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pathspec

__all__ = ["GitignoreFilter"]


@dataclass(frozen=True)
class _ScopedSpec:
    """A gitignore spec bound to the directory that defined it."""

    base: Path
    spec: pathspec.GitIgnoreSpec


@dataclass(frozen=True)
class GitignoreFilter:
    """Composite gitignore filter for a directory tree.

    Attributes:
        scoped: Per-directory gitignore specs, ordered shallow-to-deep so
            deeper rules win (they are appended later and override earlier
            matches).
        repo_root: The directory that owns the ``.git`` sentinel (or the
            search root resolved if no ``.git`` was found).
    """

    scoped: list[_ScopedSpec]
    repo_root: Path

    def is_ignored(self, path: Path) -> bool:
        """Return True iff ``path`` matches a gitignore pattern in scope.

        ``path`` may be relative or absolute. Patterns deeper in the tree
        win over shallower ones because they are appended later in
        :meth:`load_for`.

        Args:
            path: Path to test.

        Returns:
            True iff at least one in-scope gitignore spec matches ``path``.
        """
        absolute = path.resolve()
        matched = False
        for scope in self.scoped:
            try:
                rel = absolute.relative_to(scope.base)
            except ValueError:
                continue
            if scope.spec.match_file(str(rel)):
                matched = True
        return matched

    @classmethod
    def _find_repo_root(cls, *, start: Path) -> Path:
        """Walk up until a ``.git`` directory is found; return that directory.

        Falls back to the starting path resolution if no ``.git`` is found.

        Args:
            start: Directory to walk up from.

        Returns:
            The first ancestor (or ``start`` itself) that contains a
            ``.git`` directory; otherwise the resolved ``start``.
        """
        current = start.resolve()
        while True:
            if (current / ".git").exists():
                return current
            if current.parent == current:
                return start.resolve()
            current = current.parent

    @classmethod
    def load_for(cls, *, search_root: Path) -> "GitignoreFilter":
        """Build a filter for the given search root.

        Reads every ``.gitignore`` from the search root up to the repo root.
        Patterns from deeper-nested ``.gitignore`` files take precedence over
        shallower ones, mirroring git's resolution order.

        Args:
            search_root: Directory the caller intends to walk.

        Returns:
            A :class:`GitignoreFilter` ready for repeated ``is_ignored``
            queries.
        """
        repo_root = cls._find_repo_root(start=search_root)
        scoped: list[_ScopedSpec] = []

        current = search_root.resolve()
        while True:
            candidate = current / ".gitignore"
            if candidate.is_file():
                lines = candidate.read_text(encoding="utf-8", errors="ignore").splitlines()
                scoped.append(
                    _ScopedSpec(
                        base=current,
                        spec=pathspec.GitIgnoreSpec.from_lines(lines),
                    )
                )
            if current == repo_root or current.parent == current:
                break
            current = current.parent

        # Always ignore the .git directory itself.
        scoped.append(
            _ScopedSpec(
                base=repo_root,
                spec=pathspec.GitIgnoreSpec.from_lines([".git/"]),
            )
        )

        return cls(scoped=scoped, repo_root=repo_root)

    @classmethod
    def is_path_ignored(cls, *, path: Path, search_root: Path) -> bool:
        """Convenience: load and check in one call. For one-offs only.

        For repeated checks against the same root, call :meth:`load_for`
        once and reuse the filter — building a filter touches disk.

        Args:
            path: Path to test.
            search_root: Directory whose gitignore stack should be loaded.

        Returns:
            True iff ``path`` would be ignored under ``search_root``.
        """
        return cls.load_for(search_root=search_root).is_ignored(path=path)
