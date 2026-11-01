"""Ambiguous close never grants authority to close a recycled descriptor."""

import errno
import os
from pathlib import Path

import pytest

from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease, HerdrSequenceUnavailableError


@pytest.mark.parametrize(argnames="disposition", argvalues=["held", "released", "reused", "inspection"])
def test_ambiguous_close_never_retries_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disposition: str
) -> None:
    """Inspect after failure without closing either the original or replacement slot."""
    lease = HerdrFileLease()
    path = tmp_path / "lock"
    assert path.resolve().is_relative_to(tmp_path.resolve())
    lease.acquire(path=path, create=True)
    fd = lease._fd
    assert fd is not None
    real_close, real_stat = os.close, os.fstat
    replacement: list[int] = []
    calls: list[int] = []

    def fail_close(handle: int) -> None:
        """A fault may precede or follow release; all descriptors are test-owned."""
        assert handle == fd
        calls.append(handle)
        if disposition in ("released", "reused"):
            real_close(handle)
        if disposition == "reused":
            target = tmp_path / "replacement"
            assert target.resolve().is_relative_to(tmp_path.resolve())
            replacement.append(os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
            assert replacement[0] == fd
        raise OSError(errno.EIO, "synthetic close")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(target=os, name="close", value=fail_close)
            with pytest.raises(OSError):
                lease.close()
            if disposition == "inspection":

                def fail_stat(handle: int) -> os.stat_result:
                    """Refuse inspection without assuming descriptor release."""
                    raise OSError(errno.EIO, "synthetic inspection")

                patch.setattr(target=os, name="fstat", value=fail_stat)
            if disposition in ("held", "inspection"):
                with pytest.raises((OSError, HerdrSequenceUnavailableError)):
                    lease.close()
                assert lease._fd == fd
            else:
                lease.close()
                assert lease._fd is None
            assert calls == [fd]
        if replacement:
            assert real_stat(replacement[0])
    finally:
        if disposition != "released":
            real_close(fd)
