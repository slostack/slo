"""Direct tests for ``AssistantStreamBlock`` formatting."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.padding import Padding

from src.tui.widgets.assistant_stream_block import AssistantStreamBlock


class TestAssistantStreamBlock:
    """Pi-style reasoning / answer rendering details."""

    def test_thinking_renders_without_redundant_label_and_with_padding(self) -> None:
        """Reasoning text renders as padded markdown without a literal label."""
        block = AssistantStreamBlock()

        block.append_thinking(delta="  Inspecting the app  ")

        assert not hasattr(block, "_thinking_label")
        assert isinstance(block._thinking_body.renderable, Padding)
        assert isinstance(block._thinking_body.renderable.renderable, Markdown)
        assert block._thinking_body.renderable.renderable.markup == "Inspecting the app"
        assert block._thinking_body.renderable.top == 1
        assert block._thinking_body.renderable.right == 1
        assert block._thinking_body.renderable.bottom == 1
        assert block._thinking_body.renderable.left == 1

    def test_answer_renders_as_padded_markdown(self) -> None:
        """Assistant answer text uses the same padded markdown surface."""
        block = AssistantStreamBlock()

        block.append_text(delta="Hello world")

        assert block._answer_body.display is True
        assert isinstance(block._answer_body.renderable, Padding)
        assert isinstance(block._answer_body.renderable.renderable, Markdown)
        assert block._answer_body.renderable.renderable.markup == "Hello world"
        assert block._answer_body.renderable.top == 1
        assert block._answer_body.renderable.right == 1
        assert block._answer_body.renderable.bottom == 1
        assert block._answer_body.renderable.left == 1

    def test_answer_escapes_angle_brackets_before_markdown_render(self) -> None:
        """Answer text escapes angle brackets that destabilize markdown rendering."""
        block = AssistantStreamBlock()

        block.append_text(delta="Path: <repo>/src/file.py")

        assert isinstance(block._answer_body.renderable, Padding)
        assert isinstance(block._answer_body.renderable.renderable, Markdown)
        assert block._answer_body.renderable.renderable.markup == r"Path: \<repo\>/src/file.py"

    def test_reasoning_normalizes_broken_heading_markdown(self) -> None:
        """Streamed reasoning fixes common broken heading emphasis markers."""
        block = AssistantStreamBlock()

        block.append_thinking(delta="*Summarizing unstaged changes**")

        assert isinstance(block._thinking_body.renderable, Padding)
        assert isinstance(block._thinking_body.renderable.renderable, Markdown)
        assert block._thinking_body.renderable.renderable.markup == "**Summarizing unstaged changes**"

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
        assert str(block._label.renderable) == "⎇ imports"

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
