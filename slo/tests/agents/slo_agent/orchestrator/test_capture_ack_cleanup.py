"""Real owned writer cleanup at rejected startup acknowledgements."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import cast

import pytest

from src.agents.slo_agent.orchestrator import spawn_env


@pytest.mark.parametrize("acknowledgement", ["eof", "malformed", "timeout"])
def test_rejected_ack_reaps_owned_writer_without_synchronous_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acknowledgement: str
) -> None:
    """Reject each ACK shape, close input, and reap the actual finite writer off-thread."""
    root = tmp_path.resolve()
    script = root / "rejected_writer.py"
    assert script.resolve(strict=False).is_relative_to(root)
    assert (root / "capture/stdout.jsonl").resolve(strict=False).is_relative_to(root)
    script.write_text(
        "import os\n"
        "fd = int(os.environ['SLO_CAPTURE_WRITER_ACK_FD'])\n"
        + ("os.close(fd)\n" if acknowledgement == "eof" else "")
        + ("os.write(fd, b'wrong\\n')\n" if acknowledgement == "malformed" else "")
        + "while os.read(0, 65536): pass\n",
        encoding="utf-8",
    )
    original_popen = subprocess.Popen
    writers: list[subprocess.Popen[bytes]] = []
    waits: list[tuple[int, float | None]] = []
    reaped = threading.Event()
    caller_thread = threading.get_ident()

    def spawn(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        """Retain production FDs and track waits on exactly the owned writer."""
        argv = list(cast(list[str], args[0]))
        argv[-1] = str(script)
        process = original_popen(argv, **kwargs)  # type: ignore[call-overload]
        original_wait = process.wait

        def wait(timeout: float | None = None) -> int:
            """Observe reaping without changing its actual subprocess behavior."""
            waits.append((threading.get_ident(), timeout))
            result = original_wait(timeout=timeout)
            reaped.set()
            return result

        monkeypatch.setattr(process, "wait", wait)
        writers.append(process)
        return process

    monkeypatch.setattr(spawn_env.subprocess, "Popen", spawn)
    monkeypatch.setattr(spawn_env, "_CAPTURE_WRITER_STARTUP_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(OSError, match="^capture writer did not acknowledge startup$"):
        spawn_env.open_capture_file_append(
            history_root=root,
            session_id="capture",
            name="stdout.jsonl",
            credential="synthetic-ack-cleanup-unique-secret",
        )
    assert len(writers) == 1
    assert reaped.wait(timeout=5)
    assert writers[0].returncode == 0
    assert waits
    assert all(thread_id != caller_thread for thread_id, _ in waits)
    assert (root / "capture/stdout.jsonl").read_bytes() == b""
