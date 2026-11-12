"""Tests for ``AssistantChunkNormalizer``."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.agents.slo_agent.assistant_chunk_normalizer import AssistantChunkNormalizer
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


class TestAssistantChunkNormalizer:
    """Chunk normalization branches and block-finalization behavior."""

    def test_openai_reasoning_summary_chunk_becomes_thinking_events(self) -> None:
        """Visible OpenAI reasoning summary text emits thinking start+delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [{"text": "Comparing likely root causes."}],
                }
            ]
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["thinking_start", "thinking_delta"]
        assert events[1].delta == "Comparing likely root causes."

    def test_openai_reasoning_summary_chunk_preserves_fragment_spacing(self) -> None:
        """Streamed reasoning fragments keep provider-emitted spaces intact."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "summary": [
                        {"text": "I"},
                        {"text": " need"},
                        {"text": " to"},
                        {"text": " explain"},
                    ],
                }
            ]
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["thinking_start", "thinking_delta"]
        assert events[1].delta == "I need to explain"

    def test_anthropic_thinking_chunk_becomes_thinking_events(self) -> None:
        """Visible Anthropic thinking text emits thinking start+delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[
                {
                    "type": "thinking",
                    "thinking": "I should inspect the failing branch.",
                }
            ]
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["thinking_start", "thinking_delta"]
        assert events[1].delta == "I should inspect the failing branch."

    def test_plain_string_chunk_becomes_text_events(self) -> None:
        """Plain string content emits text start+delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        events = normalizer.absorb_chunk(chunk=AIMessageChunk(content="hello"))

        assert [event.kind for event in events] == ["text_start", "text_delta"]
        assert events[1].delta == "hello"

    def test_streamed_tool_call_fragment_from_content_block_becomes_tool_call_events(self) -> None:
        """Tool-call content blocks emit tool-call start+delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "read",
                    "input": {"path": "README.md"},
                }
            ]
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["tool_call_start", "tool_call_delta"]
        assert events[0].tool_name == "read"
        assert events[1].tool_arguments_delta == '{"path": "README.md"}'

    def test_streamed_tool_call_fragment_from_chunk_attributes_becomes_tool_call_events(self) -> None:
        """Chunk tool-call attributes emit tool-call start+delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[],
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "read",
                    "args": {"path": "README.md"},
                }
            ],
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["tool_call_start", "tool_call_delta"]
        assert events[1].tool_arguments_delta == '{"path": "README.md"}'

    def test_redacted_reasoning_without_visible_text_never_emits_thinking_delta(self) -> None:
        """Encrypted-only reasoning emits no fake visible thinking delta."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        chunk: AIMessageChunk = AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "encrypted_content": "opaque",
                }
            ]
        )

        events = normalizer.absorb_chunk(chunk=chunk)

        assert [event.kind for event in events] == ["thinking_start", "thinking_end"]
        assert events[0].redacted is True
        assert events[1].redacted is True

    def test_text_after_thinking_closes_thinking_block_before_text_start(self) -> None:
        """Visible answer text closes the active thinking block first."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "thinking", "thinking": "plan"}],
            )
        )

        events = normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "answer"}],
            )
        )

        assert [event.kind for event in events] == ["thinking_end", "text_start", "text_delta"]

    def test_new_text_block_closes_previous_text_block(self) -> None:
        """A second text block closes the first one before opening the next."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "hello"}],
            )
        )

        events = normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "world"}, {"type": "text", "text": "!"}],
            )
        )

        assert events[0].kind == "text_delta"
        assert [event.kind for event in events[1:]] == ["text_end", "text_start", "text_delta"]

    def test_finalize_open_blocks_emits_closing_events(self) -> None:
        """Open thinking, text, and tool-call blocks emit end events on finalize."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "thinking", "thinking": "reason"}],
            )
        )
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "tool_use", "id": "call_1", "name": "read", "input": {"path": "x"}}],
            )
        )

        events = normalizer.finalize_open_blocks()

        assert [event.kind for event in events] == ["thinking_end", "tool_call_end"]
        assert events[1].tool_call_id == "call_1"

    def test_finalize_open_blocks_prefers_completed_reasoning_and_tool_input(self) -> None:
        """Completed assistant truth is threaded into closing thinking/tool-call events."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[
                    {"type": "reasoning", "summary": [{"text": "Ineed"}]},
                    {"type": "tool_use", "id": "call_1", "name": "read", "input": {"path": "x"}},
                ],
            )
        )

        completed_message: AIMessage = AIMessage(
            content=[
                {
                    "type": "reasoning",
                    "summary": [{"text": "I need spacing."}],
                }
            ],
            tool_calls=[{"id": "call_1", "name": "read", "args": {"path": "README.md"}}],
        )

        events = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        assert events[0].kind == "thinking_end"
        assert events[0].content == "I need spacing."
        assert events[1].kind == "tool_call_end"
        assert events[1].tool_input == {"path": "README.md"}

    def test_emit_text_delta_saves_implicitly_closed_thinking_block_id_when_thinking_was_open(
        self,
    ) -> None:
        """_emit_text_delta saves the open thinking block id before clearing it.

        When answer text arrives while a thinking block is still open,
        the block id must be preserved so finalize_open_blocks can emit
        a repair thinking_end with the completed reasoning text.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "thinking", "thinking": "reasoning text"}],
            )
        )
        assert normalizer._open_thinking_block_id == "thinking:0:0"
        assert normalizer._implicitly_closed_thinking_block_id is None

        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "answer"}],
            )
        )

        assert normalizer._open_thinking_block_id is None
        assert normalizer._implicitly_closed_thinking_block_id == "thinking:0:0"

    def test_finalize_open_blocks_emits_repair_thinking_end_for_implicitly_closed_block(
        self,
    ) -> None:
        """finalize_open_blocks emits a content-carrying thinking_end for the implicitly closed block.

        The repair event lets TranscriptProjectionAdapter replace the malformed
        concatenated thinking text with the provider's final formatted text.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "thinking", "thinking": "Icanoutlinekeypoints."}],
            )
        )
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "answer"}],
            )
        )

        completed_message: AIMessage = AIMessage(
            content=[
                {
                    "type": "thinking",
                    "thinking": "I can outline key points.",
                }
            ]
        )

        events = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        repair_events = [event for event in events if event.kind == "thinking_end"]
        assert len(repair_events) == 1
        repair_event = repair_events[0]
        assert repair_event.block_id == "thinking:0:0"
        assert repair_event.content == "I can outline key points."
        assert normalizer._implicitly_closed_thinking_block_id is None

    def test_finalize_open_blocks_emits_no_repair_when_reasoning_text_is_empty(
        self,
    ) -> None:
        """finalize_open_blocks emits no repair thinking_end when reasoning text is absent.

        When the completed AIMessage carries no reasoning content (e.g. a
        plain-string message), no spurious repair event should be emitted.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "thinking", "thinking": "some reasoning"}],
            )
        )
        normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[{"type": "text", "text": "answer"}],
            )
        )

        completed_message: AIMessage = AIMessage(content="plain answer text")

        events = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        repair_events = [event for event in events if event.kind == "thinking_end"]
        assert len(repair_events) == 0


TOOL_EVENT_KINDS: frozenset[str] = frozenset({"tool_call_start", "tool_call_delta", "tool_call_end"})


def tool_events(*, stream_events: list[AgentStreamEventDAO]) -> list[AgentStreamEventDAO]:
    """Keep only tool-call request events, in stream order.

    Args:
        stream_events (list[AgentStreamEventDAO]): Normalizer output.

    Returns:
        list[AgentStreamEventDAO]: ``tool_call_start``/``delta``/``end`` events.
    """
    return [stream_event for stream_event in stream_events if stream_event.kind in TOOL_EVENT_KINDS]


def tool_event_summaries(
    *, stream_events: list[AgentStreamEventDAO]
) -> list[tuple[str, str | None, str | None]]:
    """Summarize tool events as ``(kind, tool_call_id, tool_name)`` tuples.

    Args:
        stream_events (list[AgentStreamEventDAO]): Normalizer output.

    Returns:
        list[tuple[str, str | None, str | None]]: One tuple per tool event.
    """
    return [
        (stream_event.kind, stream_event.tool_call_id, stream_event.tool_name)
        for stream_event in tool_events(stream_events=stream_events)
    ]


def absorb_chunks(
    *, normalizer: AssistantChunkNormalizer, chunks: list[AIMessageChunk]
) -> list[AgentStreamEventDAO]:
    """Feed chunks in order and collect every emitted event.

    Args:
        normalizer (AssistantChunkNormalizer): Normalizer under test.
        chunks (list[AIMessageChunk]): Provider chunks in stream order.

    Returns:
        list[AgentStreamEventDAO]: Events emitted by all chunks, in order.
    """
    stream_events: list[AgentStreamEventDAO] = []
    for chunk in chunks:
        stream_events.extend(normalizer.absorb_chunk(chunk=chunk))
    return stream_events


def tool_call_chunk_message(
    *, tool_call_id: str | None, tool_name: str | None, args: str, index: int | None
) -> AIMessageChunk:
    """Build a Chat Completions style chunk carrying one ``tool_call_chunks`` fragment.

    Args:
        tool_call_id (str | None): Provider call id, absent on follow-ups.
        tool_name (str | None): Tool name, usually only on the opening fragment.
        args (str): Argument text fragment.
        index (int | None): Call slot inside the assistant message.

    Returns:
        AIMessageChunk: Chunk with tool data only in ``tool_call_chunks``.
    """
    return AIMessageChunk(
        content="",
        tool_call_chunks=[{"id": tool_call_id, "name": tool_name, "args": args, "index": index}],
    )


class TestAssistantChunkNormalizerCloseOnce:
    """Change 1: every call id closes exactly once per normalizer lifetime."""

    def test_emits_no_tool_events_when_call_is_finalized_twice(self) -> None:
        """A2: the second ``finalize_open_blocks`` with the same message emits no tool events."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"path": "a.py"}', index=0),
            ],
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {"path": "a.py"}}],
        )

        first_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )
        second_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        assert tool_event_summaries(stream_events=first_events) == [("tool_call_end", "call_a", "read")]
        assert first_events[0].tool_input == {"path": "a.py"}
        assert second_events == []

    def test_emits_one_start_and_end_when_completed_only_call_is_finalized_twice(self) -> None:
        """A2/A8: a call never streamed gets one named start and one end across both finalizations."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {"path": "a.py"}}],
        )

        first_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )
        second_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        assert tool_event_summaries(stream_events=first_events) == [
            ("tool_call_start", "call_a", "read"),
            ("tool_call_end", "call_a", "read"),
        ]
        assert second_events == []

    def test_emits_start_and_end_once_with_empty_input_when_call_has_no_args(self) -> None:
        """A9: a call without arguments starts and ends once with ``tool_input == {}``."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        streamed_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[tool_call_chunk_message(tool_call_id="call_now", tool_name="now", args="", index=0)],
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_now", "name": "now", "args": {}}],
        )

        closing_events: list[AgentStreamEventDAO] = [
            *normalizer.finalize_open_blocks(completed_assistant_message=completed_message),
            *normalizer.finalize_open_blocks(completed_assistant_message=completed_message),
        ]

        assert tool_event_summaries(stream_events=[*streamed_events, *closing_events]) == [
            ("tool_call_start", "call_now", "now"),
            ("tool_call_end", "call_now", "now"),
        ]
        assert closing_events[0].tool_input == {}

    def test_preserves_empty_input_when_completed_args_override_buffer(self) -> None:
        """An explicit completed ``{}`` outranks buffered argument text on the end event."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(
                    tool_call_id="call_a", tool_name="read", args='{"path": "x"}', index=0
                )
            ],
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {}}],
        )

        closing_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        assert tool_event_summaries(stream_events=closing_events) == [("tool_call_end", "call_a", "read")]
        assert closing_events[0].tool_input == {}

    def test_closes_open_call_from_buffer_when_completed_message_omits_it(self) -> None:
        """An open named call absent from the completed message closes once from buffered args."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(
                    tool_call_id="call_a", tool_name="read", args='{"path": "x"}', index=0
                )
            ],
        )

        closing_events: list[AgentStreamEventDAO] = [
            *normalizer.finalize_open_blocks(completed_assistant_message=AIMessage(content="")),
            *normalizer.finalize_open_blocks(completed_assistant_message=None),
        ]

        assert tool_event_summaries(stream_events=closing_events) == [("tool_call_end", "call_a", "read")]
        assert closing_events[0].tool_input == {"path": "x"}

    def test_closes_text_opened_after_completed_message_when_iteration_finalizes(self) -> None:
        """A3 safety net: iteration end still closes text opened after the completed message."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {}}],
        )
        normalizer.finalize_open_blocks(completed_assistant_message=completed_message)
        normalizer.absorb_chunk(chunk=AIMessageChunk(content="late text"))

        closing_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed_message,
        )

        assert [stream_event.kind for stream_event in closing_events] == ["text_end"]


def tool_event_deltas(
    *, stream_events: list[AgentStreamEventDAO]
) -> list[tuple[str, str | None, str | None, str | None]]:
    """Summarize tool events as ``(kind, tool_call_id, tool_name, argument delta)`` tuples.

    Args:
        stream_events (list[AgentStreamEventDAO]): Normalizer output.

    Returns:
        list[tuple[str, str | None, str | None, str | None]]: One tuple per tool event.
    """
    return [
        (
            stream_event.kind,
            stream_event.tool_call_id,
            stream_event.tool_name,
            stream_event.tool_arguments_delta,
        )
        for stream_event in tool_events(stream_events=stream_events)
    ]


def streamed_arguments_by_id(*, stream_events: list[AgentStreamEventDAO]) -> dict[str, str]:
    """Join every ``tool_call_delta`` argument piece per call id.

    Args:
        stream_events (list[AgentStreamEventDAO]): Normalizer output.

    Returns:
        dict[str, str]: Concatenated published argument text keyed by call id.
    """
    arguments_by_id: dict[str, str] = {}
    for stream_event in stream_events:
        if stream_event.kind == "tool_call_delta" and stream_event.tool_call_id is not None:
            previous_arguments: str = arguments_by_id.get(stream_event.tool_call_id, "")
            arguments_by_id[stream_event.tool_call_id] = previous_arguments + (
                stream_event.tool_arguments_delta or ""
            )
    return arguments_by_id


def has_synthetic_tool_call_id(*, stream_events: list[AgentStreamEventDAO]) -> bool:
    """Report whether any event carries an invented ``tool-call:`` id.

    Args:
        stream_events (list[AgentStreamEventDAO]): Normalizer output.

    Returns:
        bool: True when an event's call id or block id starts with ``tool-call:``.
    """
    return any(
        (stream_event.tool_call_id or "").startswith("tool-call:")
        or stream_event.block_id.startswith("tool-call:")
        for stream_event in stream_events
        if stream_event.block_id is not None
    )


CONTENT_ONLY_EQUIVALENCE_CASES: list[object] = [
    pytest.param(
        [
            AIMessageChunk(
                content=[
                    {
                        "type": "tool_call_chunk",
                        "id": "call_a",
                        "name": "read",
                        "args": '{"p": 1}',
                        "index": 0,
                    }
                ]
            )
        ],
        [tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args='{"p": 1}', index=0)],
        id="tool_call_chunk",
    ),
    pytest.param(
        [
            AIMessageChunk(
                content=[
                    {
                        "type": "function_call",
                        "call_id": "call_a",
                        "id": "fc_item",
                        "name": "read",
                        "arguments": "",
                        "index": 0,
                    }
                ]
            ),
            AIMessageChunk(content=[{"type": "function_call", "arguments": '{"p": 1}', "index": 0}]),
        ],
        [
            tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0),
            tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"p": 1}', index=0),
        ],
        id="function_call",
    ),
    pytest.param(
        [
            AIMessageChunk(
                content=[{"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}, "index": 0}]
            )
        ],
        [tool_call_chunk_message(tool_call_id="toolu_1", tool_name="read", args="", index=0)],
        id="tool_use_placeholder",
    ),
    pytest.param(
        [
            AIMessageChunk(
                content=[{"type": "tool_use", "id": "toolu_1", "name": "read", "input": {"p": 1}, "index": 0}]
            )
        ],
        [tool_call_chunk_message(tool_call_id="toolu_1", tool_name="read", args='{"p": 1}', index=0)],
        id="tool_use_input",
    ),
    pytest.param(
        [
            AIMessageChunk(
                content=[{"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}, "index": 0}]
            ),
            AIMessageChunk(content=[{"type": "input_json_delta", "partial_json": '{"p": ', "index": 0}]),
            AIMessageChunk(content=[{"type": "input_json_delta", "partial_json": "1}", "index": 0}]),
        ],
        [
            tool_call_chunk_message(tool_call_id="toolu_1", tool_name="read", args="", index=0),
            tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"p": ', index=0),
            tool_call_chunk_message(tool_call_id=None, tool_name=None, args="1}", index=0),
        ],
        id="input_json_delta",
    ),
]


class TestAssistantChunkNormalizerSlotRouting:
    """Change 2: one tool source per chunk and slot-based routing of id-less fragments."""

    def test_joins_follow_ups_to_slot_call_when_fragments_have_no_id(self) -> None:
        """A4: id-less follow-ups join the call at their slot; no ``tool-call:`` id appears."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=3)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"path"', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args=': "a.py"}', index=0),
            ],
        )
        stream_events.extend(normalizer.finalize_open_blocks())

        assert tool_event_deltas(stream_events=stream_events) == [
            ("tool_call_start", "call_a", "read", None),
            ("tool_call_delta", "call_a", "read", '{"path"'),
            ("tool_call_delta", "call_a", "read", ': "a.py"}'),
            ("tool_call_end", "call_a", "read", None),
        ]
        assert stream_events[-1].tool_input == {"path": "a.py"}
        assert has_synthetic_tool_call_id(stream_events=stream_events) is False

    def test_keeps_arguments_per_call_when_two_calls_interleave_by_slot(self) -> None:
        """A5: interleaved fragments at slots 0 and 1 each reach their own call."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0),
                tool_call_chunk_message(tool_call_id="call_b", tool_name="grep", args="", index=1),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"pa', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"pat', index=1),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='th": "a.py"}', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='tern": "x"}', index=1),
            ],
        )
        closing_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks()

        assert streamed_arguments_by_id(stream_events=stream_events) == {
            "call_a": '{"path": "a.py"}',
            "call_b": '{"pattern": "x"}',
        }
        assert [(stream_event.tool_call_id, stream_event.tool_input) for stream_event in closing_events] == [
            ("call_a", {"path": "a.py"}),
            ("call_b", {"pattern": "x"}),
        ]

    @pytest.mark.parametrize(
        "chunks",
        [
            pytest.param(
                [
                    AIMessageChunk(
                        content=[
                            {
                                "type": "function_call",
                                "call_id": "call_r1",
                                "id": "fc_1",
                                "name": "read",
                                "arguments": "",
                                "index": 0,
                            }
                        ],
                        tool_call_chunks=[{"id": "call_r1", "name": "read", "args": "", "index": 0}],
                    ),
                    AIMessageChunk(
                        content=[{"type": "function_call", "arguments": '{"path"', "index": 0}],
                        tool_call_chunks=[{"id": None, "name": None, "args": '{"path"', "index": 0}],
                    ),
                    AIMessageChunk(
                        content=[{"type": "function_call", "arguments": ': "c.py"}', "index": 0}],
                        tool_call_chunks=[{"id": None, "name": None, "args": ': "c.py"}', "index": 0}],
                    ),
                ],
                id="responses_v1",
            ),
            pytest.param(
                [
                    AIMessageChunk(
                        content=[
                            {"type": "tool_use", "id": "call_r1", "name": "read", "input": {}, "index": 0}
                        ],
                        tool_call_chunks=[{"id": "call_r1", "name": "read", "args": "", "index": 0}],
                    ),
                    AIMessageChunk(
                        content=[{"type": "input_json_delta", "partial_json": '{"path"', "index": 0}],
                        tool_call_chunks=[{"id": None, "name": None, "args": '{"path"', "index": 0}],
                    ),
                    AIMessageChunk(
                        content=[{"type": "input_json_delta", "partial_json": ': "c.py"}', "index": 0}],
                        tool_call_chunks=[{"id": None, "name": None, "args": ': "c.py"}', "index": 0}],
                    ),
                ],
                id="anthropic",
            ),
        ],
    )
    def test_publishes_arguments_once_when_both_sources_carry_the_call(
        self, *, chunks: list[AIMessageChunk]
    ) -> None:
        """A6: content blocks are ignored when ``tool_call_chunks`` carries the same call.

        Args:
            chunks (list[AIMessageChunk]): Provider fragments for the selected tool-call representation.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(normalizer=normalizer, chunks=chunks)
        stream_events.extend(normalizer.finalize_open_blocks())

        assert streamed_arguments_by_id(stream_events=stream_events) == {"call_r1": '{"path": "c.py"}'}
        assert tool_event_summaries(stream_events=stream_events) == [
            ("tool_call_start", "call_r1", "read"),
            ("tool_call_delta", "call_r1", "read"),
            ("tool_call_delta", "call_r1", "read"),
            ("tool_call_end", "call_r1", "read"),
        ]

    @pytest.mark.parametrize(
        ("content_only_chunks", "tool_call_chunk_chunks"), CONTENT_ONLY_EQUIVALENCE_CASES
    )
    def test_matches_tool_call_chunks_events_when_chunk_carries_only_content_blocks(
        self,
        *,
        content_only_chunks: list[AIMessageChunk],
        tool_call_chunk_chunks: list[AIMessageChunk],
    ) -> None:
        """A7: each §5.3 content-block row yields the same events as its ``tool_call_chunks`` form.

        Args:
            content_only_chunks (list[AIMessageChunk]): Content-only representation of the call.
            tool_call_chunk_chunks (list[AIMessageChunk]): Equivalent tool-call attribute fragments.
        """
        content_normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        tool_call_chunk_normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        content_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=content_normalizer, chunks=content_only_chunks
        )
        content_events.extend(content_normalizer.finalize_open_blocks())
        tool_call_chunk_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=tool_call_chunk_normalizer, chunks=tool_call_chunk_chunks
        )
        tool_call_chunk_events.extend(tool_call_chunk_normalizer.finalize_open_blocks())

        assert [stream_event.model_dump() for stream_event in content_events] == [
            stream_event.model_dump() for stream_event in tool_call_chunk_events
        ]
        assert tool_events(stream_events=content_events)[0].kind == "tool_call_start"
        assert tool_events(stream_events=content_events)[-1].kind == "tool_call_end"

    def test_ignores_item_id_when_function_call_block_has_call_id(self) -> None:
        """A7: a ``function_call`` block is keyed by ``call_id``, never by its output item ``id``."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(
            chunk=AIMessageChunk(
                content=[
                    {
                        "type": "function_call",
                        "call_id": "call_a",
                        "id": "fc_item",
                        "name": "read",
                        "arguments": "{}",
                        "index": 0,
                    }
                ]
            )
        )

        assert {stream_event.tool_call_id for stream_event in stream_events} == {"call_a"}

    def test_emits_named_start_before_delta_when_name_arrives_after_args(self) -> None:
        """A8: buffered args flush as one delta right after the late named start."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name=None, args='{"pa', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='th": ', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name="read", args='"a.py"}', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args="", index=0),
            ],
        )
        stream_events.extend(normalizer.finalize_open_blocks())

        assert tool_event_deltas(stream_events=stream_events) == [
            ("tool_call_start", "call_a", "read", None),
            ("tool_call_delta", "call_a", "read", '{"path": "a.py"}'),
            ("tool_call_end", "call_a", "read", None),
        ]
        assert stream_events[-1].tool_input == {"path": "a.py"}

    def test_emits_named_start_before_end_when_name_arrives_only_on_completed_message(self) -> None:
        """A8: a name known only from the completed message yields one start, then one end."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        streamed_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(
                    tool_call_id="call_a", tool_name=None, args='{"path": "a.py"}', index=0
                )
            ],
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {"path": "a.py"}}],
        )

        closing_events: list[AgentStreamEventDAO] = [
            *normalizer.finalize_open_blocks(completed_assistant_message=completed_message),
            *normalizer.finalize_open_blocks(completed_assistant_message=completed_message),
        ]

        assert streamed_events == []
        assert tool_event_summaries(stream_events=closing_events) == [
            ("tool_call_start", "call_a", "read"),
            ("tool_call_end", "call_a", "read"),
        ]

    def test_emits_one_start_when_name_repeats_on_every_fragment(self) -> None:
        """A8 supplemental: duplicate names retain the first name and open the call once."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args='{"p', index=0),
                tool_call_chunk_message(tool_call_id="call_a", tool_name="other", args='": 1}', index=0),
            ],
        )

        assert tool_event_deltas(stream_events=stream_events) == [
            ("tool_call_start", "call_a", "read", None),
            ("tool_call_delta", "call_a", "read", '{"p'),
            ("tool_call_delta", "call_a", "read", '": 1}'),
        ]

    @pytest.mark.parametrize(
        "index",
        [pytest.param(5, id="unknown_slot"), pytest.param(None, id="no_slot")],
    )
    def test_drops_fragment_when_it_has_no_id_and_no_mapped_slot(self, *, index: int | None) -> None:
        """A10: an id-less fragment whose slot maps to no call emits nothing.

        Args:
            index (int | None): Unknown or absent provider slot for the id-less fragment.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0)
        )

        stream_events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id=None, tool_name="grep", args='{"x": 1}', index=index)
        )
        closing_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks()

        assert stream_events == []
        assert tool_event_summaries(stream_events=closing_events) == [("tool_call_end", "call_a", "read")]
        assert closing_events[0].tool_input == {}

    def test_opens_separate_call_when_new_id_reuses_slot(self) -> None:
        """A11: a new id at a used slot is a separate call; follow-ups go to the newest id."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(
                    tool_call_id="call_a", tool_name="read", args='{"path": "a"}', index=0
                ),
                tool_call_chunk_message(tool_call_id="call_b", tool_name="grep", args="", index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"pattern": "b"}', index=0),
            ],
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[
                {"id": "call_a", "name": "read", "args": {"path": "a"}},
                {"id": "call_b", "name": "grep", "args": {"pattern": "b"}},
            ],
        )
        stream_events.extend(normalizer.finalize_open_blocks(completed_assistant_message=completed_message))
        stream_events.extend(normalizer.finalize_open_blocks(completed_assistant_message=completed_message))

        assert streamed_arguments_by_id(stream_events=stream_events) == {
            "call_a": '{"path": "a"}',
            "call_b": '{"pattern": "b"}',
        }
        assert [kind for kind, _, _ in tool_event_summaries(stream_events=stream_events)].count(
            "tool_call_end"
        ) == 2
        assert tool_event_summaries(stream_events=stream_events)[-2:] == [
            ("tool_call_end", "call_a", "read"),
            ("tool_call_end", "call_b", "grep"),
        ]

    @pytest.mark.parametrize(
        "chunks",
        [
            pytest.param(
                [
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name="read", args="", index=0
                    ),
                    tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"path": "k"}', index=0),
                ],
                id="kimi_opaque_id",
            ),
            pytest.param(
                [
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name="read", args="", index=0
                    ),
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name=None, args='{"path": ', index=0
                    ),
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name=None, args='"k"}', index=0
                    ),
                ],
                id="id_repeated_on_every_fragment",
            ),
            pytest.param(
                [
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name="read", args="", index=None
                    ),
                    tool_call_chunk_message(
                        tool_call_id="functions.read:0", tool_name=None, args='{"path": "k"}', index=None
                    ),
                ],
                id="id_repeated_without_slot",
            ),
        ],
    )
    def test_keeps_provider_id_exactly_when_ids_are_opaque_or_repeated(
        self, *, chunks: list[AIMessageChunk]
    ) -> None:
        """A12: Kimi-style ids and repeated ids stay exact and describe one call.

        Args:
            chunks (list[AIMessageChunk]): Provider fragments for the selected tool-call representation.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(normalizer=normalizer, chunks=chunks)
        stream_events.extend(normalizer.finalize_open_blocks())

        assert {stream_event.tool_call_id for stream_event in tool_events(stream_events=stream_events)} == {
            "functions.read:0"
        }
        assert [kind for kind, _, _ in tool_event_summaries(stream_events=stream_events)].count(
            "tool_call_start"
        ) == 1
        assert stream_events[-1].kind == "tool_call_end"
        assert stream_events[-1].tool_input == {"path": "k"}

    def test_emits_nothing_when_fragment_targets_closed_call(self) -> None:
        """A2/A8 supplemental: closed-id fragments emit nothing by id or slot."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="{}", index=0)
        )
        normalizer.finalize_open_blocks()

        late_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args='{"x": 1}', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='{"y": 2}', index=0),
            ],
        )

        assert late_events == []
        assert normalizer.finalize_open_blocks() == []

    def test_emits_nothing_when_discarded_nameless_call_later_gets_name(self) -> None:
        """A8 supplemental: a discarded nameless call stays terminal after a late named fragment."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        streamed_events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id="call_a", tool_name=None, args='{"x": 1}', index=0)
        )
        discard_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks()

        late_events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args="", index=0)
        )
        completed_message: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "call_a", "name": "read", "args": {"x": 1}}],
        )

        assert streamed_events == []
        assert discard_events == []
        assert late_events == []
        assert normalizer.finalize_open_blocks(completed_assistant_message=completed_message) == []

    def test_ends_with_empty_input_when_buffered_json_is_malformed(self) -> None:
        """A7 supplemental: malformed buffered argument JSON falls back to ``tool_input == {}``."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        normalizer.absorb_chunk(
            chunk=tool_call_chunk_message(tool_call_id="call_a", tool_name="read", args='{"pa', index=0)
        )

        closing_events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks()

        assert tool_event_summaries(stream_events=closing_events) == [("tool_call_end", "call_a", "read")]
        assert closing_events[0].tool_input == {}

    def test_emits_no_tool_events_when_chunks_carry_only_server_tool_blocks(self) -> None:
        """A7 supplemental: server-side provider tools never open a local call id."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)

        stream_events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                AIMessageChunk(
                    content=[
                        {
                            "type": "server_tool_use",
                            "id": "srvtoolu_1",
                            "name": "web_search",
                            "input": {},
                            "index": 0,
                        }
                    ]
                ),
                AIMessageChunk(
                    content=[{"type": "input_json_delta", "partial_json": '{"query": "x"}', "index": 0}]
                ),
                AIMessageChunk(
                    content=[
                        {
                            "type": "web_search_tool_result",
                            "tool_use_id": "srvtoolu_1",
                            "content": [],
                            "index": 1,
                        }
                    ]
                ),
            ],
        )
        stream_events.extend(normalizer.finalize_open_blocks())

        assert tool_events(stream_events=stream_events) == []


class TestAssistantChunkNormalizerSupplementalLifecycle:
    """EF1: public-entry proofs for the remaining A2/A7/A8 state transitions."""

    def test_retains_identical_argument_pieces_when_fragments_repeat(self) -> None:
        """A4/A7 supplemental: equal argument pieces are data, not duplicate events."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        events: list[AgentStreamEventDAO] = absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id="same", tool_name="read", args='{"s":"', index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args="ha", index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args="ha", index=0),
                tool_call_chunk_message(tool_call_id=None, tool_name=None, args='"}', index=0),
            ],
        )
        assert streamed_arguments_by_id(stream_events=events) == {"same": '{"s":"haha"}'}
        assert normalizer.finalize_open_blocks()[0].tool_input == {"s": "haha"}

    def test_closes_in_message_then_sorted_order_when_completed_and_open_calls_differ(self) -> None:
        """A2 supplemental: completed order precedes sorted remaining open ids."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        absorb_chunks(
            normalizer=normalizer,
            chunks=[
                tool_call_chunk_message(tool_call_id=call_id, tool_name="read", args="{}", index=slot)
                for slot, call_id in enumerate(["z", "b", "a", "y"])
            ],
        )
        completed: AIMessage = AIMessage(
            content="",
            tool_calls=[{"id": "y", "name": "read", "args": {}}, {"id": "b", "name": "read", "args": {}}],
        )
        events: list[AgentStreamEventDAO] = normalizer.finalize_open_blocks(
            completed_assistant_message=completed
        )
        assert [event.tool_call_id for event in events] == ["y", "b", "a", "z"]
        assert normalizer.finalize_open_blocks(completed_assistant_message=completed) == []

    @pytest.mark.parametrize(
        "slot_value",
        [
            pytest.param(None, id="A7-missing-index"),
            pytest.param("0", id="A7-string-index"),
            pytest.param(True, id="A7-bool-index"),
        ],
    )
    def test_drops_unmapped_delta_when_content_index_is_not_integer(self, *, slot_value: object) -> None:
        """A7/A10 supplemental: content list position never substitutes for a missing/invalid index.

        Args:
            slot_value (object): Missing or heterogeneous provider index.
        """
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        opening: dict[str, object] = {
            "type": "function_call",
            "call_id": "real",
            "name": "read",
            "arguments": "",
        }
        if slot_value is not None:
            opening["index"] = slot_value
        normalizer.absorb_chunk(chunk=AIMessageChunk(content=[opening]))
        events: list[AgentStreamEventDAO] = normalizer.absorb_chunk(
            chunk=AIMessageChunk(content=[{"type": "function_call", "index": 0, "arguments": '{"wrong":1}'}])
        )
        assert events == []
        assert normalizer.finalize_open_blocks()[0].tool_input == {}

    def test_discards_completed_unnamed_call_permanently_when_no_name_arrives(self) -> None:
        """A8 supplemental: an unnamed COMPLETED call is terminal, even without streamed state."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        completed: AIMessage = AIMessage(content="", tool_calls=[{"id": "unnamed", "name": "", "args": {}}])
        assert normalizer.finalize_open_blocks(completed_assistant_message=completed) == []
        assert (
            normalizer.absorb_chunk(
                chunk=tool_call_chunk_message(tool_call_id="unnamed", tool_name="read", args="{}", index=0)
            )
            == []
        )
        assert (
            normalizer.finalize_open_blocks(
                completed_assistant_message=AIMessage(
                    content="", tool_calls=[{"id": "unnamed", "name": "read", "args": {}}]
                )
            )
            == []
        )

    def test_discards_id_only_call_permanently_when_finalized_before_name(self) -> None:
        """A8 supplemental: an id-only fragment is open and becomes terminal on finalization."""
        normalizer: AssistantChunkNormalizer = AssistantChunkNormalizer(iteration=0)
        assert (
            normalizer.absorb_chunk(
                chunk=tool_call_chunk_message(tool_call_id="id-only", tool_name=None, args="", index=2)
            )
            == []
        )
        assert normalizer.finalize_open_blocks() == []
        assert (
            normalizer.absorb_chunk(
                chunk=tool_call_chunk_message(tool_call_id=None, tool_name="read", args="{}", index=2)
            )
            == []
        )
        assert normalizer.finalize_open_blocks() == []
