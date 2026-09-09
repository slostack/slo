"""ContextFileEntryDAO — one discovered project instruction file with source tier annotation."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

__all__ = ["ContextFileEntryDAO"]


class ContextFileEntryDAO(BaseModel):
    """One discovered project instruction file with source tier annotation.

    Attributes:
        path: Absolute filesystem path to the instruction file.
        content: Full UTF-8 file content.
        tier: ``'global'`` for user-level (``~/.slo/``) files loaded first;
            ``'project'`` for files found walking up from cwd;
            ``'workspace_folder'`` for files found walking up from a workspace folder.
        workspace_folder_root: Absolute root path of the workspace folder whose
            lineage walk produced this entry. ``None`` for non-workspace tiers.
        workspace_folder_display_name: Optional display name from
            ``folders[].name`` in the workspace file. ``None`` for non-workspace tiers.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    content: str
    tier: Literal["global", "project", "workspace_folder"] = "project"
    workspace_folder_root: Optional[str] = None
    workspace_folder_display_name: Optional[str] = None
