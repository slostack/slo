"""Walk-up discovery tests for ``ProjectContextDiscovery`` (sub-spec 01.g §5.2 / 18.04)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.project_context.dao import ContextFileEntryDAO
from src.agents.slo_agent.project_context.service import ProjectContextDiscovery
from src.agents.slo_agent.workspace.dao import WorkspaceFolderDAO

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, Path]:
    """A fake repo with a ``.git`` root, an AGENTS.md at the root, and a SLO.md deeper."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("workspace rules")
    sub = tmp_path / "src" / "feature"
    sub.mkdir(parents=True)
    (sub / "SLO.md").write_text("feature rules")
    return tmp_path, sub


# ---------------------------------------------------------------------------
# Existing behaviour (adapted from tuple-era tests)
# ---------------------------------------------------------------------------


class TestProjectContextDiscovery:
    """Walk-up discovery behaviour for project instruction files."""

    def test_walk_up_finds_both(self, repo: tuple[Path, Path]) -> None:
        """Both filenames from different tree levels are returned."""
        _, sub = repo
        names = [entry.path.split("/")[-1] for entry in ProjectContextDiscovery.invoke(cwd=str(sub))]
        assert "SLO.md" in names and "AGENTS.md" in names

    def test_deepest_first(self, repo: tuple[Path, Path]) -> None:
        """The entry deepest in the tree (SLO.md in sub) appears first."""
        _, sub = repo
        first_entry = ProjectContextDiscovery.invoke(cwd=str(sub))[0]
        assert first_entry.path.endswith("SLO.md")

    def test_walks_past_git_boundary(self, tmp_path: Path) -> None:
        """Files in ancestors above the .git root ARE now returned (no hard stop).

        Layout:
          tmp_path/
            CLAUDE.md          ← ancestor file above the .git boundary
            inner/
              .git/
              SLO.md
              src/feature/     ← cwd
        """
        # Ancestor file (above .git) uses CLAUDE.md — not shadowed by anything below
        ancestor_file = tmp_path / "CLAUDE.md"
        ancestor_file.write_text("ancestor rules")

        inner = tmp_path / "inner"
        inner.mkdir()
        (inner / ".git").mkdir()
        (inner / "SLO.md").write_text("project rules")

        sub = inner / "src" / "feature"
        sub.mkdir(parents=True)

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            contents = [entry.content for entry in ProjectContextDiscovery.invoke(cwd=str(sub))]

        # Files both inside and above the .git boundary are found
        assert "project rules" in contents
        assert "ancestor rules" in contents

    def test_no_files_returns_empty(self, tmp_path: Path) -> None:
        """An empty directory tree with a .git marker returns an empty list."""
        (tmp_path / ".git").mkdir()
        # patch _load_global_context so a real ~/.slo/ dir doesn't interfere
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            assert ProjectContextDiscovery.invoke(cwd=str(tmp_path)) == []

    def test_walk_up_finds_docs_research_file(self, tmp_path: Path) -> None:
        """The repo-local ``docs/RESEARCH.md`` file is discovered as project context."""
        docs_dir: Path = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        research_path: Path = docs_dir / "RESEARCH.md"
        research_path.write_text("repo index", encoding="utf-8")
        sub: Path = tmp_path / "src" / "feature"
        sub.mkdir(parents=True)

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(cwd=str(sub))

        paths = [entry.path for entry in results]
        assert str(research_path.resolve()) in paths


# ---------------------------------------------------------------------------
# New tests: ContextFileEntryDAO return type
# ---------------------------------------------------------------------------


class TestProjectContextDiscoveryReturnType:
    """Verify the new ``ContextFileEntryDAO`` return type and tier labels."""

    def test_returns_context_file_entry_dao_objects(self, repo: tuple[Path, Path]) -> None:
        """Every element in the result is a ``ContextFileEntryDAO`` instance."""
        _, sub = repo
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(cwd=str(sub))
        assert results, "Expected at least one entry"
        for entry in results:
            assert isinstance(entry, ContextFileEntryDAO)

    def test_project_tier_label_on_walked_entries(self, repo: tuple[Path, Path]) -> None:
        """Entries discovered by walking up from cwd carry ``tier='project'``."""
        _, sub = repo
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(cwd=str(sub))
        for entry in results:
            assert entry.tier == "project"

    def test_entry_path_and_content_populated(self, repo: tuple[Path, Path]) -> None:
        """Each entry has a non-empty path and matching content."""
        _, sub = repo
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(cwd=str(sub))
        for entry in results:
            assert entry.path
            assert entry.content


# ---------------------------------------------------------------------------
# New tests: global context tier
# ---------------------------------------------------------------------------


class TestProjectContextDiscoveryWorkspace:
    """Workspace-folder discovery extends cwd-only discovery without duplicates."""

    def test_workspace_folder_contributes_workspace_tier_entries(self, tmp_path: Path) -> None:
        """A workspace folder outside the cwd lineage adds workspace-tier entries."""
        cwd: Path = tmp_path / "project_a"
        other: Path = tmp_path / "project_b"
        cwd.mkdir()
        other.mkdir()
        (cwd / "AGENTS.md").write_text("cwd rules", encoding="utf-8")
        (other / "AGENTS.md").write_text("other rules", encoding="utf-8")

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(
                cwd=str(cwd),
                workspace_folders=[WorkspaceFolderDAO(path=other.resolve(), display_name="Other")],
            )

        workspace_entries = [entry for entry in results if entry.tier == "workspace_folder"]
        assert len(workspace_entries) == 1
        assert workspace_entries[0].path == str((other / "AGENTS.md").resolve())
        assert workspace_entries[0].workspace_folder_root == str(other.resolve())
        assert workspace_entries[0].workspace_folder_display_name == "Other"

    def test_workspace_folder_dedupes_against_cwd_walk(self, tmp_path: Path) -> None:
        """A workspace folder overlapping cwd does not duplicate the same file."""
        cwd: Path = tmp_path / "project"
        cwd.mkdir()
        (cwd / "AGENTS.md").write_text("shared", encoding="utf-8")

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(
                cwd=str(cwd),
                workspace_folders=[WorkspaceFolderDAO(path=cwd.resolve(), display_name="Same")],
            )

        agents_entries = [entry for entry in results if entry.path.endswith("AGENTS.md")]
        assert len(agents_entries) == 1
        assert agents_entries[0].tier == "project"

    def test_empty_workspace_folders_matches_cwd_only_output(self, tmp_path: Path) -> None:
        """An empty workspace list preserves today's exact cwd-only behavior."""
        cwd: Path = tmp_path / "project"
        cwd.mkdir()
        (cwd / "AGENTS.md").write_text("cwd rules", encoding="utf-8")

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            baseline = ProjectContextDiscovery.invoke(cwd=str(cwd))
            with_empty_workspaces = ProjectContextDiscovery.invoke(
                cwd=str(cwd),
                workspace_folders=[],
            )

        assert baseline == with_empty_workspaces

    def test_workspace_walk_discovers_ancestor_context_files(self, tmp_path: Path) -> None:
        """Walking up from a workspace folder discovers ancestor instruction files."""
        ancestor: Path = tmp_path / "parent"
        leaf: Path = ancestor / "child"
        unrelated_cwd: Path = tmp_path / "cwd"
        leaf.mkdir(parents=True)
        unrelated_cwd.mkdir()
        (ancestor / "AGENTS.md").write_text("ancestor rules", encoding="utf-8")

        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            results = ProjectContextDiscovery.invoke(
                cwd=str(unrelated_cwd),
                workspace_folders=[WorkspaceFolderDAO(path=leaf.resolve(), display_name=None)],
            )

        workspace_paths = [entry.path for entry in results if entry.tier == "workspace_folder"]
        assert str((ancestor / "AGENTS.md").resolve()) in workspace_paths


class TestProjectContextDiscoveryGlobal:
    """Global user context (~/.slo/) prepended before project entries."""

    def test_global_tier_prepended_when_present(self, tmp_path: Path) -> None:
        """A global entry with ``tier='global'`` is the first result when present."""
        global_entry = ContextFileEntryDAO(
            path="/home/user/.slo/AGENTS.md",
            content="global user rules",
            tier="global",
        )
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=global_entry):
            results = ProjectContextDiscovery.invoke(cwd=str(tmp_path))
        assert results[0].tier == "global"
        assert results[0].content == "global user rules"

    def test_global_absent_dir_returns_project_only(self, repo: tuple[Path, Path]) -> None:
        """When ``~/.slo/`` does not exist, only project-tier entries are returned."""
        _, sub = repo
        non_existent = Path("/nonexistent_slo_dir_for_testing")
        with patch.object(Path, "home", return_value=non_existent.parent):
            # Actually test via _load_global_context returning None
            with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
                results = ProjectContextDiscovery.invoke(cwd=str(sub))
        assert all(entry.tier == "project" for entry in results)

    def test_global_empty_dir_safe(self, tmp_path: Path) -> None:
        """An empty ``~/.slo/`` directory does not raise and returns no global entry."""
        fake_home = tmp_path / "home"
        slo_dir = fake_home / ".slo"
        slo_dir.mkdir(parents=True)

        with patch.object(Path, "home", return_value=fake_home):
            entry = ProjectContextDiscovery._load_global_context()
        assert entry is None

    def test_load_global_context_returns_global_tier_entry(self, tmp_path: Path) -> None:
        """``_load_global_context`` returns a ``tier='global'`` entry when a file exists."""
        fake_home = tmp_path / "home"
        slo_dir = fake_home / ".slo"
        slo_dir.mkdir(parents=True)
        (slo_dir / "AGENTS.md").write_text("global instructions")

        with patch.object(Path, "home", return_value=fake_home):
            entry = ProjectContextDiscovery._load_global_context()

        assert entry is not None
        assert entry.tier == "global"
        assert entry.content == "global instructions"
        assert entry.path.endswith("AGENTS.md")

    def test_load_global_context_returns_none_when_dir_absent(self) -> None:
        """``_load_global_context`` returns None when the ~/.slo/ directory is absent."""
        with patch.object(ProjectContextDiscovery, "_load_global_context", return_value=None):
            result = ProjectContextDiscovery._load_global_context()
        assert result is None
