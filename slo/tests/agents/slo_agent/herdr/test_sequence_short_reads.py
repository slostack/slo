"""Counter admission must consume EOF, not just a valid JSON prefix."""

import os
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrSequenceStore, HerdrSequenceUnavailableError


@pytest.mark.parametrize(argnames="case", argvalues=["valid", "suffix", "4096", "4097", "error"])
def test_short_reads_preserve_counter_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Read the complete bounded record; refusal never repairs or reserves corrupt bytes."""
    store = HerdrSequenceStore(state_root=tmp_path, socket_namespace="default", pane_id="pane")
    store.acquire()
    store.reserve(source="custom:slo")
    store.close()
    (path,) = (tmp_path / "sequence-v1").glob("*.json")
    valid = path.read_bytes()
    content = valid
    if case == "suffix":
        content += b"INVALID"
    if case in ("4096", "4097"):
        content += b" " * (int(case) - len(valid))
    assert path.resolve().is_relative_to(tmp_path.resolve()) and not path.is_symlink()
    path.write_bytes(content)
    real_read = os.read
    reads = 0

    def short_read(fd: int, size: int) -> bytes:
        """Expose a complete JSON prefix before suffix, EOF or a subsequent error."""
        nonlocal reads
        reads += 1
        if case == "error" and reads > 1:
            raise OSError("synthetic read error")
        return real_read(fd, min(size, len(valid)))

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="read", value=short_read)
            if case in ("suffix", "4097", "error"):
                with pytest.raises(HerdrSequenceUnavailableError):
                    store.acquire()
                with pytest.raises(HerdrSequenceUnavailableError):
                    store.reserve(source="custom:slo")
            else:
                store.acquire()
                assert reads > 1
        assert path.read_bytes() == content
    finally:
        store.close()
