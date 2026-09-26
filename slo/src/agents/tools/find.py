"""``find`` tool — glob-based filename search (sub-spec 01.e §4.2).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Description text
is lifted verbatim from pi ``find.ts:119``.
"""

from __future__ import annotations

FIND_PROMPT_SNIPPET: str = "find files by glob pattern, respecting .gitignore"

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._gitignore import GitignoreFilter
from src.agents.tools._glob import GlobMatcher
from src.agents.tools._truncate import (
    DEFAULT_LIMIT_FIND,
    DEFAULT_MAX_BYTES,
    Truncator,
)

__all__ = [
    "FindSchemaDAO",
    "FindTool",
    "find_tool",
]


class FindSchemaDAO(BaseModel):
    """LangChain args schema for the find tool."""

    pattern: str = Field(
        description=(
            "Glob pattern to match files. A pattern without '/' matches file names "
            "at any depth, e.g. '*.py'; a pattern with '/' is matched relative to "
            "the search directory, e.g. 'src/*.py' or 'src/**/*.spec.py'"
        ),
    )
    path: Optional[str] = Field(
        default=None,
        description="Directory to search in (default: current directory)",
    )
    limit: Optional[int] = Field(
        default=DEFAULT_LIMIT_FIND,
        description=f"Maximum number of results (default: {DEFAULT_LIMIT_FIND})",
    )

    model_config = ConfigDict(
        title="FindSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class FindTool:
    @classmethod
    async def invoke(
        cls,
        pattern: str,
        path: Optional[str] = None,
        limit: Optional[int] = DEFAULT_LIMIT_FIND,
    ) -> str:
        """Glob-walk ``path`` and return matching relative paths.

        Args:
            pattern (str): Tool glob pattern; see ``GlobMatcher``.
            path (Optional[str]): Search root. Defaults to cwd.
            limit (Optional[int]): Hard cap on result count.

        Returns:
            str: Newline-separated relative paths (sorted), or a no-match /
                error message.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            pattern=pattern,
            path=path,
            limit=limit,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        pattern: str,
        path: Optional[str] = None,
        limit: Optional[int] = DEFAULT_LIMIT_FIND,
    ) -> str:
        """Glob-walk ``path`` synchronously and return matching paths.

        Args:
            pattern (str): Tool glob pattern; see ``GlobMatcher``.
            path (Optional[str]): Search root. Defaults to cwd.
            limit (Optional[int]): Hard cap on result count.

        Returns:
            str: Matching relative paths, or a no-match / error message.
        """
        try:
            root = Path(path) if path else Path.cwd()
            if not root.exists():
                return f"Error: search path not found: {root}"
            if not root.is_dir():
                return f"Error: search path is not a directory: {root}"

            limit_value: int = limit or DEFAULT_LIMIT_FIND
            filt: GitignoreFilter = GitignoreFilter.load_for(search_root=root)

            out: list[str] = []
            total_bytes = 0
            for match in GlobMatcher.iter_matches(root=root, pattern=pattern):
                if not match.is_file():
                    continue
                if filt.is_ignored(path=match):
                    continue
                rel: Path = match.relative_to(root)
                rendered: str = str(rel)
                out.append(rendered)
                total_bytes += len(rendered.encode("utf-8")) + 1
                if len(out) >= limit_value or total_bytes >= DEFAULT_MAX_BYTES:
                    out.append(
                        f"\n[limit reached: {len(out)} results, "
                        f"{Truncator.format_size(num_bytes=total_bytes)}]"
                    )
                    return "\n".join(out)

            out.sort()
            if not out:
                return f"(no files matching {pattern!r} under {root})"
            return "\n".join(out)
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg="FindTool failed", e=exc, stack_trace=False)
            return f"Error: find failed: {exc}"


@tool(name_or_callable="find", args_schema=FindSchemaDAO)
async def find_tool(
    pattern: str,
    path: Optional[str] = None,
    limit: Optional[int] = DEFAULT_LIMIT_FIND,
) -> str:
    """Search for files by glob pattern. Returns matching file paths relative to the search directory. Respects .gitignore. Output is truncated to 1000 results or 64KB (whichever is hit first).

    Args:
        pattern (str): Glob pattern to match files.
        path (Optional[str]): Directory to search in.
        limit (Optional[int]): Max results.

    Returns:
        str: Sorted relative paths, or a no-match / error message.
    """
    log_info(msg=f"Using Find Tool with pattern: {pattern!r}")
    return await FindTool.invoke(pattern=pattern, path=path, limit=limit)


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        # Scenario 1 — find all Python files under cwd.
        print("---[ scenario 1: **/*.py under cwd ]---")
        print(await FindTool.invoke(pattern="**/*.py", limit=5))

        # Scenario 2 — pattern that matches nothing.
        print("\n---[ scenario 2: **/*.rs (no Rust here) ]---")
        print(await FindTool.invoke(pattern="**/*.rs"))

        # Scenario 3 — error: search path is a file, not a directory.
        print("\n---[ scenario 3: search path is a file ]---")
        print(await FindTool.invoke(pattern="*", path=__file__))

    asyncio.run(main())
