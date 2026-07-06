"""Tests for ``src.agents.slo_agent.message_text`` helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from src.agents.slo_agent.message_text import assistant_message_reasoning_text


class TestAssistantMessageReasoningText:
    """Completed assistant reasoning-text normalization."""

    def test_summary_fragments_preserve_provider_spacing(self) -> None:
        """Completed reasoning summaries keep leading-space fragments intact."""
        message: AIMessage = AIMessage(
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

        assert assistant_message_reasoning_text(message=message) == "I need to explain"

    def test_summary_fragments_insert_spaces_between_unspaced_words(self) -> None:
        """Unspaced reasoning fragments are joined into readable prose."""
        message: AIMessage = AIMessage(
            content=[
                {
                    "type": "reasoning",
                    "summary": [
                        {"text": "The"},
                        {"text": "user"},
                        {"text": "wants"},
                        {"text": "clarity"},
                    ],
                }
            ]
        )

        assert assistant_message_reasoning_text(message=message) == "The user wants clarity"
