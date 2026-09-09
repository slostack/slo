"""Tests for ``_project_stdout_capture`` (sub-spec 54.a.4).

Covers thinking block emission, tool call/result reconstruction,
partial-stream flushing, and interleaved-event ordering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tui.workflow_visualizer_loader import _project_stdout_capture

# ── helpers ───────────────────────────────────────────────────────────────────


def _write_events(tmp_path: Path, *events: dict) -> Path:
    """Write a list of event dicts as JSONL and return the file path.

    Args:
        tmp_path (Path): Pytest temporary directory.
        *events (dict): Event dicts to serialize.

    Returns:
        Path: Path to the written stdout.jsonl file.
    """
    capture = tmp_path / "stdout.jsonl"
    lines = [json.dumps(e) for e in events]
    capture.write_text("\n".join(lines), encoding="utf-8")
    return capture


# ── tests ─────────────────────────────────────────────────────────────────────


class TestAssistantTextProjection:
    """``text_delta`` accumulation and ``run_completed`` flush."""

    def test_text_delta_flushed_on_run_completed(self, tmp_path: Path) -> None:
        """text_delta content is accumulated and emitted as an assistant entry."""
        capture = _write_events(
            tmp_path,
            {"kind": "text_delta", "delta": "Hello ", "iteration": 0},
            {"kind": "text_delta", "delta": "world", "iteration": 0},
            {"kind": "run_completed", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].kind == "assistant"
        assert entries[0].answer == "Hello world"

    def test_text_delta_flushed_at_eof_without_terminal(self, tmp_path: Path) -> None:
        """Partial stream (no run_completed) still yields assistant content."""
        capture = _write_events(
            tmp_path,
            {"kind": "text_delta", "delta": "partial", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].kind == "assistant"
        assert entries[0].answer == "partial"

    def test_text_end_also_flushes(self, tmp_path: Path) -> None:
        """``text_end`` closes the assistant buffer like ``run_completed``."""
        capture = _write_events(
            tmp_path,
            {"kind": "text_delta", "delta": "hi", "iteration": 0},
            {"kind": "text_end", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].answer == "hi"

    def test_empty_capture_returns_empty_list(self, tmp_path: Path) -> None:
        """An empty file produces an empty entries list."""
        capture = tmp_path / "stdout.jsonl"
        capture.write_text("", encoding="utf-8")
        assert _project_stdout_capture(path=capture) == []

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        """A missing capture file returns an empty list rather than raising."""
        missing = tmp_path / "stdout.jsonl"
        assert _project_stdout_capture(path=missing) == []

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        """Non-JSON lines are silently ignored; valid lines still project."""
        capture = tmp_path / "stdout.jsonl"
        capture.write_text(
            "not-json\n" + json.dumps({"kind": "text_delta", "delta": "ok", "iteration": 0}) + "\n",
            encoding="utf-8",
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].answer == "ok"


class TestThinkingBlockProjection:
    """``thinking_delta`` / ``thinking_end`` emission."""

    def test_thinking_block_emitted_on_end(self, tmp_path: Path) -> None:
        """Accumulated thinking deltas are emitted as a thinking entry on thinking_end."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_delta", "delta": "I think ", "iteration": 0},
            {"kind": "thinking_delta", "delta": "therefore", "iteration": 0},
            {"kind": "thinking_end", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].kind == "thinking"
        assert entries[0].content == "I think therefore"

    def test_thinking_block_flushed_at_eof(self, tmp_path: Path) -> None:
        """Thinking buffer is flushed at EOF even without thinking_end."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_delta", "delta": "reasoning", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].kind == "thinking"
        assert entries[0].content == "reasoning"

    def test_thinking_before_assistant_text(self, tmp_path: Path) -> None:
        """Thinking entry precedes assistant entry in document order."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_delta", "delta": "thought", "iteration": 0},
            {"kind": "thinking_end", "iteration": 0},
            {"kind": "text_delta", "delta": "answer", "iteration": 0},
            {"kind": "run_completed", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 2
        assert entries[0].kind == "thinking"
        assert entries[1].kind == "assistant"

    def test_empty_thinking_buffer_not_emitted(self, tmp_path: Path) -> None:
        """A thinking_end with no preceding deltas produces no entry."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_end", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert entries == []


class TestToolCallProjection:
    """``tool_call_start`` / ``tool_call_delta`` / ``tool_call_end`` reconstruction."""

    def test_tool_call_emitted_on_end(self, tmp_path: Path) -> None:
        """tool_call_start/delta/end produces a tool entry with parsed args."""
        capture = _write_events(
            tmp_path,
            {
                "kind": "tool_call_start",
                "block_id": "blk-1",
                "tool_name": "read_file",
                "iteration": 0,
            },
            {
                "kind": "tool_call_delta",
                "block_id": "blk-1",
                "tool_arguments_delta": '{"path":',
                "iteration": 0,
            },
            {
                "kind": "tool_call_delta",
                "block_id": "blk-1",
                "tool_arguments_delta": ' "/tmp/f"}',
                "iteration": 0,
            },
            {
                "kind": "tool_call_end",
                "block_id": "blk-1",
                "iteration": 0,
            },
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.kind == "tool"
        assert entry.tool_name == "read_file"
        assert entry.tool_input == {"path": "/tmp/f"}

    def test_tool_result_appended(self, tmp_path: Path) -> None:
        """tool_result emits a tool entry carrying the result text."""
        capture = _write_events(
            tmp_path,
            {
                "kind": "tool_call_start",
                "block_id": "blk-1",
                "tool_name": "bash",
                "iteration": 0,
            },
            {"kind": "tool_call_end", "block_id": "blk-1", "iteration": 0},
            {
                "kind": "tool_result",
                "tool_call_id": "blk-1",
                "content": "exit 0",
                "iteration": 0,
            },
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 2
        call_entry = entries[0]
        result_entry = entries[1]
        assert call_entry.kind == "tool"
        assert call_entry.tool_name == "bash"
        assert result_entry.kind == "tool"
        assert result_entry.output == "exit 0"

    def test_malformed_tool_args_fallback_to_raw(self, tmp_path: Path) -> None:
        """Non-JSON argument stream falls back to ``{"raw": ...}``."""
        capture = _write_events(
            tmp_path,
            {
                "kind": "tool_call_start",
                "block_id": "blk-1",
                "tool_name": "run",
                "iteration": 0,
            },
            {
                "kind": "tool_call_delta",
                "block_id": "blk-1",
                "tool_arguments_delta": "not-json",
                "iteration": 0,
            },
            {"kind": "tool_call_end", "block_id": "blk-1", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        assert len(entries) == 1
        assert entries[0].tool_input == {"raw": "not-json"}

    def test_tool_result_without_matching_start_is_ignored(self, tmp_path: Path) -> None:
        """tool_result with an unrecognized call id produces no entry."""
        capture = _write_events(
            tmp_path,
            {
                "kind": "tool_result",
                "tool_call_id": "unknown-id",
                "content": "orphan",
                "iteration": 0,
            },
        )
        entries = _project_stdout_capture(path=capture)
        assert entries == []

    def test_interleaved_thinking_tool_and_assistant(self, tmp_path: Path) -> None:
        """Interleaved stream produces entries in document order."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_delta", "delta": "plan", "iteration": 0},
            {"kind": "thinking_end", "iteration": 0},
            {
                "kind": "tool_call_start",
                "block_id": "b1",
                "tool_name": "edit",
                "iteration": 0,
            },
            {
                "kind": "tool_call_delta",
                "block_id": "b1",
                "tool_arguments_delta": "{}",
                "iteration": 0,
            },
            {"kind": "tool_call_end", "block_id": "b1", "iteration": 0},
            {
                "kind": "tool_result",
                "tool_call_id": "b1",
                "content": "ok",
                "iteration": 0,
            },
            {"kind": "text_delta", "delta": "done", "iteration": 0},
            {"kind": "run_completed", "iteration": 0},
        )
        entries = _project_stdout_capture(path=capture)
        kinds = [e.kind for e in entries]
        assert kinds == ["thinking", "tool", "tool", "assistant"]
