"""Tests for the shared workflow transcript renderer (feature 94 a.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest
from rich.markdown import Markdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.workflows.transcript_renderer import WorkflowTranscriptRenderer


@dataclass
class _RecordingLog:
    """Record every renderable and its scroll_end argument, like RichLog.write."""

    writes: list[tuple[object, Optional[bool]]] = field(default_factory=list)

    def write(self, content: object, *, scroll_end: Optional[bool] = None) -> None:
        """Store one write call."""
        self.writes.append((content, scroll_end))


def _plain(*, writes: list[tuple[object, Optional[bool]]]) -> list[str]:
    """Return the plain text of every Text/Markdown write, in order."""
    return [_plain_one(item=item) for item, _ in writes]


def _plain_one(*, item: object) -> str:
    """Return the plain text of one Text or Markdown renderable."""
    if isinstance(item, Text):
        return item.plain
    assert isinstance(item, Markdown)
    return item.markup


def _write(*, entry: TranscriptEntryDAO) -> _RecordingLog:
    """Render one entry into a fresh recording log."""
    log = _RecordingLog()
    WorkflowTranscriptRenderer.write_entry(log=log, entry=entry)  # type: ignore[arg-type]
    return log


class TestWriteEntry:
    """``write_entry`` renders one entry and never moves the reader's position."""

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            (TranscriptEntryDAO(kind="user", content="hi"), ["▶ User", "hi", "─" * 24]),
            (
                TranscriptEntryDAO(kind="assistant", reasoning="why", answer="ok"),
                ["◀ Assistant", "~ reasoning", "why", "ok", "─" * 24],
            ),
            (TranscriptEntryDAO(kind="assistant", content="fallback"), ["◀ Assistant", "fallback", "─" * 24]),
            (TranscriptEntryDAO(kind="thinking", content="hmm"), ["~ Thinking", "hmm", "─" * 24]),
            (TranscriptEntryDAO(kind="tool", tool_name="grep", output="out"), ["⚙ grep", "out", "─" * 24]),
            (TranscriptEntryDAO(kind="tool"), ["⚙ tool", "─" * 24]),
            (TranscriptEntryDAO(kind="user"), ["▶ User", "─" * 24]),
        ],
    )
    def test_entry_kinds_render_existing_layout(self, entry: TranscriptEntryDAO, expected: list[str]) -> None:
        """Each kind keeps the external viewer's header, body and separator."""
        log = _write(entry=entry)

        assert _plain(writes=log.writes) == expected

    def test_every_write_passes_scroll_end_false(self) -> None:
        """No write may scroll the progress log, even with auto-scroll disabled."""
        log = _write(entry=TranscriptEntryDAO(kind="assistant", reasoning="r", answer="a"))

        assert {scroll_end for _, scroll_end in log.writes} == {False}

    def test_answers_render_markdown_and_long_bodies_are_clipped(self) -> None:
        """Markdown bodies stay Markdown; thinking/tool bodies keep their 2000/800 caps."""
        answer = _write(entry=TranscriptEntryDAO(kind="assistant", answer="# Title"))
        thinking = _write(entry=TranscriptEntryDAO(kind="thinking", content="t" * 2100))
        tool = _write(entry=TranscriptEntryDAO(kind="tool", tool_name="x", output="o" * 900))

        assert isinstance(answer.writes[1][0], Markdown)
        assert _plain(writes=thinking.writes)[1] == "t" * 2000
        assert _plain(writes=tool.writes)[1] == "o" * 800

    def test_markup_in_content_is_literal(self) -> None:
        """Untrusted tool output with Rich markup is written as literal text."""
        log = _write(entry=TranscriptEntryDAO(kind="tool", tool_name="[b]x[/b]", output="[red]boom[/red]"))

        assert _plain(writes=log.writes)[:2] == ["⚙ [b]x[/b]", "[red]boom[/red]"]

    async def test_writes_to_mounted_rich_log_without_scrolling(self) -> None:
        """A mounted non-following RichLog keeps its offset after rendering entries."""

        class _Host(App[None]):
            def compose(self) -> ComposeResult:
                yield RichLog(id="log", wrap=False, auto_scroll=False)

        async with _Host().run_test(size=(60, 10)) as pilot:
            log = pilot.app.query_one("#log", RichLog)
            for index in range(30):
                WorkflowTranscriptRenderer.write_entry(
                    log=log, entry=TranscriptEntryDAO(kind="user", content=str(index))
                )
            await pilot.pause()

            assert log.scroll_y == 0
            assert log.max_scroll_y > 0


class TestFormatEntry:
    """``format_entry`` keeps the textual single-Text formatting."""

    def test_thinking_entry_renders_header(self) -> None:
        """Thinking entries carry the thinking header and body."""
        text = WorkflowTranscriptRenderer.format_entry(
            entry=TranscriptEntryDAO(kind="thinking", content="deep")
        )

        assert text.plain == "~ Thinking\ndeep\n"

    def test_assistant_entry_renders_reasoning_then_answer(self) -> None:
        """Assistant entries show reasoning before the answer."""
        text = WorkflowTranscriptRenderer.format_entry(
            entry=TranscriptEntryDAO(kind="assistant", reasoning="r", answer="a")
        )

        assert text.plain == "◀ Assistant\n~ reasoning\nr\na\n"

    @pytest.mark.parametrize(
        ("entry", "expected"),
        [
            (TranscriptEntryDAO(kind="user", content="u"), "▶ User\nu\n"),
            (TranscriptEntryDAO(kind="assistant", content="c"), "◀ Assistant\nc\n"),
            (TranscriptEntryDAO(kind="tool", output="o" * 600), "⚙ tool\n" + "o" * 500 + "\n"),
        ],
    )
    def test_remaining_kinds(self, entry: TranscriptEntryDAO, expected: str) -> None:
        """User, assistant-content and tool entries keep their layout and caps."""
        assert WorkflowTranscriptRenderer.format_entry(entry=entry).plain == expected
