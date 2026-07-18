"""Model-specific task-prompt clause helpers."""

from __future__ import annotations

_KIMI_FOR_CODING_CLAUSE: str = (
    "When using kimi explicitly specify kimi to be \n"
    "- Be succinct and terse. \n"
    "- Never narrate and explain tool usage. \n"
    "- Be concise and succinct when explaining edits. Always 1-2 lines and never more. \n"
    "- Use bullet points as much as possible. \n"
    "- Keep final response to 200-250 words and never more. "
)
"""Exact clause appended to task prompts run with the model ``kimi-for-coding``."""


_KIMI_FOR_CODING_MODEL_NAME: str = "kimi-for-coding"
"""Canonical model name that triggers the terse-response clause."""


def append_kimi_for_coding_clause(*, prompt: str, model_name: str) -> str:
    """Append the Kimi-for-coding task clause when the model matches exactly.

    Args:
        prompt (str): Task prompt to conditionally amend.
        model_name (str): Resolved canonical model name for the task.

    Returns:
        str: ``prompt`` with the clause appended once when ``model_name`` is
            exactly ``kimi-for-coding``; otherwise the original prompt.
    """
    if model_name != _KIMI_FOR_CODING_MODEL_NAME:
        return prompt
    if _KIMI_FOR_CODING_CLAUSE in prompt:
        return prompt
    separator: str = "\n\n" if prompt and not prompt.endswith("\n") else "\n"
    return f"{prompt}{separator}{_KIMI_FOR_CODING_CLAUSE}"
