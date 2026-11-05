"""Stateful projector from ``AgentStreamEventDAO`` to transcript widgets."""

from __future__ import annotations

import asyncio
import json
from typing import Optional, Protocol, Self

from config.logger import log_warning
from src.tui.components.chat_transcript.commands import (
    ProjectionInput,
    ProjectUserTurnDAO,
    ProjectReplayEntryDAO,
)
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.tui.event_renderer import format_tool_call_headline, format_tool_result_line
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from src.tui.widgets.tool_execution_block import ToolExecutionBlock
from src.tui.widgets.user_message_block import UserMessageBlock

__all__ = ["TranscriptMountHost", "TranscriptProjectionAdapter"]


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

    async def mount_turn_separator_if_needed(self, *, before: Optional[int] = None) -> bool:
        """Mount and record a turn separator when prior content exists."""
        ...

    async def mount_assistant_block(
        self,
        *,
        title_prefix: Optional[str] = None,
        before: Optional[int] = None,
    ) -> AssistantStreamBlock:
        """Mount and return a fresh answer-only assistant block.

        Args:
            title_prefix (Optional[str]): Optional dim label above the answer
                content. The parent projector path never sets it; the parameter
                is retained for host-interface compatibility only.
        """
        ...

    async def mount_thinking_block(
        self,
        *,
        before: Optional[int] = None,
    ) -> AssistantStreamThinkingBlock:
        """Mount and return a fresh thinking-segment block.

        The only projector-to-app seam for mounting a new thinking widget.
        """
        ...

    async def mount_tool_execution_block(
        self,
        *,
        tool_call_id: str,
        tool_name: Optional[str],
        before: Optional[int] = None,
    ) -> ToolExecutionBlock:
        """Mount and return a fresh tool execution block."""
        ...

    async def mount_transcript_line(
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


class ReplayEntryProjector(Protocol):
    """One keyword-only replay operation stored in the projection dispatch table."""

    async def __call__(self, *, entry: TranscriptEntryDAO, before: Optional[int] = None) -> None:
        """Mount the supplied entry at the requested position, or append by default."""
        ...


class TranscriptProjectionAdapter:
    """Turn agent events into messages, thinking blocks, and tool output in the chat.

    Keep the displayed content in conversation order. Keep a separate answer
    block for each assistant iteration, and use each thinking block's ID to
    update the right block even when other output has appeared since then.
    The app routes child-agent events elsewhere; this adapter does not
    display their progress."""

    def __init__(self, *, host: TranscriptMountHost) -> None:
        """Save the interface used to add message widgets and record transcript text."""
        self._host: TranscriptMountHost = host
        self._delivery_closed = False
        self._delivery_lock = asyncio.Lock()
        self._projection_version = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._assistant_blocks: dict[int, AssistantStreamBlock] = {}
        self._thinking_blocks: dict[str, AssistantStreamThinkingBlock] = {}
        """Normalized thinking ``block_id`` to mounted widget for this prompt."""
        self._thinking_block_iterations: dict[str, int] = {}
        """Thinking ``block_id`` to outer iteration for diagnostics only."""
        self._open_thinking_block_ids: set[str] = set()
        """Normalized ids that may still receive their matching ``thinking_end``."""
        self._tool_blocks: dict[str, ToolExecutionBlock] = {}
        self._tool_argument_buffers: dict[str, str] = {}
        self._recorded_tool_calls: set[str] = set()
        self._replay_projectors: dict[str, ReplayEntryProjector] = {
            "user": self._project_replay_user,
            "assistant": self._project_replay_assistant,
            "tool": self._project_replay_tool,
            "note": self._project_replay_note,
        }

    @classmethod
    def register(cls, *, host: TranscriptMountHost) -> Self:
        """Return a fresh inactive projector borrowing the specialized mount host.

        Called during transcript construction, before mount or a running loop.
        No history is read and no widget or task is created by registration.

        Args:
            host: Destination for widgets and their logical transcript text.

        Returns:
            A fresh projector whose close leaves the host available.
        """
        return cls(host=host)

    async def handle(self, *, event: ProjectionInput) -> None:
        """Process live events, user messages, and saved-history entries one at a time."""
        self._ensure_projection_adapter_open()
        self._update_delivery_loop()
        projection_version = self._projection_version
        async with self._delivery_lock:
            self._ensure_projection_adapter_open()
            self._update_delivery_loop()
            if projection_version != self._projection_version:
                raise RuntimeError("Projection belongs to a retired presentation")
            match event:
                case AgentStreamEventDAO():
                    await self._project(event=event)
                case ProjectUserTurnDAO():
                    await self._project_user_turn(text=event.text, before=event.before)
                case ProjectReplayEntryDAO():
                    await self._project_replay_entry(entry=event.entry, before=event.before)
                case _:
                    raise TypeError(f"Unsupported projection event: {type(event).__name__}")

    def _ensure_projection_adapter_open(self) -> None:
        """Raise RuntimeError after close, before loop capture or target access."""
        if self._delivery_closed:
            raise RuntimeError("Transcript projection adapter is closed")

    def _update_delivery_loop(self) -> None:
        """Store the first delivery/reset loop; later calls must use that same loop.

        Registration is inert. The mounted owner, not this adapter, establishes
        UI-loop authority. Raise RuntimeError before changing a borrowed target
        when a later call arrives on a different loop.
        """
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        self._ensure_delivery_loop(loop=loop)

    def _ensure_delivery_loop(self, *, loop: asyncio.AbstractEventLoop) -> None:
        """Require the running loop to match this adapter's stored delivery loop."""
        if loop is not self._loop:
            raise RuntimeError("Transcript adapter delivery requires the UI loop")

    async def reset(self) -> None:
        """Wait for active display work and clear per-run tracking without closing the supplied host."""
        self._ensure_projection_adapter_open()
        self._update_delivery_loop()
        await self._retire(close=False)

    async def close(self) -> None:
        """Wait for accepted display work and clear tracking without closing the supplied host."""
        await self._retire(close=True)

    async def _retire(self, *, close: bool) -> None:
        """Finish cleanup before reporting cancellation, and allow failed cleanup to be retried."""
        self._delivery_closed = self._delivery_closed or close
        task = asyncio.create_task(self._finish_retirement())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _finish_retirement(self) -> None:
        """Wait for active widget updates before clearing the IDs used to track them."""
        async with self._delivery_lock:
            self._projection_version += 1
            self._reset_for_new_run()

    def _reset_for_new_run(self) -> None:
        """Clear per-run tracking before the next prompt starts."""
        self._assistant_blocks.clear()
        self._thinking_blocks.clear()
        self._thinking_block_iterations.clear()
        self._open_thinking_block_ids.clear()
        self._tool_blocks.clear()
        self._tool_argument_buffers.clear()
        self._recorded_tool_calls.clear()

    async def _project(self, *, event: AgentStreamEventDAO) -> None:
        """Display one parent-agent event.

        The app routes child-agent events elsewhere. Match thinking updates by
        their block ID, not by assistant iteration, so each update reaches the
        original thinking block.
        """
        if event.kind == "thinking_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            if not event.block_id:
                log_warning(
                    "TranscriptProjectionAdapter: ignoring thinking_delta with no block_id",
                    iteration=event.iteration,
                )
                return
            thinking_block: AssistantStreamThinkingBlock = await self._get_or_create_thinking_block(
                block_id=event.block_id,
                iteration=event.iteration,
            )
            thinking_block.append_thinking(delta=event.delta or "")
            return

        if event.kind == "thinking_end":
            if not event.block_id:
                log_warning(
                    "TranscriptProjectionAdapter: ignoring thinking_end with no block_id",
                    iteration=event.iteration,
                )
                return
            self._finalize_thinking_block(block_id=event.block_id, content=event.content)
            return

        if event.kind == "text_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            answer_block: AssistantStreamBlock = await self._get_or_create_assistant_block(
                iteration=event.iteration,
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
            if not event.tool_arguments_delta and not event.tool_input:
                return  # empty announcement delta — do not mount a blank block
            if not event.tool_name and event.tool_input is None:
                # If the tool name is not known yet, save the arguments and
                # wait for the name or the end of the call before adding a block.
                # This avoids showing a generic ``tool(command=...)`` headline.
                buffered_tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
                if event.tool_arguments_delta:
                    self._tool_argument_buffers[buffered_tool_call_id] = (
                        self._tool_argument_buffers.get(buffered_tool_call_id, "")
                        + event.tool_arguments_delta
                    )
                return
            tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
            delta_tool_block: ToolExecutionBlock = await self._get_or_create_tool_block(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name,
            )
            if event.tool_arguments_delta:
                self._tool_argument_buffers[tool_call_id] = (
                    self._tool_argument_buffers.get(tool_call_id, "") + event.tool_arguments_delta
                )
            parsed_input: dict[str, object] = event.tool_input or self._best_effort_parse_tool_input(
                raw_arguments=self._tool_argument_buffers.get(tool_call_id, ""),
            )
            delta_tool_block.update_tool_call(
                tool_name=event.tool_name,
                tool_input=parsed_input,
            )
            return

        if event.kind == "tool_call_end":
            if not event.tool_name and event.tool_call_id not in self._tool_blocks:
                # The call ended without a name and without a displayed
                # block, so there is nothing to finish or show.
                self._tool_argument_buffers.pop(event.tool_call_id or "", None)
                return
            tool_call_id = event.tool_call_id or event.block_id or "tool-call"
            final_tool_block: ToolExecutionBlock = await self._get_or_create_tool_block(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name,
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

        if event.kind == "tool_output_update":
            await self._project_tool_output_update(event=event)
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
            await self._host.mount_transcript_line(
                content="(compacting session history)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_completed":
            await self._host.mount_transcript_line(
                content="(compaction complete)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_retrying":
            await self._host.mount_transcript_line(
                content="(retrying original message after compaction)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "compaction_failed":
            await self._host.mount_transcript_line(
                content=(f"(compaction failed) {event.content}" if event.content else "(compaction failed)"),
                classes="assistant-aborted",
            )
            return

        if event.kind == "recovery_started":
            await self._host.mount_transcript_line(
                content="(recovering from error — trying another approach)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "recovery_succeeded":
            await self._host.mount_transcript_line(
                content="(recovered — continuing)",
                classes="assistant-aborted",
            )
            return

        if event.kind == "recovery_exhausted":
            await self._host.mount_transcript_line(
                content="(could not recover automatically)",
                classes="assistant-aborted",
            )
            return

    async def _project_tool_output_update(self, *, event: AgentStreamEventDAO) -> None:
        """Update the tool’s existing block with output received so far, before its final result arrives."""
        tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
        block: ToolExecutionBlock = await self._get_or_create_tool_block(
            tool_call_id=tool_call_id,
            tool_name=event.tool_name,
        )
        metadata: dict[str, object] = event.metadata or {}
        block.update_partial(
            snapshot=ToolOutputUpdateDAO.model_validate(
                {
                    "tool_call_id": tool_call_id,
                    # An empty name leaves the widget's unknown-name display unchanged.
                    "tool_name": event.tool_name or block.tool_name or "",
                    "content_snapshot": event.content or "",
                    "truncated": bool(metadata.get("truncated", False)),
                    "full_output_path": metadata.get("full_output_path"),
                }
            )
        )

    async def _project_user_turn(self, *, text: str, before: Optional[int] = None) -> None:
        """Add a user message and record its text before the agent starts.

        Add a turn separator if there is earlier content. Insert at the requested
        child position, or append when no position is supplied.
        """
        separated = await self._host.mount_turn_separator_if_needed(before=before)
        if separated and before is not None:
            before += 1
        await self._host.mount_user_message_block(text=text, before=before)
        self._host.record_transcript_line(content=f"> {text}", classes="user-line")

    async def _project_replay_entry(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Display one saved history entry using the same message widgets as live output."""
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
        await self._project_user_turn(text=entry.content or "", before=before)

    async def _project_replay_assistant(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Display a saved assistant answer and record its text.

        Put saved reasoning in a finished thinking block before the answer. Do not
        create live thinking-event tracking or artificial completion events.
        """
        if entry.reasoning:
            thinking_block: AssistantStreamThinkingBlock = await self._host.mount_thinking_block(
                before=before
            )
            thinking_block.set_thinking(content=entry.reasoning)
            thinking_block.seal()
            if before is not None:
                # Put the answer after its thinking block. Inserting both at
                # the same position would reverse their order.
                before = before + 1
        block: AssistantStreamBlock = await self._host.mount_assistant_block(before=before)
        content, classes = self._finalize_replay_assistant(block=block, entry=entry)
        self._host.record_transcript_line(content=content, classes=classes)

    async def _project_replay_note(
        self,
        *,
        entry: TranscriptEntryDAO,
        before: Optional[int] = None,
    ) -> None:
        """Display a saved workflow note as a single notice line."""
        await self._host.mount_transcript_line(
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
            tool_name=entry.tool_name,
            before=before,
        )
        block.update_tool_call(tool_name=entry.tool_name, tool_input=entry.tool_input)
        if entry.output is None:
            block.mark_incomplete()
        else:
            block.update_result(tool_name=entry.tool_name, output=entry.output)
        self._record_replay_tool_lines(entry=entry)

    @staticmethod
    def _finalize_replay_assistant(
        *,
        block: AssistantStreamBlock,
        entry: TranscriptEntryDAO,
    ) -> tuple[str, str]:
        """Apply a saved answer’s completed, cancelled, or failed state and return its text and styles.

        Apply only one final state: these operations each mark the block finished.
        For a cancelled or failed answer, show its partial text before the status note.
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
        """Record the tool-call heading and result text from a saved tool entry."""
        self._host.record_transcript_line(
            content=ToolExecutionBlockCallFormatter.format(
                tool_name=entry.tool_name,
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
        """Create a stable display label for a saved tool call.

        Saved blocks are not updated again, so this label need not be globally unique.
        """
        return f"replay:{entry.iteration}:{entry.tool_name or ''}"

    async def _get_or_create_thinking_block(
        self,
        *,
        block_id: str,
        iteration: int,
    ) -> AssistantStreamThinkingBlock:
        """Find or create the thinking widget for this block ID.

        Mount and cache only on first use so later completed text repairs the
        same widget. The assistant iteration is diagnostic, not block identity.

        Args:
            block_id: Stable thinking-stream identity within this prompt.
            iteration: Assistant iteration retained for diagnostics.

        Returns:
            The cached or newly mounted thinking widget; host failures propagate.
        """
        block: AssistantStreamThinkingBlock | None = self._thinking_blocks.get(block_id)
        if block is not None:
            return block
        block = await self._host.mount_thinking_block()
        self._thinking_blocks[block_id] = block
        self._thinking_block_iterations[block_id] = iteration
        self._open_thinking_block_ids.add(block_id)
        return block

    def _finalize_thinking_block(self, *, block_id: str, content: Optional[str]) -> None:
        """Replace and finish the matching open thinking block when completed text is available.

        Ignore unknown or finished IDs. Without text, keep the block open for a
        later repair. Run completion finishes all blocks and makes late updates harmless.
        """
        if block_id not in self._open_thinking_block_ids:
            return
        if not content:
            return
        block: AssistantStreamThinkingBlock | None = self._thinking_blocks.get(block_id)
        if block is None:
            return
        block.set_thinking(content=content)
        block.seal()
        self._open_thinking_block_ids.discard(block_id)

    def _seal_all_thinking_blocks(self) -> None:
        """Mark every tracked thinking block finished when the agent run ends."""
        for block in self._thinking_blocks.values():
            block.seal()
        self._open_thinking_block_ids.clear()

    async def _get_or_create_assistant_block(
        self,
        *,
        iteration: int,
    ) -> AssistantStreamBlock:
        """Find or create the answer block for this assistant iteration and finish older blocks.

        Iterations only increase, so older answers will not receive more text.
        Finishing them lets the transcript remove old blocks during long runs.
        Cache hits do not mount or seal anything; a newly mounted answer is cached
        before older answers are sealed. Host mounting failures propagate.

        Args:
            iteration: Assistant iteration whose answer receives subsequent text.

        Returns:
            The existing or newly mounted answer widget.
        """
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is not None:
            return block
        block = await self._host.mount_assistant_block()
        self._assistant_blocks[iteration] = block
        self._seal_stale_assistant_blocks(except_iteration=iteration)
        return block

    def _seal_stale_assistant_blocks(self, *, except_iteration: int) -> None:
        """Mark all tracked answer blocks finished except the specified iteration.

        Do this when a newer iteration starts and when a run ends. Finishing an
        already finished block is safe; no separate status check is needed.
        """
        for iteration, block in self._assistant_blocks.items():
            if iteration == except_iteration:
                continue
            block.seal()

    async def _get_or_create_tool_block(
        self,
        *,
        tool_call_id: str,
        tool_name: Optional[str],
    ) -> ToolExecutionBlock:
        """Return the mounted tool block for ``tool_call_id``.

        Args:
            tool_call_id (str): Stable tool call id.
            tool_name (Optional[str]): Tool name when known.

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
        """Update the tool’s existing block, or show a result notice when no matching block exists."""
        tool_call_id: str | None = event.tool_call_id
        if tool_call_id is None or tool_call_id not in self._tool_blocks:
            await self._host.mount_transcript_line(
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
        """Record a tool-call text line once."""
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
        """Show the completed answer for this iteration and finish every other answer block from the run."""
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if not content:
            # Without final text, finish the existing block without removing
            # text already received. Do not create an empty block.
            if block is not None:
                block.seal()
            self._seal_stale_assistant_blocks(except_iteration=iteration)
            return
        # When final text is available, create a block if needed and finish it
        # with that text instead of the partial text received earlier.
        if block is None:
            block = await self._get_or_create_assistant_block(iteration=iteration)
        block.finalize(final_text=content)
        self._host.record_transcript_line(content=content, classes="assistant-final")
        self._seal_stale_assistant_blocks(except_iteration=iteration)

    async def _finalize_aborted_run(self, *, iteration: int) -> None:
        """Mark the current answer cancelled, or show a notice if no answer exists.

        Finish older answer blocks too.
        """
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            await self._host.mount_transcript_line(
                content="(aborted)",
                classes="assistant-aborted",
            )
            self._seal_stale_assistant_blocks(except_iteration=iteration)
            return
        block.mark_aborted()
        self._host.record_transcript_line(
            content="(aborted)",
            classes="assistant-aborted",
        )
        self._seal_stale_assistant_blocks(except_iteration=iteration)

    async def _finalize_failed_run(self, *, iteration: int, error_message: str) -> None:
        """Mark the current answer failed, or show an error notice if no answer exists.

        Finish older answer blocks too.
        """
        rendered_error: str = f"(error: {error_message})"
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            await self._host.mount_transcript_line(
                content=rendered_error,
                classes="assistant-aborted",
            )
            self._seal_stale_assistant_blocks(except_iteration=iteration)
            return
        block.mark_failed(error_message=error_message)
        self._host.record_transcript_line(
            content=rendered_error,
            classes="assistant-aborted",
        )
        self._seal_stale_assistant_blocks(except_iteration=iteration)

    @staticmethod
    def _best_effort_parse_tool_input(*, raw_arguments: str) -> dict[str, object]:
        """Parse streamed tool-call JSON when it is complete enough.

        Args:
            raw_arguments (str): Accumulated streamed JSON fragment.

        Returns:
            dict[str, object]: Parsed args, or ``{}`` when incomplete.
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
    def format(*, tool_name: Optional[str], tool_input: dict[str, object]) -> str:
        """Return the visible tool-call headline text.

        Args:
            tool_name (Optional[str]): Tool name when known.
            tool_input (dict[str, object]): Parsed args.

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
