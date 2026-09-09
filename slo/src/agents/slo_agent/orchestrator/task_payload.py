"""Tolerant parsing of the legacy ``tasks_json`` string for ``spawn_sub_agents``.

The orchestrator LLM occasionally emits a ``tasks_json`` value that is a valid
JSON array followed by trailing content (a duplicated array, a stray token, or a
line of prose). Python's ``json.loads`` rejects the whole string with
``JSONDecodeError: Extra data`` even though the leading array is complete and
usable. This module recovers the intended task objects from that malformed input
instead of failing the batch.

It is a pure text-to-dicts layer: it knows nothing about ``SubAgentTaskDAO`` or
the pool. The caller (``spawn_tool.resolve_sub_agent_tasks``) builds DAOs from
the returned dicts, so this module stays independently testable.

Sub-spec 58.a.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["TasksJsonParseDAO", "parse_tasks_json"]


class TasksJsonParseDAO(BaseModel):
    """Outcome of tolerantly parsing a legacy ``tasks_json`` string.

    Attributes:
        task_dicts (list[dict[str, Any]]): Recovered raw task objects, in order,
            after flattening arrays and dropping non-object trailing data. Empty
            when ``error`` is set.
        recovery_notes (list[str]): Human-readable notes describing every
            tolerance applied. Empty when the input parsed cleanly.
        error (Optional[str]): Set when no task object could be recovered at all;
            ``None`` on success.
    """

    model_config = ConfigDict(extra="forbid")

    task_dicts: list[dict[str, Any]] = Field(default_factory=list)
    recovery_notes: list[str] = Field(default_factory=list)
    error: Optional[str] = None


def parse_tasks_json(*, tasks_json: str) -> TasksJsonParseDAO:
    """Recover the intended task objects from a legacy ``tasks_json`` string.

    Reads the first complete JSON value and every additional JSON value that
    directly follows it, flattens arrays into their object elements, drops any
    non-JSON trailing tail, and de-duplicates by ``task_id`` (keeping the first
    occurrence). A ``JSONDecodeError: Extra data`` shape is therefore recovered
    rather than rejected.

    Args:
        tasks_json (str): The raw string the orchestrator supplied. May be
            wrapped in a Markdown code fence, double-encoded, or trailed by junk.

    Returns:
        TasksJsonParseDAO: Recovered ``task_dicts`` plus ``recovery_notes``, or a
            populated ``error`` when nothing usable could be recovered.
    """
    text: str = _strip_json_code_fence(text=tasks_json.strip())
    if not text:
        return TasksJsonParseDAO(error=_empty_input_error())
    values, ignored_char_count = _recover_leading_json_values(text=text)
    if not values:
        return TasksJsonParseDAO(error=_undecodable_error())
    task_dicts: list[dict[str, Any]] = _flatten_task_dicts(values=values)
    if not task_dicts:
        return TasksJsonParseDAO(error=_no_task_objects_error())
    deduped, dedup_notes = _deduplicate_task_dicts(task_dicts=task_dicts)
    return TasksJsonParseDAO(
        task_dicts=deduped,
        recovery_notes=_recovery_notes(
            values=values,
            ignored_char_count=ignored_char_count,
            dedup_notes=dedup_notes,
        ),
    )


def _strip_json_code_fence(*, text: str) -> str:
    """Remove a single wrapping Markdown code fence when present.

    Args:
        text (str): Already whitespace-stripped input.

    Returns:
        str: The fence-free body, or ``text`` unchanged when no fence is present.
    """
    if not text.startswith("```"):
        return text
    without_open: str = text.split("\n", 1)[1] if "\n" in text else ""
    if without_open.rstrip().endswith("```"):
        without_open = without_open.rstrip()[:-3]
    return without_open.strip()


def _recover_leading_json_values(*, text: str) -> tuple[list[Any], int]:
    """Decode every JSON value that appears back-to-back from the start.

    Uses ``json.JSONDecoder().raw_decode`` so a complete leading value is read
    even when trailing content follows. Decoding stops at the first character
    that no longer begins a JSON value; the count of the remaining non-whitespace
    characters is returned so the caller can report how much was ignored.

    Args:
        text (str): Fence-free candidate text.

    Returns:
        tuple[list[Any], int]: The decoded values in order, and the number of
            trailing non-JSON characters that were ignored.
    """
    decoder: json.JSONDecoder = json.JSONDecoder()
    values: list[Any] = []
    index: int = 0
    length: int = len(text)
    while index < length:
        index = _skip_whitespace(text=text, index=index)
        if index >= length:
            break
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        values.append(value)
    return values, len(text[index:].strip())


def _skip_whitespace(*, text: str, index: int) -> int:
    """Return the index of the next non-whitespace character at or after ``index``.

    Args:
        text (str): The text being scanned.
        index (int): The starting index.

    Returns:
        int: The first index >= ``index`` whose character is not whitespace, or
            ``len(text)`` when only whitespace remains.
    """
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _flatten_task_dicts(*, values: list[Any]) -> list[dict[str, Any]]:
    """Flatten decoded JSON values into an ordered list of task objects.

    Args:
        values (list[Any]): Values returned by ``_recover_leading_json_values``.

    Returns:
        list[dict[str, Any]]: The task objects, in first-seen order.
    """
    task_dicts: list[dict[str, Any]] = []
    for value in values:
        task_dicts.extend(_task_dicts_from_value(value=value))
    return task_dicts


def _task_dicts_from_value(*, value: Any) -> list[dict[str, Any]]:
    """Extract zero or more task objects from one decoded JSON value.

    An object contributes itself; an array contributes its object elements; a
    string is decoded one extra level (the double-encoded case) and re-flattened;
    any other scalar contributes nothing.

    Args:
        value (Any): One decoded JSON value.

    Returns:
        list[dict[str, Any]]: Task objects contributed by this value.
    """
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        return _task_dicts_from_double_encoded_string(text=value)
    return []


def _task_dicts_from_double_encoded_string(*, text: str) -> list[dict[str, Any]]:
    """Decode a double-encoded ``tasks_json`` value one extra level.

    Args:
        text (str): A decoded value that was itself a JSON string.

    Returns:
        list[dict[str, Any]]: Task objects from the inner JSON, or empty when the
            inner content is not JSON objects.
    """
    try:
        inner: Any = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _task_dicts_from_value(value=inner)


def _deduplicate_task_dicts(
    *,
    task_dicts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop later objects that reuse an earlier ``task_id``.

    Duplicate ids would collide when the pool correlates results, so only the
    first occurrence of each id is kept. Objects without a string ``task_id`` are
    passed through untouched — 58.b's DAO construction reports that as a
    validation error.

    Args:
        task_dicts (list[dict[str, Any]]): Flattened task objects.

    Returns:
        tuple[list[dict[str, Any]], list[str]]: The de-duplicated list and one
            note per dropped duplicate.
    """
    seen_task_ids: set[str] = set()
    kept: list[dict[str, Any]] = []
    notes: list[str] = []
    for task_dict in task_dicts:
        task_id: Any = task_dict.get("task_id")
        if isinstance(task_id, str) and task_id in seen_task_ids:
            notes.append(f"dropped duplicate task_id '{task_id}'")
            continue
        if isinstance(task_id, str):
            seen_task_ids.add(task_id)
        kept.append(task_dict)
    return kept, notes


def _recovery_notes(
    *,
    values: list[Any],
    ignored_char_count: int,
    dedup_notes: list[str],
) -> list[str]:
    """Build the ordered list of tolerance notes for one recovery.

    Args:
        values (list[Any]): Decoded JSON values from the input.
        ignored_char_count (int): Trailing non-JSON characters that were dropped.
        dedup_notes (list[str]): Notes emitted while de-duplicating task ids.

    Returns:
        list[str]: Human-readable notes; empty when the input parsed cleanly.
    """
    notes: list[str] = []
    if len(values) > 1:
        notes.append(f"merged {len(values)} back-to-back JSON values")
    if ignored_char_count > 0:
        notes.append(f"ignored {ignored_char_count} trailing characters after a complete value")
    notes.extend(dedup_notes)
    return notes


def _empty_input_error() -> str:
    """Return the error for input that is empty after normalisation."""
    return "Invalid tasks_json: empty after stripping; expected a JSON array of " "task objects."


def _undecodable_error() -> str:
    """Return the error for input with no decodable leading JSON value."""
    return "Invalid tasks_json: no JSON value could be decoded; expected a JSON " "array of task objects."


def _no_task_objects_error() -> str:
    """Return the error for input that decoded but held no task objects."""
    return (
        "Invalid tasks_json: decoded JSON contained no task objects; expected a "
        "JSON array of objects with 'task_id' and 'prompt'."
    )
