"""LLM-invokable safe Git diff content loader for one repository file."""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.tui.git_diff_content_service import GitDiffContentDAO, GitDiffContentError, GitDiffContentService
from src.tui.slodiff.model import FileStateKind

__all__ = ["ShowGitDiffSchemaDAO", "ShowGitDiffTool", "show_git_diff_tool"]


class ShowGitDiffSchemaDAO(BaseModel):
    """Validate the LLM argument for the show_git_diff tool."""

    model_config = ConfigDict(title="ShowGitDiffSchemaDAO", extra="ignore", from_attributes=True)

    repository_relative_path: str = Field(
        description="Repository-relative POSIX file path to diff, for example 'src/tui/app.py'."
    )


class ShowGitDiffTool:
    """Load typed HEAD-versus-worktree content without allowing errors to break an agent run."""

    @classmethod
    async def invoke(
        cls,
        *,
        repository_relative_path: str,
        workdir: Path,
    ) -> GitDiffContentDAO:
        """Load Git diff content or return a stable safe stub.

        WHAT: Delegates to GitDiffContentService, the shared read-only validation
        boundary, and converts every expected or unexpected failure to UNCHANGED.
        WHO: The LangChain bridge and direct in-process callers invoke this method.
        WHEN: Runs when an agent needs to inspect one changed repository file.

        Args:
            repository_relative_path (str): File path relative to the repository root.
            workdir (Path): Required caller-selected repository scope.

        Returns:
            GitDiffContentDAO: Loaded typed content or an empty UNCHANGED error stub.
        """
        try:
            return await GitDiffContentService.invoke(
                requested_path=repository_relative_path,
                workdir=workdir,
            )
        except GitDiffContentError as exception:
            log_error(msg="show_git_diff content error", error=exception.operator_message)
            return cls._build_error_stub(repository_relative_path=repository_relative_path)
        except Exception as exception:  # noqa: BLE001 - a LangChain tool must never terminate the agent loop
            log_error(msg="show_git_diff unexpected error", error=str(exception))
            return cls._build_error_stub(repository_relative_path=repository_relative_path)

    @classmethod
    def _build_error_stub(cls, *, repository_relative_path: str) -> GitDiffContentDAO:
        """Build the empty UNCHANGED result shared by both tool failure branches.

        WHAT: Represents an unavailable diff without exposing internal failure detail.
        WHO: invoke calls this after expected and unexpected service failures.
        WHEN: The tool must return safely rather than propagate an error into the agent.

        Args:
            repository_relative_path (str): The unmodified caller-provided path.

        Returns:
            GitDiffContentDAO: Empty safe result carrying FileStateKind.UNCHANGED.
        """
        return GitDiffContentDAO(
            repository_relative_path=repository_relative_path,
            base_content="",
            changed_content="",
            file_state=FileStateKind.UNCHANGED,
        )


@tool(name_or_callable="show_git_diff", args_schema=ShowGitDiffSchemaDAO)
async def show_git_diff_tool(repository_relative_path: str) -> str:
    """Show one file's safe HEAD-versus-worktree diff as structured JSON.

    WHAT: Resolves the process working directory using Slo's established
    cwd-bound-tool convention, delegates to ShowGitDiffTool, and serializes its DAO.
    WHO: LangChain calls this bridge when the model invokes ``show_git_diff``.
    WHEN: Use after edits or when an operator asks what changed in one file.

    Args:
        repository_relative_path (str): POSIX file path relative to the repository root.

    Returns:
        str: JSON-serialized GitDiffContentDAO suitable for a LangChain ToolMessage.
    """
    log_info(msg=f"Using show_git_diff tool for path: {repository_relative_path!r}")
    result = await ShowGitDiffTool.invoke(
        repository_relative_path=repository_relative_path,
        workdir=Path(os.getcwd()),
    )
    return result.model_dump_json()


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        """Run a local manual smoke check against the repository worktree."""
        result = await ShowGitDiffTool.invoke(
            repository_relative_path="src/agents/tools/show_git_diff.py",
            workdir=Path(__file__).resolve().parents[3],
        )
        log_info(msg=f"show_git_diff smoke state: {result.file_state}")

    asyncio.run(main())
