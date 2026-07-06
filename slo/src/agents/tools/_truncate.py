"""Output truncation helpers shared by read, bash, grep, find, ls.

Mirrors pi's truncation behaviour at pi/packages/agent/src/harness/utils/truncate.ts
and the per-tool defaults documented in pi/packages/coding-agent/src/core/tools/.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


__all__ = [
    "DEFAULT_LIMIT_FIND",
    "DEFAULT_LIMIT_GREP",
    "DEFAULT_LIMIT_LS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_LINES",
    "GREP_MAX_LINE_LENGTH",
    "TruncationResult",
    "Truncator",
]


DEFAULT_MAX_LINES: Final[int] = 2000
DEFAULT_MAX_BYTES: Final[int] = 65536
GREP_MAX_LINE_LENGTH: Final[int] = 500
DEFAULT_LIMIT_FIND: Final[int] = 1000
DEFAULT_LIMIT_GREP: Final[int] = 100
DEFAULT_LIMIT_LS: Final[int] = 500


@dataclass(frozen=True)
class TruncationResult:
    """Outcome of a truncation step.

    Attributes:
        text: The (possibly shorter) output to surface to the model.
        truncated: True iff truncation actually happened.
        original_lines: Total line count of the input before truncation.
        original_bytes: Byte count of the UTF-8-encoded input.
    """

    text: str
    truncated: bool
    original_lines: int
    original_bytes: int


class Truncator:
    """Output-truncation primitives for read, bash, grep, find, ls.

    All methods are pure classmethods with named-only arguments. The class
    is a stateless namespace — there is no instance state, and constructing
    one is unnecessary.
    """

    @classmethod
    def format_size(cls, *, num_bytes: int) -> str:
        """Render a byte count as a short human-readable label.

        Args:
            num_bytes: Non-negative byte count.

        Returns:
            ``'<N>B'``, ``'<N.N>KB'``, or ``'<N.N>MB'`` per pi's convention.
        """
        if num_bytes < 1024:
            return f"{num_bytes}B"
        if num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f}KB"
        return f"{num_bytes / (1024 * 1024):.1f}MB"

    @classmethod
    def head(
        cls,
        *,
        text: str,
        max_lines: int = DEFAULT_MAX_LINES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> TruncationResult:
        """Keep the first ``max_lines`` lines and first ``max_bytes`` bytes; drop the tail.

        Used by ``read``: the model can continue with an ``offset`` to consume
        the dropped tail of a large file.

        Truncation rule: stop at whichever limit (lines or bytes) is hit first.

        Args:
            text: Input string to truncate.
            max_lines: Maximum number of leading lines to keep.
            max_bytes: Maximum number of UTF-8 bytes to keep.

        Returns:
            A :class:`TruncationResult` carrying the (possibly truncated) text
            plus original line/byte counts.
        """
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        total_bytes = len(text.encode("utf-8"))

        if total_lines <= max_lines and total_bytes <= max_bytes:
            return TruncationResult(
                text=text,
                truncated=False,
                original_lines=total_lines,
                original_bytes=total_bytes,
            )

        kept: list[str] = []
        kept_bytes = 0
        for index, line in enumerate(lines):
            line_bytes = len(line.encode("utf-8"))
            if index >= max_lines or kept_bytes + line_bytes > max_bytes:
                break
            kept.append(line)
            kept_bytes += line_bytes

        body = "".join(kept)
        footer = (
            f"\n\n[output truncated — kept first {len(kept)} of {total_lines} lines, "
            f"{cls.format_size(num_bytes=kept_bytes)} of {cls.format_size(num_bytes=total_bytes)}]"
        )
        return TruncationResult(
            text=body + footer,
            truncated=True,
            original_lines=total_lines,
            original_bytes=total_bytes,
        )

    @classmethod
    def tail(
        cls,
        *,
        text: str,
        max_lines: int = DEFAULT_MAX_LINES,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> TruncationResult:
        """Keep the last ``max_lines`` lines and last ``max_bytes`` bytes; drop the head.

        Used by ``bash``: the most recent output is the most useful, so we keep
        the tail and discard the head. Caller is responsible for spilling the
        full output to a temp file and appending the path to the returned text.

        Args:
            text: Input string to truncate.
            max_lines: Maximum number of trailing lines to keep.
            max_bytes: Maximum number of UTF-8 bytes to keep.

        Returns:
            A :class:`TruncationResult` carrying the (possibly truncated) text
            plus original line/byte counts.
        """
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        total_bytes = len(text.encode("utf-8"))

        if total_lines <= max_lines and total_bytes <= max_bytes:
            return TruncationResult(
                text=text,
                truncated=False,
                original_lines=total_lines,
                original_bytes=total_bytes,
            )

        kept_rev: list[str] = []
        kept_bytes = 0
        for line in reversed(lines):
            line_bytes = len(line.encode("utf-8"))
            if len(kept_rev) >= max_lines or kept_bytes + line_bytes > max_bytes:
                break
            kept_rev.append(line)
            kept_bytes += line_bytes

        body = "".join(reversed(kept_rev))
        footer_prefix = (
            f"[output truncated — kept last {len(kept_rev)} of {total_lines} lines, "
            f"{cls.format_size(num_bytes=kept_bytes)} of {cls.format_size(num_bytes=total_bytes)}]\n"
        )
        return TruncationResult(
            text=footer_prefix + body,
            truncated=True,
            original_lines=total_lines,
            original_bytes=total_bytes,
        )

    @classmethod
    def line(cls, *, line: str, max_length: int = GREP_MAX_LINE_LENGTH) -> str:
        """Truncate a single line for grep output.

        Returns the line unchanged if shorter than ``max_length``; otherwise
        keeps the first ``max_length`` characters and appends ``'…'``.

        Args:
            line: A single line of text (no trailing newline expected).
            max_length: Maximum length in characters before truncation.

        Returns:
            The line, possibly with its tail replaced by ``'…'``.
        """
        if len(line) <= max_length:
            return line
        return line[:max_length] + "…"
