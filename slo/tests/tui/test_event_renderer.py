"""Unit tests for ``EventRenderer`` (sub-spec 02.a.2 §8.2).

The renderer now emits a two-line block per tool call (``⏺`` headline,
``⎿`` continuation) and stays silent on uninformative intermediate
events. These tests cover every dispatch branch and every per-tool
summariser entry point introduced for the Claude-Code-style layout.
"""

from __future__ import annotations

from typing import List, Tuple

from src.agents.slo_agent.dao import ProgressEventDAO
from src.tui.event_renderer import EventRenderer


class FakeRichLog:
    """List-backed fake satisfying ``RichLogLike``.

    Each ``write`` call appends ``(content, classes)`` to ``writes``.
    """

    def __init__(self) -> None:
        self.writes: List[Tuple[str, str]] = []

    def write(self, content: str, classes: str = "") -> None:
        """Record a single write call.

        Args:
            content (str): The line content.
            classes (str): Semantic render class. Defaults to ``""``.
        """
        self.writes.append((content, classes))


class TestEventRendererDispatch:
    """One test per ``render`` branch — three live branches + one silent."""

    def test_tool_call_emits_read_headline_with_path_context(self) -> None:
        """A read tool call renders a Claude-Code-style path-focused headline."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="read",
            tool_input={"file_path": "foo.py", "offset": 1, "limit": 10},
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes == [
            ("⏺ read foo.py:1-10", "tool-line"),
        ]

    def test_grep_tool_call_emits_pattern_and_search_path(self) -> None:
        """A grep tool call keeps the searched pattern and path visible."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="grep",
            tool_input={"pattern": "reasoning", "path": "src/tui", "glob": "*.py"},
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes == [
            ("⏺ grep /reasoning/ in src/tui (*.py)", "tool-line"),
        ]

    def test_tool_result_emits_continuation_with_summary(self) -> None:
        """A tool-result event renders ``⎿ <summary>`` with ``tool-result``."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="read",
            tool_output="line one\nline two\nline three",
        )

        EventRenderer.render(event=event, log=log)

        assert len(log.writes) == 1
        content, classes = log.writes[0]
        assert content.startswith("⎿ ")
        assert "3 lines" in content
        assert "KB" in content
        assert classes == "tool-result"

    def test_unknown_tool_uses_default_summarizer(self) -> None:
        """An unknown tool name falls through to first-line / 120-char truncation."""
        log: FakeRichLog = FakeRichLog()
        long_first_line: str = "x" * 200
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="some_unknown_tool",
            tool_output=f"{long_first_line}\nsecond line discarded",
        )

        EventRenderer.render(event=event, log=log)

        assert len(log.writes) == 1
        content, classes = log.writes[0]
        assert classes == "tool-result"
        # Glyph + space + 120 chars + ellipsis
        assert content == f"⎿ {'x' * 120}…"

    def test_long_bash_command_is_truncated_in_the_headline(self) -> None:
        """A long bash command is truncated to 60 chars + ellipsis in the headline."""
        log: FakeRichLog = FakeRichLog()
        long_value: str = "y" * 100
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="bash",
            tool_input={"command": long_value},
        )

        EventRenderer.render(event=event, log=log)

        assert len(log.writes) == 1
        content, classes = log.writes[0]
        assert classes == "tool-line"
        assert content == f'⏺ $ {"y" * 60}…'

    def test_final_event_writes_assistant_final(self) -> None:
        """A final event with a normal response → ``assistant-final`` class."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=True,
            response="all done",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes == [("all done", "assistant-final")]

    def test_aborted_final_writes_aborted_line(self) -> None:
        """A final event with the abort sentinel → italic ``(aborted)`` line."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=True,
            response="<aborted>",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes == [("(aborted)", "assistant-aborted")]

    def test_silent_event_writes_nothing(self) -> None:
        """An event with no tool fields, no final flag, no response → no writes."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            message="assistant message",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes == []


class TestEventRendererSummarizers:
    """One test per ``_SUMMARIZERS`` entry plus the default fallback."""

    def test_summarize_ls_counts_non_empty_lines(self) -> None:
        """``ls`` summariser reports ``"<n> entries"``."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="ls",
            tool_output="a\nb\nc\n\n",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ 3 entries"

    def test_summarize_grep_counts_match_lines(self) -> None:
        """``grep`` summariser reports ``"<n> matches"``."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="grep",
            tool_output="foo.py:1: match\nbar.py:2: match\n",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ 2 matches"

    def test_summarize_bash_reports_exit_zero_and_line_count(self) -> None:
        """``bash`` summariser reports ``"exit 0 · <n> lines"``."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="bash",
            tool_output="hello\nworld\n",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ exit 0 · 2 lines"

    def test_summarize_find_counts_paths(self) -> None:
        """``find`` summariser reports ``"<n> paths"``."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="find",
            tool_output="./a\n./b\n./c\n",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ 3 paths"

    def test_summarize_write_uses_default_first_line(self) -> None:
        """``write`` summariser surfaces the first line, untruncated when short."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="write",
            tool_output="wrote 42 bytes to foo.txt\nignored second line",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ wrote 42 bytes to foo.txt"

    def test_summarize_edit_uses_default_first_line(self) -> None:
        """``edit`` summariser surfaces the first line, untruncated when short."""
        log: FakeRichLog = FakeRichLog()
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="edit",
            tool_output="replaced 1 occurrence in bar.py",
        )

        EventRenderer.render(event=event, log=log)

        assert log.writes[0][0] == "⎿ replaced 1 occurrence in bar.py"

    def test_summarize_read_uses_line_and_byte_counts(self) -> None:
        """``read`` summariser reports ``"<n> lines · <kb> KB"``."""
        log: FakeRichLog = FakeRichLog()
        # 1024 'x' bytes + one trailing newline gives ``1 lines · 1.0 KB``.
        event: ProgressEventDAO = ProgressEventDAO(
            is_final=False,
            tool_name="read",
            tool_output=("x" * 1024) + "\n",
        )

        EventRenderer.render(event=event, log=log)

        content: str = log.writes[0][0]
        assert content.startswith("⎿ ")
        assert "1 lines" in content
        assert "1.0 KB" in content
