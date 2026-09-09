"""ProjectContextDiscovery — walk up from cwd collecting project instruction files.

Matches the project guardrail files plus the repo research index:
``SLO.md`` (preferred), ``AGENTS.md`` (workspace-wide), ``CLAUDE.md``
(Claude-Code style), and ``docs/RESEARCH.md``. Files closer to cwd come
first so they render above more distant ones. The deepest copy of a given
relative path wins.

The discovery walk no longer stops at ``.git`` boundaries so parent directories
in a monorepo layout (above the innermost repo root) are also searched.
A separate global tier loads ``~/.slo/`` first so user-level instructions
are prepended before any project-tier files.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Iterable, Optional

from src.agents.slo_agent.project_context.dao import ContextFileEntryDAO
from src.agents.slo_agent.workspace.dao import WorkspaceFolderDAO

__all__ = ["ProjectContextDiscovery"]


class ProjectContextDiscovery:
    """Discover project instruction files by walking up from a starting cwd.

    Walks all the way to the filesystem root (no ``.git`` hard stop).
    Prepends a global user tier from ``~/.slo/`` before project-tier results.
    Returns ``ContextFileEntryDAO`` objects in global-first, deepest-project-first order.
    """

    _PROJECT_CONTEXT_PATHS: ClassVar[tuple[str, ...]] = (
        "SLO.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/RESEARCH.md",
    )

    @classmethod
    def invoke(
        cls,
        *,
        cwd: str,
        workspace_folders: Optional[list[WorkspaceFolderDAO]] = None,
    ) -> list[ContextFileEntryDAO]:
        """Return ``ContextFileEntryDAO`` entries for cwd and workspace folders.

        Loads the global user-level file from ``~/.slo/`` first (prepended),
        then walks from ``cwd`` to the filesystem root collecting project-tier files.
        When ``workspace_folders`` is supplied, the same walk runs from each
        workspace folder and contributes ``workspace_folder`` entries after the
        cwd-derived project entries.

        Args:
            cwd: Starting directory; resolved to an absolute path before walking.
            workspace_folders: Optional additional roots from a VSCode workspace file.

        Returns:
            list[ContextFileEntryDAO]: All discovered instruction files,
                global tier first, then project tier deepest-first, then
                workspace-folder entries.
        """
        results: list[ContextFileEntryDAO] = []
        seen_paths: set[str] = set()

        global_entry: Optional[ContextFileEntryDAO] = cls._load_global_context()
        if global_entry is not None:
            results.append(global_entry)
            seen_paths.add(global_entry.path)

        project_entries: list[ContextFileEntryDAO] = cls._collect_project_entries(
            cwd=cwd,
            seen_paths=seen_paths,
        )
        results.extend(project_entries)

        if workspace_folders:
            workspace_entries: list[ContextFileEntryDAO] = cls._collect_workspace_entries(
                workspace_folders=workspace_folders,
                seen_paths=seen_paths,
            )
            results.extend(workspace_entries)

        return results

    @classmethod
    def _collect_project_entries(
        cls,
        *,
        cwd: str,
        seen_paths: set[str],
    ) -> list[ContextFileEntryDAO]:
        """Walk from ``cwd`` to the filesystem root and collect project-tier files.

        The cwd walk preserves the existing "deepest filename wins" behavior by
        deduping within the walk on filename while also registering every accepted
        absolute path in ``seen_paths`` so later workspace walks can skip files the
        cwd lineage already contributed.

        Args:
            cwd: Starting directory resolved to an absolute path.
            seen_paths: Absolute file paths already accepted into the result.

        Returns:
            list[ContextFileEntryDAO]: Project-tier entries, deepest-first.
        """
        cwd_path = Path(cwd).resolve()
        seen_names: set[str] = set()
        entries: list[ContextFileEntryDAO] = []

        for directory in cls._walk_up(start=cwd_path):
            for relative_path in cls._PROJECT_CONTEXT_PATHS:
                candidate = directory / relative_path
                if relative_path in seen_names or not candidate.is_file():
                    continue
                seen_names.add(relative_path)
                try:
                    content = candidate.read_text(encoding="utf-8")
                except OSError:
                    continue
                path_str: str = str(candidate)
                entries.append(
                    ContextFileEntryDAO(
                        path=path_str,
                        content=content,
                        tier="project",
                    )
                )
                seen_paths.add(path_str)

        return entries

    @classmethod
    def _load_global_context(cls) -> Optional[ContextFileEntryDAO]:
        """Load the global user-level instruction file from ``~/.slo/``.

        Checks each relative path in ``_PROJECT_CONTEXT_PATHS`` in order and returns
        the first readable file found.

        Returns:
            Optional[ContextFileEntryDAO]: The global file entry if found, else ``None``.
        """
        global_dir = Path.home() / ".slo"
        if not global_dir.is_dir():
            return None

        for relative_path in cls._PROJECT_CONTEXT_PATHS:
            candidate = global_dir / relative_path
            if not candidate.is_file():
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
                return ContextFileEntryDAO(
                    path=str(candidate),
                    content=content,
                    tier="global",
                )
            except OSError:
                continue

        return None

    @classmethod
    def _collect_workspace_entries(
        cls,
        *,
        workspace_folders: list[WorkspaceFolderDAO],
        seen_paths: set[str],
    ) -> list[ContextFileEntryDAO]:
        """Walk each workspace folder up to root and collect new entries only.

        Args:
            workspace_folders: Resolved workspace folders in declaration order.
            seen_paths: Absolute file paths already accepted into the result.

        Returns:
            list[ContextFileEntryDAO]: Workspace-tier entries in folder declaration order.
        """
        entries: list[ContextFileEntryDAO] = []

        for folder in workspace_folders:
            for directory in cls._walk_up(start=folder.path):
                for relative_path in cls._PROJECT_CONTEXT_PATHS:
                    candidate = directory / relative_path
                    if not candidate.is_file():
                        continue
                    path_str: str = str(candidate)
                    if path_str in seen_paths:
                        continue
                    try:
                        content = candidate.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    seen_paths.add(path_str)
                    entries.append(
                        ContextFileEntryDAO(
                            path=path_str,
                            content=content,
                            tier="workspace_folder",
                            workspace_folder_root=str(folder.path),
                            workspace_folder_display_name=folder.display_name,
                        )
                    )

        return entries

    @classmethod
    def _walk_up(cls, *, start: Path) -> Iterable[Path]:
        """Yield ``start`` and each ancestor directory up to the filesystem root.

        Args:
            start: The directory to begin yielding from.

        Yields:
            Each directory in order from ``start`` to the filesystem root.
        """
        current = start
        while True:
            yield current
            if current.parent == current:
                return
            current = current.parent
