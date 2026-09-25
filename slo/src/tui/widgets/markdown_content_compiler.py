"""Compile Markdown ASTs into readable, natively selectable Textual content."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from markdown_it import MarkdownIt
from markdown_it.token import Token as MarkdownToken
from pygments import lex
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Keyword, Literal, Name, Number, String, Token
from textual.content import Span
from textual.style import Style

__all__ = ["MarkdownContentCompiler", "MarkdownContentDAO"]

_LOGGER = logging.getLogger(__name__)
_SUPPORTED_LEXER_ALIASES: dict[str, str] = {
    "python": "python",
    "py": "python",
    "bash": "bash",
    "sh": "bash",
    "shell": "bash",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "diff": "diff",
    "patch": "diff",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "tsx": "tsx",
    "jsx": "jsx",
    "toml": "toml",
    "ini": "ini",
    "xml": "xml",
    "html": "html",
    "css": "css",
    "sql": "sql",
    "dockerfile": "dockerfile",
    "markdown": "markdown",
    "md": "markdown",
}
_DIFF_LEXER_NAMES: frozenset[str] = frozenset({"diff", "patch"})


@dataclass(frozen=True)
class MarkdownContentDAO:
    """Hold exact raw Markdown and its independently selectable visible buffer."""

    raw_markdown: str
    visible_text: str
    spans: tuple[Span, ...]


class _VisibleBufferWriter:
    """Own the compiler's sole append-only visible text buffer and role spans."""

    def __init__(self) -> None:
        """Initialize an empty buffer."""
        self._parts: list[str] = []
        self._spans: list[Span] = []
        self._length: int = 0

    def append_text(self, *, text: str) -> tuple[int, int]:
        """Append text and return its half-open visible range."""
        start: int = self._length
        self._parts.append(text)
        self._length += len(text)
        return start, self._length

    def append_styled_text(self, *, text: str, role: str) -> tuple[int, int]:
        """Append text and assign a semantic role to its non-empty range."""
        start, end = self.append_text(text=text)
        self.add_span(start=start, end=end, role=role)
        return start, end

    def append_prefix(self, *, text: str, role: str) -> tuple[int, int]:
        """Append compiler-owned structural text with its semantic role."""
        return self.append_styled_text(text=text, role=role)

    def append_newline_if_needed(self) -> None:
        """Terminate a non-empty current line exactly once."""
        if self._length and not self.visible_text.endswith("\n"):
            self.append_text(text="\n")

    def append_block_separator_if_needed(self) -> None:
        """Separate non-empty adjacent blocks with exactly one blank line."""
        if not self._length:
            return
        if self.visible_text.endswith("\n\n"):
            return
        if self.visible_text.endswith("\n"):
            self.append_text(text="\n")
        else:
            self.append_text(text="\n\n")

    def add_span(self, *, start: int, end: int, role: str) -> None:
        """Add a bounded non-empty semantic role span."""
        if start < end:
            self._spans.append(Span(start, end, role))

    @property
    def length(self) -> int:
        """Return the current visible length."""
        return self._length

    @property
    def visible_text(self) -> str:
        """Return the visible text written so far."""
        return "".join(self._parts)

    def trim_terminal_newlines(self) -> None:
        """Discard compiler-created terminal line separators before building output."""
        text: str = self.visible_text
        trimmed_text: str = text.rstrip("\n")
        if trimmed_text == text:
            return
        self._parts = [trimmed_text]
        self._length = len(trimmed_text)
        self._spans = [span for span in self._spans if span.end <= self._length]

    def build(self, *, raw_markdown: str) -> MarkdownContentDAO:
        """Build validated immutable output or use a safe literal fallback."""
        visible_text: str = self.visible_text
        if not all(0 <= span.start <= span.end <= len(visible_text) for span in self._spans):
            _LOGGER.warning("markdown_compilation_invariant_failed", extra={"raw_length": len(raw_markdown)})
            return _plain_visible_fallback(raw_markdown=raw_markdown)
        return MarkdownContentDAO(
            raw_markdown=raw_markdown, visible_text=visible_text, spans=tuple(self._spans)
        )


class MarkdownContentCompiler:
    """Compile markdown-it AST tokens into one readable visible text buffer."""

    @classmethod
    def compile(cls, *, raw_markdown: str) -> MarkdownContentDAO:
        """Compile raw Markdown into visible text and semantic role spans.

        Args:
            raw_markdown (str): Exact message source retained by its owner.

        Returns:
            MarkdownContentDAO: Raw source, selectable visible text, and visible-buffer spans.
        """
        if not raw_markdown or raw_markdown.isspace():
            return _plain_visible_fallback(raw_markdown=raw_markdown)
        try:
            tokens: list[MarkdownToken] = MarkdownIt("gfm-like").parse(raw_markdown)
            if _contains_table_token(tokens=tokens):
                return _plain_visible_fallback(raw_markdown=raw_markdown)
            writer = _VisibleBufferWriter()
            _BlockCompiler(tokens=tokens, writer=writer).compile()
            return writer.build(raw_markdown=raw_markdown)
        except Exception as error:
            _LOGGER.warning(
                "markdown_compilation_failed",
                extra={"exception_type": type(error).__name__, "raw_length": len(raw_markdown)},
            )
            return _plain_visible_fallback(raw_markdown=raw_markdown)


@dataclass(frozen=True)
class _ListLineContext:
    """Describe a list line without deriving depth from its rendered marker."""

    depth: int
    marker: Optional[str] = None

    @property
    def indentation(self) -> str:
        """Return the exact two-space indentation for this AST list depth."""
        return "  " * self.depth


class _BlockCompiler:
    """Walk block tokens and delegate all visible writes to one writer."""

    def __init__(self, *, tokens: list[MarkdownToken], writer: _VisibleBufferWriter) -> None:
        """Store one token sequence and its shared writer."""
        self._tokens = tokens
        self._writer = writer
        self._index: int = 0

    def compile(self) -> None:
        """Compile every top-level block without a leading or trailing separator."""
        self._compile_until(close_type=None, quote_depth=0, list_line_context=None)
        self._trim_terminal_newlines()

    def _compile_until(
        self,
        *,
        close_type: Optional[str],
        quote_depth: int,
        list_line_context: Optional[_ListLineContext],
    ) -> None:
        """Compile tokens until a matching container close token is reached."""
        first_block: bool = True
        while self._index < len(self._tokens):
            token = self._tokens[self._index]
            token_type: str = getattr(token, "type", "")
            if close_type is not None and token_type == close_type:
                self._index += 1
                return
            if token_type in {"paragraph_open", "heading_open", "fence", "code_block", "hr", "html_block"}:
                if not first_block:
                    self._append_container_separator(
                        quote_depth=quote_depth, list_line_context=list_line_context
                    )
                self._compile_leaf_block(
                    token=token,
                    quote_depth=quote_depth,
                    list_line_context=list_line_context,
                )
                first_block = False
                list_line_context = None
                continue
            if token_type == "blockquote_open":
                if not first_block:
                    self._append_container_separator(
                        quote_depth=quote_depth, list_line_context=list_line_context
                    )
                self._index += 1
                self._compile_until(
                    close_type="blockquote_close",
                    quote_depth=quote_depth + 1,
                    list_line_context=list_line_context,
                )
                first_block = False
                list_line_context = None
                continue
            if token_type in {"bullet_list_open", "ordered_list_open"}:
                if not first_block:
                    self._append_container_separator(
                        quote_depth=quote_depth, list_line_context=list_line_context
                    )
                self._compile_list(token=token, quote_depth=quote_depth, depth=0)
                first_block = False
                list_line_context = None
                continue
            if token_type == "inline":
                self._append_line_prefix(quote_depth=quote_depth, list_line_context=list_line_context)
                _append_inline(token=token, writer=self._writer)
                self._index += 1
                first_block = False
                list_line_context = None
                continue
            content: str = getattr(token, "content", "")
            if content:
                _LOGGER.warning(
                    "markdown_compiler_unhandled_leaf",
                    extra={"token_type": token_type, "content_length": len(content)},
                )
                self._append_line_prefix(quote_depth=quote_depth, list_line_context=list_line_context)
                self._writer.append_text(text=content)
                first_block = False
                list_line_context = None
            self._index += 1

    def _append_container_separator(
        self, *, quote_depth: int, list_line_context: Optional[_ListLineContext]
    ) -> None:
        """Separate top-level blocks while keeping continuous lists and quotes line-oriented."""
        if quote_depth or list_line_context is not None:
            self._writer.append_newline_if_needed()
            return
        self._writer.append_block_separator_if_needed()

    def _compile_leaf_block(
        self, *, token: object, quote_depth: int, list_line_context: Optional[_ListLineContext]
    ) -> None:
        """Compile one paragraph, heading, code, rule, or literal HTML block."""
        token_type: str = getattr(token, "type", "")
        self._append_line_prefix(quote_depth=quote_depth, list_line_context=list_line_context)
        if token_type in {"paragraph_open", "heading_open"}:
            inline = self._tokens[self._index + 1] if self._index + 1 < len(self._tokens) else token
            start: int = self._writer.length
            _append_inline(token=inline, writer=self._writer)
            if token_type == "heading_open":
                self._writer.add_span(start=start, end=self._writer.length, role="markdown-heading")
            self._index += 3
            return
        if token_type in {"fence", "code_block"}:
            _append_code_block(token=token, writer=self._writer)
            self._index += 1
            return
        if token_type == "hr":
            self._writer.append_styled_text(text="─", role="markdown-muted")
            self._index += 1
            return
        self._writer.append_text(text=getattr(token, "content", ""))
        self._index += 1

    def _compile_list(self, *, token: object, quote_depth: int, depth: int) -> None:
        """Compile a list using AST start metadata and compiler-owned markers."""
        ordered: bool = getattr(token, "type", "") == "ordered_list_open"
        attrs: object = getattr(token, "attrs", {}) or {}
        start_value: str | int = attrs.get("start", 1) if isinstance(attrs, dict) else 1
        ordinal: int = int(start_value) if str(start_value).isdigit() else 1
        close_type: str = "ordered_list_close" if ordered else "bullet_list_close"
        self._index += 1
        while (
            self._index < len(self._tokens) and getattr(self._tokens[self._index], "type", "") != close_type
        ):
            if getattr(self._tokens[self._index], "type", "") != "list_item_open":
                self._index += 1
                continue
            prefix: str = f"{ordinal}. " if ordered else "• "
            self._index += 1
            self._compile_list_item(quote_depth=quote_depth, depth=depth, marker=prefix)
            if (
                self._index < len(self._tokens)
                and getattr(self._tokens[self._index], "type", "") != close_type
            ):
                self._writer.append_newline_if_needed()
            ordinal += 1
        if self._index < len(self._tokens):
            self._index += 1

    def _compile_list_item(self, *, quote_depth: int, depth: int, marker: str) -> None:
        """Compile one list item and preserve nested blocks as new indented lines."""
        self._compile_list_item_content(quote_depth=quote_depth, depth=depth, marker=marker)

    def _compile_list_item_content(self, *, quote_depth: int, depth: int, marker: str) -> None:
        """Compile a list item's direct blocks and nested lists without a separator."""
        first_block: bool = True
        while self._index < len(self._tokens):
            token = self._tokens[self._index]
            token_type: str = getattr(token, "type", "")
            if token_type == "list_item_close":
                self._index += 1
                return
            if token_type in {"bullet_list_open", "ordered_list_open"}:
                self._writer.append_newline_if_needed()
                self._compile_list(token=token, quote_depth=quote_depth, depth=depth + 1)
                first_block = False
                continue
            if token_type == "blockquote_open":
                self._writer.append_newline_if_needed()
                self._index += 1
                self._compile_until(
                    close_type="blockquote_close",
                    quote_depth=quote_depth + 1,
                    list_line_context=_ListLineContext(depth=depth + 1),
                )
                first_block = False
                continue
            if token_type in {"paragraph_open", "heading_open", "fence", "code_block", "hr", "html_block"}:
                if not first_block:
                    self._writer.append_newline_if_needed()
                self._compile_leaf_block(
                    token=token,
                    quote_depth=quote_depth,
                    list_line_context=_ListLineContext(
                        depth=depth if first_block else depth + 1, marker=marker if first_block else None
                    ),
                )
                first_block = False
                continue
            self._index += 1

    def _append_line_prefix(self, *, quote_depth: int, list_line_context: Optional[_ListLineContext]) -> None:
        """Write AST-depth indentation, quote, and optional list marker before a visible line."""
        if list_line_context is not None:
            self._writer.append_text(text=list_line_context.indentation)
        if quote_depth:
            self._writer.append_prefix(text="│ " * quote_depth, role="markdown-quote")
        if list_line_context is not None and list_line_context.marker is not None:
            self._writer.append_prefix(text=list_line_context.marker.rstrip(), role="markdown-muted")
            self._writer.append_text(text=" ")

    def _trim_terminal_newlines(self) -> None:
        """Remove compiler-only terminal separators without modifying source fallback paths."""
        self._writer.trim_terminal_newlines()


def _append_inline(*, token: object, writer: _VisibleBufferWriter) -> None:
    """Append inline AST children while hiding Markdown control syntax."""
    children: list[object] = getattr(token, "children", None) or []
    stack: list[tuple[str, int, Optional[str], int]] = []
    pending_spans: list[tuple[int, int, int, str]] = []
    for child_index, child in enumerate(children):
        child_type: str = getattr(child, "type", "")
        if child_type == "text":
            writer.append_text(text=getattr(child, "content", ""))
        elif child_type in {"softbreak", "hardbreak"}:
            writer.append_text(text="\n")
        elif child_type == "code_inline":
            writer.append_styled_text(text=getattr(child, "content", ""), role="markdown-inline-code")
        elif child_type in {"em_open", "strong_open", "link_open", "s_open"}:
            role: str = {
                "em_open": "markdown-emphasis",
                "strong_open": "markdown-strong",
                "link_open": "markdown-link",
                "s_open": "markdown-emphasis",
            }[child_type]
            attrs: object = getattr(child, "attrs", {}) or {}
            href: Optional[str] = attrs.get("href") if isinstance(attrs, dict) else None
            stack.append((role, writer.length, href, child_index))
        elif child_type in {"em_close", "strong_close", "link_close", "s_close"}:
            if stack:
                role, start, _href, open_index = stack.pop()
                pending_spans.append((open_index, start, writer.length, role))
        elif child_type == "image":
            writer.append_styled_text(text=getattr(child, "content", ""), role="markdown-link")
        else:
            content: str = getattr(child, "content", "")
            if content:
                _LOGGER.warning(
                    "markdown_compiler_unhandled_leaf",
                    extra={"token_type": child_type, "content_length": len(content)},
                )
                writer.append_text(text=content)
    ordered_inline_spans: list[tuple[int, int, int, str]] = sorted(pending_spans, key=lambda span: span[0])
    writer._spans.extend(Span(start, end, role) for _open_index, start, end, role in ordered_inline_spans)
    writer._spans.sort(key=lambda span: (span.start, -(span.end - span.start)))


def _append_code_block(*, token: object, writer: _VisibleBufferWriter) -> None:
    """Append fence or indented code and safe Pygments spans over visible code only."""
    emitted_code: str = getattr(token, "content", "").removesuffix("\n")
    start, end = writer.append_styled_text(text=emitted_code, role="markdown-code")
    if getattr(token, "type", "") != "fence":
        return
    info: str = getattr(token, "info", "")
    if _is_diff_fence_info(info=info):
        _append_diff_line_spans(code=emitted_code, start=start, writer=writer)
    _append_code_token_spans(code=emitted_code, info=info, start=start, end=end, writer=writer)


def _append_code_token_spans(
    *, code: str, info: str, start: int, end: int, writer: _VisibleBufferWriter
) -> None:
    """Add Pygments spans only if exact emitted-code reconstruction succeeds."""
    lexer: Optional[Lexer] = _resolve_supported_lexer(info=info)
    if lexer is None:
        return
    try:
        token_values: list[tuple[Token, str]] = list(lex(code, lexer))
    except Exception:
        return
    reconstructed: str = "".join(value for _, value in token_values)
    if reconstructed == f"{code}\n":
        token_values[-1] = (token_values[-1][0], token_values[-1][1].removesuffix("\n"))
        reconstructed = "".join(value for _, value in token_values)
    if reconstructed != code:
        return
    offset: int = start
    for token_type, value in token_values:
        next_offset: int = offset + len(value)
        if value:
            writer.add_span(start=offset, end=next_offset, role=_role_for_token(token_type=token_type))
        offset = next_offset
    if offset != end:
        _LOGGER.warning("markdown_compilation_invariant_failed", extra={"raw_length": len(code)})


def _is_diff_fence_info(*, info: str) -> bool:
    """Return whether complete trimmed fence info selects diff line roles."""
    return info.strip().lower() in _DIFF_LEXER_NAMES


def _append_diff_line_spans(*, code: str, start: int, writer: _VisibleBufferWriter) -> None:
    """Add line-level diff roles without modifying the emitted visible code text."""
    offset: int = start
    for line in code.splitlines(keepends=True):
        line_end: int = offset + len(line.rstrip("\n"))
        writer.add_span(start=offset, end=line_end, role=_role_for_diff_line(line=line))
        offset += len(line)
    if code and not code.endswith("\n"):
        return


def _role_for_diff_line(*, line: str) -> str:
    """Map one exact visible diff line to its semantic presentation role."""
    if line.startswith(("+++", "---")):
        return "markdown-code-diff-file"
    if line.startswith("@@"):
        return "markdown-code-diff-hunk"
    if line.startswith("+"):
        return "markdown-code-diff-added"
    if line.startswith("-"):
        return "markdown-code-diff-removed"
    return "markdown-code"


def _resolve_supported_lexer(*, info: str) -> Optional[Lexer]:
    """Resolve only exact approved case-insensitive fence-info aliases."""
    lexer_name: Optional[str] = _SUPPORTED_LEXER_ALIASES.get(info.strip().lower())
    if lexer_name is None:
        return None
    try:
        return get_lexer_by_name(lexer_name)
    except Exception:
        return None


def _role_for_token(*, token_type: Token) -> str:
    """Map a Pygments token category to a theme semantic role."""
    if token_type in Comment:
        return "markdown-code-comment"
    if token_type in Keyword:
        return "markdown-code-keyword"
    if token_type in String or token_type in Literal.String:
        return "markdown-code-string"
    if token_type in Number or token_type in Literal.Number:
        return "markdown-code-number"
    if token_type in Name:
        return "markdown-code-name"
    return "markdown-code-punctuation"


def _contains_table_token(*, tokens: list[MarkdownToken]) -> bool:
    """Return whether parsing produced GFM table structure that needs literal fallback."""
    return any(getattr(token, "type", "").startswith("table_") for token in tokens)


def _plain_visible_fallback(*, raw_markdown: str) -> MarkdownContentDAO:
    """Return the recoverable raw-as-visible fallback without presentation spans."""
    return MarkdownContentDAO(raw_markdown=raw_markdown, visible_text=raw_markdown, spans=())


def _resolve_semantic_spans(*, spans: tuple[Span, ...], theme_variables: dict[str, str]) -> tuple[Span, ...]:
    """Resolve pure compiler roles at a mounted body rendering boundary."""
    return tuple(
        Span(span.start, span.end, Style.parse(f"${span.style}", variables=theme_variables)) for span in spans
    )
