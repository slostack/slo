"""Tests for answer streaming, finalization, and dual raw/visible buffers."""

from __future__ import annotations

from src.tui.components.chat_transcript.component import ChatTranscript
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from textual.content import Content
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock


def _build_session() -> SloAgentSession:
    """Build a deterministic session for mounted streaming tests."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestAssistantStreamBlock:
    """Answer body output and complete-copy behavior."""

    def test_answer_keeps_raw_accumulator_and_renders_visible_markdown(self) -> None:
        """Heading, emphasis, links, and fences compile into a separate visible buffer."""
        raw = "# Plan\n\nRead **AGENTS.md** and [guide](https://example.test).\n\n```python\nvalue = 1\n```"
        block = AssistantStreamBlock()
        block.append_text(delta=raw)
        assert block.answer_text == raw
        assert str(block._answer_body.content) == "Plan\n\nRead AGENTS.md and guide.\n\nvalue = 1"
        assert block.get_copyable_text() == "Plan\n\nRead AGENTS.md and guide.\n\nvalue = 1"
        assert block.get_raw_markdown_for_copy() == raw

    def test_visible_selection_is_bounded_to_compiled_text(self) -> None:
        """Selection extraction never attempts to map visible offsets back to raw Markdown."""
        block = AssistantStreamBlock()
        block.append_text(delta="# alpha bravo")
        selected: Optional[tuple[str, str]] = block._answer_body.get_selection(
            Selection(start=Offset(x=6, y=0), end=Offset(x=11, y=0))
        )
        assert selected == ("bravo", "\n")
        assert block._answer_body.get_selection(SELECT_ALL) == ("alpha bravo", "\n")

    def test_empty_finalization_hides_and_unselects_answer(self) -> None:
        """A terminal empty answer clears stale visible state while raw accumulator becomes empty."""
        block = AssistantStreamBlock()
        block.append_text(delta="partial")
        block.finalize(final_text="")
        assert block._answer_body.display is False
        assert block.get_copyable_text() == ""
        assert block.get_raw_markdown_for_copy() == ""

    def test_css_remains_bare_and_padded_without_card_copy_controls(self) -> None:
        """The compiler rewire preserves transcript visual ownership and no local copy UI."""
        assert "padding: 0 1;" in AssistantStreamBlock.DEFAULT_CSS
        assert "background: transparent;" in AssistantStreamBlock.DEFAULT_CSS
        children = list(AssistantStreamBlock().compose())
        assert len(children) == 2


class TestAssistantStreamBlockStreaming:
    """Existing answer stream coalescing/finalization decisions remain intact."""

    def test_unmounted_append_renders_synchronously(self) -> None:
        """Direct construction retains immediate rendering for existing callers."""
        block = AssistantStreamBlock()
        block.append_text(delta="Hello")
        assert block._last_rendered_answer == "Hello"
        assert block._answer_dirty is False

    def test_finalization_preserves_completed_raw_truth(self) -> None:
        """Final output replaces streamed raw truth before the final compiler render."""
        block = AssistantStreamBlock()
        block.append_text(delta="partial")
        block.finalize(final_text="# final")
        assert block.finalized is True
        assert block.answer_text == "# final"
        assert block.get_copyable_text() == "final"

    @pytest.mark.asyncio
    async def test_mounted_seal_flushes_last_dirty_answer(self) -> None:
        """Sealing still flushes pending raw answer content before its timer stops."""
        app = SloTUI(session=_build_session())
        async with app.run_test() as pilot:
            block = AssistantStreamBlock()
            assert app.query_one(ChatTranscript)._transcript_content is not None
            await app.query_one(ChatTranscript)._transcript_content.mount(block)
            block._answer_text = "# tail"
            block._answer_dirty = True
            block.seal()
            await pilot.pause()
            assert block._last_rendered_answer == "# tail"
            assert block.get_copyable_text() == "tail"
            assert block._flush_timer is None
