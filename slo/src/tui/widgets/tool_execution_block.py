"""Live-updating tool execution widget for the Slo TUI."""

from __future__ import annotations

import json
from typing import Any, Optional

from textual.app import ComposeResult
from textual.containers import Vertical

from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.tui.event_renderer import (
    format_tool_call_headline,
    format_tool_result_line,
)
from src.tui.widgets.literal_text_static import LiteralTextStatic

__all__ = ["ToolExecutionBlock"]


class ToolExecutionBlock(Vertical):
    """Render one live tool execution with expandable details."""

    can_focus: bool = True

    DEFAULT_CSS = """
    ToolExecutionBlock {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
        padding: 0 1;
        background: $tool-pending-bg;
    }

    ToolExecutionBlock.-done {
        background: $tool-success-bg;
    }

    ToolExecutionBlock.-error {
        background: $tool-error-bg;
    }

    ToolExecutionBlock.-active {
        border-left: wide $accent;
        padding-left: 1;
    }

    ToolExecutionBlock .tool-call-headline {
        color: $success;
        text-style: bold;
        background: transparent;
    }

    ToolExecutionBlock .tool-call-result {
        color: $text-muted;
        background: transparent;
    }

    ToolExecutionBlock .tool-call-hint {
        color: $text-muted;
        text-style: italic;
        background: transparent;
    }

    ToolExecutionBlock .tool-call-incomplete {
        color: $warning;
        text-style: italic;
        background: transparent;
    }
    """

    def __init__(
        self,
        *,
        tool_call_id: str,
        tool_name: Optional[str],
        force_expanded: Optional[bool] = None,
    ) -> None:
        """Seed a live tool block.

        Args:
            tool_call_id (str): Stable tool call id.
            tool_name (Optional[str]): Tool name when known; ``None`` before
                the streamed name resolves (headline stays blank until then).
            force_expanded (Optional[bool]): Initial expansion state from the
                global expand-all toggle. ``None`` (default) and ``False`` both
                start collapsed; ``True`` starts expanded so details appear as
                soon as arguments and output arrive.
        """
        super().__init__()
        self._tool_call_id: str = tool_call_id
        self._tool_name: Optional[str] = tool_name
        self._tool_input: dict[str, Any] = {}
        self._result_output: Optional[str] = None
        self._partial_output: Optional[str] = None
        # A tool block is compact by default; expand only when the global
        # toggle explicitly forces it on.
        self._expanded: bool = force_expanded is True
        self._headline: LiteralTextStatic = LiteralTextStatic("", classes="tool-call-headline")
        self._hint: LiteralTextStatic = LiteralTextStatic("", classes="tool-call-hint")
        self._expanded_body: LiteralTextStatic = LiteralTextStatic("")
        self._result_line: LiteralTextStatic = LiteralTextStatic("", classes="tool-call-result")
        self._last_rendered_snapshot: tuple[str, str, str] = ("", "", "")
        self._marked_incomplete: bool = False
        self._refresh()

    def compose(self) -> ComposeResult:
        """Compose the call, hint, expanded body, and result rows.

        Yields:
            ComposeResult: Headline, hint, expanded body, and result widgets.
        """
        yield self._headline
        yield self._hint
        yield self._expanded_body
        yield self._result_line

    @property
    def tool_call_id(self) -> str:
        """Return the stable tool call id.

        Returns:
            str: Tool call id.
        """
        return self._tool_call_id

    @property
    def tool_name(self) -> Optional[str]:
        """Return the current tool name, when known.

        Returns:
            Optional[str]: Tool name, or ``None`` before it resolves.
        """
        return self._tool_name

    @property
    def tool_input(self) -> dict[str, Any]:
        """Return the current parsed tool input.

        Returns:
            dict[str, Any]: Parsed tool args.
        """
        return dict(self._tool_input)

    @property
    def result_output(self) -> Optional[str]:
        """Return the latest tool output.

        Returns:
            Optional[str]: Raw output when present.
        """
        return self._result_output

    @property
    def is_expandable(self) -> bool:
        """Return True when the block carries hidden detail.

        Returns:
            bool: True when expanded mode can reveal more information.
        """
        return self._has_expandable_arguments() or self._has_expandable_output()

    def get_copyable_text(self) -> str:
        """Return a plain-text summary of the tool call for clipboard copy.

        Formats the tool name, serialized input, and result output into a
        compact multi-line block. Called by
        ``SloTUI.action_copy_visible_text`` when this block holds focus.

        Returns:
            str: Tool name, input args, and result joined by newlines.
        """
        lines: list[str] = [f"tool: {self._tool_name}"]
        if self._tool_input:
            lines.append(f"input: {json.dumps(obj=self._tool_input, indent=2)}")
        if self._result_output is not None:
            lines.append(f"result: {self._result_output}")
        return "\n".join(lines)

    def set_active(self, *, active: bool) -> None:
        """Toggle the active block styling.

        Args:
            active (bool): True when this is the active expandable block.
        """
        self.set_class(active, "-active")

    def toggle_expanded(self) -> None:
        """Toggle expanded detail rendering when hidden detail exists."""
        if not self.is_expandable:
            return
        self._expanded = not self._expanded
        self._refresh()

    def set_expanded(self, *, expanded: bool) -> None:
        """Set the expansion state from the global expand-all toggle.

        A no-op when the block carries no hidden detail (nothing to reveal)
        or when the state is unchanged.

        Args:
            expanded (bool): True reveals arguments and raw output; False
                collapses back to the headline and result summary.
        """
        if not self.is_expandable:
            return
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._refresh()

    def update_tool_call(
        self,
        *,
        tool_name: Optional[str] = None,
        tool_input: Optional[dict[str, Any]] = None,
    ) -> None:
        """Refresh the visible tool call headline.

        Args:
            tool_name (Optional[str]): Latest tool name when known.
            tool_input (Optional[dict[str, Any]]): Latest parsed tool args.
        """
        if tool_name:
            self._tool_name = tool_name
        if tool_input is not None:
            self._tool_input = dict(tool_input)
        self._refresh()

    def update_partial(self, *, snapshot: ToolOutputUpdateDAO) -> None:
        """Render one in-progress output snapshot without settling this call.

        WHAT: Stores display-only partial content separately from terminal state.
        WHO: ``TranscriptProjectionAdapter`` calls it for tool-output update events.
        WHEN: A streaming-capable tool is still running.
        """
        self._tool_name = snapshot.tool_name or self._tool_name
        self._partial_output = snapshot.content_snapshot
        self.add_class("-running")
        self._result_line.update(
            format_tool_result_line(name=self._tool_name, output=snapshot.content_snapshot)
        )
        self._refresh()

    def update_result(
        self,
        *,
        tool_name: Optional[str],
        output: str,
    ) -> None:
        """Store a recorded tool result and select its completed visual state.

        Called by ``TranscriptProjectionAdapter`` when a tool-result event arrives. The
        method preserves result formatting and expansion behavior; the classes
        are CSS hooks only and do not replace ``_result_output`` as lifecycle
        truth.

        Args:
            tool_name (Optional[str]): Latest tool name when known.
            output (str): Raw tool output.
        """
        if tool_name:
            self._tool_name = tool_name
        self._result_output = output
        self._partial_output = None
        self.remove_class("-error")
        self.remove_class("-running")
        self.add_class("-done")
        self._result_line.update(
            format_tool_result_line(
                name=self._tool_name,
                output=output,
            )
        )
        self._refresh()

    def mark_incomplete(self) -> None:
        """Mark a terminal no-result tool call and select its error visual state.

        Called by replay/projector recovery when no tool result can arrive. The
        existing ``is_incomplete`` field remains the source used by transcript
        liveness; these classes merely make that state visually legible.
        """
        self._result_output = None
        self._marked_incomplete = True
        self.remove_class("-done")
        self.add_class("-error")
        self._result_line.remove_class("tool-call-result")
        self._result_line.add_class("tool-call-incomplete")
        self._result_line.update(
            "⎿ no result recorded — this call may not have completed before the session ended"
        )

    @property
    def is_incomplete(self) -> bool:
        """Return True when this tool call was explicitly marked incomplete.

        A tool block marked incomplete is terminal (its result will never
        arrive), so the transcript window may safely evict it — unlike a block
        still legitimately awaiting its result. Read by ``SloTUI._is_block_live``.

        Returns:
            bool: True when ``mark_incomplete`` has been called.
        """
        return self._marked_incomplete

    def _refresh(self) -> None:
        """Refresh visible surfaces from tool state, skipping unchanged renders.

        Each ``Static.update`` forces a transcript reflow, so a ``_refresh`` that
        would render identical headline/hint/body strings (e.g. a repeated
        ``update_tool_call`` with the same args) must do no DOM work.
        """
        headline: str = format_tool_call_headline(name=self._tool_name, tool_input=self._tool_input)
        hint: str = self._hint_text()
        body: str = self._expanded_body_text()
        snapshot: tuple[str, str, str] = (headline, hint, body)
        if snapshot == self._last_rendered_snapshot:
            return
        self._last_rendered_snapshot = snapshot
        self._headline.update(headline)
        self._hint.update(hint)
        self._expanded_body.update(body)

    def _hint_text(self) -> str:
        """Return the collapsed-mode expansion hint when needed.

        Returns:
            str: Hint line for hidden detail, or ``""``.
        """
        if not self.is_expandable or self._expanded:
            return ""
        return "⎿ Press Ctrl+O to expand details"

    def _expanded_body_text(self) -> str:
        """Return the expanded detail body text.

        Returns:
            str: Expanded call/output detail, or ``""`` when collapsed.
        """
        if not self._expanded:
            return ""
        sections: list[str] = []
        arguments_text: str = self._pretty_arguments()
        if arguments_text:
            sections.append(f"arguments:\n{arguments_text}")
        output_text: str = self._result_output or ""
        if output_text:
            sections.append(f"output:\n{output_text}")
        return "\n\n".join(sections)

    def _pretty_arguments(self) -> str:
        """Return the pretty-printed tool arguments.

        Returns:
            str: Indented JSON arguments, or ``""`` when absent.
        """
        if not self._tool_input:
            return ""
        return json.dumps(self._tool_input, indent=2, ensure_ascii=False)

    def _has_expandable_arguments(self) -> bool:
        """Return True when pretty-printed arguments would add detail.

        Returns:
            bool: True when the block has parsed arguments.
        """
        return bool(self._tool_input)

    def _has_expandable_output(self) -> bool:
        """Return True when the raw output should be user-expandable.

        Returns:
            bool: True when a raw result body is present.
        """
        return bool(self._result_output)
