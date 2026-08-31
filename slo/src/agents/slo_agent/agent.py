"""``SloAgent`` — stateful wrapper around the compiled LangGraph (sub-spec 01.f §4.4).

Owns the graph, steering / follow-up queues, abort signal, the
last-assistant-text tracker, and the multi-turn ReAct loop itself.
Enforces "one prompt at a time" per instance. Concurrent workloads run
multiple ``SloAgent`` instances (typically one per uvicorn worker
process).

The loop here mirrors pi's ``runLoop`` at
``pi/packages/agent/src/agent-loop.ts:155``. It is **unbounded**: stop
signals are (a) the model emits an assistant message with no tool
calls, (b) ``abort()`` is requested, or (c) the caller-supplied
``should_stop_after_turn_hook`` returns ``True``. There is no
iteration cap.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator, Literal, Optional, Sequence

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from config.logger import log_info
from src.agents.base import LLM
from src.agents.hooks import (
    Hook,
    ShouldStopAfterTurnHook,
    ShouldStopAfterTurnHookContextDAO,
    TurnAccumulatorDAO,
)
from src.agents.slo_agent.assistant_chunk_normalizer import (
    AssistantChunkNormalizer,
)
from src.agents.slo_agent.graph import SloAgentBuildResult, SloAgentStateDAO, build_slo_agent
from src.agents.slo_agent.graph_stream_parser import parse_graph_stream_item
from src.agents.slo_agent.message_text import assistant_message_text
from src.agents.slo_agent.rate_limit.service import int_or_none, IterationRetryPolicy
from src.agents.providers.stream_recovery.dao import ProviderStreamFailure
from src.agents.providers.stream_recovery.service import (
    StreamRecoveryService,
    provider_stream_first_progress_timeout_seconds,
    provider_stream_idle_timeout_seconds,
)
from src.agents.slo_agent.rate_limit.dao import RateLimitRetryPlanDAO
from src.agents.slo_agent.recovery.dao import RecoveryClass, RecoveryDecisionDAO
from src.agents.slo_agent.recovery.service import (
    IterationRecoveryPolicy,
    RecoveryObservationBuilder,
    RecoveryPolicy,
)
from src.agents.slo_agent.sessions.usage import TokenUsageTotalsDAO

if TYPE_CHECKING:
    from src.agents.providers.model_pool import ModelPoolDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.turn_stream_accumulator import TurnStreamAccumulator
from src.agents.slo_agent.project_context.dao import ContextFileEntryDAO
from src.agents.slo_agent.project_context.service import ProjectContextDiscovery
from src.agents.slo_agent.prompts import SystemPromptBuilder
from src.agents.slo_agent.skills.dao import SkillEntryDAO
from src.agents.slo_agent.skills.service import SkillsLoader
from src.agents.slo_agent.workspace.dao import (
    WorkspaceFileParseError,
    WorkspaceFolderDAO,
)
from src.agents.slo_agent.workspace.service import VscodeWorkspaceLoader
from config.cfg import SKILLS_DIR, USER_SKILLS_DIR, USER_WORKFLOWS_DIR
from src.agents.slo_agent.events.runtime import (
    AgentRuntimeEventDAO,
    AgentRuntimeHandler,
    AgentRuntimePayloadDAO,
)
from src.agents.reasoning_capabilities import ReasoningLevel

__all__ = ["SloAgent"]


_TOOL_OUTPUT_PREVIEW_CHARS: int = 240
"""Legacy tool-output preview cap retained for backward-compatible tests."""


class SloAgent:
    """Wrapper around a compiled Slo LangGraph + the multi-turn loop.

    Public surface:
    - ``invoke(query, history)`` — async-generator over normalized
      ``AgentStreamEventDAO`` events.
    - ``steer(message)`` — queue a message to inject before the next agent turn.
    - ``abort()`` — request graceful cancellation of the current run.
    """

    def __init__(
        self,
        *,
        model_name: Optional[str] = None,
        model_pool_dao: Optional["ModelPoolDAO"] = None,
        tools: Optional[Sequence[BaseTool]] = None,
        llm: Optional[LLM] = None,
        reasoning_level: ReasoningLevel = "off",
        system_prompt: Optional[str] = None,
        should_stop_after_turn_hook: ShouldStopAfterTurnHook = Hook.should_stop_after_turn_hook,
        cwd: Optional[str] = None,
        workspace_file: Optional[Path] = None,
        append_system_prompt: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Build the agent.

        Args:
            model_name (Optional[str]): Identifier passed to
                ``LLMFactory.create``. Ignored when ``model_pool_dao`` or
                ``llm`` is supplied.
            model_pool_dao (Optional[ModelPoolDAO]): When set (and ``llm`` is
                not injected), the agent builds a ``ModelPool`` (multi-model
                fallback) via ``build_slo_agent``. ``None`` keeps the
                single-model path. Ignored when ``llm`` is supplied.
            tools (Optional[Sequence[BaseTool]]): Tools the agent may
                call. Defaults to slo's extended bundle (see
                ``build_slo_agent``).
            llm (Optional[LLM]): Pre-built chat model — typically a
                ``FauxChatModel`` for tests.
            reasoning_level (ReasoningLevel): Canonical active reasoning
                level forwarded into the lazy LLM build path. Ignored
                when ``llm`` is supplied directly.
            system_prompt (Optional[str]): Final prompt string supplied by
                the caller. When provided it wins outright: runtime prompt
                building (and the cwd/date grounding it adds) is skipped.
            should_stop_after_turn_hook (ShouldStopAfterTurnHook): Hook
                evaluated after every turn. Returning ``True`` halts
                the loop before the next LLM call. The default is the
                no-op classmethod on ``Hook`` so the call site never
                branches on ``None``.
            cwd (Optional[str]): Working directory used for project-context
                discovery and the prompt's trailing cwd line. Defaults to
                ``os.getcwd()`` when not supplied.
            workspace_file (Optional[Path]): Optional VSCode workspace file
                whose declared folders contribute additive project-context
                walks. ``None`` keeps discovery cwd-only.
            append_system_prompt (Optional[str]): Extra prompt text appended
                after the base (or custom) prompt body. Ignored when a final
                ``system_prompt`` override is supplied.
            custom_prompt (Optional[str]): Full replacement for the default
                role/tools/guidelines body. Ignored when a final
                ``system_prompt`` override is supplied.
            session_id (Optional[str]): Owning ``SloAgentSession.session_id``.
                Threaded through ``LLMFactory.create`` so the ChatGPT-backend
                Responses lane (feature 07) can attribute prompt-cache
                hits per session. Ignored when ``llm`` is supplied
                directly.
        """
        self._llm: Optional[LLM] = llm
        _build_result: SloAgentBuildResult = build_slo_agent(
            model_name=model_name,
            model_pool_dao=model_pool_dao,
            tools=tools,
            llm=llm,
            reasoning_level=reasoning_level,
            session_id=session_id,
        )
        self._graph: CompiledStateGraph = _build_result.graph
        # Retain the built (tool-bound) LLM — a single model or a ModelPool — so
        # routed-model introspection (``SloAgentSession._resolve_active_model_name``)
        # works on the lazy build path, not only when an LLM is injected.
        self._llm = _build_result.llm
        self._cwd: str = cwd if cwd is not None else os.getcwd()
        self._workspace_file: Optional[Path] = workspace_file
        self._workspace_folders: list[WorkspaceFolderDAO] = self._resolve_workspace_folders()
        self._project_context_files: list[ContextFileEntryDAO] = ProjectContextDiscovery.invoke(
            cwd=self._cwd,
            workspace_folders=self._workspace_folders or None,
        )
        self.context_files: list[ContextFileEntryDAO] = list(self._project_context_files)
        self._skills: list[SkillEntryDAO] = SkillsLoader.load_merged(
            vendored_skills_dir=SKILLS_DIR,
            user_skills_dir=USER_SKILLS_DIR,
            user_workflows_dir=USER_WORKFLOWS_DIR,
        )
        self._system_prompt: str = self._resolve_system_prompt(
            system_prompt=system_prompt,
            tools=list(_build_result.tools),
            cwd=self._cwd,
            append_system_prompt=append_system_prompt,
            custom_prompt=custom_prompt,
            project_context_files=self._project_context_files,
            skills=self._skills,
            workspace_folders=self._workspace_folders,
        )
        self._supports_explicit_caching: bool = _build_result.supports_explicit_caching
        self._should_stop_after_turn_hook: ShouldStopAfterTurnHook = should_stop_after_turn_hook
        self._steering_queue: asyncio.Queue[BaseMessage] = asyncio.Queue()
        self._active_turn: TurnStreamAccumulator = TurnStreamAccumulator()
        self._abort_event: asyncio.Event = asyncio.Event()
        self._running: bool = False
        self._last_assistant_text: str = ""
        self._last_usage_totals: TokenUsageTotalsDAO = TokenUsageTotalsDAO()
        self._usage_capture_version: int = 0
        self._current_iteration: int = 0
        self._recovery_budget: int = 2
        """Maximum LLM-driven recoveries per submitted prompt. Default 2."""
        log_info(msg="SloAgent built")

    @property
    def llm(self) -> Optional[LLM]:
        """Return the built, tool-bound LLM (single model or ModelPool).

        Set from ``build_slo_agent(...).llm`` in ``__init__`` — so it is the
        live, tool-bound model on every build path (lazy or injected), not only
        when an LLM is injected. For a pooled session this is the bound
        ``ModelPool``, which is what makes routed-model introspection work.

        ``SloAgentSession._resolve_active_model_name()`` reads this via duck
        typing (``hasattr(llm, "active_model_name")``) to detect a ``ModelPool``
        without importing that class; a bound single model has no such attribute
        and the session falls back to the configured name.

        Returns:
            Optional[LLM]: The built, tool-bound LLM instance.
        """
        return self._llm

    @property
    def workspace_folders(self) -> list[WorkspaceFolderDAO]:
        """Return the resolved workspace folders for this agent.

        Returns:
            list[WorkspaceFolderDAO]: Workspace folders loaded at agent boot.
        """
        return list(self._workspace_folders)

    def _resolve_workspace_folders(self) -> list[WorkspaceFolderDAO]:
        """Load workspace folders, degrading to cwd-only discovery on failure.

        Returns:
            list[WorkspaceFolderDAO]: Resolved workspace folders, or an empty
                list when no workspace file is configured or the file cannot
                be loaded.
        """
        if self._workspace_file is None:
            return []
        if not self._workspace_file.is_file():
            log_info(
                msg="workspace_file_missing",
                workspace_file=str(self._workspace_file),
            )
            return []
        try:
            return VscodeWorkspaceLoader.invoke(workspace_file=self._workspace_file)
        except WorkspaceFileParseError as exc:
            log_info(
                msg="workspace_file_unreadable",
                workspace_file=str(self._workspace_file),
                reason=exc.reason,
            )
            return []

    def _resolve_system_prompt(
        self,
        *,
        system_prompt: Optional[str],
        tools: Optional[Sequence[BaseTool]],
        cwd: str,
        append_system_prompt: Optional[str],
        custom_prompt: Optional[str],
        project_context_files: list[ContextFileEntryDAO],
        skills: Optional[list[SkillEntryDAO]] = None,
        workspace_folders: Optional[list[WorkspaceFolderDAO]] = None,
    ) -> str:
        """Choose between caller override and runtime prompt assembly.

        ``__init__`` invokes this once during agent construction after cwd
        and project-context discovery have already completed. In the common
        case it delegates to ``SystemPromptBuilder.invoke()``; when the
        caller has supplied a final ``system_prompt`` string it returns that
        value unchanged and bypasses runtime assembly entirely (including
        the cwd/date grounding the builder would otherwise add).

        Args:
            system_prompt (Optional[str]): Caller-supplied final prompt.
                Highest-precedence override.
            tools (Optional[Sequence[BaseTool]]): Active tools for this run.
            cwd (str): Working directory for this run.
            append_system_prompt (Optional[str]): Optional prompt text to
                append on the runtime-assembly path.
            custom_prompt (Optional[str]): Optional full body override on the
                runtime-assembly path.
            project_context_files (list[ContextFileEntryDAO]): Discovered repo
                guidance files with tier annotations.
            skills (Optional[list[SkillEntryDAO]]): Pre-loaded skill entries
                from ``SkillsLoader``. Forwarded to the prompt builder to
                render the XML manifest. Defaults to None.
            workspace_folders (Optional[list[WorkspaceFolderDAO]]): Optional
                resolved folders from a VSCode workspace file.

        Returns:
            str: The prompt string stored on the agent instance.
        """
        if system_prompt is not None:
            return system_prompt

        return SystemPromptBuilder.invoke(
            tools=tools,
            cwd=cwd,
            custom_prompt=custom_prompt,
            append_system_prompt=append_system_prompt,
            project_context_files=project_context_files,
            skills=skills,
            workspace_folders=workspace_folders,
        )

    # ---- Public surface ---------------------------------------------------

    @property
    def last_usage_totals(self) -> TokenUsageTotalsDAO:
        """Return the last completed-turn usage totals.

        Returns:
            TokenUsageTotalsDAO: Last completed-turn usage metadata.
        """
        return self._last_usage_totals.model_copy(deep=True)

    @property
    def usage_capture_version(self) -> int:
        """Return the monotonic capture version for usage metadata.

        Returns:
            int: Usage capture version incremented on each completed capture.
        """
        return self._usage_capture_version

    def _capture_usage_from_completed_turn(self, *, turn: TurnStreamAccumulator) -> None:
        """Capture usage metadata from the turn's completed assistant message.

        Args:
            turn (TurnStreamAccumulator): Completed turn accumulator.
        """
        completed_assistant_message: Optional[AIMessage] = turn.completed_assistant_message
        if completed_assistant_message is None:
            return
        self._capture_completed_usage(message=completed_assistant_message)

    def _capture_completed_usage(self, *, message: AIMessage) -> None:
        """Extract usage metadata from one completed assistant message.

        Args:
            message (AIMessage): Completed assistant message.
        """
        usage_metadata: dict[str, object] = dict(message.usage_metadata or {})
        next_totals: TokenUsageTotalsDAO = TokenUsageTotalsDAO(
            input_tokens=int_or_none(value=usage_metadata.get("input_tokens")),
            output_tokens=int_or_none(value=usage_metadata.get("output_tokens")),
            total_tokens=int_or_none(value=usage_metadata.get("total_tokens")),
            cache_creation_input_tokens=int_or_none(
                value=usage_metadata.get("cache_creation_input_tokens"),
            ),
            cache_read_input_tokens=int_or_none(
                value=usage_metadata.get("cache_read_input_tokens"),
            ),
        )
        if next_totals == self._last_usage_totals:
            return
        self._last_usage_totals = next_totals
        self._usage_capture_version += 1

    # ---- Run-lifecycle helpers (extracted from invoke) -------------------------

    def _validate_invoke_inputs(
        self,
        *,
        history: Optional[list[dict]],
        message_history: Optional[list[BaseMessage]],
    ) -> None:
        """Raise early when the caller supplies conflicting or illegal inputs.

        Args:
            history (Optional[list[dict]]): Legacy dict-shaped prior conversation.
            message_history (Optional[list[BaseMessage]]): Projector-built prior messages.

        Raises:
            ValueError: If both ``history`` and ``message_history`` are supplied.
            RuntimeError: If a run is already in progress on this instance.
        """
        if history is not None and message_history is not None:
            raise ValueError("Pass only one of `history` or `message_history` to SloAgent.")
        if self._running:
            raise RuntimeError(
                "SloAgent is already processing. Call steer() to queue a "
                "message, or await completion before invoking again."
            )

    def _initialize_run_state(self) -> None:
        """Reset all per-run mutable state before a new streaming run begins.

        Sets the agent into the 'running' state and clears all turn-scoped
        accumulators. ``self._active_turn`` is reset so a stale completed turn from
        a prior run cannot influence the new run's stop decision.
        """
        self._running = True
        self._last_assistant_text = ""
        self._last_usage_totals = TokenUsageTotalsDAO()
        self._current_iteration = 0
        self._active_turn = TurnStreamAccumulator()

    def _teardown_run_state(self) -> None:
        """Clear running state in the ``invoke`` finally block.

        Clears the abort event so a subsequent run is not immediately aborted,
        and releases the running lock so the caller may submit a new prompt.
        """
        self._abort_event.clear()
        self._running = False

    async def _emit_run_started_trace(
        self,
        *,
        query: str,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> None:
        """Emit the ``run_started`` runtime trace event.

        Args:
            query (str): The user prompt, forwarded as the trace payload content.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.
        """
        await self._emit_trace_event(
            runtime_handler=runtime_handler,
            event=AgentRuntimeEventDAO(
                kind="run_started",
                payload=AgentRuntimePayloadDAO(content=query),
            ),
        )

    def _build_initial_run_context(
        self,
        *,
        query: str,
        history: Optional[list[dict]],
        message_history: Optional[list[BaseMessage]],
    ) -> list[BaseMessage]:
        """Build the initial accumulated message list for this run.

        The returned list is mutable and is extended throughout the run by
        ``_apply_steering`` (inter-turn steering injection) and
        ``_process_updates_mode_chunk`` (completed delta messages).

        Args:
            query (str): The user prompt.
            history (Optional[list[dict]]): Legacy dict-shaped conversation.
            message_history (Optional[list[BaseMessage]]): Projector-built messages.

        Returns:
            list[BaseMessage]: ``[SystemMessage, *prior_history, HumanMessage(query)]``,
                ready for the first graph turn.
        """
        return self._build_initial_messages(
            query=query,
            history=history,
            message_history=message_history,
        )

    async def _handle_pre_run_abort(
        self,
        *,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Emit trace and stream event when abort was requested before the run started.

        Args:
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Yields:
            AgentStreamEventDAO: A single ``run_aborted`` event at ``iteration=0``.
        """
        await self._emit_trace_event(
            runtime_handler=runtime_handler,
            event=AgentRuntimeEventDAO(kind="run_aborted"),
        )
        yield AgentStreamEventDAO(kind="run_aborted", iteration=0, content="<aborted>")

    async def _apply_steering(
        self,
        *,
        accumulated_messages: list[BaseMessage],
        iteration: int,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Drain the steering queue, emit traces, yield events, and extend the run context.

        Steering messages drained here are folded into ``accumulated_messages``
        so the next graph turn sees them as part of the message history. The
        ``steering_applied`` stream events let the TUI render queued steers as
        regular user messages at the moment they enter the model context.

        Args:
            accumulated_messages (list[BaseMessage]): The run's accumulated message list.
                Extended in place with drained steering messages.
            iteration (int): The iteration these messages are being applied to.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Yields:
            AgentStreamEventDAO: One ``steering_applied`` event per drained message.
                Yields nothing when the queue is empty.
        """
        steering: list[BaseMessage] = self._drain(queue=self._steering_queue)
        await self._emit_steering_traces(runtime_handler=runtime_handler, messages=steering)
        for event in self._steering_applied_events(messages=steering, iteration=iteration):
            yield event
        accumulated_messages.extend(steering)

    async def _process_messages_mode_chunk(
        self,
        *,
        chunk: AIMessageChunk,
        normalizer: AssistantChunkNormalizer,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> list[AgentStreamEventDAO]:
        """Process one ``messages``-mode chunk from the LangGraph stream.

        Captures token usage from the chunk, feeds it to the normalizer to produce
        normalized stream events, emits stream-level trace events for each, and
        returns the full list so the caller can yield and inspect visibility.

        Args:
            chunk (AIMessageChunk): One raw assistant message chunk from the graph.
            normalizer (AssistantChunkNormalizer): The current attempt's chunk normalizer.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Returns:
            list[AgentStreamEventDAO]: Normalized stream events produced by this chunk.
        """
        self._capture_completed_usage(message=chunk)
        stream_events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(chunk=chunk)
        for event in stream_events:
            await self._emit_stream_trace_event(
                runtime_handler=runtime_handler,
                stream_event=event,
            )
        return stream_events

    async def _process_updates_mode_chunk(
        self,
        *,
        chunk: dict,
        accumulated_messages: list[BaseMessage],
        turn: TurnStreamAccumulator,
        iteration: int,
        normalizer: AssistantChunkNormalizer,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> list[AgentStreamEventDAO]:
        """Process one ``updates``-mode chunk from the LangGraph stream.

        Extracts completed messages from the chunk, extends the accumulated context,
        absorbs them into the turn accumulator, emits full-fidelity trace events,
        finalizes any open normalizer blocks for completed ``AIMessage`` objects,
        and collects ``tool_result`` events for any ``ToolMessage`` objects.

        Mutates ``accumulated_messages`` and ``turn`` in place.

        Args:
            chunk (dict): One LangGraph update chunk.
            accumulated_messages (list[BaseMessage]): Mutable run context.
            turn (TurnStreamAccumulator): Per-attempt turn state accumulator.
            iteration (int): Current outer-loop iteration index.
            normalizer (AssistantChunkNormalizer): The current attempt's normalizer.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Returns:
            list[AgentStreamEventDAO]: Stream events produced by this chunk
                (closing events from open blocks and tool_result events).
                Empty when the chunk contains no delta messages.
        """
        delta_messages: list[BaseMessage] = self._chunk_message_delta(chunk=chunk)
        if not delta_messages:
            return []

        accumulated_messages.extend(delta_messages)
        turn.absorb_messages(messages=delta_messages)

        for trace_event in self._trace_events_from_messages(messages=delta_messages):
            await self._emit_trace_event(runtime_handler=runtime_handler, event=trace_event)

        events: list[AgentStreamEventDAO] = []
        for message in delta_messages:
            if isinstance(message, AIMessage):
                self._capture_completed_usage(message=message)
                for closing_event in normalizer.finalize_open_blocks(
                    completed_assistant_message=message,
                ):
                    await self._emit_stream_trace_event(
                        runtime_handler=runtime_handler,
                        stream_event=closing_event,
                    )
                    events.append(closing_event)

        events.extend(
            self._stream_events_from_update_messages(
                messages=delta_messages,
                iteration=iteration,
            )
        )
        return events

    async def _stream_graph_turn(
        self,
        *,
        accumulated_messages: list[BaseMessage],
        normalizer: AssistantChunkNormalizer,
        turn: TurnStreamAccumulator,
        iteration: int,
        runtime_handler: Optional[AgentRuntimeHandler],
        first_progress_timeout_seconds: Optional[float] = None,
        idle_timeout_seconds: Optional[float] = None,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Stream one LangGraph turn and yield all resulting stream events.

        Dispatches each raw stream item to the appropriate mode handler:
        ``messages`` mode normalizes ``AIMessageChunk`` deltas; ``updates`` mode
        accumulates completed messages and yields tool results. Aborts the
        generator (yielding ``run_aborted``) if the abort event is set on any
        iteration of the inner loop.

        Mutates ``accumulated_messages`` and ``turn`` in place via
        ``_process_updates_mode_chunk``.

        Args:
            accumulated_messages (list[BaseMessage]): Mutable run context.
            normalizer (AssistantChunkNormalizer): Per-attempt chunk normalizer.
            turn (TurnStreamAccumulator): Per-attempt turn state accumulator.
            iteration (int): Current outer-loop iteration index.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Yields:
            AgentStreamEventDAO: Normalized stream events from the graph turn.

        Raises:
            Exception: Any exception raised by ``self._graph.astream``.
        """
        first_progress_timeout: float = (
            first_progress_timeout_seconds
            if first_progress_timeout_seconds is not None
            else provider_stream_first_progress_timeout_seconds()
        )
        idle_timeout: float = (
            idle_timeout_seconds if idle_timeout_seconds is not None else provider_stream_idle_timeout_seconds()
        )
        turn_state: SloAgentStateDAO = SloAgentStateDAO(messages=list(accumulated_messages))
        graph_stream = self._graph.astream(turn_state, stream_mode=["messages", "updates"])
        first_progress_pending: bool = True
        provider_read_pending: bool = True
        try:
            while True:
                raw_item = await self._read_next_graph_stream_item(
                    graph_stream=graph_stream,
                    first_progress_pending=first_progress_pending,
                    first_progress_timeout_seconds=first_progress_timeout,
                    idle_timeout_seconds=idle_timeout,
                    provider_read_pending=provider_read_pending,
                )
                if raw_item is None:
                    return
                first_progress_pending = False
                if self._abort_event.is_set():
                    await self._emit_trace_event(
                        runtime_handler=runtime_handler,
                        event=AgentRuntimeEventDAO(kind="run_aborted", iteration=iteration),
                    )
                    yield AgentStreamEventDAO(
                        kind="run_aborted",
                        iteration=iteration,
                        content="<aborted>",
                    )
                    return
                parsed = parse_graph_stream_item(raw_item=raw_item)
                if parsed.mode == "messages":
                    if not isinstance(parsed.message_chunk, AIMessageChunk):
                        continue
                    stream_events: list[AgentStreamEventDAO] = await self._process_messages_mode_chunk(
                        chunk=parsed.message_chunk,
                        normalizer=normalizer,
                        runtime_handler=runtime_handler,
                    )
                    provider_read_pending = not self._starts_local_tool_work(events=stream_events)
                    for event in stream_events:
                        yield event
                    continue
                if parsed.update_chunk is None:
                    continue
                provider_read_pending = True
                for event in await self._process_updates_mode_chunk(
                    chunk=parsed.update_chunk,
                    accumulated_messages=accumulated_messages,
                    turn=turn,
                    iteration=iteration,
                    normalizer=normalizer,
                    runtime_handler=runtime_handler,
                ):
                    yield event
        finally:
            await self._close_graph_stream(graph_stream=graph_stream)

    @staticmethod
    async def _close_graph_stream(*, graph_stream: AsyncIterator[object]) -> None:
        """Close a generator-backed graph stream when the provider read loop exits."""
        if not isinstance(graph_stream, AsyncGenerator):
            return
        await graph_stream.aclose()

    async def _read_next_graph_stream_item(
        self,
        *,
        graph_stream: AsyncIterator[object],
        first_progress_pending: bool,
        first_progress_timeout_seconds: float,
        idle_timeout_seconds: float,
        provider_read_pending: bool,
    ) -> object | None:
        """Read one graph item under the provider transport-progress deadline.

        WHAT: Applies the first-progress deadline before the initial graph item and
            the idle deadline thereafter, translating only deadline expiry into a
            typed provider-stream failure.
        WHO: Called by ``_stream_graph_turn`` at the LangGraph/provider read boundary.
        WHEN: Once for every pending ``anext`` while one ReAct iteration is live.
        """
        if not provider_read_pending:
            return await self._read_graph_item_without_provider_deadline(graph_stream=graph_stream)
        timeout: float = first_progress_timeout_seconds if first_progress_pending else idle_timeout_seconds
        try:
            return await asyncio.wait_for(anext(graph_stream), timeout=timeout)
        except StopAsyncIteration:
            return None
        except asyncio.TimeoutError as exc:
            from src.agents.providers.stream_recovery.dao import (  # noqa: PLC0415
                ProviderStreamProgressTimeout,
            )

            phase: Literal["first_progress", "idle"] = "first_progress" if first_progress_pending else "idle"
            raise ProviderStreamProgressTimeout(phase=phase) from exc

    @staticmethod
    async def _read_graph_item_without_provider_deadline(
        *,
        graph_stream: AsyncIterator[object],
    ) -> object | None:
        """Read a graph item while LangGraph waits for a local tool result.

        A ``tool_call_start`` has already crossed the commit boundary. LangGraph
        can legitimately pause the combined graph iterator while it executes that
        local tool, so ``_stream_graph_turn`` calls this helper instead of applying
        a provider-byte idle timeout during that interval.
        """
        try:
            return await anext(graph_stream)
        except StopAsyncIteration:
            return None

    @staticmethod
    def _starts_local_tool_work(*, events: list[AgentStreamEventDAO]) -> bool:
        """Return whether a provider chunk starts local tool execution.

        ``_stream_graph_turn`` calls this after normalizing a messages-mode chunk
        so its next graph read does not mistake LangGraph's local tool wait for a
        provider transport stall.
        """
        return any(event.kind == "tool_call_start" for event in events)

    async def _finalize_iteration(
        self,
        *,
        turn: TurnStreamAccumulator,
        normalizer: AssistantChunkNormalizer,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Perform post-iteration housekeeping and yield any remaining closing events.

        Captures token usage from the completed turn, finalizes any still-open
        normalizer blocks (yielding their closing stream events and emitting
        stream-level trace events), and updates ``self._last_assistant_text``.

        Called once per outer-loop iteration, after the inner retry loop breaks
        on a successful graph turn.

        Args:
            turn (TurnStreamAccumulator): Completed turn state.
            normalizer (AssistantChunkNormalizer): The successful attempt's normalizer.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Yields:
            AgentStreamEventDAO: Closing stream events for any still-open blocks.
                Yields nothing when all blocks were cleanly closed during streaming.
        """
        self._capture_usage_from_completed_turn(turn=turn)
        for closing_event in normalizer.finalize_open_blocks(
            completed_assistant_message=turn.completed_assistant_message,
        ):
            await self._emit_stream_trace_event(
                runtime_handler=runtime_handler,
                stream_event=closing_event,
            )
            yield closing_event
        self._last_assistant_text = turn.final_assistant_text

    async def _should_loop_continue(
        self,
        *,
        accumulated_messages: list[BaseMessage],
    ) -> bool:
        """Determine whether the outer ReAct loop should execute another iteration.

        Checks the steering queue non-destructively to detect a pending steer
        that would revive a run that would otherwise stop. The actual drain is
        performed by the subsequent ``_apply_steering`` call in ``_react_loop``.

        A pending steer overrides a would-stop verdict because steering's contract
        is: any steer queued before the loop evaluates its stop condition is
        honored by reviving the run for at least one more turn.

        Args:
            accumulated_messages (list[BaseMessage]): Full accumulated message list.

        Returns:
            bool: ``True`` to execute another iteration; ``False`` to break the loop.
        """
        has_pending_steering: bool = not self._steering_queue.empty()
        hook_turn: TurnAccumulatorDAO = self._turn_to_hook_accumulator(turn=self._active_turn)
        would_stop: bool = (
            await self._evaluate_stop_hook(turn=hook_turn, messages=accumulated_messages)
            or not self._last_turn_has_tool_calls(messages=accumulated_messages)
        )
        return not would_stop or has_pending_steering

    async def _execute_iteration_with_retry(
        self,
        *,
        accumulated_messages: list[BaseMessage],
        iteration: int,
        runtime_handler: Optional[AgentRuntimeHandler],
        iteration_retry_policy: Optional[IterationRetryPolicy],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Execute one outer-loop iteration, retrying on eligible provider failures.

        Each attempt starts with a fresh ``normalizer`` and ``turn`` so a
        partial failed stream does not corrupt the accumulator state for the retry.
        On a successful attempt, ``self._active_turn`` is set to the completed turn
        so ``_should_loop_continue`` can evaluate the stop hook.

        Args:
            accumulated_messages (list[BaseMessage]): Mutable run context.
            iteration (int): Current outer-loop iteration index.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.
            iteration_retry_policy (Optional[IterationRetryPolicy]): Retry decision callable.
                ``None`` disables retry: any exception surfaces ``run_failed``.

        Yields:
            AgentStreamEventDAO: Stream events for this iteration, including
                finalization events yielded by ``_finalize_iteration``.

        Raises:
            Exception: Re-raises the original exception when the iteration is not retryable.
        """
        attempt: int = 0
        while True:
            attempt += 1
            partial_output_committed: bool = False
            normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=iteration)
            turn: TurnStreamAccumulator = TurnStreamAccumulator()
            try:
                async for event in self._stream_graph_turn(
                    accumulated_messages=accumulated_messages,
                    normalizer=normalizer,
                    turn=turn,
                    iteration=iteration,
                    runtime_handler=runtime_handler,
                ):
                    if self._is_committed_output_event(event=event):
                        partial_output_committed = True
                    yield event
                if self._abort_event.is_set():
                    return  # run_aborted already yielded; skip finalization and break
                self._active_turn = turn
                break
            except Exception as exc:
                stream_decision = StreamRecoveryService.classify(
                    exc=exc,
                    partial_output_committed=partial_output_committed,
                )
                if stream_decision.action.value != "propagate":
                    raise ProviderStreamFailure(
                        decision=stream_decision,
                        partial_output_committed=partial_output_committed,
                        attempt_number=attempt,
                    ) from exc
                retry_decision: RateLimitRetryPlanDAO = self._decide_iteration_retry(
                    iteration_retry_policy=iteration_retry_policy,
                    exc=exc,
                    saw_visible_output_this_iteration=partial_output_committed,
                    attempt_number=attempt,
                )
                if not retry_decision.retryable:
                    # Terminal-failure emission now lives in ``_react_loop``, which
                    # first offers the exception to the recovery policy. Re-raise
                    # the original exception unchanged.
                    raise
                yield AgentStreamEventDAO(
                    kind="run_retrying",
                    iteration=self._current_iteration,
                    content=retry_decision.message,
                    metadata={"wait_seconds": retry_decision.wait_seconds},
                )
                await asyncio.sleep(retry_decision.wait_seconds)

        async for event in self._finalize_iteration(
            turn=turn,
            normalizer=normalizer,
            runtime_handler=runtime_handler,
        ):
            yield event

    async def _react_loop(
        self,
        *,
        accumulated_messages: list[BaseMessage],
        runtime_handler: Optional[AgentRuntimeHandler],
        iteration_retry_policy: Optional[IterationRetryPolicy],
        iteration_recovery_policy: Optional[IterationRecoveryPolicy] = None,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Drive the outer ReAct iteration loop, recovering from recoverable failures.

        On a recoverable escaped exception within ``self._recovery_budget``, demotes
        it into a recovery observation and re-enters the loop; otherwise emits
        ``run_failed`` and re-raises. Evaluates stop conditions via
        ``_should_loop_continue`` before each inter-turn steering application.

        Args:
            accumulated_messages (list[BaseMessage]): Mutable run context, extended each turn.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.
            iteration_retry_policy (Optional[IterationRetryPolicy]): Per-iteration retry decision.
            iteration_recovery_policy (Optional[IterationRecoveryPolicy]): LLM recovery
                decision. ``None`` preserves the legacy fail-fast behavior.

        Yields:
            AgentStreamEventDAO: All stream events produced across all iterations.
        """
        iteration: int = 0
        recoveries_used: int = 0
        pending_recovery: bool = False
        while True:
            self._current_iteration = iteration
            try:
                async for event in self._execute_iteration_with_retry(
                    accumulated_messages=accumulated_messages,
                    iteration=iteration,
                    runtime_handler=runtime_handler,
                    iteration_retry_policy=iteration_retry_policy,
                ):
                    yield event
            except Exception as exc:
                recovery_decision: RecoveryDecisionDAO = self._decide_iteration_recovery(
                    exc=exc,
                    recoveries_used=recoveries_used,
                    iteration_recovery_policy=iteration_recovery_policy,
                )
                if (
                    recovery_decision.recovery_class is RecoveryClass.LLM_RECOVERABLE
                    and recoveries_used < self._recovery_budget
                ):
                    async for event in self._perform_recovery(
                        exc=exc,
                        decision=recovery_decision,
                        accumulated_messages=accumulated_messages,
                    ):
                        yield event
                    recoveries_used += 1
                    iteration += 1
                    pending_recovery = True
                    continue
                async for event in self._emit_terminal_failure(
                    exc=exc,
                    recoveries_attempted=recoveries_used > 0,
                    runtime_handler=runtime_handler,
                ):
                    yield event
                raise

            if pending_recovery:
                pending_recovery = False
                yield AgentStreamEventDAO(
                    kind="recovery_succeeded",
                    iteration=self._current_iteration,
                )

            if self._abort_event.is_set():
                return  # run_aborted already yielded; skip stop evaluation and next iteration

            if not await self._should_loop_continue(accumulated_messages=accumulated_messages):
                break

            iteration += 1
            async for event in self._apply_steering(
                accumulated_messages=accumulated_messages,
                iteration=iteration,
                runtime_handler=runtime_handler,
            ):
                yield event

    def _decide_iteration_recovery(
        self,
        *,
        exc: BaseException,
        recoveries_used: int,
        iteration_recovery_policy: Optional[IterationRecoveryPolicy],
    ) -> RecoveryDecisionDAO:
        """Classify an escaped iteration exception for recovery.

        Returns a ``FATAL`` decision when no recovery policy is injected (the
        legacy default), otherwise delegates to the injected policy. Invoked by
        ``_react_loop`` for every exception that escapes
        ``_execute_iteration_with_retry``.

        Args:
            exc (BaseException): The exception that ended the iteration.
            recoveries_used (int): Recoveries already spent this submission.
            iteration_recovery_policy (Optional[IterationRecoveryPolicy]): The
                injected decision callable, or ``None``.

        Returns:
            RecoveryDecisionDAO: The recovery classification for ``exc``.
        """
        if iteration_recovery_policy is None:
            return RecoveryDecisionDAO(
                recovery_class=RecoveryClass.FATAL,
                reason="No recovery policy injected.",
            )
        return iteration_recovery_policy(exc, recoveries_used)

    async def _perform_recovery(
        self,
        *,
        exc: BaseException,
        decision: RecoveryDecisionDAO,
        accumulated_messages: list[BaseMessage],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Demote ``exc`` into an observation and prepare the loop to re-enter.

        Builds the recovery observation, appends it to ``accumulated_messages``
        so the next iteration sees it, and yields one ``recovery_started`` event
        carrying the observation text (``content``) and audit fields
        (``metadata``) the session persists from. Invoked by ``_react_loop``
        when a recoverable exception is within budget.

        Args:
            exc (BaseException): The recoverable exception being demoted.
            decision (RecoveryDecisionDAO): Its classification, for hint + reason.
            accumulated_messages (list[BaseMessage]): Mutable run context; the
                observation is appended here exactly once.

        Yields:
            AgentStreamEventDAO: One ``recovery_started`` event.
        """
        observation: BaseMessage = RecoveryObservationBuilder.build(
            exc=exc,
            decision=decision,
            accumulated_messages=accumulated_messages,
        )
        accumulated_messages.append(observation)
        observation_text: str = str(observation.content)
        yield AgentStreamEventDAO(
            kind="recovery_started",
            iteration=self._current_iteration,
            content=observation_text,
            metadata={
                "reason": decision.reason,
                "error": f"{type(exc).__name__}: {exc}",
                "recovery_class": decision.recovery_class.name,
            },
        )

    async def _emit_terminal_failure(
        self,
        *,
        exc: BaseException,
        recoveries_attempted: bool,
        runtime_handler: Optional[AgentRuntimeHandler],
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Emit the terminal failure events for an unrecovered exception.

        Yields ``recovery_exhausted`` first when a recovery had been attempted,
        then the ``run_failed`` trace and stream events (relocated here from
        ``_execute_iteration_with_retry``). Invoked by ``_react_loop`` just
        before it re-raises.

        Args:
            exc (BaseException): The unrecovered exception.
            recoveries_attempted (bool): Whether any recovery ran this submission.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.

        Yields:
            AgentStreamEventDAO: ``recovery_exhausted`` (conditional) then
                ``run_failed``.
        """
        if recoveries_attempted:
            yield AgentStreamEventDAO(
                kind="recovery_exhausted",
                iteration=self._current_iteration,
                content=f"{type(exc).__name__}: {exc}",
            )
        error_message: str = f"{type(exc).__name__}: {exc}"
        await self._emit_trace_event(
            runtime_handler=runtime_handler,
            event=AgentRuntimeEventDAO(
                kind="run_failed",
                iteration=self._current_iteration,
                payload=AgentRuntimePayloadDAO(error_message=error_message),
            ),
        )
        yield AgentStreamEventDAO(
            kind="run_failed",
            iteration=self._current_iteration,
            content=error_message,
        )

    async def _execute_run(
        self,
        *,
        query: str,
        history: Optional[list[dict]],
        message_history: Optional[list[BaseMessage]],
        runtime_handler: Optional[AgentRuntimeHandler],
        iteration_retry_policy: Optional[IterationRetryPolicy],
        iteration_recovery_policy: Optional[IterationRecoveryPolicy] = None,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Coordinate the full run lifecycle: abort check → preamble → loop → completion.

        The sequence is: optional pre-run abort fast-path → ``run_started`` trace →
        initial context construction → initial steering drain → ReAct loop →
        ``run_completed`` trace and event.

        Args:
            query (str): The user prompt.
            history (Optional[list[dict]]): Legacy dict-shaped prior conversation.
            message_history (Optional[list[BaseMessage]]): Projector-built messages.
            runtime_handler (Optional[AgentRuntimeHandler]): Trace observer.
            iteration_retry_policy (Optional[IterationRetryPolicy]): Retry decision callable.
            iteration_recovery_policy (Optional[IterationRecoveryPolicy]): LLM recovery
                decision callable.

        Yields:
            AgentStreamEventDAO: All stream events for this run.
        """
        if self._abort_event.is_set():
            async for event in self._handle_pre_run_abort(runtime_handler=runtime_handler):
                yield event
            return

        await self._emit_run_started_trace(query=query, runtime_handler=runtime_handler)

        accumulated_messages: list[BaseMessage] = self._build_initial_run_context(
            query=query,
            history=history,
            message_history=message_history,
        )
        async for event in self._apply_steering(
            accumulated_messages=accumulated_messages,
            iteration=0,
            runtime_handler=runtime_handler,
        ):
            yield event

        async for event in self._react_loop(
            accumulated_messages=accumulated_messages,
            runtime_handler=runtime_handler,
            iteration_retry_policy=iteration_retry_policy,
            iteration_recovery_policy=iteration_recovery_policy,
        ):
            yield event

        if self._abort_event.is_set():
            return  # run_aborted already yielded by _stream_graph_turn; skip run_completed

        await self._emit_trace_event(
            runtime_handler=runtime_handler,
            event=AgentRuntimeEventDAO(
                kind="run_completed",
                iteration=self._current_iteration,
                payload=AgentRuntimePayloadDAO(content=self._last_assistant_text),
            ),
        )
        yield AgentStreamEventDAO(
            kind="run_completed",
            iteration=self._current_iteration,
            content=self._last_assistant_text,
        )

    async def invoke(
        self,
        *,
        query: str,
        history: Optional[list[dict]] = None,
        message_history: Optional[list[BaseMessage]] = None,
        runtime_handler: Optional[AgentRuntimeHandler] = None,
        iteration_retry_policy: Optional[IterationRetryPolicy] = None,
        iteration_recovery_policy: Optional[IterationRecoveryPolicy] = None,
    ) -> AsyncGenerator[AgentStreamEventDAO, None]:
        """Run the multi-turn loop and yield normalized stream events.

        This is the canonical gateway for the agent. Each ReAct iteration is
        the retry unit (37.a.5): a switchable provider failure *before that
        iteration emits visible output* is retried in place via
        ``iteration_retry_policy``; a failure after visible output, a
        non-retryable error, or no injected policy surfaces ``run_failed`` and
        re-raises. When ``iteration_recovery_policy`` is injected, a recoverable
        escaped exception is demoted into a recovery observation and the loop
        re-enters up to ``self._recovery_budget`` times (feature 50).

        Args:
            query (str): The user prompt.
            history (Optional[list[dict]]): Optional prior conversation as
                ``[{'role': 'user'|'assistant', 'content': str}, ...]``.
            message_history (Optional[list[BaseMessage]]): Optional pre-built
                LangChain message history (typically from
                ``SessionHistoryProjector``). Mutually exclusive with ``history``.
            runtime_handler (Optional[AgentRuntimeHandler]): Optional
                correctness-critical trace observer.
            iteration_retry_policy (Optional[IterationRetryPolicy]): Per-iteration
                retry decision injected by the session. ``None`` preserves the
                legacy no-retry behavior.
            iteration_recovery_policy (Optional[IterationRecoveryPolicy]): Per-
                iteration LLM-recovery decision injected by the session.
                ``None`` preserves the legacy fail-fast behavior.

        Yields:
            AgentStreamEventDAO: Normalized visible delta, tool-result, and
                terminal run events.

        Raises:
            RuntimeError: If a run is already in progress on this instance.
            ValueError: If both ``history`` and ``message_history`` are supplied.
        """
        self._validate_invoke_inputs(history=history, message_history=message_history)
        self._initialize_run_state()
        try:
            async for event in self._execute_run(
                query=query,
                history=history,
                message_history=message_history,
                runtime_handler=runtime_handler,
                iteration_retry_policy=iteration_retry_policy,
                iteration_recovery_policy=iteration_recovery_policy,
            ):
                yield event
        finally:
            self._teardown_run_state()

    def steer(self, message: str | BaseMessage) -> None:
        """Queue a message to inject before the next agent turn.

        Steering enqueued before ``invoke`` is called is drained into the
        first turn's message list. Steering enqueued during a run is drained
        between turns.

        Args:
            message (str | BaseMessage): Either raw text or a prebuilt
                LangChain message.
        """
        msg: BaseMessage = HumanMessage(content=message) if isinstance(message, str) else message
        self._steering_queue.put_nowait(msg)

    def abort(self) -> None:
        """Request graceful cancellation of the current run.

        The next graph update sees ``self._abort_event`` set and yields
        a terminal ``run_aborted`` stream event.
        """
        self._abort_event.set()

    # ---- Private helpers --------------------------------------------------

    @staticmethod
    def _is_committed_output_event(*, event: AgentStreamEventDAO) -> bool:
        """Return whether an event crosses the iteration commit boundary.

        A delta, a tool-call start, a tool result, or a completed assistant
        update can represent visible or side-effecting work. The session must
        never automatically replay that iteration after this point.
        """
        return event.kind in {"thinking_delta", "text_delta", "tool_call_start", "tool_result", "text_end"}

    @staticmethod
    def _is_visible_output_event(*, event: AgentStreamEventDAO) -> bool:
        """Return True when ``event`` is visible transcript output for the iteration.

        Mirrors the session's visible-output gate: once an iteration streams any
        of these kinds, retrying it would risk duplicate or corrupt transcript,
        so a later failure in the same iteration must surface rather than retry.

        Args:
            event (AgentStreamEventDAO): The stream event under inspection.

        Returns:
            bool: True for thinking/text deltas, tool-call starts, and tool results.
        """
        return SloAgent._is_committed_output_event(event=event)

    def _decide_iteration_retry(
        self,
        *,
        iteration_retry_policy: Optional[IterationRetryPolicy],
        exc: BaseException,
        saw_visible_output_this_iteration: bool,
        attempt_number: int,
    ) -> RateLimitRetryPlanDAO:
        """Resolve whether to retry the current iteration after a failure.

        Returns a non-retryable plan when no policy was injected (test/default
        path), when the iteration already emitted visible output (silent replay
        would duplicate transcript), or when the policy declines. Otherwise
        returns the policy's plan.

        Args:
            iteration_retry_policy (Optional[IterationRetryPolicy]): Injected
                decision callable, or ``None`` for the no-retry default.
            exc (BaseException): The raised exception.
            saw_visible_output_this_iteration (bool): Whether this iteration
                streamed visible output before failing.
            attempt_number (int): One-indexed attempt count for this iteration.

        Returns:
            RateLimitRetryPlanDAO: The retry decision for this iteration.
        """
        if iteration_retry_policy is None or saw_visible_output_this_iteration:
            return RateLimitRetryPlanDAO(
                retryable=False,
                wait_seconds=0,
                message=f"{type(exc).__name__}: {exc}",
            )
        return iteration_retry_policy(exc, saw_visible_output_this_iteration, attempt_number)

    def _resolve_supports_explicit_caching(self) -> bool:
        """Return whether the current route needs explicit cache_control markers.

        For a ``ModelPool`` the active route can change between turns, so this
        reads the pool's live ``supports_explicit_caching`` (duck-typed) at
        message-build time, reflecting the previous turn's final route. For a
        single model it falls back to the static build-time flag. Cache markers
        only affect the first attempt and are ignored by non-Anthropic providers,
        so a same-turn route switch is benign.

        Returns:
            bool: True when the system message should carry a cache_control marker.
        """
        dynamic = getattr(self._llm, "supports_explicit_caching", None)
        if isinstance(dynamic, bool):
            return dynamic
        return self._supports_explicit_caching

    def _build_initial_messages(
        self,
        query: str,
        history: Optional[list[dict]] = None,
        message_history: Optional[list[BaseMessage]] = None,
    ) -> list[BaseMessage]:
        """Assemble the initial message list for a run.

        Accepts either the legacy ``history`` (``list[dict]``) or the
        projector-built ``message_history`` (``list[BaseMessage]``) but
        never both. The system prompt is always prepended by the
        agent; projected history must therefore exclude it.

        Args:
            query (str): The user prompt.
            history (Optional[list[dict]]): Legacy dict-shaped prior
                conversation entries.
            message_history (Optional[list[BaseMessage]]): Projector-
                built prior LangChain messages.

        Returns:
            list[BaseMessage]:
                ``[SystemMessage, *history_or_message_history, HumanMessage(query)]``.

        Raises:
            ValueError: If both history representations are supplied.
        """
        if history is not None and message_history is not None:
            raise ValueError("Pass only one of `history` or `message_history` to SloAgent.")
        _cache_kwargs: dict = (
            {"additional_kwargs": {"cache_control": {"type": "ephemeral"}}}
            if self._resolve_supports_explicit_caching()
            else {}
        )
        messages: list[BaseMessage] = [SystemMessage(content=self._system_prompt, **_cache_kwargs)]
        if message_history:
            messages.extend(message_history)
        elif history:
            messages.extend(self._history_to_messages(history=history))
        messages.append(HumanMessage(content=query))
        return messages

    def _drain(self, queue: asyncio.Queue[BaseMessage]) -> list[BaseMessage]:
        """Drain an asyncio.Queue into a list, leaving the queue empty.

        Args:
            queue (asyncio.Queue[BaseMessage]): The queue to drain.

        Returns:
            list[BaseMessage]: Items in FIFO order.
        """
        drained: list[BaseMessage] = []
        while not queue.empty():
            drained.append(queue.get_nowait())
        return drained

    def _chunk_message_delta(self, chunk: dict) -> list[BaseMessage]:
        """Extract the new messages a node added in one ``stream_mode='updates'`` chunk.

        Args:
            chunk (dict): A LangGraph update chunk, shaped
                ``{node_name: delta}``.

        Returns:
            list[BaseMessage]: The ``messages`` list from the delta, or
                empty if the node produced none.
        """
        if not chunk:
            return []
        _, delta = next(iter(chunk.items()))
        return list(delta.get("messages") or [])

    def _last_turn_has_tool_calls(self, messages: list[BaseMessage]) -> bool:
        """Return True iff the most recent AIMessage in ``messages`` has tool calls.

        Args:
            messages (list[BaseMessage]): The accumulated message list.

        Returns:
            bool: True iff the latest ``AIMessage`` carries one or more
                ``tool_calls``. False if there is no ``AIMessage`` or
                the latest one stopped without calling tools.
        """
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return bool(msg.tool_calls)
        return False

    def _turn_to_hook_accumulator(
        self,
        *,
        turn: TurnStreamAccumulator,
    ) -> TurnAccumulatorDAO:
        """Convert completed turn state into the stop-hook accumulator shape.

        Args:
            turn (TurnStreamAccumulator): Completed turn state from the
                updates channel.

        Returns:
            TurnAccumulatorDAO: Hook-facing turn accumulator.
        """
        hook_turn: TurnAccumulatorDAO = TurnAccumulatorDAO()
        for message in turn.completed_messages:
            hook_turn.absorb(message=message)
        return hook_turn

    async def _evaluate_stop_hook(
        self,
        *,
        turn: TurnAccumulatorDAO,
        messages: list[BaseMessage],
    ) -> bool:
        """Build the hook context for the turn and delegate to ``Hook``.

        Returns ``False`` early when the turn produced no assistant
        message — the hook context requires one (Pydantic enforces the
        non-optional field).

        Args:
            turn (TurnAccumulatorDAO): The just-completed turn's
                accumulator.
            messages (list[BaseMessage]): Full accumulated message list.

        Returns:
            bool: The hook's verdict for this turn, or ``False`` when
                no assistant message exists yet.
        """
        if turn.assistant_message is None:
            return False
        context: ShouldStopAfterTurnHookContextDAO = ShouldStopAfterTurnHookContextDAO(
            message=turn.assistant_message,
            tool_results=list(turn.tool_results),
            messages=list(messages),
        )
        return await Hook.evaluate_should_stop_after_turn_hook(
            hook=self._should_stop_after_turn_hook,
            context=context,
        )

    def _stream_events_from_update_messages(
        self,
        *,
        messages: list[BaseMessage],
        iteration: int,
    ) -> list[AgentStreamEventDAO]:
        """Convert completed update-channel messages into stream events.

        Ownership rules:

        - ``AIMessage`` from ``updates`` does NOT emit visible text deltas.
          It is terminal truth only.
        - ``ToolMessage`` from ``updates`` DOES emit ``tool_result``.

        Args:
            messages (list[BaseMessage]): Completed messages from one updates chunk.
            iteration (int): Outer-loop iteration number.

        Returns:
            list[AgentStreamEventDAO]: Update-channel-derived events.
        """
        events: list[AgentStreamEventDAO] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            events.append(
                AgentStreamEventDAO(
                    kind="tool_result",
                    iteration=iteration,
                    tool_name=message.name or "tool",
                    tool_call_id=message.tool_call_id or None,
                    content=(message.content if isinstance(message.content, str) else str(message.content)),
                )
            )
        return events

    async def _emit_trace_event(
        self,
        *,
        runtime_handler: Optional[AgentRuntimeHandler],
        event: AgentRuntimeEventDAO,
    ) -> None:
        """Forward one trace event to the caller-supplied handler.

        No-ops when ``runtime_handler`` is ``None`` so callers that do
        not care about full-fidelity capture pay nothing.

        Args:
            runtime_handler (Optional[AgentRuntimeHandler]): The
                caller's trace observer.
            event (AgentRuntimeEventDAO): The runtime event to forward.
        """
        if runtime_handler is None:
            return
        await runtime_handler(event)

    async def _emit_stream_trace_event(
        self,
        *,
        runtime_handler: Optional[AgentRuntimeHandler],
        stream_event: AgentStreamEventDAO,
    ) -> None:
        """Map replay-safe visible stream events onto the runtime trace seam.

        Args:
            runtime_handler (Optional[AgentRuntimeHandler]): Correctness-critical trace sink.
            stream_event (AgentStreamEventDAO): Normalized visible stream event.
        """
        if runtime_handler is None:
            return
        if stream_event.kind not in {
            "thinking_start",
            "thinking_delta",
            "thinking_end",
            "text_start",
            "text_delta",
            "text_end",
        }:
            return
        await runtime_handler(
            AgentRuntimeEventDAO(
                kind="assistant_delta",
                iteration=stream_event.iteration,
                payload=AgentRuntimePayloadDAO(
                    delta_kind=stream_event.kind,
                    block_id=stream_event.block_id,
                    delta=stream_event.delta,
                    content=stream_event.content,
                    redacted=stream_event.redacted,
                ),
            )
        )

    async def _emit_steering_traces(
        self,
        *,
        runtime_handler: Optional[AgentRuntimeHandler],
        messages: list[BaseMessage],
    ) -> None:
        """Emit one ``steering_message`` trace per drained steering message.

        Args:
            runtime_handler (Optional[AgentRuntimeHandler]): The trace observer.
            messages (list[BaseMessage]): Drained steering messages.
        """
        for message in messages:
            await self._emit_trace_event(
                runtime_handler=runtime_handler,
                event=AgentRuntimeEventDAO(
                    kind="steering_message",
                    iteration=self._current_iteration,
                    payload=AgentRuntimePayloadDAO(
                        content=(
                            message.content if isinstance(message.content, str) else str(message.content)
                        ),
                    ),
                ),
            )

    @staticmethod
    def _steering_applied_events(
        *,
        messages: list[BaseMessage],
        iteration: int,
    ) -> list[AgentStreamEventDAO]:
        """Build one ``steering_applied`` stream event per drained steer message.

        These let the interactive surface render a queued steer as a regular
        user message the moment the agent actually folds it into the model
        context — the visible counterpart to the pending marker the TUI
        shows when the steer is first queued.

        Args:
            messages (list[BaseMessage]): Drained steering messages.
            iteration (int): The iteration the messages were folded into.

        Returns:
            list[AgentStreamEventDAO]: One ``steering_applied`` event each.
        """
        events: list[AgentStreamEventDAO] = []
        for message in messages:
            content: str = (
                message.content if isinstance(message.content, str) else str(message.content)
            )
            events.append(
                AgentStreamEventDAO(
                    kind="steering_applied",
                    iteration=iteration,
                    content=content,
                )
            )
        return events

    def _trace_events_from_messages(
        self,
        *,
        messages: list[BaseMessage],
    ) -> list[AgentRuntimeEventDAO]:
        """Build full-fidelity runtime trace events from completed messages.

        Args:
            messages (list[BaseMessage]): Completed messages from one updates chunk.

        Returns:
            list[AgentRuntimeEventDAO]: Full-fidelity trace events for the batch.
        """
        events: list[AgentRuntimeEventDAO] = []
        for message in messages:
            events.extend(self._trace_events_from_message(message=message))
        return events

    def _trace_events_from_message(
        self,
        *,
        message: BaseMessage,
    ) -> list[AgentRuntimeEventDAO]:
        """Translate one raw LangChain message into runtime trace events.

        Args:
            message (BaseMessage): One raw message emitted by the graph.

        Returns:
            list[AgentRuntimeEventDAO]: Full-fidelity trace events for
                that message. Empty for messages we do not represent.
        """
        if isinstance(message, AIMessage):
            if message.tool_calls:
                events: list[AgentRuntimeEventDAO] = []
                for tool_call in message.tool_calls:
                    events.append(
                        AgentRuntimeEventDAO(
                            kind="tool_call",
                            iteration=self._current_iteration,
                            payload=AgentRuntimePayloadDAO(
                                content=assistant_message_text(message=message),
                                tool_name=tool_call.get("name"),
                                tool_call_id=tool_call.get("id"),
                                tool_input=dict(tool_call.get("args") or {}),
                                tool_calls=list(message.tool_calls),  # type: ignore[arg-type]  # ToolCall is a TypedDict
                            ),
                        )
                    )
                return events
            content_text: str = assistant_message_text(message=message)
            return [
                AgentRuntimeEventDAO(
                    kind="assistant_message",
                    iteration=self._current_iteration,
                    payload=AgentRuntimePayloadDAO(content=content_text),
                )
            ]
        if isinstance(message, ToolMessage):
            image_reference: str | None = message.additional_kwargs.get("image_reference")
            tool_output: str = (
                image_reference
                if image_reference is not None
                else (message.content if isinstance(message.content, str) else str(message.content))
            )
            return [
                AgentRuntimeEventDAO(
                    kind="tool_result",
                    iteration=self._current_iteration,
                    payload=AgentRuntimePayloadDAO(
                        tool_name=message.name,
                        tool_call_id=getattr(message, "tool_call_id", None),
                        tool_output=tool_output,
                    ),
                )
            ]
        return []

    @classmethod
    def _history_to_messages(cls, *, history: list[dict]) -> list[BaseMessage]:
        """Convert ``[{'role': ..., 'content': ...}]`` to LangChain message objects.

        Unknown roles (including ``"system"``) are silently skipped —
        the agent's own system prompt rules.

        Args:
            history (list[dict]): Prior conversation entries with
                ``role`` and ``content`` keys.

        Returns:
            list[BaseMessage]: Translated LangChain messages, preserving
                ``history`` order and skipping unknown roles.
        """
        out: list[BaseMessage] = []
        for item in history:
            role: str = (item.get("role") or "").lower()
            content: Any = item.get("content") or ""
            if role == "user":
                out.append(HumanMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
        return out
