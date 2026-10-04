"""Shared assistant-message text normalization helpers."""

from __future__ import annotations

import re
from typing import Any, Optional

from langchain_core.messages import AIMessage

from src.agents.providers.message_extension import (
    PROVIDER_MESSAGE_EXTENSION_KEY,
    ProviderMessageExtensionDAO,
)

__all__ = ["assistant_message_reasoning_text", "assistant_message_text"]


def assistant_message_text(*, message: AIMessage) -> str:
    """Return the human-readable text body for an assistant message.

    The ChatGPT-backed OpenAI Responses lane can surface assistant
    content as a structured list of content blocks rather than a bare
    string. ``AIMessage.text()`` normalises both shapes to the visible
    text users expect, avoiding ``str([...])`` JSON-ish transcript and
    history output.

    Args:
        message (AIMessage): The assistant message to normalise.

    Returns:
        str: Plain assistant text suitable for transcript/history use.
    """
    return message.text()


def assistant_message_reasoning_text(*, message: AIMessage) -> str:
    """Return the visible reasoning summary text for an assistant message.

    Completed provider messages can carry reasoning/thinking content as
    structured blocks. Slo's live TUI should prefer this completed text
    over raw streamed deltas so spacing, paragraph breaks, and summary
    boundaries match the provider's final view.

    Args:
        message (AIMessage): The assistant message to inspect.

    Returns:
        str: Visible reasoning summary text, or ``""`` when the message
            carries no visible reasoning blocks.
    """
    extension_text: str = _provider_extension_reasoning_text(message=message)
    if extension_text:
        return extension_text
    if not isinstance(message.content, list):
        return ""

    visible_blocks: list[str] = []
    for block in message.content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type", "")) not in {"reasoning", "thinking"}:
            continue
        visible_text: Optional[str] = _visible_reasoning_text(block=block)
        if visible_text:
            visible_blocks.append(visible_text.strip())

    return "\n\n".join(block for block in visible_blocks if block).strip()


def _provider_extension_reasoning_text(*, message: AIMessage) -> str:
    """Return plaintext reasoning or summaries from private provider metadata only.

    Args:
        message (AIMessage): Assistant message carrying optional replay metadata.

    Returns:
        str: Plaintext reasoning and summary fragments safe for the existing thinking normalizer.
    """
    try:
        extension: ProviderMessageExtensionDAO = ProviderMessageExtensionDAO.model_validate(
            message.additional_kwargs.get(PROVIDER_MESSAGE_EXTENSION_KEY)
        )
    except ValueError:
        return ""
    visible_parts: list[str] = []
    if extension.reasoning:
        visible_parts.append(extension.reasoning)
    for detail in extension.reasoning_details:
        if not isinstance(detail, dict):
            continue
        summary: object | None = detail.get("summary")
        if isinstance(summary, str) and summary.strip():
            visible_parts.append(summary)
    return "\n\n".join(part.strip() for part in visible_parts if part.strip())


def _visible_reasoning_text(*, block: dict[str, Any]) -> Optional[str]:
    """Extract visible reasoning text from one provider content block.

    Args:
        block (dict[str, Any]): Provider reasoning/thinking block.

    Returns:
        Optional[str]: Visible reasoning text when present.
    """
    summary: object = block.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary
    if isinstance(summary, list):
        pieces: list[str] = []
        for item in summary:
            if not isinstance(item, dict):
                continue
            text: object = item.get("text")
            if isinstance(text, str) and text.strip():
                pieces.append(text)
        joined: str = _join_visible_text_fragments(pieces=pieces)
        if joined:
            return joined

    for key in ("thinking", "text", "content"):
        value: object = block.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _join_visible_text_fragments(*, pieces: list[str]) -> str:
    """Join visible text fragments into readable prose.

    Provider reasoning summaries sometimes arrive as fragment lists whose
    boundaries do not preserve spaces. Joining with a literal empty string can
    collapse whole sentences into unreadable word soup, while joining with a
    blind space can introduce stray spaces before punctuation.

    Args:
        pieces (list[str]): Non-empty visible text fragments.

    Returns:
        str: Readable joined text with punctuation spacing normalized.
    """
    cleaned_pieces: list[str] = [piece.strip() for piece in pieces if piece.strip()]
    if not cleaned_pieces:
        return ""
    joined: str = " ".join(cleaned_pieces)
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
    joined = re.sub(r"([\(\[\{])\s+", r"\1", joined)
    joined = re.sub(r"\s+([\)\]\}])", r"\1", joined)
    return joined.strip()
