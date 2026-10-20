"""Adapter tests for bounded canonical-history observation (spec 94.a.3, ticket T04).

Every case uses real tmp_path JSONL. Unbounded readers (``load_events``, archive
recovery, ``read_text``/``read_bytes``) are patched to fail so a passing test proves
the observation path never falls back to full replay or repair.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Optional

import pytest

from src.agents.slo_agent.history.dao import (
    HistoryObservationWindowDAO,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import (
    FilesystemSessionHistoryStore,
    _ObservedEventsFile,
)
from src.agents.slo_agent.history.store_protocol import SessionHistoryStoreProtocol
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore

_SESSION_ID: str = "observed-session"


def _event_line(*, sequence: int, content: str = "x") -> bytes:
    """Serialize one valid canonical event as a complete JSONL record.

    Args:
        sequence (int): Store-assigned sequence number.
        content (str): Payload content.

    Returns:
        bytes: The LF-terminated JSON record.
    """
    event = SessionHistoryEventDAO(
        session_id=_SESSION_ID,
        sequence=sequence,
        kind="user_message",
        payload=SessionHistoryEventPayloadDAO(content=content),
    )
    return event.model_dump_json().encode("utf-8") + b"\n"


def _write_history(*, root: Path, data: bytes) -> Path:
    """Write raw active-history bytes for the observed session.

    Args:
        root (Path): History root owned by the test.
        data (bytes): Exact events.jsonl content.

    Returns:
        Path: The events.jsonl path.
    """
    session_dir: Path = root / _SESSION_ID
    session_dir.mkdir(parents=True, exist_ok=True)
    events_path: Path = session_dir / "events.jsonl"
    events_path.write_bytes(data)
    return events_path


@pytest.fixture
def history_root(tmp_path: Path) -> Path:
    """Return a history root inside this test's temp directory."""
    root: Path = tmp_path / "history"
    root.mkdir()
    return root


@pytest.fixture
def store(history_root: Path, monkeypatch: pytest.MonkeyPatch) -> FilesystemSessionHistoryStore:
    """Return a real store whose full-load and recovery paths fail when called."""
    observed_store = FilesystemSessionHistoryStore(root=history_root)

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("observation must not use full-load, recovery or unbounded reads")

    monkeypatch.setattr(observed_store, "_load_events_sync", _forbidden)
    monkeypatch.setattr(observed_store, "_recover_compaction_archive_if_needed", _forbidden)
    monkeypatch.setattr(Path, "read_text", _forbidden)
    monkeypatch.setattr(Path, "read_bytes", _forbidden)
    return observed_store


def _bytes_of(*, path: Path) -> bytes:
    """Read a file with the builtin opener, which the fixtures leave unpatched.

    Args:
        path (Path): Temp-owned file to inspect.

    Returns:
        bytes: The file's complete content.
    """
    with open(path, "rb") as handle:
        return handle.read()


def _open_descriptor_count() -> int:
    """Return how many descriptors this process holds (Linux /proc)."""
    return len(os.listdir("/proc/self/fd"))


class TestObservationLimitsAndIdentity:
    """Budgets and identity are validated before any file is opened."""

    @pytest.mark.parametrize(
        ("max_bytes", "max_events"),
        [
            (0, 10),
            (-1, 10),
            (2_097_153, 10),
            (10, 0),
            (10, -5),
            (10, 2_001),
            (True, 10),
        ],
    )
    async def test_invalid_limits_are_rejected_before_open(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        max_bytes: int,
        max_events: int,
    ) -> None:
        """Rejects nonpositive, excessive or boolean budgets without touching the file."""
        _write_history(root=history_root, data=_event_line(sequence=1))

        def _no_open(*args: object, **kwargs: object) -> None:
            raise AssertionError("file opened before limit validation")

        monkeypatch.setattr(os, "open", _no_open)

        with pytest.raises(ValueError):
            await store.load_observation_window(
                session_id=_SESSION_ID,
                max_bytes=max_bytes,
                max_events=max_events,
            )

    @pytest.mark.parametrize("session_id", ["", ".", "..", "../escape", "a/b", "a\\b", "x\x00y"])
    async def test_unsafe_session_identity_is_rejected(
        self,
        store: FilesystemSessionHistoryStore,
        session_id: str,
    ) -> None:
        """Rejects identities that are not exactly one safe path component."""
        with pytest.raises(ValueError):
            await store.load_observation_window(session_id=session_id)

    async def test_maximum_limits_are_accepted(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Accepts the documented upper bounds exactly."""
        _write_history(root=history_root, data=_event_line(sequence=1))

        window = await store.load_observation_window(
            session_id=_SESSION_ID,
            max_bytes=2_097_152,
            max_events=2_000,
        )

        assert window.availability == "available"


class TestObservationAvailability:
    """Empty, available and missing sources are distinct observations."""

    async def test_zero_byte_active_file_is_empty(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Reports an existing empty log as authoritatively empty."""
        _write_history(root=history_root, data=b"")

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "empty"
        assert window.events == ()
        assert window.truncated is False

    async def test_complete_window_returns_events_and_revision(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Returns every record of a small log with a device/inode/size/mtime/start revision."""
        data: bytes = _event_line(sequence=1) + _event_line(sequence=2)
        events_path: Path = _write_history(root=history_root, data=data)
        status = os.stat(events_path)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "available"
        assert [event.sequence for event in window.events] == [1, 2]
        assert window.truncated is False
        assert window.revision == f"{status.st_dev}:{status.st_ino}:{len(data)}:{status.st_mtime_ns}:0"
        assert _bytes_of(path=events_path) == data

    async def test_missing_session_directory_is_unavailable(
        self,
        store: FilesystemSessionHistoryStore,
    ) -> None:
        """Reports a session with no directory as unavailable, not empty."""
        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window == HistoryObservationWindowDAO.unavailable()

    async def test_window_dao_is_frozen(self) -> None:
        """Keeps the observation envelope immutable once returned."""
        window = HistoryObservationWindowDAO.unavailable()

        with pytest.raises(ValueError):
            window.truncated = True  # type: ignore[misc]


class _BudgetedStream:
    """Read boundary that fails unbounded reads or total reads above a byte budget."""

    def __init__(self, *, inner: BinaryIO, budget: int, before_read: Callable[[], None]) -> None:
        """Wrap the store's real stream.

        Args:
            inner (BinaryIO): Real unbuffered stream opened by the store.
            budget (int): Maximum total bytes the observation may request.
            before_read (Callable[[], None]): Hook that may mutate the file mid-read.
        """
        self._inner: BinaryIO = inner
        self._budget: int = budget
        self._before_read: Callable[[], None] = before_read
        self.requested: int = 0

    def fileno(self) -> int:
        """Return the wrapped descriptor."""
        return self._inner.fileno()

    def seek(self, offset: int) -> int:
        """Delegate a seek to the wrapped stream."""
        return self._inner.seek(offset)

    def read(self, size: Optional[int] = None) -> bytes:
        """Allow only explicit, budgeted reads."""
        if size is None or size < 0:
            raise AssertionError("unbounded read attempted")
        self.requested += size
        if self.requested > self._budget:
            raise AssertionError("read exceeds the observation budget")
        self._before_read()
        return self._inner.read(size)


@pytest.fixture
def budgeted_streams(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., list[_BudgetedStream]]]:
    """Install the instrumented read boundary; returns a configurer listing wrapped streams."""
    streams: list[_BudgetedStream] = []
    real_stream_for = _ObservedEventsFile._stream_for

    def _configure(*, budget: int, before_read: Callable[[], None] = lambda: None) -> list[_BudgetedStream]:
        def _wrapped(*, descriptor: int) -> BinaryIO:
            stream = _BudgetedStream(
                inner=real_stream_for(descriptor=descriptor),
                budget=budget,
                before_read=before_read,
            )
            streams.append(stream)
            return stream  # type: ignore[return-value]

        monkeypatch.setattr(_ObservedEventsFile, "_stream_for", staticmethod(_wrapped))
        return streams

    yield _configure


def _many_lines(*, count: int, first_sequence: int = 1) -> bytes:
    """Return ``count`` consecutive valid records.

    Args:
        count (int): Number of records.
        first_sequence (int): Sequence of the first record.

    Returns:
        bytes: Concatenated LF-terminated records.
    """
    return b"".join(_event_line(sequence=first_sequence + index) for index in range(count))


class TestBoundedRead:
    """The byte budget bounds every read and the decoder input."""

    async def test_read_budget_is_enforced_before_decode(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        budgeted_streams: Callable[..., list[_BudgetedStream]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reads at most max_bytes once and decodes only complete records inside it."""
        data: bytes = _many_lines(count=500)
        events_path: Path = _write_history(root=history_root, data=data)
        streams = budgeted_streams(budget=4_096)
        decoded: list[bytes] = []
        real_decode = FilesystemSessionHistoryStore._decode_observation_record

        def _counting_decode(*, record: bytes) -> Optional[SessionHistoryEventDAO]:
            decoded.append(record)
            return real_decode(record=record)

        monkeypatch.setattr(
            FilesystemSessionHistoryStore, "_decode_observation_record", staticmethod(_counting_decode)
        )

        window = await store.load_observation_window(session_id=_SESSION_ID, max_bytes=4_096)

        assert streams[0].requested == 4_096
        assert sum(len(record) + 1 for record in decoded) <= 4_096
        assert window.truncated is True
        assert [event.sequence for event in window.events] == list(range(501 - len(window.events), 501))
        assert len(window.events) == len(decoded)
        assert window.revision.endswith(f":{len(data) - 4_096}")
        assert _bytes_of(path=events_path) == data

    async def test_large_single_record_is_omitted(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        budgeted_streams: Callable[..., list[_BudgetedStream]],
    ) -> None:
        """Omits a record larger than the budget without a second read."""
        data: bytes = (
            _event_line(sequence=1) + _event_line(sequence=2, content="a" * 6_000) + _event_line(sequence=3)
        )
        _write_history(root=history_root, data=data)
        streams = budgeted_streams(budget=4_096)

        window = await store.load_observation_window(session_id=_SESSION_ID, max_bytes=4_096)

        assert [event.sequence for event in window.events] == [3]
        assert window.truncated is True
        assert len(streams) == 1

    async def test_window_inside_one_huge_final_record_is_available_and_empty(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Reports zero events, not an empty log, when the budget sees only a fragment."""
        _write_history(
            root=history_root, data=_event_line(sequence=1) + _event_line(sequence=2, content="b" * 6_000)
        )

        window = await store.load_observation_window(session_id=_SESSION_ID, max_bytes=4_096)

        assert window.availability == "available"
        assert window.events == ()
        assert window.truncated is True


class TestRecordBoundaries:
    """Only complete LF-delimited records reach the decoder."""

    async def test_partial_utf8_and_lf_boundaries(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Drops a leading fragment split inside UTF-8 and a final line without LF."""
        leading: bytes = _event_line(sequence=1, content="é" * 3_000)
        middle: bytes = _event_line(sequence=2, content="line\u2028sep\u0085next")
        partial_tail: bytes = _event_line(sequence=3)[:-10]
        data: bytes = leading + middle + partial_tail
        _write_history(root=history_root, data=data)
        budget: int = len(middle) + len(partial_tail) + 1_001  # start lands inside the é run

        assert data[len(data) - budget : len(data) - budget + 1] in {b"\xc3", b"\xa9"}

        decoded: list[bytes] = []
        real_decode = FilesystemSessionHistoryStore._decode_observation_record

        def _recording_decode(*, record: bytes) -> Optional[SessionHistoryEventDAO]:
            decoded.append(record)
            return real_decode(record=record)

        monkeypatch.setattr(
            FilesystemSessionHistoryStore, "_decode_observation_record", staticmethod(_recording_decode)
        )

        window = await store.load_observation_window(session_id=_SESSION_ID, max_bytes=budget)

        assert [event.sequence for event in window.events] == [2]
        assert window.events[0].payload.content == "line\u2028sep\u0085next"
        assert window.truncated is True
        assert decoded == [middle[:-1]]

    async def test_offset_on_record_boundary_still_omits_first_record(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Conservatively discards the first record when the window starts mid-file."""
        first: bytes = _event_line(sequence=1)
        second: bytes = _event_line(sequence=2)
        third: bytes = _event_line(sequence=3)
        _write_history(root=history_root, data=first + second + third)

        window = await store.load_observation_window(
            session_id=_SESSION_ID, max_bytes=len(second) + len(third)
        )

        assert [event.sequence for event in window.events] == [3]
        assert window.truncated is True

    async def test_crlf_and_blank_lines_are_tolerated(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Accepts CRLF records and ignores blank lines like the full loader."""
        data: bytes = _event_line(sequence=1)[:-1] + b"\r\n" + b"\n  \n" + _event_line(sequence=2)
        _write_history(root=history_root, data=data)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert [event.sequence for event in window.events] == [1, 2]
        assert window.truncated is False

    @pytest.mark.parametrize(
        "malformed",
        [
            b"{not json PRIVATE-SENTINEL}\n",
            b"\xff\xfePRIVATE-SENTINEL\n",
            b'{"kind": "PRIVATE-SENTINEL", "session_id": "x"}\n',
            b"42\n",
        ],
        ids=["json", "utf8", "schema", "non-object"],
    )
    async def test_malformed_complete_lines_are_skipped(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        caplog: pytest.LogCaptureFixture,
        malformed: bytes,
    ) -> None:
        """Skips invalid records with omission state and never logs their bytes."""
        data: bytes = _event_line(sequence=1) + malformed + _event_line(sequence=2)
        events_path: Path = _write_history(root=history_root, data=data)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert [event.sequence for event in window.events] == [1, 2]
        assert window.truncated is True
        assert "PRIVATE-SENTINEL" not in caplog.text
        assert _bytes_of(path=events_path) == data

    async def test_events_are_returned_in_ascending_sequence(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Sorts the retained records by sequence like the full loader."""
        data: bytes = _event_line(sequence=3) + _event_line(sequence=1) + _event_line(sequence=2)
        _write_history(root=history_root, data=data)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert [event.sequence for event in window.events] == [1, 2, 3]


class TestEventBudget:
    """The event budget keeps only the latest records."""

    async def test_two_thousand_records_fit_without_omission(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Returns exactly 2,000 records with no omission at the cap."""
        _write_history(root=history_root, data=_many_lines(count=2_000))

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert len(window.events) == 2_000
        assert window.truncated is False

    async def test_record_cap_keeps_latest_and_marks_omission(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Drops the oldest valid record above 2,000 and marks the window truncated."""
        _write_history(root=history_root, data=_many_lines(count=2_001))

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert [event.sequence for event in window.events] == list(range(2, 2_002))
        assert window.truncated is True

    async def test_small_event_budget_keeps_latest(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Honours a caller budget below the cap."""
        _write_history(root=history_root, data=_many_lines(count=10))

        window = await store.load_observation_window(session_id=_SESSION_ID, max_events=3)

        assert [event.sequence for event in window.events] == [8, 9, 10]
        assert window.truncated is True


class TestRefusedSources:
    """Missing, symlinked and non-regular sources are unavailable and never repaired."""

    async def test_missing_active_never_recovers_archive(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Leaves a compaction archive in place and reports the session unavailable."""
        session_dir: Path = history_root / _SESSION_ID
        session_dir.mkdir()
        archive: Path = session_dir / "events.pre-0001.jsonl"
        archive_bytes: bytes = _many_lines(count=3)
        archive.write_bytes(archive_bytes)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window == HistoryObservationWindowDAO.unavailable()
        assert not (session_dir / "events.jsonl").exists()
        assert _bytes_of(path=archive) == archive_bytes
        assert sorted(path.name for path in session_dir.iterdir()) == ["events.pre-0001.jsonl"]

    async def test_symlinked_events_file_is_refused(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        tmp_path: Path,
        budgeted_streams: Callable[..., list[_BudgetedStream]],
    ) -> None:
        """Refuses an events.jsonl symlink to a file in a second temp-owned root."""
        outside: Path = tmp_path / "outside"
        outside.mkdir()
        target: Path = outside / "events.jsonl"
        target_bytes: bytes = _many_lines(count=2)
        target.write_bytes(target_bytes)
        session_dir: Path = history_root / _SESSION_ID
        session_dir.mkdir()
        (session_dir / "events.jsonl").symlink_to(target)
        streams = budgeted_streams(budget=2_097_152)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "unavailable"
        assert streams == []
        assert _bytes_of(path=target) == target_bytes

    async def test_symlinked_session_directory_is_refused(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        tmp_path: Path,
    ) -> None:
        """Refuses a session directory that is a symlink outside the history root."""
        outside: Path = tmp_path / "outside"
        outside.mkdir()
        (outside / "events.jsonl").write_bytes(_many_lines(count=2))
        (history_root / _SESSION_ID).symlink_to(outside, target_is_directory=True)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "unavailable"

    async def test_directory_named_events_is_refused(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Refuses a non-regular events path such as a directory."""
        (history_root / _SESSION_ID / "events.jsonl").mkdir(parents=True)

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "unavailable"

    async def test_fifo_events_path_is_refused_without_blocking(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Refuses a FIFO without blocking the observation thread."""
        session_dir: Path = history_root / _SESSION_ID
        session_dir.mkdir()
        os.mkfifo(session_dir / "events.jsonl")

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "unavailable"

    async def test_missing_history_root_is_unavailable(self, tmp_path: Path) -> None:
        """Reports unavailable when the configured root does not exist yet."""
        missing_root_store = FilesystemSessionHistoryStore(root=tmp_path / "absent")

        window = await missing_root_store.load_observation_window(session_id=_SESSION_ID)

        assert window.availability == "unavailable"
        assert not (tmp_path / "absent").exists()

    async def test_other_open_failures_propagate_and_close_descriptors(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Raises a real I/O fault instead of masking it, leaking no descriptors."""
        _write_history(root=history_root, data=_event_line(sequence=1))
        real_open = os.open

        def _denied_events_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if path == "events.jsonl":
                raise PermissionError(errno.EACCES, "denied")
            return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(os, "open", _denied_events_open)
        before: int = _open_descriptor_count()

        with pytest.raises(PermissionError):
            await store.load_observation_window(session_id=_SESSION_ID)

        assert _open_descriptor_count() == before


class TestGenerationChanges:
    """A source that changes during the read is unavailable; replacements get new revisions."""

    @staticmethod
    def _append(*, events_path: Path) -> Callable[[], None]:
        """Return a hook that appends one record through a separate writer."""

        def _hook() -> None:
            with open(events_path, "ab") as writer:
                writer.write(_event_line(sequence=99))

        return _hook

    @staticmethod
    def _replace_file(*, events_path: Path) -> Callable[[], None]:
        """Return a hook that atomically replaces the active log with same-size content."""

        def _hook() -> None:
            replacement: Path = events_path.with_name("replacement.jsonl")
            with open(replacement, "wb") as writer:
                writer.write(_event_line(sequence=7))
            os.replace(replacement, events_path)

        return _hook

    @staticmethod
    def _replace_directory(*, events_path: Path) -> Callable[[], None]:
        """Return a hook that moves the session directory away and recreates it."""

        def _hook() -> None:
            session_dir: Path = events_path.parent
            session_dir.rename(session_dir.with_name("moved-away"))
            session_dir.mkdir()
            with open(events_path, "wb") as writer:
                writer.write(_event_line(sequence=7))

        return _hook

    @pytest.mark.parametrize("mutation", ["_append", "_replace_file", "_replace_directory"])
    async def test_changed_descriptor_returns_unavailable(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
        budgeted_streams: Callable[..., list[_BudgetedStream]],
        mutation: str,
    ) -> None:
        """Returns no events when fstat or path identity changed during the read."""
        events_path: Path = _write_history(root=history_root, data=_event_line(sequence=1))
        budgeted_streams(budget=2_097_152, before_read=getattr(self, mutation)(events_path=events_path))
        before: int = _open_descriptor_count()

        window = await store.load_observation_window(session_id=_SESSION_ID)

        assert window == HistoryObservationWindowDAO.unavailable()
        assert _open_descriptor_count() == before

    async def test_replacement_between_polls_changes_revision(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Observes a replaced generation with a new revision and only its records."""
        events_path: Path = _write_history(root=history_root, data=_event_line(sequence=1))
        first = await store.load_observation_window(session_id=_SESSION_ID)
        self._replace_file(events_path=events_path)()

        second = await store.load_observation_window(session_id=_SESSION_ID)

        assert second.revision != first.revision
        assert [event.sequence for event in second.events] == [7]

    async def test_append_between_polls_extends_window(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Sees an appended record on the next poll with a new size revision."""
        events_path: Path = _write_history(root=history_root, data=_event_line(sequence=1))
        first = await store.load_observation_window(session_id=_SESSION_ID)
        self._append(events_path=events_path)()

        second = await store.load_observation_window(session_id=_SESSION_ID)

        assert second.revision != first.revision
        assert [event.sequence for event in second.events] == [1, 99]

    async def test_successful_and_refused_reads_close_every_descriptor(
        self,
        store: FilesystemSessionHistoryStore,
        history_root: Path,
    ) -> None:
        """Leaves the process descriptor count unchanged after available and unavailable reads."""
        before: int = _open_descriptor_count()
        await store.load_observation_window(session_id=_SESSION_ID)
        _write_history(root=history_root, data=_event_line(sequence=1))
        await store.load_observation_window(session_id=_SESSION_ID)

        assert _open_descriptor_count() == before


class TestTreeDelegation:
    """The tree decorator delegates the exact limits to its flat store."""

    async def test_tree_delegates_same_limits(
        self,
        history_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Forwards identity and budgets unchanged and returns the flat result."""
        tree = TreeBasedFilesystemSessionHistoryStore(root=history_root)
        calls: list[dict[str, object]] = []
        expected = HistoryObservationWindowDAO.unavailable()

        async def _recording(**kwargs: object) -> HistoryObservationWindowDAO:
            calls.append(kwargs)
            return expected

        monkeypatch.setattr(tree._flat, "load_observation_window", _recording)

        window = await tree.load_observation_window(session_id=_SESSION_ID, max_bytes=4_096, max_events=7)

        assert window is expected
        assert calls == [{"session_id": _SESSION_ID, "max_bytes": 4_096, "max_events": 7}]

    async def test_tree_reads_real_window_with_default_limits(self, history_root: Path) -> None:
        """Reads the same bounded window through the default tree store."""
        _write_history(root=history_root, data=_many_lines(count=3))
        tree = TreeBasedFilesystemSessionHistoryStore(root=history_root)

        window = await tree.load_observation_window(session_id=_SESSION_ID)

        assert [event.sequence for event in window.events] == [1, 2, 3]
        assert isinstance(tree, SessionHistoryStoreProtocol)

    async def test_tree_rejects_invalid_limits(self, history_root: Path) -> None:
        """Surfaces the flat store's limit validation unchanged."""
        tree = TreeBasedFilesystemSessionHistoryStore(root=history_root)

        with pytest.raises(ValueError):
            await tree.load_observation_window(session_id=_SESSION_ID, max_bytes=0)
