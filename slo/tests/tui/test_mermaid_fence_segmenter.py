"""Unit tests for raw-answer segmentation into text and mermaid parts."""

from __future__ import annotations

from src.tui.mermaid_fence_segmenter import AnswerSegmentDAO, MermaidFenceSegmenter


class TestMermaidFenceSegmenterHappyPaths:
    """Fast path and well-formed closed mermaid fences."""

    def test_no_mermaid_returns_single_text_part(self) -> None:
        """An answer without a mermaid opener stays one untouched text part."""
        answer: str = "Just prose.\n\nAnd a second paragraph.\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]

    def test_single_closed_fence_yields_text_mermaid_text(self) -> None:
        """Prose around a closed fence becomes ordered text/mermaid/text parts."""
        answer: str = "Before.\n```mermaid\ngraph TD\n  A --> B\n```\nAfter.\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert [segment.kind for segment in segments] == ["text", "mermaid", "text"]
        assert segments[0].content == "Before.\n"
        assert segments[1].content == "graph TD\n  A --> B\n"
        assert segments[2].content == "After.\n"


class TestMermaidFenceSegmenterDegradedFences:
    """Fences that must never become a chart."""

    def test_empty_fence_body_stays_inline_text(self) -> None:
        """A whitespace-only fence body is re-attached to the text part."""
        answer: str = "Before.\n```mermaid\n   \n```\nAfter.\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]

    def test_unterminated_fence_stays_inline_text(self) -> None:
        """An opener with no closer keeps its original bytes inside the text part."""
        answer: str = "Before.\n```mermaid\ngraph TD\n  A --> B\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]


class TestMermaidFenceSegmenterNesting:
    """Mermaid fences shown inside another fenced block stay inert."""

    def test_mermaid_fence_inside_a_longer_outer_fence_is_not_segmented(self) -> None:
        """A mermaid example inside a longer outer fence survives byte-identically."""
        answer: str = (
            "Here is how to write a diagram:\n"
            "\n"
            "`````markdown\n"
            "```mermaid\n"
            "graph TD\n"
            "  A --> B\n"
            "```\n"
            "That was the example.\n"
            "`````\n"
            "\n"
            "Done.\n"
        )

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]

    def test_mermaid_fence_after_a_closed_non_mermaid_fence_is_segmented(self) -> None:
        """The enclosing-fence state clears at its closer, so a later fence still segments."""
        answer: str = (
            "```python\n" "print('hello')\n" "```\n" "```mermaid\n" "graph TD\n" "  A --> B\n" "```\n"
        )

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert [segment.kind for segment in segments] == ["text", "mermaid"]
        assert segments[0].content == "```python\nprint('hello')\n```\n"
        assert segments[1].content == "graph TD\n  A --> B\n"


class TestMermaidFenceSegmenterOpenerRecognition:
    """Exactly which info lines open a mermaid fence."""

    def test_opener_with_trailing_whitespace_is_recognized(self) -> None:
        """Trailing whitespace after the info string still opens a fence."""
        answer: str = "```mermaid   \ngraph TD\n  A --> B\n```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="mermaid", content="graph TD\n  A --> B\n")]

    def test_indented_opener_is_recognized(self) -> None:
        """Leading whitespace before the marker still opens a fence."""
        answer: str = "  ```mermaid\n  graph TD\n  ```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="mermaid", content="  graph TD\n")]

    def test_mermaid_prefixed_non_mermaid_fence_is_not_segmented(self) -> None:
        """A language identifier that merely starts with ``mermaid`` is not mermaid."""
        answer: str = "```mermaidExtra\ngraph TD\n  A --> B\n```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]

    def test_closed_mermaid_fence_after_blank_text_lines_is_segmented(self) -> None:
        """Blank lines before a fence never raise and stay in the preceding text part."""
        answer: str = "Intro.\n\n   \n```mermaid\ngraph TD\n```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert [segment.kind for segment in segments] == ["text", "mermaid"]
        assert segments[0].content == "Intro.\n\n   \n"
        assert segments[1].content == "graph TD\n"


class TestMermaidFenceSegmenterOrdering:
    """Segment order and boundaries across an answer."""

    def test_fence_at_start_and_end_of_answer(self) -> None:
        """An answer that is only a fence emits no empty text parts."""
        answer: str = "```mermaid\ngraph TD\n  A --> B\n```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="mermaid", content="graph TD\n  A --> B\n")]

    def test_multiple_fences_keep_stream_order(self) -> None:
        """Two fences and their surrounding prose stay in stream order."""
        answer: str = (
            "First.\n"
            "```mermaid\n"
            "graph TD\n"
            "```\n"
            "Middle.\n"
            "```mermaid\n"
            "sequenceDiagram\n"
            "```\n"
            "Last.\n"
        )

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert [segment.kind for segment in segments] == [
            "text",
            "mermaid",
            "text",
            "mermaid",
            "text",
        ]
        assert [segment.content for segment in segments] == [
            "First.\n",
            "graph TD\n",
            "Middle.\n",
            "sequenceDiagram\n",
            "Last.\n",
        ]

    def test_non_mermaid_fence_is_not_segmented(self) -> None:
        """A python fence stays inside the text part."""
        answer: str = "Before.\n```python\nprint('hello')\n```\nAfter.\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]


class TestMermaidFenceSegmenterBytePreservation:
    """Degraded fences keep their exact original bytes."""

    def test_unterminated_indented_or_trailing_whitespace_fence_stays_byte_identical(self) -> None:
        """An unterminated indented opener keeps its tab and trailing spaces."""
        answer: str = "Intro.\n\t```mermaid   \ngraph TD\n  A --> B\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]
        assert "\t```mermaid   \n" in segments[0].content

    def test_empty_fence_with_crlf_markers_stays_byte_identical(self) -> None:
        """An empty fence keeps the CRLF line endings of both marker lines."""
        answer: str = "Before.\r\n```mermaid\r\n\r\n```\r\nAfter.\r\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments == [AnswerSegmentDAO(kind="text", content=answer)]
        assert "```mermaid\r\n" in segments[0].content
        assert "```\r\n" in segments[0].content


class TestMermaidFenceSegmenterContentContract:
    """What the mermaid part carries and what the whole part list preserves."""

    def test_mermaid_content_is_never_escaped(self) -> None:
        """Edge syntax and angle brackets survive verbatim in the mermaid part."""
        answer: str = "```mermaid\ngraph TD\n  A[Start] --> B[<end>]\n```\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        assert segments[0].kind == "mermaid"
        assert segments[0].content == "graph TD\n  A[Start] --> B[<end>]\n"
        assert "--\\>" not in segments[0].content

    def test_text_parts_reassemble_to_original_stream(self) -> None:
        """Joining every part reproduces the input minus only the fence marker lines."""
        answer: str = "Before.\n```mermaid\ngraph TD\n  A --> B\n```\nAfter.\n"

        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=answer)

        reassembled: str = "".join(segment.content for segment in segments)
        assert reassembled == "Before.\ngraph TD\n  A --> B\nAfter.\n"
        assert reassembled == answer.replace("```mermaid\n", "").replace("```\n", "")
