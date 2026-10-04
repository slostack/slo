"""Regression contracts for parent-process containment teardown."""

import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest

from tests.agents.slo_agent.orchestrator.capture_test_safety import CaptureLaunchContainment


@pytest.mark.parametrize("fail_inside_scope", [False, True])
def test_reporter_guards_restore_after_each_use(tmp_path: Path, fail_inside_scope: bool) -> None:
    """Keep all guards active, then restore every global even on exceptional teardown."""
    original = (
        subprocess.Popen,
        asyncio.create_subprocess_exec,
        socket.create_connection,
        socket.socket.connect,
        socket.socket.connect_ex,
        os.devnull,
    )
    for _ in range(2):
        try:
            with pytest.MonkeyPatch.context() as patch:
                CaptureLaunchContainment.install_reporter_bootstrap(
                    root=tmp_path.resolve(), monkeypatch=patch
                )
                with pytest.raises(AssertionError, match="unexpected writer child"):
                    subprocess.Popen(["unapproved"])
                with pytest.raises(AssertionError, match="blocked external network"):
                    socket.create_connection(("127.0.0.1", 1))
                assert asyncio.create_subprocess_exec != original[1]
                assert socket.socket.connect != original[3]
                assert socket.socket.connect_ex != original[4]
                if fail_inside_scope:
                    raise RuntimeError("synthetic teardown")
        except RuntimeError as error:
            assert str(error) == "synthetic teardown"
        assert (
            subprocess.Popen,
            asyncio.create_subprocess_exec,
            socket.create_connection,
            socket.socket.connect,
            socket.socket.connect_ex,
            os.devnull,
        ) == original
