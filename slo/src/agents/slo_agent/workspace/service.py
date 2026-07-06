"""VscodeWorkspaceLoader service — loads resolved folders from a VSCode workspace file."""
from __future__ import annotations

import json
from pathlib import Path

import json5

from config.logger import log_info
from src.agents.slo_agent.workspace.dao import WorkspaceFileParseError, WorkspaceFolderDAO


__all__ = ["VscodeWorkspaceLoader"]


class VscodeWorkspaceLoader:
    """Load resolved folders from a VSCode ``.code-workspace`` file."""

    @classmethod
    def invoke(cls, *, workspace_file: Path) -> list[WorkspaceFolderDAO]:
        """Return the resolved folders declared in ``workspace_file``.

        Args:
            workspace_file: Absolute path to the workspace file.

        Returns:
            list[WorkspaceFolderDAO]: Resolved folders in declaration order.

        Raises:
            WorkspaceFileParseError: When the file cannot be read or parsed.
        """
        raw_text: str = cls._read_text(workspace_file=workspace_file)
        data: dict = cls._parse_json(workspace_file=workspace_file, raw_text=raw_text)
        entries: list[dict] = cls._extract_folder_entries(
            workspace_file=workspace_file,
            data=data,
        )
        folders: list[WorkspaceFolderDAO] = cls._resolve_entries(
            workspace_file=workspace_file,
            entries=entries,
        )
        log_info(
            msg="workspace_file_loaded",
            workspace_file=str(workspace_file),
            resolved_folder_count=len(folders),
            declared_folder_count=len(entries),
        )
        return folders

    @classmethod
    def _read_text(cls, *, workspace_file: Path) -> str:
        """Read the workspace file as UTF-8 text.

        Args:
            workspace_file: Absolute path to the workspace file.

        Returns:
            str: The file contents.

        Raises:
            WorkspaceFileParseError: When the file cannot be opened.
        """
        try:
            return workspace_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceFileParseError(
                workspace_file=workspace_file,
                reason=f"cannot read file ({exc})",
            ) from exc

    @classmethod
    def _parse_json(cls, *, workspace_file: Path, raw_text: str) -> dict:
        """Parse the workspace file as strict JSON with a JSONC fallback.

        Args:
            workspace_file: Path to the workspace file being parsed.
            raw_text: Raw file contents.

        Returns:
            dict: Parsed object root.

        Raises:
            WorkspaceFileParseError: When the file is not valid JSON/JSONC or
                when the root value is not an object.
        """
        parsed_data: object
        try:
            parsed_data = json.loads(raw_text)
        except json.JSONDecodeError as strict_exc:
            try:
                parsed_data = json5.loads(raw_text)
            except Exception as jsonc_exc:
                raise WorkspaceFileParseError(
                    workspace_file=workspace_file,
                    reason=(
                        "malformed JSON/JSONC "
                        f"({strict_exc.msg} at line {strict_exc.lineno}, column {strict_exc.colno})"
                    ),
                ) from jsonc_exc

        if not isinstance(parsed_data, dict):
            raise WorkspaceFileParseError(
                workspace_file=workspace_file,
                reason="root JSON value must be an object",
            )

        return parsed_data

    @classmethod
    def _extract_folder_entries(
        cls,
        *,
        workspace_file: Path,
        data: dict,
    ) -> list[dict]:
        """Extract and validate the ``folders`` array.

        Args:
            workspace_file: Path to the workspace file being parsed.
            data: Parsed workspace-file object.

        Returns:
            list[dict]: Validated folder-entry dicts.

        Raises:
            WorkspaceFileParseError: When ``folders`` is missing, not a list,
                or contains malformed entries.
        """
        folders: object = data.get("folders")
        if folders is None:
            raise WorkspaceFileParseError(
                workspace_file=workspace_file,
                reason="missing required 'folders' array",
            )
        if not isinstance(folders, list):
            raise WorkspaceFileParseError(
                workspace_file=workspace_file,
                reason="'folders' must be an array",
            )

        for index, entry in enumerate(folders):
            if not isinstance(entry, dict):
                raise WorkspaceFileParseError(
                    workspace_file=workspace_file,
                    reason=f"folders[{index}] must be an object",
                )
            if "path" not in entry or not isinstance(entry["path"], str):
                raise WorkspaceFileParseError(
                    workspace_file=workspace_file,
                    reason=f"folders[{index}] missing required string 'path'",
                )

        return folders

    @classmethod
    def _resolve_entries(
        cls,
        *,
        workspace_file: Path,
        entries: list[dict],
    ) -> list[WorkspaceFolderDAO]:
        """Resolve each folder entry to an absolute filesystem path.

        Missing-on-disk folders are silently dropped so the caller can keep
        working with the remaining valid folders.

        Args:
            workspace_file: Path to the workspace file being parsed.
            entries: Validated ``folders`` entries.

        Returns:
            list[WorkspaceFolderDAO]: Resolved folders in declaration order.
        """
        base_dir: Path = workspace_file.parent.resolve()
        resolved_folders: list[WorkspaceFolderDAO] = []

        for entry in entries:
            candidate: Path = (base_dir / entry["path"]).resolve()
            if not candidate.is_dir():
                log_info(
                    msg="workspace_folder_missing",
                    workspace_file=str(workspace_file),
                    declared_path=entry["path"],
                    resolved_path=str(candidate),
                )
                continue
            resolved_folders.append(
                WorkspaceFolderDAO(
                    path=candidate,
                    display_name=entry.get("name"),
                )
            )

        return resolved_folders
