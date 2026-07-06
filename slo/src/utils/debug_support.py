"""Interactive debugging helpers shared across CLI entry points."""
from __future__ import annotations

import sys

from config.cfg import DEBUGPY, DEBUGPY_PORT


def maybe_start_debugpy() -> None:
    """Start a debugpy attach server when ``SLO_DEBUGPY`` is set.

    The interactive TUI owns the terminal (raw mode + alternate screen), so an
    in-terminal ``pdb``/``breakpoint()`` prompt is invisible and unusable.
    debugpy exposes the debugger over a TCP socket instead, letting VSCode
    attach and honour gutter breakpoints while Textual keeps the screen.

    debugpy is a dev-only dependency; the import is deferred so production
    installs (which omit the dev group) never touch it. Blocks until a client
    attaches so breakpoints set before the run are honoured.

    Environment:
        SLO_DEBUGPY: When set to any value, enables the attach server.
        SLO_DEBUGPY_PORT: Optional listen port (defaults to ``5678``).

    Returns:
        None: Returns immediately when ``SLO_DEBUGPY`` is unset.
    """
    if DEBUGPY is None:
        return
    import debugpy

    host: str = "127.0.0.1"
    port: int = DEBUGPY_PORT
    debugpy.listen((host, port))
    print(f"[debugpy] waiting for VSCode to attach on {host}:{port} ...", file=sys.stderr, flush=True)
    debugpy.wait_for_client()
    print("[debugpy] debugger attached; continuing.", file=sys.stderr, flush=True)
