"""Tests for ``src.agents.tools._truncate`` (sub-spec 01.c §5.1)."""
from src.agents.tools._truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    GREP_MAX_LINE_LENGTH,
    Truncator,
)


def test_format_size_branches() -> None:
    assert Truncator.format_size(num_bytes=0) == "0B"
    assert Truncator.format_size(num_bytes=1023) == "1023B"
    assert Truncator.format_size(num_bytes=1024) == "1.0KB"
    assert Truncator.format_size(num_bytes=1024 * 1024) == "1.0MB"


def test_truncate_head_no_op_under_limits() -> None:
    text = "a\nb\nc\n"
    result = Truncator.head(text=text, max_lines=10, max_bytes=1000)
    assert result.truncated is False
    assert result.text == text


def test_truncate_head_drops_tail_lines() -> None:
    text = "".join(f"line{i}\n" for i in range(5))
    result = Truncator.head(text=text, max_lines=3, max_bytes=1000)
    assert result.truncated is True
    assert "line0" in result.text
    assert "line2" in result.text
    assert "line3" not in result.text
    assert "[output truncated" in result.text


def test_truncate_head_drops_at_byte_limit() -> None:
    """When max_bytes is the tighter constraint, bytes wins."""
    # 20 lines of 9 bytes each = 180 bytes total. max_bytes=50 keeps ~5 lines.
    text = "".join(f"line{i:03d}\n" for i in range(20))
    result = Truncator.head(text=text, max_lines=100, max_bytes=50)
    assert result.truncated is True
    assert "line000" in result.text       # earliest line survives
    assert "line019" not in result.text   # latest line was dropped


def test_truncate_tail_keeps_last_lines() -> None:
    text = "".join(f"line{i}\n" for i in range(5))
    result = Truncator.tail(text=text, max_lines=2, max_bytes=1000)
    assert result.truncated is True
    assert "line4" in result.text
    assert "line3" in result.text
    assert "line0" not in result.text
    assert result.text.startswith("[output truncated")


def test_truncate_line_short_passthrough() -> None:
    assert Truncator.line(line="hello") == "hello"


def test_truncate_line_long_appends_ellipsis() -> None:
    long = "x" * (GREP_MAX_LINE_LENGTH + 10)
    truncated = Truncator.line(line=long)
    assert truncated.endswith("…")
    assert len(truncated) == GREP_MAX_LINE_LENGTH + 1


def test_default_constants_match_pi() -> None:
    """Documentation constants must match pi to keep descriptions accurate."""
    assert DEFAULT_MAX_LINES == 2000
    assert DEFAULT_MAX_BYTES == 65536
    assert GREP_MAX_LINE_LENGTH == 500
