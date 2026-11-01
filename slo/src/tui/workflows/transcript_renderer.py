"""WorkflowTranscriptRenderer — shared entry-to-Rich presentation for workflow progress.

Both the external ``slo visualize`` viewer and the in-app session progress modal
render public ``TranscriptEntryDAO`` values through this one formatter, so the
two viewers cannot drift apart. It owns presentation only: no file reads, no
scrolling decisions and no execution state. Every RichLog write passes
``scroll_end=False``; the owning view decides where the reader is.

Feature 94 a.3 (extracted from ``HeadlessWorkflowVisualizer``).
"""

from __future__ import annotations

from typing import Callable

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO

__all__ = ["WorkflowTranscriptRenderer"]

_REASONING_LIMIT: int = 2000
"""Characters of reasoning/thinking shown per entry."""

_WRITTEN_TOOL_OUTPUT_LIMIT: int = 800
"""Characters of tool output written as a RichLog block."""

_FORMATTED_TOOL_OUTPUT_LIMIT: int = 500
"""Characters of tool output inside a single formatted Text block."""

_SEPARATOR: str = "─" * 24
"""Dim rule closing every written entry."""


class WorkflowTranscriptRenderer:
    """Render public transcript entries for workflow progress views."""

    @classmethod
    def write_entry(cls, *, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write one entry as header, body renderables and a closing separator.

        WHAT: Assistant answers and user messages render as Markdown, reasoning and
            thinking as dim italic, tool entries as a bold header plus clipped
            output. Unknown kinds fall back to their literal text.
        WHO: Called by HeadlessWorkflowVisualizer's textual detail pane and by the
            session progress modal.
        WHEN: Once per new entry while a view paints a progress snapshot.

        Args:
            log (RichLog): Target log owned by the calling view; never scrolled here.
            entry (TranscriptEntryDAO): Public entry to render.
        """
        writer: Callable[..., None] = cls._ENTRY_WRITERS.get(entry.kind, cls._write_fallback)
        writer(log=log, entry=entry)
        log.write(Text(_SEPARATOR, style="dim"), scroll_end=False)

    @classmethod
    def format_entry(cls, *, entry: TranscriptEntryDAO) -> Text:
        """Format one entry as a single Rich Text block with role colours.

        WHAT: Builds the textual-mode block used where one renderable per entry is
            required (for example a plain transcript dump).
        WHO: Called by HeadlessWorkflowVisualizer's format dispatcher.
        WHEN: Whenever a textual-mode Text block is requested.

        Args:
            entry (TranscriptEntryDAO): Public entry to format.

        Returns:
            Text: Styled block ending with a newline.
        """
        block = Text()
        if entry.kind == "user":
            block.append("▶ User\n", style="bold cyan")
            cls._append_line(block=block, value=entry.content, style="cyan")
            return block
        if entry.kind == "assistant":
            return cls._format_assistant(block=block, entry=entry)
        if entry.kind == "thinking":
            block.append("~ Thinking\n", style="bold dim")
            cls._append_line(
                block=block, value=cls._clip(value=entry.content, limit=_REASONING_LIMIT), style="dim italic"
            )
            return block
        if entry.kind == "tool":
            block.append(f"⚙ {entry.tool_name or 'tool'}\n", style="bold yellow")
            output: str = cls._clip(value=entry.output, limit=_FORMATTED_TOOL_OUTPUT_LIMIT)
            cls._append_line(block=block, value=output, style="yellow")
            return block
        block.append(str(entry) + "\n")
        return block

    @classmethod
    def _format_assistant(cls, *, block: Text, entry: TranscriptEntryDAO) -> Text:
        """Append the assistant header, optional reasoning and answer to ``block``.

        Args:
            block (Text): Empty block being built by format_entry.
            entry (TranscriptEntryDAO): Assistant entry.

        Returns:
            Text: The completed block.
        """
        block.append("◀ Assistant\n", style="bold green")
        if entry.reasoning:
            block.append("~ reasoning\n", style="bold dim")
            block.append(entry.reasoning[:_REASONING_LIMIT] + "\n", style="dim italic")
        cls._append_line(block=block, value=entry.answer or entry.content, style="green")
        return block

    @staticmethod
    def _append_line(*, block: Text, value: object, style: str) -> None:
        """Append ``value`` plus a newline when it is non-empty.

        Args:
            block (Text): Block being built.
            value (object): Optional body text.
            style (str): Rich style for the body.
        """
        if value:
            block.append(f"{value}\n", style=style)

    @staticmethod
    def _clip(*, value: object, limit: int) -> str:
        """Return ``value`` as text clipped to ``limit`` characters; empty for None.

        Args:
            value (object): Optional body value.
            limit (int): Maximum characters kept.

        Returns:
            str: Clipped text.
        """
        return str(value)[:limit] if value else ""

    @staticmethod
    def _write_user(*, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write the user header and Markdown body.

        Args:
            log (RichLog): Target log.
            entry (TranscriptEntryDAO): User entry.
        """
        log.write(Text("▶ User", style="bold cyan"), scroll_end=False)
        if entry.content:
            log.write(Markdown(entry.content), scroll_end=False)

    @staticmethod
    def _write_assistant(*, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write the assistant header, optional reasoning and Markdown answer.

        Args:
            log (RichLog): Target log.
            entry (TranscriptEntryDAO): Assistant entry.
        """
        log.write(Text("◀ Assistant", style="bold green"), scroll_end=False)
        if entry.reasoning:
            log.write(Text("~ reasoning", style="bold dim"), scroll_end=False)
            log.write(Markdown(entry.reasoning[:_REASONING_LIMIT], style="dim italic"), scroll_end=False)
        body: str = entry.answer or entry.content or ""
        if body:
            log.write(Markdown(body), scroll_end=False)

    @staticmethod
    def _write_thinking(*, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write the thinking header and clipped dim Markdown body.

        Args:
            log (RichLog): Target log.
            entry (TranscriptEntryDAO): Thinking entry.
        """
        log.write(Text("~ Thinking", style="bold dim"), scroll_end=False)
        if entry.content:
            log.write(Markdown(entry.content[:_REASONING_LIMIT], style="dim italic"), scroll_end=False)

    @staticmethod
    def _write_tool(*, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write the tool header and clipped output block.

        Args:
            log (RichLog): Target log.
            entry (TranscriptEntryDAO): Tool entry.
        """
        log.write(Text(f"⚙ {entry.tool_name or 'tool'}", style="bold yellow"), scroll_end=False)
        if entry.output:
            log.write(Text(str(entry.output)[:_WRITTEN_TOOL_OUTPUT_LIMIT], style="yellow"), scroll_end=False)

    @staticmethod
    def _write_fallback(*, log: RichLog, entry: TranscriptEntryDAO) -> None:
        """Write an entry of a kind without a dedicated layout as literal text.

        Args:
            log (RichLog): Target log.
            entry (TranscriptEntryDAO): Entry of an unlisted kind.
        """
        log.write(Text(str(entry)), scroll_end=False)

    _ENTRY_WRITERS: dict[str, Callable[..., None]] = {
        "user": _write_user,
        "assistant": _write_assistant,
        "thinking": _write_thinking,
        "tool": _write_tool,
    }
