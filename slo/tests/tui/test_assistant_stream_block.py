"""Direct tests for ``AssistantStreamBlock`` answer-only formatting (spec 72.a.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.markdown import Markdown
from rich.padding import Padding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.selection import SELECT_ALL
from textual.widget import Widget
from textual.worker import Worker
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.providers.faux import FauxChatModel
from src.tui.app import SloTUI
from src.tui.widgets.assistant_stream_block import AnswerMarkdownPart, AssistantStreamBlock
from src.tui.widgets.mermaid_chart_block import MermaidChartBlock
from tests.tui._scroll_settle import pump_until

_MERMAID_FENCE: str = "```mermaid\ngraph TD\n  A[Start] --> B[End]\n```\n"
"""One closed mermaid fence used by the segmented-answer tests."""

_MERMAID_SOURCE: str = "graph TD\n  A[Start] --> B[End]\n"
"""The fence body ``_MERMAID_FENCE`` segments into, byte for byte."""


class TestAssistantStreamBlock:
    """Pi-style answer rendering details; thinking lives in its own widget."""

    def test_answer_without_mermaid_renders_single_markdown_part(self) -> None:
        """A mermaid-free answer is one padded-markdown part (specs 72.a.3, 77.a.3)."""
        block = AssistantStreamBlock()

        block.append_text(delta="Hello world")

        parts: list[Widget] = list(block._answer_body.compose())
        assert block._answer_body.display is True
        assert len(parts) == 1
        part: Widget = parts[0]
        assert isinstance(part, AnswerMarkdownPart)
        assert isinstance(part.content, Padding)
        assert isinstance(part.content.renderable, Markdown)
        assert part.content.renderable.markup == "Hello world"
        assert part.content.top == 1
        assert part.content.right == 0
        assert part.content.bottom == 1
        assert part.content.left == 0

    def test_widget_css_uses_transcript_output_pad(self) -> None:
        """The block declares the uniform ``TRANSCRIPT_OUTPUT_PAD`` convention."""
        block_rule: str = AssistantStreamBlock.DEFAULT_CSS.split("AssistantStreamBlock {")[1].split("}")[0]
        assert "padding: 0 1;" in block_rule

    def test_answer_escapes_angle_brackets_before_markdown_render(self) -> None:
        """Answer text escapes angle brackets that destabilize markdown rendering."""
        block = AssistantStreamBlock()

        block.append_text(delta="Path: <repo>/src/file.py")

        part: Widget = list(block._answer_body.compose())[0]
        assert isinstance(part.content, Padding)
        assert isinstance(part.content.renderable, Markdown)
        assert part.content.renderable.markup == r"Path: \<repo\>/src/file.py"

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
            "AssistantStreamBlock .assistant-answer-markdown-part Heading {"
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
            "AssistantStreamBlock .assistant-answer-markdown-part Heading",
            "AssistantStreamBlock .assistant-answer-markdown-part BulletList",
            "AssistantStreamBlock .assistant-answer-markdown-part OrderedList",
            "AssistantStreamBlock .assistant-answer-markdown-part BlockQuote",
            "AssistantStreamBlock .assistant-answer-markdown-part CodeBlock",
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
    """The answer parts serve raw text through Textual's selection seam (spec 72.a.3).

    The seam moved from the body to ``AnswerMarkdownPart`` in ``77.a.3``: the
    body became a container of answer segments, and Textual's
    ``SelectState._walk_selected_widgets`` skips containers, so only a leaf
    part is ever asked for selected text. The contract asserted here — the
    raw, unescaped answer reaches the selection machinery — is unchanged.
    """

    def test_no_selectable_part_is_staged_without_answer_text(self) -> None:
        """An empty answer surface stages no selectable leaf at all.

        WHAT: The body owns no selection seam since ``77.a.3`` — it is a
            container — so "nothing is selectable" is asserted as "no leaf
            part exists", the only reachable form of the contract.
        WHO: The spec-72.a.3 regression suite calls this on a fresh block.
        WHEN: Before any answer text has been streamed.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()

        assert list(block._answer_body.compose()) == []

    def test_get_selection_extracts_raw_answer_text(self) -> None:
        """A full-surface selection yields the raw answer text, unescaped.

        The markdown renderable escapes angle brackets for display, but the
        selection seam must serve the raw answer so a drag-selection copy
        lands the true text on the shared clipboard funnel.

        WHO: The spec-72.a.3 regression suite calls this after streamed text.
        """
        block: AssistantStreamBlock = AssistantStreamBlock()
        block.append_text(delta="select me <now>")

        part: Widget = list(block._answer_body.compose())[0]
        selected: Optional[tuple[str, str]] = part.get_selection(SELECT_ALL)

        assert selected == ("select me <now>", "\n")

    def test_finalize_with_empty_text_hides_and_clears_the_answer_surface(self) -> None:
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
        assert list(block._answer_body.compose()) == []


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


def _mounted_child_types(*, block: AssistantStreamBlock) -> list[type[Widget]]:
    """Return the concrete types of the answer body's mounted children.

    Called by the segmented-answer tests to assert composition order without
    reaching into private reconciliation state.

    Args:
        block (AssistantStreamBlock): The block whose answer body to inspect.

    Returns:
        list[type[Widget]]: One entry per mounted answer-part widget, in order.
    """
    return [type(child) for child in block._answer_body.children]


def _staged_child_types(*, block: AssistantStreamBlock) -> list[type[Widget]]:
    """Return the concrete types of the answer body's pre-mount staged children.

    Called by the direct-construction segmented-answer tests, where
    ``show_answer`` stages children for ``compose`` instead of reconciling a
    live DOM.

    Args:
        block (AssistantStreamBlock): The block whose answer body to inspect.

    Returns:
        list[type[Widget]]: One entry per staged answer-part widget, in order.
    """
    return [type(child) for child in block._answer_body.compose()]


class TestSegmentedAnswerComposition:
    """The answer body composes one child per answer segment (spec 77.a.3)."""

    def test_answer_with_mermaid_mounts_chart_block_in_order(self) -> None:
        """A closed fence between prose composes part, chart, part — in stream order."""
        block: AssistantStreamBlock = AssistantStreamBlock()

        block.finalize(final_text=f"Here is the flow:\n\n{_MERMAID_FENCE}\nAnd that is all.\n")

        children: list[Widget] = list(block._answer_body.compose())
        assert _staged_child_types(block=block) == [
            AnswerMarkdownPart,
            MermaidChartBlock,
            AnswerMarkdownPart,
        ]
        assert isinstance(children[0], AnswerMarkdownPart)
        assert children[0].raw_text == "Here is the flow:\n\n"
        assert isinstance(children[1], MermaidChartBlock)
        assert children[1].source == _MERMAID_SOURCE
        assert isinstance(children[2], AnswerMarkdownPart)
        assert children[2].raw_text == "\nAnd that is all.\n"

    def test_streaming_open_fence_renders_as_markdown_until_closed(self) -> None:
        """A still-open fence stays inline markdown — no chart card exists yet."""
        block: AssistantStreamBlock = AssistantStreamBlock()

        block.append_text(delta="Here is the flow:\n\n```mermaid\ngraph TD\n  A[Start] --> B[End]\n")

        staged: list[Widget] = list(block._answer_body.compose())
        assert _staged_child_types(block=block) == [AnswerMarkdownPart]
        assert isinstance(staged[0], AnswerMarkdownPart)
        assert "```mermaid" in staged[0].raw_text

    @pytest.mark.asyncio
    async def test_chart_block_appears_after_closing_fence_streams(self) -> None:
        """The first reconciliation after the closer arrives mounts the chart card."""
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.append_text(delta="Here is the flow:\n\n```mermaid\ngraph TD\n  A[Start] --> B[End]\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _mounted_child_types(block=block) == [AnswerMarkdownPart],
            )
            assert _mounted_child_types(block=block) == [AnswerMarkdownPart]

            block.append_text(delta="```\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: MermaidChartBlock in _mounted_child_types(block=block),
            )

            assert _mounted_child_types(block=block) == [AnswerMarkdownPart, MermaidChartBlock]

    def test_finalize_with_mermaid_renders_chart_block(self) -> None:
        """The replay-equivalent ``finalize`` seam segments exactly like streaming."""
        block: AssistantStreamBlock = AssistantStreamBlock()

        block.finalize(final_text=f"Replayed answer.\n\n{_MERMAID_FENCE}")

        staged: list[Widget] = list(block._answer_body.compose())
        assert _staged_child_types(block=block) == [AnswerMarkdownPart, MermaidChartBlock]
        assert isinstance(staged[1], MermaidChartBlock)
        assert staged[1].source == _MERMAID_SOURCE

    @pytest.mark.asyncio
    async def test_replay_shaped_finalize_mounts_the_chart_block(self) -> None:
        """A block mounted first and finalized after renders the same chart card.

        WHAT: Reproduces the replay sequence exactly —
            ``TranscriptProjector._project_replay_assistant`` mounts the block
            and only then calls ``finalize``, so the answer takes the mounted
            reconciliation branch, not the pre-mount staging branch that
            ``test_finalize_with_mermaid_renders_chart_block`` above covers.
        WHO: Guards acceptance criterion 8 (replay parity).
        WHEN: On session resume.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.finalize(final_text=f"Replayed answer.\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)

            assert _mounted_child_types(block=block) == [AnswerMarkdownPart, MermaidChartBlock]
            assert _answer_charts(block=block)[0].source == _MERMAID_SOURCE


def _answer_parts(*, block: AssistantStreamBlock) -> list[AnswerMarkdownPart]:
    """Return the mounted markdown parts of the answer body, in order.

    Called by the reuse-rule tests to assert widget identity across flushes.

    Args:
        block (AssistantStreamBlock): The block whose answer body to inspect.

    Returns:
        list[AnswerMarkdownPart]: The mounted prose parts, in stream order.
    """
    return [child for child in block._answer_body.children if isinstance(child, AnswerMarkdownPart)]


def _answer_charts(*, block: AssistantStreamBlock) -> list[MermaidChartBlock]:
    """Return the mounted chart cards of the answer body, in order.

    Called by the reuse-rule tests to assert widget identity across flushes.

    Args:
        block (AssistantStreamBlock): The block whose answer body to inspect.

    Returns:
        list[MermaidChartBlock]: The mounted chart cards, in stream order.
    """
    return [child for child in block._answer_body.children if isinstance(child, MermaidChartBlock)]


class TestSegmentedAnswerReuseRule:
    """Reconciliation reuses children by segment kind, never by equality (spec 77.a.3)."""

    @pytest.mark.asyncio
    async def test_streaming_deltas_update_the_tail_part_in_place(self) -> None:
        """The growing tail part keeps its identity — the guard against a 30 fps teardown."""
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.append_text(delta="one")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_parts(block=block)) == 1)
            first_part: AnswerMarkdownPart = _answer_parts(block=block)[0]

            block.append_text(delta=" two")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _answer_parts(block=block)[0].raw_text == "one two",
            )
            block.append_text(delta=" three")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _answer_parts(block=block)[0].raw_text == "one two three",
            )

            parts: list[AnswerMarkdownPart] = _answer_parts(block=block)
            assert len(parts) == 1
            assert parts[0] is first_part
            assert parts[0].raw_text == "one two three"

    @pytest.mark.asyncio
    async def test_growth_after_closed_fence_keeps_chart_instance(self) -> None:
        """A delta after a closed fence leaves the mounted chart card untouched."""
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.append_text(delta=f"intro\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)
            first_chart: MermaidChartBlock = _answer_charts(block=block)[0]

            block.append_text(delta="\nAnd more prose after the chart.\n")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_parts(block=block)) == 2)

            charts: list[MermaidChartBlock] = _answer_charts(block=block)
            assert len(charts) == 1
            assert charts[0] is first_chart
            assert _mounted_child_types(block=block) == [
                AnswerMarkdownPart,
                MermaidChartBlock,
                AnswerMarkdownPart,
            ]

    @pytest.mark.asyncio
    async def test_wholesale_text_replacement_rebuilds_divergent_tail(self) -> None:
        """Replacement text reuses the matching prefix and rebuilds from the divergence."""
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.set_answer(content=f"intro\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)
            first_part: AnswerMarkdownPart = _answer_parts(block=block)[0]
            first_chart: MermaidChartBlock = _answer_charts(block=block)[0]

            block.set_answer(content="intro\n\n```mermaid\nflowchart LR\n  X --> Y\n```\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _answer_charts(block=block)[0] is not first_chart,
            )

            assert _answer_parts(block=block)[0] is first_part
            assert _answer_charts(block=block)[0] is not first_chart
            assert _answer_charts(block=block)[0].source == "flowchart LR\n  X --> Y\n"

    @pytest.mark.asyncio
    async def test_answer_that_is_only_a_fence_replaces_the_text_part_with_a_chart(self) -> None:
        """An answer that is only a fence ends as one chart card and no prose.

        WHAT: Streams an answer with no prose at all, so the single part is a
            text segment before the closer arrives and a mermaid segment
            after it, and the text child must be gone by the end. Every other
            segmented test begins with prose, so this shape — the plain "draw
            me a diagram" answer — is otherwise unrendered by the suite.
        WHO: Guards the prose-free answer shape.
        WHEN: While a prose-free answer streams in.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.append_text(delta="```mermaid\ngraph TD\n  A[Start] --> B[End]\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _mounted_child_types(block=block) == [AnswerMarkdownPart],
            )
            assert _mounted_child_types(block=block) == [AnswerMarkdownPart]

            block.append_text(delta="```\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _mounted_child_types(block=block) == [MermaidChartBlock],
            )

            assert _mounted_child_types(block=block) == [MermaidChartBlock]
            assert _answer_charts(block=block)[0].source == _MERMAID_SOURCE

    @pytest.mark.asyncio
    async def test_completed_answer_without_the_fence_replaces_the_chart_with_prose(self) -> None:
        """A mounted chart child is torn down when its segment turns into text.

        WHAT: Replaces a fence-only answer with prose-only completed truth, so
            the segment at index 0 changes kind from ``mermaid`` to ``text``.
            That is the one transition only the kind check in
            ``_reusable_prefix_length`` catches: the content check beside it
            fires solely for ``mermaid`` segments, so without the kind check
            the chart card would be "reused" for a prose segment and stay on
            screen showing the withdrawn diagram.
        WHO: Guards the terminal ``set_answer`` seam, which replaces streamed
            text with the completed answer wholesale.
        WHEN: A terminal event supplies completed text that no longer holds
            the fence the stream had shown.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.set_answer(content=_MERMAID_FENCE)
            await pump_until(
                pilot=pilot,
                predicate=lambda: _mounted_child_types(block=block) == [MermaidChartBlock],
            )
            assert _mounted_child_types(block=block) == [MermaidChartBlock]

            block.set_answer(content="No diagram after all.\n")
            await pump_until(
                pilot=pilot,
                predicate=lambda: _mounted_child_types(block=block) == [AnswerMarkdownPart],
            )

            assert _mounted_child_types(block=block) == [AnswerMarkdownPart]
            assert _answer_parts(block=block)[0].raw_text == "No diagram after all.\n"


class TestSegmentedAnswerReconciliationTransaction:
    """Reconciliation is one serialized, cancellable DOM transaction (spec 77.a.3)."""

    @pytest.mark.asyncio
    async def test_reconciliation_when_two_flushes_arrive_before_prior_removals_settle_preserves_final_segment_order(
        self,
    ) -> None:
        """Two flushes in one tick settle to exactly the final segment list, in order.

        ``Widget.remove`` returns an awaitable and leaves the child in
        ``self.children`` until the next event cycle, while ``Widget.mount``
        registers immediately — so overlapping transactions would slice
        ``self.children`` against a stale snapshot and leave missing,
        duplicate, or stale children behind.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.set_answer(content=f"intro\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(block._answer_body.children) == 2)

            block.set_answer(content="intro\n\n```mermaid\nflowchart LR\n  X --> Y\n```\n")
            block.set_answer(content=f"intro\n\n{_MERMAID_FENCE}\ntail prose\n")
            await pump_until(pilot=pilot, predicate=lambda: len(block._answer_body.children) == 3)

            assert _mounted_child_types(block=block) == [
                AnswerMarkdownPart,
                MermaidChartBlock,
                AnswerMarkdownPart,
            ]
            assert _answer_charts(block=block)[0].source == _MERMAID_SOURCE
            assert _answer_parts(block=block)[0].raw_text == "intro\n\n"
            assert _answer_parts(block=block)[1].raw_text == "\ntail prose\n"

    @pytest.mark.asyncio
    async def test_answer_surface_reconciliation_worker_is_cancelled_on_block_unmount(self) -> None:
        """The body owns its worker, so unmounting the block tears that worker down."""
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()

            block.set_answer(content=f"intro\n\n{_MERMAID_FENCE}")
            started_worker: Optional[Worker[None]] = block._answer_body._reconcile_worker
            assert started_worker is not None

            await block.remove()
            await pilot.pause()

            assert block._answer_body._reconcile_worker is None
            assert started_worker.is_running is False


class TestSegmentedAnswerScrollFollow:
    """The asynchronous DOM growth re-arms scroll-follow (spec 77.a.3)."""

    @pytest.mark.asyncio
    async def test_streaming_answer_keeps_transcript_pinned_to_bottom(self) -> None:
        """Streaming prose plus a closed fence leaves the transcript at the bottom.

        The answer surface now grows its DOM asynchronously, so
        ``_flush_dirty_regions``'s synchronous ``Rendered`` post lands
        *before* the height change; the reconciliation re-posts ``Rendered``
        after its transaction so the re-pin never reads a stale height. This
        test pins the user-visible outcome — the transcript stays at the
        bottom while an answer containing a chart streams in.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(80, 12)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()
            scroll: Optional[VerticalScroll] = app._transcript_scroll
            assert scroll is not None

            for index in range(12):
                block.append_text(delta=f"prose line {index}\n\n")
                await pilot.pause()
            block.append_text(delta=_MERMAID_FENCE)

            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)
            await pump_until(
                pilot=pilot,
                predicate=lambda: scroll.max_scroll_y > 0 and (scroll.max_scroll_y - scroll.scroll_y) <= 1.0,
            )

            assert scroll.max_scroll_y > 0
            assert (scroll.max_scroll_y - scroll.scroll_y) <= 1.0

    @pytest.mark.asyncio
    async def test_reconciliation_posts_rendered_after_the_chart_is_mounted(self) -> None:
        """The answer body re-posts ``Rendered`` once its chart card is mounted.

        WHAT: Records who posted each ``Rendered`` and how many answer
            children existed AT POST TIME. The block's synchronous
            ``_flush_dirty_regions`` post is made before the worker mounts
            anything (asserted here, so the discrimination is not assumed);
            only the reconciliation's own re-post can be made with the chart
            card already in the DOM.
        WHO: Guards the re-post in
            ``AssistantAnswerBody._drain_reconciliations``. The scroll-outcome
            test above pins the user-visible result but not which widget
            re-armed it, so it cannot stand in for this.
        WHEN: While an answer containing a closed mermaid fence streams in.

        The counts are read at post time, not in the app's handler: message
        handling lags the DOM transaction, so by handling time BOTH posts see
        the mounted card and nothing discriminates.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(80, 12)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()
            body: Widget = block._answer_body
            posts: list[tuple[str, int]] = []
            recorded: set[int] = set()

            def build_post_recorder(
                *, poster: str, forward: Callable[[Message], bool]
            ) -> Callable[[Message], bool]:
                """Wrap one widget's ``post_message`` to log its ``Rendered`` posts.

                Args:
                    poster (str): Name recorded for the posting widget.
                    forward (Callable[[Message], bool]): The widget's real
                        ``post_message``.

                Returns:
                    Callable[[Message], bool]: The recording replacement.
                """

                def record_post(message: Message) -> bool:
                    """Log the answer-child count, then post for real.

                    Each message is logged once, against the first widget that
                    posts it: Textual bubbles the body's post up through the
                    block, which would otherwise log it a second time.

                    Args:
                        message (Message): The message being posted.

                    Returns:
                        bool: Whatever the real ``post_message`` returned.
                    """
                    if isinstance(message, AssistantStreamBlock.Rendered) and id(message) not in recorded:
                        recorded.add(id(message))
                        posts.append((poster, len(body.children)))
                    return forward(message)

                return record_post

            record_block_post: Callable[[Message], bool] = build_post_recorder(
                poster="block", forward=block.post_message
            )
            record_body_post: Callable[[Message], bool] = build_post_recorder(
                poster="body", forward=body.post_message
            )
            block.post_message = record_block_post  # type: ignore[method-assign]
            body.post_message = record_body_post  # type: ignore[method-assign]

            block.append_text(delta=f"Here is the flow:\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)
            await pilot.pause()

            children_at_block_posts: list[int] = [count for poster, count in posts if poster == "block"]

            assert children_at_block_posts, "the flush never posted Rendered; the premise is untested"
            assert max(children_at_block_posts) < 2, "the flush post already saw the card"
            assert ("body", 2) in posts, "the reconciliation posted no Rendered after mounting the card"


class TestSegmentedAnswerSelection:
    """A real drag over a segmented answer still reaches the clipboard (spec 77.a.3)."""

    @pytest.mark.asyncio
    async def test_drag_over_segmented_answer_copies_raw_answer(self) -> None:
        """A drag across a segmented answer lands prose and mermaid source on the clipboard.

        The body became a container, and Textual's
        ``SelectState._walk_selected_widgets`` skips containers — so this
        only works because every answer part is a selectable leaf. Calling
        ``get_selection`` directly would prove nothing about reachability, so
        the interaction is driven through a real pilot drag.
        """
        app: SloTUI = SloTUI(session=_build_session())
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            block: AssistantStreamBlock = await app.mount_assistant_block()
            block.finalize(final_text=f"answer spans the block\n\n{_MERMAID_FENCE}")
            await pump_until(pilot=pilot, predicate=lambda: len(_answer_charts(block=block)) == 1)
            await pilot.pause()

            region = block.region
            assert region.area > 0
            start: tuple[int, int] = (region.x, region.y)
            end: tuple[int, int] = (region.x + region.width - 1, region.y + region.height - 1)

            await pilot.mouse_down(offset=start)
            await pilot.mouse_up(offset=end)
            await pilot.pause()

            selection: Optional[str] = app.screen.get_selected_text()
            assert selection is not None
            assert "answer spans the block" in selection
            assert "graph TD" in selection
            assert "A[Start] --> B[End]" in selection
            assert "ctrl+f for full screen" not in selection, "card chrome must never reach the clipboard"
            assert "📊 Mermaid chart" not in selection, "card chrome must never reach the clipboard"
            assert app._clipboard == selection
