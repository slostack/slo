"""Private I/O failure translation and real durability fault evidence."""

import os
import stat
import traceback
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.restore import HerdrRestoreStore, HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


@pytest.mark.parametrize("fault", ["open", "close", "inode", "mode"])
def test_record_descriptor_fault(tmp_path: Path, fault: str) -> None:
    """Record-specific failures cannot leak values or return an unverified inode."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    record = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    before = record.read_bytes()
    original_open, original_close = os.open, os.close
    record_fd: list[int] = []

    def open_record(path: Path, flags: int, mode: int = 0o777) -> int:
        """Mutate only the contained record at its exact open boundary."""
        if path == record:
            if fault == "open":
                raise OSError("PRIVATE-SENTINEL")
            if fault == "inode":
                record.rename(record.parent / "retained")
                original_close(original_open(record, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
                record.write_bytes(before)
            if fault == "mode":
                record.chmod(0o644)
        fd = original_open(path, flags, mode)
        if path == record:
            record_fd.append(fd)
        return fd

    def close_record(fd: int) -> None:
        """Release the real descriptor before injecting a close-reporting failure."""
        original_close(fd)
        if fault == "close" and record_fd and fd == record_fd[-1]:
            raise OSError("PRIVATE-SENTINEL")

    with (
        patch.object(os, "open", side_effect=open_record),
        patch.object(os, "close", side_effect=close_record),
    ):
        with pytest.raises(HerdrRestoreUnavailableError) as caught:
            store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
    assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    assert record.read_bytes() == before


@pytest.mark.parametrize("operation", ["save", "load"])
def test_lease_close_fault_is_private(tmp_path: Path, operation: str) -> None:
    """Even a cleanup syscall failure must cross the fixed public error boundary."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    original = HerdrFileLease.close

    def close_then_fail(lease: HerdrFileLease) -> None:
        """Actually release the owned descriptor before injecting a private fault."""
        original(lease)
        raise OSError("PRIVATE-SENTINEL")

    with patch.object(HerdrFileLease, "close", close_then_fail):
        with pytest.raises(HerdrRestoreUnavailableError) as caught:
            if operation == "save":
                store.save(config=config_for(tmp_path))
            else:
                store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
    assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
    assert store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID) == config_for(
        tmp_path
    )


@pytest.mark.parametrize("directory", [False, True])
def test_real_fsync_failure(tmp_path: Path, directory: bool) -> None:
    """Fail actual writer fsync: pre-replace cleans temp; post-replace retains orphan."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    root = tmp_path / "restore-v1"
    old = root / f"{saved.restore_reference}.json"
    before = old.read_bytes()
    original = os.fsync
    calls: list[bool] = []

    def sync(fd: int) -> None:
        """Select file or directory descriptor without bypassing writer execution."""
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        calls.append(is_directory)
        if is_directory == directory:
            raise OSError("PRIVATE-SENTINEL")
        original(fd)

    with patch("src.agents.slo_agent.history.atomic_io.os.fsync", side_effect=sync):
        with pytest.raises(HerdrRestoreUnavailableError) as caught:
            store.save(config=config_for(tmp_path))
    assert calls == ([False, True] if directory else [False])
    assert len(list(root.iterdir())) == (2 if directory else 1)
    assert old.read_bytes() == before
    assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(caught.value))
