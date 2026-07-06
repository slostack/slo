"""Tests for expandable tool execution blocks."""

from __future__ import annotations

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
        """Unknown generic tool metadata returns empty string to suppress display."""
        headline: str = format_tool_call_headline(name="tool", tool_input={})

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
        assert "Ctrl+O" in str(block._hint.renderable)

    def test_toggle_expanded_reveals_arguments_and_output(self) -> None:
        """Expanded mode reveals hidden argument and output detail."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="read",
        )
        block.update_tool_call(tool_name="read", tool_input={"path": "README.md"})
        block.update_result(tool_name="read", output="line one\nline two")

        block.toggle_expanded()

        expanded_text: str = str(block._expanded_body.renderable)
        assert '"path": "README.md"' in expanded_text
        assert "line one" in expanded_text

    def test_tool_block_exposes_shared_panel_rhythm_styling(self) -> None:
        """Tool blocks declare the same panel-like rhythm as other message widgets."""
        assert "background: $panel;" in ToolExecutionBlock.DEFAULT_CSS

    def test_mark_incomplete_renders_highlighted_note_and_clears_output(self) -> None:
        """A tool call with no recorded result shows a highlighted incomplete note."""
        block: ToolExecutionBlock = ToolExecutionBlock(
            tool_call_id="call_1",
            tool_name="bash",
        )
        block.update_tool_call(tool_name="bash", tool_input={"command": "x"})

        block.mark_incomplete()

        result_text: str = str(block._result_line.renderable)
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
            block: ToolExecutionBlock = await app.mount_tool_execution_block(
                tool_call_id="call_1",
                tool_name="read",
            )
            block.update_tool_call(tool_name="read", tool_input={"path": "README.md"})
            block.update_result(tool_name="read", output="body")
            await pilot.pause()

            assert "arguments:" not in str(block._expanded_body.renderable)

            await pilot.press("ctrl+o")
            await pilot.pause()

            assert "arguments:" in str(block._expanded_body.renderable)


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
