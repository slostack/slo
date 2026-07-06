"""``grep`` tool — pattern search across file contents (sub-spec 01.e §4.1).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Description text
is lifted verbatim from pi ``grep.ts:131`` with Python constants
interpolated at import time.
"""

from __future__ import annotations

GREP_PROMPT_SNIPPET: str = "search file contents for a pattern, respecting .gitignore"

import re
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._gitignore import GitignoreFilter
from src.agents.tools._truncate import (
    DEFAULT_LIMIT_GREP,
    DEFAULT_MAX_BYTES,
    Truncator,
)

__all__ = [
    "GrepSchemaDAO",
    "GrepTool",
    "grep_tool",
]


class GrepSchemaDAO(BaseModel):
    """LangChain args schema for the grep tool."""

    pattern: str = Field(description="Search pattern (regex or literal string)")
    path: Optional[str] = Field(
        default=None,
        description="Directory or file to search (default: current directory)",
    )
    glob: Optional[str] = Field(
        default=None,
        description="Filter files by glob pattern, e.g. '*.py' or '**/*.spec.py'",
    )
    ignoreCase: Optional[bool] = Field(
        default=False,
        description="Case-insensitive search (default: false)",
    )
    literal: Optional[bool] = Field(
        default=False,
        description=("Treat pattern as literal string instead of regex (default: false)"),
    )
    context: Optional[int] = Field(
        default=0,
        description="Number of lines to show before and after each match (default: 0)",
    )
    limit: Optional[int] = Field(
        default=DEFAULT_LIMIT_GREP,
        description=f"Maximum number of matches to return (default: {DEFAULT_LIMIT_GREP})",
    )

    model_config = ConfigDict(
        title="GrepSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class GrepTool:
    @classmethod
    async def invoke(
        cls,
        pattern: str,
        path: Optional[str] = None,
        glob: Optional[str] = None,
        ignoreCase: Optional[bool] = False,
        literal: Optional[bool] = False,
        context: Optional[int] = 0,
        limit: Optional[int] = DEFAULT_LIMIT_GREP,
    ) -> str:
        """Search files under ``path`` for lines matching ``pattern``.

        Args:
            pattern (str): Regex (default) or literal string when
                ``literal=True``.
            path (Optional[str]): Search root. Defaults to cwd.
            glob (Optional[str]): Optional filename glob filter.
            ignoreCase (Optional[bool]): Case-insensitive regex flag.
            literal (Optional[bool]): Treat ``pattern`` as a literal.
            context (Optional[int]): Number of context lines before / after
                each match.
            limit (Optional[int]): Hard cap on match count.

        Returns:
            str: ``file:line:match`` rows separated by newlines, or
                ``"(no matches ...)"`` / ``"Error: ..."`` on no-hit / failure.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            pattern=pattern,
            path=path,
            glob=glob,
            ignoreCase=ignoreCase,
            literal=literal,
            context=context,
            limit=limit,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        pattern: str,
        path: Optional[str] = None,
        glob: Optional[str] = None,
        ignoreCase: Optional[bool] = False,
        literal: Optional[bool] = False,
        context: Optional[int] = 0,
        limit: Optional[int] = DEFAULT_LIMIT_GREP,
    ) -> str:
        """Search files synchronously for lines matching ``pattern``.

        Args:
            pattern (str): Regex (default) or literal string when ``literal=True``.
            path (Optional[str]): Search root. Defaults to cwd.
            glob (Optional[str]): Optional filename glob filter.
            ignoreCase (Optional[bool]): Case-insensitive regex flag.
            literal (Optional[bool]): Treat ``pattern`` as a literal.
            context (Optional[int]): Number of context lines before / after each match.
            limit (Optional[int]): Hard cap on match count.

        Returns:
            str: Rendered grep rows, or a no-match / error message.
        """
        try:
            root = Path(path) if path else Path.cwd()
            if not root.exists():
                return f"Error: search path not found: {root}"

            flags: re.RegexFlag = re.IGNORECASE if ignoreCase else re.RegexFlag(0)
            regex_text: str = re.escape(pattern) if literal else pattern
            try:
                regex = re.compile(regex_text, flags)
            except re.error as exc:
                return f"Error: invalid regex: {exc}"

            targets: list[Path] = [root] if root.is_file() else cls._iter_files(root=root, glob=glob)
            filt: GitignoreFilter = GitignoreFilter.load_for(
                search_root=root if root.is_dir() else root.parent,
            )

            out_lines: list[str] = []
            total_bytes = 0
            match_count = 0
            limit_value: int = limit or DEFAULT_LIMIT_GREP

            for file in targets:
                if filt.is_ignored(path=file):
                    continue
                try:
                    content = file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                lines: list[str] = content.splitlines()
                for index, line in enumerate(lines, start=1):
                    if not regex.search(line):
                        continue
                    rendered: str = f"{file}:{index}:{Truncator.line(line=line)}"
                    out_lines.append(rendered)
                    total_bytes += len(rendered.encode("utf-8")) + 1
                    match_count += 1

                    if context and context > 0:
                        cls._append_context(
                            out_lines=out_lines,
                            file=file,
                            lines=lines,
                            hit=index,
                            context=context,
                        )

                    if match_count >= limit_value or total_bytes >= DEFAULT_MAX_BYTES:
                        out_lines.append(
                            f"\n[limit reached: {match_count} matches, "
                            f"{Truncator.format_size(num_bytes=total_bytes)}]"
                        )
                        return "\n".join(out_lines)

            if not out_lines:
                return f"(no matches for {pattern!r} in {root})"
            return "\n".join(out_lines)
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg="GrepTool failed", e=exc, stack_trace=False)
            return f"Error: grep failed: {exc}"

    @classmethod
    def _iter_files(cls, root: Path, glob: Optional[str]) -> list[Path]:
        pattern = glob or "**/*"
        return [p for p in root.glob(pattern) if p.is_file()]

    @classmethod
    def _append_context(
        cls,
        out_lines: list[str],
        file: Path,
        lines: list[str],
        hit: int,
        context: int,
    ) -> None:
        start = max(1, hit - context)
        end = min(len(lines), hit + context)
        for i in range(start, end + 1):
            if i == hit:
                continue
            out_lines.append(f"{file}:{i}-{Truncator.line(line=lines[i - 1])}")


@tool(name_or_callable="grep", args_schema=GrepSchemaDAO)
async def grep_tool(
    pattern: str,
    path: Optional[str] = None,
    glob: Optional[str] = None,
    ignoreCase: Optional[bool] = False,
    literal: Optional[bool] = False,
    context: Optional[int] = 0,
    limit: Optional[int] = DEFAULT_LIMIT_GREP,
) -> str:
    """Search file contents for a pattern. Returns matching lines with file paths and line numbers. Respects .gitignore. Output is truncated to 100 matches or 64KB (whichever is hit first). Long lines are truncated to 500 chars.

    Args:
        pattern (str): Search pattern. Regex by default; literal when ``literal=True``.
        path (Optional[str]): Directory or file to search. Defaults to the current working directory.
        glob (Optional[str]): Glob filter applied to filenames (e.g. ``'*.py'``).
        ignoreCase (Optional[bool]): Case-insensitive search.
        literal (Optional[bool]): Treat ``pattern`` as a literal string.
        context (Optional[int]): Lines of surrounding context per match.
        limit (Optional[int]): Max matches to return.

    Returns:
        str: ``file:line:match`` rows, or a no-match / error message.
    """
    log_info(msg=f"Using Grep Tool with pattern: {pattern!r}")
    return await GrepTool.invoke(
        pattern=pattern,
        path=path,
        glob=glob,
        ignoreCase=ignoreCase,
        literal=literal,
        context=context,
        limit=limit,
    )


if __name__ == "__main__":
    # Quick test harness: exercises GrepTool against three scenarios.
    import asyncio

    async def main() -> None:
        # Scenario 1 — find "def " in this file.
        print("---[ scenario 1: 'def ' in this file ]---")
        print(await GrepTool.invoke(pattern="def ", path=__file__, limit=5))

        # Scenario 2 — literal search (no regex interpretation).
        print("\n---[ scenario 2: literal '(' in this file ]---")
        print(await GrepTool.invoke(pattern="(", path=__file__, literal=True, limit=3))

        # Scenario 3 — invalid regex returns clean error.
        print("\n---[ scenario 3: invalid regex ]---")
        print(await GrepTool.invoke(pattern="(unclosed", path=__file__))

    asyncio.run(main())
