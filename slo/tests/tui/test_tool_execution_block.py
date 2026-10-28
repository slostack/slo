"""Tests for expandable tool execution blocks."""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.event_renderer import format_tool_call_headline
from src.tui.widgets.tool_execution_block import ToolExecutionBlock


class TestToolExecutionFormatting:
    """Visible formatting guarantees for tool headlines."""

    def test_preparing_state_returns_empty_headline(self) -> None:
        """Name-unknown tool metadata returns empty string to suppress display."""
        headline: str = format_tool_call_headline(name=None, tool_input={})

        assert headline == ""


class TestToolExecutionBlock:
    """Collapsed and expanded tool execution rendering."""

    def test_hint_renders_when_block_has_expandable_details(self) -> None:
        """Parsed tool args expose the Ctrl+O affordance in collapsed mode."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="read",
        )

        block.update_tool_call(tool_name="read", tool_input={"path": "README.md"})

        assert block.is_expandable is True
        assert "Ctrl+O" in str(block._hint.content)

    def test_toggle_expanded_reveals_arguments_and_output(self) -> None:
        """Expanded mode reveals hidden argument and output detail."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="read",
        )
        block.update_tool_call(tool_name="read", tool_input={"path": "README.md"})
        block.update_result(tool_name="read", output="line one\nline two")

        block.toggle_expanded()

        expanded_text: str = str(block._expanded_body.content)
        assert '"path": "README.md"' in expanded_text
        assert "line one" in expanded_text

    def test_tool_result_with_regex_renders_literally(self) -> None:
        """A grep-style regex result keeps its ``[...]`` verbatim, not as markup.

        The raw output carries the brackets in the expanded body; the collapsed
        result line is only a summary count, so the literal check targets the
        expanded output surface.
        """
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="grep",
        )

        block.update_result(tool_name="grep", output="matches: /[a-z]+/  found 12")
        block.toggle_expanded()

        expanded_text: str = str(block._expanded_body.content)
        assert "/[a-z]+/" in expanded_text

    def test_expanded_body_with_json_array_renders_literally(self) -> None:
        """Expanded args containing a JSON array keep the brackets verbatim."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="write",
        )
        block.update_tool_call(tool_name="write", tool_input={"paths": ["a", "b"]})

        block.toggle_expanded()

        expanded_text: str = str(block._expanded_body.content)
        assert '"a"' in expanded_text
        assert '"b"' in expanded_text
        assert "[" in expanded_text and "]" in expanded_text

    def test_tool_block_uses_pending_fill_by_default(self) -> None:
        """A not-yet-terminal tool block paints the pending token fill (spec 72.a.5)."""
        block_rule: str = ToolExecutionBlock.DEFAULT_CSS.split("ToolExecutionBlock {")[1].split("}")[0]
        assert "background: $tool-pending-bg;" in block_rule

    def test_widget_css_uses_transcript_output_pad(self) -> None:
        """The widget declares the uniform ``TRANSCRIPT_OUTPUT_PAD`` convention."""
        block_rule: str = ToolExecutionBlock.DEFAULT_CSS.split("ToolExecutionBlock {")[1].split("}")[0]
        assert "padding: 0 1;" in block_rule

    def test_mark_incomplete_renders_highlighted_note_and_clears_output(self) -> None:
        """A tool call with no recorded result shows a highlighted incomplete note."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="bash",
        )
        block.update_tool_call(tool_name="bash", tool_input={"command": "x"})

        block.mark_incomplete()

        result_text: str = str(block._result_line.content)
        assert "may not have completed" in result_text
        assert block.result_output is None
        assert block._result_line.has_class("tool-call-incomplete")

    @pytest.mark.asyncio
    async def test_ctrl_o_toggles_active_expandable_tool_block(self) -> None:
        """The app-level hotkey toggles the most recent tool block."""
        session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
            workdir=Path(".").resolve(),
            session_id=str(uuid4()),
        )
        app: SloTUI = SloTUI(session=session)

        async with app.run_test() as pilot:
            await pilot.pause()
            block: ToolExecutionBlock = await app.query_one(ChatTranscript).mount_tool_execution_block(
                tool_call_id="call_1",
                tool_name="read",
            )
            block.update_tool_call(tool_name="read", tool_input={"path": "README.md"})
            block.update_result(tool_name="read", output="body")
            await pilot.pause()

            assert "arguments:" not in str(block._expanded_body.content)

            await pilot.press("ctrl+o")
            await pilot.pause()

            assert "arguments:" in str(block._expanded_body.content)


class TestToolExecutionBlockTerminalStateClasses:
    """CSS-state hooks ``-done`` / ``-error`` at terminal transitions (spec 72.a.5)."""

    def test_fresh_block_has_neither_done_nor_error_class(self) -> None:
        """A pending tool block carries no terminal-state class."""
        block: ToolExecutionBlock = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")

        assert not block.has_class("-done")
        assert not block.has_class("-error")

    def test_update_result_adds_done_class(self) -> None:
        """A recorded result selects the completed visual state."""
        block: ToolExecutionBlock = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")

        block.update_result(tool_name="bash", output="file.txt")

        assert block.has_class("-done")
        assert not block.has_class("-error")

    def test_update_result_clears_pre_existing_error_class(self) -> None:
        """A late result removes the error hook left by an earlier incomplete mark."""
        block: ToolExecutionBlock = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        block.mark_incomplete()
        assert block.has_class("-error")

        block.update_result(tool_name="bash", output="file.txt")

        assert block.has_class("-done")
        assert not block.has_class("-error")

    def test_mark_incomplete_adds_error_class_and_clears_done(self) -> None:
        """A terminal no-result call selects the error visual state."""
        block: ToolExecutionBlock = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        block.update_result(tool_name="bash", output="partial")
        assert block.has_class("-done")

        block.mark_incomplete()

        assert block.has_class("-error")
        assert not block.has_class("-done")
        assert block.is_incomplete is True
        assert block.result_output is None

    def test_active_class_coexists_with_terminal_state_class(self) -> None:
        """``-active`` remains orthogonal: it survives alongside ``-done``/``-error``."""
        block: ToolExecutionBlock = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        block.set_active(active=True)

        block.update_result(tool_name="bash", output="file.txt")

        assert block.has_class("-active")
        assert block.has_class("-done")

    def test_css_paints_pending_done_and_error_token_selectors(self) -> None:
        """The stylesheet maps each lifecycle class to its canonical token fill."""
        done_rule: str = ToolExecutionBlock.DEFAULT_CSS.split("ToolExecutionBlock.-done {")[1].split("}")[0]
        error_rule: str = ToolExecutionBlock.DEFAULT_CSS.split("ToolExecutionBlock.-error {")[1].split("}")[0]

        assert "background: $tool-success-bg;" in done_rule
        assert "background: $tool-error-bg;" in error_rule


class TestToolExecutionBlockGlobalExpand:
    """Global expand/collapse behaviour for ``ToolExecutionBlock`` (sub-spec 42.a.12)."""

    def test_natural_default_starts_collapsed(self) -> None:
        """A tool block is compact by default."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")

        assert block._expanded is False

    def test_force_expanded_true_starts_expanded(self) -> None:
        """Mounting under expand-all starts expanded."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash", force_expanded=True)

        assert block._expanded is True


class TestToolExecutionBlockCopyableText:
    """``get_copyable_text`` protocol for clipboard copy (spec 56)."""

    def test_includes_tool_name_input_and_result(self) -> None:
        """``get_copyable_text`` includes the tool name, serialized input, and result."""
        block = ToolExecutionBlock(tool_call_id="tc1", tool_name="bash")
        block._tool_input = {"command": "ls"}
        block._result_output = "file.txt"

        text = block.get_copyable_text()

        assert "bash" in text
        assert "ls" in text
        assert "file.txt" in text

    def test_omits_result_line_when_result_absent(self) -> None:
        """``get_copyable_text`` omits the result section when output is not yet populated."""
        block = ToolExecutionBlock(tool_call_id="tc1", tool_name="read")

        text = block.get_copyable_text()

        assert "result:" not in text

    def test_omits_input_section_when_args_empty(self) -> None:
        """``get_copyable_text`` omits the input section when no args are present."""
        block = ToolExecutionBlock(tool_call_id="tc1", tool_name="read")
        block._result_output = "content"

        text = block.get_copyable_text()

        assert "input:" not in text
        assert "content" in text

    def test_tool_name_always_present(self) -> None:
        """``get_copyable_text`` always includes the tool name as the first line."""
        block = ToolExecutionBlock(tool_call_id="tc1", tool_name="grep")

        text = block.get_copyable_text()

        assert text.startswith("tool: grep")

    def test_set_expanded_noop_when_not_expandable(self) -> None:
        """A block with no hidden detail ignores set_expanded."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")

        block.set_expanded(expanded=True)

        assert block._expanded is False

    def test_set_expanded_reveals_detail_when_expandable(self) -> None:
        """With args and output, set_expanded reveals the detail body."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        block.update_tool_call(tool_input={"command": "ls"})
        block.update_result(tool_name="bash", output="file1")

        block.set_expanded(expanded=True)
        assert block._expanded_body_text() != ""

        block.set_expanded(expanded=False)
        assert block._expanded_body_text() == ""


class TestToolExecutionBlockRefreshGuard:
    """_refresh skips redundant Static.update when content is unchanged (spec 59, Bug #3c)."""

    def test_repeated_update_with_same_args_is_noop(self) -> None:
        """A second update_tool_call with identical args keeps the same snapshot."""
        block = ToolExecutionBlock(tool_call_id="t1", tool_name="grep")
        block.update_tool_call(tool_name="grep", tool_input={"pattern": "x"})
        first = block._last_rendered_snapshot
        block.update_tool_call(tool_name="grep", tool_input={"pattern": "x"})
        assert block._last_rendered_snapshot == first

    def test_changed_args_updates_snapshot(self) -> None:
        """Different tool args result in an updated snapshot."""
        block = ToolExecutionBlock(tool_call_id="t1", tool_name="grep")
        block.update_tool_call(tool_name="grep", tool_input={"pattern": "x"})
        first = block._last_rendered_snapshot
        block.update_tool_call(tool_name="grep", tool_input={"pattern": "y"})
        assert block._last_rendered_snapshot != first


class TestToolExecutionBlockIsIncomplete:
    """is_incomplete accessor and mark_incomplete terminal semantics (spec 59, Phase 1c)."""

    def test_is_incomplete_false_by_default(self) -> None:
        """A fresh tool block is not marked incomplete."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        assert block.is_incomplete is False

    def test_mark_incomplete_sets_is_incomplete_true(self) -> None:
        """Calling mark_incomplete flips is_incomplete to True."""
        block = ToolExecutionBlock(tool_call_id="tc", tool_name="bash")
        block.mark_incomplete()
        assert block.is_incomplete is True
