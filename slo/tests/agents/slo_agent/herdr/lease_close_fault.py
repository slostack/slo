"""Exact temp-owned descriptor faults shared by pane and restore cleanup tests."""

import errno
import os
from pathlib import Path

from src.agents.slo_agent.herdr.sequence_store import HerdrFileLease


class LeaseCloseFault:
    """Inject one ambiguous close; retain independent test-only teardown authority."""

    def __init__(self, *, lease: HerdrFileLease, root: Path, case: str) -> None:
        """Capture an acquired test lease and original syscalls before patching."""
        assert lease._fd is not None
        self.fd = lease._fd
        self.root = root.resolve(strict=True)
        self.case = case
        self.close_calls = 0
        self.real_close = os.close
        self.real_stat = os.fstat
        self.open = True
        self.identity = self.real_stat(self.fd)
        self.lease = lease

    def close(self, fd: int) -> None:
        """Fail only the owned slot; released/reused cases model post-release errors."""
        if fd != self.fd:
            self.real_close(fd)
            return
        self.close_calls += 1
        if self.case in ("released", "reused", "same_inode", "ebadf"):
            self.real_close(fd)
            self.open = False
        if self.case in ("reused", "same_inode"):
            path = self.root / "replacement"
            if self.case == "same_inode":
                path = next(
                    path for path in self.root.rglob("*.lock") if path.stat().st_ino == self.identity.st_ino
                )
            assert path.resolve().is_relative_to(self.root) and not path.is_symlink()
            replacement = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            assert replacement == fd
            self.open = True
        raise OSError(errno.EBADF if self.case == "ebadf" else errno.EIO, "private-close-sentinel")

    def inspect(self, fd: int) -> os.stat_result:
        """Inspection failure proves neither absence nor ownership of a generation."""
        if fd == self.fd and self.case == "inspection" and self.close_calls:
            raise OSError(errno.EIO, "private-inspection-sentinel")
        return self.real_stat(fd)

    def finish(self) -> None:
        """Close only the fixture-known live generation after all product assertions."""
        if self.open:
            self.real_close(self.fd)
            self.open = False
        self.lease.close()
