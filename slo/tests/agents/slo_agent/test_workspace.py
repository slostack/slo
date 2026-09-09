"""Unit tests for ``VscodeWorkspaceLoader`` (feature 24.a.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.slo_agent.workspace.dao import WorkspaceFileParseError, WorkspaceFolderDAO
from src.agents.slo_agent.workspace.service import VscodeWorkspaceLoader


class TestReadsValidWorkspaceFile:
    """Loader parses well-formed workspace files."""

    def test_returns_dao_list_in_declared_order(self, tmp_path: Path) -> None:
        """Folders are returned in declaration order with resolved paths."""
        folder_a: Path = tmp_path / "alpha"
        folder_b: Path = tmp_path / "beta"
        folder_a.mkdir()
        folder_b.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            json.dumps(
                {
                    "folders": [
                        {"name": "Alpha", "path": "alpha"},
                        {"path": "beta"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [
            WorkspaceFolderDAO(path=folder_a.resolve(), display_name="Alpha"),
            WorkspaceFolderDAO(path=folder_b.resolve(), display_name=None),
        ]

    def test_supports_absolute_folder_paths(self, tmp_path: Path) -> None:
        """Absolute ``folders[].path`` values are preserved as absolute paths."""
        external: Path = tmp_path / "external"
        external.mkdir()
        workspace_file: Path = tmp_path / "scoped" / "x.code-workspace"
        workspace_file.parent.mkdir()
        workspace_file.write_text(
            json.dumps({"folders": [{"path": str(external)}]}),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [WorkspaceFolderDAO(path=external.resolve(), display_name=None)]


class TestSkipsMissingFolders:
    """Missing folders are dropped while valid folders remain."""

    def test_drops_missing_folder_and_keeps_existing(self, tmp_path: Path) -> None:
        """Missing-on-disk folders are excluded from the result set."""
        present: Path = tmp_path / "present"
        present.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            json.dumps(
                {
                    "folders": [
                        {"path": "present"},
                        {"path": "missing"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [WorkspaceFolderDAO(path=present.resolve(), display_name=None)]


class TestRejectsMalformedFiles:
    """Malformed files raise ``WorkspaceFileParseError``."""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """A non-existent file path produces an actionable parse error."""
        workspace_file: Path = tmp_path / "missing.code-workspace"

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert exc_info.value.workspace_file == workspace_file
        assert "cannot read file" in exc_info.value.reason

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        """Malformed JSON raises with strict-parser line information."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text("{ not json", encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "malformed JSON/JSONC" in exc_info.value.reason
        assert "line" in exc_info.value.reason

    def test_root_must_be_object(self, tmp_path: Path) -> None:
        """A top-level array is rejected because the root must be an object."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text("[]", encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "root JSON value must be an object" in exc_info.value.reason

    def test_missing_folders_array_raises(self, tmp_path: Path) -> None:
        """A workspace file without ``folders`` is rejected."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text("{}", encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "missing required 'folders' array" in exc_info.value.reason

    def test_folders_must_be_a_list(self, tmp_path: Path) -> None:
        """A non-list ``folders`` value is rejected."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": {}}', encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "'folders' must be an array" in exc_info.value.reason

    def test_folder_entry_must_have_path(self, tmp_path: Path) -> None:
        """A folder entry missing ``path`` is rejected."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": [{"name": "x"}]}', encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "missing required string 'path'" in exc_info.value.reason


class TestEmptyFoldersArray:
    """An empty folders array is valid and returns an empty result."""

    def test_empty_folders_returns_empty_list(self, tmp_path: Path) -> None:
        """Empty ``folders`` yields an empty result without raising."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == []


class TestJsoncTolerance:
    """JSONC syntax is accepted via the ``json5`` fallback."""

    def test_line_comments_are_accepted(self, tmp_path: Path) -> None:
        """`//` comments do not break workspace parsing."""
        folder: Path = tmp_path / "f"
        folder.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            ("{\n" "  // comment\n" '  "folders": [\n' '    { "path": "f" }\n' "  ]\n" "}"),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [WorkspaceFolderDAO(path=folder.resolve(), display_name=None)]

    def test_block_comments_are_accepted(self, tmp_path: Path) -> None:
        """`/* ... */` comments do not break workspace parsing."""
        folder: Path = tmp_path / "f"
        folder.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            ("{\n" "  /* block comment */\n" '  "folders": [{ "path": "f" }]\n' "}"),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [WorkspaceFolderDAO(path=folder.resolve(), display_name=None)]

    def test_trailing_commas_are_accepted(self, tmp_path: Path) -> None:
        """Trailing commas in arrays and objects are accepted."""
        folder_a: Path = tmp_path / "a"
        folder_b: Path = tmp_path / "b"
        folder_a.mkdir()
        folder_b.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            ("{\n" '  "folders": [\n' '    { "path": "a", },\n' '    { "path": "b", },\n' "  ],\n" "}"),
            encoding="utf-8",
        )

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [
            WorkspaceFolderDAO(path=folder_a.resolve(), display_name=None),
            WorkspaceFolderDAO(path=folder_b.resolve(), display_name=None),
        ]

    def test_strict_json_does_not_invoke_json5(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Clean JSON files stay on the strict fast path and skip ``json5``."""
        import src.agents.slo_agent.workspace.service as workspace_module

        folder: Path = tmp_path / "f"
        folder.mkdir()
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text(
            json.dumps({"folders": [{"path": "f"}]}),
            encoding="utf-8",
        )
        call_count: dict[str, int] = {"count": 0}
        original_loads = workspace_module.json5.loads

        def _counting_loads(*args, **kwargs):
            call_count["count"] += 1
            return original_loads(*args, **kwargs)

        monkeypatch.setattr(workspace_module.json5, "loads", _counting_loads)

        result: list[WorkspaceFolderDAO] = VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert result == [WorkspaceFolderDAO(path=folder.resolve(), display_name=None)]
        assert call_count["count"] == 0

    def test_double_failure_surfaces_strict_error(self, tmp_path: Path) -> None:
        """When both parsers fail, the strict parser's message is preserved."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text("this is not json at all", encoding="utf-8")

        with pytest.raises(WorkspaceFileParseError) as exc_info:
            VscodeWorkspaceLoader.invoke(workspace_file=workspace_file)

        assert "malformed JSON/JSONC" in exc_info.value.reason
        assert "line" in exc_info.value.reason
        assert "column" in exc_info.value.reason
