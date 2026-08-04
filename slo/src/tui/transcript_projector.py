"""Stateful projector from ``AgentStreamEventDAO`` to transcript widgets."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional, Protocol

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.event_renderer import format_tool_call_headline, format_tool_result_line
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.user_message_block import UserMessageBlock

__all__ = ["TranscriptMountHost", "TranscriptProjector"]


_ABORTED_TERMINAL_NOTE: str = "aborted"
"""Replay terminal-note value marking an aborted assistant turn."""


class TranscriptMountHost(Protocol):
    """Minimal app surface the projector depends on."""

    async def mount_user_message_block(
        self,
        *,
        text: str,
        before: Optional[int] = None,
    ) -> UserMessageBlock:
        """Mount and return a fresh user message block."""
        ...

    def mount_turn_separator_if_needed(self, *, before: Optional[int] = None) -> bool:
        """Mount and record a turn separator when prior content exists."""
        ...

    async def mount_assistant_block(
        self,
        *,
        title_prefix: Optional[str] = None,
        before: Optional[int] = None,
    ) -> AssistantStreamBlock:
        """Mount and return a fresh assistant block.

        Args:
            title_prefix (Optional[str]): Optional dim label above content.
                Used by the sub-agent path to tag child output with task id.
        """
        ...

    async def mount_tool_execution_block(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        before: Optional[int] = None,
    ) -> ToolExecutionBlock:
        """Mount and return a fresh tool execution block."""
        ...

    def write_transcript_line(
        self,
        *,
        content: str,
        classes: str,
        before: Optional[int] = None,
    ) -> None:
        """Write an append-only line to the transcript and logical log."""
        ...

    def record_transcript_line(self, *, content: str, classes: str) -> None:
        """Record a logical transcript line without rendering a duplicate widget line."""
        ...


class TranscriptProjector:
    """Project normalized stream events into transcript widget updates.

    Assistant reasoning / answer content must stay in chronological transcript
    order. A single prompt can span multiple outer-loop assistant iterations,
    so the projector maintains one ``AssistantStreamBlock`` per iteration
    instead of mutating the very first block for the entire run.
    """

    def __init__(self, *, host: TranscriptMountHost) -> None:
        """Store the app/host collaboration seam.

        Args:
            host (TranscriptMountHost): App-level host used for mounting
                widgets and writing fallback transcript lines.
        """
        self._host: TranscriptMountHost = host
        self._assistant_blocks: dict[int, AssistantStreamBlock] = {}
        self._tool_blocks: dict[str, ToolExecutionBlock] = {}
        self._tool_argument_buffers: dict[str, str] = {}
        self._recorded_tool_calls: set[str] = set()
        # Sub-agent routing state (sub-spec 03.c):
        self._sub_agent_assistant_blocks: dict[str, AssistantStreamBlock] = {}
        self._sub_agent_tool_blocks: dict[str, ToolExecutionBlock] = {}
        self._sub_agent_argument_buffers: dict[str, str] = {}
        self._replay_projectors: dict[str, Callable[..., Awaitable[None]]] = {
            "user": self._project_replay_user,
            "assistant": self._project_replay_assistant,
            "tool": self._project_replay_tool,
            "note": self._project_replay_note,
        }

    def reset_for_new_run(self) -> None:
        """Reset run-scoped projector state before a new prompt starts."""
        self._assistant_blocks.clear()
        self._tool_blocks.clear()
        self._tool_argument_buffers.clear()
        self._recorded_tool_calls.clear()
        self._sub_agent_assistant_blocks.clear()
        self._sub_agent_tool_blocks.clear()
        self._sub_agent_argument_buffers.clear()

    async def project(self, *, event: AgentStreamEventDAO) -> None:
        """Apply one normalized stream event to the transcript.

        Sub-agent events (``event.is_sub_agent_event is True``) are intercepted
        first and dispatched to ``_project_sub_agent_event`` so the existing
        orchestrator kind-chain is never entered for child events.

        Args:
            event (AgentStreamEventDAO): Normalized stream event.
        """
        if event.is_sub_agent_event:
            await self._project_sub_agent_event(event=event)
            return

        if event.kind == "thinking_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            thinking_block: AssistantStreamBlock = await self._ensure_assistant_block(
                iteration=event.iteration,
            )
            thinking_block.append_thinking(delta=event.delta or "")
            return

        if event.kind == "thinking_end":
            maybe_thinking_block: AssistantStreamBlock | None = self._assistant_blocks.get(event.iteration)
            if maybe_thinking_block is not None and event.content:
                maybe_thinking_block.set_thinking(content=event.content)
            return

        if event.kind == "text_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            answer_block: AssistantStreamBlock = await self._ensure_assistant_block(
                iteration=event.iteration
            )
            answer_block.append_text(delta=event.delta or "")
            return

        if event.kind == "text_end":
            maybe_answer_block: AssistantStreamBlock | None = self._assistant_blocks.get(event.iteration)
            if maybe_answer_block is not None and event.content:
                maybe_answer_block.set_answer(content=event.content)
            return

        if event.kind == "tool_call_start":
            return

        if event.kind == "tool_call_delta":
            tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
            delta_tool_block: ToolExecutionBlock = await self._ensure_tool_block(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name or "tool",
            )
            if event.tool_arguments_delta:
                self._tool_argument_buffers[tool_call_id] = (
                    self._tool_argument_buffers.get(tool_call_id, "") + event.tool_arguments_delta
                )
            parsed_input: dict[str, Any] = event.tool_input or self._best_effort_parse_tool_input(
                raw_arguments=self._tool_argument_buffers.get(tool_call_id, ""),
            )
            delta_tool_block.update_tool_call(
                tool_name=event.tool_name,
                tool_input=parsed_input,
            )
            return

        if event.kind == "tool_call_end":
            tool_call_id = event.tool_call_id or event.block_id or "tool-call"
            final_tool_block: ToolExecutionBlock = await self._ensure_tool_block(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name or "tool",
            )
            parsed_input = event.tool_input or self._best_effort_parse_tool_input(
                raw_arguments=self._tool_argument_buffers.get(tool_call_id, ""),
            )
            final_tool_block.update_tool_call(
                tool_name=event.tool_name,
                tool_input=parsed_input,
            )
            self._record_tool_call(block=final_tool_block)
            return

        if event.kind == "tool_result":
            await self._project_tool_result(event=event)
            return

        if event.kind == "run_completed":
            await self._finalize_completed_run(
                iteration=event.iteration,
                content=event.content or "",
            )
            return

        if event.kind == "run_aborted":
            await self._finalize_aborted_run(iteration=event.iteration)
            return

        if event.kind == "run_failed":
            await self._finalize_failed_run(
                iteration=event.iteration,
                error_message=event.content or "unknown error",
            )
            return

        if event.kind == "compaction_started":
            self._host.write_transcript_line(
                content="(compacting session history)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_completed":
            self._host.write_transcript_line(
                content="(compaction complete)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_retrying":
            self._host.write_transcript_line(
                content="(retrying original message after compaction)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_failed":
            return

        if event.kind == "recovery_started":
            self._host.write_transcript_line(
                content="(recovering from error — trying another approach)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "recovery_succeeded":
            self._host.write_transcript_line(
                content="(recovered — continuing)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "recovery_exhausted":
            self._host.write_transcript_line(
                content="(could not recover automatically)",
                classes="assistant-aborted",
            )
            return

    async def project_user_turn(self, *, text: str, before: Optional[int] = None) -> None:
        """Mount one live user turn and record its logical line.

        Invoked by ``SloTUI._echo_user_line`` the moment a prompt is
        submitted, before the agent run starts. Mounts a dedicated
        ``UserMessageBlock`` (the visible content) and records the
        ``> text`` logical line for the copy/replay seam, with a turn
        separator ahead of it when prior content exists.

        Args:
            text (str): The raw user prompt text.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        self._host.mount_turn_separator_if_needed(before=before)
        await self._host.mount_user_message_block(text=text, before=before)
        self._host.record_transcript_line(content=f"> {text}", classes="user-line")

    async def project_replay_entry(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Mount one finalized transcript entry during session replay.

        Invoked once per completed entry by
        ``SloTUI._hydrate_transcript_from_history``. Dispatches on
        ``entry.kind`` through the replay table so a resumed session mounts
        the same components the live path mounts.

        Args:
            entry (TranscriptEntryDAO): One completed transcript entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        await self._replay_projectors[entry.kind](entry=entry, before=before)

    async def _project_replay_user(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Mount a replayed user turn via the shared user-turn path.

        Args:
            entry (TranscriptEntryDAO): A ``kind="user"`` entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        await self.project_user_turn(text=entry.content or "", before=before)

    async def _project_replay_assistant(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Mount a finalized assistant turn and record its logical line.

        Args:
            entry (TranscriptEntryDAO): A ``kind="assistant"`` entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        block: AssistantStreamBlock = await self._host.mount_assistant_block(before=before)
        self._seed_replay_reasoning(block=block, reasoning=entry.reasoning)
        content, classes = self._finalize_replay_assistant(block=block, entry=entry)
        self._host.record_transcript_line(content=content, classes=classes)

    async def _project_replay_note(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Write a replayed workflow note as a one-line notice (spec 57.a.4).

        Args:
            entry (TranscriptEntryDAO): A ``kind="note"`` entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        self._host.write_transcript_line(
            content=entry.content or "",
            classes="sub-agent-notice",
            before=before,
        )

    async def _project_replay_tool(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Mount a finalized tool execution and record its logical lines.

        Args:
            entry (TranscriptEntryDAO): A ``kind="tool"`` entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        block: ToolExecutionBlock = await self._host.mount_tool_execution_block(
            tool_call_id=self._replay_tool_call_id(entry=entry),
            tool_name=entry.tool_name or "tool",
            before=before,
        )
        block.update_tool_call(tool_name=entry.tool_name, tool_input=entry.tool_input)
        if entry.output is None:
            block.mark_incomplete()
        else:
            block.update_result(tool_name=entry.tool_name, output=entry.output)
        self._record_replay_tool_lines(entry=entry)

    @staticmethod
    def _seed_replay_reasoning(*, block: AssistantStreamBlock, reasoning: Optional[str]) -> None:
        """Seed a replayed assistant block's reasoning region, if any.

        Args:
            block (AssistantStreamBlock): The mounted assistant block.
            reasoning (Optional[str]): Completed reasoning summary text.
        """
        if not reasoning:
            return
        block.set_thinking(content=reasoning)

    @staticmethod
    def _finalize_replay_assistant(
        *,
        block: AssistantStreamBlock,
        entry: TranscriptEntryDAO,
    ) -> tuple[str, str]:
        """Apply a replayed turn's terminal state and return its logical line.

        ``finalize`` and ``mark_aborted``/``mark_failed`` are mutually
        exclusive — each sets the block's ``_finalized`` guard, so a
        terminated turn renders its partial answer then applies the note,
        while a clean turn finalizes. The returned pair is the logical line
        the copy/replay seam records.

        Args:
            block (AssistantStreamBlock): The mounted assistant block.
            entry (TranscriptEntryDAO): The assistant entry being replayed.

        Returns:
            tuple[str, str]: The ``(content, classes)`` logical line.
        """
        if entry.terminal_note == _ABORTED_TERMINAL_NOTE:
            block.set_answer(content=entry.answer or "")
            block.mark_aborted()
            return "(aborted)", "assistant-aborted"
        if entry.terminal_note:
            block.set_answer(content=entry.answer or "")
            block.mark_failed(error_message=entry.terminal_note)
            return f"(failed: {entry.terminal_note})", "assistant-aborted"
        block.finalize(final_text=entry.answer or "")
        return entry.answer or "", "assistant-final"

    def _record_replay_tool_lines(self, *, entry: TranscriptEntryDAO) -> None:
        """Record the headline and result logical lines for a tool entry.

        Args:
            entry (TranscriptEntryDAO): A ``kind="tool"`` entry.
        """
        self._host.record_transcript_line(
            content=ToolExecutionBlockCallFormatter.format(
                tool_name=entry.tool_name or "tool",
                tool_input=entry.tool_input,
            ),
            classes="tool-line",
        )
        if entry.output is None:
            self._host.record_transcript_line(
                content="⎿ no result recorded — this call may not have completed before the session ended",
                classes="tool-call-incomplete",
            )
            return
        self._host.record_transcript_line(
            content=ToolExecutionBlockResultFormatter.format(
                tool_name=entry.tool_name,
                output=entry.output,
            ),
            classes="tool-result",
        )

    @staticmethod
    def _replay_tool_call_id(*, entry: TranscriptEntryDAO) -> str:
        """Return a display-only tool-call id for a replayed tool block.

        Replay blocks are mounted directly (never cached or updated again),
        so this id only needs to be a stable label, not globally unique.

        Args:
            entry (TranscriptEntryDAO): A ``kind="tool"`` entry.

        Returns:
            str: A synthetic replay tool-call id.
        """
        return f"replay:{entry.iteration}:{entry.tool_name or 'tool'}"

    async def _project_sub_agent_event(
        self, *, event: AgentStreamEventDAO
    ) -> None:
        """Render one sub-agent event inline with a task-id prefix.

        Lifecycle events (``sub_agent_spawned``, ``sub_agent_completed``,
        ``sub_agent_failed``) produce a single notice line. Content events
        (``text_delta``, ``thinking_delta``, ``tool_call_*``, ``tool_result``)
        are routed to task-keyed blocks reusing the same widget types as the
        orchestrator path. All other event kinds are silently dropped.

        Args:
            event (AgentStreamEventDAO): A sub-agent stream event (guaranteed
                ``is_sub_agent_event is True``).
        """
        task_id: str = event.task_id or event.sub_agent_id or "sub-agent"

        if event.kind == "sub_agent_spawned":
            self._host.write_transcript_line(
                content=f"\u2387 {task_id}: spawned",
                classes="sub-agent-notice",
            )
            return

        if event.kind == "sub_agent_completed":
            self._host.write_transcript_line(
                content=f"\u2387 {task_id}: completed",
                classes="sub-agent-notice",
            )
            return

        if event.kind == "sub_agent_failed":
            self._host.write_transcript_line(
                content=f"\u2387 {task_id}: failed",
                classes="sub-agent-notice",
            )
            return

        if event.kind == "thinking_delta":
            block: AssistantStreamBlock = await self._ensure_sub_agent_assistant_block(
                task_id=task_id,
            )
            block.append_thinking(delta=event.delta or "")
            return

        if event.kind == "thinking_end":
            block = await self._ensure_sub_agent_assistant_block(task_id=task_id)
            if event.content:
                block.set_thinking(content=event.content)
            return

        if event.kind == "text_delta":
            block = await self._ensure_sub_agent_assistant_block(task_id=task_id)
            block.append_text(delta=event.delta or "")
            return

        if event.kind == "text_end":
            block = await self._ensure_sub_agent_assistant_block(task_id=task_id)
            if event.content:
                block.set_answer(content=event.content)
            return

        if event.kind in ("tool_call_delta", "tool_call_end"):
            composite_id: str = (
                f"{task_id}:{event.tool_call_id or event.block_id or 'tool'}"
            )
            tool_block: ToolExecutionBlock = await self._ensure_sub_agent_tool_block(
                composite_id=composite_id,
                tool_name=event.tool_name or "tool",
            )
            if event.tool_arguments_delta:
                self._sub_agent_argument_buffers[composite_id] = (
                    self._sub_agent_argument_buffers.get(composite_id, "")
                    + event.tool_arguments_delta
                )
            parsed_input: dict[str, Any] = event.tool_input or self._best_effort_parse_tool_input(
                raw_arguments=self._sub_agent_argument_buffers.get(composite_id, ""),
            )
            tool_block.update_tool_call(
                tool_name=event.tool_name,
                tool_input=parsed_input,
            )
            return

        if event.kind == "tool_result":
            composite_id = f"{task_id}:{event.tool_call_id or 'tool'}"
            if composite_id in self._sub_agent_tool_blocks:
                tool_block = self._sub_agent_tool_blocks.pop(composite_id)
                tool_block.update_result(
                    tool_name=event.tool_name,
                    output=event.content or "",
                )
                self._sub_agent_argument_buffers.pop(composite_id, None)
            return

        if event.kind == "run_completed":
            # Finalize the sub-agent block with the LLM-confirmed final text.
            # Without this, the AssistantStreamBlock remains in its "streaming"
            # state permanently since the pane projector never receives an
            # explicit finalize call from any other path.
            assistant_block = self._sub_agent_assistant_blocks.get(task_id)
            if assistant_block is not None:
                assistant_block.finalize(final_text=event.content or assistant_block.answer_text)
            return

        if event.kind == "run_aborted":
            assistant_block = self._sub_agent_assistant_blocks.get(task_id)
            if assistant_block is not None:
                assistant_block.mark_aborted()
            else:
                self._host.write_transcript_line(
                    content="(sub-agent aborted)",
                    classes="assistant-aborted",
                )
            return

        if event.kind == "run_failed":
            assistant_block = self._sub_agent_assistant_blocks.get(task_id)
            error: str = event.content or "unknown error"
            if assistant_block is not None:
                assistant_block.mark_failed(error_message=error)
            else:
                self._host.write_transcript_line(
                    content=f"(sub-agent error: {error})",
                    classes="assistant-aborted",
                )
            return

        # All other kinds (run_retrying, tool_call_start, etc.) are silently
        # dropped for sub-agent events. Terminal lifecycle state is communicated
        # via sub_agent_completed / sub_agent_failed lifecycle events.

    async def _ensure_sub_agent_assistant_block(
        self, *, task_id: str
    ) -> AssistantStreamBlock:
        """Return or mount the assistant block for ``task_id``.

        Sub-agent assistant blocks are keyed by ``task_id`` so all content
        events from one child task stream into the same block. Each block
        receives a ``\u2387 {task_id}`` title prefix so the user can tell
        which child produced which output.

        Args:
            task_id (str): Caller-assigned task identifier.

        Returns:
            AssistantStreamBlock: Mounted or cached sub-agent assistant block.
        """
        block: AssistantStreamBlock | None = self._sub_agent_assistant_blocks.get(task_id)
        if block is not None:
            return block
        block = await self._host.mount_assistant_block(
            title_prefix=f"\u2387 {task_id}",
        )
        self._sub_agent_assistant_blocks[task_id] = block
        return block

    async def _ensure_sub_agent_tool_block(
        self,
        *,
        composite_id: str,
        tool_name: str,
    ) -> ToolExecutionBlock:
        """Return or mount a tool execution block keyed by composite ``task_id:tool_call_id``.

        Args:
            composite_id (str): ``"{task_id}:{tool_call_id}"`` composite key.
            tool_name (str): Tool name for the block header.

        Returns:
            ToolExecutionBlock: Mounted or cached sub-agent tool block.
        """
        block: ToolExecutionBlock | None = self._sub_agent_tool_blocks.get(composite_id)
        if block is not None:
            return block
        block = await self._host.mount_tool_execution_block(
            tool_call_id=composite_id,
            tool_name=tool_name,
        )
        self._sub_agent_tool_blocks[composite_id] = block
        return block

    async def _ensure_assistant_block(self, *, iteration: int) -> AssistantStreamBlock:
        """Return the assistant block for ``iteration``.

        Each outer-loop assistant iteration owns its own transcript block so
        later thinking/text updates do not rewrite an older block above live
        tool output.

        Args:
            iteration (int): Outer-loop assistant iteration.

        Returns:
            AssistantStreamBlock: Mounted or cached assistant block.
        """
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is not None:
            return block
        block = await self._host.mount_assistant_block()
        self._assistant_blocks[iteration] = block
        return block

    async def _ensure_tool_block(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
    ) -> ToolExecutionBlock:
        """Return the mounted tool block for ``tool_call_id``.

        Args:
            tool_call_id (str): Stable tool call id.
            tool_name (str): Tool name.

        Returns:
            ToolExecutionBlock: Mounted or cached tool block.
        """
        block: ToolExecutionBlock | None = self._tool_blocks.get(tool_call_id)
        if block is not None:
            return block
        block = await self._host.mount_tool_execution_block(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        self._tool_blocks[tool_call_id] = block
        return block

    async def _project_tool_result(self, *, event: AgentStreamEventDAO) -> None:
        """Project one tool result into the live transcript.

        Args:
            event (AgentStreamEventDAO): Tool-result stream event.
        """
        tool_call_id: str | None = event.tool_call_id
        if tool_call_id is None or tool_call_id not in self._tool_blocks:
            self._host.write_transcript_line(
                content=ToolExecutionBlockResultFormatter.format(
                    tool_name=event.tool_name,
                    output=event.content or "",
                ),
                classes="tool-result",
            )
            return

        block: ToolExecutionBlock = self._tool_blocks.pop(tool_call_id)
        block.update_result(
            tool_name=event.tool_name,
            output=event.content or "",
        )
        self._record_tool_call(block=block)
        self._host.record_transcript_line(
            content=ToolExecutionBlockResultFormatter.format(
                tool_name=event.tool_name,
                output=event.content or "",
            ),
            classes="tool-result",
        )
        self._tool_argument_buffers.pop(tool_call_id, None)

    def _record_tool_call(self, *, block: ToolExecutionBlock) -> None:
        """Persist one logical tool-call line exactly once.

        Args:
            block (ToolExecutionBlock): Live tool block.
        """
        if block.tool_call_id in self._recorded_tool_calls:
            return
        self._host.record_transcript_line(
            content=ToolExecutionBlockCallFormatter.format(
                tool_name=block.tool_name,
                tool_input=block.tool_input,
            ),
            classes="tool-line",
        )
        self._recorded_tool_calls.add(block.tool_call_id)

    async def _finalize_completed_run(self, *, iteration: int, content: str) -> None:
        """Finalize the terminal assistant block for ``iteration``.

        Args:
            iteration (int): Outer-loop assistant iteration.
            content (str): Completed assistant answer text.
        """
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if not content:
            # No confirmed final text: seal any existing block without clearing
            # its streamed content, and never create a new empty block.
            if block is not None:
                block.seal()
            return
        # Confirmed final text: create the block when absent, then finalize it
        # with the LLM-confirmed text (authoritative over streamed deltas).
        if block is None:
            block = await self._ensure_assistant_block(iteration=iteration)
        block.finalize(final_text=content)
        self._host.record_transcript_line(content=content, classes="assistant-final")

    async def _finalize_aborted_run(self, *, iteration: int) -> None:
        """Finalize the current iteration block or render a fallback aborted line.

        Args:
            iteration (int): Outer-loop assistant iteration.
        """
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            self._host.write_transcript_line(
                content="(aborted)",
                classes="assistant-aborted",
            )
            return
        block.mark_aborted()
        self._host.record_transcript_line(
            content="(aborted)",
            classes="assistant-aborted",
        )

    async def _finalize_failed_run(self, *, iteration: int, error_message: str) -> None:
        """Finalize the current iteration block or render a fallback error line.

        Args:
            iteration (int): Outer-loop assistant iteration.
            error_message (str): One-line user-visible error summary.
        """
        rendered_error: str = f"(error: {error_message})"
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            self._host.write_transcript_line(
                content=rendered_error,
                classes="assistant-aborted",
            )
            return
        block.mark_failed(error_message=error_message)
        self._host.record_transcript_line(
            content=rendered_error,
            classes="assistant-aborted",
        )

    @staticmethod
    def _best_effort_parse_tool_input(*, raw_arguments: str) -> dict[str, Any]:
        """Parse streamed tool-call JSON when it is complete enough.

        Args:
            raw_arguments (str): Accumulated streamed JSON fragment.

        Returns:
            dict[str, Any]: Parsed args, or ``{}`` when incomplete.
        """
        if not raw_arguments:
            return {}
        try:
            parsed: object = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
        return {}


class ToolExecutionBlockCallFormatter:
    """Small adapter so the projector can reuse tool headline formatting."""

    @staticmethod
    def format(*, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Return the visible tool-call headline text.

        Args:
            tool_name (str): Tool name.
            tool_input (dict[str, Any]): Parsed args.

        Returns:
            str: Tool-call headline text.
        """
        return format_tool_call_headline(name=tool_name, tool_input=tool_input)


class ToolExecutionBlockResultFormatter:
    """Small adapter so the projector can reuse tool result formatting."""

    @staticmethod
    def format(*, tool_name: Optional[str], output: str) -> str:
        """Return the visible tool-result continuation text.

        Args:
            tool_name (Optional[str]): Tool name when known.
            output (str): Raw tool output.

        Returns:
            str: Tool-result continuation text.
        """
        return format_tool_result_line(name=tool_name, output=output)
