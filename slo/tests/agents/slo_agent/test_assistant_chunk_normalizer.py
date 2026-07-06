"""Tests for ``AssistantChunkNormalizer``."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from src.agents.slo_agent.assistant_chunk_normalizer import AssistantChunkNormalizer


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

        The repair event lets TranscriptProjector replace the malformed
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
