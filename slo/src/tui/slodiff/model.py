"""Pure, clean-room diff model for slodiff with stdlib-only dependencies."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import StrEnum


class FileStateKind(StrEnum):
    """Describe a worktree file's state relative to its HEAD version."""

    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class DiffOpcodeDAO:
    """Represent one named stdlib difflib opcode span."""

    tag: str
    base_start: int
    base_end: int
    changed_start: int
    changed_end: int


@dataclass(frozen=True, slots=True)
class DiffHunkDAO:
    """Represent adjacent diff opcode rows with surrounding line context."""

    opcodes: list[DiffOpcodeDAO]


@dataclass(frozen=True, slots=True)
class SloDiffModel:
    """Hold the pure before-versus-after model consumed by SloDiffView."""

    hunks: list[DiffHunkDAO]
    addition_count: int
    removal_count: int
    base_lines: list[str]
    changed_lines: list[str]

    @classmethod
    def build(
        cls,
        *,
        base_content: str,
        changed_content: str,
        context_lines: int = 3,
    ) -> "SloDiffModel":
        """Build grouped line differences for SloDiffView during threaded preparation.

        Args:
            base_content (str): Original text, or empty text for an added file.
            changed_content (str): Changed text, or empty text for a deleted file.
            context_lines (int): Equal lines retained around each changed hunk.

        Returns:
            SloDiffModel: Typed hunks, counts, and line-preserving inputs.
        """
        base_lines: list[str] = base_content.splitlines(keepends=True)
        changed_lines: list[str] = changed_content.splitlines(keepends=True)
        hunks: list[DiffHunkDAO] = cls._build_hunks(
            base_lines=base_lines,
            changed_lines=changed_lines,
            context_lines=context_lines,
        )
        addition_count, removal_count = cls._count_hunks(hunks=hunks)
        return cls(
            hunks=hunks,
            addition_count=addition_count,
            removal_count=removal_count,
            base_lines=base_lines,
            changed_lines=changed_lines,
        )

    @classmethod
    def _build_hunks(
        cls,
        *,
        base_lines: list[str],
        changed_lines: list[str],
        context_lines: int,
    ) -> list[DiffHunkDAO]:
        """Group difflib opcode rows while SloDiffModel.build constructs the model.

        Args:
            base_lines (list[str]): Original line-preserving sequence.
            changed_lines (list[str]): Changed line-preserving sequence.
            context_lines (int): Equal context lines to retain per hunk.

        Returns:
            list[DiffHunkDAO]: Ordered grouped opcode rows.
        """
        matcher = difflib.SequenceMatcher(isjunk=None, a=base_lines, b=changed_lines, autojunk=False)
        return [
            DiffHunkDAO(
                opcodes=[
                    DiffOpcodeDAO(
                        tag=tag,
                        base_start=base_start,
                        base_end=base_end,
                        changed_start=changed_start,
                        changed_end=changed_end,
                    )
                    for tag, base_start, base_end, changed_start, changed_end in opcode_group
                ]
            )
            for opcode_group in matcher.get_grouped_opcodes(n=context_lines)
        ]

    @classmethod
    def _count_hunks(cls, *, hunks: list[DiffHunkDAO]) -> tuple[int, int]:
        """Count changed-side additions and base-side removals after hunk construction.

        Args:
            hunks (list[DiffHunkDAO]): Grouped opcode rows to count.

        Returns:
            tuple[int, int]: Added and removed line counts, in that order.
        """
        additions: int = sum(
            opcode.changed_end - opcode.changed_start
            for hunk in hunks
            for opcode in hunk.opcodes
            if opcode.tag in ("insert", "replace")
        )
        removals: int = sum(
            opcode.base_end - opcode.base_start
            for hunk in hunks
            for opcode in hunk.opcodes
            if opcode.tag in ("delete", "replace")
        )
        return additions, removals
