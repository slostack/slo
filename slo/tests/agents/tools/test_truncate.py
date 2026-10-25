"""Tests for ``src.agents.tools._truncate`` (sub-spec 01.c §5.1)."""

import pytest

from src.agents.tools._truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    GREP_MAX_LINE_LENGTH,
    TruncationResult,
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
    assert "line000" in result.text  # earliest line survives
    assert "line019" not in result.text  # latest line was dropped


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


class TestTruncationMetadata:
    @pytest.mark.parametrize(argnames="text,count", argvalues=[("", 0), ("é\r\nx", 2)])
    def test_retains_counts_and_text_when_within_budgets(self, text: str, count: int) -> None:
        """Both shared directions preserve literal complete content and its counts."""
        for truncate in (Truncator.head, Truncator.tail):
            result: TruncationResult = truncate(text=text)
            assert result.text == text
            assert result.kept_lines == result.original_lines == count
            assert result.original_bytes == len(text.encode("utf-8"))
            assert result.truncated is False

    @pytest.mark.parametrize(
        argnames="max_bytes,kept,head_text,tail_text",
        argvalues=[
            (6, 2, "é\nx\n", "é\nx\n"),
            (5, 2, "é\nx\n", "é\nx\n"),
            (
                4,
                1,
                "é\n\n\n[output truncated — kept first 1 of 2 lines, 3B of 5B]",
                "[output truncated — kept last 1 of 2 lines, 2B of 5B]\nx\n",
            ),
            (
                1,
                0,
                "\n\n[output truncated — kept first 0 of 2 lines, 0B of 5B]",
                "[output truncated — kept last 0 of 2 lines, 0B of 5B]\n",
            ),
        ],
    )
    def test_counts_complete_lines_when_utf8_byte_budget_is_reached(
        self, max_bytes: int, kept: int, head_text: str, tail_text: str
    ) -> None:
        """Metadata excludes generic footers and existing shared output remains exact."""
        head: TruncationResult = Truncator.head(text="é\nx\n", max_bytes=max_bytes)
        tail: TruncationResult = Truncator.tail(text="é\nx\n", max_bytes=max_bytes)
        assert head.kept_lines == tail.kept_lines == kept
        assert head.text == head_text
        assert tail.text == tail_text
        assert head.truncated == tail.truncated == (max_bytes < 5)
        assert head.original_lines == tail.original_lines == 2
        assert head.original_bytes == tail.original_bytes == 5

    @pytest.mark.parametrize(argnames="max_lines,kept", argvalues=[(0, 0), (1, 1), (2, 2), (3, 2)])
    def test_counts_lines_when_line_budget_is_reached(self, max_lines: int, kept: int) -> None:
        """Both directions report the actual complete-line selection at each edge."""
        for truncate in (Truncator.head, Truncator.tail):
            result: TruncationResult = truncate(text="a\nb", max_lines=max_lines)
            assert result.kept_lines == kept
            assert result.truncated == (max_lines < 2)

    def test_constructs_result_when_only_legacy_fields_are_supplied(self) -> None:
        """The added metadata does not require changes to existing result constructors."""
        result = TruncationResult(text="a", truncated=False, original_lines=1, original_bytes=1)
        assert result.text == "a"
        assert result.kept_lines == 0
