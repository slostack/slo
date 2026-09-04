"""Direct tests for ``AssistantStreamThinkingBlock`` formatting (spec 72.a.2)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.markdown import Markdown
from rich.padding import Padding
from textual.message import Message

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock


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


class TestAssistantStreamThinkingBlock:
    """One thinking segment owns its reasoning buffer and muted rendering."""

    def test_thinking_renders_without_redundant_label_and_with_padding(self) -> None:
        """Reasoning text renders as padded markdown without a literal label."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="  Inspecting the app  ")

        assert not hasattr(block, "_thinking_label")
        assert isinstance(block._body.content, Padding)
        assert isinstance(block._body.content.renderable, Markdown)
        assert block._body.content.renderable.markup == "Inspecting the app"
        assert block._body.content.top == 1
        assert block._body.content.right == 0
        assert block._body.content.bottom == 1
        assert block._body.content.left == 0

    def test_widget_css_uses_transcript_output_pad(self) -> None:
        """The widget declares the uniform ``TRANSCRIPT_OUTPUT_PAD`` convention."""
        block_rule: str = AssistantStreamThinkingBlock.DEFAULT_CSS.split("AssistantStreamThinkingBlock {")[
            1
        ].split("}")[0]
        assert "padding: 0 1;" in block_rule

    def test_reasoning_normalizes_broken_heading_markdown(self) -> None:
        """Streamed reasoning fixes the ``*text**`` broken heading emphasis."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="*Summarizing unstaged changes**")

        assert isinstance(block._body.content, Padding)
        assert isinstance(block._body.content.renderable, Markdown)
        assert block._body.content.renderable.markup == "**Summarizing unstaged changes**"

    def test_reasoning_normalizes_single_star_emphasis_line(self) -> None:
        """A ``*text*`` streamed line is promoted to balanced bold emphasis."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="*plan first*")

        assert isinstance(block._body.content, Padding)
        assert isinstance(block._body.content.renderable, Markdown)
        assert block._body.content.renderable.markup == "**plan first**"

    def test_reasoning_passes_well_formed_lines_through_unchanged(self) -> None:
        """Lines that match no glitch branch keep their original text."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="**already balanced**")

        assert isinstance(block._body.content, Padding)
        assert isinstance(block._body.content.renderable, Markdown)
        assert block._body.content.renderable.markup == "**already balanced**"

    def test_thinking_escapes_angle_brackets_before_markdown_render(self) -> None:
        """Reasoning text escapes angle brackets that destabilize markdown rendering."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="type is list[str]")

        assert isinstance(block._body.content, Padding)
        assert isinstance(block._body.content.renderable, Markdown)
        assert "list[str]" in block._body.content.renderable.markup

    def test_thinking_body_uses_muted_surface_class(self) -> None:
        """The reasoning surface keeps the muted thinking CSS class for styling."""
        block = AssistantStreamThinkingBlock()

        assert "assistant-thinking-body" in block._body.classes

    def test_thinking_body_css_uses_canonical_thinking_text_token(self) -> None:
        """The reasoning body paints muted italic ``$thinking-text`` on a bare surface (spec 72.a.5)."""
        body_rule: str = AssistantStreamThinkingBlock.DEFAULT_CSS.split(
            "AssistantStreamThinkingBlock .assistant-thinking-body {"
        )[1].split("}")[0]

        assert "color: $thinking-text;" in body_rule
        assert "text-style: italic;" in body_rule
        assert "background: transparent;" in body_rule

    def test_block_background_is_bare_canvas(self) -> None:
        """The thinking segment carries no card fill of its own (spec 72.a.5)."""
        block_rule: str = AssistantStreamThinkingBlock.DEFAULT_CSS.split("AssistantStreamThinkingBlock {")[
            1
        ].split("}")[0]

        assert "background: transparent;" in block_rule

    def test_empty_body_starts_hidden(self) -> None:
        """An empty reasoning surface does not reserve a blank layout row."""
        block = AssistantStreamThinkingBlock()

        assert block._body.display is False

    def test_widget_is_focusable(self) -> None:
        """A thinking segment is a focusable transcript child for keyboard copy."""
        assert AssistantStreamThinkingBlock.can_focus is True

    def test_streamed_reasoning_inserts_spacing_between_word_fragments(self) -> None:
        """Reasoning deltas from Codex-style word fragments stay readable while streaming."""
        block = AssistantStreamThinkingBlock()

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


class TestMergeReasoningDelta:
    """``_merge_reasoning_delta`` spacing-repair decision branches."""

    def test_concatenates_when_existing_is_empty(self) -> None:
        """An empty accumulator accepts the delta verbatim."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="", delta="word")
        assert merged == "word"

    def test_concatenates_when_delta_is_empty(self) -> None:
        """An empty delta leaves the accumulator unchanged."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="word", delta="")
        assert merged == "word"

    def test_concatenates_when_existing_ends_with_whitespace(self) -> None:
        """No extra space is inserted after trailing whitespace."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="word ", delta="next")
        assert merged == "word next"

    def test_concatenates_when_delta_starts_with_whitespace(self) -> None:
        """No extra space is inserted before leading whitespace."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="word", delta=" next")
        assert merged == "word next"

    def test_concatenates_when_delta_starts_with_closing_punctuation(self) -> None:
        """Punctuation continuations attach without a space."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="word", delta=".")
        assert merged == "word."

    def test_concatenates_when_existing_ends_with_opening_bracket(self) -> None:
        """Text attaches directly after an opening bracket."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="call(", delta="arg")
        assert merged == "call(arg"

    def test_concatenates_when_delta_starts_with_word_character_joiner(self) -> None:
        """Hyphen/slash continuations attach without a space."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="re", delta="-")
        assert merged == "re-"

    def test_concatenates_when_existing_ends_with_word_character_joiner(self) -> None:
        """Text attaches directly after a hyphen/slash fragment."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="re-", delta="plan")
        assert merged == "re-plan"

    def test_inserts_a_space_between_plain_word_fragments(self) -> None:
        """The default branch inserts one space between two word fragments."""
        merged: str = AssistantStreamThinkingBlock._merge_reasoning_delta(existing="hello", delta="world")
        assert merged == "hello world"


class TestAssistantStreamThinkingBlockSeal:
    """``seal()`` finalizes the segment without clearing streamed reasoning."""

    def test_seal_marks_block_finalized(self) -> None:
        """``seal()`` flips the segment into the finalized state."""
        block = AssistantStreamThinkingBlock()

        block.seal()

        assert block.finalized is True

    def test_seal_preserves_streamed_thinking_text(self) -> None:
        """``seal()`` does not overwrite previously streamed reasoning text."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="Inspecting the file")

        block.seal()

        assert block.thinking_text == "Inspecting the file"

    def test_seal_is_idempotent_on_already_sealed_block(self) -> None:
        """``seal()`` is a no-op once the segment has already been sealed."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="reasoning")

        block.seal()
        block.seal()

        assert block.finalized is True
        assert block.thinking_text == "reasoning"

    def test_append_thinking_is_a_noop_after_seal(self) -> None:
        """A sealed segment rejects further streamed deltas."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="before")

        block.seal()
        block.append_thinking(delta="after")

        assert block.thinking_text == "before"

    def test_set_thinking_is_a_noop_after_seal(self) -> None:
        """A sealed segment rejects completed text; repair only lands while open."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="before")

        block.seal()
        block.set_thinking(content="after")

        assert block.thinking_text == "before"

    def test_append_thinking_ignores_empty_delta(self) -> None:
        """An empty delta never mutates the reasoning buffer."""
        block = AssistantStreamThinkingBlock()

        block.append_thinking(delta="")

        assert block.thinking_text == ""
        assert block._body.display is False

    def test_set_thinking_ignores_empty_content(self) -> None:
        """Empty completed content never mutates the reasoning buffer."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="kept")

        block.set_thinking(content="")

        assert block.thinking_text == "kept"


class TestAssistantStreamThinkingBlockExpansion:
    """Global expand/collapse behaviour for ``AssistantStreamThinkingBlock``."""

    def test_natural_default_shows_reasoning(self) -> None:
        """Reasoning is visible by default once present."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="deep reasoning")

        assert block._body.display is True

    def test_force_expanded_true_shows_reasoning(self) -> None:
        """Reasoning is visible when the block mounts under expand-all."""
        block = AssistantStreamThinkingBlock(force_expanded=True)
        block.set_thinking(content="deep reasoning")

        assert block._body.display is True

    def test_force_expanded_false_hides_reasoning(self) -> None:
        """Reasoning is hidden when the block mounts under collapse-all."""
        block = AssistantStreamThinkingBlock(force_expanded=False)
        block.set_thinking(content="deep reasoning")

        assert block._body.display is False

    def test_set_expanded_toggles_reasoning_visibility(self) -> None:
        """``set_expanded`` shows/hides reasoning while preserving its content."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="deep reasoning")

        block.set_expanded(expanded=False)
        assert block._body.display is False

        block.set_expanded(expanded=True)
        assert block._body.display is True
        assert block.thinking_text == "deep reasoning"

    def test_set_expanded_with_same_state_is_a_noop(self) -> None:
        """``set_expanded`` short-circuits when the state is already applied."""
        block = AssistantStreamThinkingBlock(force_expanded=False)
        render_calls: list[int] = [0]
        original_render = block._render_thinking

        def _counting_render() -> None:
            render_calls[0] += 1
            original_render()

        block._render_thinking = _counting_render  # type: ignore[method-assign]

        block.set_expanded(expanded=False)

        assert render_calls[0] == 0


class TestAssistantStreamThinkingBlockCopyableText:
    """``get_copyable_text`` returns reasoning only for the focused-copy path."""

    def test_returns_reasoning_only(self) -> None:
        """Focused copy yields exactly the segment's reasoning text."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="private reasoning")

        assert block.get_copyable_text() == "private reasoning"

    def test_returns_empty_string_when_no_reasoning(self) -> None:
        """Focused copy yields an empty string before any reasoning arrives."""
        block = AssistantStreamThinkingBlock()

        assert block.get_copyable_text() == ""


class TestAssistantStreamThinkingBlockCoalescing:
    """Coalesced, mount-aware streaming render + final flush for one segment."""

    def test_unmounted_append_renders_synchronously(self) -> None:
        """Before mount, a delta renders immediately (direct-construction contract)."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="Hello")
        assert block._last_rendered == "Hello"
        assert block._dirty is False

    def test_flush_skips_unchanged_text(self) -> None:
        """``_flush`` does nothing when the accumulator equals the snapshot."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="Hello")
        block._dirty = True
        block._flush()
        assert block._last_rendered == "Hello"
        assert block._dirty is False

    def test_flush_is_a_noop_when_not_dirty(self) -> None:
        """``_flush`` returns immediately when no render is pending."""
        block = AssistantStreamThinkingBlock()
        block.append_thinking(delta="Hello")
        render_calls: list[int] = [0]
        original_render = block._render_thinking

        def _counting_render() -> None:
            render_calls[0] += 1
            original_render()

        block._render_thinking = _counting_render  # type: ignore[method-assign]

        block._flush()

        assert render_calls[0] == 0

    def test_set_thinking_renders_completed_truth_synchronously(self) -> None:
        """``set_thinking`` renders immediately (completed truth is eager)."""
        block = AssistantStreamThinkingBlock()
        block.set_thinking(content="full reasoning")
        assert block._last_rendered == "full reasoning"

    def test_seal_flushes_pending_text(self) -> None:
        """``seal`` flushes pending dirty text before finalizing."""
        block = AssistantStreamThinkingBlock()
        block._thinking_text = "tail text"
        block._dirty = True
        block.seal()
        assert block._last_rendered == "tail text"
        assert block._flush_timer is None
        assert block.finalized is True

    def test_unmounted_flush_posts_no_rendered_message(self) -> None:
        """An unmounted flush renders without posting the follow notification."""
        block = AssistantStreamThinkingBlock()
        posted: list[Message] = []

        def _recording_post_message(message: Message) -> bool:
            posted.append(message)
            return True

        block.post_message = _recording_post_message  # type: ignore[method-assign]

        block.append_thinking(delta="reasoning")

        assert posted == []

    @pytest.mark.asyncio
    async def test_mounted_flush_posts_the_shared_rendered_message(self) -> None:
        """A mounted flush posts ``AssistantStreamBlock.Rendered`` for scroll follow."""
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)
        async with app.run_test() as pilot:
            block = AssistantStreamThinkingBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            posted: list[object] = []
            original_post_message = block.post_message

            def _recording_post_message(message: Message) -> bool:
                posted.append(message)
                return original_post_message(message)

            block.post_message = _recording_post_message  # type: ignore[method-assign]

            block.append_thinking(delta="reasoning")
            await pilot.pause(delay=0.1)

            rendered_messages = [
                message for message in posted if isinstance(message, AssistantStreamBlock.Rendered)
            ]
            assert len(rendered_messages) == 1
            # A fresh transcript viewport rests at the bottom, so the pre-flush
            # follow snapshot reports follow mode.
            assert rendered_messages[0].was_following is True

    @pytest.mark.asyncio
    async def test_seal_flushes_last_delta_when_mounted(self) -> None:
        """``seal`` renders the last un-flushed delta before stopping the timer."""
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)
        async with app.run_test() as pilot:
            block = AssistantStreamThinkingBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            block._thinking_text = "tail text"
            block._dirty = True
            block.seal()
            await pilot.pause()
            assert block._last_rendered == "tail text"
            assert block._flush_timer is None

    @pytest.mark.asyncio
    async def test_mounted_coalescing_renders_once_per_frame(self) -> None:
        """Multiple deltas within one frame produce exactly one ``_render_thinking`` call."""
        session: SloAgentSession = _build_session()
        app: SloTUI = SloTUI(session=session)
        render_call_count: list[int] = [0]
        async with app.run_test() as pilot:
            block = AssistantStreamThinkingBlock()
            assert app._transcript_content is not None
            await app._transcript_content.mount(block)
            original_render = block._render_thinking

            def _counting_render() -> None:
                render_call_count[0] += 1
                original_render()

            block._render_thinking = _counting_render  # type: ignore[method-assign]
            block.append_thinking(delta="Hello")
            block.append_thinking(delta=" world")
            block.append_thinking(delta=" from")
            block.append_thinking(delta=" coalescing")
            assert block._flush_timer is not None
            await pilot.pause()
            assert render_call_count[0] == 1, (
                f"Expected 1 _render_thinking call but got {render_call_count[0]}; "
                "the coalescing timer is not suppressing per-delta renders"
            )
            assert block._last_rendered == "Hello world from coalescing"
            assert block._flush_timer is not None
