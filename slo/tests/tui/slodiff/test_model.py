"""Tests for the pure slodiff diff model."""

from __future__ import annotations

import ast
from pathlib import Path

from src.tui.slodiff.model import DiffHunkDAO, DiffOpcodeDAO, FileStateKind, SloDiffModel

_CORE_DIRECTORY: Path = Path(__file__).resolve().parents[3] / "src" / "tui" / "slodiff"
_ALLOWED_THIRD_PARTY_IMPORT_ROOTS: frozenset[str] = frozenset({"rich", "textual"})


def _third_party_import_roots(*, source: str) -> set[str]:
    """Return non-stdlib absolute import roots declared by one core module.

    Args:
        source (str): Python source from a slodiff module.

    Returns:
        set[str]: Imported roots that are not resolved by Python's standard library.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source=source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            roots.add(node.module.partition(".")[0])
    return {root for root in roots if root not in __import__("sys").stdlib_module_names}


class TestSloDiffCoreDependencyBoundary:
    """Regression coverage for the extractable core's import contract."""

    def test_core_modules_when_parsed_import_only_textual_or_rich_third_parties(self) -> None:
        """The clean-room core has no Slo or unapproved third-party import roots."""
        imported_roots: set[str] = set()
        for module_path in _CORE_DIRECTORY.glob("*.py"):
            imported_roots.update(_third_party_import_roots(source=module_path.read_text(encoding="utf-8")))

        assert imported_roots <= _ALLOWED_THIRD_PARTY_IMPORT_ROOTS


class TestSloDiffModelBuild:
    """Decision-path coverage for SloDiffModel.build."""

    def test_build_when_identical_returns_no_hunks(self) -> None:
        """Identical content produces no changed hunk or counts."""
        model = SloDiffModel.build(base_content="same\n", changed_content="same\n")
        assert model.hunks == []
        assert model.addition_count == 0
        assert model.removal_count == 0

    def test_build_when_line_added_counts_addition(self) -> None:
        """An inserted line increments additions only."""
        model = SloDiffModel.build(base_content="a\n", changed_content="a\nb\n")
        assert model.addition_count == 1
        assert model.removal_count == 0

    def test_build_when_line_removed_counts_removal(self) -> None:
        """A removed line increments removals only."""
        model = SloDiffModel.build(base_content="a\nb\n", changed_content="a\n")
        assert model.addition_count == 0
        assert model.removal_count == 1

    def test_build_when_both_empty_returns_no_hunks(self) -> None:
        """Two empty documents have no changed hunks."""
        assert SloDiffModel.build(base_content="", changed_content="").hunks == []

    def test_build_when_base_empty_all_lines_are_additions(self) -> None:
        """An added file counts every changed line."""
        model = SloDiffModel.build(base_content="", changed_content="a\nb\n")
        assert (model.addition_count, model.removal_count) == (2, 0)

    def test_build_when_changed_empty_all_lines_are_removals(self) -> None:
        """A deleted file counts every base line."""
        model = SloDiffModel.build(base_content="a\nb\n", changed_content="")
        assert (model.addition_count, model.removal_count) == (0, 2)

    def test_build_when_line_replaced_counts_both(self) -> None:
        """A replacement increments addition and removal counts."""
        model = SloDiffModel.build(base_content="old\n", changed_content="new\n")
        assert (model.addition_count, model.removal_count) == (1, 1)

    def test_build_when_modified_populates_hunks(self) -> None:
        """A changed document exposes typed hunk and opcode objects."""
        model = SloDiffModel.build(base_content="a\nb\nc\n", changed_content="a\nX\nc\n")
        assert all(isinstance(hunk, DiffHunkDAO) for hunk in model.hunks)
        assert all(isinstance(opcode, DiffOpcodeDAO) for hunk in model.hunks for opcode in hunk.opcodes)

    def test_build_keeps_line_endings(self) -> None:
        """The raw model lines preserve source line endings."""
        model = SloDiffModel.build(base_content="a\n", changed_content="a\nb\n")
        assert model.changed_lines == ["a\n", "b\n"]


class TestFileStateKind:
    """Stable enum-value coverage."""

    def test_file_state_kind_values_are_stable_strings(self) -> None:
        """The public enum serializes to the specified stable values."""
        assert FileStateKind.MODIFIED == "modified"
        assert FileStateKind.ADDED == "added"
        assert FileStateKind.DELETED == "deleted"
        assert FileStateKind.UNCHANGED == "unchanged"
