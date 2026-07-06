"""Tests for the ``read_pdf`` tool (sub-spec 01.e PDF extension)."""
from pathlib import Path

import pytest
from pypdf import PdfWriter

from src.agents.tools.read_pdf import ReadPdfTool, read_pdf_tool


def _build_pdf(target: Path, num_pages: int = 3) -> Path:
    """Build a syntactically-valid PDF with N blank pages.

    Note: ``pypdf`` cannot author text content easily, so the pages
    extract to empty strings. That's fine — the plumbing (page range
    selection, header formatting, error paths) is exercised regardless.
    """
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    with target.open("wb") as fh:
        writer.write(fh)
    return target


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    return _build_pdf(target=tmp_path / "sample.pdf", num_pages=3)


@pytest.mark.asyncio
async def test_read_pdf_whole_document(pdf_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path)})
    assert "3 pages total" in result
    assert "extracted pages 1-3" in result
    assert "--- page 1 ---" in result
    assert "--- page 3 ---" in result


@pytest.mark.asyncio
async def test_read_pdf_single_page(pdf_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path), "pages": "2"})
    assert "extracted pages 2-2" in result
    assert "--- page 2 ---" in result
    assert "--- page 1 ---" not in result


@pytest.mark.asyncio
async def test_read_pdf_page_range(pdf_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path), "pages": "1-2"})
    assert "extracted pages 1-2" in result
    assert "--- page 1 ---" in result
    assert "--- page 2 ---" in result
    assert "--- page 3 ---" not in result


@pytest.mark.asyncio
async def test_read_pdf_invalid_range(pdf_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path), "pages": "xx"})
    assert result.startswith("Error: invalid pages range")


@pytest.mark.asyncio
async def test_read_pdf_reversed_range(pdf_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path), "pages": "5-2"})
    assert "start > end" in result


@pytest.mark.asyncio
async def test_read_pdf_missing_file(tmp_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(tmp_path / "missing.pdf")})
    assert result.startswith("Error: file not found")


@pytest.mark.asyncio
async def test_read_pdf_directory_returns_error(tmp_path: Path) -> None:
    result = await read_pdf_tool.ainvoke({"path": str(tmp_path)})
    assert "directory" in result


@pytest.mark.asyncio
async def test_read_pdf_clamps_end_to_total_pages(pdf_path: Path) -> None:
    """Asking for pages '1-99' on a 3-page PDF should clamp to 3."""
    result = await read_pdf_tool.ainvoke({"path": str(pdf_path), "pages": "1-99"})
    assert "extracted pages 1-3" in result


@pytest.mark.asyncio
async def test_read_pdf_invalid_pdf_returns_error(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-pdf.pdf"
    bogus.write_text("this is not a PDF")
    result = await read_pdf_tool.ainvoke({"path": str(bogus)})
    assert result.startswith("Error:")


def test_read_pdf_tool_metadata() -> None:
    assert read_pdf_tool.name == "read_pdf"
    assert "Extract text from a PDF file" in read_pdf_tool.description


def test_parse_range_whole_document() -> None:
    assert ReadPdfTool._parse_range(pages=None, total_pages=10) == (1, 10)
    assert ReadPdfTool._parse_range(pages="", total_pages=10) == (1, 10)


def test_parse_range_single_page() -> None:
    assert ReadPdfTool._parse_range(pages="3", total_pages=10) == (3, 3)


def test_parse_range_inclusive() -> None:
    assert ReadPdfTool._parse_range(pages="2-5", total_pages=10) == (2, 5)


def test_parse_range_clamps_to_total() -> None:
    assert ReadPdfTool._parse_range(pages="5-50", total_pages=10) == (5, 10)
