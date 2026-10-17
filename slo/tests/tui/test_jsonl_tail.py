"""Tests for incremental JSONL capture tails."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

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


class _RecordingPath(type(Path())):  # type: ignore[misc]
    """Temp-owned path whose opened handles record every requested read size."""

    read_sizes: list[int]

    def open(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        """Open the file and wrap the handle so read sizes are observable."""
        handle = super().open(*args, **kwargs)
        sizes: list[int] = self.read_sizes
        real_read = handle.read

        def _read(size: int = -1) -> bytes:
            if size is None or size < 0:
                raise AssertionError("unbounded capture read")
            sizes.append(size)
            return real_read(size)

        handle.read = _read
        return handle


def _recording_path(*, path: Path) -> _RecordingPath:
    """Return a recording view of a temp-owned capture path.

    Args:
        path (Path): Capture path inside tmp_path.

    Returns:
        _RecordingPath: Path whose reads are recorded in ``read_sizes``.
    """
    recording = _RecordingPath(path)
    recording.read_sizes = []
    return recording


def _replace(*, path: Path, data: bytes) -> None:
    """Atomically replace the capture with a new inode holding ``data``.

    Args:
        path (Path): Capture path inside tmp_path.
        data (bytes): Replacement content.
    """
    replacement: Path = path.with_name("replacement.jsonl")
    replacement.write_bytes(data)
    os.replace(replacement, path)


@pytest.mark.parametrize("max_read_bytes", [0, -1])
def test_invalid_read_budget_is_rejected(tmp_path: Path, max_read_bytes: int) -> None:
    """Rejects a nonpositive per-read byte budget."""
    with pytest.raises(ValueError):
        JsonlTail(path=tmp_path / "stdout.jsonl", max_read_bytes=max_read_bytes)


def test_new_tail_starts_at_revision_zero_untruncated(tmp_path: Path) -> None:
    """Starts with no resets and no omission, even after the file first appears."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)

    assert tail.read_new() == []
    path.write_bytes(b"one\n")

    assert tail.read_new() == [b"one"]
    assert tail.revision == 0
    assert tail.truncated is False


def test_equal_size_replacement_resets_and_rereads(tmp_path: Path) -> None:
    """Reads a same-size replacement from its start under a new revision."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"aaa\n")
    assert tail.read_new() == [b"aaa"]

    _replace(path=path, data=b"bbb\n")

    assert tail.read_new() == [b"bbb"]
    assert tail.revision == 1


def test_larger_replacement_resets_instead_of_seeking_old_offset(tmp_path: Path) -> None:
    """Never resumes a replacement at the previous generation's offset."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"one\n")
    assert tail.read_new() == [b"one"]

    _replace(path=path, data=b"two\nthree\n")

    assert tail.read_new() == [b"two", b"three"]
    assert tail.revision == 1


def test_shrink_resets_revision_and_discards_pending(tmp_path: Path) -> None:
    """Drops a held partial line from the old generation when the file shrinks."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path)
    path.write_bytes(b"first\nheld-partial")
    assert tail.read_new() == [b"first"]

    path.write_bytes(b"new\n")

    assert tail.read_new() == [b"new"]
    assert tail.revision == 1


def test_initial_oversized_file_reads_latest_bounded_tail(tmp_path: Path) -> None:
    """Reads only the newest complete lines within the budget and marks omission."""
    path: Path = tmp_path / "stdout.jsonl"
    path.write_bytes(b"".join(f"line-{index:03d}\n".encode() for index in range(10)))
    recording = _recording_path(path=path)
    tail = JsonlTail(path=recording, max_read_bytes=25)

    lines = tail.read_new()

    assert lines == [b"line-008", b"line-009"]
    assert tail.truncated is True
    assert recording.read_sizes == [25]


def test_oversized_backlog_after_first_read_selects_bounded_tail(tmp_path: Path) -> None:
    """Skips an appended backlog larger than the budget down to its latest lines."""
    path: Path = tmp_path / "stdout.jsonl"
    recording = _recording_path(path=path)
    tail = JsonlTail(path=recording, max_read_bytes=25)
    path.write_bytes(b"start\n")
    assert tail.read_new() == [b"start"]
    assert tail.truncated is False

    with path.open("ab") as handle:
        handle.write(b"".join(f"line-{index:03d}\n".encode() for index in range(10)))

    assert tail.read_new() == [b"line-008", b"line-009"]
    assert tail.truncated is True
    assert max(recording.read_sizes) <= 25


def test_oversized_single_line_is_skipped_until_its_newline(tmp_path: Path) -> None:
    """Never emits the tail fragment of a line longer than the budget."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path, max_read_bytes=16)
    path.write_bytes(b"x" * 40)

    assert tail.read_new() == []

    with path.open("ab") as handle:
        handle.write(b"end-of-big\nnext\n")

    assert tail.read_new() == [b"next"]
    assert tail.truncated is True


def test_pending_bytes_are_capped_to_the_budget(tmp_path: Path) -> None:
    """Drops a growing partial line once held bytes exceed the budget."""
    path: Path = tmp_path / "stdout.jsonl"
    recording = _recording_path(path=path)
    tail = JsonlTail(path=recording, max_read_bytes=16)
    path.write_bytes(b"a" * 10)
    assert tail.read_new() == []
    assert tail.truncated is False

    with path.open("ab") as handle:
        handle.write(b"b" * 10)
    assert tail.read_new() == []

    with path.open("ab") as handle:
        handle.write(b"\nok\n")

    assert tail.read_new() == [b"ok"]
    assert tail.truncated is True
    assert max(recording.read_sizes) <= 16


def test_bounded_repeated_append_returns_every_line(tmp_path: Path) -> None:
    """Returns every line of small appends without omission or reset."""
    path: Path = tmp_path / "stdout.jsonl"
    recording = _recording_path(path=path)
    tail = JsonlTail(path=recording, max_read_bytes=16)
    path.write_bytes(b"")
    collected: list[bytes] = []

    for index in range(20):
        with path.open("ab") as handle:
            handle.write(f"l{index}\n".encode())
        collected.extend(tail.read_new())

    assert collected == [f"l{index}".encode() for index in range(20)]
    assert tail.truncated is False
    assert tail.revision == 0
    assert max(recording.read_sizes) <= 16


def test_replacement_after_truncated_view_clears_omission(tmp_path: Path) -> None:
    """Starts a replacement generation with a fresh omission state."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path, max_read_bytes=16)
    path.write_bytes(b"y" * 40 + b"\n")
    tail.read_new()
    assert tail.truncated is True

    _replace(path=path, data=b"fresh\n")

    assert tail.read_new() == [b"fresh"]
    assert tail.truncated is False
    assert tail.revision == 1


def test_line_completed_inside_one_read_above_budget_is_dropped(tmp_path: Path) -> None:
    """Drops a line that held bytes plus one read complete above the budget."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path, max_read_bytes=16)
    path.write_bytes(b"a" * 10)
    assert tail.read_new() == []

    with path.open("ab") as handle:
        handle.write(b"b" * 7 + b"c\n")

    assert tail.read_new() == []
    assert tail.truncated is True


def test_line_exactly_at_budget_is_emitted(tmp_path: Path) -> None:
    """Emits a complete line whose length equals the budget without omission."""
    path: Path = tmp_path / "stdout.jsonl"
    tail = JsonlTail(path=path, max_read_bytes=16)
    path.write_bytes(b"a" * 10)
    assert tail.read_new() == []

    with path.open("ab") as handle:
        handle.write(b"b" * 6 + b"\nok\n")

    assert tail.read_new() == [b"a" * 10 + b"b" * 6, b"ok"]
    assert tail.truncated is False
