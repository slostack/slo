"""Syntax-highlight spans for expanded tool-call arguments and output.

WHAT: Chooses a language for one tool call's output (from the tool name, its
arguments, or a cheap content sniff) and produces semantic role spans over the
exact text, reusing the Markdown compiler's Pygments lexer allowlist and
theme roles (``markdown-code-*``). Spans are pure role names; widgets resolve
them against the active theme at render time.
WHO: ``ToolExecutionBlock`` calls ``highlight_tool_body`` when expanded.
WHEN: Only for expanded bodies; oversized text skips highlighting entirely.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from textual.content import Span

from src.tui.widgets.markdown_content_compiler import (
    _append_code_token_spans,
    _append_diff_line_spans,
    _VisibleBufferWriter,
)

__all__ = ["HIGHLIGHT_MAX_CHARS", "code_spans", "detect_output_language"]

HIGHLIGHT_MAX_CHARS: int = 200_000
"""Text longer than this renders plain so huge outputs never stall the transcript."""

_EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cc": "c++",
    ".cpp": "c++",
    ".hpp": "c++",
    ".cs": "c#",
    ".java": "java",
    ".rs": "rust",
    ".zig": "zig",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".diff": "diff",
    ".patch": "diff",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".tcss": "css",
    ".sql": "sql",
    ".md": "markdown",
}
_FILENAME_LANGUAGES: dict[str, str] = {"dockerfile": "dockerfile", "containerfile": "dockerfile"}
_PATH_TOOLS: frozenset[str] = frozenset({"read", "write"})
_LOCATION_TOOLS: frozenset[str] = frozenset({"grep"})
_LOCATION_ROLE: str = "markdown-code-name"


def language_for_path(*, path: str) -> str | None:
    """Return the highlight language implied by a file path, if supported.

    Args:
        path (str): File path as passed to the tool.

    Returns:
        Optional[str]: A compiler lexer alias, or ``None`` for unknown types.
    """
    pure: PurePosixPath = PurePosixPath(path)
    by_name: str | None = _FILENAME_LANGUAGES.get(pure.name.lower())
    if by_name is not None:
        return by_name
    return _EXTENSION_LANGUAGES.get(pure.suffix.lower())


def detect_output_language(*, tool_name: str | None, tool_input: dict[str, Any], output: str) -> str | None:
    """Choose the highlight language for one tool's raw output.

    Args:
        tool_name (Optional[str]): Tool name when known.
        tool_input (dict[str, Any]): Parsed tool arguments.
        output (str): Raw tool output.

    Returns:
        Optional[str]: A lexer alias, ``"grep"`` for location-prefixed match
            lines, or ``None`` to render plain.
    """
    if tool_name in _PATH_TOOLS:
        path: Any = tool_input.get("path")
        return language_for_path(path=path) if isinstance(path, str) and tool_name == "read" else None
    if tool_name in _LOCATION_TOOLS:
        return "grep"
    return _sniff_language(output=output)


def _sniff_language(*, output: str) -> str | None:
    """Recognise unified diffs and JSON documents in otherwise untyped output."""
    stripped: str = output.lstrip()
    if stripped.startswith(("diff --git", "--- a/", "@@ ")):
        return "diff"
    if stripped[:1] in ("{", "["):
        try:
            json.loads(stripped)
        except ValueError:
            return None
        return "json"
    return None


def code_spans(*, text: str, language: str | None, offset: int = 0) -> list[Span]:
    """Return semantic role spans that highlight ``text`` as ``language``.

    Args:
        text (str): Exact visible text to highlight.
        language (Optional[str]): Lexer alias from ``detect_output_language``.
        offset (int): Position of ``text`` inside the enclosing visible buffer.

    Returns:
        list[Span]: Role-name spans (possibly empty) shifted by ``offset``.
    """
    if not text or language is None or len(text) > HIGHLIGHT_MAX_CHARS:
        return []
    if language == "grep":
        return _grep_location_spans(text=text, offset=offset)
    writer: _VisibleBufferWriter = _VisibleBufferWriter()
    start, end = writer.append_text(text=text)
    if language == "diff":
        _append_diff_line_spans(code=text, start=start, writer=writer)
    else:
        _append_code_token_spans(code=text, info=language, start=start, end=end, writer=writer)
    return [
        Span(span.start + offset, span.end + offset, span.style)
        for span in writer._spans
        if span.style != "markdown-code-punctuation"
    ]


def _grep_location_spans(*, text: str, offset: int) -> list[Span]:
    """Colour the ``path:line:`` prefix of each grep match line."""
    spans: list[Span] = []
    position: int = offset
    for line in text.splitlines(keepends=True):
        parts: list[str] = line.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            prefix_length: int = len(parts[0]) + len(parts[1]) + 2
            spans.append(Span(position, position + prefix_length, _LOCATION_ROLE))
        position += len(line)
    return spans
