"""Tests for the TUI transcript projector."""

from __future__ import annotations

import pytest

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.transcript_projector import TranscriptProjector


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
    """Minimal assistant block fake for projector tests."""

    def __init__(self) -> None:
        self.thinking: str = ""
        self.answer: str = ""
        self.finalized_with: str | None = None
        self.sealed: bool = False
        self.aborted: bool = False
        self.failed_with: str | None = None

    def append_thinking(self, *, delta: str) -> None:
        self.thinking += delta

    def set_thinking(self, *, content: str) -> None:
        self.thinking = content

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
        self.tool_blocks: dict[str, FakeToolBlock] = {}
        self.user_blocks: list[FakeUserBlock] = []
        self.separators: int = 0
        self.lines: list[tuple[str, str]] = []
        self.recorded: list[tuple[str, str]] = []

    async def mount_user_message_block(self, *, text: str):
        block = FakeUserBlock(text=text)
        self.user_blocks.append(block)
        return block

    def mount_turn_separator_if_needed(self) -> None:
        if any(classes != "turn-separator" for _content, classes in self.recorded):
            self.separators += 1
            self.recorded.append(("┈", "turn-separator"))

    async def mount_assistant_block(self, *, title_prefix=None):
        block = FakeAssistantBlock()
        block.title_prefix = title_prefix
        self.blocks.append(block)
        return block

    async def mount_tool_execution_block(self, *, tool_call_id: str, tool_name: str):
        block = FakeToolBlock(tool_call_id=tool_call_id, tool_name=tool_name)
        self.tool_blocks[tool_call_id] = block
        return block

    def write_transcript_line(self, *, content: str, classes: str) -> None:
        self.lines.append((content, classes))

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        self.recorded.append((content, classes))


class TestTranscriptProjector:
    """Streaming-block lifecycle and fallback rendering."""

    @pytest.mark.asyncio
    async def test_first_visible_delta_mounts_block(self) -> None:
        """The first visible delta mounts an assistant block and writes into it."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="working", iteration=0),
        )

        assert len(host.blocks) == 1
        assert host.blocks[0].thinking == "working"

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
            event=AgentStreamEventDAO(kind="thinking_delta", delta="Ineed", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_end", content="I need spacing.", iteration=0),
        )

        assert host.blocks[0].thinking == "I need spacing."

    @pytest.mark.asyncio
    async def test_second_thinking_end_with_content_repairs_malformed_concatenated_text(
        self,
    ) -> None:
        """A second thinking_end carrying content replaces the malformed concatenated thinking text.

        This exercises the end-to-end repair path: deltas accumulate without
        spaces, the first (contentless) thinking_end is a no-op, then the
        repair thinking_end emitted by finalize_open_blocks replaces the
        malformed text with the provider's correctly formatted truth.
        """
        host: FakeHost = FakeHost()
        projector: TranscriptProjector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="I", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="can", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="outline", iteration=0),
        )

        # The contentless implicit-close emitted by _emit_text_delta — must be a no-op.
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
            ),
        )

        assert host.blocks[0].thinking == "Icanoutline"

        # The repair event emitted by finalize_open_blocks.
        await projector.project(
            event=AgentStreamEventDAO(
                kind="thinking_end",
                iteration=0,
                block_id="thinking:0:0",
                content="I can outline.",
            ),
        )

        assert host.blocks[0].thinking == "I can outline."

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
            event=AgentStreamEventDAO(kind="thinking_delta", delta="", iteration=0),
        )
        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta=None, iteration=0),
        )

        assert host.blocks == []

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
        """Later assistant iterations mount new blocks instead of rewriting older ones."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="thinking_delta", delta="first", iteration=0),
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
            event=AgentStreamEventDAO(kind="thinking_delta", delta="second", iteration=1),
        )

        assert len(host.blocks) == 2
        assert host.blocks[0].thinking == "first"
        assert host.blocks[1].thinking == "second"

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

    def test_reset_for_new_run_clears_run_scoped_state(self) -> None:
        """Reset clears run-scoped assistant and tool state between prompts."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)
        projector._assistant_blocks = {0: FakeAssistantBlock()}  # type: ignore[attr-defined]
        projector._tool_blocks = {"call_1": FakeToolBlock(tool_call_id="call_1", tool_name="read")}  # type: ignore[attr-defined]

        projector.reset_for_new_run()

        assert projector._assistant_blocks == {}  # type: ignore[attr-defined]
        assert projector._tool_blocks == {}  # type: ignore[attr-defined]


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
        assert block.thinking == "why"
        assert block.finalized_with == "answer"
        assert block.aborted is False
        assert ("answer", "assistant-final") in host.recorded

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


class TestTranscriptProjectorSubAgentRouting:
    """Routing gate: ``is_sub_agent_event`` events never enter the orchestrator chain (03.c)."""

    @pytest.mark.asyncio
    async def test_sub_agent_text_delta_does_not_create_orchestrator_block(
        self,
    ) -> None:
        """A ``text_delta`` with ``sub_agent_id`` routes to a sub-agent block, not orchestrator."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="child output",
                sub_agent_id="s-abc",
                task_id="imports",
            )
        )

        # One block created for the sub-agent
        assert len(host.blocks) == 1
        assert host.blocks[0].title_prefix == "⎇ imports"
        # The orchestrator assistant blocks dict is empty
        assert len(projector._assistant_blocks) == 0
        # The sub-agent assistant blocks dict has one entry
        assert "imports" in projector._sub_agent_assistant_blocks

    @pytest.mark.asyncio
    async def test_orchestrator_text_delta_unaffected(self) -> None:
        """A ``text_delta`` without ``sub_agent_id`` still routes to orchestrator block."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(kind="text_delta", delta="orch output", iteration=0)
        )

        assert len(host.blocks) == 1
        # Sub-agent dicts untouched
        assert len(projector._sub_agent_assistant_blocks) == 0


class TestTranscriptProjectorLifecycleNotices:
    """Lifecycle notice lines rendered by ``_project_sub_agent_event`` (03.c)."""

    @pytest.mark.asyncio
    async def test_sub_agent_spawned_writes_notice_line(self) -> None:
        """``sub_agent_spawned`` writes '⎇ task-1: spawned' to transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="sub_agent_spawned",
                sub_agent_id="s-1",
                task_id="task-1",
            )
        )

        assert ("⎇ task-1: spawned", "sub-agent-notice") in host.lines

    @pytest.mark.asyncio
    async def test_sub_agent_completed_writes_notice_line(self) -> None:
        """``sub_agent_completed`` writes '⎇ task-1: completed' to transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="sub_agent_completed",
                sub_agent_id="s-1",
                task_id="task-1",
            )
        )

        assert ("⎇ task-1: completed", "sub-agent-notice") in host.lines

    @pytest.mark.asyncio
    async def test_sub_agent_failed_writes_notice_line(self) -> None:
        """``sub_agent_failed`` writes '⎇ task-1: failed' to transcript."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="sub_agent_failed",
                sub_agent_id="s-1",
                task_id="task-1",
            )
        )

        assert ("⎇ task-1: failed", "sub-agent-notice") in host.lines


class TestTranscriptProjectorSubAgentBlocks:
    """Sub-agent block creation and caching (03.c)."""

    @pytest.mark.asyncio
    async def test_two_text_deltas_same_task_id_reuse_block(self) -> None:
        """Two ``text_delta`` events with the same ``task_id`` stream into one block."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="part1 ",
                sub_agent_id="s-1",
                task_id="t1",
            )
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="part2",
                sub_agent_id="s-1",
                task_id="t1",
            )
        )

        # Only one block mounted
        assert len(host.blocks) == 1
        assert host.blocks[0].answer == "part1 part2"

    @pytest.mark.asyncio
    async def test_different_task_ids_create_separate_blocks(self) -> None:
        """Two children with different ``task_id`` values get separate blocks."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="child A",
                sub_agent_id="s-1",
                task_id="taskA",
            )
        )
        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="child B",
                sub_agent_id="s-2",
                task_id="taskB",
            )
        )

        assert len(host.blocks) == 2

    @pytest.mark.asyncio
    async def test_reset_clears_sub_agent_blocks(self) -> None:
        """``reset_for_new_run`` clears sub-agent assistant and tool block dicts."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(
            event=AgentStreamEventDAO(
                kind="text_delta",
                delta="x",
                sub_agent_id="s-1",
                task_id="t1",
            )
        )
        assert len(projector._sub_agent_assistant_blocks) == 1

        projector.reset_for_new_run()

        assert len(projector._sub_agent_assistant_blocks) == 0
        assert len(projector._sub_agent_tool_blocks) == 0
        assert len(projector._sub_agent_argument_buffers) == 0


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
    async def test_compaction_failed_does_not_write_transcript_line(self) -> None:
        """compaction_failed is handled silently — the original error will surface."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        await projector.project(event=AgentStreamEventDAO(kind="compaction_failed"))

        assert len(host.lines) == 0, "compaction_failed must not add a transcript line"

    @pytest.mark.asyncio
    async def test_compaction_events_do_not_affect_assistant_blocks(self) -> None:
        """Compaction events must not mount assistant or tool blocks."""
        host = FakeHost()
        projector = TranscriptProjector(host=host)

        for kind in ("compaction_started", "compaction_completed", "compaction_retrying"):
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
