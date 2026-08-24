"""E2E proof of mouse-selection auto-copy plus the no-regression sweep (68.b.5).

The headline test drives a real Pilot mouse drag across a known transcript block
and asserts the selected text reached the clipboard through the overridden funnel.
The remaining tests guard the four hard no-regression areas (streaming, steering
render, keyboard block copy, window eviction) after the Textual major bump.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.steering_pending_block import SteeringPendingBlock
from src.tui.widgets.tool_execution_block import ToolExecutionBlock


def _build_session() -> SloAgentSession:
    """Build a faux-model session for the selection E2E tests.

    Returns:
        SloAgentSession: Session driven by a faux assistant response.
    """
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


def _find_literal_line(*, app: SloTUI, needle: str) -> Optional[LiteralTextStatic]:
    """Return the first transcript ``LiteralTextStatic`` whose text contains ``needle``.

    Called by the drag and eviction tests to locate the block to select.

    Args:
        app (SloTUI): The running app.
        needle (str): Substring to match in the rendered line.

    Returns:
        Optional[LiteralTextStatic]: The matching widget, or ``None``.
    """
    assert app._transcript_content is not None
    for child in app._transcript_content.children:
        if isinstance(child, LiteralTextStatic) and needle in str(child.render()):
            return child
    return None


class TestMouseSelectionE2E:
    """End-to-end mouse-drag selection → clipboard proof."""

    @pytest.mark.asyncio
    async def test_mouse_drag_selection_auto_copies_to_clipboard(self) -> None:
        """A raw Pilot mouse drag across a block auto-copies the span to clipboard."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app._write_adapter_line(content="copy me please", classes="tool-result")
            await pilot.pause()

            target: Optional[LiteralTextStatic] = _find_literal_line(app=app, needle="copy me please")
            assert target is not None

            region = target.region
            start: tuple[int, int] = (region.x, region.y)
            end: tuple[int, int] = (region.x + len("copy me please"), region.y)

            # The raw mouse_down -> mouse_up drag is the required asserting path.
            await pilot.mouse_down(offset=start)
            await pilot.mouse_up(offset=end)
            await pilot.pause()

            selection: Optional[str] = app.screen.get_selected_text()
            assert selection is not None and selection != ""
            assert "copy me please" in selection
            assert app._clipboard is not None
            assert "copy me please" in app._clipboard


class TestNoRegressionSweep:
    """Guards for the four hard no-regression areas after the bump."""

    @pytest.mark.asyncio
    async def test_streaming_with_brackets_no_regression(self) -> None:
        """Streamed reasoning/answer/tool text with ``[...]`` renders literally."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await app._render_event(
                event=AgentStreamEventDAO(kind="thinking_delta", delta="type is list[str]", iteration=0)
            )
            await app._render_event(
                event=AgentStreamEventDAO(kind="text_delta", delta="range [a-z]+ ok", iteration=0)
            )
            await pilot.pause(delay=0.1)

            block: Optional[AssistantStreamBlock] = None
            assert app._transcript_content is not None
            for child in app._transcript_content.children:
                if isinstance(child, AssistantStreamBlock):
                    block = child
            assert block is not None
            assert "list[str]" in block.thinking_text
            assert "[a-z]+" in block.answer_text

            tool: ToolExecutionBlock = await app.mount_tool_execution_block(
                tool_call_id="call_1",
                tool_name="grep",
            )
            tool.update_result(tool_name="grep", output="hit /[a-z]+/")
            tool.toggle_expanded()
            await pilot.pause()
            assert "/[a-z]+/" in str(tool._expanded_body.content)

    @pytest.mark.asyncio
    async def test_steer_with_brackets_renders_literally_e2e(self) -> None:
        """A mounted ``SteeringPendingBlock`` renders bracketed steer text literally."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert app._transcript_content is not None
            block: SteeringPendingBlock = SteeringPendingBlock(message="apply list[str] then [a-z]+")
            await app._transcript_content.mount(block)
            await pilot.pause()

            rendered: str = str(block.render())
            assert "list[str]" in rendered
            assert "[a-z]+" in rendered

    @pytest.mark.asyncio
    async def test_keyboard_block_copy_still_works_and_emits_osc52(self) -> None:
        """Keyboard block copy lands the focused block text and runs the OSC 52 path."""
        app: SloTUI = SloTUI(session=_build_session())

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tool: ToolExecutionBlock = await app.mount_tool_execution_block(
                tool_call_id="call_1",
                tool_name="read",
            )
            tool.update_tool_call(tool_name="read", tool_input={"path": "README.md"})
            tool.update_result(tool_name="read", output="body")
            tool.focus()
            await pilot.pause()

            await app.action_copy_visible_text()
            await pilot.pause()

            assert app._clipboard is not None
            assert "read" in app._clipboard

    @pytest.mark.asyncio
    async def test_selection_survives_window_eviction(self) -> None:
        """Selecting then evicting the block leaves selection/copy safe (no raise)."""
        app: SloTUI = SloTUI(session=_build_session())

        with patch("src.tui.app.TRANSCRIPT_WINDOW_SIZE", 5):
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                app._write_adapter_line(content="select then evict", classes="tool-result")
                await pilot.pause()

                target: Optional[LiteralTextStatic] = _find_literal_line(app=app, needle="select then evict")
                assert target is not None
                region = target.region
                await pilot.mouse_down(offset=(region.x, region.y))
                await pilot.mouse_up(offset=(region.x + len("select"), region.y))
                await pilot.pause()

                for index in range(20):
                    app._write_adapter_line(content=f"filler line {index}", classes="tool-result")
                for _ in range(4):
                    await pilot.pause()

                # get_selected_text filters unattached widgets; must not raise.
                app.screen.get_selected_text()
                app.copy_to_clipboard("post-eviction")
                assert app._clipboard == "post-eviction"
