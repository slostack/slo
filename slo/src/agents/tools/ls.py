"""``ls`` tool — directory listing (sub-spec 01.e §4.3).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Description text
is lifted verbatim from pi ``ls.ts:107``.
"""

from __future__ import annotations

LS_PROMPT_SNIPPET: str = "list the contents of a directory"

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._truncate import (
    DEFAULT_LIMIT_LS,
    DEFAULT_MAX_BYTES,
    Truncator,
)

__all__ = [
    "LsSchemaDAO",
    "LsTool",
    "ls_tool",
]


class LsSchemaDAO(BaseModel):
    """LangChain args schema for the ls tool."""

    path: Optional[str] = Field(
        default=None,
        description="Directory to list (default: current directory)",
    )
    limit: Optional[int] = Field(
        default=DEFAULT_LIMIT_LS,
        description=f"Maximum number of entries to return (default: {DEFAULT_LIMIT_LS})",
    )

    model_config = ConfigDict(
        title="LsSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class LsTool:
    @classmethod
    async def invoke(
        cls,
        path: Optional[str] = None,
        limit: Optional[int] = DEFAULT_LIMIT_LS,
    ) -> str:
        """Return sorted directory contents with ``/`` suffix on subdirs.

        Args:
            path (Optional[str]): Directory to list. Defaults to cwd.
            limit (Optional[int]): Hard cap on entry count.

        Returns:
            str: Newline-separated entries, or an error / empty-directory
                message.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            path=path,
            limit=limit,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        path: Optional[str] = None,
        limit: Optional[int] = DEFAULT_LIMIT_LS,
    ) -> str:
        """Return sorted directory contents synchronously.

        Args:
            path (Optional[str]): Directory to list. Defaults to cwd.
            limit (Optional[int]): Hard cap on entry count.

        Returns:
            str: Directory listing, or an error / empty-directory message.
        """
        try:
            root = Path(path) if path else Path.cwd()
            if not root.exists():
                return f"Error: path not found: {root}"
            if not root.is_dir():
                return f"Error: path is not a directory: {root}"

            limit_value: int = limit or DEFAULT_LIMIT_LS
            try:
                entries: list[Path] = sorted(root.iterdir(), key=lambda item: item.name)
            except PermissionError as exc:
                return f"Error: permission denied: {exc}"

            out: list[str] = []
            total_bytes = 0
            for entry in entries:
                name: str = entry.name + ("/" if entry.is_dir() else "")
                out.append(name)
                total_bytes += len(name.encode("utf-8")) + 1
                if len(out) >= limit_value or total_bytes >= DEFAULT_MAX_BYTES:
                    out.append(
                        f"\n[limit reached: {len(out)} entries, "
                        f"{Truncator.format_size(num_bytes=total_bytes)}]"
                    )
                    return "\n".join(out)

            return "\n".join(out) if out else f"(empty directory: {root})"
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg="LsTool failed", e=exc, stack_trace=False)
            return f"Error: ls failed: {exc}"


@tool(name_or_callable="ls", args_schema=LsSchemaDAO)
async def ls_tool(
    path: Optional[str] = None,
    limit: Optional[int] = DEFAULT_LIMIT_LS,
) -> str:
    """List directory contents. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to 500 entries or 64KB (whichever is hit first).

    Args:
        path (Optional[str]): Directory to list.
        limit (Optional[int]): Max entries to return.

    Returns:
        str: Sorted entries, or an error / empty-directory message.
    """
    log_info(msg=f"Using Ls Tool with path: {path or '<cwd>'}")
    return await LsTool.invoke(path=path, limit=limit)


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        # Scenario 1 — list cwd.
        print("---[ scenario 1: cwd ]---")
        print(await LsTool.invoke())

        # Scenario 2 — list this tool's own directory.
        print("\n---[ scenario 2: src/agents/tools/ ]---")
        print(await LsTool.invoke(path=str(Path(__file__).parent)))

        # Scenario 3 — error: missing path.
        print("\n---[ scenario 3: missing path ]---")
        print(await LsTool.invoke(path="/tmp/slo-not-there-xyz"))

    asyncio.run(main())
