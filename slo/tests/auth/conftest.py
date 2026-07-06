"""Shared fixtures for auth-module tests (06.a).

Currently exposes one fixture, ``free_port``, used by tests that need a
real but currently-unbound TCP port (for example, fixed-bind tests that
do not want to hard-code Codex's production port 1455 and risk
colliding with a real Slo sign-in on the developer's machine).
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture
def free_port() -> int:
    """Return a TCP port that is free at the moment of the call.

    Opens an ephemeral socket on ``127.0.0.1:0``, reads the port the OS
    picked, and closes the socket immediately. The port is then almost
    always still free when the test binds it a few microseconds later;
    there is a tiny race window, but it is acceptable for unit tests
    that bind the port in the very next statement.

    Returns:
        int: A port number that was free when the fixture ran.
    """
    sock: socket.socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    finally:
        sock.close()
    return port
