"""Direct tests for ``AssistantStreamBlock`` answer-only formatting (spec 72.a.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.markdown import Markdown
from rich.padding import Padding
from textual.selection import SELECT_ALL
from textual.widget import Widget
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from tests.tui._scroll_settle import pump_until


class TestAssistantStreamBlock:
    """Pi-style answer rendering details; thinking lives in its own widget."""

    def test_answer_renders_as_padded_markdown(self) -> None:
        """Assistant answer text uses vertical-only padding (spec 72.a.3)."""
        block = AssistantStreamBlock()

        block.append_text(delta="Hello world")

        assert block._answer_body.display is True
        assert isinstance(block._answer_body.content, Padding)
        assert isinstance(block._answer_body.content.renderable, Markdown)
        assert block._answer_body.content.renderable.markup == "Hello world"
        assert block._answer_body.content.top == 1
        assert block._answer_body.content.right == 0
        assert block._answer_body.content.bottom == 1
        assert block._answer_body.content.left == 0

    def test_widget_css_uses_transcript_output_pad(self) -> None:
        """The block declares the uniform ``TRANSCRIPT_OUTPUT_PAD`` convention."""
        block_rule: str = AssistantStreamBlock.DEFAULT_CSS.split("AssistantStreamBlock {")[1].split("}")[0]
        assert "padding: 0 1;" in block_rule

    def test_answer_escapes_angle_brackets_before_markdown_render(self) -> None:
        """Answer text escapes angle brackets that destabilize markdown rendering."""
        block = AssistantStreamBlock()

        block.append_text(delta="Path: <repo>/src/file.py")

        assert isinstance(block._answer_body.content, Padding)
        assert isinstance(block._answer_body.content.renderable, Markdown)
        assert block._answer_body.content.renderable.markup == r"Path: \<repo\>/src/file.py"

    def test_answer_surface_keeps_its_widget_class(self) -> None:
        """The answer surface keeps the distinct answer widget class for styling."""
        block = AssistantStreamBlock()

        assert "assistant-answer-body" in block._answer_body.classes

    def test_answer_block_and_body_paint_bare_canvas(self) -> None:
        """Answer block and body stay bare on the terminal canvas (spec 72.a.5)."""
        block_rule: str = AssistantStreamBlock.DEFAULT_CSS.split("AssistantStreamBlock {")[1].split("}")[0]
        body_rule: str = AssistantStreamBlock.DEFAULT_CSS.split(
            "AssistantStreamBlock .assistant-answer-body {"
        )[1].split("}")[0]

        assert "background: transparent;" in block_rule
        assert "background: transparent;" in body_rule
        assert "background: $panel;" not in AssistantStreamBlock.DEFAULT_CSS
        assert "background: $surface;" not in AssistantStreamBlock.DEFAULT_CSS

    def test_answer_headings_use_canonical_md_heading_token(self) -> None:
        """Assistant markdown headings use the warm ``$md-heading`` role (spec 72.a.5)."""
        heading_rule: str = AssistantStreamBlock.DEFAULT_CSS.split(
            "AssistantStreamBlock .assistant-answer-body Heading {"
        )[1].split("}")[0]

        assert "color: $md-heading;" in heading_rule

    def test_empty_surfaces_start_hidden(self) -> None:
        """Empty answer / terminal regions do not reserve blank layout rows."""
        block = AssistantStreamBlock()

        assert block._answer_body.display is False
        assert block._terminal_note.display is False

    def test_assistant_block_composes_no_focusable_card_control(self) -> None:
        """Verify the flattened assistant block has no focusable card control.

        A retired card-local copy control would reappear as an extra focusable
        composed child, so the composed-children list and their focusability
        are the behavioral guard that no card control remains (spec 72.a.3).

        WHO: The spec-72.a.3 regression suite calls this after constructing the
            answer block.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()

        children: list[Widget] = list(block.compose())

        assert children == [block._answer_body, block._terminal_note]
        assert all(not child.can_focus for child in children)
        assert block.can_focus is True

    def test_block_css_targets_only_answer_side_surfaces(self) -> None:
        """Verify the stylesheet styles only the answer-side surfaces.

        A retired copy header or control rule would reappear as an extra CSS
        selector, so the exact selector set is the behavioral guard that no
        card-control styling remains (spec 72.a.3).

        WHO: The spec-72.a.3 regression suite calls this against the class CSS.
        """
        selectors: set[str] = {
            line.strip().removesuffix("{").strip()
            for line in AssistantStreamBlock.DEFAULT_CSS.splitlines()
            if "{" in line
        }

        assert selectors == {
            "AssistantStreamBlock .sub-agent-label",
            "AssistantStreamBlock",
            "AssistantStreamBlock .assistant-answer-body",
            "AssistantStreamBlock .assistant-answer-body Heading",
            "AssistantStreamBlock .assistant-answer-body BulletList",
            "AssistantStreamBlock .assistant-answer-body OrderedList",
            "AssistantStreamBlock .assistant-answer-body BlockQuote",
            "AssistantStreamBlock .assistant-answer-body CodeBlock",
            "AssistantStreamBlock .assistant-terminal-warning",
        }


class TestAssistantStreamBlockAnswerOnly:
    """The answer block owns no thinking state, helpers, or API (spec 72.a.2)."""

    def test_no_thinking_state_or_api_remains(self) -> None:
        """All thinking surface, buffer, scheduler, and merge helpers are gone."""
        block = AssistantStreamBlock()

        assert not hasattr(block, "_thinking_body")
        assert not hasattr(block, "_thinking_text")
        assert not hasattr(block, "_thinking_dirty")
        assert not hasattr(block, "_last_rendered_thinking")
        assert not hasattr(block, "thinking_text")
        assert not hasattr(block, "append_thinking")
        assert not hasattr(block, "set_thinking")
        assert not hasattr(block, "set_expanded")
        assert not hasattr(block, "_stabilize_reasoning_markdown")
        assert not hasattr(block, "_normalize_reasoning_line")
        assert not hasattr(block, "_merge_reasoning_delta")

    def test_compose_yields_answer_and_terminal_note_only(self) -> None:
        """``compose()`` yields exactly the answer-side regions when no label is set."""
        block: AssistantStreamBlock = AssistantStreamBlock()
        widgets = list(block.compose())

        assert widgets == [block._answer_body, block._terminal_note]


class TestAssistantStreamBlockSeal:
    """``seal()`` finalizes the block without clearing streamed content (spec 32.a)."""

    def test_seal_marks_block_finalized(self) -> None:
        """``seal()`` flips the block into the finalized state."""
        block = AssistantStreamBlock()

        block.seal()

        assert block.finalized is True

    def test_seal_preserves_streamed_answer_text(self) -> None:
        """``seal()`` does not overwrite previously streamed answer text."""
        block = AssistantStreamBlock()
        block.append_text(delta="I'll prepare the read call now.")

        block.seal()

        assert block.answer_text == "I'll prepare the read call now."

    def test_seal_is_idempotent_on_already_finalized_block(self) -> None:
        """``seal()`` is a no-op once the block has already been finalized."""
        block = AssistantStreamBlock()
        block.finalize(final_text="final answer")

        block.seal()

        assert block.finalized is True
        assert block.answer_text == "final answer"


class TestAssistantStreamBlockTitlePrefix:
    """Optional ``title_prefix`` constructor argument (sub-spec 03.d)."""

    def test_no_prefix_creates_no_label_widget(self) -> None:
        """``AssistantStreamBlock()`` without a prefix creates no label Static."""
        block: AssistantStreamBlock = AssistantStreamBlock()

        assert block._label is None

    def test_prefix_creates_label_static(self) -> None:
        """``AssistantStreamBlock(title_prefix=...)`` stores a label Static."""
        block: AssistantStreamBlock = AssistantStreamBlock(title_prefix="⎇ task-1")

        assert block._label is not None

    def test_prefix_label_text_matches_argument(self) -> None:
        """The label Static contains exactly the supplied prefix text."""
        block: AssistantStreamBlock = AssistantStreamBlock(title_prefix="⎇ imports")

        assert block._label is not None
        assert str(block._label.content) == "⎇ imports"

    def test_compose_yields_label_first_when_prefix_set(self) -> None:
        """``compose()`` yields the label widget before the content regions."""
        block: AssistantStreamBlock = AssistantStreamBlock(title_prefix="⎇ t1")
        widgets = list(block.compose())

        assert widgets[0] is block._label

    def test_compose_no_label_in_output_when_prefix_none(self) -> None:
        """``compose()`` does not yield a label widget when prefix is ``None``."""
        block: AssistantStreamBlock = AssistantStreamBlock()
        widgets = list(block.compose())

        assert block._label not in widgets
        # Two content widgets (answer + terminal note); no copy header remains.
        assert len(widgets) == 2

    def test_prefix_does_not_affect_text_accumulation(self) -> None:
        """A block with a prefix still accumulates answer text correctly."""
        block: AssistantStreamBlock = AssistantStreamBlock(title_prefix="⎇ t1")
        block.append_text(delta="hello ")
        block.append_text(delta="world")

        assert block.answer_text == "hello world"

    def test_no_prefix_text_accumulation_unchanged(self) -> None:
        """``AssistantStreamBlock()`` without prefix accumulates text as before."""
        block: AssistantStreamBlock = AssistantStreamBlock()
        block.append_text(delta="answer")

        assert block.answer_text == "answer"


class TestAssistantStreamBlockCopyableText:
    """``get_copyable_text`` returns answer text only (spec 72.a.2)."""

    def test_returns_answer_text_only(self) -> None:
        """Focused copy yields exactly the block's answer text."""
        block = AssistantStreamBlock()
        block.append_text(delta="public answer")

        assert block.get_copyable_text() == "public answer"

    def test_returns_empty_string_when_no_answer(self) -> None:
        """Focused copy yields an empty string before any answer text arrives."""
        block = AssistantStreamBlock()

        assert block.get_copyable_text() == ""


class TestAssistantAnswerBodySelection:
    """The answer surface serves raw text through Textual's selection seam (spec 72.a.3)."""

    def test_get_selection_returns_none_without_answer_text(self) -> None:
        """An empty answer surface offers no selectable text.

        WHO: The spec-72.a.3 regression suite calls this on a fresh block.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()

        assert block._answer_body.get_selection(SELECT_ALL) is None

    def test_get_selection_extracts_raw_answer_text(self) -> None:
        """A full-surface selection yields the raw answer text, unescaped.

        The markdown renderable escapes angle brackets for display, but the
        selection seam must serve the raw answer so a drag-selection copy
        lands the true text on the shared clipboard funnel.

        WHO: The spec-72.a.3 regression suite calls this after streamed text.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()
        block.append_text(delta="select me <now>")

        selected: Optional[tuple[str, str]] = block._answer_body.get_selection(SELECT_ALL)

        assert selected == ("select me <now>", "\n")

    def test_finalize_with_empty_text_hides_previously_rendered_answer_surface(self) -> None:
        """Hide stale answer text when the completed answer is empty.

        WHAT: Verifies an empty completed answer clears a previously visible
            surface and withdraws its selection.
        WHO: The spec-72.a.3 regression suite calls this after streamed text.
        WHEN: A terminal assistant event supplies no completed answer text.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()
        block.append_text(delta="partial answer")

        block.finalize(final_text="")

        assert block._answer_body.display is False
        assert str(block._answer_body.content) == ""
        assert block._answer_body.get_selection(SELECT_ALL) is None


def _build_session() -> SloAgentSession:
    """Build a minimal ``SloAgentSession`` driven by a Faux LLM for pilot tests.

    Returns:
        SloAgentSession: A session ready to drive a ``SloTUI``.
    """
    agent: SloAgent = SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")]))
    return SloAgentSession(
        agent=agent,
        workdir=Path(".").resolve(),
        session_id=str(uuid4()),
    )


class TestAssistantStreamBlockCoalescing:
    """Coalesced, mount-aware streaming render + final flush (spec 59, Bug #2, CRITICAL #4)."""

    def test_unmounted_append_renders_synchronously(self) -> None:
        """Before mount, a delta renders immediately (preserves existing contract)."""
        block = AssistantStreamBlock()
        block.append_text(delta="Hello")
        assert block._last_rendered_answer == "Hello"
        assert block._answer_dirty is False

    def test_flush_answer_skips_unchanged_text(self) -> None:
        """_flush_answer does nothing when the accumulator equals the snapshot."""
        block = AssistantStreamBlock()
        block.append_text(delta="Hello")
        # After the synchronous flush, snapshot == accumulator. Mark dirty again.
        block._answer_dirty = True
        block._flush_answer()
        # Snapshot still equals "Hello"; no re-render, dirty cleared.
        assert block._last_rendered_answer == "Hello"
        assert block._answer_dirty is False

    def test_set_answer_renders_completed_truth_synchronously(self) -> None:
        """set_answer renders immediately (completed truth is eager)."""
        block = AssistantStreamBlock()
        block.set_answer(content="done")
        assert block._last_rendered_answer == "done"

    def test_flush_dirty_regions_is_a_noop_when_the_answer_is_clean(self) -> None:
        """_flush_dirty_regions renders nothing when the answer surface is not dirty."""
        block = AssistantStreamBlock()
        block.append_text(delta="Hello")
        render_calls: list[int] = [0]
        original_render = block._render_answer

        def _counting_render() -> None:
            render_calls[0] += 1
            original_render()

        block._render_answer = _counting_render  # type: ignore[method-assign]

        block._flush_dirty_regions()

        assert render_calls[0] == 0
        assert block._last_rendered_answer == "Hello"

    def test_finalize_flushes_and_marks_timer_none(self) -> None:
        """finalize flushes pending text and leaves _flush_timer as None."""
        block = AssistantStreamBlock()
        block._answer_text = "streamed"
        block._answer_dirty = True
        block.finalize(final_text="final answer")
        assert block._last_rendered_answer == "final answer"
        assert block._flush_timer is None
        assert block.finalized is True

    def test_seal_flushes_pending_text(self) -> None:
        """seal flushes pending dirty regions before finalizing."""
        block = AssistantStreamBlock()
        block._answer_text = "tail text"
        block._answer_dirty = True
        block.seal()
        assert block._last_rendered_answer == "tail text"
        assert block._flush_timer is None
        assert block.finalized is True

    def test_mark_aborted_flushes_pending_text(self) -> None:
        """mark_aborted flushes pending dirty regions before finalizing."""
        block = AssistantStreamBlock()
        block._answer_text = "partial"
        block._answer_dirty = True
        block.mark_aborted()
        assert block._last_rendered_answer == "partial"
        assert block._flush_timer is None

    def test_mark_failed_flushes_pending_text(self) -> None:
        """mark_failed flushes pending dirty regions before finalizing."""
        block = AssistantStreamBlock()
        block._answer_text = "partial"
        block._answer_dirty = True
        block.mark_failed(error_message="oops")
        assert block._last_rendered_answer == "partial"
        assert block._flush_timer is None

    def test_terminal_note_error_with_brackets(self) -> None:
        """A failure message containing ``[...]`` renders literally in the note."""
        block = AssistantStreamBlock()

        block.mark_failed(error_message="bad token [EOF]")

        assert block.terminal_note_text == "(error: bad token [EOF])"
        assert "[EOF]" in str(block._terminal_note.content)

    @pytest.mark.asyncio
    async def test_seal_flushes_last_delta_when_mounted(self) -> None:
        """seal renders the last un-flushed delta before stopping the timer."""
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)
        async with app.run_test() as pilot:
            block = AssistantStreamBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            # Append without waiting for the timer to tick — mark dirty manually.
            block._answer_text = "tail text"
            block._answer_dirty = True
            block.seal()  # must flush before stopping
            await pilot.pause()
            assert block._last_rendered_answer == "tail text"
            assert block._flush_timer is None

    @pytest.mark.asyncio
    async def test_mounted_coalescing_renders_once_per_frame(self) -> None:
        """Multiple deltas within one frame produce exactly one _render_answer call.

        This test guards the core Phase 1b fix: before the fix, every
        ``append_text`` call would invoke ``_render_answer`` synchronously
        (because ``or self._flush_timer is None`` made the guard always true),
        so N deltas produced N renders. After the fix, the coalescing timer
        is started on the first delta and only fires once per ~30 Hz tick,
        collapsing N same-frame deltas into one ``Static.update``.

        Assertion: after several deltas and ONE ``pilot.pause()``, the last
        rendered answer snapshot equals the full accumulated text (the timer
        ticked once), AND ``_flush_timer`` is not None (the timer is still
        running because the block is not finalized).
        """
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)
        render_call_count: list[int] = [0]
        async with app.run_test() as pilot:
            block = AssistantStreamBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            # Patch _render_answer to count invocations.
            original_render = block._render_answer

            def _counting_render() -> None:
                render_call_count[0] += 1
                original_render()

            block._render_answer = _counting_render  # type: ignore[method-assign]
            # Issue several deltas synchronously — no pause between them.
            # A working coalescing timer must NOT render synchronously here.
            block.append_text(delta="Hello")
            block.append_text(delta=" world")
            block.append_text(delta=" from")
            block.append_text(delta=" coalescing")
            # The timer should now be running (not None), and no render yet.
            assert (
                block._flush_timer is not None
            ), "_flush_timer must be set after first delta on a mounted block"
            # One pause lets the ~30 Hz timer tick and flush exactly once.
            await pilot.pause()
            # After one frame, the render should have fired exactly once.
            assert render_call_count[0] == 1, (
                f"Expected 1 _render_answer call but got {render_call_count[0]}; "
                "the coalescing timer is not suppressing per-delta renders"
            )
            assert block._last_rendered_answer == "Hello world from coalescing"
            assert block._flush_timer is not None
