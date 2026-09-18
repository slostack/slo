"""Focused process-PTY checks for the 79.b.2 Textual capture harness."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.characterization.textual_pty import PtyChildTimeoutError, TextualPtyCapture

_STARTUP_MARKER: bytes = b"\x1b[?1049h"


def _unpatched_cli_command() -> tuple[str, ...]:
    """Return the current-worktree command that enters Slo without a test bootstrap.

    Returns:
        tuple[str, ...]: Interpreter and module invocation for the unpatched CLI boundary.
    """
    return (sys.executable, "-m", "src.cli")


async def test_unpatched_cli_subprocess_pty_writes_input_and_captures_pyte_state(tmp_path: Path) -> None:
    """Prove the harness drives and captures an unpatched CLI-owned Textual process.

    The visible startup marker proves the child entered the real CLI/application
    chain. Ctrl-C is written by the parent to the PTY master only after that
    marker arrives, so the normal exit also proves master input delivery.
    """
    capture = await TextualPtyCapture.invoke(
        command=_unpatched_cli_command(),
        cwd=Path.cwd(),
        environment={"SLO_HOME": str(tmp_path / "slo-home")},
        input_after_bytes=_STARTUP_MARKER,
        input_bytes=(b"\x03",),
        terminal_height=5,
        timeout_seconds=5.0,
    )

    assert capture.child.command == _unpatched_cli_command()
    assert capture.child.pid > 0
    assert capture.child.reaped is True
    assert capture.child.return_code == 0
    assert capture.written_input == b"\x03"
    assert _STARTUP_MARKER in capture.raw_bytes
    assert b"Resume this session: slo --resume" in capture.raw_bytes
    assert capture.raw.length == len(capture.raw_bytes)
    assert len(capture.raw.sha256) == 64
    assert capture.raw.base64
    assert any("Resume this session: slo --resume" in line for line in [*capture.frame, *capture.scrollback])
    assert 0 <= capture.cursor_column < 100
    assert 0 <= capture.cursor_row < 5


async def test_timeout_cleanup_terminates_and_reaps_unpatched_cli_child(tmp_path: Path) -> None:
    """Prove a bounded timeout leaves no unreaped unpatched CLI child behind."""
    with pytest.raises(PtyChildTimeoutError) as error:
        await TextualPtyCapture.invoke(
            command=_unpatched_cli_command(),
            cwd=Path.cwd(),
            environment={"SLO_HOME": str(tmp_path / "slo-home")},
            terminal_height=5,
            timeout_seconds=0.05,
        )

    assert error.value.child.reaped is True
    assert error.value.child.return_code is not None
    assert "raw_tail=" in str(error.value)
