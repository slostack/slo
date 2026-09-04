"""Tests for incremental JSONL capture tails."""

from __future__ import annotations

from pathlib import Path

from src.tui.jsonl_tail import JsonlTail


def test_read_new_returns_appended_lines(tmp_path: Path) -> None:
    """Returns only complete lines appended since the visualizer last read."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"one\ntwo\n")

    assert tail.read_new() == [b"one", b"two"]

    path.write_bytes(b"one\ntwo\nthree\n")

    assert tail.read_new() == [b"three"]


def test_read_new_buffers_partial_line(tmp_path: Path) -> None:
    """Holds an incomplete line until the capture writer terminates it."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"partial")

    assert tail.read_new() == []

    with path.open("ab") as handle:
        handle.write(b" line\n")

    assert tail.read_new() == [b"partial line"]


def test_read_new_resets_after_truncation(tmp_path: Path) -> None:
    """Reads replacement content after the visualizer observes a smaller file."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"long original line\n")

    assert tail.read_new() == [b"long original line"]

    path.write_bytes(b"new\n")

    assert tail.read_new() == [b"new"]


def test_read_new_returns_empty_when_absent(tmp_path: Path) -> None:
    """Returns no lines when the visualizer has no capture file yet."""
    tail = JsonlTail(path=tmp_path / "stdout.jsonl")

    assert tail.read_new() == []
