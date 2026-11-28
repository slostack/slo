"""Syntax highlighting for expanded tool-call arguments and output."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.content import Content, Span

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.tool_output_highlighter import (
    HIGHLIGHT_MAX_CHARS,
    code_spans,
    detect_output_language,
    language_for_path,
)


def _span_role(*, span: Span) -> str:
    """Return the semantic role name a highlighter span carries.

    Args:
        span (Span): Span produced by ``code_spans``.

    Returns:
        str: The role name; highlighter spans never carry resolved ``Style`` objects.
    """
    assert isinstance(span.style, str)
    return span.style


def _expanded_content(*, block: ToolExecutionBlock) -> Content:
    """Return the expanded body as the literal ``Content`` the block renders.

    Args:
        block (ToolExecutionBlock): Mounted tool block.

    Returns:
        Content: Expanded body content.
    """
    content = block._expanded_body.content
    assert isinstance(content, Content)
    return content


class TestLanguageDetection:
    """Language selection from tool name, arguments, and output shape."""

    @pytest.mark.parametrize(
        ("path", "language"),
        [
            ("src/app.py", "python"),
            ("web/App.TSX", "tsx"),
            ("config.yml", "yaml"),
            ("src/tui/app.tcss", "css"),
            ("deploy/Dockerfile", "dockerfile"),
            ("notes.txt", None),
            ("Makefile", None),
        ],
    )
    def test_read_language_follows_path(self, path: str, language: str | None) -> None:
        """``read`` output is highlighted by the file's extension or name."""
        assert language_for_path(path=path) == language
        assert detect_output_language(tool_name="read", tool_input={"path": path}, output="x") == language

    def test_write_output_is_plain(self) -> None:
        """``write`` returns a status line, never file content."""
        assert (
            detect_output_language(tool_name="write", tool_input={"path": "a.py"}, output="Wrote 3 bytes")
            is None
        )

    def test_grep_uses_location_highlighting(self) -> None:
        """``grep`` match lines get their ``path:line:`` prefix highlighted."""
        assert detect_output_language(tool_name="grep", tool_input={}, output="a.py:1:x") == "grep"

    @pytest.mark.parametrize(
        ("output", "language"),
        [
            ("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", "diff"),
            ('{"ok": true}', "json"),
            ("  [1, 2]", "json"),
            ("{not json", None),
            ("total 0\nREADME.md", None),
        ],
    )
    def test_untyped_output_is_sniffed(self, output: str, language: str | None) -> None:
        """Other tools (e.g. ``bash``) highlight only recognisable diffs or JSON."""
        assert detect_output_language(tool_name="bash", tool_input={}, output=output) == language


class TestCodeSpans:
    """Role spans produced over exact visible text."""

    def test_python_spans_cover_keywords_and_strings(self) -> None:
        """Python source yields keyword and string roles at the right offsets."""
        text: str = 'def f():\n    return "hi"\n'
        spans = code_spans(text=text, language="python", offset=10)
        by_role: dict[str, list[str]] = {}
        for span in spans:
            by_role.setdefault(_span_role(span=span), []).append(text[span.start - 10 : span.end - 10])
        assert "def" in by_role["markdown-code-keyword"]
        assert '"hi"' in "".join(by_role["markdown-code-string"])

    def test_diff_lines_get_line_roles(self) -> None:
        """Diff output colours added/removed/hunk lines."""
        text: str = "@@ -1 +1 @@\n-old\n+new\n"
        roles: dict[str, str] = {
            text[s.start : s.end]: _span_role(span=s) for s in code_spans(text=text, language="diff")
        }
        assert roles["-old"] == "markdown-code-diff-removed"
        assert roles["+new"] == "markdown-code-diff-added"
        assert roles["@@ -1 +1 @@"] == "markdown-code-diff-hunk"

    def test_grep_prefix_spans(self) -> None:
        """Only well-formed ``path:line:`` prefixes are highlighted."""
        text: str = "src/a.py:12:  x = 1\nnot a match\nb.py:3:y\n"
        prefixes: list[str] = [text[s.start : s.end] for s in code_spans(text=text, language="grep")]
        assert prefixes == ["src/a.py:12:", "b.py:3:"]

    def test_plain_unknown_and_oversized_text_has_no_spans(self) -> None:
        """Unknown languages and huge outputs render plain."""
        assert code_spans(text="x = 1", language=None) == []
        assert code_spans(text="x = 1\n" * (HIGHLIGHT_MAX_CHARS // 6 + 1), language="python") == []


def _session() -> SloAgentSession:
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path.cwd(),
        session_id=str(uuid4()),
    )


async def _mounted_block(app: SloTUI) -> ToolExecutionBlock:
    block: ToolExecutionBlock = await app.query_one(ChatTranscriptComponent).mount_tool_execution_block(
        tool_call_id="call_1", tool_name="read"
    )
    block.update_tool_call(tool_name="read", tool_input={"path": "a.py"})
    block.set_expanded(expanded=True)
    return block


class TestToolExecutionBlockHighlighting:
    """Expanded tool bodies render highlighted, literal Content."""

    def test_unmounted_block_renders_plain_literal_text(self) -> None:
        """Before mount there is no theme, so the body stays plain but complete."""
        block = ToolExecutionBlock(tool_call_id="c", tool_name="read", force_expanded=True)
        block.update_tool_call(tool_name="read", tool_input={"path": "a.py"})
        block.update_result(tool_name="read", output="x = [a-z]\n")
        content = block._expanded_body.content
        assert isinstance(content, Content)
        assert "x = [a-z]" in str(content)
        assert content.spans == []

    @pytest.mark.asyncio
    async def test_mounted_read_of_python_file_is_highlighted(self) -> None:
        """A mounted, expanded ``read`` of a .py file carries keyword colours."""
        app = SloTUI(session=_session())
        async with app.run_test() as pilot:
            await pilot.pause()
            block = await _mounted_block(app)
            block.update_tool_call(tool_name="read", tool_input={"path": "a.py"})
            block.update_result(tool_name="read", output="import os  # [x]\n")
            await pilot.pause()

            content = block._expanded_body.content
            assert isinstance(content, Content)
            text: str = str(content)
            assert text == block._expanded_body_text()
            assert "import os  # [x]" in text
            highlighted: set[str] = {text[s.start : s.end] for s in content.spans}
            assert "import" in highlighted
            assert '"path"' in highlighted  # JSON argument key

    @pytest.mark.asyncio
    async def test_error_output_is_not_highlighted(self) -> None:
        """Failed calls keep their output plain."""
        app = SloTUI(session=_session())
        async with app.run_test() as pilot:
            await pilot.pause()
            block = await _mounted_block(app)
            block.update_tool_call(tool_name="read", tool_input={"path": "a.py"})
            block.update_result(tool_name="read", output="Error: file not found: a.py")
            await pilot.pause()

            content = _expanded_content(block=block)
            text: str = str(content)
            output_start: int = text.index("output:\n")
            assert all(span.end <= output_start for span in content.spans)

    @pytest.mark.asyncio
    async def test_theme_switch_rerenders_highlight_colours(self) -> None:
        """Switching themes re-resolves span styles against the new palette."""
        app = SloTUI(session=_session())
        async with app.run_test() as pilot:
            await pilot.pause()
            block = await _mounted_block(app)
            block.update_tool_call(tool_name="read", tool_input={"path": "a.py"})
            block.update_result(tool_name="read", output="import os\n")
            await pilot.pause()
            before = [repr(s.style) for s in _expanded_content(block=block).spans]

            app.theme = SLO_DEFAULT_THEME.name if app.theme == SLO_DARK_THEME.name else SLO_DARK_THEME.name
            await pilot.pause()
            after = [repr(s.style) for s in _expanded_content(block=block).spans]

            assert before and after and before != after
