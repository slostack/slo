"""``read`` tool — read a UTF-8 text file or attach an image (sub-spec 01.d §4.1).

Follows ``awesome-agi/build-agent-tools.md`` conventions: ``*SchemaDAO`` args,
``ReadTool`` class with classmethod ``invoke``, ``@tool``-decorated bridge
function, ``__all__``, ``__main__`` block, ``log_info`` at entry.

Description text is lifted verbatim from pi ``read.ts:215`` with the Python
truncation constants interpolated at import time.

Text results remain raw strings. Image results use ``ToolResultDAO`` so the
executor can keep live multimodal content separate from the compact durable
image reference. See ``docs/RESEARCH.md`` for the tool architecture.
"""

from __future__ import annotations

READ_PROMPT_SNIPPET: str = (
    "read the contents of a UTF-8 text file at a given path, or attach an image; PDFs should use read_pdf"
)

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.slo_agent.tool_execution.dao import ToolResultDAO
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._image_content import ImageContent, ImageResizeResult
from src.agents.tools._truncate import DEFAULT_MAX_BYTES, TruncationResult, Truncator

__all__ = [
    "ReadSchemaDAO",
    "ReadTool",
    "read_tool",
]


class ReadSchemaDAO(BaseModel):
    """LangChain args schema for the read tool."""

    path: str = Field(description="Path to the file to read (relative or absolute)")
    offset: Optional[int] = Field(
        default=None,
        description="Line number to start reading from (1-indexed)",
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of lines to read",
    )

    model_config = ConfigDict(
        title="ReadSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


class ReadTool:
    @classmethod
    async def invoke(
        cls,
        path: str,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> str | ToolResultDAO:
        """Read a file. See ``read_tool`` for the user-facing description.

        Args:
            path (str): Path to the file (relative or absolute).
            offset (Optional[int]): 1-indexed line to start reading from.
            limit (Optional[int]): Maximum number of lines to read.

        Returns:
            str | ToolResultDAO: File content as text, or structured image
                content with a compact durable reference. Errors are returned
                as ``"Error: ..."`` strings.
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            path=path,
            offset=offset,
            limit=limit,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        path: str,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> str | ToolResultDAO:
        """Read a file synchronously for thread-offloaded callers.

        Args:
            path (str): Path to the file (relative or absolute).
            offset (Optional[int]): 1-indexed line to start reading from.
            limit (Optional[int]): Maximum number of lines to read.

        Returns:
            str | ToolResultDAO: File content as text, or structured image
                content with a compact durable reference.
        """
        try:
            target = Path(path)
            if not target.exists():
                return f"Error: file not found: {path}"
            if target.is_dir():
                return f"Error: path is a directory, use ls: {path}"

            if ImageContent.is_image(path=target):
                result: ImageResizeResult = ImageContent.build_block(path=target)
                return ToolResultDAO(
                    content=[dict(result["block"])],
                    image_reference=result["reference"],
                )

            if cls._is_pdf(path=target):
                return f"Error: {path} is a PDF. Use read_pdf instead."
            if cls._looks_binary(path=target):
                return f"Error: {path} appears to be a binary file and cannot be read as text."

            try:
                with target.open(mode="r", encoding="utf-8", newline="") as handle:
                    raw: str = handle.read()
            except UnicodeDecodeError as exc:
                return f"Error: cannot decode {path} as UTF-8 text: {exc}"

            return cls._format_text(text=raw, offset=offset, limit=limit)
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg=f"ReadTool failed for {path}", e=exc, stack_trace=False)
            return f"Error: read failed: {exc}"

    @classmethod
    def _is_pdf(cls, *, path: Path) -> bool:
        """Return ``True`` when ``path`` points to a PDF file."""
        return path.suffix.lower() == ".pdf"

    @classmethod
    def _looks_binary(cls, *, path: Path) -> bool:
        """Return ``True`` when a small byte sample looks binary."""
        with path.open("rb") as handle:
            sample: bytes = handle.read(8192)
        return b"\x00" in sample

    @classmethod
    def _format_text(cls, *, text: str, offset: Optional[int], limit: Optional[int]) -> str:
        """Select complete lines and attach file-wide continuation guidance.

        Args:
            text (str): Full decoded file content.
            offset (Optional[int]): One-based starting line, clamped to one.
            limit (Optional[int]): Caller line limit, or None for the remaining file.

        Returns:
            str: Selected content with guidance only when unread lines remain.
        """
        lines: list[str] = text.splitlines(keepends=True)
        start: int = max(0, (offset or 1) - 1)
        end: Optional[int] = start + limit if limit is not None else None
        selected: list[str] = lines[start:end]
        truncated: TruncationResult = Truncator.head(text="".join(selected))
        if not truncated.kept_lines:
            return cls._no_progress(start=start, total=len(lines), oversized=truncated.truncated)
        body: str = "".join(selected[: truncated.kept_lines])
        return body + cls._continuation(
            start=start, end=start + truncated.kept_lines, total=len(lines), truncated=truncated.truncated
        )

    @classmethod
    def _no_progress(cls, *, start: int, total: int, oversized: bool) -> str:
        """Explain why an empty read cannot advance, without skipping any content.

        Args:
            start (int): Zero-based index of the requested first line.
            total (int): Full-file line count.
            oversized (bool): Whether the first selected line exceeds the byte budget.

        Returns:
            str: Bounded guidance for the blocking line or caller limit; empty at EOF.
        """
        if oversized:
            return (
                f"[Line {start + 1} exceeds the {DEFAULT_MAX_BYTES}-byte read limit. No lines were read. "
                f"Use bash to inspect at most {DEFAULT_MAX_BYTES} bytes of that line, or create a copy "
                "with shorter lines and read the copy.]"
            )
        if start >= total:
            return ""
        return (
            f"[{total - start} more lines. No lines were read. "
            f"Use offset={start + 1} and change or omit limit to continue.]"
        )

    @classmethod
    def _continuation(cls, *, start: int, end: int, total: int, truncated: bool) -> str:
        """Describe the next unread line after a nonempty text selection.

        Args:
            start (int): Zero-based index of the first displayed line.
            end (int): Exclusive index of the last displayed line.
            total (int): Full-file line count, before caller slicing.
            truncated (bool): Whether the output budget shortened the selection.

        Returns:
            str: A separated continuation footer, or an empty string at EOF.
        """
        if end >= total:
            return ""
        if truncated:
            return f"\n\n[Showing lines {start + 1}-{end} of {total}. Use offset={end + 1} to continue.]"
        return f"\n\n[{total - end} more lines. Use offset={end + 1} to continue.]"


@tool(name_or_callable="read", args_schema=ReadSchemaDAO)
async def read_tool(
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> str | ToolResultDAO:
    """Read the contents of a UTF-8 text file. Supports images (jpg, png, gif, webp) as attachments. PDFs should use ``read_pdf``. Binary files return an error. For text files, output is truncated to 2000 lines or 64KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.

    Args:
        path (str): Path to the file (relative or absolute).
        offset (Optional[int]): 1-indexed line to start reading from.
        limit (Optional[int]): Maximum number of lines to read.

    Returns:
        str | ToolResultDAO: File content as text, or structured image content
            with a compact durable reference.
    """
    log_info(msg=f"Using Read Tool with path: {path}")
    return await ReadTool.invoke(path=path, offset=offset, limit=limit)


if __name__ == "__main__":
    # Quick test harness: exercises ReadTool against three scenarios so a
    # developer can run ``python -m src.agents.tools.read`` and see real
    # behaviour without standing up the full agent stack.
    import asyncio
    import tempfile

    async def main() -> None:
        # Scenario 1 — read this very file's first 5 lines.
        print("---[ scenario 1: read self, offset=1 limit=5 ]---")
        print(await ReadTool.invoke(path=__file__, offset=1, limit=5))

        # Scenario 2 — read a fresh temp file end-to-end.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("line1\nline2\nline3\n")
            temp_path = fh.name
        print(f"\n---[ scenario 2: read freshly-written file {temp_path} ]---")
        print(await ReadTool.invoke(path=temp_path))

        # Scenario 3 — try to read a missing path (expect an Error: string).
        print("\n---[ scenario 3: read missing path ]---")
        print(await ReadTool.invoke(path="/tmp/slo-does-not-exist-xyz"))

    asyncio.run(main())
