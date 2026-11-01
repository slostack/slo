"""Fail-closed load security using exclusively temporary private files."""

from pathlib import Path
import os
from unittest.mock import patch

import pytest

from src.agents.slo_agent.herdr.dao import HerdrRestoreUnavailableError
from src.agents.slo_agent.herdr.restore import HerdrRestoreStore
from tests.agents.slo_agent.herdr.test_restore_save import SESSION_ID, config_for


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "json",
        "oversize",
        "mode",
        "hardlink",
        "directory",
        "fifo",
        "symlink",
        "identity",
        "reference",
        "schema",
    ],
)
def test_load_faults_are_private(tmp_path: Path, fault: str) -> None:
    """Unsafe exact targets refuse without rewriting or falling back to another record."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    original = path.read_text()
    if fault == "missing":
        path.unlink()
    elif fault == "json":
        path.write_text("PRIVATE-SENTINEL")
    elif fault == "oversize":
        path.write_bytes(b" " * 65537)
    elif fault == "mode":
        path.chmod(0o644)
    elif fault == "hardlink":
        os.link(path, tmp_path / "alias")
    elif fault in {"directory", "fifo", "symlink"}:
        path.unlink()
        if fault == "directory":
            path.mkdir(mode=0o700)
        elif fault == "fifo":
            os.mkfifo(path, mode=0o600)
        else:
            target = tmp_path / "private-target"
            target.touch(mode=0o600)
            target.write_text(original)
            path.symlink_to(target)
    else:
        replacements = {
            "identity": (SESSION_ID, "87654321-1234-1234-1234-123456789abc"),
            "reference": (saved.restore_reference, "r1-" + "0" * 32),
            "schema": ('"schema_version":1', '"schema_version":2'),
        }
        before, after = replacements[fault]
        path.write_text(original.replace(before, after))
    with pytest.raises(HerdrRestoreUnavailableError) as caught:
        store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
    assert "PRIVATE-SENTINEL" not in str(caught.value)


def test_partial_reads_cannot_hide_trailing_bytes(tmp_path: Path) -> None:
    """A short OS read is not EOF; trailing invalid bytes must still be checked."""
    assert tmp_path.resolve() == tmp_path
    store = HerdrRestoreStore(state_root=tmp_path)
    saved = store.save(config=config_for(tmp_path))
    path = tmp_path / "restore-v1" / f"{saved.restore_reference}.json"
    size = path.stat().st_size
    with path.open("ab") as stream:
        stream.write(b"PRIVATE-SENTINEL")
    original = os.read

    def short_read(fd: int, count: int) -> bytes:
        """Bound the first read at the valid JSON boundary."""
        return original(fd, min(count, size))

    with patch("src.agents.slo_agent.herdr.restore.os.read", side_effect=short_read):
        with pytest.raises(HerdrRestoreUnavailableError):
            store.load(restore_reference=saved.restore_reference, session_id=SESSION_ID)
