"""``read`` tool — read a UTF-8 text file or attach an image (sub-spec 01.d §4.1).

Follows ``awesome-agi/build-agent-tools.md`` conventions: ``*SchemaDAO`` args,
``ReadTool`` class with classmethod ``invoke``, ``@tool``-decorated bridge
function, ``__all__``, ``__main__`` block, ``log_info`` at entry.

Description text is lifted verbatim from pi ``read.ts:215`` with the Python
truncation constants interpolated at import time.

Deviation note: returns ``str | list[ImageContentBlock]`` rather than a ``*ResultDAO``.
Coding agents consume raw file text directly from ``ToolMessage.content``;
JSON-wrapping the file body would force the model to parse it back out, and
image attachments require the multimodal content-list shape natively. See
``docs/RESEARCH.md`` for the full deviation rationale.
"""

from __future__ import annotations

READ_PROMPT_SNIPPET: str = "read the contents of a UTF-8 text file at a given path, or attach an image; PDFs should use read_pdf"

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._image_content import ImageContent, ImageContentBlock
from src.agents.tools._truncate import Truncator

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
    ) -> str | list[ImageContentBlock]:
        """Read a file. See ``read_tool`` for the user-facing description.

        Args:
            path (str): Path to the file (relative or absolute).
            offset (Optional[int]): 1-indexed line to start reading from.
            limit (Optional[int]): Maximum number of lines to read.

        Returns:
            str | list[ImageContentBlock]: File content as text, or a
                LangChain multimodal content list with one image block for
                image files. Errors are returned as ``"Error: ..."`` strings.
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
    ) -> str | list[ImageContentBlock]:
        """Read a file synchronously for thread-offloaded callers.

        Args:
            path (str): Path to the file (relative or absolute).
            offset (Optional[int]): 1-indexed line to start reading from.
            limit (Optional[int]): Maximum number of lines to read.

        Returns:
            str | list[ImageContentBlock]: File content as text, or a
                multimodal image block.
        """
        try:
            target = Path(path)
            if not target.exists():
                return f"Error: file not found: {path}"
            if target.is_dir():
                return f"Error: path is a directory, use ls: {path}"

            if ImageContent.is_image(path=target):
                return [ImageContent.build_block(path=target)]

            if cls._is_pdf(path=target):
                return f"Error: {path} is a PDF. Use read_pdf instead."
            if cls._looks_binary(path=target):
                return f"Error: {path} appears to be a binary file and cannot be read as text."

            try:
                raw: str = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                return f"Error: cannot decode {path} as UTF-8 text: {exc}"

            sliced: str = cls._slice(text=raw, offset=offset, limit=limit)
            return Truncator.head(text=sliced).text
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
    def _slice(cls, text: str, offset: Optional[int], limit: Optional[int]) -> str:
        """Apply offset/limit line slicing if either is set; otherwise pass through."""
        if offset is None and limit is None:
            return text
        lines = text.splitlines(keepends=True)
        start = max(0, (offset or 1) - 1)
        end = start + limit if limit is not None else None
        return "".join(lines[start:end])


@tool(name_or_callable="read", args_schema=ReadSchemaDAO)
async def read_tool(
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> str | list[ImageContentBlock]:
    """Read the contents of a UTF-8 text file. Supports images (jpg, png, gif, webp) as attachments. PDFs should use ``read_pdf``. Binary files return an error. For text files, output is truncated to 2000 lines or 64KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.

    Args:
        path (str): Path to the file (relative or absolute).
        offset (Optional[int]): 1-indexed line to start reading from.
        limit (Optional[int]): Maximum number of lines to read.

    Returns:
        str | list[ImageContentBlock]: File content as text, or a
            multimodal content list with one image block for image files.
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
