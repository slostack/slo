"""Decision-path and isolated-repository tests for the show_git_diff tool."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.agents.tools.bundles import create_extended_tools
from src.agents.tools.show_git_diff import ShowGitDiffTool, show_git_diff_tool
from src.agents.slo_agent.skills.service import SkillsLoader
from src.tui.git_diff_content_service import GitDiffContentDAO, GitDiffContentError
from src.tui.slodiff.model import FileStateKind


def _build_content(
    *,
    repository_relative_path: str = "src/example.py",
    base_content: str = "before\n",
    changed_content: str = "after\n",
    file_state: FileStateKind = FileStateKind.MODIFIED,
) -> GitDiffContentDAO:
    """Build representative Git diff content for one tool test."""
    return GitDiffContentDAO(
        repository_relative_path=repository_relative_path,
        base_content=base_content,
        changed_content=changed_content,
        file_state=file_state,
    )


def _initialize_git_repository(*, workdir: Path) -> None:
    """Create one isolated repository with a committed file for bridge coverage."""

    def run_git(*arguments: str) -> None:
        """Run one Git command in the isolated repository."""
        subprocess.run(args=["git", *arguments], cwd=workdir, check=True, capture_output=True)

    run_git("init")
    run_git("config", "user.email", "test@example.invalid")
    run_git("config", "user.name", "Slo Test")
    (workdir / "example.py").write_text("before\n", encoding="utf-8")
    run_git("add", "example.py")
    run_git("commit", "-m", "initial")
    (workdir / "example.py").write_text("after\n", encoding="utf-8")


class TestShowGitDiffToolInvoke:
    """Typed core behavior for the LLM-facing Git diff tool."""

    async def test_invoke_when_service_succeeds_returns_service_dao(self, tmp_path: Path) -> None:
        """The core preserves a successful typed service result."""
        content = _build_content()
        with patch(
            "src.tui.git_diff_content_service.GitDiffContentService.invoke",
            new=AsyncMock(return_value=content),
        ):
            result = await ShowGitDiffTool.invoke(
                repository_relative_path="src/example.py",
                workdir=tmp_path,
            )
        assert result == content

    async def test_invoke_when_content_error_returns_unchanged_stub(self, tmp_path: Path) -> None:
        """Expected safe service failures never escape the agent tool."""
        error = GitDiffContentError(operator_message="Binary files are not supported.")
        with patch(
            "src.tui.git_diff_content_service.GitDiffContentService.invoke",
            new=AsyncMock(side_effect=error),
        ):
            result = await ShowGitDiffTool.invoke(repository_relative_path="blob.bin", workdir=tmp_path)
        assert result == _build_content(
            repository_relative_path="blob.bin",
            base_content="",
            changed_content="",
            file_state=FileStateKind.UNCHANGED,
        )

    async def test_invoke_when_unexpected_error_returns_unchanged_stub(self, tmp_path: Path) -> None:
        """Unexpected service defects also degrade to the stable safe stub."""
        with patch(
            "src.tui.git_diff_content_service.GitDiffContentService.invoke",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            result = await ShowGitDiffTool.invoke(repository_relative_path="broken.py", workdir=tmp_path)
        assert result.file_state is FileStateKind.UNCHANGED
        assert result.base_content == ""
        assert result.changed_content == ""


class TestShowGitDiffToolBridge:
    """LangChain bridge registration, JSON, and process-CWD behavior."""

    async def test_bridge_when_called_in_isolated_repository_returns_serialized_diff(
        self, tmp_path: Path
    ) -> None:
        """The real bridge resolves process CWD and serializes genuine Git content."""
        _initialize_git_repository(workdir=tmp_path)
        with patch("src.agents.tools.show_git_diff.os.getcwd", return_value=str(tmp_path)):
            payload = await show_git_diff_tool.ainvoke({"repository_relative_path": "example.py"})
        decoded: dict[str, str] = json.loads(payload)
        assert decoded["repository_relative_path"] == "example.py"
        assert decoded["base_content"] == "before\n"
        assert decoded["changed_content"] == "after\n"
        assert decoded["file_state"] == "modified"

    def test_extended_bundle_includes_show_git_diff(self) -> None:
        """The default extended bundle exposes the agent-callable bridge."""
        assert "show_git_diff" in {tool.name for tool in create_extended_tools()}

    def test_skill_loader_discovers_show_git_diff_by_frontmatter_name(self) -> None:
        """The vendored skill name matches the callable tool rather than its directory."""
        repository_root = Path(__file__).resolve().parents[3]
        entries = SkillsLoader.load(skills_dir=str(repository_root / "skills"))
        assert "show_git_diff" in {entry.name for entry in entries}
