"""Direct tests for ``AssistantStreamBlock`` formatting."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.markdown import Markdown
from rich.padding import Padding

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock


class TestAssistantStreamBlock:
    """Pi-style reasoning / answer rendering details."""

    def test_thinking_renders_without_redundant_label_and_with_padding(self) -> None:
        """Reasoning text renders as padded markdown without a literal label."""
        block = AssistantStreamBlock()

        block.append_thinking(delta="  Inspecting the app  ")

        assert not hasattr(block, "_thinking_label")
        assert isinstance(block._thinking_body.content, Padding)
        assert isinstance(block._thinking_body.content.renderable, Markdown)
        assert block._thinking_body.content.renderable.markup == "Inspecting the app"
        assert block._thinking_body.content.top == 1
        assert block._thinking_body.content.right == 1
        assert block._thinking_body.content.bottom == 1
        assert block._thinking_body.content.left == 1

    def test_answer_renders_as_padded_markdown(self) -> None:
        """Assistant answer text uses the same padded markdown surface."""
        block = AssistantStreamBlock()

        block.append_text(delta="Hello world")

        assert block._answer_body.display is True
        assert isinstance(block._answer_body.content, Padding)
        assert isinstance(block._answer_body.content.renderable, Markdown)
        assert block._answer_body.content.renderable.markup == "Hello world"
        assert block._answer_body.content.top == 1
        assert block._answer_body.content.right == 1
        assert block._answer_body.content.bottom == 1
        assert block._answer_body.content.left == 1

    def test_answer_escapes_angle_brackets_before_markdown_render(self) -> None:
        """Answer text escapes angle brackets that destabilize markdown rendering."""
        block = AssistantStreamBlock()

        block.append_text(delta="Path: <repo>/src/file.py")

        assert isinstance(block._answer_body.content, Padding)
        assert isinstance(block._answer_body.content.renderable, Markdown)
        assert block._answer_body.content.renderable.markup == r"Path: \<repo\>/src/file.py"

    def test_reasoning_normalizes_broken_heading_markdown(self) -> None:
        """Streamed reasoning fixes common broken heading emphasis markers."""
        block = AssistantStreamBlock()

        block.append_thinking(delta="*Summarizing unstaged changes**")

        assert isinstance(block._thinking_body.content, Padding)
        assert isinstance(block._thinking_body.content.renderable, Markdown)
        assert block._thinking_body.content.renderable.markup == "**Summarizing unstaged changes**"

    def test_reasoning_and_answer_use_distinct_surface_classes(self) -> None:
        """Reasoning and answer surfaces keep distinct widget classes for styling."""
        block = AssistantStreamBlock()

        assert "assistant-thinking-body" in block._thinking_body.classes
        assert "assistant-answer-body" in block._answer_body.classes

    def test_empty_surfaces_start_hidden(self) -> None:
        """Empty thinking / answer / terminal regions do not reserve blank layout rows."""
        block = AssistantStreamBlock()

        assert block._thinking_body.display is False
        assert block._answer_body.display is False
        assert block._terminal_note.display is False

    def test_streamed_reasoning_inserts_spacing_between_word_fragments(self) -> None:
        """Reasoning deltas from Codex-style word fragments stay readable while streaming."""
        block = AssistantStreamBlock()

        block.append_thinking(delta="I")
        block.append_thinking(delta="need")
        block.append_thinking(delta="to")
        block.append_thinking(delta="plan")
        block.append_thinking(delta=",")
        block.append_thinking(delta="not")
        block.append_thinking(delta="re")
        block.append_thinking(delta="-")
        block.append_thinking(delta="plan")

        assert block.thinking_text == "I need to plan, not re-plan"


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

    def test_seal_preserves_streamed_thinking_text(self) -> None:
        """``seal()`` does not overwrite previously streamed reasoning text."""
        block = AssistantStreamBlock()
        block.append_thinking(delta="Inspecting the file")

        block.seal()

        assert block.thinking_text == "Inspecting the file"

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
        # Three content widgets only
        assert len(widgets) == 3

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


class TestAssistantStreamBlockExpansion:
    """Global expand/collapse behaviour for ``AssistantStreamBlock`` (sub-spec 42.a.12)."""

    def test_natural_default_shows_reasoning(self) -> None:
        """Reasoning is visible by default once present."""
        block = AssistantStreamBlock()
        block.set_thinking(content="deep reasoning")

        assert block._thinking_body.display is True

    def test_force_expanded_false_hides_reasoning(self) -> None:
        """Reasoning is hidden when the block mounts under collapse-all."""
        block = AssistantStreamBlock(force_expanded=False)
        block.set_thinking(content="deep reasoning")

        assert block._thinking_body.display is False

    def test_set_expanded_toggles_reasoning_visibility(self) -> None:
        """``set_expanded`` shows/hides reasoning while preserving its content."""
        block = AssistantStreamBlock()
        block.set_thinking(content="deep reasoning")

        block.set_expanded(expanded=False)
        assert block._thinking_body.display is False

        block.set_expanded(expanded=True)
        assert block._thinking_body.display is True

    def test_answer_visible_regardless_of_collapse(self) -> None:
        """The answer region stays visible even when collapsed."""
        block = AssistantStreamBlock(force_expanded=False)
        block.set_answer(content="the answer")

        assert block._answer_body.display is True


class TestAssistantStreamBlockCopyableText:
    """``get_copyable_text`` protocol for clipboard copy (spec 56)."""

    def test_combines_thinking_and_answer_with_blank_line(self) -> None:
        """``get_copyable_text`` joins both parts with a blank-line separator."""
        block = AssistantStreamBlock()
        block._thinking_text = "thinking"
        block._answer_text = "answer"

        assert block.get_copyable_text() == "thinking\n\nanswer"

    def test_skips_empty_thinking_when_absent(self) -> None:
        """``get_copyable_text`` returns only the answer when thinking is empty."""
        block = AssistantStreamBlock()
        block._answer_text = "answer only"

        assert block.get_copyable_text() == "answer only"

    def test_skips_empty_answer_when_absent(self) -> None:
        """``get_copyable_text`` returns only thinking when answer is empty."""
        block = AssistantStreamBlock()
        block._thinking_text = "thinking only"

        assert block.get_copyable_text() == "thinking only"

    def test_returns_empty_string_when_both_absent(self) -> None:
        """``get_copyable_text`` returns empty string when the block has no content."""
        block = AssistantStreamBlock()

        assert block.get_copyable_text() == ""


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

    def test_unmounted_append_thinking_renders_synchronously(self) -> None:
        """Before mount, a thinking delta renders immediately."""
        block = AssistantStreamBlock()
        block.append_thinking(delta="reasoning here")
        assert block._last_rendered_thinking == "reasoning here"
        assert block._thinking_dirty is False

    def test_set_thinking_renders_completed_truth_synchronously(self) -> None:
        """set_thinking renders immediately (completed truth is eager)."""
        block = AssistantStreamBlock()
        block.set_thinking(content="full reasoning")
        assert block._last_rendered_thinking == "full reasoning"

    def test_flush_dirty_regions_only_renders_dirty_surfaces(self) -> None:
        """_flush_dirty_regions processes only surfaces that are marked dirty."""
        block = AssistantStreamBlock()
        block._answer_text = "A"
        block._answer_dirty = True
        block._thinking_dirty = False
        block._flush_dirty_regions()
        # Answer was dirty so it rendered; thinking was not dirty.
        assert block._last_rendered_answer == "A"
        assert block._last_rendered_thinking == ""

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
