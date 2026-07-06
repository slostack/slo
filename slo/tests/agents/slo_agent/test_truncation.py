"""Tests for ``src.agents.slo_agent.truncation`` (spec 02.b §8).

``was_output_truncated`` normalizes Anthropic / OpenAI-Chat / OpenAI-Responses
output-limit signals into one boolean and must never raise on odd metadata.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.slo_agent.truncation import was_output_truncated


def _message(*, metadata: Optional[dict[str, Any]]) -> AIMessage:
    """Build an ``AIMessage`` carrying the given ``response_metadata``.

    Args:
        metadata (Optional[dict[str, Any]]): The provider response metadata to
            attach (``None`` exercises the missing-metadata path).

    Returns:
        AIMessage: A message with the supplied metadata and no tool calls.
    """
    message = AIMessage(content="")
    if metadata is not None:
        message.response_metadata = metadata
    return message


def test_detects_anthropic_max_tokens() -> None:
    """Anthropic ``stop_reason == "max_tokens"`` is truncation."""
    assert was_output_truncated(message=_message(metadata={"stop_reason": "max_tokens"})) is True


def test_detects_openai_length() -> None:
    """OpenAI Chat ``finish_reason == "length"`` is truncation."""
    assert was_output_truncated(message=_message(metadata={"finish_reason": "length"})) is True


def test_detects_responses_incomplete_max_output_tokens() -> None:
    """OpenAI Responses ``status=incomplete`` + ``max_output_tokens`` is truncation."""
    metadata = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    assert was_output_truncated(message=_message(metadata=metadata)) is True


def test_normal_stop_reason_is_not_truncation() -> None:
    """Normal terminal reasons are not truncation."""
    assert was_output_truncated(message=_message(metadata={"stop_reason": "tool_use"})) is False
    assert was_output_truncated(message=_message(metadata={"stop_reason": "end_turn"})) is False
    assert was_output_truncated(message=_message(metadata={"finish_reason": "tool_calls"})) is False


def test_incomplete_with_other_reason_is_not_truncation() -> None:
    """``status=incomplete`` for a non-output-limit reason is not truncation."""
    metadata = {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}}
    assert was_output_truncated(message=_message(metadata=metadata)) is False


def test_empty_or_missing_metadata_is_false() -> None:
    """Empty or absent metadata returns ``False`` without raising."""
    assert was_output_truncated(message=_message(metadata={})) is False
    assert was_output_truncated(message=_message(metadata=None)) is False
