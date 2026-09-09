"""Raw-text segmentation of assistant answers into text and mermaid parts.

This module is the ONLY component that understands mermaid fence syntax.
It runs on the raw (unescaped) answer text: ``AssistantAnswerBody`` escapes
``<``/``>`` for markdown safety, which corrupts mermaid edge syntax
(``-->`` becomes ``--\\>``), so segmentation must happen first and only
``text`` parts may be escaped downstream.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = ["AnswerSegmentDAO", "MermaidFenceSegmenter"]

_MERMAID_FENCE_OPENER: str = "```mermaid"
"""Info string that opens a mermaid fence — exact first-token match required."""

_FENCE_CLOSER: str = "```"
"""Line that closes a mermaid fence."""

_FENCE_MARKER_CHARACTER: str = "`"
"""The character a fence marker run is made of."""

_MINIMUM_FENCE_MARKER_LENGTH: int = 3
"""Shortest backtick run that opens a markdown fence."""

_NO_FENCE: str = ""
"""Sentinel for "no fence is open" — no real opener line or marker is empty."""


class AnswerSegmentDAO(BaseModel):
    """One ordered part of a segmented assistant answer.

    Attributes:
        kind (Literal["text", "mermaid"]): ``text`` parts render as markdown
            (after escaping); ``mermaid`` parts render as a
            ``MermaidChartBlock`` and must be used verbatim (never escaped).
        content (str): The part's raw content. For ``mermaid`` parts this is
            the fence body without the fence lines themselves.
    """

    kind: Literal["text", "mermaid"]
    content: str


def _is_mermaid_fence_opener(*, line: str) -> bool:
    """Return whether one fence-info line declares exactly ``mermaid``.

    WHAT: Decides opener recognition, and nothing else.
    WHO: ``_FenceWalk._consume_at_top_level`` calls it for every raw line
    walked outside any fence.
    WHEN: Once per top-level line of the answer.

    Args:
        line (str): Raw fence opener line, including optional indentation.

    Returns:
        bool: True only when the first non-whitespace token is exactly
            `````mermaid``; False for blank lines and non-mermaid fences.
    """
    tokens: list[str] = line.strip().split(maxsplit=1)
    return bool(tokens) and tokens[0] == _MERMAID_FENCE_OPENER


def _fence_marker(*, stripped: str) -> str:
    """Return the backtick run that opens a non-mermaid fence, if any.

    WHAT: Decides whether one line opens some other fenced block, and
    nothing else.
    WHO: ``_FenceWalk._consume_at_top_level`` calls it for every top-level
    line that is not a mermaid opener.
    WHEN: Once per such line.

    Args:
        stripped (str): One source line with surrounding whitespace removed.

    Returns:
        str: The leading backtick run when it is long enough to open a
            markdown fence, else ``_NO_FENCE`` (the empty string).
    """
    marker: str = stripped[: len(stripped) - len(stripped.lstrip(_FENCE_MARKER_CHARACTER))]
    if len(marker) < _MINIMUM_FENCE_MARKER_LENGTH:
        return _NO_FENCE
    return marker


def _closes_enclosing_fence(*, stripped: str, marker: str) -> bool:
    """Return whether one line closes the enclosing non-mermaid fence.

    A closer carries no info string and is at least as long as the marker
    that opened the fence, per CommonMark.

    WHAT: Decides fence closure, and nothing else.
    WHO: ``_FenceWalk._consume_inside_other_fence`` calls it for every line
    walked inside another fence.
    WHEN: Once per line between a non-mermaid opener and its closer.

    Args:
        stripped (str): One source line with surrounding whitespace removed.
        marker (str): The backtick run that opened the enclosing fence.

    Returns:
        bool: True when this line closes that fence.
    """
    return stripped != "" and stripped.strip(_FENCE_MARKER_CHARACTER) == "" and len(stripped) >= len(marker)


class _FenceWalk:
    """The state of one segmentation pass over one raw answer.

    WHAT: Tracks which of three reading states the walk is in — top level,
    inside a mermaid fence, inside some other fence — and accumulates the
    ordered segments. One line in, at most one state change out.
    WHO: ``MermaidFenceSegmenter.segment`` builds one per call and discards
    it; nothing else constructs or holds one.
    WHEN: For the lifetime of a single ``segment`` call.

    Each open-fence state is carried by the text that opened it, so
    ``_NO_FENCE`` (the empty string) means "not inside that fence" without a
    second flag: a real mermaid opener always contains `````mermaid``, and a
    real enclosing marker is at least three backticks.
    """

    def __init__(self) -> None:
        """Start an empty walk at the top level."""
        self._segments: list[AnswerSegmentDAO] = []
        self._pending_text_lines: list[str] = []
        self._mermaid_opener_line: str = _NO_FENCE
        self._mermaid_lines: list[str] = []
        self._enclosing_marker: str = _NO_FENCE

    def consume(self, *, line: str) -> None:
        """Read one raw answer line in the walk's current state.

        WHAT: Dispatches on which reading state the walk is in — the single
        decision this method makes.
        WHO: ``MermaidFenceSegmenter.segment`` calls it once per line.
        WHEN: Once for every line of the answer, in stream order.

        Args:
            line (str): One raw source line, line ending included.
        """
        if self._mermaid_opener_line != _NO_FENCE:
            self._consume_inside_mermaid_fence(line=line)
            return
        if self._enclosing_marker != _NO_FENCE:
            self._consume_inside_other_fence(line=line)
            return
        self._consume_at_top_level(line=line)

    def finish(self) -> list[AnswerSegmentDAO]:
        """Close the walk and return the segments it accumulated.

        WHAT: Restores any still-open mermaid fence as inline text, flushes
        the trailing text run, and hands back the ordered parts.
        WHO: ``MermaidFenceSegmenter.segment`` calls it once, after the last
        line has been consumed.
        WHEN: At the end of a single segmentation pass.

        Returns:
            list[AnswerSegmentDAO]: The accumulated parts, in stream order.
        """
        self._restore_unterminated_fence()
        self._flush_text()
        return self._segments

    def _consume_inside_mermaid_fence(self, *, line: str) -> None:
        """Collect one fence-body line, or close the fence on its closer.

        WHAT: Decides whether this line ends the mermaid fence, and nothing
        else.
        WHO: ``consume`` calls it while a mermaid fence is open.
        WHEN: For every line between a mermaid opener and its closer.

        Args:
            line (str): One raw source line, line ending included.
        """
        if line.strip() != _FENCE_CLOSER:
            self._mermaid_lines.append(line)
            return
        self._close_mermaid_fence(closer_line=line)

    def _consume_inside_other_fence(self, *, line: str) -> None:
        """Carry one line of an enclosing non-mermaid fence through as text.

        WHAT: Decides whether this line closes the enclosing fence, and
        nothing else. The line itself is always kept verbatim, which is what
        keeps a mermaid fence nested inside a longer fence unsegmented.
        WHO: ``consume`` calls it while some other fence is open.
        WHEN: For every line between a non-mermaid opener and its closer.

        Args:
            line (str): One raw source line, line ending included.
        """
        self._pending_text_lines.append(line)
        if not _closes_enclosing_fence(stripped=line.strip(), marker=self._enclosing_marker):
            return
        self._enclosing_marker = _NO_FENCE

    def _consume_at_top_level(self, *, line: str) -> None:
        """Open a mermaid fence, or keep the line as pending text.

        WHAT: Decides whether this line opens a mermaid fence, and nothing
        else; whether it opens some OTHER fence is decided by
        ``_fence_marker``, so the walk knows to pass that block through.
        WHO: ``consume`` calls it while no fence is open.
        WHEN: For every line read at the top level.

        Args:
            line (str): One raw source line, line ending included.
        """
        if _is_mermaid_fence_opener(line=line):
            self._open_mermaid_fence(opener_line=line)
            return
        self._enclosing_marker = _fence_marker(stripped=line.strip())
        self._pending_text_lines.append(line)

    def _open_mermaid_fence(self, *, opener_line: str) -> None:
        """Enter the mermaid-fence state, remembering the exact opener.

        WHAT: Stores the opener verbatim so an empty or unterminated fence
        can be put back byte for byte.
        WHO: ``_consume_at_top_level`` calls it on a recognized opener.
        WHEN: Once per mermaid fence met at the top level.

        Args:
            opener_line (str): The exact source opener line.
        """
        self._mermaid_opener_line = opener_line
        self._mermaid_lines = []

    def _close_mermaid_fence(self, *, closer_line: str) -> None:
        """Emit the closed fence as a mermaid segment, or degrade it to text.

        WHAT: Decides whether the fence body is worth a chart card, and
        nothing else. An empty or whitespace-only body degrades to inline
        text, so nothing is normalized or lost from the answer stream.
        WHO: ``_consume_inside_mermaid_fence`` calls it on the closer line.
        WHEN: Once per closed mermaid fence.

        Args:
            closer_line (str): The exact source closer line.
        """
        source: str = "".join(self._mermaid_lines)
        if not source.strip():
            self._degrade_fence_to_text(closer_line=closer_line)
            return
        self._flush_text()
        self._segments.append(AnswerSegmentDAO(kind="mermaid", content=source))
        self._leave_mermaid_fence()

    def _degrade_fence_to_text(self, *, closer_line: str) -> None:
        """Re-attach an empty fence's own lines to the pending text run.

        WHAT: Puts the exact opener, body, and closer lines back, so the
        answer stream reads byte for byte as it arrived.
        WHO: ``_close_mermaid_fence`` calls it for a body with no content.
        WHEN: Once per empty or whitespace-only mermaid fence.

        Args:
            closer_line (str): The exact source closer line.
        """
        self._pending_text_lines.append(self._mermaid_opener_line)
        self._pending_text_lines.extend(self._mermaid_lines)
        self._pending_text_lines.append(closer_line)
        self._leave_mermaid_fence()

    def _restore_unterminated_fence(self) -> None:
        """Put a fence the answer never closed back into the text run.

        WHAT: Restores the exact opener line plus the collected body, so an
        answer still streaming its fence keeps rendering as ordinary
        markdown until the closer arrives.
        WHO: ``finish`` calls it before the final text flush.
        WHEN: At the end of a walk that ended inside a mermaid fence.
        """
        if self._mermaid_opener_line == _NO_FENCE:
            return
        self._pending_text_lines.append(self._mermaid_opener_line)
        self._pending_text_lines.extend(self._mermaid_lines)
        self._leave_mermaid_fence()

    def _leave_mermaid_fence(self) -> None:
        """Return the walk to the top level, dropping the fence's state.

        WHO: ``_close_mermaid_fence``, ``_degrade_fence_to_text``, and
        ``_restore_unterminated_fence`` call it once they have consumed the
        collected lines.
        WHEN: Whenever a mermaid fence stops being open.
        """
        self._mermaid_opener_line = _NO_FENCE
        self._mermaid_lines = []

    def _flush_text(self) -> None:
        """Turn the accumulated text lines into one text segment.

        WHAT: Emits nothing when no text is pending, so no empty segment is
        ever produced.
        WHO: ``_close_mermaid_fence`` calls it just before a mermaid segment
        is emitted; ``finish`` calls it once at the end of the walk.
        WHEN: At every boundary between a text run and a mermaid segment.
        """
        if not self._pending_text_lines:
            return
        self._segments.append(AnswerSegmentDAO(kind="text", content="".join(self._pending_text_lines)))
        self._pending_text_lines.clear()


class MermaidFenceSegmenter:
    """Split raw answer text into ordered text/mermaid segments.

    WHAT: A pure, stateless gateway over one ``_FenceWalk`` line walk.
    Closed mermaid fences with a non-empty body become ``mermaid`` segments;
    unterminated fences, empty fences, and mermaid fences nested inside a
    longer outer fence all stay inline as ordinary text (the status-quo
    rendering path).
    WHO: ``AssistantAnswerBody.show_answer`` is the only caller.
    WHEN: At every answer render boundary (already coalesced to ~30 fps by
    ``AssistantStreamBlock``'s flush timer).
    """

    @classmethod
    def segment(cls, *, text: str) -> list[AnswerSegmentDAO]:
        """Split raw answer text into ordered segments.

        WHAT: Walks the raw answer line by line and cuts it into parts, so
        prose keeps rendering as markdown while each well-formed mermaid
        fence body is handed on verbatim.
        WHO: ``AssistantAnswerBody.show_answer`` is the only caller.
        WHEN: At every answer render boundary (coalesced to ~30 fps).

        Args:
            text (str): Raw, unescaped assistant answer text.

        Returns:
            list[AnswerSegmentDAO]: Ordered parts. Always non-empty when
                ``text`` is non-empty; adjacent text runs separated by a
                mermaid fence arrive as distinct parts.
        """
        if _MERMAID_FENCE_OPENER not in text:
            return [AnswerSegmentDAO(kind="text", content=text)]
        walk: _FenceWalk = _FenceWalk()
        for line in text.splitlines(keepends=True):
            walk.consume(line=line)
        return walk.finish()
