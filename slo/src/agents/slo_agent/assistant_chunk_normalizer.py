"""Normalize ``AIMessageChunk`` objects into Slo stream events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ClassVar, Optional

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.tool import ToolCall, ToolCallChunk, tool_call_chunk

from src.agents.slo_agent.message_text import (
    assistant_message_reasoning_text,
    assistant_message_text,
)
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = ["AssistantChunkNormalizer"]


class AssistantChunkNormalizer:
    """Per-turn stateful normalizer for assistant chunks.

    One instance is created per attempt of one outer-loop iteration. It
    remembers which thinking/text/tool-call blocks are currently open so it can
    emit deterministic ``*_start`` and ``*_end`` events.

    Tool calls are keyed by the provider's opaque call id; id-less follow-up
    fragments are routed by their slot (``index``). For every call id a named
    ``tool_call_start`` precedes any delta or end, and ``tool_call_end`` is
    emitted at most once: closed ids stay terminal for this instance's lifetime.
    """

    # Content block type -> (call-id key, argument-text key); ``tool_use`` is handled separately.
    _TOOL_CALL_CONTENT_FIELD_KEYS: ClassVar[dict[str, tuple[str | None, str]]] = {
        "tool_call_chunk": ("id", "args"),
        "function_call": ("call_id", "arguments"),
        "input_json_delta": (None, "partial_json"),
    }

    def __init__(self, *, iteration: int) -> None:
        """Seed empty block state for one turn.

        Args:
            iteration (int): Outer-loop iteration number.
        """
        self._iteration: int = iteration
        self._open_thinking_block_id: Optional[str] = None
        self._implicitly_closed_thinking_block_id: Optional[str] = None
        self._open_text_block_id: Optional[str] = None
        self._open_tool_call_ids: set[str] = set()
        self._tool_call_names: dict[str, str] = {}
        self._tool_call_argument_buffers: dict[str, str] = {}
        # Terminal ids: ended once, or discarded unnamed. Kept for this normalizer's lifetime.
        self._closed_tool_call_ids: set[str] = set()
        # The call id opened most recently at each slot; routes id-less follow-up fragments.
        self._tool_call_id_by_index: dict[int, str] = {}

    def absorb_chunk(self, *, chunk: AIMessageChunk) -> list[AgentStreamEventDAO]:
        """Normalize one assistant chunk into ordered stream events.

        Text and thinking come from ``chunk.content``. Tool-call events come from
        exactly one source per chunk (see ``_extract_tool_call_fragments``), so a
        call carried in both ``tool_call_chunks`` and content blocks is read once.

        Args:
            chunk (AIMessageChunk): One assistant chunk from LangChain.

        Returns:
            list[AgentStreamEventDAO]: Ordered stream events.
        """
        events: list[AgentStreamEventDAO] = self._events_from_content_blocks(content=chunk.content)
        for fragment in self._extract_tool_call_fragments(chunk=chunk):
            events.extend(self._absorb_tool_call_fragment(fragment=fragment))
        return events

    def finalize_open_blocks(
        self,
        *,
        completed_assistant_message: AIMessage | None = None,
    ) -> list[AgentStreamEventDAO]:
        """Close every still-open block; idempotent for tool calls.

        ``SloAgent`` calls this twice per iteration with the same completed
        message: once when the completed ``AIMessage`` arrives on the updates
        channel, and again at iteration end as a safety net. The first call
        emits the closing events; the second normally emits nothing, because
        every tool call id it closed is terminal for this normalizer's lifetime.
        Text or thinking opened after the first call is still closed.

        Completed assistant messages carry better final formatting than raw
        streamed deltas, so their reasoning text, answer text and tool-call
        arguments are threaded into the closing events.

        Args:
            completed_assistant_message (AIMessage | None): Optional
                completed assistant message from the updates channel.

        Returns:
            list[AgentStreamEventDAO]: Text/thinking closing events, then tool-call
                closing events (a named ``tool_call_start`` precedes the end of any
                call that never had one).
        """
        return [
            *self._finalize_text_and_thinking(completed_assistant_message=completed_assistant_message),
            *self._finalize_tool_calls(completed_assistant_message=completed_assistant_message),
        ]

    def _finalize_text_and_thinking(
        self,
        *,
        completed_assistant_message: AIMessage | None,
    ) -> list[AgentStreamEventDAO]:
        """Close open thinking/text blocks and repair an implicitly closed thinking block.

        For a thinking block that ``_emit_text_delta`` closed implicitly (answer
        text arrived before the turn ended), a second repair ``thinking_end``
        carries the completed reasoning text so ``TranscriptProjectionAdapter``
        can replace the malformed concatenated text with the provider's final view.

        Args:
            completed_assistant_message (AIMessage | None): Completed message whose
                reasoning and answer text become the closing content, when present.

        Returns:
            list[AgentStreamEventDAO]: ``thinking_end`` and ``text_end`` events.
        """
        reasoning_text: str = ""
        answer_text: str = ""
        if completed_assistant_message is not None:
            reasoning_text = assistant_message_reasoning_text(message=completed_assistant_message)
            answer_text = assistant_message_text(message=completed_assistant_message)

        events: list[AgentStreamEventDAO] = []
        if self._open_thinking_block_id is not None:
            events.append(
                AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=self._iteration,
                    block_id=self._open_thinking_block_id,
                    content=reasoning_text or None,
                )
            )
            self._open_thinking_block_id = None
        if self._implicitly_closed_thinking_block_id is not None and reasoning_text:
            events.append(
                AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=self._iteration,
                    block_id=self._implicitly_closed_thinking_block_id,
                    content=reasoning_text,
                )
            )
            self._implicitly_closed_thinking_block_id = None
        if self._open_text_block_id is not None:
            events.append(
                AgentStreamEventDAO(
                    kind="text_end",
                    iteration=self._iteration,
                    block_id=self._open_text_block_id,
                    content=answer_text or None,
                )
            )
            self._open_text_block_id = None
        return events

    def _finalize_tool_calls(
        self,
        *,
        completed_assistant_message: AIMessage | None,
    ) -> list[AgentStreamEventDAO]:
        """Close completed calls in message order, then remaining open ids in sorted order.

        Completed-only calls (never streamed) are treated as implicitly open
        requests. Afterwards the transient open set, names and argument buffers
        are cleared; terminal ids and slot mappings are kept until this
        normalizer is discarded, so a repeated finalization emits nothing.

        Args:
            completed_assistant_message (AIMessage | None): Completed message whose
                tool calls supply the final names and arguments, when present.

        Returns:
            list[AgentStreamEventDAO]: Tool-call closing events.
        """
        completed_tool_calls_by_id: dict[str, ToolCall] = (
            {}
            if completed_assistant_message is None
            else self._completed_tool_calls_by_id(message=completed_assistant_message)
        )
        events: list[AgentStreamEventDAO] = []
        for tool_call_id, completed_tool_call in completed_tool_calls_by_id.items():
            events.extend(
                self._close_tool_call(tool_call_id=tool_call_id, completed_tool_call=completed_tool_call)
            )
        for tool_call_id in sorted(self._open_tool_call_ids - completed_tool_calls_by_id.keys()):
            events.extend(self._close_tool_call(tool_call_id=tool_call_id, completed_tool_call=None))
        self._open_tool_call_ids.clear()
        self._tool_call_names.clear()
        self._tool_call_argument_buffers.clear()
        return events

    def _close_tool_call(
        self,
        *,
        tool_call_id: str,
        completed_tool_call: ToolCall | None,
    ) -> list[AgentStreamEventDAO]:
        """Close one call id once, marking it terminal for this normalizer's lifetime.

        A terminal id emits nothing. A call with no completed or buffered name is
        discarded without events (no block was ever shown) but still becomes
        terminal. A named call that never had a named start first gets its
        ``tool_call_start``, so a start always precedes the end.

        Args:
            tool_call_id (str): Call id to close.
            completed_tool_call (ToolCall | None): The completed message's call
                with this id, or ``None`` when the call only streamed.

        Returns:
            list[AgentStreamEventDAO]: Nothing, ``[end]`` or ``[start, end]``.
        """
        if tool_call_id in self._closed_tool_call_ids:
            return []
        self._closed_tool_call_ids.add(tool_call_id)
        tool_name: str | None = self._resolved_tool_name(
            tool_call_id=tool_call_id,
            completed_tool_call=completed_tool_call,
        )
        if tool_name is None:
            return []
        events: list[AgentStreamEventDAO] = []
        if tool_call_id not in self._tool_call_names:
            # Completed-message starts use metadata index 0 by convention. A slot
            # mapping may exist, but display identity is the opaque call id, not this index.
            events.append(
                self._build_tool_call_start(tool_call_id=tool_call_id, tool_name=tool_name, content_index=0)
            )
        events.append(
            AgentStreamEventDAO(
                kind="tool_call_end",
                iteration=self._iteration,
                block_id=tool_call_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_input=self._resolved_tool_input(
                    tool_call_id=tool_call_id,
                    completed_tool_call=completed_tool_call,
                ),
            )
        )
        return events

    def _build_tool_call_start(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        content_index: int,
    ) -> AgentStreamEventDAO:
        """Build the named ``tool_call_start`` event for one call id.

        Args:
            tool_call_id (str): Call id, also used as the block id.
            tool_name (str): Resolved, non-empty tool name.
            content_index (int): Provider slot for streamed starts; completed-message
                starts use ``0`` by convention even if a slot mapping exists.

        Returns:
            AgentStreamEventDAO: The start event.
        """
        return AgentStreamEventDAO(
            kind="tool_call_start",
            iteration=self._iteration,
            block_id=tool_call_id,
            content_index=content_index,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

    def _events_from_content_blocks(self, *, content: object) -> list[AgentStreamEventDAO]:
        """Normalize ``chunk.content`` into visible text and thinking events.

        Tool blocks are not read here; ``_extract_tool_call_fragments`` owns them.

        Args:
            content (object): ``AIMessageChunk.content`` payload.

        Returns:
            list[AgentStreamEventDAO]: Normalized visible text events.
        """
        if isinstance(content, str):
            if not content:
                return []
            return self._emit_text_delta(
                block_id=f"text:{self._iteration}:0",
                content_index=0,
                text=content,
            )
        if not isinstance(content, list):
            return []

        events: list[AgentStreamEventDAO] = []
        for content_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            block_type: str = str(block.get("type", ""))
            if block_type in {"reasoning", "thinking"}:
                events.extend(
                    self._events_from_reasoning_block(
                        block=block,
                        content_index=content_index,
                    )
                )
                continue
            if block_type in {"text", "output_text"}:
                events.extend(
                    self._events_from_text_block(
                        block=block,
                        content_index=content_index,
                    )
                )
        return events

    def _events_from_reasoning_block(
        self,
        *,
        block: dict[str, Any],
        content_index: int,
    ) -> list[AgentStreamEventDAO]:
        """Emit visible thinking events for one reasoning block.

        Args:
            block (dict[str, Any]): Provider content block.
            content_index (int): Block index within the chunk.

        Returns:
            list[AgentStreamEventDAO]: Zero or more thinking events.
        """
        block_id: str = f"thinking:{self._iteration}:{content_index}"
        visible_text: Optional[str] = self._visible_reasoning_text(block=block)
        if not visible_text:
            if self._is_reasoning_redacted(block=block):
                return [
                    AgentStreamEventDAO(
                        kind="thinking_start",
                        iteration=self._iteration,
                        block_id=block_id,
                        content_index=content_index,
                        redacted=True,
                        metadata={"provider_block_type": str(block.get("type", ""))},
                    ),
                    AgentStreamEventDAO(
                        kind="thinking_end",
                        iteration=self._iteration,
                        block_id=block_id,
                        content_index=content_index,
                        redacted=True,
                    ),
                ]
            return []
        return self._emit_thinking_delta(
            block_id=block_id,
            content_index=content_index,
            text=visible_text,
        )

    def _events_from_text_block(
        self,
        *,
        block: dict[str, Any],
        content_index: int,
    ) -> list[AgentStreamEventDAO]:
        """Emit visible answer-text events for one text block.

        Args:
            block (dict[str, Any]): Provider content block.
            content_index (int): Block index within the chunk.

        Returns:
            list[AgentStreamEventDAO]: Zero or more text events.
        """
        text: Optional[str] = self._visible_text_text(block=block)
        if not text:
            return []
        return self._emit_text_delta(
            block_id=f"text:{self._iteration}:{content_index}",
            content_index=content_index,
            text=text,
        )

    @classmethod
    def _extract_tool_call_fragments(cls, *, chunk: AIMessageChunk) -> list[ToolCallChunk]:
        """Read one chunk's tool-call fragments from exactly one source.

        A non-empty ``tool_call_chunks`` is authoritative and the content blocks
        are ignored, because providers that fill both (OpenAI Responses
        ``responses/v1``, Anthropic) describe the same fragment twice. Otherwise
        content tool blocks are converted to the same ``ToolCallChunk`` shape.

        Args:
            chunk (AIMessageChunk): One streamed assistant chunk.

        Returns:
            list[ToolCallChunk]: Fragments in chunk order; empty when none.
        """
        if chunk.tool_call_chunks:
            return list(chunk.tool_call_chunks)
        if not isinstance(chunk.content, list):
            return []
        fragments: list[ToolCallChunk] = []
        for block in chunk.content:
            if not isinstance(block, Mapping):
                continue
            fragment: ToolCallChunk | None = cls._build_tool_call_fragment_from_content(block=block)
            if fragment is not None:
                fragments.append(fragment)
        return fragments

    @classmethod
    def _build_tool_call_fragment_from_content(cls, *, block: Mapping[str, object]) -> ToolCallChunk | None:
        """Convert one local tool content block into a ``ToolCallChunk``.

        Ordinary blocks use ``_TOOL_CALL_CONTENT_FIELD_KEYS``. A ``tool_use``
        block's ``input`` is ``{}`` as a placeholder before ``input_json_delta``
        fragments arrive, so ``{}`` becomes ``""`` and other input is serialized
        once. Server-tool and unknown block types return ``None``. The slot comes
        only from the block's integer ``index`` (0 is preserved), never from its
        list position.

        Args:
            block (Mapping[str, object]): One provider content block.

        Returns:
            ToolCallChunk | None: The fragment, or ``None`` for non-local-tool blocks.
        """
        block_type: object = block.get("type")
        tool_name: str | None = cls._non_empty_text(value=block.get("name"))
        slot: int | None = cls._content_block_slot(block=block)
        if block_type == "tool_use":
            tool_input: object = block.get("input")
            return tool_call_chunk(
                name=tool_name,
                args="" if tool_input == {} else cls._stringify_tool_arguments(arguments=tool_input),
                id=cls._non_empty_text(value=block.get("id")),
                index=slot,
            )
        field_keys: tuple[str | None, str] | None = cls._TOOL_CALL_CONTENT_FIELD_KEYS.get(str(block_type))
        if field_keys is None:
            return None
        id_key, args_key = field_keys
        args: object = block.get(args_key)
        return tool_call_chunk(
            name=tool_name,
            args=args if isinstance(args, str) else "",
            id=None if id_key is None else cls._non_empty_text(value=block.get(id_key)),
            index=slot,
        )

    def _resolve_tool_call_id(self, *, fragment: ToolCallChunk) -> str | None:
        """Route one fragment to its call id, updating the slot mapping.

        A fragment with an id uses it, and its integer slot (if any) is mapped to
        that id; a new id at a used slot replaces the mapping. An id-less fragment
        uses the id most recently opened at its slot. Anything else is unroutable:
        no id is invented.

        Args:
            fragment (ToolCallChunk): One tool-call fragment.

        Returns:
            str | None: The call id, or ``None`` when the fragment must be dropped.
        """
        tool_call_id: str | None = fragment.get("id")
        slot: int | None = fragment.get("index")
        if tool_call_id:
            if slot is not None:
                self._tool_call_id_by_index[slot] = tool_call_id
            return tool_call_id
        if slot is None:
            return None
        return self._tool_call_id_by_index.get(slot)

    def _absorb_tool_call_fragment(self, *, fragment: ToolCallChunk) -> list[AgentStreamEventDAO]:
        """Buffer one fragment and emit its start/delta events when eligible.

        Called by ``absorb_chunk`` for every streamed fragment. Guarantees that a
        named ``tool_call_start`` precedes any delta or end for the same id:
        argument text arriving before the name is only buffered; when the first
        non-empty name arrives, the start is emitted followed by one delta
        carrying all buffered text. Later names are ignored. Terminal (closed or
        discarded) ids and unroutable fragments emit nothing. Identical argument
        pieces are never deduplicated.

        Args:
            fragment (ToolCallChunk): One tool-call fragment.

        Returns:
            list[AgentStreamEventDAO]: Zero or more ``tool_call_start``/``tool_call_delta`` events.
        """
        tool_call_id: str | None = self._resolve_tool_call_id(fragment=fragment)
        if tool_call_id is None or tool_call_id in self._closed_tool_call_ids:
            return []
        self._open_tool_call_ids.add(tool_call_id)
        slot: int | None = fragment.get("index")
        content_index: int = 0 if slot is None else slot
        arguments_delta: str = fragment.get("args") or ""
        buffered_arguments: str = self._tool_call_argument_buffers.get(tool_call_id, "") + arguments_delta
        self._tool_call_argument_buffers[tool_call_id] = buffered_arguments
        if tool_call_id in self._tool_call_names:
            return self._build_tool_call_deltas(
                tool_call_id=tool_call_id,
                arguments_delta=arguments_delta,
                content_index=content_index,
            )
        tool_name: str | None = fragment.get("name")
        if not tool_name:
            return []
        self._tool_call_names[tool_call_id] = tool_name
        return [
            self._build_tool_call_start(
                tool_call_id=tool_call_id, tool_name=tool_name, content_index=content_index
            ),
            *self._build_tool_call_deltas(
                tool_call_id=tool_call_id,
                arguments_delta=buffered_arguments,
                content_index=content_index,
            ),
        ]

    def _build_tool_call_deltas(
        self,
        *,
        tool_call_id: str,
        arguments_delta: str,
        content_index: int,
    ) -> list[AgentStreamEventDAO]:
        """Build the ``tool_call_delta`` for a named call, or nothing for empty text.

        Args:
            tool_call_id (str): Call id whose named start was already emitted.
            arguments_delta (str): Argument text to publish.
            content_index (int): Provider slot, or ``0`` when unknown.

        Returns:
            list[AgentStreamEventDAO]: One delta event, or an empty list.
        """
        if not arguments_delta:
            return []
        return [
            AgentStreamEventDAO(
                kind="tool_call_delta",
                iteration=self._iteration,
                block_id=tool_call_id,
                content_index=content_index,
                tool_call_id=tool_call_id,
                tool_name=self._tool_call_names[tool_call_id],
                tool_arguments_delta=arguments_delta,
            )
        ]

    def _emit_thinking_delta(
        self,
        *,
        block_id: str,
        content_index: int,
        text: str,
    ) -> list[AgentStreamEventDAO]:
        """Open the thinking block if needed, then emit its delta.

        Args:
            block_id (str): Stable thinking block id.
            content_index (int): Provider content index.
            text (str): Visible thinking text.

        Returns:
            list[AgentStreamEventDAO]: Start + delta events as needed.
        """
        if not text:
            return []
        events: list[AgentStreamEventDAO] = []
        if self._open_text_block_id is not None:
            events.append(
                AgentStreamEventDAO(
                    kind="text_end",
                    iteration=self._iteration,
                    block_id=self._open_text_block_id,
                )
            )
            self._open_text_block_id = None
        if self._open_thinking_block_id != block_id:
            if self._open_thinking_block_id is not None:
                events.append(
                    AgentStreamEventDAO(
                        kind="thinking_end",
                        iteration=self._iteration,
                        block_id=self._open_thinking_block_id,
                    )
                )
            self._open_thinking_block_id = block_id
            events.append(
                AgentStreamEventDAO(
                    kind="thinking_start",
                    iteration=self._iteration,
                    block_id=block_id,
                    content_index=content_index,
                )
            )
        events.append(
            AgentStreamEventDAO(
                kind="thinking_delta",
                iteration=self._iteration,
                block_id=block_id,
                content_index=content_index,
                delta=text,
            )
        )
        return events

    def _emit_text_delta(
        self,
        *,
        block_id: str,
        content_index: int,
        text: str,
    ) -> list[AgentStreamEventDAO]:
        """Open the text block if needed, then emit its delta.

        Args:
            block_id (str): Stable text block id.
            content_index (int): Provider content index.
            text (str): Visible answer text.

        Returns:
            list[AgentStreamEventDAO]: Start + delta events as needed.
        """
        if not text:
            return []
        events: list[AgentStreamEventDAO] = []
        if self._open_thinking_block_id is not None:
            self._implicitly_closed_thinking_block_id = self._open_thinking_block_id
            events.append(
                AgentStreamEventDAO(
                    kind="thinking_end",
                    iteration=self._iteration,
                    block_id=self._open_thinking_block_id,
                )
            )
            self._open_thinking_block_id = None
        if self._open_text_block_id != block_id:
            if self._open_text_block_id is not None:
                events.append(
                    AgentStreamEventDAO(
                        kind="text_end",
                        iteration=self._iteration,
                        block_id=self._open_text_block_id,
                    )
                )
            self._open_text_block_id = block_id
            events.append(
                AgentStreamEventDAO(
                    kind="text_start",
                    iteration=self._iteration,
                    block_id=block_id,
                    content_index=content_index,
                )
            )
        events.append(
            AgentStreamEventDAO(
                kind="text_delta",
                iteration=self._iteration,
                block_id=block_id,
                content_index=content_index,
                delta=text,
            )
        )
        return events

    @staticmethod
    def _visible_reasoning_text(*, block: dict[str, Any]) -> Optional[str]:
        """Extract visible reasoning summary text from one provider block.

        Args:
            block (dict[str, Any]): Provider content block.

        Returns:
            Optional[str]: Visible summary text when present.
        """
        summary = block.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        if isinstance(summary, list):
            pieces: list[str] = []
            for item in summary:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    text: str = item["text"]
                    pieces.append(text)
            # Streaming fragments are substrings, not completed summary paragraphs.
            # Trimming or adding separators here destroys token and code boundaries.
            joined: str = "".join(pieces)
            if joined:
                return joined
        for key in ("text", "content", "thinking"):
            value = block.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _visible_text_text(*, block: dict[str, Any]) -> Optional[str]:
        """Extract visible assistant answer text from one provider block.

        Args:
            block (dict[str, Any]): Provider content block.

        Returns:
            Optional[str]: Visible answer text when present.
        """
        for key in ("text", "content"):
            value = block.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _is_reasoning_redacted(*, block: dict[str, Any]) -> bool:
        """Return True when the provider block is reasoning but not visible.

        Args:
            block (dict[str, Any]): Provider content block.

        Returns:
            bool: True when the block carries encrypted/redacted-only payload.
        """
        return bool(block.get("encrypted_content") or block.get("redacted") or block.get("signature"))

    @staticmethod
    def _non_empty_text(*, value: object) -> str | None:
        """Narrow a heterogeneous content value to a non-empty string.

        Args:
            value (object): Raw provider value.

        Returns:
            str | None: The string, or ``None`` when absent, empty or not a string.
        """
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def _content_block_slot(*, block: Mapping[str, object]) -> int | None:
        """Read a content block's integer slot, preserving slot 0.

        Args:
            block (Mapping[str, object]): Provider content block.

        Returns:
            int | None: The ``index`` value, or ``None`` when absent or not an integer.
        """
        slot: object = block.get("index")
        if isinstance(slot, int) and not isinstance(slot, bool):
            return slot
        return None

    @staticmethod
    def _stringify_tool_arguments(*, arguments: object) -> str:
        """Serialize full tool arguments into one JSON fragment.

        Args:
            arguments (object): Provider or LangChain tool-args payload.

        Returns:
            str: JSON string or best-effort string form.
        """
        if arguments is None:
            return ""
        if isinstance(arguments, str):
            return arguments
        try:
            return json.dumps(arguments, sort_keys=True)
        except TypeError:
            return str(arguments)

    @staticmethod
    def _completed_tool_calls_by_id(*, message: AIMessage) -> dict[str, ToolCall]:
        """Index a completed message's tool calls by id, in message order.

        Args:
            message (AIMessage): Completed assistant message.

        Returns:
            dict[str, ToolCall]: Tool calls with a non-empty id, keyed by that id.
        """
        completed_tool_calls_by_id: dict[str, ToolCall] = {}
        for tool_call in message.tool_calls:
            tool_call_id: str | None = tool_call.get("id")
            if tool_call_id:
                completed_tool_calls_by_id[tool_call_id] = tool_call
        return completed_tool_calls_by_id

    def _resolved_tool_name(
        self,
        *,
        tool_call_id: str,
        completed_tool_call: ToolCall | None,
    ) -> str | None:
        """Resolve the final name: the completed call's name, else the streamed name.

        Args:
            tool_call_id (str): Call id.
            completed_tool_call (ToolCall | None): Completed call, when present.

        Returns:
            str | None: Non-empty tool name, or ``None`` when no name ever arrived.
        """
        completed_name: str | None = None if completed_tool_call is None else completed_tool_call.get("name")
        if completed_name:
            return completed_name
        return self._tool_call_names.get(tool_call_id)

    def _resolved_tool_input(
        self,
        *,
        tool_call_id: str,
        completed_tool_call: ToolCall | None,
    ) -> dict[str, object]:
        """Resolve the final arguments: completed args, else parsed buffered text.

        An explicit completed ``{}`` outranks buffered argument text.

        Args:
            tool_call_id (str): Call id.
            completed_tool_call (ToolCall | None): Completed call, when present.

        Returns:
            dict[str, object]: Final arguments; ``{}`` when unparseable or absent.
        """
        completed_args: object = None if completed_tool_call is None else completed_tool_call.get("args")
        if isinstance(completed_args, dict):
            return dict(completed_args)
        buffered_args: str = self._tool_call_argument_buffers.get(tool_call_id, "")
        return self._best_effort_parse_tool_arguments(arguments=buffered_args)

    @staticmethod
    def _best_effort_parse_tool_arguments(*, arguments: str) -> dict[str, Any]:
        """Parse finalized streamed tool arguments when possible.

        Args:
            arguments (str): Final accumulated JSON/text payload.

        Returns:
            dict[str, Any]: Parsed arguments, or ``{}`` when parsing fails.
        """
        if not arguments:
            return {}
        try:
            parsed: object = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
        return {}
