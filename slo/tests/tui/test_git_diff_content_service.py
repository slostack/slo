"""Real-temporary-repository tests for GitDiffContentService."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tui.git_diff_content_service import GitDiffContentError, GitDiffContentService
from src.tui.slodiff.model import FileStateKind


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary repository with one committed UTF-8 text file."""

    def run_git(*arguments: str) -> None:
        """Run one local git command while constructing the temporary repository."""
        subprocess.run(["git", *arguments], cwd=tmp_path, check=True, capture_output=True)

    run_git("init")
    run_git("config", "user.email", "test@example.invalid")
    run_git("config", "user.name", "Slo Test")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    run_git("add", "README.md")
    run_git("commit", "-m", "initial")
    return tmp_path


class TestGitDiffContentService:
    """Service state, validation, and content-safety tests."""

    async def test_invoke_when_file_modified_returns_modified_state(self, git_repo: Path) -> None:
        """A changed tracked file returns its HEAD and worktree content."""
        (git_repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")
        result = await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)
        assert result.file_state is FileStateKind.MODIFIED
        assert result.base_content == "hello\n"
        assert result.changed_content == "hello\nworld\n"

    async def test_invoke_when_file_added_returns_added_state(self, git_repo: Path) -> None:
        """A worktree-only file has no base content."""
        (git_repo / "new.py").write_text("answer = 42\n", encoding="utf-8")
        result = await GitDiffContentService.invoke(requested_path="new.py", workdir=git_repo)
        assert result.file_state is FileStateKind.ADDED
        assert result.base_content == ""

    async def test_invoke_when_workdir_is_nested_under_repository_reads_session_relative_path(
        self, git_repo: Path
    ) -> None:
        """A nested Slo workdir translates its path before Git reads HEAD.

        The local checkout has this shape: Git tracks ``slo/src/...`` from the
        outer repository root while Slo uses the inner ``slo`` directory as its
        session workdir. This regression test proves `/diff src/...` reads the
        same path the operator sees rather than looking for ``HEAD:src/...``.
        """
        session_workdir: Path = git_repo / "slo"
        source_path: Path = session_workdir / "src" / "example.py"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("before\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "slo/src/example.py"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add nested source"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        source_path.write_text("after\n", encoding="utf-8")

        result = await GitDiffContentService.invoke(
            requested_path="src/example.py",
            workdir=session_workdir,
        )

        assert result.file_state is FileStateKind.MODIFIED
        assert result.repository_relative_path == "src/example.py"
        assert result.base_content == "before\n"
        assert result.changed_content == "after\n"

    async def test_invoke_when_head_is_unborn_returns_added_state(self, tmp_path: Path) -> None:
        """A real repository with no commit treats every worktree file as added."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "new.py").write_text("answer = 42\n", encoding="utf-8")

        result = await GitDiffContentService.invoke(requested_path="new.py", workdir=tmp_path)

        assert result.file_state is FileStateKind.ADDED
        assert result.base_content == ""
        assert result.changed_content == "answer = 42\n"

    async def test_invoke_when_file_deleted_returns_deleted_state(self, git_repo: Path) -> None:
        """A HEAD-only file has no changed content."""
        (git_repo / "README.md").unlink()
        result = await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)
        assert result.file_state is FileStateKind.DELETED
        assert result.changed_content == ""

    async def test_invoke_when_unchanged_raises_no_changes(self, git_repo: Path) -> None:
        """An unchanged tracked file never produces screen content."""
        with pytest.raises(GitDiffContentError, match="No changes detected for README.md."):
            await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

    @pytest.mark.parametrize(
        ("requested_path", "operator_message"),
        [
            ("  ", "Path must not be empty."),
            ("/tmp/file", "Path must be relative to the repository root."),
            ("../file", "Path must not contain traversal components."),
            ("./file", "Path must not contain traversal components."),
            (".git/config", "Path must not point inside the .git directory."),
            ("bad\\path", "Path must be relative to the repository root."),
            ("C:file", "Path must be relative to the repository root."),
            ("bad\x00path", "Path must not contain NUL bytes."),
        ],
    )
    async def test_invoke_when_path_is_invalid_raises_stable_message(
        self,
        git_repo: Path,
        requested_path: str,
        operator_message: str,
    ) -> None:
        """Every rejected path form returns its specified safe message."""
        with pytest.raises(GitDiffContentError) as error_info:
            await GitDiffContentService.invoke(requested_path=requested_path, workdir=git_repo)
        assert error_info.value.operator_message == operator_message

    async def test_invoke_when_file_missing_raises_not_found(self, git_repo: Path) -> None:
        """A path absent from HEAD and worktree is rejected safely."""
        with pytest.raises(GitDiffContentError, match="File not found in HEAD or worktree."):
            await GitDiffContentService.invoke(requested_path="missing.txt", workdir=git_repo)

    async def test_invoke_when_path_is_directory_raises_error(self, git_repo: Path) -> None:
        """Directories are not valid single-file diff targets."""
        (git_repo / "directory").mkdir()
        with pytest.raises(GitDiffContentError, match="Path points to a directory, not a file."):
            await GitDiffContentService.invoke(requested_path="directory", workdir=git_repo)

    async def test_invoke_when_binary_raises_error(self, git_repo: Path) -> None:
        """NUL-containing worktree data is rejected as binary."""
        (git_repo / "binary.bin").write_bytes(b"text\x00binary")
        with pytest.raises(GitDiffContentError, match="Binary files are not supported."):
            await GitDiffContentService.invoke(requested_path="binary.bin", workdir=git_repo)

    async def test_invoke_when_non_utf8_raises_error(self, git_repo: Path) -> None:
        """Non-UTF-8 worktree data is rejected."""
        (git_repo / "latin.bin").write_bytes(b"\xff")
        with pytest.raises(GitDiffContentError, match="File contains non-UTF-8 text."):
            await GitDiffContentService.invoke(requested_path="latin.bin", workdir=git_repo)

    async def test_invoke_when_file_exceeds_size_limit_raises_error(self, git_repo: Path) -> None:
        """A worktree file beyond the documented one-megabyte bound is rejected."""
        (git_repo / "large.txt").write_text("a" * 1_000_001, encoding="utf-8")
        with pytest.raises(GitDiffContentError, match="File is too large to diff \(limit 1 MB\)."):
            await GitDiffContentService.invoke(requested_path="large.txt", workdir=git_repo)

    async def test_invoke_when_head_blob_exceeds_size_limit_raises_error(self, git_repo: Path) -> None:
        """A committed HEAD blob beyond the documented bound is rejected before screen creation."""
        (git_repo / "README.md").write_text("a" * 1_000_001, encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "large HEAD blob"], cwd=git_repo, check=True, capture_output=True
        )
        (git_repo / "README.md").unlink()

        with pytest.raises(GitDiffContentError, match="File is too large to diff \(limit 1 MB\)."):
            await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

    async def test_invoke_when_head_blob_is_binary_raises_error(self, git_repo: Path) -> None:
        """A binary HEAD blob is rejected even when the worktree file has been deleted."""
        (git_repo / "README.md").write_bytes(b"base\x00binary")
        subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "binary HEAD blob"], cwd=git_repo, check=True, capture_output=True
        )
        (git_repo / "README.md").unlink()

        with pytest.raises(GitDiffContentError, match="Binary files are not supported."):
            await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

    async def test_invoke_when_head_blob_is_non_utf8_raises_error(self, git_repo: Path) -> None:
        """A non-UTF-8 HEAD blob is rejected even when the worktree file has been deleted."""
        (git_repo / "README.md").write_bytes(b"\xff")
        subprocess.run(["git", "add", "README.md"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "non UTF8 HEAD blob"], cwd=git_repo, check=True, capture_output=True
        )
        (git_repo / "README.md").unlink()

        with pytest.raises(GitDiffContentError, match="File contains non-UTF-8 text."):
            await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

    async def test_invoke_when_git_show_times_out_returns_safe_message(self, git_repo: Path) -> None:
        """A Git timeout never leaks command details or an absolute workdir into the transcript."""
        with patch(
            "src.tui.git_diff_content_service.asyncio.to_thread",
            side_effect=subprocess.TimeoutExpired(cmd="git show", timeout=10),
        ):
            with pytest.raises(GitDiffContentError) as error_info:
                await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

        assert error_info.value.operator_message == "Git command timed out."

    async def test_invoke_when_git_subprocess_raises_os_error_hides_details(self, git_repo: Path) -> None:
        """A Git launch failure is replaced with the stable HEAD-read message."""
        with patch(
            "src.tui.git_diff_content_service.asyncio.to_thread",
            side_effect=OSError(f"git unavailable at {git_repo}"),
        ):
            with pytest.raises(GitDiffContentError) as error_info:
                await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

        assert error_info.value.operator_message == "Could not read HEAD version of file."
        assert str(git_repo) not in error_info.value.operator_message

    async def test_invoke_when_worktree_read_raises_os_error_hides_details(self, git_repo: Path) -> None:
        """A worktree read failure is replaced with the stable HEAD-read message."""
        original_to_thread = asyncio.to_thread

        async def read_failure(function, *arguments, **keyword_arguments):
            """Raise only when the service attempts the worktree byte read."""
            if getattr(function, "__name__", "") == "read_bytes":
                raise OSError(f"permission denied for {git_repo}")
            return await original_to_thread(function, *arguments, **keyword_arguments)

        with patch("src.tui.git_diff_content_service.asyncio.to_thread", new=read_failure):
            with pytest.raises(GitDiffContentError) as error_info:
                await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

        assert error_info.value.operator_message == "Could not read HEAD version of file."
        assert str(git_repo) not in error_info.value.operator_message

    async def test_invoke_when_git_show_fails_unexpectedly_hides_stderr(self, git_repo: Path) -> None:
        """Unexpected Git stderr is replaced with the stable operator-safe message."""
        result = subprocess.CompletedProcess(
            args=["git", "show"],
            returncode=128,
            stdout=b"",
            stderr=f"fatal: secret at {git_repo}".encode(),
        )
        with patch(
            "src.tui.git_diff_content_service.asyncio.to_thread",
            new=lambda function, *args, **kwargs: asyncio.sleep(0, result=result),
        ):
            with pytest.raises(GitDiffContentError) as error_info:
                await GitDiffContentService.invoke(requested_path="README.md", workdir=git_repo)

        assert error_info.value.operator_message == "Could not read HEAD version of file."
        assert str(git_repo) not in error_info.value.operator_message

    async def test_invoke_when_symlink_escapes_workdir_raises_error(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """A symlink cannot make the service read outside its repository."""
        outside_path = tmp_path.parent / "outside.txt"
        outside_path.write_text("secret\n", encoding="utf-8")
        (git_repo / "escape.txt").symlink_to(outside_path)
        with pytest.raises(GitDiffContentError, match="Path must be relative to the repository root."):
            await GitDiffContentService.invoke(requested_path="escape.txt", workdir=git_repo)
