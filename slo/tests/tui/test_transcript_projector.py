"""Tests for the TUI transcript projector."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.transcript_projector import TranscriptProjector
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock


def _user_entry(*, content: str) -> TranscriptEntryDAO:
    """Build a replay user entry."""
    return TranscriptEntryDAO(kind="user", content=content)


def _assistant_entry(
    *,
    reasoning: str | None = None,
    answer: str | None = None,
    terminal_note: str | None = None,
) -> TranscriptEntryDAO:
    """Build a replay assistant entry."""
    return TranscriptEntryDAO(
        kind="assistant",
        reasoning=reasoning,
        answer=answer,
        terminal_note=terminal_note,
    )


def _tool_entry(*, tool_name: str, tool_input: dict, output: str) -> TranscriptEntryDAO:
    """Build a replay tool entry."""
    return TranscriptEntryDAO(
        kind="tool",
        tool_name=tool_name,
        tool_input=tool_input,
        output=output,
    )


class FakeAssistantBlock:
    """Minimal answer-only assistant block fake for projector tests."""

    def __init__(self) -> None:
        self.answer: str = ""
        self.title_prefix: str | None = None
        self.finalized_with: str | None = None
        self.sealed: bool = False
        self.aborted: bool = False
        self.failed_with: str | None = None

    @property
    def answer_text(self) -> str:
        return self.answer

    def append_text(self, *, delta: str) -> None:
        self.answer += delta

    def set_answer(self, *, content: str) -> None:
        self.answer = content

    def finalize(self, *, final_text: str) -> None:
        self.finalized_with = final_text

    def seal(self) -> None:
        self.sealed = True

    def mark_aborted(self) -> None:
        self.aborted = True

    def mark_failed(self, *, error_message: str) -> None:
        self.failed_with = error_message


class FakeThinkingBlock(AssistantStreamThinkingBlock):
    """Minimal thinking-segment block fake for projector tests.

    Subclasses the real widget so ``FakeHost.mount_thinking_block`` stays
    return-type compatible with ``TranscriptMountHost``; every method the
    projector touches is overridden and ``__init__`` deliberately skips
    ``super().__init__()`` so no Textual state is constructed.
    """

    def __init__(self) -> None:
        self.thinking: str = ""
        self.sealed: bool = False

    @property
    def thinking_text(self) -> str:
        return self.thinking

    @property
    def finalized(self) -> bool:
        return self.sealed

    def append_thinking(self, *, delta: str) -> None:
        self.thinking += delta

    def set_thinking(self, *, content: str) -> None:
        self.thinking = content

    def seal(self) -> None:
        self.sealed = True


class FakeToolBlock:
    """Minimal tool block fake for projector tests."""

    def __init__(self, *, tool_call_id: str, tool_name: str) -> None:
        self.tool_call_id: str = tool_call_id
        self.tool_name: str = tool_name
        self.tool_input: dict = {}
        self.result_output: str | None = None

    def update_tool_call(self, *, tool_name: str | None = None, tool_input: dict | None = None) -> None:
        if tool_name:
            self.tool_name = tool_name
        if tool_input is not None:
            self.tool_input = dict(tool_input)

    def update_result(self, *, tool_name: str | None, output: str) -> None:
        if tool_name:
            self.tool_name = tool_name
        self.result_output = output

    def mark_incomplete(self) -> None:
        self.result_output = None
        self.incomplete = True


class FakeUserBlock:
    """Minimal user block fake for projector tests."""

    def __init__(self, *, text: str) -> None:
        self.text: str = text


class FakeHost:
    """Minimal transcript host fake for projector tests."""

    def __init__(self) -> None:
        self.blocks: list[FakeAssistantBlock] = []
        self.thinking_blocks: list[FakeThinkingBlock] = []
        self.tool_blocks: dict[str, FakeToolBlock] = {}
        self.user_blocks: list[FakeUserBlock] = []
        self.mount_order: list[str] = []
        self.separators: int = 0
        self.lines: list[tuple[str, str]] = []
        self.recorded: list[tuple[str, str]] = []

    async def mount_user_message_block(self, *, text: str, before: int | None = None):
        del before
        block = FakeUserBlock(text=text)
        self.user_blocks.append(block)
        self.mount_order.append("user")
        return block

    def mount_turn_separator_if_needed(self, *, before: int | None = None) -> bool:
        del before
        if any(classes != "turn-separator" for _content, classes in self.recorded):
            self.separators += 1
            self.recorded.append(("┈", "turn-separator"))
            return True
        return False

    async def mount_assistant_block(self, *, title_prefix=None, before: int | None = None):
        del before
        block = FakeAssistantBlock()
        block.title_prefix = title_prefix
        self.blocks.append(block)
        self.mount_order.append("answer")
        return block

    async def mount_thinking_block(self, *, before: int | None = None) -> FakeThinkingBlock:
        """Build a fake mounted thinking segment.

        WHAT: Records thinking-block mount order and returns a controllable fake.
        WHO: ``TranscriptProjector`` calls this through the fake host in projector tests.
        WHEN: A tested parent ``thinking_delta`` first introduces a normalized block id.

        Args:
            before (int | None): Requested prepend index, when replay inserts content.

        Returns:
            FakeThinkingBlock: The fake segment used by assertions.
        """
        del before
        block: FakeThinkingBlock = FakeThinkingBlock()
        self.thinking_blocks.append(block)
        self.mount_order.append("thinking")
        return block

    async def mount_tool_execution_block(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        before: int | None = None,
    ):
        del before
        block = FakeToolBlock(tool_call_id=tool_call_id, tool_name=tool_name)
        self.tool_blocks[tool_call_id] = block
        self.mount_order.append("tool")
        return block

    def write_transcript_line(self, *, content: str, classes: str, before: int | None = None) -> None:
        del before
        self.lines.append((content, classes))

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        self.recorded.append((content, classes))


class TestTranscriptProjector:
    """Streaming-block lifecycle and fallback rendering."""

    @pytest.mark.asyncio
    async def test_first_visible_delta_mounts_block(self) -> None:
        """The first visible thinking delta mounts a thinking block and writes into it."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="working",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )

        assert len(host.thinking_blocks) == 1
        assert host.thinking_blocks[0].thinking == "working"
        assert host.blocks == []

    @pytest.mark.asyncio
    async def test_text_end_can_replace_partial_answer_with_completed_text(self) -> None:
        """Completed text-end content replaces partial streamed answer text."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="part", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_end", content="partial answer", iteration=0),
        )

        assert host.blocks[0].answer == "partial answer"

    @pytest.mark.asyncio
    async def test_thinking_end_can_replace_partial_reasoning_with_completed_text(self) -> None:
        """Completed thinking-end content replaces partial streamed reasoning text."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="Ineed",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                content="I need spacing.",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )

        assert host.thinking_blocks[0].thinking == "I need spacing."

    @pytest.mark.asyncio
    async def test_second_thinking_end_with_content_repairs_malformed_concatenated_text(
        self,
    ) -> None:
        """A second thinking_end carrying content replaces the malformed concatenated thinking text.

        This exercises the end-to-end repair path: deltas accumulate without
        spaces, the first (contentless) thinking_end is a no-op that leaves the
        segment open and live, then the repair thinking_end emitted by
        finalize_open_blocks replaces the malformed text with the provider's
        correctly formatted truth and seals the segment.
        """
        host: FakeHost = FakeHost()
        projector: TranscriptProjector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="I",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="can",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="outline",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )

        # The contentless implicit-close emitted by _emit_text_delta.
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )

        assert host.thinking_blocks[0].thinking == "Icanoutline"
        # A contentless end never seals: the segment stays live for its repair.
        assert host.thinking_blocks[0].sealed is False

        # The repair event emitted by finalize_open_blocks re-applies to the
        # original block_id widget.
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
                content="I can outline.",
            ),
        )

        assert host.thinking_blocks[0].thinking == "I can outline."
        assert host.thinking_blocks[0].sealed is True

    @pytest.mark.asyncio
    async def test_duplicate_content_bearing_thinking_end_does_not_mutate_sealed_segment(
        self,
    ) -> None:
        """A second content-bearing ``thinking_end`` never overwrites a sealed segment.

        Once a repair end seals the segment and retires its ``block_id`` from
        the open set, a duplicate or late end for the same id is a no-op —
        sealed reasoning is immutable.
        """
        host: FakeHost = FakeHost()
        projector: TranscriptProjector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta",
                delta="draft",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
                content="final",
            ),
        )

        assert host.thinking_blocks[0].sealed is True

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
                content="overwrite",
            ),
        )

        assert host.thinking_blocks[0].thinking == "final"
        assert host.thinking_blocks[0].sealed is True

    @pytest.mark.asyncio
    async def test_tool_call_delta_updates_tool_block_with_parsed_arguments(self) -> None:
        """Streamed tool-call JSON updates the live tool block before execution ends."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_start",
                tool_call_id="call_1",
                tool_name="read",
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_delta",
                tool_call_id="call_1",
                tool_name="read",
                tool_arguments_delta='{"path": "README.md"}',
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_end",
                tool_call_id="call_1",
                tool_name="read",
                tool_input={"path": "README.md"},
                iteration=0,
            ),
        )

        assert host.tool_blocks["call_1"].tool_input == {"path": "README.md"}
        assert host.recorded == [("⏺ read README.md", "tool-line")]

    @pytest.mark.asyncio
    async def test_tool_result_updates_live_tool_block_and_records_summary(self) -> None:
        """Matched tool results update the widget instead of writing duplicate log lines."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_start",
                tool_call_id="call_1",
                tool_name="read",
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_end",
                tool_call_id="call_1",
                tool_name="read",
                tool_input={"path": "README.md"},
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_result",
                tool_call_id="call_1",
                tool_name="read",
                content="line one\nline two",
                iteration=0,
            ),
        )

        assert host.lines == []
        assert host.tool_blocks["call_1"].result_output == "line one\nline two"
        assert host.recorded == [
            ("⏺ read README.md", "tool-line"),
            ("⎿ 2 lines · 0.0 KB", "tool-result"),
        ]

    @pytest.mark.asyncio
    async def test_tool_result_without_tool_block_writes_fallback_line(self) -> None:
        """Tool results without a live tool block fall back to append-only rendering."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_result",
                tool_name="read",
                content="line one\nline two",
                iteration=0,
            ),
        )

        assert host.lines == [("⎿ 2 lines · 0.0 KB", "tool-result")]

    @pytest.mark.asyncio
    async def test_run_completed_finalizes_block_with_completed_text(self) -> None:
        """Terminal completion finalizes with completed runtime truth."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="completed truth", iteration=0),
        )

        assert host.blocks[0].answer == "partial"
        assert host.blocks[0].finalized_with == "completed truth"
        assert host.recorded == [("completed truth", "assistant-final")]

    @pytest.mark.asyncio
    async def test_run_completed_without_visible_delta_mounts_terminal_only_block(self) -> None:
        """A terminal-only answer still renders through an assistant block."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="done", iteration=0),
        )

        assert len(host.blocks) == 1
        assert host.blocks[0].finalized_with == "done"
        assert host.recorded == [("done", "assistant-final")]

    @pytest.mark.asyncio
    async def test_empty_text_delta_does_not_mount_block(self) -> None:
        """An empty ``text_delta`` never mounts an orphaned empty block (spec 32.a)."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta=None, iteration=0),
        )

        assert host.blocks == []

    @pytest.mark.asyncio
    async def test_empty_thinking_delta_does_not_mount_block(self) -> None:
        """An empty ``thinking_delta`` never mounts an orphaned empty block (spec 32.a)."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="", iteration=0, block_id="thinking:0:0"),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta=None, iteration=0, block_id="thinking:0:0"
            ),
        )

        assert host.thinking_blocks == []

    @pytest.mark.asyncio
    async def test_run_completed_empty_content_seals_existing_block_without_clearing(self) -> None:
        """Empty completion seals a streamed block, preserving its text (spec 32.a)."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta", delta="I'll prepare the read call now.", iteration=0
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="", iteration=0),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[0].finalized_with is None
        assert host.blocks[0].answer == "I'll prepare the read call now."
        assert host.recorded == []

    @pytest.mark.asyncio
    async def test_run_completed_empty_content_without_block_creates_nothing(self) -> None:
        """Empty completion with no streamed block creates no empty block (spec 32.a)."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="", iteration=0),
        )

        assert host.blocks == []
        assert host.recorded == []

    @pytest.mark.asyncio
    async def test_second_iteration_mounts_a_new_assistant_block_in_order(self) -> None:
        """Later assistant iterations mount new answer blocks instead of rewriting older ones."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="first", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_start",
                tool_call_id="call_1",
                tool_name="read",
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="second", iteration=1),
        )

        assert len(host.blocks) == 2
        assert host.blocks[0].answer == "first"
        assert host.blocks[1].answer == "second"

    @pytest.mark.asyncio
    async def test_run_aborted_marks_active_block_and_records_terminal_line(self) -> None:
        """Abort preserves partial content and records the terminal marker."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_aborted", content="<aborted>", iteration=0),
        )

        assert host.blocks[0].aborted is True
        assert host.recorded == [("(aborted)", "assistant-aborted")]

    @pytest.mark.asyncio
    async def test_run_failed_marks_active_block_and_records_terminal_line(self) -> None:
        """Failures preserve partial content and record a one-line error marker."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_failed", content="boom", iteration=0),
        )

        assert host.blocks[0].failed_with == "boom"
        assert host.recorded == [("(error: boom)", "assistant-aborted")]

    @pytest.mark.asyncio
    async def test_run_failed_without_visible_delta_falls_back_to_line_render(self) -> None:
        """Failures before any visible delta still render an error line."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="run_failed", content="boom", iteration=0),
        )

        assert host.lines == [("(error: boom)", "assistant-aborted")]

    @pytest.mark.asyncio
    async def test_tool_call_start_does_not_mount_block(self) -> None:
        """tool_call_start alone must not mount a ToolExecutionBlock.

        The block must only be created when real tool data arrives
        via tool_call_delta or tool_call_end.
        """
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_start",
                tool_call_id="call_1",
                tool_name=None,
                iteration=0,
            ),
        )

        assert host.tool_blocks == {}
        assert host.lines == []
        assert host.recorded == []

    @pytest.mark.asyncio
    async def test_empty_tool_call_delta_does_not_mount_block(self) -> None:
        """An announcement-only tool_call_delta must not mount a blank block.

        The normalizer can emit a tool_call_delta carrying neither arguments
        nor parsed input (the provider's tool-call announcement chunk). The
        block must only appear once real tool data arrives, via a contentful
        tool_call_delta or tool_call_end.
        """
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_delta",
                tool_call_id="call_1",
                tool_name="read",
                tool_arguments_delta="",
                iteration=0,
            ),
        )

        assert host.tool_blocks == {}
        assert host.lines == []
        assert host.recorded == []

        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_end",
                tool_call_id="call_1",
                tool_name="read",
                tool_input={"path": "README.md"},
                iteration=0,
            ),
        )

        assert list(host.tool_blocks) == ["call_1"]
        assert host.tool_blocks["call_1"].tool_input == {"path": "README.md"}

    def test_reset_for_new_run_clears_run_scoped_state(self) -> None:
        """Reset clears run-scoped assistant, thinking, and tool state between prompts."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)
        projector._assistant_blocks = {0: FakeAssistantBlock()}  # type: ignore[attr-defined]
        projector._tool_blocks = {"call_1": FakeToolBlock(tool_call_id="call_1", tool_name="read")}  # type: ignore[attr-defined]
        projector._thinking_blocks = {"thinking:0:0": FakeThinkingBlock()}
        projector._thinking_block_iterations = {"thinking:0:0": 0}
        projector._open_thinking_block_ids = {"thinking:0:0"}

        projector.reset_for_new_run()

        assert projector._assistant_blocks == {}  # type: ignore[attr-defined]
        assert projector._tool_blocks == {}  # type: ignore[attr-defined]
        assert projector._thinking_blocks == {}  # type: ignore[attr-defined]
        assert projector._thinking_block_iterations == {}
        assert projector._open_thinking_block_ids == set()

    # -- 61.a.1: _seal_stale_assistant_blocks direct decision-point coverage --

    @pytest.mark.asyncio
    async def test_seal_stale_assistant_blocks_seals_every_block_except_the_named_iteration(
        self,
    ) -> None:
        """The sweep seals every tracked block except the exempt iteration."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="b", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="c", iteration=2),
        )

        projector._seal_stale_assistant_blocks(except_iteration=2)  # type: ignore[attr-defined]

        assert host.blocks[0].sealed is True
        assert host.blocks[1].sealed is True
        assert host.blocks[2].sealed is False

    @pytest.mark.asyncio
    async def test_seal_stale_assistant_blocks_seals_nothing_when_only_the_named_iteration_is_tracked(
        self,
    ) -> None:
        """The sweep is a guaranteed no-op when only the exempt iteration is tracked."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )

        projector._seal_stale_assistant_blocks(except_iteration=0)  # type: ignore[attr-defined]

        assert host.blocks[0].sealed is False

    # -- 61.a.1: _finalize_completed_run call-site tests --

    @pytest.mark.asyncio
    async def test_run_completed_empty_content_seals_prior_iteration_via_sweep_when_no_new_block_created(
        self,
    ) -> None:
        """The run-end sweep seals a prior iteration even when D2 never fires for the terminal one."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0),
        )
        # No delta was ever sent for iteration=1, so _ensure_assistant_block is
        # never called for it and D2 never fires for this run.
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert len(host.blocks) == 1

    @pytest.mark.asyncio
    async def test_run_completed_with_content_seals_every_other_tracked_block(self) -> None:
        """A confirmed-text completion seals every other tracked block via the sweep."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="b", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="final answer", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[1].finalized_with == "final answer"
        assert host.blocks[1].sealed is False

    # -- 61.a.1: _finalize_aborted_run call-site tests --

    @pytest.mark.asyncio
    async def test_run_aborted_seals_every_other_tracked_block(self) -> None:
        """Abort seals every other tracked block while marking the current one aborted."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="b", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_aborted", content="<aborted>", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[1].aborted is True
        assert host.blocks[1].sealed is False

    @pytest.mark.asyncio
    async def test_run_aborted_seals_prior_iteration_when_the_current_iteration_has_no_block(
        self,
    ) -> None:
        """The sweep reaches a prior iteration even on the no-current-block fallback branch."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_aborted", content="<aborted>", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert ("(aborted)", "assistant-aborted") in host.lines

    # -- 61.a.1: _finalize_failed_run call-site tests --

    @pytest.mark.asyncio
    async def test_run_failed_seals_every_other_tracked_block(self) -> None:
        """Failure seals every other tracked block while marking the current one failed."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="b", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_failed", content="boom", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[1].failed_with == "boom"
        assert host.blocks[1].sealed is False

    @pytest.mark.asyncio
    async def test_run_failed_seals_prior_iteration_when_the_current_iteration_has_no_block(
        self,
    ) -> None:
        """The sweep reaches a prior iteration even on the no-current-block fallback branch."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_failed", content="boom", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert ("(error: boom)", "assistant-aborted") in host.lines

    # -- 61.a.1: sweep runs before the dict is cleared for the next prompt --

    @pytest.mark.asyncio
    async def test_reset_for_new_run_starts_the_next_prompt_with_no_stale_entries_after_a_sweep(
        self,
    ) -> None:
        """Reset genuinely clears the dict after a sweep-then-terminal-event cycle."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="a", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="b", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="done", iteration=1),
        )

        projector.reset_for_new_run()

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="next", iteration=0),
        )

        assert len(host.blocks) == 3
        assert host.blocks[2] is not host.blocks[0]
        assert host.blocks[2] is not host.blocks[1]

    # -- 61.a.2: seal-on-advance in _ensure_assistant_block --

    @pytest.mark.asyncio
    async def test_ensure_assistant_block_seals_the_previous_block_when_a_second_iteration_mounts(
        self,
    ) -> None:
        """Mounting a second iteration's block seals the block it supersedes."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="first", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="second", iteration=1),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[1].sealed is False
        assert len(host.blocks) == 2

    @pytest.mark.asyncio
    async def test_ensure_assistant_block_leaves_earlier_sealed_blocks_untouched_when_a_third_iteration_mounts(
        self,
    ) -> None:
        """A third iteration's mount re-seals an already-sealed earlier block without error."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="first", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="second", iteration=1),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="third", iteration=2),
        )

        assert host.blocks[0].sealed is True
        assert host.blocks[1].sealed is True
        assert host.blocks[2].sealed is False

    @pytest.mark.asyncio
    async def test_ensure_assistant_block_seals_nothing_when_the_iteration_block_already_exists(
        self,
    ) -> None:
        """The cache-hit branch returns early and does not re-run the sweep."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="first", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="second", iteration=1),
        )
        host.blocks[0].sealed = False
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="more", iteration=1),
        )

        assert host.blocks[0].sealed is False
        assert len(host.blocks) == 2


class TestThinkingSegmentRouting:
    """Normalized ``block_id`` owns thinking-segment identity (spec 72.a.2)."""

    @pytest.mark.asyncio
    async def test_thinking_delta_without_block_id_mounts_nothing(self) -> None:
        """A malformed thinking delta with no ``block_id`` is ignored, never guessed."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="orphan", iteration=0),
        )

        assert host.thinking_blocks == []
        assert host.blocks == []

    @pytest.mark.asyncio
    async def test_thinking_delta_with_same_block_id_reuses_the_mounted_block(self) -> None:
        """Two deltas for one normalized ``block_id`` stream into one widget."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="part1 ", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="part2", iteration=0, block_id="thinking:0:0"
            ),
        )

        assert len(host.thinking_blocks) == 1
        assert host.thinking_blocks[0].thinking == "part1 part2"

    @pytest.mark.asyncio
    async def test_two_thinking_block_ids_in_one_iteration_mount_separate_blocks_in_order(self) -> None:
        """Two normalized thinking blocks in one iteration mount as separate children."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="working", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="verify", iteration=0, block_id="thinking:0:1"
            ),
        )

        assert len(host.thinking_blocks) == 2
        assert host.thinking_blocks[0].thinking == "plan"
        assert host.thinking_blocks[1].thinking == "verify"
        assert host.mount_order == ["thinking", "answer", "thinking"]

    @pytest.mark.asyncio
    async def test_repair_thinking_end_after_answer_and_tool_updates_and_seals_the_original_block(
        self,
    ) -> None:
        """A late repair ``thinking_end`` targets its original ``block_id`` widget."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="I will", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_end",
                tool_call_id="call_1",
                tool_name="read",
                tool_input={"path": "a.py"},
                iteration=0,
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="verify", iteration=0, block_id="thinking:0:1"
            ),
        )

        # The repair end for t0 arrives after answer/tool/t1 output.
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
                content="plan files",
            ),
        )

        assert host.thinking_blocks[0].thinking == "plan files"
        assert host.thinking_blocks[0].sealed is True
        # The newer segment is untouched by the older id's end event.
        assert host.thinking_blocks[1].thinking == "verify"
        assert host.thinking_blocks[1].sealed is False

    @pytest.mark.asyncio
    async def test_thinking_end_with_unknown_block_id_cannot_mutate_a_newer_block(self) -> None:
        """An unknown ``block_id`` end event is a no-op, never applied to another block."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="verify", iteration=0, block_id="thinking:0:1"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:missing",
                content="bad",
            ),
        )

        assert len(host.thinking_blocks) == 1
        assert host.thinking_blocks[0].thinking == "verify"
        assert host.thinking_blocks[0].sealed is False

    @pytest.mark.asyncio
    async def test_thinking_end_without_block_id_is_ignored(self) -> None:
        """A malformed thinking end with no ``block_id`` cannot seal or mutate anything."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="verify", iteration=0, block_id="thinking:0:1"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_end", iteration=0, content="bad"),
        )

        assert host.thinking_blocks[0].thinking == "verify"
        assert host.thinking_blocks[0].sealed is False

    @pytest.mark.asyncio
    async def test_text_and_tool_events_do_not_seal_an_open_thinking_segment(self) -> None:
        """Answer/tool routing retains an open segment for its later repair end."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="I will", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="tool_call_end",
                tool_call_id="call_1",
                tool_name="read",
                tool_input={"path": "a.py"},
                iteration=0,
            ),
        )

        assert host.thinking_blocks[0].sealed is False

    @pytest.mark.asyncio
    async def test_run_completed_seals_every_retained_thinking_block(self) -> None:
        """Terminal completion settles all thinking segments before answer treatment."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="verify", iteration=0, block_id="thinking:0:1"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_completed", content="done", iteration=0),
        )

        assert host.thinking_blocks[0].sealed is True
        assert host.thinking_blocks[1].sealed is True
        assert projector._open_thinking_block_ids == set()

    @pytest.mark.asyncio
    async def test_run_aborted_seals_every_retained_thinking_block(self) -> None:
        """Terminal abort settles all thinking segments before answer treatment."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_aborted", content="<aborted>", iteration=0),
        )

        assert host.thinking_blocks[0].sealed is True
        assert projector._open_thinking_block_ids == set()

    @pytest.mark.asyncio
    async def test_run_failed_seals_every_retained_thinking_block(self) -> None:
        """Terminal failure settles all thinking segments before answer treatment."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_delta", delta="plan", iteration=0, block_id="thinking:0:0"
            ),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="run_failed", content="boom", iteration=0),
        )

        assert host.thinking_blocks[0].sealed is True
        assert projector._open_thinking_block_ids == set()


class TestTranscriptProjectorHasNoChildRoute:
    """The projector owns no parallel sub-agent transcript renderer (spec 72.a.2)."""

    def test_projector_has_no_sub_agent_route_or_registries(self) -> None:
        """All projector-side child rendering state and helpers are deleted."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        assert not hasattr(projector, "_project_sub_agent_event")
        assert not hasattr(projector, "_ensure_sub_agent_assistant_block")
        assert not hasattr(projector, "_ensure_sub_agent_tool_block")
        assert not hasattr(projector, "_sub_agent_assistant_blocks")
        assert not hasattr(projector, "_sub_agent_tool_blocks")
        assert not hasattr(projector, "_sub_agent_argument_buffers")

    def test_projector_has_no_seed_replay_reasoning_helper(self) -> None:
        """Replay reasoning mounts a real thinking block; the seeding shim is gone."""
        assert not hasattr(TranscriptProjector, "_seed_replay_reasoning")


class TestUserTurn:
    """``project_user_turn`` — live user-message component + separator."""

    @pytest.mark.asyncio
    async def test_user_turn_mounts_block_and_records_line(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_user_turn(text="hello **world**")

        assert [block.text for block in host.user_blocks] == ["hello **world**"]
        assert ("> hello **world**", "user-line") in host.recorded

    @pytest.mark.asyncio
    async def test_first_turn_has_no_separator_second_turn_does(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_user_turn(text="one")
        assert host.separators == 0

        await projector.project_user_turn(text="two")
        assert host.separators == 1


class TestProjectReplayEntry:
    """``project_replay_entry`` — replay mounts the same live components."""

    @pytest.mark.asyncio
    async def test_user_entry_mounts_user_block(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(entry=_user_entry(content="hi"))

        assert [block.text for block in host.user_blocks] == ["hi"]
        assert ("> hi", "user-line") in host.recorded

    @pytest.mark.asyncio
    async def test_completed_assistant_entry_finalizes_block(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=_assistant_entry(reasoning="why", answer="answer"),
        )

        block = host.blocks[-1]
        assert block.finalized_with == "answer"
        assert block.aborted is False
        assert ("answer", "assistant-final") in host.recorded

    @pytest.mark.asyncio
    async def test_replay_reasoning_mounts_a_sealed_thinking_block_before_the_answer_block(
        self,
    ) -> None:
        """Persisted reasoning mounts one sealed thinking block ahead of the answer."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=_assistant_entry(reasoning="why", answer="answer"),
        )

        assert len(host.thinking_blocks) == 1
        assert host.thinking_blocks[0].thinking == "why"
        assert host.thinking_blocks[0].sealed is True
        assert host.mount_order == ["thinking", "answer"]
        # The logical assistant line is recorded exactly once.
        assert host.recorded == [("answer", "assistant-final")]

    @pytest.mark.asyncio
    async def test_replay_assistant_entry_without_reasoning_mounts_answer_only(self) -> None:
        """An entry with no reasoning mounts no thinking block."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(entry=_assistant_entry(answer="answer"))

        assert host.thinking_blocks == []
        assert host.mount_order == ["answer"]
        assert host.blocks[-1].finalized_with == "answer"

    @pytest.mark.asyncio
    async def test_aborted_assistant_entry_marks_aborted_not_finalized(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=_assistant_entry(answer="partial", terminal_note="aborted"),
        )

        block = host.blocks[-1]
        assert block.aborted is True
        assert block.finalized_with is None  # finalize must not run on a terminated turn
        assert block.answer == "partial"
        assert ("(aborted)", "assistant-aborted") in host.recorded

    @pytest.mark.asyncio
    async def test_failed_assistant_entry_marks_failed(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=_assistant_entry(answer="partial", terminal_note="boom"),
        )

        block = host.blocks[-1]
        assert block.failed_with == "boom"
        assert block.finalized_with is None
        assert ("(failed: boom)", "assistant-aborted") in host.recorded

    @pytest.mark.asyncio
    async def test_tool_entry_mounts_and_records_two_lines(self) -> None:
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=_tool_entry(tool_name="read", tool_input={"path": "a.py"}, output="3 lines"),
        )

        tool_block = next(iter(host.tool_blocks.values()))
        assert tool_block.tool_name == "read"
        assert tool_block.result_output == "3 lines"
        classes = [classes for _content, classes in host.recorded]
        assert "tool-line" in classes
        assert "tool-result" in classes

    @pytest.mark.asyncio
    async def test_orphaned_tool_entry_marks_incomplete_and_records_note(self) -> None:
        """A replay tool entry with no recorded result renders an incomplete note, not a blank result."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        orphan: TranscriptEntryDAO = TranscriptEntryDAO(
            kind="tool",
            tool_name="bash",
            tool_input={"command": "readline"},
            output=None,
        )
        await projector.project_replay_entry(entry=orphan)

        tool_block = next(iter(host.tool_blocks.values()))
        assert getattr(tool_block, "incomplete", False) is True
        assert tool_block.result_output is None
        classes = [classes for _content, classes in host.recorded]
        assert "tool-call-incomplete" in classes
        assert "tool-result" not in classes


class TestCompactionEventProjection:
    """Transcript notices for compaction lifecycle events (spec 46.a.3)."""

    @pytest.mark.asyncio
    async def test_compaction_started_writes_transcript_line(self) -> None:
        """compaction_started writes a visible notice to the transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(event=AgentStreamEventDAO(kind="compaction_started"))

        assert len(host.lines) == 1
        content, classes = host.lines[0]
        assert "compact" in content.lower()

    @pytest.mark.asyncio
    async def test_compaction_completed_writes_transcript_line(self) -> None:
        """compaction_completed writes a visible notice to the transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(event=AgentStreamEventDAO(kind="compaction_completed"))

        assert len(host.lines) == 1
        content, _ = host.lines[0]
        assert "compaction" in content.lower()

    @pytest.mark.asyncio
    async def test_compaction_retrying_writes_transcript_line(self) -> None:
        """compaction_retrying writes a visible notice to the transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(event=AgentStreamEventDAO(kind="compaction_retrying"))

        assert len(host.lines) == 1
        content, _ = host.lines[0]
        assert "retry" in content.lower()

    @pytest.mark.asyncio
    async def test_compaction_failed_with_content_writes_safe_notice(self) -> None:
        """compaction_failed with content writes exactly one safe notice."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="compaction_failed",
                content="RuntimeError: Unsupported parameter: max_output_tokens",
            )
        )

        assert len(host.lines) == 1
        content, _ = host.lines[0]
        assert "compaction failed" in content.lower()
        assert "Unsupported parameter: max_output_tokens" in content

    @pytest.mark.asyncio
    async def test_compaction_failed_without_content_writes_fallback_notice(self) -> None:
        """compaction_failed without content keeps the terse fallback notice."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(event=AgentStreamEventDAO(kind="compaction_failed"))

        assert len(host.lines) == 1
        content, _ = host.lines[0]
        assert content == "(compaction failed)"

    @pytest.mark.asyncio
    async def test_compaction_events_do_not_affect_assistant_blocks(self) -> None:
        """Compaction events must not mount assistant or tool blocks."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        for kind in (
            "compaction_started",
            "compaction_completed",
            "compaction_retrying",
            "compaction_failed",
        ):
            await projector.project(event=AgentStreamEventDAO(kind=kind))  # type: ignore[arg-type]

        assert len(host.blocks) == 0, "no assistant blocks should be mounted"
        assert len(host.tool_blocks) == 0, "no tool blocks should be mounted"

    @pytest.mark.asyncio
    async def test_compaction_sequence_produces_ordered_transcript_lines(self) -> None:
        """The full compaction cycle writes transcript lines in the correct order."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        for kind in ("compaction_started", "compaction_completed", "compaction_retrying"):
            await projector.project(event=AgentStreamEventDAO(kind=kind))  # type: ignore[arg-type]

        assert len(host.lines) == 3
        assert "compact" in host.lines[0][0].lower()
        assert "retry" in host.lines[2][0].lower()


class TestProjectReplayNote:
    """``kind="note"`` replay entries render as one-line notices (spec 57.a.4)."""

    @pytest.mark.asyncio
    async def test_note_entry_writes_sub_agent_notice_line(self) -> None:
        """A replayed workflow note re-renders the live ``⊛`` line."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=TranscriptEntryDAO(kind="note", content="⊛ [workflow wf-3f2a] phase 1: COMPLETE"),
        )

        assert ("⊛ [workflow wf-3f2a] phase 1: COMPLETE", "sub-agent-notice") in host.lines

    @pytest.mark.asyncio
    async def test_replay_passes_before_to_user_separator_and_block(self) -> None:
        """A replayed user turn forwards the prepend index through its separator and widget mounts."""
        host = FakeHost()
        recorded_before: list[int | None] = []
        original_separator = host.mount_turn_separator_if_needed
        original_mount = host.mount_user_message_block

        def _record_separator(*, before: int | None = None) -> bool:
            recorded_before.append(before)
            return original_separator(before=before)

        async def _record_user_mount(*, text: str, before: int | None = None) -> FakeUserBlock:
            recorded_before.append(before)
            return await original_mount(text=text, before=before)

        host.mount_turn_separator_if_needed = _record_separator  # type: ignore[method-assign]
        host.mount_user_message_block = _record_user_mount  # type: ignore[method-assign]
        projector = TranscriptProjector(host=host)
        await projector.project_user_turn(text="prior turn")

        recorded_before.clear()
        await projector.project_replay_entry(entry=_user_entry(content="older turn"), before=1)

        assert recorded_before == [1, 1]

    @pytest.mark.asyncio
    async def test_replay_passes_before_to_note_write(self) -> None:
        """A replayed note forwards the prepend index through the raw transcript write path."""
        host = FakeHost()
        recorded_before: list[int | None] = []
        original_write = host.write_transcript_line

        def _record_write(*, content: str, classes: str, before: int | None = None) -> None:
            recorded_before.append(before)
            original_write(content=content, classes=classes, before=before)

        host.write_transcript_line = _record_write  # type: ignore[method-assign]
        projector = TranscriptProjector(host=host)

        await projector.project_replay_entry(
            entry=TranscriptEntryDAO(kind="note", content="older note"),
            before=1,
        )

        assert recorded_before == [1]
