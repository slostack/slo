"""Stateful projector from ``AgentStreamEventDAO`` to transcript widgets."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional, Protocol

from config.logger import log_warning
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.tui.event_renderer import format_tool_call_headline, format_tool_result_line
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
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
    so the projector maintains one answer ``AssistantStreamBlock`` per
    iteration. Thinking segments are identified by the normalizer's stable
    ``block_id`` and mounted as their own ``AssistantStreamThinkingBlock``
    children, so a repair ``thinking_end`` updates its original widget even
    after answer or tool output arrived in between. Child sub-agent events
    never reach this projector — ``SloTUI._route_sub_agent_event`` is the sole
    owner of the fleet/child route.
    """

    def __init__(self, *, host: TranscriptMountHost) -> None:
        """Store the app/host collaboration seam.

        Args:
            host (TranscriptMountHost): App-level host used for mounting
                widgets and writing fallback transcript lines.
        """
        self._host: TranscriptMountHost = host
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
        self._replay_projectors: dict[str, Callable[..., Awaitable[None]]] = {
            "user": self._project_replay_user,
            "assistant": self._project_replay_assistant,
            "tool": self._project_replay_tool,
            "note": self._project_replay_note,
        }

    def reset_for_new_run(self) -> None:
        """Reset run-scoped projector state before a new prompt starts."""
        self._assistant_blocks.clear()
        self._thinking_blocks.clear()
        self._thinking_block_iterations.clear()
        self._open_thinking_block_ids.clear()
        self._tool_blocks.clear()
        self._tool_argument_buffers.clear()
        self._recorded_tool_calls.clear()

    async def project(self, *, event: AgentStreamEventDAO) -> None:
        """Apply one normalized stream event to the transcript.

        Parent/orchestrator events only: the app intercepts every
        ``sub_agent_id`` event before this projector is called, so no child
        route exists here. Thinking branches route by the normalizer's stable
        ``block_id``; iteration is diagnostic context, never identity.

        Args:
            event (AgentStreamEventDAO): Normalized stream event.
        """
        if event.kind == "thinking_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            if not event.block_id:
                log_warning(
                    "TranscriptProjector: ignoring thinking_delta with no block_id",
                    iteration=event.iteration,
                )
                return
            thinking_block: AssistantStreamThinkingBlock = await self._ensure_thinking_block(
                block_id=event.block_id,
                iteration=event.iteration,
            )
            thinking_block.append_thinking(delta=event.delta or "")
            return

        if event.kind == "thinking_end":
            if not event.block_id:
                log_warning(
                    "TranscriptProjector: ignoring thinking_end with no block_id",
                    iteration=event.iteration,
                )
                return
            self._finalize_thinking_block(block_id=event.block_id, content=event.content)
            return

        if event.kind == "text_delta":
            if not (event.delta or ""):
                return  # no content — do not mount an empty block
            answer_block: AssistantStreamBlock = await self._ensure_assistant_block(
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
                # Name-unknown streamed fragment: buffer the raw arguments and
                # defer mounting until the name resolves (or the call ends), so
                # the generic ``tool(command=...)`` headline never appears.
                buffered_tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
                if event.tool_arguments_delta:
                    self._tool_argument_buffers[buffered_tool_call_id] = (
                        self._tool_argument_buffers.get(buffered_tool_call_id, "")
                        + event.tool_arguments_delta
                    )
                return
            tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
            delta_tool_block: ToolExecutionBlock = await self._ensure_tool_block(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name,
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
            if not event.tool_name and event.tool_call_id not in self._tool_blocks:
                # Terminal event for a name-unknown call that never mounted a
                # block: nothing visible to finalize — skip placeholder noise.
                self._tool_argument_buffers.pop(event.tool_call_id or "", None)
                return
            tool_call_id = event.tool_call_id or event.block_id or "tool-call"
            final_tool_block: ToolExecutionBlock = await self._ensure_tool_block(
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

    async def _project_tool_output_update(self, *, event: AgentStreamEventDAO) -> None:
        """Patch the live tool block with one display-only output snapshot.

        WHAT: Routes a partial snapshot to the same block used by its terminal result.
        WHO: The normalized event projector calls it for ``tool_output_update``.
        WHEN: A streaming tool publishes accumulated output before it settles.
        """
        tool_call_id: str = event.tool_call_id or event.block_id or "tool-call"
        block: ToolExecutionBlock = await self._ensure_tool_block(
            tool_call_id=tool_call_id,
            tool_name=event.tool_name,
        )
        metadata: dict[str, Any] = event.metadata or {}
        block.update_partial(
            snapshot=ToolOutputUpdateDAO(
                tool_call_id=tool_call_id,
                tool_name=event.tool_name or block.tool_name,
                content_snapshot=event.content or "",
                truncated=bool(metadata.get("truncated", False)),
                full_output_path=metadata.get("full_output_path"),
            )
        )

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

        Persisted reasoning mounts one sealed thinking block immediately
        before the replayed answer block, mirroring the live path's
        chronological children. No replay thinking registry is created and no
        synthetic ``thinking_end`` is emitted.

        Args:
            entry (TranscriptEntryDAO): A ``kind="assistant"`` entry.
            before (Optional[int]): Child index to insert before. ``None``
                appends at the end.
        """
        if entry.reasoning:
            thinking_block: AssistantStreamThinkingBlock = await self._host.mount_thinking_block(
                before=before
            )
            thinking_block.set_thinking(content=entry.reasoning)
            thinking_block.seal()
            if before is not None:
                # The answer must follow its thinking block: mounting both at
                # the same prepend index would reverse their order.
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
        """Return a display-only tool-call id for a replayed tool block.

        Replay blocks are mounted directly (never cached or updated again),
        so this id only needs to be a stable label, not globally unique.

        Args:
            entry (TranscriptEntryDAO): A ``kind="tool"`` entry.

        Returns:
            str: A synthetic replay tool-call id.
        """
        return f"replay:{entry.iteration}:{entry.tool_name or ''}"

    async def _ensure_thinking_block(
        self,
        *,
        block_id: str,
        iteration: int,
    ) -> AssistantStreamThinkingBlock:
        """Return the thinking widget identified by normalized stream identity.

        Called by the parent ``thinking_delta`` branch. The normalizer owns
        provider-content segmentation; preserving ``block_id`` lets a later
        repair ``thinking_end`` update the original mounted widget.

        Args:
            block_id (str): Stable normalized thinking-content identifier.
            iteration (int): Outer assistant iteration for diagnostics only.

        Returns:
            AssistantStreamThinkingBlock: Mounted or cached thinking widget.
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
        """Apply a completed repair to one open thinking segment.

        WHAT: Replaces and seals only the segment eligible for its matching
            end; a retired or unknown id, and a contentless end, are no-ops.
        WHO: ``project`` calls this for parent ``thinking_end`` events.
        WHEN: Contentless ends leave the segment open (and unevictable) for
            their repair; terminal sweeps retire every id, so a late or
            duplicate end can never mutate a sealed segment.

        Args:
            block_id (str): Stable normalized thinking-content identifier.
            content (Optional[str]): Completed reasoning text, if supplied.
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
        """Settle every retained parent thinking block at a terminal run event.

        Called first by each terminal helper (``_finalize_completed_run``,
        ``_finalize_aborted_run``, ``_finalize_failed_run``) so no thinking
        widget stays live once its run can no longer produce a repair end.
        """
        for block in self._thinking_blocks.values():
            block.seal()
        self._open_thinking_block_ids.clear()

    async def _ensure_assistant_block(
        self,
        *,
        iteration: int,
    ) -> AssistantStreamBlock:
        """Return the assistant block for ``iteration``, sealing the block(s) it replaces.

        Each outer-loop assistant iteration owns its own transcript block so
        later thinking/text updates do not rewrite an older block above live
        tool output. Strict monotonicity of the ReAct loop's iteration counter
        (``agent.py:855``, ``:881``, ``:905`` — iteration only ever increases)
        guarantees that any other tracked block has already stopped receiving
        deltas the moment a new one is mounted, so it is safe to seal it here
        ("seal-on-advance", spec 61 D2) rather than waiting for the run's
        terminal event (D1) — this is what stops a single long-running turn
        from saturating the transcript window on its own, before the run ever
        completes.

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
        self._seal_stale_assistant_blocks(except_iteration=iteration)
        return block

    def _seal_stale_assistant_blocks(self, *, except_iteration: int) -> None:
        """Tell every tracked assistant block other than ``except_iteration`` to seal.

        This is the single implementation behind two call sites that both need
        the same guarantee — every assistant block this run has mounted stops
        being reported "live" once it can no longer receive updates:

        * **Seal-on-advance** — ``_ensure_assistant_block`` calls this
          immediately after mounting a new block for a new iteration. Strict
          monotonicity of the ReAct loop's iteration counter
          (``agent.py:855``, ``:881``, ``:905`` — iteration only ever
          increases) guarantees every other tracked block has already stopped
          streaming the moment a later iteration's block is mounted.
        * **Run-end sweep** — each of ``_finalize_completed_run``,
          ``_finalize_aborted_run``, and ``_finalize_failed_run`` calls this
          after applying the authoritative terminal treatment to the current
          iteration's block, so every iteration this run ever touched is
          sealed before ``reset_for_new_run`` clears ``_assistant_blocks`` for
          the next prompt.

        ``AssistantStreamBlock.seal()`` is idempotent (it no-ops once
        ``_finalized`` is already True), so this method tells every block to
        seal unconditionally rather than first asking whether it still needs
        to — there is exactly one decision here: which block is exempt.

        Args:
            except_iteration (int): The iteration whose block must not be
                sealed by this call — it either just received its own
                terminal treatment at the call site, or is the block just
                mounted for the new iteration.
        """
        for iteration, block in self._assistant_blocks.items():
            if iteration == except_iteration:
                continue
            block.seal()

    async def _ensure_tool_block(
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

        Also seals every other tracked assistant block from this run (the
        run-end sweep, spec 61 D1) so a multi-iteration turn never leaves a
        stale block permanently reporting itself live to the transcript
        window.

        Args:
            iteration (int): Outer-loop assistant iteration.
            content (str): Completed assistant answer text.
        """
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if not content:
            # No confirmed final text: seal any existing block without clearing
            # its streamed content, and never create a new empty block.
            if block is not None:
                block.seal()
            self._seal_stale_assistant_blocks(except_iteration=iteration)
            return
        # Confirmed final text: create the block when absent, then finalize it
        # with the LLM-confirmed text (authoritative over streamed deltas).
        if block is None:
            block = await self._ensure_assistant_block(iteration=iteration)
        block.finalize(final_text=content)
        self._host.record_transcript_line(content=content, classes="assistant-final")
        self._seal_stale_assistant_blocks(except_iteration=iteration)

    async def _finalize_aborted_run(self, *, iteration: int) -> None:
        """Finalize the current iteration block or render a fallback aborted line.

        Also seals every other tracked assistant block from this run (the
        run-end sweep, spec 61 D1).

        Args:
            iteration (int): Outer-loop assistant iteration.
        """
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            self._host.write_transcript_line(
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
        """Finalize the current iteration block or render a fallback error line.

        Also seals every other tracked assistant block from this run (the
        run-end sweep, spec 61 D1).

        Args:
            iteration (int): Outer-loop assistant iteration.
            error_message (str): One-line user-visible error summary.
        """
        rendered_error: str = f"(error: {error_message})"
        self._seal_all_thinking_blocks()
        block: AssistantStreamBlock | None = self._assistant_blocks.get(iteration)
        if block is None:
            self._host.write_transcript_line(
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
    def format(*, tool_name: Optional[str], tool_input: dict[str, Any]) -> str:
        """Return the visible tool-call headline text.

        Args:
            tool_name (Optional[str]): Tool name when known.
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
