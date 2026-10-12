"""slo self-updater — reinstall slo via pipx straight from the git repository.

``slo update`` reinstalls the pipx-managed slo install from the repo:

* default: pin to the latest published release tag (``vX.Y.Z``),
* ``--development``: track ``main``,
* ``--ref <ref>``: install an explicit branch / tag / commit.

This mirrors ``install.sh`` exactly — both reinstall via
``pipx install --force "git+<url>@<ref>#subdirectory=slo"`` — so install and
update share one mechanism. The repo identity and layout below are kept in sync
with ``SLO_REPO_URL`` / ``SLO_REPO_SUBDIR`` in ``install.sh``.

After the reinstall, :class:`ShellEnvironmentDefaults` first invokes the
just-installed ``install.sh --finalize-launcher`` so its generated user launcher
is hardened, then conditionally sets missing ``SLO_HOME`` / ``SLO_SKILLS_DIR`` /
``SLO_KB_DIR`` defaults. ``install.sh`` stays the only launcher and shell-state
writer; variables that already exist are never touched.

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
from typing import ClassVar, Mapping, Optional

from config.cfg import cfg as _cfg

__all__ = ["ShellEnvironmentDefaults", "Updater", "main"]


class Updater:
    """Reinstall slo via pipx straight from the git repo.

    :meth:`invoke` is the single entry point shared by the ``slo update`` CLI
    command. It resolves a git ref (latest release, ``main``, or an explicit
    ref), builds the pip VCS requirement, and reinstalls with ``pipx install
    --force`` — replacing the pipx venv in place and leaving ``SLO_HOME``
    (runtime data) untouched. It then sets any missing environment defaults
    through :class:`ShellEnvironmentDefaults`.
    """

    # ---- Repository identity (keep in sync with install.sh) ----------------
    REPO_URL: ClassVar[str] = "https://gitlab.com/core-27/slo.git"
    FALLBACK_REPO_URL: ClassVar[str] = "https://github.com/slostack/slo.git"
    REMOTE_TIMEOUT_SECONDS: ClassVar[int] = 30
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
        cls._install_with_fallback(ref=target)
        ShellEnvironmentDefaults.finalize_launcher()
        ShellEnvironmentDefaults.ensure(environ=os.environ)

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
        repo_url = cls._repo_url()
        try:
            completed = cls._ls_remote(repo_url=repo_url, tags=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            fallback = cls._fallback_repo_url()
            if not fallback:
                raise
            cls._announce_fallback()
            repo_url = fallback
            completed = cls._ls_remote(repo_url=repo_url, tags=True)
        return cls._latest_release_tag(output=completed.stdout, repo_url=repo_url)

    @classmethod
    def _latest_release_tag(cls, *, output: str, repo_url: str) -> str:
        """Select the highest numeric release from a reachable repository's tags.

        Args:
            output: Git ls-remote tag output.
            repo_url: Source used for the no-release diagnostic.

        Returns:
            The highest release tag.

        Raises:
            SystemExit: The reachable repository has no release tags.
        """
        versions: list[tuple[tuple[int, int, int], str]] = []
        for line in output.splitlines():
            tag = line.rsplit("refs/tags/", 1)[-1].strip()
            if (match := cls._VERSION_TAG_RE.match(tag)) is not None:
                versions.append(((int(match[1]), int(match[2]), int(match[3])), tag))
        if not versions:
            raise SystemExit(
                f"slo update: no vX.Y.Z release tags found on {repo_url}. "
                "Use --development to track main, or --ref to pin a branch/tag/commit."
            )
        versions.sort()
        return versions[-1][1]

    @classmethod
    def _pipx_spec(cls, *, ref: str, repo_url: Optional[str] = None) -> str:
        """Build the public pip VCS requirement ``git+<url>@<ref>#subdirectory=<subdir>``.

        Args:
            ref: The git ref to install.
            repo_url: Selected repository; defaults to the configured primary.

        Returns:
            The pip requirement string passed to ``pipx install``.
        """
        spec = f"git+{repo_url or cls._repo_url()}@{ref}"
        if cls.REPO_SUBDIR:
            spec += f"#subdirectory={cls.REPO_SUBDIR}"
        return spec

    @classmethod
    def _repo_url(cls) -> str:
        """Return the primary repository configured for this update."""
        return os.environ.get("SLO_REPO_URL") or cls.REPO_URL

    @classmethod
    def _fallback_repo_url(cls) -> str:
        """Return the mirror, without substituting Slo for an unrelated custom repo.

        An explicitly empty SLO_REPO_FALLBACK_URL disables fallback. Custom
        primaries require an explicit mirror URL; identical URLs disable retries.
        """
        default = cls.FALLBACK_REPO_URL if cls._repo_url() == cls.REPO_URL else ""
        fallback = os.environ.get("SLO_REPO_FALLBACK_URL", default)
        return fallback if fallback != cls._repo_url() else ""

    @classmethod
    def _install_with_fallback(cls, *, ref: str) -> None:
        """Retry the same ref on the mirror only if the primary is inaccessible.

        Args:
            ref: Resolved branch, tag or commit, unchanged across attempts.

        Raises:
            subprocess.CalledProcessError: Installation fails, or both sources fail.
            OSError: A required local executable is unavailable.
        """
        try:
            cls._pipx_install(spec=cls._pipx_spec(ref=ref))
        except subprocess.CalledProcessError:
            fallback = cls._fallback_repo_url()
            if not fallback or cls._remote_available(repo_url=cls._repo_url()):
                raise
            cls._announce_fallback()
            cls._pipx_install(spec=cls._pipx_spec(ref=ref, repo_url=fallback))

    @classmethod
    def _remote_available(cls, *, repo_url: str) -> bool:
        """Probe the primary after pipx fails, excluding ordinary build failures.

        Args:
            repo_url: Repository whose accessibility is checked.

        Returns:
            Whether git can read the remote refs within the bounded wait.
        """
        try:
            cls._ls_remote(repo_url=repo_url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        return True

    @classmethod
    def _ls_remote(cls, *, repo_url: str, tags: bool = False) -> subprocess.CompletedProcess[str]:
        """Read remote refs without prompting, with a bounded transport wait.

        Args:
            repo_url: Primary or mirror URL, never populated with a token.
            tags: Read release tags rather than all refs.

        Returns:
            Successful git output.

        Raises:
            subprocess.CalledProcessError: The repository is inaccessible.
            subprocess.TimeoutExpired: Git exceeds the probe deadline.
            OSError: Git cannot be started.
        """
        options = ["--tags", "--refs"] if tags else []
        return subprocess.run(
            args=["git", "ls-remote", *options, repo_url],
            check=True,
            text=True,
            capture_output=True,
            timeout=cls.REMOTE_TIMEOUT_SECONDS,
            env=cls._git_environment(),
        )

    @staticmethod
    def _git_environment() -> dict[str, str]:
        """Keep existing Git auth, but prevent interactive and stalled HTTP fetches.

        The same environment reaches pipx's git subprocesses. No API token is
        read, embedded in a URL, or persisted by the updater.
        """
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1")
        env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "30")
        return env

    @staticmethod
    def _announce_fallback() -> None:
        """Report a source switch without printing potentially sensitive URLs."""
        print("slo update: primary repository inaccessible; trying the mirror.", file=sys.stderr)

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
        env = cls._git_environment()
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


class ShellEnvironmentDefaults:
    """Set missing Slo environment defaults after ``slo update`` reinstalls the package.

    Only variables that do not exist are set: when ``SLO_HOME``,
    ``SLO_SKILLS_DIR``, and ``SLO_KB_DIR`` (or its ``KB_DIR`` fallback) all
    exist, shell files are left untouched. Otherwise the just-installed
    ``install.sh --finalize-environment`` writes the managed environment file
    and profile source blocks, whose lines themselves only fill unset
    variables. An existing ``SLO_SKILLS_DIR`` is never rewritten, but a stale
    one is reported so the user can fix their own export.
    """

    # Each required variable and the names that satisfy it, in precedence order.
    REQUIRED: ClassVar[dict[str, tuple[str, ...]]] = {
        "SLO_HOME": ("SLO_HOME",),
        "SLO_SKILLS_DIR": ("SLO_SKILLS_DIR",),
        "SLO_KB_DIR": ("SLO_KB_DIR", "KB_DIR"),
    }

    @classmethod
    def finalize_launcher(cls) -> None:
        """Run the installed launcher-only finalizer after pipx regeneration.

        Raises:
            SystemExit: If the installed package metadata or finalizer cannot be used.
        """
        location: Optional[Path] = cls.installed_location()
        failure_prefix: str = "slo code was updated, but its launcher was not finalized"
        if location is None:
            raise SystemExit(
                f"{failure_prefix}: 'pipx runpip slo show slo' did not report the installed location. "
                "Re-run the matching tagged public installer."
            )
        installer: Path = location / "install.sh"
        if installer.is_symlink() or not installer.is_file():
            raise SystemExit(
                f"{failure_prefix}: {installer} is unavailable. Re-run the matching tagged public installer."
            )
        try:
            subprocess.run(
                [shutil.which("bash") or "bash", str(installer), "--finalize-launcher"],
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit(
                f"{failure_prefix} ({error}). Re-run the matching tagged public installer."
            ) from error

    @classmethod
    def ensure(cls, *, environ: Mapping[str, str]) -> None:
        """Set missing defaults via the installed ``install.sh``, then report a stale skills path.

        Args:
            environ: The environment ``slo update`` runs in.

        Raises:
            SystemExit: When a default is missing and the installed package or
                its installer cannot be found or fails. The package itself is
                already updated at that point, and the message says so.
        """
        location = cls.installed_location()
        missing = cls.missing(environ=environ)
        if missing:
            cls._finalize(location=location, missing=missing)
        else:
            print(
                "slo update: SLO_HOME, SLO_SKILLS_DIR and SLO_KB_DIR are already set; "
                "shell environment left unchanged.",
                file=sys.stderr,
            )
        cls._report_skills_dir(environ=environ, location=location)

    @classmethod
    def missing(cls, *, environ: Mapping[str, str]) -> list[str]:
        """Return the required variables that do not exist (set-but-empty counts as existing).

        Args:
            environ: The environment to inspect.

        Returns:
            The missing variable names, in ``REQUIRED`` order.
        """
        return [
            name for name, accepted in cls.REQUIRED.items() if not any(key in environ for key in accepted)
        ]

    @staticmethod
    def installed_location() -> Optional[Path]:
        """Return the installed distribution ``Location`` from ``pipx runpip slo show slo``.

        Mirrors ``slo_resolve_vendored_skills_dir`` in ``install.sh``: pip
        metadata is the only source of truth, and the pipx layout is never guessed.

        Returns:
            The single reported ``Location``, or ``None`` when pipx fails or the
            metadata has no, or more than one, ``Location`` field.
        """
        try:
            completed = subprocess.run(
                ["pipx", "runpip", "slo", "show", "slo"],
                check=True,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        locations = [
            line.removeprefix("Location: ").strip()
            for line in completed.stdout.splitlines()
            if line.startswith("Location: ")
        ]
        return Path(locations[0]) if len(locations) == 1 else None

    @classmethod
    def _finalize(cls, *, location: Optional[Path], missing: list[str]) -> None:
        """Run the installed ``install.sh --finalize-environment``.

        Args:
            location: Installed distribution location, or ``None`` when unknown.
            missing: Variable names being defaulted, for the progress message.

        Raises:
            SystemExit: When the installer cannot be found or fails.
        """
        failure_prefix = "slo was updated, but its environment defaults could not be set"
        if location is None:
            raise SystemExit(
                f"{failure_prefix}: 'pipx runpip slo show slo' did not report the installed location. "
                "Re-run the public install.sh to set them."
            )
        installer = location / "install.sh"
        if not installer.is_file():
            raise SystemExit(
                f"{failure_prefix}: {installer} is missing. Re-run the public install.sh to set them."
            )
        print(f"slo update: setting missing Slo environment defaults: {', '.join(missing)}", file=sys.stderr)
        try:
            subprocess.run(
                [shutil.which("bash") or "bash", str(installer), "--finalize-environment"], check=True
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit(
                f"{failure_prefix} ({error}). Fix the issue above, then run: "
                f"bash {installer} --finalize-environment"
            ) from error
        print(
            "slo update: open a new shell (or source ~/.slo/shell/environment.sh) to pick them up.",
            file=sys.stderr,
        )

    @staticmethod
    def _report_skills_dir(*, environ: Mapping[str, str], location: Optional[Path]) -> None:
        """Warn when an existing ``SLO_SKILLS_DIR`` is broken or differs from the installed skills.

        Args:
            environ: The environment ``slo update`` runs in.
            location: Installed distribution location, or ``None`` when unknown.
        """
        if "SLO_SKILLS_DIR" not in environ:
            return
        configured = environ["SLO_SKILLS_DIR"]
        installed = location / "skills" if location is not None else None
        installed_text = str(installed) if installed is not None else "an unknown location"
        if not configured or not (Path(configured) / "INDEX.md").is_file():
            print(
                f"slo update: warning: SLO_SKILLS_DIR={configured!r} has no INDEX.md, so Slo cannot load "
                f"its skills. The installed skills are at {installed_text}. Update or remove that "
                "export in your shell profile.",
                file=sys.stderr,
            )
            return
        if installed is not None and os.path.realpath(configured) != os.path.realpath(installed):
            print(
                f"slo update: note: SLO_SKILLS_DIR points to {configured}, not the skills just installed "
                f"at {installed}. Slo will keep using {configured}.",
                file=sys.stderr,
            )


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
