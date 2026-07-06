"""``write`` tool — full-file write with parent-dir auto-create (sub-spec 01.d §4.2).

Follows ``awesome-agi/build-agent-tools.md`` conventions. Description text is
lifted verbatim from pi ``write.ts:190``.
"""

from __future__ import annotations

WRITE_PROMPT_SNIPPET: str = (
    "create or overwrite a file — pass the complete file content inline as the content argument"
)

from pathlib import Path

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call

__all__ = [
    "WriteSchemaDAO",
    "WriteTool",
    "write_tool",
]


class WriteSchemaDAO(BaseModel):
    """LangChain args schema for the write tool."""

    path: str = Field(description="Path to the file to write (relative or absolute)")
    content: str = Field(
        description=(
            "Complete file content to write, passed inline in this tool call — "
            "do not output content as text first and then call write with only a path"
        )
    )

    model_config = ConfigDict(
        title="WriteSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class WriteTool:
    @classmethod
    async def invoke(cls, path: str, content: str) -> str:
        """Write content to a file.

        Args:
            path (str): Destination path (relative or absolute). Parent
                directories are created if they don't exist.
            content (str): UTF-8 text to write.

        Returns:
            str: Confirmation message ``"Wrote N bytes to <path>"`` on
                success, or ``"Error: ..."`` on failure.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            path=path,
            content=content,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        path: str,
        content: str,
    ) -> str:
        """Write content synchronously for thread-offloaded callers.

        Args:
            path (str): Destination path (relative or absolute).
            content (str): UTF-8 text to write.

        Returns:
            str: Confirmation of bytes written, or an error message.
        """
        try:
            target = Path(path)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                return f"Error: failed to write {path}: {exc}"

            return f"Wrote {len(content.encode('utf-8'))} bytes to {target}"
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg=f"WriteTool failed for {path}", e=exc, stack_trace=False)
            return f"Error: write failed: {exc}"


@tool(name_or_callable="write", args_schema=WriteSchemaDAO)
async def write_tool(path: str, content: str) -> str:
    """Write content to a file — pass the complete file content inline as the content argument. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories.

    Args:
        path (str): Destination path (relative or absolute).
        content (str): Complete UTF-8 text to write, supplied inline in this tool call.

    Returns:
        str: Confirmation of bytes written, or an error message.
    """
    log_info(msg=f"Using Write Tool with path: {path}")
    return await WriteTool.invoke(path=path, content=content)


if __name__ == "__main__":
    # Quick test harness: exercises WriteTool against three scenarios.
    import asyncio
    import tempfile
    from pathlib import Path as _Path

    async def main() -> None:
        # Scenario 1 — write a new file.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            target = fh.name
        print("---[ scenario 1: write new file ]---")
        print(await WriteTool.invoke(path=target, content="hello from slo write tool\n"))
        print(f"contents: {_Path(target).read_text()!r}")

        # Scenario 2 — overwrite the same file.
        print("\n---[ scenario 2: overwrite ]---")
        print(await WriteTool.invoke(path=target, content="second pass\n"))
        print(f"contents: {_Path(target).read_text()!r}")

        # Scenario 3 — write into a nested directory that does not exist yet.
        nested = _Path(tempfile.gettempdir()) / "slo_write_demo" / "deep" / "out.txt"
        print(f"\n---[ scenario 3: create parent dirs at {nested} ]---")
        print(await WriteTool.invoke(path=str(nested), content="auto-created parents\n"))
        print(f"contents: {nested.read_text()!r}")

    asyncio.run(main())
