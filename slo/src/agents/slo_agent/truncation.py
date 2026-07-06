"""Cross-provider output-truncation detection for the slo agent graph (spec 02.b).

A response is "output-truncated" when the model stopped because it hit its
output-token ceiling, not because it finished its turn. Each provider signals this
differently; :func:`was_output_truncated` normalizes those signals into one boolean
so the graph's ``tool_node`` can react uniformly — a truncated tool call loses its
trailing argument to partial-JSON parsing and would otherwise surface only a
misleading schema-validation error. See
``specifications/02-output-token-limits-and-truncation/overview.md``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

__all__ = ["was_output_truncated"]


def was_output_truncated(*, message: AIMessage) -> bool:
    """Return ``True`` if ``message`` was cut off at the model's output limit.

    Recognizes every provider signal slo can receive:

    - Anthropic Messages: ``stop_reason == "max_tokens"``
    - OpenAI Chat Completions: ``finish_reason == "length"``
    - OpenAI Responses API (Codex / reasoning lanes): ``status == "incomplete"``
      with ``incomplete_details.reason == "max_output_tokens"``

    Invoked by ``tool_node`` after dispatching tool calls. Tolerant of missing or
    unexpected metadata — returns ``False`` rather than raising — because
    ``response_metadata`` shape varies across providers and SDK versions.

    Args:
        message (AIMessage): The assistant message returned by the LLM.

    Returns:
        bool: ``True`` when the response hit the output-token ceiling.
    """
    metadata: dict[str, Any] = message.response_metadata or {}

    if metadata.get("stop_reason") == "max_tokens":
        return True
    if metadata.get("finish_reason") == "length":
        return True
    if metadata.get("status") == "incomplete":
        details: Any = metadata.get("incomplete_details") or {}
        reason: Any = details.get("reason") if isinstance(details, dict) else None
        if reason == "max_output_tokens":
            return True
    return False
