"""Core compaction logic for Slo session history (sub-spec 01.a.7).

Identifies the cut point in an event list, renders the compacted slice as
human-readable text, calls an LLM to summarise, and returns a
CompactionResult.  No I/O except the single LLM call; the caller persists
the result.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from config.ai_model_config import MODEL_DEFAULTS, ModelDefaults
from src.agents.slo_agent.compaction.constants import (
    COMPACTION_INPUT_SAFETY_DIVISOR,
    DEFAULT_CONTEXT_WINDOW,
    KEEP_RECENT_TOKENS,
    RESERVED_TOKEN_LIMIT,
)
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO

__all__ = ["CompactionResult", "Compacter"]


def _get_context_window(*, model_name: str) -> int:
    """Return the input context-window token limit for ``model_name``.

    Args:
        model_name (str): Model identifier used by the session.

    Returns:
        int: Context window in tokens; falls back to ``DEFAULT_CONTEXT_WINDOW``.
    """
    defaults: Optional[ModelDefaults] = MODEL_DEFAULTS.get(model_name)
    if defaults is None:
        return DEFAULT_CONTEXT_WINDOW
    return defaults.get("context_window", DEFAULT_CONTEXT_WINDOW)


def _max_compaction_input_token_units(*, context_window: int) -> int:
    """Return the safe compaction-input budget in chars/4 token-units.

    The chars/4 approximation used by ``SessionHistoryEventPayloadDAO.token_usage``
    underestimates actual token count for code-heavy content by up to 3×.
    Applying ``COMPACTION_INPUT_SAFETY_DIVISOR`` to the available context window
    (after reserving headroom for the LLM response) keeps the summarisation call
    safely within the model's real limit even under worst-case underestimation.

    Args:
        context_window (int): Model context window in actual tokens.

    Returns:
        int: Maximum compaction-input token-units before the LLM call would
            risk overflowing the model.
    """
    available: int = max(0, context_window - RESERVED_TOKEN_LIMIT)
    return max(1, available // COMPACTION_INPUT_SAFETY_DIVISOR)


class CompactionResult(BaseModel):
    """Result of one compaction run."""

    summary_text: str = Field(description="LLM-generated summary inserted at cut_point.")
    first_kept_entry_id: str = Field(description="ID of first history event retained in full.")
    cut_point_entry_id: str = Field(description="ID of event where the summary was inserted.")
    tokens_before: int = Field(description="Estimated token count before compaction.")
    tokens_after: int = Field(description="Estimated token count after compaction.")


_SKIP_KINDS: frozenset[str] = frozenset(
    {
        "session_started",
        "run_started",
        "run_completed",
        "run_aborted",
        "run_failed",
        "run_retrying",
        "route_switched",
        "assistant_delta",
        "slash_command",
        "orchestrator_started",
        "sub_agent_spawned",
        "sub_agent_completed",
    }
)

_SYSTEM_PROMPT_TEMPLATE: str = (
    "You are a conversation compactor for an AI coding assistant called Slo. "
    "Your task is to produce a concise but complete summary of the conversation "
    "history shown below. The summary will replace the original messages in the "
    "agent's context window, so it must preserve:\n"
    "- Every decision, conclusion, and file path that was established.\n"
    "- Every tool call and its result, including errors and retries.\n"
    "- The user's original intent and any mid-conversation corrections.\n"
    "- Any outstanding tasks or open questions at the time of compaction.\n\n"
    "Write in plain prose. Do not truncate tool outputs that contain critical "
    "information (file contents, error messages, command output). Be terse on "
    "small-talk and boilerplate, thorough on substance.\n\n"
    "Active model: {model_name}"
)


class Compacter:
    """Compact old session events into an LLM-generated summary.

    All methods are classmethods; the class is stateless.  Entry point is
    ``compact()``.
    """

    @classmethod
    async def compact(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        model_name: str,
        llm: BaseChatModel,
        context_window: Optional[int] = None,
    ) -> CompactionResult:
        """Compact old events into an LLM summary, returning bookkeeping metadata.

        Identifies the cut point, builds the compaction input text, calls the
        LLM to summarise, and returns a CompactionResult. Does not write to
        disk — the caller is responsible for persisting the result via the
        store's append_compaction_summary().

        When the compacted slice is too large for the model's context window
        (which can happen because the chars/4 token estimator underestimates
        code-heavy content), ``_cap_compacted_events`` trims it from the NEWEST
        end.  Overflow events are prepended to ``retained_events`` so they are
        kept verbatim in history and will be summarised on the next compaction
        pass. This prevents the summarisation call from itself overflowing the
        model — the failure mode that causes "(compacting session history)" to
        appear followed by an immediate run failure.

        Args:
            events (list[SessionHistoryEventDAO]): Full event list in append
                order (oldest first).
            model_name (str): Active model name; passed to the LLM system
                prompt for context and used to look up the context-window cap.
            llm (BaseChatModel): Bound LangChain chat model used for
                summarisation.
            context_window (Optional[int]): Override the model-table context
                window lookup. Primarily for tests. Defaults to ``None``
                (use ``MODEL_DEFAULTS``).

        Returns:
            CompactionResult: Summary text, cut-point ids, and token counts.

        Raises:
            ValueError: When the event list is too short or no viable cut
                point exists (propagated from _find_cut_point).
        """
        cut_point_index: int = cls._find_cut_point(events=events)

        compacted_events: list[SessionHistoryEventDAO] = events[: cut_point_index + 1]
        retained_events: list[SessionHistoryEventDAO] = events[cut_point_index + 1 :]

        # Cap the compacted slice so the summarisation LLM call cannot itself
        # overflow the model. Overflow events (too-recent-to-summarise-now) move
        # to retained_events and are handled on the next compaction pass.
        effective_context_window: int = (
            context_window if context_window is not None else _get_context_window(model_name=model_name)
        )
        max_input_units: int = _max_compaction_input_token_units(
            context_window=effective_context_window,
        )
        compacted_events, overflow_events = cls._cap_compacted_events(
            events=compacted_events,
            max_token_units=max_input_units,
        )
        retained_events = overflow_events + retained_events

        compaction_input: str = cls._build_compaction_input(events=compacted_events)
        summary_text: str = await cls._invoke_llm_summary(
            compaction_input=compaction_input,
            model_name=model_name,
            llm=llm,
        )

        tokens_before: int = sum(e.payload.token_usage or 0 for e in compacted_events)
        tokens_after: int = math.ceil(len(summary_text) / 4)

        return CompactionResult(
            summary_text=summary_text,
            first_kept_entry_id=retained_events[0].event_id,
            cut_point_entry_id=compacted_events[-1].event_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )

    # ---- Private helpers --------------------------------------------------

    @classmethod
    def _cap_compacted_events(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        max_token_units: int,
    ) -> tuple[list[SessionHistoryEventDAO], list[SessionHistoryEventDAO]]:
        """Split the compacted slice into a safe head and an overflow tail.

        Walks events from OLDEST to NEWEST, accumulating ``token_usage``.
        Once the running total would exceed ``max_token_units``, everything
        from that point onward is returned as overflow and will be prepended
        to ``retained_events`` by the caller. The head (events[:split]) is
        sent to the LLM for summarisation.

        At least one event is always included in the head (when the very first
        event exceeds the budget it is still included so compaction makes
        forward progress).

        Args:
            events (list[SessionHistoryEventDAO]): Compacted slice, oldest first.
            max_token_units (int): Token-unit budget for the summarisation input.

        Returns:
            tuple[list[SessionHistoryEventDAO], list[SessionHistoryEventDAO]]:
                ``(head, overflow)`` where ``head`` is safe to summarise and
                ``overflow`` is retained verbatim for the next compaction pass.
        """
        accumulated: int = 0
        for idx, event in enumerate(events):
            next_total: int = accumulated + (event.payload.token_usage or 0)
            if next_total > max_token_units and idx > 0:
                return events[:idx], events[idx:]
            accumulated = next_total
        return events, []

    @classmethod
    def has_viable_cut_point(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> bool:
        """Return whether durable events have a clean manual compaction cut.

        Args:
            events (list[SessionHistoryEventDAO]): Full event log in append order.

        Returns:
            bool: ``True`` when compaction can retain a valid tail without I/O.
        """
        try:
            cls._find_cut_point(events=events)
        except ValueError:
            return False
        return True

    @classmethod
    def _find_cut_point(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> int:
        """Return the index of the newest event that should be compacted.

        Walks events from newest to oldest, accumulating token_usage, until
        the retained window reaches or exceeds KEEP_RECENT_TOKENS. The cut
        point is the mirror index in the original list, subject to two rules:

        1. Clean cut. The cut must never split a tool span — a
           ``tool_call`` and its matching ``tool_result`` (and therefore a
           parallel tool-call batch, or a ``spawn_sub_agents`` group whose
           ``tool_call``/``tool_result`` straddle the interleaved sub-agent
           lifecycle events). When the token-driven candidate would split a
           span, the cut moves *up* (an earlier index, compacting more) until
           every retained ``tool_result`` keeps its ``tool_call`` — see
           ``_retreat_to_clean_cut``.
        2. First-message anchor. Never leave only the first ``user_message``
           uncompacted; if the cut would fall at or before it, advance past it
           (then re-clean).

        The returned cut always satisfies ``_is_clean_cut``.

        Args:
            events (list[SessionHistoryEventDAO]): Full event list in append
                order (oldest first).

        Returns:
            int: Index into events of the cut-point event (inclusive upper
                bound of the compacted slice).

        Raises:
            ValueError: When the event list is too short, the retain window
                covers the entire list, or no clean cut point exists.
        """
        if len(events) < 2:
            raise ValueError("Event list too short to find a cut point.")

        accumulated: int = 0
        candidate_cut: Optional[int] = None

        for rev_idx, event in enumerate(reversed(events)):
            forward_idx: int = len(events) - 1 - rev_idx
            accumulated += event.payload.token_usage or 0

            if accumulated >= KEEP_RECENT_TOKENS:
                # Everything from forward_idx onward is retained: once the
                # retained window reaches the KEEP_RECENT_TOKENS budget we
                # stop, so the budget is honoured exactly rather than
                # overshot by a whole event. The candidate cut is the event
                # just before that boundary.
                candidate_cut = forward_idx - 1
                break

        if candidate_cut is None:
            raise ValueError("Total token usage does not exceed KEEP_RECENT_TOKENS; " "no compaction needed.")

        if candidate_cut < 0:
            raise ValueError("No viable cut point: retain window covers the entire event list.")

        # Rule 1 (clean cut): retreat up until the cut splits no tool span.
        candidate_cut = cls._retreat_to_clean_cut(
            events=events,
            candidate_cut=candidate_cut,
        )
        if candidate_cut < 0:
            raise ValueError(
                "No viable clean cut point: a tool-call group spans the entire " "compactable range."
            )

        # Rule 2 (first-message anchor): never leave only the first
        # user_message uncompacted. Advancing the cut may re-enter a tool span,
        # so re-clean afterwards.
        first_user_idx: Optional[int] = next(
            (i for i, e in enumerate(events) if e.kind == "user_message"),
            None,
        )
        if first_user_idx is not None and candidate_cut <= first_user_idx:
            candidate_cut = first_user_idx + 1
            if candidate_cut >= len(events):
                raise ValueError(
                    "No viable cut point: all compactable events precede or " "equal the first user_message."
                )
            candidate_cut = cls._retreat_to_clean_cut(
                events=events,
                candidate_cut=candidate_cut,
            )

        if candidate_cut < 0 or not cls._is_clean_cut(events=events, cut=candidate_cut):
            raise ValueError(
                "No viable clean cut point: the computed boundary splits a tool "
                "span that cannot be avoided."
            )

        return candidate_cut

    @classmethod
    def _tool_spans(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> list[tuple[int, int]]:
        """Return ``(call_index, result_index)`` for every paired tool call.

        Walks the event list once, recording each ``tool_call`` by its
        ``tool_call_id`` and pairing it with the next ``tool_result`` carrying
        the same id. A parallel batch yields one span per id; a
        ``spawn_sub_agents`` call yields its own span. Unmatched calls or
        results are ignored — the cut only needs to avoid splitting *paired*
        spans. Events interleaved between a call and its result
        (``assistant_delta``, ``sub_agent_spawned``, ``sub_agent_completed``)
        are irrelevant to the span.

        Args:
            events (list[SessionHistoryEventDAO]): Full event list in append
                order (oldest first).

        Returns:
            list[tuple[int, int]]: ``(call_index, result_index)`` pairs.
        """
        call_index_by_id: dict[str, int] = {}
        spans: list[tuple[int, int]] = []
        for index, event in enumerate(events):
            tool_call_id: str = event.payload.tool_call_id or ""
            if not tool_call_id:
                continue
            if event.kind == "tool_call":
                call_index_by_id[tool_call_id] = index
            elif event.kind == "tool_result" and tool_call_id in call_index_by_id:
                spans.append((call_index_by_id[tool_call_id], index))
        return spans

    @classmethod
    def _retreat_to_clean_cut(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        candidate_cut: int,
    ) -> int:
        """Move the cut up until it splits no tool span.

        A span ``(call_idx, result_idx)`` is split when
        ``call_idx <= cut < result_idx`` — the call is compacted while the
        result is retained, which orphans the result. The retreat moves the cut
        to ``min(splitting call_idx) - 1`` and re-checks, pushing the whole
        group onto the compacted side. It always moves the cut *earlier*
        (compacting more), never later.

        Args:
            events (list[SessionHistoryEventDAO]): Full event list in append
                order (oldest first).
            candidate_cut (int): The token-walk cut to clean up.

        Returns:
            int: A clean cut index, or a negative index when no clean cut
                exists in range (a span covers the whole compactable prefix).
        """
        spans: list[tuple[int, int]] = cls._tool_spans(events=events)
        cut: int = candidate_cut
        while cut >= 0:
            splitting_calls: list[int] = [
                call_idx for (call_idx, result_idx) in spans if call_idx <= cut < result_idx
            ]
            if not splitting_calls:
                return cut
            cut = min(splitting_calls) - 1
        return cut

    @classmethod
    def _is_clean_cut(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
        cut: int,
    ) -> bool:
        """Return True when ``events[cut+1:]`` is a self-contained slice.

        The retained slice must contain no ``tool_result`` whose ``tool_call``
        is at index ``<= cut`` — i.e. the cut splits no tool span. This is the
        cut-completeness invariant asserted before a cut is returned.

        Args:
            events (list[SessionHistoryEventDAO]): Full event list in append
                order (oldest first).
            cut (int): The cut index to validate.

        Returns:
            bool: ``True`` when no retained tool_result is orphaned by the cut.
        """
        return all(
            not (call_idx <= cut < result_idx) for (call_idx, result_idx) in cls._tool_spans(events=events)
        )

    @classmethod
    def _build_compaction_input(
        cls,
        *,
        events: list[SessionHistoryEventDAO],
    ) -> str:
        """Render the compacted event slice as a human-readable text block.

        Lifecycle events that carry no conversational content are skipped.
        tool_call events include the tool name and serialised arguments.
        tool_result events include the tool name and output.

        Args:
            events (list[SessionHistoryEventDAO]): Events to compact, oldest
                first, already sliced to the cut point.

        Returns:
            str: A human-readable text block suitable for LLM summarisation.
        """
        lines: list[str] = []

        for event in events:
            if event.kind in _SKIP_KINDS:
                continue

            payload = event.payload

            if event.kind == "user_message":
                lines.append(f"user: {payload.content or ''}")

            elif event.kind == "steering_message":
                lines.append(f"system (steering): {payload.content or ''}")

            elif event.kind == "assistant_message":
                lines.append(f"assistant: {payload.content or ''}")

            elif event.kind == "tool_call":
                tool_name: str = payload.tool_name or "unknown_tool"
                tool_args: str = str(payload.tool_input or {})
                lines.append(f"tool_call [{tool_name}]: {tool_args}")

            elif event.kind == "tool_result":
                tool_name_r: str = payload.tool_name or "unknown_tool"
                output: str = payload.tool_output or ""
                lines.append(f"tool_result [{tool_name_r}]: {output}")

            elif event.kind == "compaction_summary":
                lines.append(f"[prior summary]: {payload.content or ''}")

        return "\n\n".join(lines)

    @classmethod
    async def _invoke_llm_summary(
        cls,
        *,
        compaction_input: str,
        model_name: str,
        llm: BaseChatModel,
    ) -> str:
        """Call the LLM to produce a summary of the compacted event block.

        Sends a system prompt instructing the model to be concise but
        complete, followed by the compaction input as a human message. Caps
        the response at RESERVED_TOKEN_LIMIT tokens.

        Args:
            compaction_input (str): Human-readable rendering of the events
                to be summarised.
            model_name (str): Active model name, included in the system
                prompt for context.
            llm (BaseChatModel): Bound LangChain chat model to invoke.

        Returns:
            str: The LLM's summary text.
        """
        system_prompt: str = _SYSTEM_PROMPT_TEMPLATE.format(model_name=model_name)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=compaction_input),
        ]

        # ``max_tokens`` is a per-call model kwarg (forwarded by ``ainvoke``
        # to the underlying model), not a ``RunnableConfig`` key — passing it
        # as ``config`` is both a type error and a no-op. Capping the response
        # at RESERVED_TOKEN_LIMIT keeps the compaction turn inside its budget.
        response = await llm.ainvoke(
            input=messages,
            max_tokens=RESERVED_TOKEN_LIMIT,
        )

        content = response.content
        if isinstance(content, list):
            # Structured content blocks (Anthropic tool-use format).
            text_parts: list[str] = [
                block if isinstance(block, str) else block.get("text", "")
                for block in content
                if isinstance(block, (str, dict))
            ]
            return "".join(text_parts)

        return str(content)
