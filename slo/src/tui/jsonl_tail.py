"""JsonlTail — offset-tracked incremental reader for JSONL capture files.

One tail per capture file. Each ``read_new`` call returns only complete lines
appended since the previous call; a trailing partial line is held for the next
call. Files that shrink reset automatically. Pure filesystem, no Textual.

Sub-spec 71.a.7.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["JsonlTail"]


class JsonlTail:
    """Incrementally read one growing JSONL capture file."""

    def __init__(self, *, path: Path) -> None:
        """Bind the tail to one capture path.

        WHAT: Stores the next unread byte position for one capture file.
        WHO: Called by WorkflowVisualizerLoader when it first tails a session.
        WHEN: Once per capture path, before visualizer refreshes read new lines.

        Args:
            path (Path): JSONL file to tail; it may not exist yet.
        """
        self._path: Path = path
        self._offset: int = 0
        self._pending: bytes = b""

    def read_new(self) -> list[bytes]:
        """Return complete lines appended since the prior visualizer refresh.

        WHAT: Reads only bytes after the saved offset and retains an incomplete
        trailing line until the capture writer supplies its newline.
        WHO: Called by WorkflowVisualizerLoader for live transcript updates.
        WHEN: Once on each visualizer refresh while a session is live.

        Returns:
            list[bytes]: Complete new lines without newline bytes, in order.
        """
        if not self._path.exists():
            return []
        size: int = self._path.stat().st_size
        if size < self._offset:
            self._reset()
        if size == self._offset:
            return []
        return self._read_appended(size=size)

    def _reset(self) -> None:
        """Restart reading after capture rotation or truncation."""
        self._offset = 0
        self._pending = b""

    def _read_appended(self, *, size: int) -> list[bytes]:
        """Read and split the appended byte range into complete JSONL lines.

        Args:
            size (int): Current capture file size in bytes.

        Returns:
            list[bytes]: Complete lines from the newly appended bytes.
        """
        with self._path.open("rb") as handle:
            handle.seek(self._offset)
            chunk: bytes = handle.read(size - self._offset)
        self._offset = size
        data: bytes = self._pending + chunk
        lines: list[bytes] = data.split(b"\n")
        self._pending = lines.pop() if data and not data.endswith(b"\n") else b""
        return [line for line in lines if line]
