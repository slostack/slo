"""Read-only, safe HEAD-versus-worktree content loading for slodiff."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path, PurePosixPath
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.tui.slodiff.model import FileStateKind

_GIT_COMMAND_TIMEOUT_SECONDS: float = 10.0
_MAX_DIFF_FILE_BYTES: int = 1_000_000

_EMPTY_PATH_MESSAGE = "Path must not be empty."
_RELATIVE_PATH_MESSAGE = "Path must be relative to the repository root."
_TRAVERSAL_PATH_MESSAGE = "Path must not contain traversal components."
_NUL_PATH_MESSAGE = "Path must not contain NUL bytes."
_GIT_PATH_MESSAGE = "Path must not point inside the .git directory."
_DIRECTORY_PATH_MESSAGE = "Path points to a directory, not a file."
_NOT_FOUND_MESSAGE = "File not found in HEAD or worktree."
_TOO_LARGE_MESSAGE = "File is too large to diff (limit 1 MB)."
_BINARY_MESSAGE = "Binary files are not supported."
_NON_UTF8_MESSAGE = "File contains non-UTF-8 text."
_HEAD_READ_MESSAGE = "Could not read HEAD version of file."
_TIMEOUT_MESSAGE = "Git command timed out."


class GitDiffContentError(Exception):
    """Carry one stable, operator-safe failure message from the content service."""

    def __init__(self, *, operator_message: str) -> None:
        """Store the transcript-safe explanation consumed by TUI and tool callers.

        Args:
            operator_message (str): Stable message without paths, stderr, or tracebacks.
        """
        super().__init__(operator_message)
        self.operator_message: str = operator_message


class GitDiffContentDAO(BaseModel):
    """Represent validated HEAD and worktree content for one repository file."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    repository_relative_path: str = Field(description="Normalized repository-relative POSIX path.")
    base_content: str = Field(description="HEAD content, empty for an added file.")
    changed_content: str = Field(description="Worktree content, empty for a deleted file.")
    file_state: FileStateKind = Field(description="Detected HEAD-versus-worktree file state.")


class GitDiffContentService:
    """Load validated text pairs for one file without mutating the repository."""

    @classmethod
    async def invoke(cls, *, requested_path: str, workdir: Path) -> GitDiffContentDAO:
        """Load one safe, changed repository-relative path for the screen or agent tool.

        Args:
            requested_path (str): Raw slash-command or tool path argument.
            workdir (Path): Repository root supplied by the caller.

        Returns:
            GitDiffContentDAO: Validated HEAD/worktree text and its file state.

        Raises:
            GitDiffContentError: If validation, Git, decoding, or state checks fail.
        """
        try:
            repository_relative_path: str = cls._validate_path(requested_path=requested_path)
            repository_root: Path = await cls._resolve_repository_root(workdir=workdir)
            worktree_path: Path = workdir / repository_relative_path
            cls._reject_escaping_symlink(worktree_path=worktree_path, workdir=workdir)
            cls._reject_directory(path=worktree_path)
            git_repository_path: str = cls._build_git_repository_path(
                repository_relative_path=repository_relative_path,
                repository_root=repository_root,
                workdir=workdir,
            )
            base_content: Optional[str] = await cls._read_head_content(
                repository_relative_path=git_repository_path,
                workdir=repository_root,
            )
            changed_content: Optional[str] = await cls._read_worktree_content(path=worktree_path)
        except OSError as exception:
            raise GitDiffContentError(operator_message=_HEAD_READ_MESSAGE) from exception
        file_state: FileStateKind = cls._detect_file_state(
            base_content=base_content,
            changed_content=changed_content,
        )
        cls._reject_unchanged(file_state=file_state, repository_relative_path=repository_relative_path)
        return GitDiffContentDAO(
            repository_relative_path=repository_relative_path,
            base_content=base_content or "",
            changed_content=changed_content or "",
            file_state=file_state,
        )

    @classmethod
    async def _resolve_repository_root(cls, *, workdir: Path) -> Path:
        """Return the repository root that contains the session workdir.

        WHAT: Asks Git for the root path so HEAD object paths use the repository
            namespace even when Slo starts in a nested project directory.
        WHO: ``invoke`` calls it before reading the HEAD version of a file.
        WHEN: Runs once for every accepted `/diff` request.

        Args:
            workdir (Path): Session-scoped directory that may be below the Git root.

        Returns:
            Path: Resolved absolute root reported by Git.

        Raises:
            GitDiffContentError: If Git cannot identify a containing repository.
        """
        command: list[str] = ["git", "rev-parse", "--show-toplevel"]
        try:
            result: subprocess.CompletedProcess[bytes] = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=workdir,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exception:
            raise GitDiffContentError(operator_message=_TIMEOUT_MESSAGE) from exception
        if result.returncode != 0:
            raise GitDiffContentError(operator_message=_HEAD_READ_MESSAGE)
        return Path(result.stdout.decode("utf-8").strip()).resolve()

    @classmethod
    def _build_git_repository_path(
        cls,
        *,
        repository_relative_path: str,
        repository_root: Path,
        workdir: Path,
    ) -> str:
        """Translate a session-relative file path into Git's root-relative path.

        WHAT: Prefixes a requested session path with the session directory's
            repository-relative location when the TUI starts below the Git root.
        WHO: ``invoke`` calls it before ``_read_head_content`` runs ``git show``.
        WHEN: Runs after path validation and repository-root discovery.

        Args:
            repository_relative_path (str): Validated path typed by the operator.
            repository_root (Path): Root reported by ``git rev-parse``.
            workdir (Path): Session directory that scopes `/diff`.

        Returns:
            str: POSIX path understood by ``HEAD:<path>``.
        """
        workdir_relative_path: Path = workdir.resolve().relative_to(repository_root)
        if workdir_relative_path == Path("."):
            return repository_relative_path
        return (workdir_relative_path / repository_relative_path).as_posix()

    @classmethod
    def _validate_path(cls, *, requested_path: str) -> str:
        """Normalize one requested path before the service performs filesystem I/O.

        Args:
            requested_path (str): Raw operator-supplied path.

        Returns:
            str: Safe normalized POSIX repository-relative path.

        Raises:
            GitDiffContentError: If the supplied path is unsafe or malformed.
        """
        stripped_path: str = requested_path.strip()
        cls._reject_empty_path(path=stripped_path)
        cls._reject_nul_path(path=stripped_path)
        cls._reject_non_posix_path(path=stripped_path)
        cls._reject_raw_traversal_path(path=stripped_path)
        path: PurePosixPath = PurePosixPath(stripped_path)
        cls._reject_absolute_path(path=path)
        cls._reject_git_path(path=path)
        return path.as_posix()

    @classmethod
    def _reject_empty_path(cls, *, path: str) -> None:
        """Reject blank path arguments before all other validation steps."""
        if not path:
            raise GitDiffContentError(operator_message=_EMPTY_PATH_MESSAGE)

    @classmethod
    def _reject_nul_path(cls, *, path: str) -> None:
        """Reject NUL-bearing path arguments before filesystem resolution."""
        if "\x00" in path:
            raise GitDiffContentError(operator_message=_NUL_PATH_MESSAGE)

    @classmethod
    def _reject_non_posix_path(cls, *, path: str) -> None:
        """Reject Windows separators and drive notation from POSIX-only paths."""
        if "\\" in path or ":" in path:
            raise GitDiffContentError(operator_message=_RELATIVE_PATH_MESSAGE)

    @classmethod
    def _reject_absolute_path(cls, *, path: PurePosixPath) -> None:
        """Reject absolute paths before joining them to the repository root."""
        if path.is_absolute():
            raise GitDiffContentError(operator_message=_RELATIVE_PATH_MESSAGE)

    @classmethod
    def _reject_raw_traversal_path(cls, *, path: str) -> None:
        """Reject explicit current-directory and parent-directory path components."""
        if any(component in (".", "..") for component in path.split("/")):
            raise GitDiffContentError(operator_message=_TRAVERSAL_PATH_MESSAGE)

    @classmethod
    def _reject_git_path(cls, *, path: PurePosixPath) -> None:
        """Reject direct access to Git metadata before invoking Git or reading files."""
        if path.parts and path.parts[0] == ".git":
            raise GitDiffContentError(operator_message=_GIT_PATH_MESSAGE)

    @classmethod
    def _reject_escaping_symlink(cls, *, worktree_path: Path, workdir: Path) -> None:
        """Reject a worktree symlink that resolves outside the supplied repository root."""
        resolved_path: Path = worktree_path.resolve()
        resolved_workdir: Path = workdir.resolve()
        if resolved_path == resolved_workdir or resolved_workdir in resolved_path.parents:
            return
        raise GitDiffContentError(operator_message=_RELATIVE_PATH_MESSAGE)

    @classmethod
    def _reject_directory(cls, *, path: Path) -> None:
        """Reject directories because slodiff operates on exactly one file."""
        if path.is_dir():
            raise GitDiffContentError(operator_message=_DIRECTORY_PATH_MESSAGE)

    @classmethod
    async def _read_head_content(cls, *, repository_relative_path: str, workdir: Path) -> Optional[str]:
        """Read and decode HEAD content, preserving absent-from-HEAD as None.

        Args:
            repository_relative_path (str): Safe POSIX path supplied to Git.
            workdir (Path): Repository root used as subprocess cwd.

        Returns:
            Optional[str]: Decoded HEAD text, or None for an added worktree file.

        Raises:
            GitDiffContentError: If Git fails unexpectedly, times out, or content is unsafe.
        """
        command: list[str] = [
            "git",
            "show",
            "--no-ext-diff",
            "--no-textconv",
            f"HEAD:{repository_relative_path}",
        ]
        try:
            result: subprocess.CompletedProcess[bytes] = await asyncio.to_thread(
                subprocess.run,
                command,
                cwd=workdir,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=_GIT_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exception:
            raise GitDiffContentError(operator_message=_TIMEOUT_MESSAGE) from exception
        if result.returncode != 0:
            return cls._content_for_absent_head(stderr_bytes=result.stderr)
        return cls._decode_content(raw=result.stdout)

    @classmethod
    def _content_for_absent_head(cls, *, stderr_bytes: bytes) -> None:
        """Interpret Git's documented missing-HEAD-path errors and reject all others."""
        stderr: str = stderr_bytes.decode("utf-8", errors="replace")
        if cls._is_absent_head_error(stderr=stderr):
            return None
        raise GitDiffContentError(operator_message=_HEAD_READ_MESSAGE)

    @classmethod
    def _is_absent_head_error(cls, *, stderr: str) -> bool:
        """Identify Git errors that mean no HEAD blob exists for the requested path.

        Args:
            stderr (str): Decoded Git stderr from a failed ``git show`` command.

        Returns:
            bool: True for a missing path in HEAD or an unborn repository HEAD.
        """
        return (
            "does not exist" in stderr
            or "exists on disk, but not in" in stderr
            or "invalid object name 'HEAD'" in stderr
        )

    @classmethod
    async def _read_worktree_content(cls, *, path: Path) -> Optional[str]:
        """Read and decode worktree content, preserving a deleted file as None."""
        if not path.exists():
            return None
        raw: bytes = await asyncio.to_thread(path.read_bytes)
        return cls._decode_content(raw=raw)

    @classmethod
    def _decode_content(cls, *, raw: bytes) -> str:
        """Enforce the per-side size, binary, and UTF-8 limits for diff text."""
        cls._reject_large_content(raw=raw)
        cls._reject_binary_content(raw=raw)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exception:
            raise GitDiffContentError(operator_message=_NON_UTF8_MESSAGE) from exception

    @classmethod
    def _reject_large_content(cls, *, raw: bytes) -> None:
        """Reject content larger than the documented one-megabyte per-side limit."""
        if len(raw) > _MAX_DIFF_FILE_BYTES:
            raise GitDiffContentError(operator_message=_TOO_LARGE_MESSAGE)

    @classmethod
    def _reject_binary_content(cls, *, raw: bytes) -> None:
        """Reject NUL-bearing content because binary diffs are not in scope."""
        if b"\x00" in raw:
            raise GitDiffContentError(operator_message=_BINARY_MESSAGE)

    @classmethod
    def _detect_file_state(
        cls,
        *,
        base_content: Optional[str],
        changed_content: Optional[str],
    ) -> FileStateKind:
        """Classify HEAD and worktree presence after both bounded reads finish."""
        if base_content is None and changed_content is None:
            raise GitDiffContentError(operator_message=_NOT_FOUND_MESSAGE)
        if base_content is None:
            return FileStateKind.ADDED
        if changed_content is None:
            return FileStateKind.DELETED
        if base_content == changed_content:
            return FileStateKind.UNCHANGED
        return FileStateKind.MODIFIED

    @classmethod
    def _reject_unchanged(cls, *, file_state: FileStateKind, repository_relative_path: str) -> None:
        """Prevent callers from opening a diff screen for an unchanged file."""
        if file_state is FileStateKind.UNCHANGED:
            raise GitDiffContentError(operator_message=f"No changes detected for {repository_relative_path}.")
