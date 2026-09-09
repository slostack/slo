"""Parse VSCode ``.code-workspace`` files into resolved workspace folders.

A workspace file declares a JSON or JSONC document with a ``folders`` array.
Each entry must provide a ``path`` and may optionally provide a display
``name``. Relative ``path`` values are resolved against the workspace file's
parent directory.

The loader accepts both strict JSON and JSONC. It tries ``json.loads`` first
and falls back to ``json5.loads`` only when the strict parser rejects the
file. If both parsers fail, the strict parser's error is surfaced because it
carries the most actionable line/column information.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

__all__ = [
    "WorkspaceFileParseError",
    "WorkspaceFolderDAO",
]


class WorkspaceFolderDAO(BaseModel):
    """One resolved folder declared in a VSCode workspace file.

    Attributes:
        path: Absolute filesystem path of the resolved folder.
        display_name: Optional operator-facing label from ``folders[].name``.
    """

    model_config = ConfigDict(frozen=True)

    path: Path
    display_name: Optional[str] = None


class WorkspaceFileParseError(ValueError):
    """Raised when a workspace file cannot be opened or parsed.

    Attributes:
        workspace_file: The path the caller supplied.
        reason: One-line operator-facing explanation of the failure.
    """

    def __init__(self, *, workspace_file: Path, reason: str) -> None:
        """Initialize the exception.

        Args:
            workspace_file: The path the caller supplied.
            reason: One-line operator-facing explanation of the failure.
        """
        self.workspace_file: Path = workspace_file
        self.reason: str = reason
        super().__init__(f"Invalid workspace file {workspace_file}: {reason}")
