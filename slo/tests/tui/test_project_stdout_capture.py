"""Tests for the loader's capture projection (sub-spec 54.a.4; feature 94 a.3).

Covers thinking block emission, tool call/result reconstruction,
partial-stream flushing, and interleaved-event ordering through the single
live-capture seam (``_CaptureView``) that replaced the separate full-file
projector and the viewer-local live accumulation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.workflow_visualizer_loader import (
    PROGRESS_MAX_PENDING_TOOLS,
    PROGRESS_MAX_TEXT_BYTES,
    PROGRESS_TEXT_CLIPPED_MARKER,
    _CaptureView,
    _PendingToolCalls,
    _public_text_bytes,
)

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
    capture.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return capture


def _project_stdout_capture(*, path: Path) -> list[TranscriptEntryDAO]:
    """Project every complete capture line through a fresh loader capture view.

    Args:
        path (Path): Capture file inside tmp_path.

    Returns:
        list[TranscriptEntryDAO]: Public entries in event order.
    """
    return list(_CaptureView(path=path).observe().entries)


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


def _append(*, path: Path, events: list[dict]) -> None:
    """Append complete JSONL events to a capture file inside tmp_path."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(event) + "\n" for event in events))


class TestCaptureViewIncremental:
    """Live accumulation moved from the external viewer into the loader seam."""

    def test_text_deltas_coalesce_across_reads(self, tmp_path: Path) -> None:
        """Deltas arriving on separate polls extend one open assistant entry."""
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        _append(path=capture, events=[{"kind": "text_delta", "delta": "hello "}])
        first = view.observe()
        _append(path=capture, events=[{"kind": "text_delta", "delta": "world"}])
        second = view.observe()

        assert [entry.answer for entry in second.entries] == ["hello world"]
        assert second.revision != first.revision
        assert second.generation == first.generation

    def test_unchanged_capture_keeps_revision(self, tmp_path: Path) -> None:
        """A poll with no new lines reports the same content revision."""
        capture = _write_events(tmp_path, {"kind": "text_delta", "delta": "a"})
        view = _CaptureView(path=capture)

        assert view.observe().revision == view.observe().revision

    def test_terminal_event_closes_block_and_is_recorded(self, tmp_path: Path) -> None:
        """A run terminal event closes the open block; later text starts a new entry."""
        capture = _write_events(
            tmp_path,
            {"kind": "text_delta", "delta": "one"},
            {"kind": "run_completed"},
            {"kind": "text_delta", "delta": "two"},
        )

        observation = _CaptureView(path=capture).observe()

        assert [entry.answer for entry in observation.entries] == ["one", "two"]
        assert observation.terminal_seen is True

    def test_interleaved_open_blocks_never_merge_kinds(self, tmp_path: Path) -> None:
        """Thinking after unclosed text starts a new thinking entry instead of extending text."""
        capture = _write_events(
            tmp_path,
            {"kind": "thinking_delta", "delta": "t1"},
            {"kind": "text_delta", "delta": "a1"},
            {"kind": "thinking_delta", "delta": "t2"},
        )

        entries = _project_stdout_capture(path=capture)

        assert [(entry.kind, entry.content or entry.answer) for entry in entries] == [
            ("thinking", "t1"),
            ("assistant", "a1"),
            ("thinking", "t2"),
        ]

    def test_private_stream_metadata_never_reaches_entries(self, tmp_path: Path) -> None:
        """Debug metadata and provider extensions on stream events are not projected."""
        capture = _write_events(
            tmp_path,
            {"kind": "text_delta", "delta": "public", "metadata": {"continuation": "PRIVATE-SENTINEL"}},
        )

        entries = _project_stdout_capture(path=capture)

        assert "PRIVATE-SENTINEL" not in "".join(entry.model_dump_json() for entry in entries)

    def test_entry_count_is_capped_with_omission(self, tmp_path: Path) -> None:
        """More than 2,000 entries keeps the latest 2,000 and records omission."""
        events = [
            event
            for index in range(2_005)
            for event in (
                {"kind": "tool_call_start", "block_id": f"b{index}", "tool_name": "t"},
                {"kind": "tool_result", "tool_call_id": f"b{index}", "content": str(index)},
            )
        ]
        capture = _write_events(tmp_path, *events)

        observation = _CaptureView(path=capture).observe()

        assert len(observation.entries) == 2_000
        assert observation.entries[-1].output == "2004"
        assert observation.omitted is True

    def test_public_text_is_capped_with_omission(self, tmp_path: Path) -> None:
        """Accumulated public text above 2 MiB drops the oldest entries and records omission."""
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        chunk: str = "x" * (1024 * 1024)
        for _ in range(3):
            _append(path=capture, events=[{"kind": "text_delta", "delta": chunk}])
            observation = view.observe()

        total = sum(len((entry.answer or "").encode()) for entry in observation.entries)
        assert total <= 2 * 1024 * 1024
        assert total > 0
        assert observation.omitted is True

    def test_replacement_resets_entries_and_generation(self, tmp_path: Path) -> None:
        """A replaced capture never replays old entries into the new file."""
        capture = _write_events(tmp_path, {"kind": "text_delta", "delta": "old"})
        view = _CaptureView(path=capture)
        before = view.observe()
        replacement = tmp_path / "replacement.jsonl"
        replacement.write_text(json.dumps({"kind": "text_delta", "delta": "new"}) + "\n", encoding="utf-8")
        replacement.replace(capture)

        after = view.observe()

        assert [entry.answer for entry in after.entries] == ["new"]
        assert after.generation != before.generation
        assert after.reset is True

    def test_missing_capture_is_unavailable(self, tmp_path: Path) -> None:
        """No capture file yields an unavailable observation, not empty completeness."""
        observation = _CaptureView(path=tmp_path / "stdout.jsonl").observe()

        assert observation.available is False
        assert observation.entries == ()


def _tool_start(*, block_id: str, tool_name: str = "write") -> dict:
    """Build one tool-call start event."""
    return {"kind": "tool_call_start", "block_id": block_id, "tool_name": tool_name}


def _tool_delta(*, block_id: str, delta: str) -> dict:
    """Build one tool-arguments delta event."""
    return {"kind": "tool_call_delta", "block_id": block_id, "tool_arguments_delta": delta}


class TestCaptureViewToolBounds:
    """Streamed tool calls stay inside the 2 MiB public-text and pending-buffer bounds."""

    def test_streamed_tool_arguments_above_budget_are_capped(self, tmp_path: Path) -> None:
        """Three 1 MiB argument deltas yield one entry within 2 MiB, marked and omitted."""
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        _append(path=capture, events=[_tool_start(block_id="b")])
        view.observe()
        for _ in range(3):
            _append(path=capture, events=[_tool_delta(block_id="b", delta="x" * (1024 * 1024))])
            view.observe()
        _append(path=capture, events=[{"kind": "tool_call_end", "block_id": "b"}])

        observation = view.observe()

        assert len(observation.entries) == 1
        entry = observation.entries[0]
        assert sum(_public_text_bytes(entry=item) for item in observation.entries) <= PROGRESS_MAX_TEXT_BYTES
        assert entry.tool_name == "write"
        assert entry.tool_input is not None
        raw = str(entry.tool_input["raw"])
        assert raw.startswith("x" * 1024)
        assert raw.endswith(PROGRESS_TEXT_CLIPPED_MARKER)
        assert observation.omitted is True

    def test_non_ascii_tool_arguments_are_clipped_within_budget(self, tmp_path: Path) -> None:
        """Escape-expanding arguments are clipped so the lone entry still fits the budget."""
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        _append(path=capture, events=[_tool_start(block_id="b")])
        view.observe()
        for _ in range(4):
            _append(path=capture, events=[_tool_delta(block_id="b", delta="\u00e9" * 300_000)])
            view.observe()
        _append(path=capture, events=[{"kind": "tool_call_end", "block_id": "b"}])

        observation = view.observe()

        assert len(observation.entries) == 1
        assert _public_text_bytes(entry=observation.entries[0]) <= PROGRESS_MAX_TEXT_BYTES
        assert observation.omitted is True

    def test_small_tool_arguments_are_not_marked(self, tmp_path: Path) -> None:
        """Arguments within budget are parsed as before and record no omission."""
        capture = _write_events(
            tmp_path,
            _tool_start(block_id="b"),
            _tool_delta(block_id="b", delta=json.dumps({"path": "/tmp/f"})),
            {"kind": "tool_call_end", "block_id": "b"},
        )

        observation = _CaptureView(path=capture).observe()

        assert [entry.tool_input for entry in observation.entries] == [{"path": "/tmp/f"}]
        assert observation.omitted is False

    def test_unclosed_tool_starts_keep_a_bounded_buffer_count(self, tmp_path: Path) -> None:
        """A flood of unclosed starts retains only the newest pending calls and records omission."""
        flood: int = PROGRESS_MAX_PENDING_TOOLS + 500
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        _append(path=capture, events=[_tool_start(block_id=f"b{index}") for index in range(flood)])
        view.observe()
        _append(
            path=capture,
            events=[
                {"kind": "tool_result", "tool_call_id": f"b{index}", "content": str(index)}
                for index in range(flood)
            ],
        )

        observation = view.observe()

        outputs = [entry.output for entry in observation.entries]
        assert len(outputs) == PROGRESS_MAX_PENDING_TOOLS
        assert outputs[0] == str(flood - PROGRESS_MAX_PENDING_TOOLS)
        assert outputs[-1] == str(flood - 1)
        assert observation.omitted is True

    def test_pending_argument_bytes_share_one_budget(self, tmp_path: Path) -> None:
        """Open calls above 2 MiB together evict the oldest buffer; its late result has no entry."""
        half: str = "y" * (1536 * 1024)
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        for events in (
            [_tool_start(block_id="old", tool_name="old"), _tool_delta(block_id="old", delta=half)],
            [_tool_start(block_id="new", tool_name="new"), _tool_delta(block_id="new", delta=half)],
            [
                {"kind": "tool_call_end", "block_id": "new"},
                {"kind": "tool_result", "tool_call_id": "old", "content": "late"},
            ],
        ):
            _append(path=capture, events=events)
            observation = view.observe()

        assert [entry.tool_name for entry in observation.entries] == ["new"]
        assert observation.entries[0].tool_input == {"raw": half}
        assert observation.omitted is True

    def test_lone_oversized_text_entry_is_clipped(self, tmp_path: Path) -> None:
        """A single tool entry above the budget is clipped with a fixed marker, never kept whole."""
        capture = tmp_path / "stdout.jsonl"
        view = _CaptureView(path=capture)
        _append(path=capture, events=[_tool_start(block_id="b", tool_name="r" * 256)])
        view.observe()
        _append(
            path=capture,
            events=[
                {"kind": "tool_result", "tool_call_id": "b", "content": "z" * (PROGRESS_MAX_TEXT_BYTES - 128)}
            ],
        )

        observation = view.observe()

        assert len(observation.entries) == 1
        entry = observation.entries[0]
        assert _public_text_bytes(entry=entry) <= PROGRESS_MAX_TEXT_BYTES
        assert (entry.output or "").endswith(PROGRESS_TEXT_CLIPPED_MARKER)
        assert observation.omitted is True


class TestPendingToolCalls:
    """The pending-call owner bounds buffered argument bytes and call count."""

    def test_one_open_call_never_buffers_more_than_the_budget(self) -> None:
        """Arguments streamed above 2 MiB into one open call are truncated at the budget."""
        pending = _PendingToolCalls()
        pending.start(block_id="b", tool_name="write")
        for _ in range(3):
            pending.append(block_id="b", delta="x" * (1024 * 1024))

        assert pending.buffered_bytes == PROGRESS_MAX_TEXT_BYTES
        assert pending.omitted is True

    def test_multibyte_truncation_keeps_whole_characters(self) -> None:
        """Truncation never splits a UTF-8 character and never exceeds the budget."""
        pending = _PendingToolCalls()
        pending.start(block_id="b", tool_name="write")
        pending.append(block_id="b", delta="a")
        pending.append(block_id="b", delta="\u00e9" * PROGRESS_MAX_TEXT_BYTES)

        assert PROGRESS_MAX_TEXT_BYTES - 1 <= pending.buffered_bytes <= PROGRESS_MAX_TEXT_BYTES
        entry = pending.end(block_id="b")
        assert entry is not None and entry.tool_input is not None
        assert str(entry.tool_input["raw"]).encode("utf-8").decode("utf-8")
        assert pending.buffered_bytes == 0

    def test_starts_beyond_the_count_evict_the_oldest(self) -> None:
        """More than the pending-call bound keeps only the newest calls."""
        pending = _PendingToolCalls()
        for index in range(PROGRESS_MAX_PENDING_TOOLS + 3):
            pending.start(block_id=f"b{index}", tool_name=f"t{index}")

        assert pending.pending_calls == PROGRESS_MAX_PENDING_TOOLS
        assert pending.finish(call_id="b0") is None
        assert (
            pending.finish(call_id=f"b{PROGRESS_MAX_PENDING_TOOLS + 2}")
            == f"t{PROGRESS_MAX_PENDING_TOOLS + 2}"
        )
        assert pending.omitted is True

    def test_within_bounds_records_no_omission(self) -> None:
        """Calls that end and finish within the bounds release their bytes and omit nothing."""
        pending = _PendingToolCalls()
        pending.start(block_id="b", tool_name="read")
        pending.append(block_id="b", delta='{"path": "/tmp/f"}')
        pending.append(block_id="unknown", delta="ignored")

        entry = pending.end(block_id="b")

        assert entry is not None and entry.tool_input == {"path": "/tmp/f"}
        assert (pending.buffered_bytes, pending.pending_calls) == (0, 1)
        assert pending.finish(call_id="b") == "read"
        assert (pending.pending_calls, pending.omitted) == (0, False)
        assert pending.end(block_id="b") is None
