"""Tests for the ``read`` tool (sub-spec 01.d §5.1)."""

from pathlib import Path

import pytest
from PIL import Image

from src.agents.slo_agent.tool_execution.dao import ToolResultDAO
from src.agents.tools._truncate import DEFAULT_MAX_LINES
from src.agents.tools.read import ReadTool, read_tool


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
    assert isinstance(result, ToolResultDAO)
    assert isinstance(result.content, list)
    assert result.content[0]["type"] == "image"
    assert result.content[0]["source"]["media_type"] == "image/png"
    assert result.image_reference.startswith("[image attached: tiny.png,")


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

    result = await ReadTool.invoke(path=str(target))

    assert isinstance(result, str)
    assert result == f"Error: {target} appears to be a binary file and cannot be read as text."


@pytest.mark.asyncio
async def test_read_invalid_utf8_returns_decode_error(tmp_path: Path) -> None:
    target = tmp_path / "invalid.txt"
    target.write_bytes(b"\xff\xfehello")

    result = await read_tool.ainvoke({"path": str(target)})

    assert result.startswith(f"Error: cannot decode {target} as UTF-8 text:")


@pytest.mark.asyncio
async def test_read_large_image_returns_tool_result_dao(tmp_path: Path) -> None:
    """ReadTool returns live image content plus a compact durable reference."""
    target: Path = tmp_path / "large.png"
    Image.new("RGB", (3000, 2000), color="green").save(target, format="PNG")

    result = await ReadTool.invoke(path=str(target))

    assert isinstance(result, ToolResultDAO)
    assert isinstance(result.content, list)
    assert result.content[0]["type"] == "image"
    assert result.image_reference.startswith("[image attached: large.png,")


@pytest.mark.asyncio
async def test_read_text_still_returns_str(tmp_path: Path) -> None:
    """ReadTool preserves its text-only string contract."""
    target: Path = tmp_path / "notes.txt"
    target.write_text("just text")

    result = await ReadTool.invoke(path=str(target))

    assert isinstance(result, str)
    assert "just text" in result


@pytest.mark.asyncio
async def test_read_pdf_still_returns_error_str(tmp_path: Path) -> None:
    """ReadTool keeps redirecting PDF reads to read_pdf as an error string."""
    target: Path = tmp_path / "doc.pdf"
    target.write_bytes(b"%PDF-1.4 fake")

    result = await ReadTool.invoke(path=str(target))

    assert isinstance(result, str)
    assert "read_pdf" in result


def test_read_tool_metadata() -> None:
    assert read_tool.name == "read"
    assert "Read the contents of a UTF-8 text file" in read_tool.description
