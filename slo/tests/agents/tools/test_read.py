"""Tests for the ``read`` tool (sub-spec 01.d §5.1)."""

from pathlib import Path

import pytest
from PIL import Image

from src.agents.slo_agent.tool_execution.dao import ToolResultDAO
from src.agents.tools._truncate import DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES
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
    assert result.endswith("[Showing lines 1-2000 of 2100. Use offset=2001 to continue.]")


@pytest.mark.asyncio
async def test_read_offset_limit_slices(tmp_path: Path) -> None:
    target = tmp_path / "lines.txt"
    target.write_text("a\nb\nc\nd\ne\n")
    result = await read_tool.ainvoke({"path": str(target), "offset": 2, "limit": 2})
    assert result == "b\nc\n\n\n[2 more lines. Use offset=4 to continue.]"


@pytest.mark.asyncio
async def test_read_png_returns_image_content(tmp_path: Path) -> None:
    target = tmp_path / "tiny.png"
    Image.new("RGB", (1, 1), color="blue").save(target, format="PNG")
    result = await read_tool.ainvoke({"path": str(target)})
    assert isinstance(result, ToolResultDAO)
    assert isinstance(result.content, list)
    assert result.content[0]["type"] == "image"
    assert result.content[0]["source"]["media_type"] == "image/png"
    assert result.image_reference is not None
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
    assert result.image_reference is not None
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


class TestReadContinuation:
    @pytest.mark.parametrize(
        argnames="content", argvalues=["", "one", "one\n", "one\ntwo\n", "one\r\ntwo\r\n", "one\rtwo"]
    )
    async def test_read_preserves_content_when_complete(self, tmp_path: Path, content: str) -> None:
        """Complete reads return the original content without a continuation footer."""
        target: Path = tmp_path / "complete.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data=content, encoding="utf-8")

        assert await read_tool.ainvoke({"path": str(target)}) == content

    @pytest.mark.parametrize(argnames="offset", argvalues=[1, 7])
    async def test_read_reconstructs_content_when_line_budget_is_reached(
        self, tmp_path: Path, offset: int
    ) -> None:
        """Following the advertised offset consumes each remaining line exactly once."""
        lines: list[str] = [f"line {index}\n" for index in range(4100)]
        target: Path = tmp_path / "chunks.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="".join(lines), encoding="utf-8")
        chunks: list[str] = []
        next_offset: int = offset

        for _ in range(3):
            result: str = await read_tool.ainvoke({"path": str(target), "offset": next_offset})
            end: int = min(next_offset + DEFAULT_MAX_LINES - 1, len(lines))
            body: str = "".join(lines[next_offset - 1 : end])
            if end < len(lines):
                footer: str = (
                    f"\n\n[Showing lines {next_offset}-{end} of 4100. Use offset={end + 1} to continue.]"
                )
                assert result == body + footer
                chunks.append(result.removesuffix(footer))
                next_offset = int(result.split("Use offset=")[1].split()[0])
            else:
                assert result == body
                chunks.append(result)

        assert "".join(chunks) == "".join(lines[offset - 1 :])

    async def test_read_reports_absolute_range_when_utf8_bytes_limit_output(self, tmp_path: Path) -> None:
        """Byte truncation counts UTF-8 bytes and never emits a partial line."""
        line: str = "é" * 1000 + "\n"
        lines: list[str] = [line] * 50
        target: Path = tmp_path / "utf8.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="".join(lines), encoding="utf-8")
        kept: int = DEFAULT_MAX_BYTES // len(line.encode("utf-8"))

        result: str = await read_tool.ainvoke({"path": str(target), "offset": 3})

        assert result == line * kept + (
            f"\n\n[Showing lines 3-{2 + kept} of 50. Use offset={3 + kept} to continue.]"
        )
        assert await read_tool.ainvoke({"path": str(target), "offset": 3 + kept}) == line * (48 - kept)

    async def test_read_has_no_continuation_when_limit_reaches_eof(self, tmp_path: Path) -> None:
        """A caller limit at EOF does not advertise nonexistent remaining lines."""
        target: Path = tmp_path / "eof.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="a\nb\nc\n", encoding="utf-8")

        assert await read_tool.ainvoke({"path": str(target), "offset": 2, "limit": 2}) == "b\nc\n"

    async def test_read_explains_no_progress_when_next_line_exceeds_byte_budget(self, tmp_path: Path) -> None:
        """An ordinary chunk can lead to an oversized line without silently skipping it."""
        target: Path = tmp_path / "unsafe'$(not-a-command).txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="first\n" + "é" * DEFAULT_MAX_BYTES + "\nlast\n", encoding="utf-8")

        first: str = await read_tool.ainvoke({"path": str(target)})
        assert first == "first\n\n\n[Showing lines 1-1 of 3. Use offset=2 to continue.]"
        oversized: str = await read_tool.ainvoke({"path": str(target), "offset": 2})

        assert oversized == (
            "[Line 2 exceeds the 65536-byte read limit. No lines were read. "
            "Use bash to inspect at most 65536 bytes of that line, or create a copy "
            "with shorter lines and read the copy.]"
        )
        assert "Use offset=" not in oversized
        assert str(target) not in oversized
        assert len(oversized) < 300

    @pytest.mark.parametrize(argnames="ending", argvalues=["\r\n", "\r"])
    async def test_read_preserves_terminators_when_continuing_a_limited_read(
        self, tmp_path: Path, ending: str
    ) -> None:
        """Caller-limited chunks retain the exact original terminators and last line."""
        target: Path = tmp_path / "terminators.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_bytes((f"one{ending}two{ending}three").encode("utf-8"))

        first: str = await read_tool.ainvoke({"path": str(target), "limit": 2})
        assert first == f"one{ending}two{ending}\n\n[1 more lines. Use offset=3 to continue.]"
        assert await read_tool.ainvoke({"path": str(target), "offset": 3}) == "three"

    @pytest.mark.parametrize(
        argnames="offset,limit,expected",
        argvalues=[
            (1, 0, "[3 more lines. No lines were read. Use offset=1 and change or omit limit to continue.]"),
            (2, -1, "[2 more lines. No lines were read. Use offset=2 and change or omit limit to continue.]"),
            (1, -1, "a\nb\n\n\n[1 more lines. Use offset=3 to continue.]"),
            (0, 1, "a\n\n\n[2 more lines. Use offset=2 to continue.]"),
            (-3, 1, "a\n\n\n[2 more lines. Use offset=2 to continue.]"),
            (3, 2, "c\n"),
            (4, 0, ""),
            (5, -1, ""),
        ],
    )
    async def test_read_retains_slice_semantics_when_inputs_reach_boundaries(
        self, tmp_path: Path, offset: int, limit: int, expected: str
    ) -> None:
        """Existing Python slicing remains intact, with truthful no-progress guidance."""
        target: Path = tmp_path / "boundaries.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="a\nb\nc\n", encoding="utf-8")

        assert await read_tool.ainvoke({"path": str(target), "offset": offset, "limit": limit}) == expected

    async def test_read_counts_literal_crlf_bytes_when_exactly_at_budget(self, tmp_path: Path) -> None:
        """An exactly fitting UTF-8 line includes its CRLF in the byte budget."""
        line: str = "é" * ((DEFAULT_MAX_BYTES - 2) // 2) + "\r\n"
        target: Path = tmp_path / "exact.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_bytes((line + "tail").encode("utf-8"))

        assert await read_tool.ainvoke({"path": str(target), "limit": 1}) == (
            line + "\n\n[1 more lines. Use offset=2 to continue.]"
        )
        assert await read_tool.ainvoke({"path": str(target)}) == (
            line + "\n\n[Showing lines 1-1 of 2. Use offset=2 to continue.]"
        )
        assert await read_tool.ainvoke({"path": str(target), "offset": 2}) == "tail"

    @pytest.mark.parametrize(argnames="total", argvalues=[DEFAULT_MAX_LINES, DEFAULT_MAX_LINES + 1])
    async def test_read_applies_line_budget_when_at_boundary(self, tmp_path: Path, total: int) -> None:
        """Only a file exceeding the line budget receives a truncation footer."""
        target: Path = tmp_path / "line-budget.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="a\n" * total, encoding="utf-8")
        expected: str = "a\n" * DEFAULT_MAX_LINES
        if total > DEFAULT_MAX_LINES:
            expected += "\n\n[Showing lines 1-2000 of 2001. Use offset=2001 to continue.]"

        assert await read_tool.ainvoke({"path": str(target)}) == expected

    async def test_read_uses_full_file_total_when_caller_selection_is_truncated(self, tmp_path: Path) -> None:
        """The caller limit never replaces the file-wide count in continuation guidance."""
        target: Path = tmp_path / "selection.txt"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_text(data="a\n" * 3000, encoding="utf-8")

        assert await read_tool.ainvoke({"path": str(target), "offset": 10, "limit": 2005}) == (
            "a\n" * DEFAULT_MAX_LINES + "\n\n[Showing lines 10-2009 of 3000. Use offset=2010 to continue.]"
        )
