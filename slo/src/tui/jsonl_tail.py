"""JsonlTail — offset-tracked, bounded incremental reader for JSONL capture files.

One tail per capture file. Each ``read_new`` call returns only complete lines
appended since the previous call; a trailing partial line is held for the next
call. Every read, and the held partial line, is bounded by ``max_read_bytes``:
a larger backlog is skipped down to its latest complete lines, and a single line
longer than the budget is dropped. A replaced (new device/inode) or shrunk file
resets the tail and bumps ``revision`` so callers reproject instead of replaying
old buffers into the new file. Pure filesystem, no Textual.

Sub-spec 71.a.7; bounded contract from spec 94.a.3.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO, Optional

__all__ = ["JsonlTail"]

_DEFAULT_MAX_READ_BYTES: int = 2_097_152


class JsonlTail:
    """Incrementally read one growing JSONL capture file within a byte budget."""

    def __init__(self, *, path: Path, max_read_bytes: int = _DEFAULT_MAX_READ_BYTES) -> None:
        """Bind the tail to one capture path.

        WHAT: Stores the next unread byte position and the file generation for one
            capture file.
        WHO: Called by WorkflowVisualizerLoader when it first tails a session.
        WHEN: Once per capture path, before visualizer refreshes read new lines.

        Args:
            path (Path): JSONL file to tail; it may not exist yet.
            max_read_bytes (int, optional): Positive bound for each read and for the
                held partial line. Defaults to 2,097,152.

        Raises:
            ValueError: When ``max_read_bytes`` is not positive.
        """
        if max_read_bytes <= 0:
            raise ValueError("max_read_bytes must be positive")
        self._path: Path = path
        self._max_read_bytes: int = max_read_bytes
        self._offset: int = 0
        self._pending: bytes = b""
        # (st_dev, st_ino) of the generation being tailed; None until first observed.
        self._identity: Optional[tuple[int, int]] = None
        # True while the bytes being read belong to a line whose start was omitted.
        self._skipping_partial_line: bool = False
        self._revision: int = 0
        self._truncated: bool = False

    @property
    def revision(self) -> int:
        """Count of resets caused by file replacement or truncation. Read-only."""
        return self._revision

    @property
    def truncated(self) -> bool:
        """Whether bytes of the current generation were omitted from this view. Read-only."""
        return self._truncated

    def read_new(self) -> list[bytes]:
        """Return complete lines appended since the prior visualizer refresh.

        WHAT: Reads at most ``max_read_bytes`` after the saved offset from the same
            descriptor whose identity and size it checks, resetting first when the
            file was replaced or shrank, and retains an incomplete trailing line
            until the capture writer supplies its newline.
        WHO: Called by WorkflowVisualizerLoader for live transcript updates.
        WHEN: Once on each visualizer refresh while a session is live.

        Returns:
            list[bytes]: Complete new lines without newline bytes, in order.
        """
        try:
            handle: BinaryIO = self._path.open("rb")
        except FileNotFoundError:
            return []
        with handle:
            status: os.stat_result = os.fstat(handle.fileno())
            self._follow_generation(status=status)
            if status.st_size == self._offset:
                return []
            return self._read_appended(handle=handle, size=status.st_size)

    def _follow_generation(self, *, status: os.stat_result) -> None:
        """Reset when the opened file is a new generation or shorter than the offset.

        Args:
            status (os.stat_result): Status of the descriptor about to be read.
        """
        identity: tuple[int, int] = (status.st_dev, status.st_ino)
        replaced: bool = self._identity is not None and identity != self._identity
        if replaced or status.st_size < self._offset:
            self._reset()
        self._identity = identity

    def _reset(self) -> None:
        """Restart reading after capture rotation, replacement or truncation."""
        self._offset = 0
        self._pending = b""
        self._skipping_partial_line = False
        self._truncated = False
        self._revision += 1

    def _read_appended(self, *, handle: BinaryIO, size: int) -> list[bytes]:
        """Read the bounded appended byte range and split it into complete lines.

        Args:
            handle (BinaryIO): Open capture descriptor.
            size (int): Current capture file size in bytes.

        Returns:
            list[bytes]: Complete lines from the newly appended bytes.
        """
        start: int = self._bounded_start(size=size)
        handle.seek(start)
        chunk: bytes = handle.read(size - start)
        self._offset = start + len(chunk)
        return self._complete_lines(chunk=chunk)

    def _bounded_start(self, *, size: int) -> int:
        """Choose where to read from, skipping a backlog larger than the budget.

        Args:
            size (int): Current capture file size in bytes.

        Returns:
            int: The saved offset, or the start of the latest bounded tail.
        """
        if size - self._offset <= self._max_read_bytes:
            return self._offset
        self._omit_partial_line()
        return size - self._max_read_bytes

    def _omit_partial_line(self) -> None:
        """Drop held bytes and ignore input until the next newline ends the omitted line."""
        self._pending = b""
        self._skipping_partial_line = True
        self._truncated = True

    def _complete_lines(self, *, chunk: bytes) -> list[bytes]:
        """Join held bytes with ``chunk`` and return the complete, non-omitted lines.

        Args:
            chunk (bytes): Bytes just read, at most the budget.

        Returns:
            list[bytes]: Non-empty complete lines in order.
        """
        lines: list[bytes] = (self._pending + chunk).split(b"\n")
        self._pending = lines.pop()
        if self._skipping_partial_line and lines:
            lines.pop(0)
            self._skipping_partial_line = False
        self._cap_pending()
        return self._within_budget(lines=[line for line in lines if line])

    def _within_budget(self, *, lines: list[bytes]) -> list[bytes]:
        """Drop complete lines longer than the budget and mark the view truncated.

        Held bytes plus one read can complete a line of up to twice the budget, so
        the length check applies to every complete line regardless of poll timing.

        Args:
            lines (list[bytes]): Non-empty complete lines in order.

        Returns:
            list[bytes]: The lines no longer than ``max_read_bytes``, in order.
        """
        kept: list[bytes] = [line for line in lines if len(line) <= self._max_read_bytes]
        self._truncated = self._truncated or len(kept) < len(lines)
        return kept

    def _cap_pending(self) -> None:
        """Drop a held partial line once it exceeds the budget; it can never be emitted whole."""
        if len(self._pending) > self._max_read_bytes:
            self._omit_partial_line()
