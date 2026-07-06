"""``read_pdf`` tool — extract text from a PDF file (sub-spec 01.e extension).

Uses ``pypdf`` for pure-Python text extraction (no system deps). Page
selection mirrors the Read-tool ``offset/limit`` convention but expresses
ranges as a string (``"1-5"``, ``"3"``, ``"10-20"``) since PDF pages are
1-indexed and discontinuous selections are rare.

Returns plain text (truncated via ``_truncate.Truncator.head``). Native
multimodal PDF attachments (Anthropic-only ``document`` content blocks)
are a v1.1 toggle — text extraction works for every provider and matches
the LLM's coding-agent consumption pattern.
"""

from __future__ import annotations

READ_PDF_PROMPT_SNIPPET: str = "extract text from a PDF file, optionally for a page range"

import re
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from config.logger import log_error, log_info
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools._truncate import Truncator

__all__ = [
    "ReadPdfSchemaDAO",
    "ReadPdfTool",
    "read_pdf_tool",
]


class ReadPdfSchemaDAO(BaseModel):
    """LangChain args schema for the read_pdf tool."""

    path: str = Field(description="Path to the PDF file (relative or absolute)")
    pages: Optional[str] = Field(
        default=None,
        description=(
            "Optional page range, 1-indexed and inclusive. Examples: "
            "'1-5', '3', '10-20'. Omit to read every page."
        ),
    )
    password: Optional[str] = Field(
        default=None,
        description="Password for encrypted PDFs. Omit for unencrypted files.",
    )

    model_config = ConfigDict(
        title="ReadPdfSchemaDAO",
        extra="ignore",
        from_attributes=True,
    )


_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)\s*)?$")


class ReadPdfTool:
    @classmethod
    async def invoke(
        cls,
        path: str,
        pages: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Extract text from a PDF.

        Args:
            path (str): Path to the PDF file.
            pages (Optional[str]): 1-indexed inclusive range; ``"3"`` for
                a single page, ``"5-10"`` for a range. None = whole document.
            password (Optional[str]): Password for encrypted PDFs.

        Returns:
            str: Extracted text (head-truncated), or ``"Error: ..."`` on
                failure (missing file, malformed PDF, bad password, bad range).
        """
        return await run_blocking_tool_call(
            func=cls._invoke_sync,
            path=path,
            pages=pages,
            password=password,
        )

    @classmethod
    def _invoke_sync(
        cls,
        *,
        path: str,
        pages: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        """Extract text from a PDF synchronously.

        Args:
            path (str): Path to the PDF file.
            pages (Optional[str]): Optional 1-indexed page range.
            password (Optional[str]): Password for encrypted PDFs.

        Returns:
            str: Extracted text, or an error message.
        """
        try:
            target = Path(path)
            if not target.exists():
                return f"Error: file not found: {path}"
            if target.is_dir():
                return f"Error: path is a directory: {path}"

            try:
                reader = PdfReader(target)
            except PdfReadError as exc:
                return f"Error: invalid PDF: {exc}"

            if reader.is_encrypted:
                if not password:
                    return "Error: PDF is encrypted; pass 'password' to decrypt"
                if not reader.decrypt(password):
                    return "Error: PDF password is incorrect"

            total_pages: int = len(reader.pages)
            try:
                start, end = cls._parse_range(pages=pages, total_pages=total_pages)
            except ValueError as exc:
                return f"Error: {exc}"

            chunks: list[str] = []
            for page_num in range(start, end + 1):
                try:
                    text: str = reader.pages[page_num - 1].extract_text() or ""
                except FileNotDecryptedError as exc:
                    return f"Error: page {page_num} undecryptable: {exc}"
                chunks.append(f"--- page {page_num} ---\n{text.rstrip()}")

            body: str = "\n\n".join(chunks)
            header: str = (
                f"[PDF: {target.name} · {total_pages} pages total · " f"extracted pages {start}-{end}]\n\n"
            )
            return Truncator.head(text=header + body).text
        except Exception as exc:  # noqa: BLE001 — surface to model
            log_error(msg=f"ReadPdfTool failed for {path}", e=exc, stack_trace=False)
            return f"Error: read_pdf failed: {exc}"

    @classmethod
    def _parse_range(
        cls,
        pages: Optional[str],
        total_pages: int,
    ) -> tuple[int, int]:
        """Resolve ``pages`` string into a 1-indexed inclusive ``(start, end)``.

        Args:
            pages (Optional[str]): Range string or None for whole document.
            total_pages (int): Total page count of the PDF.

        Returns:
            tuple[int, int]: ``(start, end)``, both 1-indexed and clamped
                to ``[1, total_pages]``.

        Raises:
            ValueError: when the range syntax is invalid or empty after clamp.
        """
        if pages is None or not pages.strip():
            return 1, total_pages

        match = _RANGE_RE.match(pages)
        if not match:
            raise ValueError(f"invalid pages range {pages!r}; expected '<n>' or '<n>-<m>'")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if start < 1 or end < 1:
            raise ValueError(f"pages must be 1-indexed, got {pages!r}")
        if start > end:
            raise ValueError(f"start > end in pages range {pages!r}")

        clamped_start = min(start, total_pages)
        clamped_end = min(end, total_pages)
        if clamped_start > total_pages:
            raise ValueError(f"start {start} > total pages {total_pages}")
        return clamped_start, clamped_end


@tool(name_or_callable="read_pdf", args_schema=ReadPdfSchemaDAO)
async def read_pdf_tool(
    path: str,
    pages: Optional[str] = None,
    password: Optional[str] = None,
) -> str:
    """Extract text from a PDF file. Returns the extracted text with a header noting the page range. Pages can be a single number ('3') or a range ('5-10'); omit to read the whole document. Output is head-truncated to 2000 lines or 64KB. For encrypted PDFs, pass the password.

    Args:
        path (str): Path to the PDF file (relative or absolute).
        pages (Optional[str]): 1-indexed inclusive page range, e.g. ``'1-5'``,
            ``'3'``, or ``'10-20'``. Omit for the whole document.
        password (Optional[str]): Password for encrypted PDFs.

    Returns:
        str: Extracted text, or an error message.
    """
    log_info(msg=f"Using ReadPdf Tool with path: {path} pages={pages!r}")
    return await ReadPdfTool.invoke(path=path, pages=pages, password=password)


if __name__ == "__main__":
    # Quick test harness: synthesises a tiny PDF on the fly so the demo
    # is self-contained.
    import asyncio
    import tempfile

    async def main() -> None:
        try:
            from pypdf import PdfWriter
        except ImportError:
            print("pypdf not installed; skipping demo")
            return

        # Build a 3-page PDF with one line of text per page using pypdf's
        # blank-page helper. (pypdf can't easily author text-heavy PDFs,
        # but the resulting file IS a valid PDF that ``extract_text`` will
        # return empty strings for — which is enough to exercise the
        # plumbing without a heavier dependency.)
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=612, height=792)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            writer.write(fh)
            pdf_path = fh.name

        # Scenario 1 — read all pages.
        print(f"---[ scenario 1: read all pages of {pdf_path} ]---")
        print(await ReadPdfTool.invoke(path=pdf_path))

        # Scenario 2 — read a single page.
        print("\n---[ scenario 2: pages='2' ]---")
        print(await ReadPdfTool.invoke(path=pdf_path, pages="2"))

        # Scenario 3 — read a range.
        print("\n---[ scenario 3: pages='1-2' ]---")
        print(await ReadPdfTool.invoke(path=pdf_path, pages="1-2"))

        # Scenario 4 — invalid range surfaces a clean error.
        print("\n---[ scenario 4: invalid range 'xx' ]---")
        print(await ReadPdfTool.invoke(path=pdf_path, pages="xx"))

        # Scenario 5 — missing file.
        print("\n---[ scenario 5: missing file ]---")
        print(await ReadPdfTool.invoke(path="/tmp/slo-not-a-pdf-xyz.pdf"))

    asyncio.run(main())
