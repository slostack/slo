"""Pure golden tests for compiler-owned visible Markdown transcript buffers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.tui.widgets.markdown_content_compiler import MarkdownContentCompiler


def _roles(*, source: str) -> list[str]:
    """Return compiler semantic role strings for a source value."""
    roles: list[str] = []
    for span in MarkdownContentCompiler.compile(raw_markdown=source).spans:
        assert isinstance(span.style, str)
        roles.append(span.style)
    return roles


class TestMarkdownContentCompiler:
    """AST-to-visible-text compiler contract."""

    def test_compiles_the_normative_nested_markdown_example(self) -> None:
        """Headings, lists, links, quotes, and fences hide source-only chrome."""
        source: str = """# Plan

- Read **AGENTS.md**
  1. Find `MarkdownContentCompiler`

> Keep [the link](https://example.test) readable.

```python
value = 1
```"""

        compiled = MarkdownContentCompiler.compile(raw_markdown=source)

        assert compiled.visible_text == (
            "Plan\n\n• Read AGENTS.md\n  1. Find MarkdownContentCompiler\n\n"
            "│ Keep the link readable.\n\nvalue = 1"
        )
        assert "markdown-heading" in _roles(source=source)
        assert "markdown-strong" in _roles(source=source)
        assert "markdown-inline-code" in _roles(source=source)
        assert "markdown-link" in _roles(source=source)
        assert "markdown-quote" in _roles(source=source)
        assert "markdown-code" in _roles(source=source)

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("first\n\nsecond", "first\n\nsecond"),
            ("---", "─"),
            ("![alt text](https://image.test/p.png)", "alt text"),
            ("<span>literal</span>", "<span>literal</span>"),
            ("3. third\n4. fourth", "3. third\n4. fourth"),
        ],
    )
    def test_compiles_supported_block_and_inline_constructs(self, source: str, expected: str) -> None:
        """The bounded renderer has deterministic visible output for each construct."""
        assert MarkdownContentCompiler.compile(raw_markdown=source).visible_text == expected

    @pytest.mark.parametrize("source", ["", "  \n   \n"])
    def test_preserves_empty_and_whitespace_only_raw_source(self, source: str) -> None:
        """Zero-token inputs retain the source as their selectable fallback buffer."""
        compiled = MarkdownContentCompiler.compile(raw_markdown=source)
        assert compiled.raw_markdown == source
        assert compiled.visible_text == source
        assert compiled.spans == ()

    @pytest.mark.parametrize("language", ["python", "py", "bash", "sh", "shell", "json", "yaml", "yml"])
    def test_supported_fence_aliases_add_generic_and_token_roles(self, language: str) -> None:
        """Supported aliases tokenize only the already-emitted visible code text."""
        compiled = MarkdownContentCompiler.compile(raw_markdown=f"```{language}\nvalue = 1\n```")
        assert compiled.visible_text == "value = 1"
        assert compiled.spans[0].style == "markdown-code"
        assert len(compiled.spans) > 1

    @pytest.mark.parametrize(
        "source", ["```rust\nlet value = 1;\n```", "```python {.line-numbers}\nvalue = 1\n```"]
    )
    def test_unknown_or_attribute_bearing_fences_use_generic_code_only(self, source: str) -> None:
        """Fence labels are exact aliases rather than guessed language prefixes."""
        assert _roles(source=source) == ["markdown-code"]

    def test_parser_failure_falls_back_without_exposing_source_or_style_errors(self) -> None:
        """A parser exception leaves the raw source visible and unstyled."""
        with patch("src.tui.widgets.markdown_content_compiler.MarkdownIt.parse", side_effect=RuntimeError):
            compiled = MarkdownContentCompiler.compile(raw_markdown="**unavailable**")
        assert compiled.visible_text == "**unavailable**"
        assert compiled.spans == ()

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("- a\n  - b\n    - c", "• a\n  • b\n    • c"),
            ("- one\n\n  second para", "• one\n  second para"),
            ("- item\n  > quoted", "• item\n  │ quoted"),
            ("- item\n\n  ```python\n  x = 1\n  ```", "• item\n  x = 1"),
            ("> outer\n>> inner", "│ outer\n│ │ inner"),
        ],
    )
    def test_compiles_nested_list_and_quote_blocks_without_losing_structure(
        self, source: str, expected: str
    ) -> None:
        """Nested list contexts retain depth, continuations, code, and quote prefixes."""
        assert MarkdownContentCompiler.compile(raw_markdown=source).visible_text == expected

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("- parent\n   1. child", "• parent\n  1. child"),
            ("1. parent\n   - child", "1. parent\n  • child"),
            ("1. parent\n   1. child", "1. parent\n  1. child"),
            ("- one\n   1. two\n      - three", "• one\n  1. two\n    • three"),
        ],
    )
    def test_compiles_mixed_nested_lists_from_ast_depth(self, source: str, expected: str) -> None:
        """List indentation is two spaces per AST depth, regardless of marker width."""
        assert MarkdownContentCompiler.compile(raw_markdown=source).visible_text == expected

    def test_compiles_tables_without_corrupting_cell_boundaries(self) -> None:
        """Table syntax remains literal when the bounded renderer has no table layout."""
        source: str = "| a | b |\n|---|---|\n| 1 | 2 |"
        assert MarkdownContentCompiler.compile(raw_markdown=source).visible_text == source

    def test_compiles_strikethrough_without_dropping_its_text_or_style(self) -> None:
        """GFM strikethrough keeps its child text and receives a visible semantic style."""
        compiled = MarkdownContentCompiler.compile(raw_markdown="~~gone~~")
        assert compiled.visible_text == "gone"
        assert "markdown-emphasis" in _roles(source="~~gone~~")

    def test_logs_and_preserves_nonempty_unknown_leaf_content(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown non-empty leaves remain readable and emit only redacted diagnostics."""
        # The private AST seam is deliberately patched to cover an otherwise parser-specific token.
        from markdown_it.token import Token

        token = Token(type="unknown_leaf", tag="", nesting=0)
        token.content = "kept"
        with patch("src.tui.widgets.markdown_content_compiler.MarkdownIt.parse", return_value=[token]):
            compiled = MarkdownContentCompiler.compile(raw_markdown="source")
        assert compiled.visible_text == "kept"
        assert "markdown_compiler_unhandled_leaf" in caplog.text
        assert "source" not in caplog.text

    @pytest.mark.parametrize("failure", ["resolve", "lex", "reconstruct"])
    def test_keeps_generic_code_span_when_lexer_safety_check_fails(self, failure: str) -> None:
        """Each lexer safety failure leaves the compiler-emitted generic code intact."""
        source: str = "```python\nvalue = 1\n```"
        if failure == "resolve":
            with patch(
                "src.tui.widgets.markdown_content_compiler._resolve_supported_lexer", return_value=None
            ):
                compiled = MarkdownContentCompiler.compile(raw_markdown=source)
        elif failure == "lex":
            with patch("src.tui.widgets.markdown_content_compiler.lex", side_effect=RuntimeError):
                compiled = MarkdownContentCompiler.compile(raw_markdown=source)
        else:
            with patch("src.tui.widgets.markdown_content_compiler.lex", return_value=[(object(), "wrong")]):
                compiled = MarkdownContentCompiler.compile(raw_markdown=source)
        assert compiled.visible_text == "value = 1"
        assert [span.style for span in compiled.spans] == ["markdown-code"]

    def test_orders_outer_inline_spans_before_inner_overlapping_spans(self) -> None:
        """Nested semantic roles retain deterministic outer-before-inner insertion order."""
        compiled = MarkdownContentCompiler.compile(
            raw_markdown="**outer *inner `code`* [link](https://e.test)**"
        )

        role_ranges: list[tuple[str, int, int]] = [
            (str(span.style), span.start, span.end) for span in compiled.spans
        ]

        assert compiled.visible_text == "outer inner code link"
        assert role_ranges == [
            ("markdown-strong", 0, 21),
            ("markdown-emphasis", 6, 16),
            ("markdown-inline-code", 12, 16),
            ("markdown-link", 17, 21),
        ]

    @pytest.mark.parametrize(
        "source",
        ["*unclosed emphasis", "**unclosed strong", "[unclosed link](https://e.test"],
    )
    def test_retains_all_visible_text_when_inline_markdown_is_unbalanced(self, source: str) -> None:
        """Malformed inline delimiters remain readable without a parser crash or text loss."""
        compiled = MarkdownContentCompiler.compile(raw_markdown=source)

        assert compiled.visible_text
        assert "unclosed" in compiled.visible_text

    @pytest.mark.parametrize(
        "language",
        [
            "diff",
            "patch",
            "javascript",
            "js",
            "typescript",
            "ts",
            "tsx",
            "jsx",
            "toml",
            "ini",
            "xml",
            "html",
            "css",
            "sql",
            "dockerfile",
            "markdown",
            "md",
        ],
    )
    def test_extended_exact_fence_aliases_add_generic_and_token_roles(self, language: str) -> None:
        """Exact case-insensitive extended aliases tokenize only visible fenced code."""
        source: str = f"```{language.upper()}\nvalue = 1\n```"

        compiled = MarkdownContentCompiler.compile(raw_markdown=source)

        assert compiled.visible_text == "value = 1"
        assert compiled.spans[0].style == "markdown-code"
        assert len(compiled.spans) > 1

    def test_indented_code_keeps_generic_code_span_without_language_tokenization(self) -> None:
        """Indented code always remains visible with the generic fallback role."""
        compiled = MarkdownContentCompiler.compile(raw_markdown="    value = 1\n    next = 2\n")

        assert compiled.visible_text == "value = 1\nnext = 2"
        assert [span.style for span in compiled.spans] == ["markdown-code"]

    def test_diff_fence_adds_semantic_line_roles_over_exact_visible_code(self) -> None:
        """Diff line roles decorate compiler-emitted code without changing its text."""
        source: str = """```patch
--- a/old.py
+++ b/new.py
@@ -1 +1 @@
-old
+new
```"""

        compiled = MarkdownContentCompiler.compile(raw_markdown=source)
        spans: list[tuple[int, int, str]] = [
            (span.start, span.end, str(span.style)) for span in compiled.spans
        ]

        assert compiled.visible_text == "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new"
        assert (0, len("--- a/old.py"), "markdown-code-diff-file") in spans
        assert (len("--- a/old.py\n"), len("--- a/old.py\n+++ b/new.py"), "markdown-code-diff-file") in spans
        assert (
            len("--- a/old.py\n+++ b/new.py\n"),
            len("--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@"),
            "markdown-code-diff-hunk",
        ) in spans
        assert any(role == "markdown-code-diff-removed" for _start, _end, role in spans)
        assert any(role == "markdown-code-diff-added" for _start, _end, role in spans)
        assert all(0 <= start <= end <= len(compiled.visible_text) for start, end, _role in spans)

    @pytest.mark.parametrize(
        "source",
        [
            "```python {.line-numbers}\nvalue = 1\n```",
            "```diff --git\n+value\n```",
            "```unknown\nvalue = 1\n```",
            "```\nvalue = 1\n```",
        ],
    )
    def test_attribute_unknown_and_unlabeled_fences_keep_generic_code_only(self, source: str) -> None:
        """Only complete trimmed aliases may opt a fence into syntax tokenization."""
        assert _roles(source=source) == ["markdown-code"]

    def test_spans_are_pure_visible_role_ranges_without_an_offset_mapper(self) -> None:
        """Pure output is app-free and every span indexes only visible text."""
        compiled = MarkdownContentCompiler.compile(raw_markdown="# *visible*")
        allowed_roles: set[str] = {
            "markdown-heading",
            "markdown-muted",
            "markdown-quote",
            "markdown-emphasis",
            "markdown-strong",
            "markdown-inline-code",
            "markdown-code",
            "markdown-link",
            "markdown-code-keyword",
            "markdown-code-string",
            "markdown-code-comment",
            "markdown-code-number",
            "markdown-code-name",
            "markdown-code-punctuation",
            "markdown-code-diff-added",
            "markdown-code-diff-removed",
            "markdown-code-diff-hunk",
            "markdown-code-diff-file",
        }
        assert compiled.visible_text == "visible"
        assert all(isinstance(span.style, str) and span.style in allowed_roles for span in compiled.spans)
        assert all(0 <= span.start <= span.end <= len(compiled.visible_text) for span in compiled.spans)
        assert not hasattr(compiled, "visible_to_raw_offsets")
