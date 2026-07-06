"""Tests for the ``read`` tool (sub-spec 01.d §5.1)."""
from pathlib import Path

import pytest
from PIL import Image

from src.agents.tools._truncate import DEFAULT_MAX_LINES
from src.agents.tools.read import read_tool


@pytest.mark.asyncio
async def test_read_text_file_returns_content(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello world\n")
    result = await read_tool.ainvoke({"path": str(target)})
    assert result == "hello world\n"


@pytest.mark.asyncio
async def test_read_missing_file_returns_error(tmp_path: Path) -> None:
    result = await read_tool.ainvoke({"path": str(tmp_path / "missing.txt")})
    assert result.startswith("Error: file not found")


@pytest.mark.asyncio
async def test_read_directory_returns_error(tmp_path: Path) -> None:
    result = await read_tool.ainvoke({"path": str(tmp_path)})
    assert "directory" in result


@pytest.mark.asyncio
async def test_read_truncates_large_file(tmp_path: Path) -> None:
    target = tmp_path / "big.txt"
    target.write_text("\n".join(f"line {i}" for i in range(DEFAULT_MAX_LINES + 100)))
    result = await read_tool.ainvoke({"path": str(target)})
    assert "[output truncated" in result


@pytest.mark.asyncio
async def test_read_offset_limit_slices(tmp_path: Path) -> None:
    target = tmp_path / "lines.txt"
    target.write_text("a\nb\nc\nd\ne\n")
    result = await read_tool.ainvoke({"path": str(target), "offset": 2, "limit": 2})
    assert result == "b\nc\n"


@pytest.mark.asyncio
async def test_read_png_returns_image_content(tmp_path: Path) -> None:
    target = tmp_path / "tiny.png"
    Image.new("RGB", (1, 1), color="blue").save(target, format="PNG")
    result = await read_tool.ainvoke({"path": str(target)})
    assert isinstance(result, list)
    assert result[0]["type"] == "image"
    assert result[0]["source"]["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_read_pdf_redirects_to_read_pdf_tool(tmp_path: Path) -> None:
    target = tmp_path / "sample.pdf"
    target.write_bytes(b"%PDF-1.7\n")

    result = await read_tool.ainvoke({"path": str(target)})

    assert result == f"Error: {target} is a PDF. Use read_pdf instead."


@pytest.mark.asyncio
async def test_read_binary_file_returns_error(tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    target.write_bytes(b"abc\x00def")

    result = await read_tool.ainvoke({"path": str(target)})

    assert result == f"Error: {target} appears to be a binary file and cannot be read as text."


@pytest.mark.asyncio
async def test_read_invalid_utf8_returns_decode_error(tmp_path: Path) -> None:
    target = tmp_path / "invalid.txt"
    target.write_bytes(b"\xff\xfehello")

    result = await read_tool.ainvoke({"path": str(target)})

    assert result.startswith(f"Error: cannot decode {target} as UTF-8 text:")


def test_read_tool_metadata() -> None:
    assert read_tool.name == "read"
    assert "Read the contents of a UTF-8 text file" in read_tool.description
