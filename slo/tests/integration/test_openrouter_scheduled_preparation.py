"""Filesystem containment fixture shared by OpenRouter acceptance compositions."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def contained_writes(tmp_path: Path) -> Iterator[list[Path]]:
    """Reject filesystem mutation outside this test's resolved root before I/O.

    The audit hook remains installed but becomes inert after fixture teardown.
    This is scoped to the in-process inbox test; it is not a subprocess sandbox.
    """
    root = tmp_path.resolve()
    active = True
    writes: list[Path] = []

    def audit(event: str, args: tuple[object, ...]) -> None:
        """Check actual write targets, including symlink and descriptor resolution."""
        if not active:
            return
        targets: tuple[object, ...] = ()
        if event == "open" and isinstance(args[2], int):
            if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                targets = args[:1]
        if event in {"os.mkdir", "os.chmod", "os.remove", "os.rmdir"}:
            targets = args[:1]
        if event == "os.rename":
            targets = args[:2]
        for target in targets:
            path = Path(f"/proc/self/fd/{target}") if isinstance(target, int) else Path(str(target))
            resolved = path.resolve()
            assert resolved.is_relative_to(root), f"write outside owned root: {resolved}"
            writes.append(resolved)
        assert event not in {"subprocess.Popen", "os.system", "socket.connect"}, event

    sys.addaudithook(audit)
    try:
        yield writes
    finally:
        active = False
