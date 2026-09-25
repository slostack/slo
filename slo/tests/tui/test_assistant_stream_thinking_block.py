"""Tests for thinking streaming and dual raw/visible Markdown buffers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock


def _build_session() -> SloAgentSession:
    """Build a deterministic session for mounted thinking-stream tests."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestAssistantStreamThinkingBlock:
    """Thinking source stabilization and compiler-visible rendering."""

    def test_stabilizes_raw_once_then_compiles_visible_markdown(self) -> None:
        """Thinking raw-copy returns stripped/stabilized Markdown while normal copy is visible."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="  *plan first*  ")
        assert block.thinking_text == "**plan first**"
        assert block.get_raw_markdown_for_copy() == "**plan first**"
        assert block.get_copyable_text() == "plan first"

    def test_stabilizes_replacement_before_any_render_flush(self) -> None:
        """Raw-copy cannot return unstripped provider content before the render timer fires."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="  *plan*  ")
        assert block.get_raw_markdown_for_copy() == "**plan**"

    def test_visible_selection_uses_compiled_thinking_buffer(self) -> None:
        """A bounded native range extracts visible text rather than source delimiters."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="# alpha bravo")
        selected: Optional[tuple[str, str]] = block._body.get_selection(
            Selection(start=Offset(x=6, y=0), end=Offset(x=11, y=0))
        )
        assert selected == ("bravo", "\n")
        assert block._body.get_selection(SELECT_ALL) == ("alpha bravo", "\n")

    def test_contentless_and_sealed_lifecycle_semantics_are_preserved(self) -> None:
        """A sealed segment rejects later stream/replay repairs as before the renderer change."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="before")
        block.seal()
        block.set_thinking(content="after")
        block.append_thinking(delta="after")
        assert block.finalized is True
        assert block.thinking_text == "before"

    def test_expansion_preserves_compiled_buffer(self) -> None:
        """Collapse only changes visibility and never changes raw or visible text ownership."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="# hello")
        block.set_expanded(expanded=False)
        assert block._body.display is False
        block.set_expanded(expanded=True)
        assert block._body.display is True
        assert block.get_copyable_text() == "hello"

    def test_spacing_merge_decisions_remain_intact(self) -> None:
        """Fragment repair stays outside the compiler boundary."""
        block = AssistantStreamThinkingBlock()
        for delta in ["I", "need", "to", "plan", ",", "not", "re", "-", "plan"]:
            block.append_thinking(delta=delta)
        assert block.thinking_text == "I need to plan, not re-plan"

    @pytest.mark.asyncio
    async def test_mounted_seal_flushes_last_dirty_thinking(self) -> None:
        """Mounted finalization still flushes its last raw value and stops the timer."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            block = AssistantStreamThinkingBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            block._thinking_text = "# tail"
            block._dirty = True
            block.seal()
            await pilot.pause()
            assert block._last_rendered == "# tail"
            assert block.get_copyable_text() == "tail"
            assert block._flush_timer is None
