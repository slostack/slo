"""Normalize ``AIMessageChunk`` objects into Slo stream events."""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.messages import AIMessage, AIMessageChunk

from src.agents.slo_agent.message_text import (
    assistant_message_reasoning_text,
    assistant_message_text,
)
from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = ["AssistantChunkNormalizer"]


class AssistantChunkNormalizer:
    """Per-turn stateful normalizer for assistant chunks.

    One instance is created per outer-loop turn. It remembers which
    thinking/text/tool-call blocks are currently open so it can emit
    deterministic ``*_start`` and ``*_end`` events.
    """

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

    def absorb_chunk(self, *, chunk: AIMessageChunk) -> list[AgentStreamEventDAO]:
        """Normalize one assistant chunk into ordered stream events.

        Args:
            chunk (AIMessageChunk): One assistant chunk from LangChain.

        Returns:
            list[AgentStreamEventDAO]: Ordered stream events.
        """
        events: list[AgentStreamEventDAO] = []
        events.extend(self._events_from_content_blocks(content=chunk.content))
        events.extend(self._events_from_tool_call_attributes(chunk=chunk))
        return events

    def finalize_open_blocks(
        self,
        *,
        completed_assistant_message: AIMessage | None = None,
    ) -> list[AgentStreamEventDAO]:
        """Close any still-open blocks at turn completion.

        Completed assistant messages carry better final formatting than
        raw streamed deltas. When available, Slo threads that completed
        truth into the closing events so the TUI can replace partial
        spacing/paragraph artifacts with the provider's final content.

        For thinking blocks that were implicitly closed mid-turn by
        ``_emit_text_delta`` (when answer text arrived before the turn
        ended), a second repair ``thinking_end`` event is emitted
        carrying the completed reasoning text so ``TranscriptProjector``
        can replace the malformed concatenated text with the provider's
        final view.

        Args:
            completed_assistant_message (AIMessage | None): Optional
                completed assistant message from the updates channel.

        Returns:
            list[AgentStreamEventDAO]: Closing ``*_end`` events.
        """
        reasoning_text: str = ""
        answer_text: str = ""
        completed_tool_calls: dict[str, dict[str, Any]] = {}
        if completed_assistant_message is not None:
            reasoning_text = assistant_message_reasoning_text(
                message=completed_assistant_message,
            )
            answer_text = assistant_message_text(message=completed_assistant_message)
            completed_tool_calls = self._completed_tool_calls_by_id(
                message=completed_assistant_message,
            )

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
        emitted_tool_call_ids: set[str] = set()
        for tool_call_id in sorted(self._open_tool_call_ids):
            completed_tool_call: dict[str, Any] = completed_tool_calls.get(tool_call_id, {})
            tool_name: Optional[str] = self._resolved_tool_name(
                tool_call_id=tool_call_id,
                completed_tool_call=completed_tool_call,
            )
            tool_input: dict[str, Any] = self._resolved_tool_input(
                tool_call_id=tool_call_id,
                completed_tool_call=completed_tool_call,
            )
            events.append(
                AgentStreamEventDAO(
                    kind="tool_call_end",
                    iteration=self._iteration,
                    block_id=tool_call_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
            )
            emitted_tool_call_ids.add(tool_call_id)
        for tool_call_id, completed_tool_call in completed_tool_calls.items():
            if tool_call_id in emitted_tool_call_ids:
                continue
            events.append(
                AgentStreamEventDAO(
                    kind="tool_call_end",
                    iteration=self._iteration,
                    block_id=tool_call_id,
                    tool_call_id=tool_call_id,
                    tool_name=self._resolved_tool_name(
                        tool_call_id=tool_call_id,
                        completed_tool_call=completed_tool_call,
                    ),
                    tool_input=self._resolved_tool_input(
                        tool_call_id=tool_call_id,
                        completed_tool_call=completed_tool_call,
                    ),
                )
            )
        self._open_tool_call_ids.clear()
        self._tool_call_names.clear()
        self._tool_call_argument_buffers.clear()
        return events

    def _events_from_content_blocks(self, *, content: object) -> list[AgentStreamEventDAO]:
        """Normalize ``chunk.content`` into visible text events.

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
                continue
            if block_type in {"tool_call_chunk", "function_call", "tool_use"}:
                events.extend(
                    self._events_from_tool_call_block(
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

    def _events_from_tool_call_block(
        self,
        *,
        block: dict[str, Any],
        content_index: int,
    ) -> list[AgentStreamEventDAO]:
        """Emit streamed tool-call events from one content block.

        Args:
            block (dict[str, Any]): Provider content block.
            content_index (int): Block index within the chunk.

        Returns:
            list[AgentStreamEventDAO]: Zero or more tool-call events.
        """
        tool_call_id: str = str(
            block.get("call_id") or block.get("id") or f"tool-call:{self._iteration}:{content_index}"
        )
        tool_name: Optional[str] = self._tool_name_from_block(block=block)
        arguments_delta: str = self._tool_arguments_delta_from_block(block=block)
        return self._emit_tool_call_delta(
            tool_call_id=tool_call_id,
            content_index=content_index,
            tool_name=tool_name,
            arguments_delta=arguments_delta,
        )

    def _events_from_tool_call_attributes(self, *, chunk: AIMessageChunk) -> list[AgentStreamEventDAO]:
        """Fallback normalization from LangChain tool-call attributes.

        Some providers surface streamed tool-call data more reliably on
        chunk attributes than inside ``chunk.content`` blocks.

        Args:
            chunk (AIMessageChunk): Source chunk.

        Returns:
            list[AgentStreamEventDAO]: Zero or more tool-call events.
        """
        raw_tool_calls: list[dict[str, Any]] = []
        tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
        if isinstance(tool_call_chunks, list):
            raw_tool_calls.extend(item for item in tool_call_chunks if isinstance(item, dict))
        elif isinstance(chunk.tool_calls, list):
            raw_tool_calls.extend(item for item in chunk.tool_calls if isinstance(item, dict))

        events: list[AgentStreamEventDAO] = []
        for index, raw_tool_call in enumerate(raw_tool_calls):
            tool_call_id: str = str(
                raw_tool_call.get("id")
                or raw_tool_call.get("call_id")
                or f"tool-call:{self._iteration}:fallback:{index}"
            )
            tool_name: Optional[str] = str(raw_tool_call.get("name")) if raw_tool_call.get("name") else None
            arguments_delta: str = self._stringify_tool_arguments(
                arguments=raw_tool_call.get("args"),
            )
            events.extend(
                self._emit_tool_call_delta(
                    tool_call_id=tool_call_id,
                    content_index=index,
                    tool_name=tool_name,
                    arguments_delta=arguments_delta,
                )
            )
        return events

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

    def _emit_tool_call_delta(
        self,
        *,
        tool_call_id: str,
        content_index: int,
        tool_name: Optional[str],
        arguments_delta: str,
    ) -> list[AgentStreamEventDAO]:
        """Open the tool-call block if needed, then emit its delta.

        Args:
            tool_call_id (str): Stable tool call id.
            content_index (int): Provider content index.
            tool_name (Optional[str]): Tool name when known.
            arguments_delta (str): Partial JSON/text fragment.

        Returns:
            list[AgentStreamEventDAO]: Start + delta events as needed.
        """
        if not arguments_delta and not tool_name:
            return []
        if tool_name:
            self._tool_call_names[tool_call_id] = tool_name
        if arguments_delta:
            previous: str = self._tool_call_argument_buffers.get(tool_call_id, "")
            self._tool_call_argument_buffers[tool_call_id] = previous + arguments_delta

        events: list[AgentStreamEventDAO] = []
        if tool_call_id not in self._open_tool_call_ids:
            self._open_tool_call_ids.add(tool_call_id)
            events.append(
                AgentStreamEventDAO(
                    kind="tool_call_start",
                    iteration=self._iteration,
                    block_id=tool_call_id,
                    content_index=content_index,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                )
            )
        if arguments_delta:
            events.append(
                AgentStreamEventDAO(
                    kind="tool_call_delta",
                    iteration=self._iteration,
                    block_id=tool_call_id,
                    content_index=content_index,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_arguments_delta=arguments_delta,
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
    def _tool_name_from_block(*, block: dict[str, Any]) -> Optional[str]:
        """Extract the tool name from one streamed tool-call block.

        Args:
            block (dict[str, Any]): Provider content block.

        Returns:
            Optional[str]: Tool name when present.
        """
        value = block.get("name")
        if isinstance(value, str) and value:
            return value
        return None

    @classmethod
    def _tool_arguments_delta_from_block(cls, *, block: dict[str, Any]) -> str:
        """Extract one streamed tool-arguments fragment.

        Args:
            block (dict[str, Any]): Provider content block.

        Returns:
            str: Partial JSON/text fragment for tool-call arguments.
        """
        for key in ("arguments", "args_text", "partial_json"):
            value = block.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("args", "input"):
            if key in block:
                return cls._stringify_tool_arguments(arguments=block.get(key))
        return ""

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
    def _completed_tool_calls_by_id(*, message: AIMessage) -> dict[str, dict[str, Any]]:
        """Index completed tool calls by id.

        Args:
            message (AIMessage): Completed assistant message.

        Returns:
            dict[str, dict[str, Any]]: Tool-call dicts keyed by call id.
        """
        completed: dict[str, dict[str, Any]] = {}
        for tool_call in message.tool_calls:
            tool_call_id: object = tool_call.get("id")
            if isinstance(tool_call_id, str) and tool_call_id:
                completed[tool_call_id] = dict(tool_call)
        return completed

    def _resolved_tool_name(
        self,
        *,
        tool_call_id: str,
        completed_tool_call: dict[str, Any],
    ) -> Optional[str]:
        """Resolve the best visible tool name for a finalized tool call.

        Args:
            tool_call_id (str): Stable tool call id.
            completed_tool_call (dict[str, Any]): Completed tool-call dict.

        Returns:
            Optional[str]: Best available tool name.
        """
        completed_name: object = completed_tool_call.get("name")
        if isinstance(completed_name, str) and completed_name:
            return completed_name
        return self._tool_call_names.get(tool_call_id)

    def _resolved_tool_input(
        self,
        *,
        tool_call_id: str,
        completed_tool_call: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve the best visible tool args for a finalized tool call.

        Args:
            tool_call_id (str): Stable tool call id.
            completed_tool_call (dict[str, Any]): Completed tool-call dict.

        Returns:
            dict[str, Any]: Best-effort parsed tool args.
        """
        completed_args: object = completed_tool_call.get("args")
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
