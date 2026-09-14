"""Tests for the tolerant tasks_json parser (sub-spec 58.a)."""

from __future__ import annotations

import json

from src.agents.slo_agent.orchestrator.task_payload import (
    TasksJsonParseDAO,
    parse_tasks_json,
)


class TestParseTasksJsonHappyPaths:
    """Well-formed and lightly-wrapped inputs parse without notes."""

    def test_parses_a_clean_array_without_notes(self) -> None:
        """A valid JSON array yields the objects and no recovery notes."""
        raw: str = json.dumps([{"task_id": "p1", "prompt": "x"}])

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=raw)

        assert result.error is None
        assert result.task_dicts == [{"task_id": "p1", "prompt": "x"}]
        assert result.recovery_notes == []

    def test_wraps_a_single_object_into_a_one_item_list(self) -> None:
        """A lone task object becomes a one-element list."""
        result: TasksJsonParseDAO = parse_tasks_json(tasks_json='{"task_id": "only", "prompt": "do x"}')

        assert result.error is None
        assert result.task_dicts == [{"task_id": "only", "prompt": "do x"}]

    def test_strips_a_markdown_json_fence(self) -> None:
        """A ```json fenced array is unwrapped before parsing."""
        inner: str = json.dumps([{"task_id": "p1", "prompt": "x"}])

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=f"```json\n{inner}\n```")

        assert result.error is None
        assert result.task_dicts == [{"task_id": "p1", "prompt": "x"}]

    def test_decodes_a_double_encoded_string(self) -> None:
        """A JSON string whose content is a task array is decoded twice."""
        inner: str = json.dumps([{"task_id": "p1", "prompt": "x"}])

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=json.dumps(inner))

        assert result.error is None
        assert result.task_dicts == [{"task_id": "p1", "prompt": "x"}]


class TestParseTasksJsonRecovery:
    """Malformed 'Extra data' shapes are recovered rather than rejected."""

    def test_ignores_trailing_prose_after_a_complete_array(self) -> None:
        """A valid array followed by prose recovers the array and notes the drop."""
        raw: str = json.dumps([{"task_id": "p1", "prompt": "x"}]) + "  // dispatch phase 1"

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=raw)

        assert result.error is None
        assert result.task_dicts == [{"task_id": "p1", "prompt": "x"}]
        assert any("ignored" in note for note in result.recovery_notes)

    def test_merges_two_concatenated_arrays(self) -> None:
        """Back-to-back arrays are merged so no intended task is lost."""
        raw: str = json.dumps([{"task_id": "p1", "prompt": "x"}]) + json.dumps(
            [{"task_id": "p2", "prompt": "y"}]
        )

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=raw)

        assert result.error is None
        assert [t["task_id"] for t in result.task_dicts] == ["p1", "p2"]
        assert any("merged" in note for note in result.recovery_notes)

    def test_drops_a_duplicate_task_id_keeping_the_first(self) -> None:
        """A repeated task_id keeps the first occurrence and notes the drop."""
        raw: str = json.dumps(
            [
                {"task_id": "p1", "prompt": "first"},
                {"task_id": "p1", "prompt": "second"},
            ]
        )

        result: TasksJsonParseDAO = parse_tasks_json(tasks_json=raw)

        assert result.error is None
        assert result.task_dicts == [{"task_id": "p1", "prompt": "first"}]
        assert any("duplicate task_id 'p1'" in note for note in result.recovery_notes)


class TestParseTasksJsonErrors:
    """Unrecoverable inputs return a clear error and no task objects."""

    def test_errors_on_empty_input(self) -> None:
        """Whitespace-only input returns an empty-input error."""
        result: TasksJsonParseDAO = parse_tasks_json(tasks_json="   ")

        assert result.task_dicts == []
        assert result.error is not None
        assert "empty" in result.error

    def test_errors_on_non_json_garbage(self) -> None:
        """Input with no decodable JSON value returns an undecodable error."""
        result: TasksJsonParseDAO = parse_tasks_json(tasks_json="not json at all")

        assert result.task_dicts == []
        assert result.error is not None

    def test_errors_when_decoded_json_has_no_objects(self) -> None:
        """Valid JSON that contains no task objects returns a no-objects error."""
        result: TasksJsonParseDAO = parse_tasks_json(tasks_json="[1, 2, 3]")

        assert result.task_dicts == []
        assert result.error is not None
        assert "no task objects" in result.error
