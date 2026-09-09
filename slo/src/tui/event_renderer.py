"""Render ``ProgressEventDAO``s into ``RichLog`` lines (sub-spec 02.a.2).

Emits a Claude-Code-style two-line block per tool call:

  ``⏺ <tool>(<args>)``        — headline written on the call event
  ``⎿ <summary>``             — continuation written on the result event

All other intermediate events (assistant-step labels, no-op chunks) are
suppressed: they were noise in the previous renderer. Final events keep
their old behaviour (markdown render or italic ``(aborted)``).
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from src.agents.slo_agent.dao import ProgressEventDAO

__all__ = [
    "EventRenderer",
    "RichLogLike",
    "format_tool_call_headline",
    "format_tool_result_line",
]


_ARG_STRING_PREVIEW_CHARS: int = 60
"""Hard cap on a single string-valued arg before it is ellipsised in headlines."""

_DEFAULT_SUMMARY_CHARS: int = 120
"""Hard cap on the first-line summary used for unknown tools."""


class RichLogLike(Protocol):
    """Minimal subset of Textual's ``RichLog`` we depend on.

    Defined as a ``Protocol`` so tests can substitute an in-memory fake
    without importing Textual. ``classes`` carries a semantic class name
    through to the 02.a.3 adapter, which maps it to a Rich style;
    Textual's real ``RichLog.write`` has no ``classes`` parameter.
    """

    def write(self, content: str, classes: str = "") -> None:
        """Append a line to the log."""
        ...


def _summarize_read(output: str) -> str:
    """Summarise the ``read`` tool's output as ``"<n> lines · <kb>"``.

    Args:
        output (str): Raw stringified return value of ``read``.

    Returns:
        str: A short headline like ``"134 lines · 4.2 KB"``.
    """
    line_count: int = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
    byte_count: int = len(output.encode(encoding="utf-8"))
    kilobytes: float = byte_count / 1024.0
    return f"{line_count} lines · {kilobytes:.1f} KB"


def _summarize_ls(output: str) -> str:
    """Summarise the ``ls`` tool's output as ``"<n> entries"``.

    Args:
        output (str): Raw stringified return value of ``ls``.

    Returns:
        str: A short headline like ``"7 entries"``.
    """
    entries: list[str] = [line for line in output.splitlines() if line.strip()]
    return f"{len(entries)} entries"


def _summarize_grep(output: str) -> str:
    """Summarise the ``grep`` tool's output as ``"<n> matches"``.

    Args:
        output (str): Raw stringified return value of ``grep``.

    Returns:
        str: A short headline like ``"12 matches"``.
    """
    matches: list[str] = [line for line in output.splitlines() if line.strip()]
    return f"{len(matches)} matches"


def _summarize_bash(output: str) -> str:
    """Summarise the ``bash`` tool's output as ``"exit 0 · <n> lines"``.

    Args:
        output (str): Raw stringified return value of ``bash``.

    Returns:
        str: A short headline like ``"exit 0 · 8 lines"``. The exit
            code is best-effort — we always report ``0`` because the
            tool layer surfaces non-zero exits as ``ToolMessage`` text
            rather than as a structured field.
    """
    line_count: int = sum(1 for line in output.splitlines() if line.strip())
    return f"exit 0 · {line_count} lines"


def _summarize_write(output: str) -> str:
    """Summarise the ``write`` tool's output as the first line.

    Args:
        output (str): Raw stringified return value of ``write``.

    Returns:
        str: The first non-empty line, truncated to the default cap.
    """
    return _summarize_default(output=output)


def _summarize_edit(output: str) -> str:
    """Summarise the ``edit`` tool's output as the first line.

    Args:
        output (str): Raw stringified return value of ``edit``.

    Returns:
        str: The first non-empty line, truncated to the default cap.
    """
    return _summarize_default(output=output)


def _summarize_find(output: str) -> str:
    """Summarise the ``find`` tool's output as ``"<n> paths"``.

    Args:
        output (str): Raw stringified return value of ``find``.

    Returns:
        str: A short headline like ``"42 paths"``.
    """
    paths: list[str] = [line for line in output.splitlines() if line.strip()]
    return f"{len(paths)} paths"


def _summarize_default(output: str) -> str:
    """Fallback summariser: first line, truncated to ``_DEFAULT_SUMMARY_CHARS``.

    Args:
        output (str): Raw stringified return value of an unknown tool.

    Returns:
        str: The first line of ``output``, ellipsised when it exceeds
            ``_DEFAULT_SUMMARY_CHARS``.
    """
    first_line: str = output.split(sep="\n", maxsplit=1)[0] if output else ""
    if len(first_line) <= _DEFAULT_SUMMARY_CHARS:
        return first_line
    return f"{first_line[:_DEFAULT_SUMMARY_CHARS]}…"


def _format_args(tool_input: dict[str, Any]) -> str:
    """Render a tool-call args dict for the generic fallback headline.

    Args:
        tool_input (dict[str, Any]): The tool call's args dict.

    Returns:
        str: A comma-separated argument list.
    """
    parts: list[str] = [f"{key}={_format_arg_value(value=value)}" for key, value in tool_input.items()]
    return ", ".join(parts)


def _format_arg_value(value: Any) -> str:
    """Render one tool-call arg value for headline display.

    Args:
        value (Any): The single arg value.

    Returns:
        str: A quoted+truncated string for ``str`` values; ``repr(value)``
            for everything else.
    """
    if isinstance(value, str):
        return _quote_and_truncate_string(value=value)
    return repr(value)


def _quote_and_truncate_string(*, value: str) -> str:
    """Quote ``value`` and ellipsise when longer than the preview cap.

    Args:
        value (str): A raw string arg.

    Returns:
        str: A double-quoted, possibly-ellipsised representation.
    """
    if len(value) <= _ARG_STRING_PREVIEW_CHARS:
        return f'"{value}"'
    return f'"{value[:_ARG_STRING_PREVIEW_CHARS]}…"'


def _truncate_inline_text(*, value: str) -> str:
    """Truncate inline headline text without adding quotes.

    Args:
        value (str): Raw inline text.

    Returns:
        str: Possibly-ellipsised inline text.
    """
    if len(value) <= _ARG_STRING_PREVIEW_CHARS:
        return value
    return f"{value[:_ARG_STRING_PREVIEW_CHARS]}…"


def _string_arg(*, tool_input: dict[str, Any], key: str) -> Optional[str]:
    """Return a string arg value when present.

    Args:
        tool_input (dict[str, Any]): Tool args.
        key (str): Arg key.

    Returns:
        Optional[str]: The string value when present.
    """
    value: object = tool_input.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _int_arg(*, tool_input: dict[str, Any], key: str) -> Optional[int]:
    """Return an int arg value when present.

    Args:
        tool_input (dict[str, Any]): Tool args.
        key (str): Arg key.

    Returns:
        Optional[int]: The int value when present.
    """
    value: object = tool_input.get(key)
    if isinstance(value, int):
        return value
    return None


def _format_read_line_range(*, tool_input: dict[str, Any]) -> str:
    """Format the read tool's optional line range suffix.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: ``":start-end"`` style suffix, or ``""`` when absent.
    """
    offset: Optional[int] = _int_arg(tool_input=tool_input, key="offset")
    limit: Optional[int] = _int_arg(tool_input=tool_input, key="limit")
    if offset is None and limit is None:
        return ""
    start_line: int = offset if offset is not None else 1
    if limit is None:
        return f":{start_line}"
    end_line: int = start_line + limit - 1
    return f":{start_line}-{end_line}"


def _format_read_call(*, tool_input: dict[str, Any]) -> str:
    """Format a ``read`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Read-specific headline body.
    """
    path: str = (
        _string_arg(tool_input=tool_input, key="path")
        or _string_arg(
            tool_input=tool_input,
            key="file_path",
        )
        or "..."
    )
    return f"read {_truncate_inline_text(value=path)}{_format_read_line_range(tool_input=tool_input)}"


def _format_grep_call(*, tool_input: dict[str, Any]) -> str:
    """Format a ``grep`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Grep-specific headline body.
    """
    pattern: str = _string_arg(tool_input=tool_input, key="pattern") or ""
    path: str = _string_arg(tool_input=tool_input, key="path") or "."
    headline: str = f"grep /{_truncate_inline_text(value=pattern)}/ in {_truncate_inline_text(value=path)}"
    glob: Optional[str] = _string_arg(tool_input=tool_input, key="glob")
    if glob:
        headline += f" ({_truncate_inline_text(value=glob)})"
    limit: Optional[int] = _int_arg(tool_input=tool_input, key="limit")
    if limit is not None:
        headline += f" limit {limit}"
    return headline


def _format_bash_call(*, tool_input: dict[str, Any]) -> str:
    """Format a ``bash`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Bash-specific headline body.
    """
    command: str = _string_arg(tool_input=tool_input, key="command") or "..."
    headline: str = f"$ {_truncate_inline_text(value=command)}"
    timeout: Optional[int] = _int_arg(tool_input=tool_input, key="timeout")
    if timeout is not None:
        headline += f" (timeout {timeout}s)"
    return headline


def _format_find_call(*, tool_input: dict[str, Any]) -> str:
    """Format a ``find`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Find-specific headline body.
    """
    pattern: str = _string_arg(tool_input=tool_input, key="pattern") or "*"
    path: str = _string_arg(tool_input=tool_input, key="path") or "."
    headline: str = f"find {_truncate_inline_text(value=pattern)} in {_truncate_inline_text(value=path)}"
    limit: Optional[int] = _int_arg(tool_input=tool_input, key="limit")
    if limit is not None:
        headline += f" (limit {limit})"
    return headline


def _format_ls_call(*, tool_input: dict[str, Any]) -> str:
    """Format an ``ls`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Ls-specific headline body.
    """
    path: str = _string_arg(tool_input=tool_input, key="path") or "."
    headline: str = f"ls {_truncate_inline_text(value=path)}"
    limit: Optional[int] = _int_arg(tool_input=tool_input, key="limit")
    if limit is not None:
        headline += f" (limit {limit})"
    return headline


def _format_write_call(*, tool_input: dict[str, Any]) -> str:
    """Format a ``write`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Write-specific headline body.
    """
    path: str = _string_arg(tool_input=tool_input, key="path") or "..."
    return f"write {_truncate_inline_text(value=path)}"


def _format_edit_call(*, tool_input: dict[str, Any]) -> str:
    """Format an ``edit`` tool call headline.

    Args:
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Edit-specific headline body.
    """
    path: str = _string_arg(tool_input=tool_input, key="path") or "..."
    return f"edit {_truncate_inline_text(value=path)}"


def _format_default_call(*, name: str, tool_input: dict[str, Any]) -> str:
    """Format the fallback generic tool call headline.

    Args:
        name (str): Tool name.
        tool_input (dict[str, Any]): Tool args.

    Returns:
        str: Generic ``name(key=value)`` body.
    """
    return f"{name}({_format_args(tool_input=tool_input)})"


def format_tool_call_headline(*, name: str, tool_input: dict[str, Any]) -> str:
    """Format the visible headline for one tool call.

    Args:
        name (str): Tool name.
        tool_input (dict[str, Any]): Tool arguments.

    Returns:
        str: Claude-Code-style ``⏺`` headline line, or ``""`` when the
        tool name and arguments are not yet known (preparing state).
    """
    if name == "tool" and not tool_input:
        return ""
    formatter_map: dict[str, Callable[[dict[str, Any]], str]] = {
        "bash": lambda value: _format_bash_call(tool_input=value),
        "read": lambda value: _format_read_call(tool_input=value),
        "grep": lambda value: _format_grep_call(tool_input=value),
        "find": lambda value: _format_find_call(tool_input=value),
        "ls": lambda value: _format_ls_call(tool_input=value),
        "write": lambda value: _format_write_call(tool_input=value),
        "edit": lambda value: _format_edit_call(tool_input=value),
    }
    formatter: Callable[[dict[str, Any]], str] | None = formatter_map.get(name)
    body: str = (
        formatter(tool_input)
        if formatter is not None
        else _format_default_call(
            name=name,
            tool_input=tool_input,
        )
    )
    return f"{EventRenderer.HEADLINE_GLYPH} {body}"


def format_tool_result_line(*, name: Optional[str], output: str) -> str:
    """Format the visible continuation line for one tool result.

    Args:
        name (Optional[str]): Tool name when known.
        output (str): Raw tool output.

    Returns:
        str: Claude-Code-style ``⎿`` continuation line.
    """
    summary: str = EventRenderer._summarize_tool_output(name=name, output=output)
    return f"{EventRenderer.CONTINUATION_GLYPH} {summary}"


class EventRenderer:
    """Stateless dispatcher from ``ProgressEventDAO`` to ``RichLog`` lines."""

    HEADLINE_GLYPH: str = "⏺"
    CONTINUATION_GLYPH: str = "⎿"
    TOOL_HEADLINE_CLASS: str = "tool-line"
    TOOL_RESULT_CLASS: str = "tool-result"
    FINAL_CLASS: str = "assistant-final"
    ABORTED_CLASS: str = "assistant-aborted"

    _SUMMARIZERS: dict[str, Callable[[str], str]] = {
        "read": _summarize_read,
        "ls": _summarize_ls,
        "grep": _summarize_grep,
        "bash": _summarize_bash,
        "write": _summarize_write,
        "edit": _summarize_edit,
        "find": _summarize_find,
    }
    _RENDERER_OVERRIDES: dict[str, Callable[[str], str]] = {}

    @classmethod
    def set_renderer_overrides(cls, *, renderers: dict[str, Callable[[str], str]]) -> None:
        """Replace the registered per-tool renderer overrides.

        WHAT: Installs a session-owned renderer map before built-in summaries.
        WHO: ``SloAgentSession`` calls this after plugin registrations change.
        WHEN: Plugins load, reload, or are disabled for the active session.

        Args:
            renderers (dict[str, Callable[[str], str]]): Renderer functions keyed
                by their canonical visible tool name.
        """
        cls._RENDERER_OVERRIDES = dict(renderers)

    @classmethod
    def render(cls, *, event: ProgressEventDAO, log: RichLogLike) -> None:
        """Dispatch ``event`` to the correct render branch.

        Branch order:
            1. Final event → ``_render_final``.
            2. Tool-call event (``tool_input`` set) → headline.
            3. Tool-result event (``tool_output`` set) → continuation.
            4. Everything else → silent no-op (intermediate noise).

        Args:
            event (ProgressEventDAO): The event to render.
            log (RichLogLike): The transcript to write into.
        """
        if event.is_final:
            cls._render_final(event=event, log=log)
            return
        if event.tool_input is not None:
            cls._render_tool_call_headline(event=event, log=log)
            return
        if event.tool_output is not None:
            cls._render_tool_call_continuation(event=event, log=log)
            return

    @classmethod
    def _render_tool_call_headline(
        cls,
        *,
        event: ProgressEventDAO,
        log: RichLogLike,
    ) -> None:
        """Render the ``⏺ <tool>(<args>)`` headline line.

        Args:
            event (ProgressEventDAO): The tool-call event (``tool_input``
                is guaranteed non-None by the dispatcher).
            log (RichLogLike): The transcript to write into.
        """
        tool_name: str = event.tool_name or "tool"
        tool_input: dict[str, Any] = event.tool_input or {}
        headline: str = format_tool_call_headline(name=tool_name, tool_input=tool_input)
        if not headline:
            return
        log.write(
            content=headline,
            classes=cls.TOOL_HEADLINE_CLASS,
        )

    @classmethod
    def _render_tool_call_continuation(
        cls,
        *,
        event: ProgressEventDAO,
        log: RichLogLike,
    ) -> None:
        """Render the ``⎿ <summary>`` continuation line.

        Args:
            event (ProgressEventDAO): The tool-result event
                (``tool_output`` is guaranteed non-None by the
                dispatcher).
            log (RichLogLike): The transcript to write into.
        """
        log.write(
            content=format_tool_result_line(
                name=event.tool_name,
                output=event.tool_output or "",
            ),
            classes=cls.TOOL_RESULT_CLASS,
        )

    @classmethod
    def _summarize_tool_output(cls, *, name: Optional[str], output: str) -> str:
        """Look up the per-tool summariser and apply it.

        Unknown tool names fall through to ``_summarize_default``.

        Args:
            name (Optional[str]): The tool name from the event.
            output (str): The raw stringified return value.

        Returns:
            str: A one-line summary suitable for the continuation glyph.
        """
        tool_name: str = name or ""
        override: Callable[[str], str] | None = cls._RENDERER_OVERRIDES.get(tool_name)
        if override is not None:
            return override(output)
        summariser: Callable[[str], str] = cls._SUMMARIZERS.get(tool_name, _summarize_default)
        return summariser(output)

    @classmethod
    def _render_final(cls, *, event: ProgressEventDAO, log: RichLogLike) -> None:
        """Render the run's final event.

        Args:
            event (ProgressEventDAO): The final event.
            log (RichLogLike): The transcript to write into.
        """
        response: str = event.response or ""
        if response == "<aborted>":
            log.write(content="(aborted)", classes=cls.ABORTED_CLASS)
            return
        log.write(content=response, classes=cls.FINAL_CLASS)
