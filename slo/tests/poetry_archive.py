"""Build real poetry archives from a copied source tree in any suite interpreter.

Archive-building tests copy the checkout's ``src``/``config`` into a
disposable directory and drive the real ``poetry-core`` build backend there.
The pytest interpreter may be source-only: ``make test`` runs under the
ambient ``poetry run`` python, which carries the project's dependencies but
not the ``poetry-core`` build backend. The convention from
``tests/cli/test_wheel_contents.py`` applies — prefer the PATH-resolved
interpreter, which the ``poetry run`` environment points at the development
environment that carries the backend. No interpreter is ever modified.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_BACKEND_SCRIPT: str = "from poetry.core.masonry.api import {entries}; {calls}"


def _can_import_poetry_core(interpreter: str) -> bool:
    """Return whether an interpreter imports the poetry-core build backend.

    Args:
        interpreter (str): Absolute path of the candidate python.

    Returns:
        bool: True when ``import poetry.core`` succeeds in that interpreter.
    """
    probe: subprocess.CompletedProcess[bytes] = subprocess.run(
        args=[interpreter, "-c", "import poetry.core"],
        capture_output=True,
        timeout=30,
    )
    return probe.returncode == 0


def archive_builder_python() -> str:
    """Return an interpreter that can import poetry.core, preferring sys.executable.

    Returns:
        str: Absolute path of the chosen builder interpreter.

    Raises:
        RuntimeError: When no candidate interpreter carries the backend.
    """
    candidates: list[str] = [sys.executable]
    for name in ("python3.11", "python3", "python"):
        found: str | None = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if _can_import_poetry_core(interpreter=candidate):
            return candidate
    raise RuntimeError(
        "no interpreter with the poetry-core build backend found "
        f"(tried: {', '.join(dict.fromkeys(candidates))})"
    )


def build_archives(*, source: Path, formats: Sequence[str], timeout: float | None = None) -> list[Path]:
    """Build the wheel and/or sdist of a copied source tree, returning paths.

    Args:
        source (Path): Directory holding the copied ``src``/``config`` and
            ``pyproject.toml`` to archive.
        formats (Sequence[str]): Formats to build; ``wheel`` and/or ``sdist``.
        timeout (float | None): Subprocess timeout in seconds; ``None`` waits.

    Returns:
        list[Path]: The built archives inside ``source/dist``.
    """
    builder: str = archive_builder_python()
    entries: list[str] = []
    calls: list[str] = []
    if "wheel" in formats:
        entries.append("build_wheel")
        calls.append("build_wheel('dist')")
    if "sdist" in formats:
        entries.append("build_sdist")
        calls.append("build_sdist('dist')")
    subprocess.run(
        args=[builder, "-c", _BACKEND_SCRIPT.format(entries=", ".join(entries), calls="; ".join(calls))],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return sorted((source / "dist").glob("*"))
