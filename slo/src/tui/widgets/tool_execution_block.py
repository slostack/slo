"""Live-updating tool execution widget for the Slo TUI."""

from __future__ import annotations

import json
from typing import Any, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from src.tui.event_renderer import (
    format_tool_call_headline,
    format_tool_result_line,
)

__all__ = ["ToolExecutionBlock"]


class ToolExecutionBlock(Vertical):
    """Render one live tool execution with expandable details."""

    DEFAULT_CSS = """
    ToolExecutionBlock {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
        padding: 1 1;
        background: $panel;
    }

    ToolExecutionBlock.-active {
        border-left: wide $accent;
        padding-left: 1;
    }

    ToolExecutionBlock .tool-call-headline {
        color: $success;
        text-style: bold;
        background: $panel;
    }

    ToolExecutionBlock .tool-call-result {
        color: $text-muted;
        background: transparent;
    }

    ToolExecutionBlock .tool-call-hint {
        color: $text-muted;
        text-style: italic;
        background: $panel;
    }

    ToolExecutionBlock .tool-call-incomplete {
        color: $warning;
        text-style: italic;
        background: $panel;
    }
    """

    def __init__(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        force_expanded: Optional[bool] = None,
    ) -> None:
        """Seed a live tool block.

        Args:
            tool_call_id (str): Stable tool call id.
            tool_name (str): Initial tool name.
            force_expanded (Optional[bool]): Initial expansion state from the
                global expand-all toggle. ``None`` (default) and ``False`` both
                start collapsed; ``True`` starts expanded so details appear as
                soon as arguments and output arrive.
        """
        super().__init__()
        self._tool_call_id: str = tool_call_id
        self._tool_name: str = tool_name
        self._tool_input: dict[str, Any] = {}
        self._result_output: Optional[str] = None
        # A tool block is compact by default; expand only when the global
        # toggle explicitly forces it on.
        self._expanded: bool = force_expanded is True
        self._headline: Static = Static("", classes="tool-call-headline")
        self._hint: Static = Static("", classes="tool-call-hint")
        self._expanded_body: Static = Static("")
        self._result_line: Static = Static("", classes="tool-call-result")
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
    def tool_name(self) -> str:
        """Return the current tool name.

        Returns:
            str: Tool name.
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

    def update_result(
        self,
        *,
        tool_name: Optional[str],
        output: str,
    ) -> None:
        """Refresh the visible tool result summary line.

        Args:
            tool_name (Optional[str]): Latest tool name when known.
            output (str): Raw tool output.
        """
        if tool_name:
            self._tool_name = tool_name
        self._result_output = output
        self._result_line.update(
            format_tool_result_line(
                name=self._tool_name,
                output=output,
            )
        )
        self._refresh()

    def mark_incomplete(self) -> None:
        """Mark this tool call as never having recorded a result.

        Rendered for replayed tool calls whose ``tool_result`` was never
        persisted — the tool hung, the process died, or the session was
        aborted mid-call. The block stays visible (the user can still see
        what was attempted) and carries a small highlighted note instead of
        a blank result line, so a partial transcript never reads as a clean
        empty result.
        """
        self._result_output = None
        self._result_line.remove_class("tool-call-result")
        self._result_line.add_class("tool-call-incomplete")
        self._result_line.update(
            "⎿ no result recorded — this call may not have completed before the session ended"
        )

    def _refresh(self) -> None:
        """Refresh all visible surfaces from the current tool state."""
        self._headline.update(
            format_tool_call_headline(
                name=self._tool_name,
                tool_input=self._tool_input,
            )
        )
        self._hint.update(self._hint_text())
        self._expanded_body.update(self._expanded_body_text())

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
