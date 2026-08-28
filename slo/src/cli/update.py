"""slo self-updater — reinstall slo via pipx straight from the git repository.

``slo update`` reinstalls the pipx-managed slo install from the repo:

* default: pin to the latest published release tag (``vX.Y.Z``),
* ``--development``: track ``main``,
* ``--ref <ref>``: install an explicit branch / tag / commit.

This mirrors ``install.sh`` exactly — both reinstall via
``pipx install --force "git+<url>@<ref>#subdirectory=slo"`` — so install and
update share one mechanism. The repo identity and layout below are kept in sync
with ``SLO_REPO_URL`` / ``SLO_REPO_SUBDIR`` in ``install.sh``.

Stdlib-only on purpose: no third-party imports, so the logic stays usable from
minimal contexts and matches ``install.sh``'s constraints.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import ClassVar, Optional

from config.cfg import cfg as _cfg

__all__ = ["Updater", "main"]


class Updater:
    """Reinstall slo via pipx straight from the git repo.

    :meth:`invoke` is the single entry point shared by the ``slo update`` CLI
    command. It resolves a git ref (latest release, ``main``, or an explicit
    ref), builds the pip VCS requirement, and reinstalls with ``pipx install
    --force`` — replacing the pipx venv in place and leaving ``SLO_HOME``
    (runtime data) untouched.
    """

    # ---- Repository identity (keep in sync with install.sh) ----------------
    REPO_URL: ClassVar[str] = "https://gitlab.com/core-27/slo.git"
    REPO_SUBDIR: ClassVar[str] = "slo"  # the project lives in slo/, not the repo root
    PYTHON_VERSION: ClassVar[str] = "3.11.7"

    # Matches release tags like ``v0.3.2`` / ``1.2.10`` (3-part semver, optional v).
    _VERSION_TAG_RE: ClassVar[re.Pattern[str]] = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

    @classmethod
    def invoke(cls, *, development: bool = False, ref: Optional[str] = None) -> None:
        """Reinstall slo via pipx at the resolved git ref.

        Args:
            development: When ``True``, track ``main``. Ignored when ``ref`` is
                given.
            ref: Explicit branch / tag / commit to install. Overrides both
                ``development`` and the default latest-release resolution.
        """
        target = ref or ("main" if development else cls.resolve_latest_release_tag())
        cls._pipx_install(spec=cls._pipx_spec(ref=target))

    @classmethod
    def resolve_latest_release_tag(cls) -> str:
        """Return the highest ``vX.Y.Z`` tag published on the remote.

        Uses ``git ls-remote --tags`` against the public repository, with no
        separate release-API call.

        Returns:
            The latest release tag (e.g. ``v0.3.2``).

        Raises:
            SystemExit: When the remote exposes no ``vX.Y.Z`` tags.
        """
        completed = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", cls.REPO_URL],
            check=True,
            text=True,
            capture_output=True,
        )
        versions: list[tuple[tuple[int, int, int], str]] = []
        for line in completed.stdout.splitlines():
            tag = line.rsplit("refs/tags/", 1)[-1].strip()
            if (match := cls._VERSION_TAG_RE.match(tag)) is not None:
                versions.append(((int(match[1]), int(match[2]), int(match[3])), tag))
        if not versions:
            raise SystemExit(
                f"slo update: no vX.Y.Z release tags found on {cls.REPO_URL}. "
                "Use --development to track main, or --ref to pin a branch/tag/commit."
            )
        versions.sort()
        return versions[-1][1]

    @classmethod
    def _pipx_spec(cls, *, ref: str) -> str:
        """Build the public pip VCS requirement ``git+<url>@<ref>#subdirectory=<subdir>``.

        Args:
            ref: The git ref to install.

        Returns:
            The pip requirement string passed to ``pipx install``.
        """
        spec = f"git+{cls.REPO_URL}@{ref}"
        if cls.REPO_SUBDIR:
            spec += f"#subdirectory={cls.REPO_SUBDIR}"
        return spec

    @classmethod

    @classmethod
    def _pipx_install(cls, *, spec: str) -> None:
        """Run ``pipx install --force`` for ``spec``, working around a broken uv shim.

        pipx auto-selects a uv backend whenever any ``uv`` is on PATH but never
        checks it runs; a stale pyenv ``uv`` shim then aborts the install. Force
        the pip backend when uv is present but not runnable, unless the caller
        already pinned ``PIPX_DEFAULT_BACKEND``.

        After a successful install, checks that ``~/.local/bin`` is on PATH and
        warns the user if it is not.

        Args:
            spec: The pip VCS requirement to install.
        """
        env = dict(os.environ)
        if "PIPX_DEFAULT_BACKEND" not in env and cls._uv_present_but_broken():
            env["PIPX_DEFAULT_BACKEND"] = "pip"
        subprocess.run(
            ["pipx", "install", "--force", "--python", cls._python_bin(), spec],
            check=True,
            env=env,
        )
        cls._check_path_after_install()

    @classmethod
    def _check_path_after_install(cls) -> None:
        """Warn on stderr when ``~/.local/bin`` is absent from the current PATH.

        Silent when ``~/.local/bin`` is already present — the common case after
        a clean install or when the user has already configured their shell.  When
        missing, prints a clear, actionable suggestion so the user knows exactly
        what to do without consulting documentation.
        """
        local_bin = str(Path.home() / ".local" / "bin")
        current_path = os.environ.get("PATH", "")
        path_entries = current_path.split(os.pathsep)
        if local_bin in path_entries:
            return
        print(
            "⚠ ~/.local/bin is not on your PATH.\n"
            "Add it to your shell config and restart your shell:\n"
            "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.zshrc\n"
            "Or run: pipx ensurepath",
            file=sys.stderr,
        )

    @classmethod
    def _python_bin(cls) -> str:
        """Resolve the concrete pinned interpreter to hand pipx.

        Mirrors install.sh: the bare ``python3.11`` pyenv shim only resolves when
        the pinned version is the *active* pyenv version (usually it is not — the
        active version is whatever virtualenv the shell is in), so prefer the real
        binary under pyenv's versions dir, then a PATH ``python3.11``, then the
        running interpreter.

        Returns:
            A path or name pipx can build a venv from.
        """
        root = _cfg("PYENV_ROOT") or cls._pyenv_root()
        if root:
            candidate = Path(root) / "versions" / cls._python_version() / "bin" / "python3.11"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        if (found := shutil.which("python3.11")) is not None:
            return found
        return sys.executable

    @classmethod
    def _python_version(cls) -> str:
        """Return the pinned Python version, honouring ``SLO_PYTHON_VERSION``.

        Returns:
            The version string (e.g. ``3.11.7``).
        """
        return _cfg("SLO_PYTHON_VERSION") or cls.PYTHON_VERSION

    @staticmethod
    def _pyenv_root() -> Optional[str]:
        """Return ``pyenv root`` output, or ``None`` when pyenv is absent / fails.

        Returns:
            The pyenv root path, or ``None``.
        """
        if shutil.which("pyenv") is None:
            return None
        try:
            completed = subprocess.run(["pyenv", "root"], check=True, text=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            return None
        return completed.stdout.strip() or None

    @staticmethod
    def _uv_present_but_broken() -> bool:
        """Return ``True`` when ``uv`` is on PATH but does not run.

        Returns:
            ``True`` if a ``uv`` exists on PATH but ``uv --version`` fails (e.g.
            a stale pyenv shim), so pipx should fall back to the pip backend.
        """
        if shutil.which("uv") is None:
            return False
        try:
            completed = subprocess.run(["uv", "--version"], check=False, text=True, capture_output=True)
        except OSError:
            return True
        return completed.returncode != 0


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for the standalone ``python -m src.cli.update`` path.

    Args:
        argv: Argument vector for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` on success).
    """
    parser = argparse.ArgumentParser(prog="slo update", description="Reinstall slo via pipx.")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--development",
        action="store_true",
        help="track main instead of pinning to the latest release",
    )
    selector.add_argument(
        "--ref",
        default=None,
        help="install an explicit branch / tag / commit",
    )
    namespace = parser.parse_args(argv)
    Updater.invoke(development=namespace.development, ref=namespace.ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
